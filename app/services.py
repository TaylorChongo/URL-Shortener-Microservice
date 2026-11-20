import secrets
import string
from datetime import datetime, timezone

from app.geoip import find_location
from app.models import URL, User
from app.repositories import TagRepository, URLRepository

ALPHABET = string.ascii_letters + string.digits
CODE_LENGTH = 6

# Tier rules: free accounts are limited, premium and admin accounts are not
FREE_ACTIVE_LINK_LIMIT = 10

# Short links live at the root (/{code}), so these words are taken by the app's own pages
# and can never be an alias or a generated short code.
RESERVED_CODES = ["api", "docs", "redoc", "health"]


class AliasTakenError(Exception):
    pass


class DuplicateURLError(Exception):
    # the user already has a link for this URL; we keep it to tell them which one
    def __init__(self, existing: URL) -> None:
        super().__init__("You already shortened this URL")
        self.existing = existing


class TierLimitError(Exception):
    # a free account tried something only premium/admin accounts may do
    pass


def alias_is_available(urls: URLRepository, alias: str) -> bool:
    if alias.lower() in RESERVED_CODES:
        return False
    return not urls.code_exists(alias)


def is_live(is_active: bool, expires_at: datetime | None) -> bool:
    # a link works when it is switched on and not expired
    if not is_active:
        return False
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        # a date sent without a timezone is read as UTC
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > datetime.now(timezone.utc)


def check_can_add_active_link(urls: URLRepository, user: User) -> None:
    if user.tier != "free":
        return
    if urls.count_active_urls(user.id) >= FREE_ACTIVE_LINK_LIMIT:
        raise TierLimitError(
            f"Free accounts can have at most {FREE_ACTIVE_LINK_LIMIT} active links: "
            "switch one off or upgrade to Premium"
        )


def check_can_use_alias(user: User) -> None:
    if user.tier == "free":
        raise TierLimitError("Custom aliases are a Premium feature")


class UrlShortenerService:
    def __init__(self, urls: URLRepository, tags: TagRepository) -> None:
        self.urls = urls
        self.tags = tags

    def generate_code(self) -> str:
        code = ""
        for _ in range(CODE_LENGTH):
            code += secrets.choice(ALPHABET)
        return code

    def shorten(self, user: User, original_url: str, tag_names: list[str], details: dict) -> URL:
        existing = self.urls.get_user_link_for_url(user.id, original_url)
        if existing is not None:
            raise DuplicateURLError(existing)

        # tier rules: a new link is always active, and an alias is premium-only
        alias = details.get("custom_alias")
        if alias is not None:
            check_can_use_alias(user)
        check_can_add_active_link(self.urls, user)

        if alias is not None and not alias_is_available(self.urls, alias):
            raise AliasTakenError()

        code = self.generate_code()
        while code.lower() in RESERVED_CODES or self.urls.code_exists(code):
            code = self.generate_code()

        tags = self.tags.get_or_create(tag_names)
        return self.urls.create(
            user_id=user.id, short_code=code, original_url=original_url, tags=tags, details=details
        )

    def find(self, code: str) -> URL | None:
        return self.urls.get_by_code(code)

    def record_visit(self, url: URL, ip_address: str, user_agent: str, referrer: str | None) -> None:
        country, city = find_location(ip_address)
        self.urls.add_click(
            url, ip_address=ip_address, user_agent=user_agent, referrer=referrer, country=country, city=city
        )
