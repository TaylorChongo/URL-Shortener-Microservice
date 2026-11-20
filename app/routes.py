import ipaddress
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
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
from app.models import URL, Click, User
from app.repositories import TagRepository, URLRepository, UserRepository, clean_tag_names
from app.schemas import (
    CityCount,
    CountryCount,
    DayClicks,
    ErrorResponse,
    IPAddressCount,
    ReferrerCount,
    ShortenRequest,
    StatsResponse,
    TagCount,
    TopURL,
    UserAgentCount,
    URLResponse,
    URLUpdate,
    UserCreate,
    UserRead,
    ValidationErrorResponse,
)
from app.security import hash_password
from app.services import AliasTakenError, UrlShortenerService, alias_is_available


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
    alias_url = None
    if url.custom_alias is not None:
        alias_url = f"{BASE_URL}/api/{url.custom_alias}"

    return URLResponse(
        id=url.id,
        short_code=url.short_code,
        short_url=f"{BASE_URL}/api/{url.short_code}",
        original_url=url.original_url,
        custom_alias=url.custom_alias,
        alias_url=alias_url,
        title=url.title,
        description=url.description,
        favicon=url.favicon,
        tags=[tag.name for tag in url.tags],
        click_count=url.click_count,
        is_active=url.is_active,
        expires_at=url.expires_at,
        created_at=url.created_at,
    )


ALIAS_TAKEN = {409: {"model": ErrorResponse, "description": "This custom alias is already used"}}

# how many rows each "clicks per ..." statistics list shows
TOP = 10


def hide_ip(ip_address) -> str:
    # The full IP stays in the database; stats only show part of it, to protect the visitor.
    # IPv4: 196.216.180.1 -> 196.216.180.xxx    IPv6: keep the first 4 groups only
    ip = ipaddress.ip_address(str(ip_address))
    if ip.version == 4:
        parts = str(ip).split(".")
        return ".".join(parts[:3]) + ".xxx"
    groups = ip.exploded.split(":")
    return ":".join(groups[:4]) + ":xxxx:xxxx:xxxx:xxxx"


def visitor_ip(request: Request) -> str:
    # the clicks.ip_address column only accepts real IP addresses,
    # so anything else (missing, or a name like "testclient") is saved as 0.0.0.0
    if request.client is None:
        return "0.0.0.0"
    try:
        ipaddress.ip_address(request.client.host)
    except ValueError:
        return "0.0.0.0"
    return request.client.host


@router.post(
    "/shorten",
    response_model=URLResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a short URL",
    description=(
        "Login required. Send a long URL and get back a unique 6-character short code and a "
        "ready-to-share short link. Optional: tags, a custom alias, a title, a description, a favicon "
        "and an expiry date. The link belongs to you."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "You are not logged in"},
        **ALIAS_TAKEN,
        422: {"model": ValidationErrorResponse, "description": "One of the fields is not valid"},
    },
)
def create_short_url(
    body: ShortenRequest,
    current_user: User = Depends(get_current_user),
    service: UrlShortenerService = Depends(get_shortener_service),
) -> URLResponse:
    details = body.model_dump(include={"custom_alias", "title", "description", "favicon", "expires_at"})
    try:
        url = service.shorten(
            user_id=current_user.id, original_url=str(body.url), tag_names=body.tags, details=details
        )
    except (AliasTakenError, IntegrityError):
        # IntegrityError: someone took the same alias at the same moment (the unique index refused it)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This custom alias is already used")
    return to_url_response(url)

