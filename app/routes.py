import ipaddress
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError

from app.config import ACCESS_TOKEN_MINUTES, BASE_URL, LOGIN_RATE_LIMIT
from app.dependencies import (
    get_current_user,
    get_shortener_service,
    get_tag_repository,
    get_url_repository,
    get_user_repository,
    require_admin,
    require_premium,
)
from app.models import URL, Click, User
from app.rate_limit import limiter
from app.repositories import TagRepository, URLRepository, UserRepository, clean_tag_names
from app.schemas import (
    AccessTokenResponse,
    AdminUserUpdate,
    CityCount,
    CountryCount,
    DayClicks,
    ErrorResponse,
    IPAddressCount,
    LinkAnalyticsResponse,
    ReferrerCount,
    RefreshRequest,
    ShortenRequest,
    StatsResponse,
    TagCount,
    TokenResponse,
    TopURL,
    URLResponse,
    URLUpdate,
    UserAgentCount,
    UserCreate,
    UserRead,
    ValidationErrorResponse,
)
from app.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    hash_password,
    read_token,
    verify_password,
)
from app.services import (
    AliasTakenError,
    DuplicateURLError,
    TierLimitError,
    UrlShortenerService,
    alias_is_available,
    check_can_add_active_link,
    check_can_use_alias,
    is_live,
)

API_PREFIX = "/api/v1"

# how many rows each "clicks per ..." statistics list shows
TOP = 10

NOT_LOGGED_IN = {401: {"model": ErrorResponse, "description": "You are not logged in"}}
NOT_FOUND = {404: {"model": ErrorResponse, "description": "No link with this short code belongs to you"}}
CONFLICT = {409: {"model": ErrorResponse, "description": "This custom alias is already used, or you already shortened this URL"}}
TIER_LIMIT = {403: {"model": ErrorResponse, "description": "Free accounts: at most 10 active links, and no custom alias"}}


# ---------- helpers ----------

def short_link(code: str) -> str:
    # short links live at the root of the site: http://127.0.0.1:8000/aB3xY9
    return f"{BASE_URL}/{code}"


def to_url_response(url: URL) -> URLResponse:
    alias_url = None
    if url.custom_alias is not None:
        alias_url = short_link(url.custom_alias)

    return URLResponse(
        id=url.id,
        short_code=url.short_code,
        short_url=short_link(url.short_code),
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


def raise_already_shortened(existing: URL) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"You already shortened this URL: {short_link(existing.short_code)}",
    )


def raise_conflict_from_database(error: IntegrityError) -> None:
    # the error text names the database rule that refused the save
    if "uq_urls_user_id_original_url" in str(error.orig):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You already shortened this URL")
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This custom alias is already used")


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


def get_own_url_or_404(urls: URLRepository, user: User, short_code: str) -> URL:
    # Admins may reach any user's link. Everyone else only finds their own:
    # someone else's link looks exactly like a link that does not exist (404).
    if user.tier == "admin":
        url = urls.get_by_code(short_code)
    else:
        url = urls.get_for_user(user_id=user.id, code=short_code)
    if url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")
    return url


# ---------- /api/v1/auth ----------

auth_router = APIRouter(prefix=f"{API_PREFIX}/auth", tags=["auth"])


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
    response_model=TokenResponse,
    summary="Log in and receive an access token and a refresh token",
    description=(
        "Send your email (in the 'username' field, as the OAuth2 standard names it) and your password "
        "as form data. You get an access token (valid 30 minutes) to send with every request, and a "
        "refresh token (valid 7 days) to get new access tokens. In Swagger, use the 'Authorize' button: "
        "it logs in through this endpoint and keeps the token for you. "
        "At most 5 attempts per minute from the same address (then 429)."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "The email or password is incorrect"},
        403: {"model": ErrorResponse, "description": "The account is disabled"},
        429: {"model": ErrorResponse, "description": "Too many login attempts: wait a minute"},
    },
)
@limiter.limit(LOGIN_RATE_LIMIT)  # counts every attempt, right or wrong, per visitor address
def login(
    request: Request,  # slowapi reads the visitor's address from it
    form: OAuth2PasswordRequestForm = Depends(),
    users: UserRepository = Depends(get_user_repository),
) -> TokenResponse:
    user = users.get_by_email(form.username.lower())

    # same message for "unknown email" and "wrong password", so nobody can find out who has an account
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled")

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        expires_in=ACCESS_TOKEN_MINUTES * 60,
    )


