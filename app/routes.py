from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError

from app.config import BASE_URL
from app.dependencies import get_shortener_service, get_user_repository
from app.repositories import UserRepository
from app.schemas import (
    ErrorResponse,
    ShortenRequest,
    ShortenResponse,
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


router = APIRouter(prefix="/api", tags=["shortener"])

@router.post(
    "/shorten",
    response_model=ShortenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a short URL",
    description="Send a long URL and get back a unique 6-character short code and a ready-to-share short link.",
    responses={422: {"model": ValidationErrorResponse, "description": "The URL is missing or not valid"}},
)
def create_short_url(
        body: ShortenRequest,
        service: UrlShortenerService = Depends(get_shortener_service)
) -> ShortenResponse:
    original_url = str(body.url)
    code = service.shorten(original_url)

    return ShortenResponse(
        short_code = code,
        short_url = f"{BASE_URL}/api/{code}",
        original_url = original_url
    )

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
    original_url = service.get_original_url(code)
    if original_url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Short URL not found")
    return RedirectResponse(url=original_url, status_code=status.HTTP_302_FOUND)
    