@router.get(
    "/{code}",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
    summary="Redirect to the original URL",
    description=(
        "Looks up the short code (or custom alias), records the visit and redirects to the original URL. "
        "Open the short link in your browser's address bar to test it: "
        "Swagger's 'Try it out' cannot follow redirects to other websites."
    ),
    responses={
        302: {"description": "Redirects to the original URL"},
        404: {"model": ErrorResponse, "description": "No URL was found for this short code"},
        410: {"model": ErrorResponse, "description": "The link was switched off or has expired"},
        422: {"model": ValidationErrorResponse, "description": "The short code is not valid"},
    },
)
def redirect_to_url(
    code: str,
    request: Request,
    service: UrlShortenerService = Depends(get_shortener_service)
) -> RedirectResponse:
    url = service.find(code)
    if url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Short URL not found")
    if not url.is_active:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This short link has been switched off")
    if url.expires_at is not None and url.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This short link has expired")

    service.record_visit(
        url,
        ip_address=visitor_ip(request),
        user_agent=request.headers.get("user-agent", ""),
        referrer=request.headers.get("referer"),
    )
    return RedirectResponse(url=url.original_url, status_code=status.HTTP_302_FOUND)
    

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
    "/stats",
    response_model=StatsResponse,
    summary="Statistics about your URLs",
    description=(
        "Login required. Totals across all your links: how many links and clicks you have, "
        "your 5 most clicked links, clicks per day for the last 7 days, how many links use each tag, "
        "and the top 10 visitors' IP addresses (partly hidden), user agents, countries, cities and referrers."
    ),
    responses={**NOT_LOGGED_IN},
)
def get_stats(
    current_user: User = Depends(get_current_user),
    urls: URLRepository = Depends(get_url_repository),
) -> StatsResponse:
    user_id = current_user.id
    return StatsResponse(
        total_urls=urls.count_urls(user_id),
        total_clicks=urls.count_clicks(user_id),
        top_urls=[
            TopURL(short_code=row.short_code, original_url=row.original_url, clicks=row.clicks)
            for row in urls.top_urls(user_id, limit=5)
        ],
        clicks_last_7_days=[DayClicks(day=row.day, clicks=row.clicks) for row in urls.clicks_per_day(user_id, days=7)],
        urls_per_tag=[TagCount(tag=row.name, urls=row.urls) for row in urls.urls_per_tag(user_id)],
        clicks_per_ip_address=[
            IPAddressCount(ip_address=hide_ip(row.value), clicks=row.clicks)
            for row in urls.clicks_grouped_by(user_id, Click.ip_address, limit=TOP)
        ],
        clicks_per_user_agent=[
            UserAgentCount(user_agent=row.value or "Unknown", clicks=row.clicks)
            for row in urls.clicks_grouped_by(user_id, Click.user_agent, limit=TOP)
        ],
        clicks_per_country=[
            CountryCount(country=row.value or "Unknown", clicks=row.clicks)
            for row in urls.clicks_grouped_by(user_id, Click.country, limit=TOP)
        ],
        clicks_per_city=[
            CityCount(city=row.city or "Unknown", country=row.country or "Unknown", clicks=row.clicks)
            for row in urls.clicks_per_city(user_id, limit=TOP)
        ],
        clicks_per_referrer=[
            ReferrerCount(referrer=row.value or "Direct", clicks=row.clicks)
            for row in urls.clicks_grouped_by(user_id, Click.referrer, limit=TOP)
        ],
    )


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
    description=(
        "Login required. Send only what you want to change. Leave a field out to keep it. "
        "Send null to clear an optional field (custom_alias, title, description, favicon, expires_at). "
        "Send is_active false to switch the link off. "
        "If nothing you sent differs from the current values, the answer is 400."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Nothing was sent, or nothing would change"},
        **NOT_LOGGED_IN,
        **NOT_FOUND,
        **ALIAS_TAKEN,
    },
)
def update_url(
    url_id: int,
    body: URLUpdate,
    current_user: User = Depends(get_current_user),
    urls: URLRepository = Depends(get_url_repository),
    tags: TagRepository = Depends(get_tag_repository),
) -> URLResponse:
    url = get_own_url_or_404(urls, current_user, url_id)

    if not body.model_fields_set:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Send at least one field to update")

    # only the fields the user actually sent (exclude_unset), e.g. {"title": "New", "expires_at": None}
    sent = body.model_dump(exclude_unset=True, exclude={"url", "tags"})
    if "url" in body.model_fields_set:
        sent["original_url"] = str(body.url)

    # keep only the fields whose value really differs from what is stored now
    changes = {}
    for field_name, value in sent.items():
        if getattr(url, field_name) != value:
            changes[field_name] = value

    # tags: compare the tidied names, in any order
    tags_changed = False
    if "tags" in body.model_fields_set:
        current_names = sorted(tag.name for tag in url.tags)
        tags_changed = sorted(clean_tag_names(body.tags)) != current_names

    if not changes and not tags_changed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nothing to update: the values you sent are the same as the current ones",
        )

    new_alias = changes.get("custom_alias")
    if new_alias is not None and not alias_is_available(urls, new_alias):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This custom alias is already used")

    new_tags = None
    if tags_changed:
        new_tags = tags.get_or_create(body.tags)

    try:
        url = urls.update(url, changes=changes, tags=new_tags)
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This custom alias is already used")
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