@auth_router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    summary="Get a new access token",
    description="Send the refresh token you got at login. You get a new access token, without typing your password again.",
    responses={
        401: {"model": ErrorResponse, "description": "The refresh token is invalid or has expired: log in again"},
        403: {"model": ErrorResponse, "description": "The account is disabled"},
    },
)
def refresh(
    body: RefreshRequest,
    users: UserRepository = Depends(get_user_repository),
) -> AccessTokenResponse:
    try:
        user_id = read_token(body.refresh_token, expected_type="refresh")
    except InvalidTokenError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error))

    user = users.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled")

    return AccessTokenResponse(access_token=create_access_token(user.id), expires_in=ACCESS_TOKEN_MINUTES * 60)


# ---------- /api/v1/urls ----------

urls_router = APIRouter(prefix=f"{API_PREFIX}/urls", tags=["urls"])


@urls_router.post(
    "",
    response_model=URLResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a short URL",
    description=(
        "Login required. Send a long URL and get back a unique 6-character short code and a "
        "ready-to-share short link. Optional: tags, a custom alias, a title, a description, a favicon "
        "and an expiry date. The link belongs to you. Free accounts can have at most 10 active links "
        "and cannot use a custom alias."
    ),
    responses={
        **NOT_LOGGED_IN,
        **TIER_LIMIT,
        **CONFLICT,
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
            user=current_user, original_url=str(body.url), tag_names=body.tags, details=details
        )
    except DuplicateURLError as error:
        raise_already_shortened(error.existing)
    except TierLimitError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    except AliasTakenError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This custom alias is already used")
    except IntegrityError as error:
        # two requests at the same moment: the database rule refused the second one
        raise_conflict_from_database(error)
    return to_url_response(url)


@urls_router.get(
    "",
    response_model=list[URLResponse],
    summary="List your URLs",
    description=(
        "Login required. Returns only your own links, newest first, one page at a time. "
        "Add ?tag=books to list only the links with that tag."
    ),
    responses={**NOT_LOGGED_IN},
)
def list_urls(
    limit: int = Query(default=20, ge=1, le=100, description="How many links per page"),
    offset: int = Query(default=0, ge=0, description="How many links to skip"),
    tag: str | None = Query(default=None, min_length=1, max_length=50, description="Only links with this tag"),
    current_user: User = Depends(get_current_user),
    urls: URLRepository = Depends(get_url_repository),
) -> list[URLResponse]:
    tag_name = None
    if tag is not None:
        # tidy it like saved tags are tidied: " Books " -> "books"
        tag_name = tag.strip().lower()
    page = urls.list_for_user(user_id=current_user.id, limit=limit, offset=offset, tag=tag_name)
    return [to_url_response(url) for url in page]


def visitor_lists(urls: URLRepository, user_id: int | None = None, url_id: int | None = None) -> dict:
    # The 5 "top 10 visitors by ..." lists, for all of a user's links (user_id) or for one link (url_id)
    return {
        "clicks_per_ip_address": [
            IPAddressCount(ip_address=hide_ip(row.value), clicks=row.clicks)
            for row in urls.clicks_grouped_by(user_id, Click.ip_address, limit=TOP, url_id=url_id)
        ],
        "clicks_per_user_agent": [
            UserAgentCount(user_agent=row.value or "Unknown", clicks=row.clicks)
            for row in urls.clicks_grouped_by(user_id, Click.user_agent, limit=TOP, url_id=url_id)
        ],
        "clicks_per_country": [
            CountryCount(country=row.value or "Unknown", clicks=row.clicks)
            for row in urls.clicks_grouped_by(user_id, Click.country, limit=TOP, url_id=url_id)
        ],
        "clicks_per_city": [
            CityCount(city=row.city or "Unknown", country=row.country or "Unknown", clicks=row.clicks)
            for row in urls.clicks_per_city(user_id, limit=TOP, url_id=url_id)
        ],
        "clicks_per_referrer": [
            ReferrerCount(referrer=row.value or "Direct", clicks=row.clicks)
            for row in urls.clicks_grouped_by(user_id, Click.referrer, limit=TOP, url_id=url_id)
        ],
    }


# /stats must be declared before /{short_code}, or "stats" would be read as a short code
@urls_router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Statistics about your URLs",
    description=(
        "Login required. Totals across all your links: how many links and clicks you have, "
        "your 5 most clicked links, clicks per day for the last 7 days and how many links use each tag. "
        "Premium and admin accounts also get the top 10 visitors' IP addresses (partly hidden), "
        "user agents, countries, cities and referrers; for free accounts these are null."
    ),
    responses={**NOT_LOGGED_IN},
)
def get_stats(
    current_user: User = Depends(get_current_user),
    urls: URLRepository = Depends(get_url_repository),
) -> StatsResponse:
    user_id = current_user.id
    detailed = current_user.tier != "free"

    details = {}
    if detailed:
        details = visitor_lists(urls, user_id=user_id)

    return StatsResponse(
        total_urls=urls.count_urls(user_id),
        total_clicks=urls.count_clicks(user_id),
        top_urls=[
            TopURL(short_code=row.short_code, original_url=row.original_url, clicks=row.clicks)
            for row in urls.top_urls(user_id, limit=5)
        ],
        clicks_last_7_days=[DayClicks(day=row.day, clicks=row.clicks) for row in urls.clicks_per_day(user_id, days=7)],
        urls_per_tag=[TagCount(tag=row.name, urls=row.urls) for row in urls.urls_per_tag(user_id)],
        detailed_analytics=detailed,
        **details,
    )


