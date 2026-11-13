from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError

from app.config import BASE_URL
from app.dependencies import (
    get_current_user,
    get_shortener_service,
    get_tag_repository,
    get_url_repository,
    get_user_repository,
)
from app.models import URL, User
from app.repositories import TagRepository, URLRepository, UserRepository
from app.schemas import (
    ErrorResponse,
    ShortenRequest,
    URLResponse,
    URLUpdate,
    UserCreate,
    UserRead,
    ValidationErrorResponse,
)
from app.security import hash_password
from app.services import UrlShortenerService


auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
    description="Send an email and a password (8 to 72 characters). The password is stored hashed, never as plain text.",
    responses={
        409: {"model": ErrorResponse, "description": "This email is already registered"},
        422: {"model": ValidationErrorResponse, "description": "The email or password is not valid"},
    },
)
def register(
    body: UserCreate,
    users: UserRepository = Depends(get_user_repository),
) -> UserRead:
    email = body.email.lower()

    if users.get_by_email(email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")

    try:
        user = users.create(email=email, hashed_password=hash_password(body.password))
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")

    return user


@auth_router.post(
    "/login",
    response_model=UserRead,
    summary="Check your email and password",
    description=(
        "Uses HTTP Basic authentication. In Swagger, click the 'Authorize' button, "
        "enter your email as the username and your password, then call this endpoint."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "The email or password is incorrect"},
        403: {"model": ErrorResponse, "description": "The account is disabled"},
    },
)
def login(current_user: User = Depends(get_current_user)) -> UserRead:
    return current_user


router = APIRouter(prefix="/api", tags=["shortener"])


def to_url_response(url: URL) -> URLResponse:
    return URLResponse(
        id=url.id,
        short_code=url.short_code,
        short_url=f"{BASE_URL}/api/{url.short_code}",
        original_url=url.original_url,
        tags=[tag.name for tag in url.tags],
        created_at=url.created_at,
    )


@router.post(
    "/shorten",
    response_model=URLResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a short URL",
    description=(
        "Login required. Send a long URL (and optional tags) and get back a unique "
        "6-character short code and a ready-to-share short link. The link belongs to you."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "You are not logged in"},
        422: {"model": ValidationErrorResponse, "description": "The URL or tags are not valid"},
    },
)
def create_short_url(
    body: ShortenRequest,
    current_user: User = Depends(get_current_user),
    service: UrlShortenerService = Depends(get_shortener_service),
) -> URLResponse:
    url = service.shorten(user_id=current_user.id, original_url=str(body.url), tag_names=body.tags)
    return to_url_response(url)

@router.get(
    "/{code}",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
    summary="Redirect to the original URL",
    description=(
        "Looks up the short code and redirects to the original URL. "
        "Open the short link in your browser's address bar to test it: "
        "Swagger's 'Try it out' cannot follow redirects to other websites."
    ),
    responses={
        302: {"description": "Redirects to the original URL"},
        404: {"model": ErrorResponse, "description": "No URL was found for this short code"},
        422: {"model": ValidationErrorResponse, "description": "The short code is not valid"},
    },
)
def redirect_to_url(
    code: str,
    service: UrlShortenerService = Depends(get_shortener_service)
) -> RedirectResponse:
    original_url = service.open(code)
    if original_url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Short URL not found")
    return RedirectResponse(url=original_url, status_code=status.HTTP_302_FOUND)
    

urls_router = APIRouter(prefix="/api/urls", tags=["urls"])

NOT_FOUND = {404: {"model": ErrorResponse, "description": "No URL with this id belongs to you"}}
NOT_LOGGED_IN = {401: {"model": ErrorResponse, "description": "You are not logged in"}}


def get_own_url_or_404(urls: URLRepository, user: User, url_id: int) -> URL:
    url = urls.get_for_user(user_id=user.id, url_id=url_id)
    if url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")
    return url


@urls_router.get(
    "",
    response_model=list[URLResponse],
    summary="List your URLs",
    description="Login required. Returns only your own links, newest first, one page at a time.",
    responses={**NOT_LOGGED_IN},
)
def list_urls(
    limit: int = Query(default=20, ge=1, le=100, description="How many links per page"),
    offset: int = Query(default=0, ge=0, description="How many links to skip"),
    current_user: User = Depends(get_current_user),
    urls: URLRepository = Depends(get_url_repository),
) -> list[URLResponse]:
    page = urls.list_for_user(user_id=current_user.id, limit=limit, offset=offset)
    return [to_url_response(url) for url in page]


@urls_router.get(
    "/{url_id}",
    response_model=URLResponse,
    summary="Get one of your URLs",
    description="Login required. Returns 404 if the URL does not exist or is not yours.",
    responses={**NOT_LOGGED_IN, **NOT_FOUND},
)
def get_url(
    url_id: int,
    current_user: User = Depends(get_current_user),
    urls: URLRepository = Depends(get_url_repository),
) -> URLResponse:
    url = get_own_url_or_404(urls, current_user, url_id)
    return to_url_response(url)


@urls_router.patch(
    "/{url_id}",
    response_model=URLResponse,
    summary="Update one of your URLs",
    description="Login required. Send only what you want to change: the long URL, the tags, or both.",
    responses={**NOT_LOGGED_IN, **NOT_FOUND},
)
def update_url(
    url_id: int,
    body: URLUpdate,
    current_user: User = Depends(get_current_user),
    urls: URLRepository = Depends(get_url_repository),
    tags: TagRepository = Depends(get_tag_repository),
) -> URLResponse:
    url = get_own_url_or_404(urls, current_user, url_id)

    new_original_url = None
    if body.url is not None:
        new_original_url = str(body.url)

    new_tags = None
    if body.tags is not None:
        new_tags = tags.get_or_create(body.tags)

    url = urls.update(url, original_url=new_original_url, tags=new_tags)
    return to_url_response(url)


@urls_router.delete(
    "/{url_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one of your URLs",
    description="Login required. Its clicks and tag links are deleted too.",
    responses={**NOT_LOGGED_IN, **NOT_FOUND},
)
def delete_url(
    url_id: int,
    current_user: User = Depends(get_current_user),
    urls: URLRepository = Depends(get_url_repository),
) -> Response:
    url = get_own_url_or_404(urls, current_user, url_id)
    urls.delete(url)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