@urls_router.get(
    "/{short_code}",
    response_model=URLResponse,
    summary="Get one of your URLs",
    description="Login required. Use the link's short code (or its custom alias). Returns 404 if it does not exist or is not yours.",
    responses={**NOT_LOGGED_IN, **NOT_FOUND},
)
def get_url(
    short_code: str,
    current_user: User = Depends(get_current_user),
    urls: URLRepository = Depends(get_url_repository),
) -> URLResponse:
    url = get_own_url_or_404(urls, current_user, short_code)
    return to_url_response(url)


# The same function answers both PUT (what the spec asks for) and PATCH:
# in both cases only the fields you send are changed.
@urls_router.put(
    "/{short_code}",
    response_model=URLResponse,
    summary="Update one of your URLs",
    description=(
        "Login required. Send only what you want to change. Leave a field out to keep it. "
        "Send null to clear an optional field (custom_alias, title, description, favicon, expires_at). "
        "Send is_active false to switch the link off. "
        "If nothing you sent differs from the current values, the answer is 400. "
        "PUT and PATCH behave the same."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Nothing was sent, or nothing would change"},
        **NOT_LOGGED_IN,
        **TIER_LIMIT,
        **NOT_FOUND,
        **CONFLICT,
    },
)
@urls_router.patch(
    "/{short_code}",
    response_model=URLResponse,
    summary="Update one of your URLs (same as PUT)",
    responses={
        400: {"model": ErrorResponse, "description": "Nothing was sent, or nothing would change"},
        **NOT_LOGGED_IN,
        **TIER_LIMIT,
        **NOT_FOUND,
        **CONFLICT,
    },
)
def update_url(
    short_code: str,
    body: URLUpdate,
    current_user: User = Depends(get_current_user),
    urls: URLRepository = Depends(get_url_repository),
    tags: TagRepository = Depends(get_tag_repository),
) -> URLResponse:
    url = get_own_url_or_404(urls, current_user, short_code)

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

    # tier rules: setting an alias is premium-only (removing one, with null, is always allowed),
    # and a link that comes back to life (switched on again, or expiry removed/extended) counts
    # towards the free limit of active links
    new_alias = changes.get("custom_alias")
    live_now = is_live(url.is_active, url.expires_at)
    live_after = is_live(changes.get("is_active", url.is_active), changes.get("expires_at", url.expires_at))
    try:
        if new_alias is not None:
            check_can_use_alias(current_user)
        if not live_now and live_after:
            check_can_add_active_link(urls, current_user)
    except TierLimitError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))

    if new_alias is not None and not alias_is_available(urls, new_alias):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This custom alias is already used")

    new_tags = None
    if tags_changed:
        new_tags = tags.get_or_create(body.tags)

    if "original_url" in changes:
        existing = urls.get_user_link_for_url(url.user_id, changes["original_url"])
        if existing is not None:
            raise_already_shortened(existing)

    try:
        url = urls.update(url, changes=changes, tags=new_tags)
    except IntegrityError as error:
        # two requests at the same moment: the database rule refused the second one
        raise_conflict_from_database(error)
    return to_url_response(url)


@urls_router.delete(
    "/{short_code}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Switch off (or delete) one of your URLs",
    description=(
        "Login required. By default the link is switched off (is_active becomes false): it stops "
        "redirecting (410) but keeps its history, and can be switched back on with PUT/PATCH. "
        "Add ?permanent=true to delete it for good, together with its clicks."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "The link is already switched off"},
        **NOT_LOGGED_IN,
        **NOT_FOUND,
    },
)
def delete_url(
    short_code: str,
    permanent: bool = Query(default=False, description="true deletes the link and its clicks for good"),
    current_user: User = Depends(get_current_user),
    urls: URLRepository = Depends(get_url_repository),
) -> Response:
    url = get_own_url_or_404(urls, current_user, short_code)

    if permanent:
        urls.delete(url)
    elif not url.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This link is already switched off")
    else:
        urls.update(url, changes={"is_active": False}, tags=None)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- /api/v1/analytics (premium and admin only) ----------

analytics_router = APIRouter(prefix=f"{API_PREFIX}/analytics", tags=["analytics"])


@analytics_router.get(
    "/{short_code}",
    response_model=LinkAnalyticsResponse,
    summary="Detailed analytics for one of your links (Premium)",
    description=(
        "Premium and admin accounts only. Use the link's short code (or alias). Visits per day "
        "(oldest first, days with no visits included as 0) and the top 10 countries, cities, "
        "referrers, user agents and IP addresses (partly hidden). "
        "Locally, country and city are 'Unknown': Docker's private address has no location."
    ),
    responses={
        **NOT_LOGGED_IN,
        403: {"model": ErrorResponse, "description": "Detailed analytics are a Premium feature"},
        **NOT_FOUND,
    },
)
def link_analytics(
    short_code: str,
    days: int = Query(default=30, ge=1, le=365, description="How many days of visits per day to show"),
    current_user: User = Depends(require_premium),
    urls: URLRepository = Depends(get_url_repository),
) -> LinkAnalyticsResponse:
    url = get_own_url_or_404(urls, current_user, short_code)

    # one entry for every day of the period, so a chart has no gaps
    counts_by_day = {}
    for row in urls.clicks_per_day(None, days=days, url_id=url.id):
        counts_by_day[row.day] = row.clicks
    today = datetime.now(timezone.utc).date()
    clicks_per_day = []
    for days_ago in range(days - 1, -1, -1):
        day = today - timedelta(days=days_ago)
        clicks_per_day.append(DayClicks(day=day, clicks=counts_by_day.get(day, 0)))

    return LinkAnalyticsResponse(
        short_code=url.short_code,
        original_url=url.original_url,
        total_clicks=url.click_count,
        days=days,
        clicks_per_day=clicks_per_day,
        **visitor_lists(urls, url_id=url.id),
    )


# ---------- /api/v1/admin (admins only) ----------
# Every route in this router goes through require_admin first: not an admin -> 403.

admin_router = APIRouter(prefix=f"{API_PREFIX}/admin", tags=["admin"])
ADMINS_ONLY = {403: {"model": ErrorResponse, "description": "You are not an admin"}}


@admin_router.get(
    "/users",
    response_model=list[UserRead],
    summary="List all users (admins only)",
    responses={**NOT_LOGGED_IN, **ADMINS_ONLY},
)
def list_users(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    users: UserRepository = Depends(get_user_repository),
) -> list[UserRead]:
    return users.list_all(limit=limit, offset=offset)


@admin_router.patch(
    "/users/{user_id}",
    response_model=UserRead,
    summary="Change a user's tier or switch their account on/off (admins only)",
    description=(
        "Send tier (free, premium or admin) and/or is_active. is_premium follows the tier automatically. "
        "An admin cannot demote or disable their own account, so the system always keeps an admin."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Nothing to change, or you tried to demote/disable yourself"},
        **NOT_LOGGED_IN,
        **ADMINS_ONLY,
        404: {"model": ErrorResponse, "description": "No user with this id"},
    },
)
def update_user(
    user_id: int,
    body: AdminUserUpdate,
    admin: User = Depends(require_admin),
    users: UserRepository = Depends(get_user_repository),
) -> UserRead:
    user = users.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not body.model_fields_set:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Send tier and/or is_active")

    # keep only the values that really differ from what is stored now
    changes = {}
    for field_name, value in body.model_dump(exclude_unset=True).items():
        if getattr(user, field_name) != value:
            changes[field_name] = value
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nothing to update: the values you sent are the same as the current ones",
        )

    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own tier or disable your own account",
        )

    return users.update(user, changes)


# ---------- /{short_code}: the public redirect ----------
# Registered last in main.py, so it never hides /docs, /health or /api/... addresses.

redirect_router = APIRouter(tags=["redirect"])


@redirect_router.get(
    "/{code}",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
    summary="Redirect to the original URL",
    description=(
        "Public, no login. Looks up the short code (or custom alias), records the visit and redirects "
        "to the original URL. Open the short link in your browser's address bar to test it: "
        "Swagger's 'Try it out' cannot follow redirects to other websites."
    ),
    responses={
        302: {"description": "Redirects to the original URL"},
        404: {"model": ErrorResponse, "description": "No URL was found for this short code"},
        410: {"model": ErrorResponse, "description": "The link was switched off or has expired"},
    },
)
def redirect_to_url(
    code: str,
    request: Request,
    service: UrlShortenerService = Depends(get_shortener_service),
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
