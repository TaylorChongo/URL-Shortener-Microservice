import secrets
import string

from app.geoip import find_location
from app.models import URL
from app.repositories import TagRepository, URLRepository

ALPHABET = string.ascii_letters + string.digits
CODE_LENGTH = 6

# these words are already used by the app's own addresses (/api/urls, /api/shorten)
RESERVED_ALIASES = ["urls", "shorten"]


class AliasTakenError(Exception):
    pass


def alias_is_available(urls: URLRepository, alias: str) -> bool:
    if alias.lower() in RESERVED_ALIASES:
        return False
    return not urls.code_exists(alias)


class UrlShortenerService:
    def __init__(self, urls: URLRepository, tags: TagRepository) -> None:
        self.urls = urls
        self.tags = tags

    def generate_code(self) -> str:
        code = ""
        for _ in range(CODE_LENGTH):
            code += secrets.choice(ALPHABET)
        return code

    def shorten(self, user_id: int, original_url: str, tag_names: list[str], details: dict) -> URL:
        alias = details.get("custom_alias")
        if alias is not None and not alias_is_available(self.urls, alias):
            raise AliasTakenError()

        code = self.generate_code()
        while self.urls.code_exists(code):
            code = self.generate_code()

        tags = self.tags.get_or_create(tag_names)
        return self.urls.create(
            user_id=user_id, short_code=code, original_url=original_url, tags=tags, details=details
        )

    def find(self, code: str) -> URL | None:
        return self.urls.get_by_code(code)

    def record_visit(self, url: URL, ip_address: str, user_agent: str, referrer: str | None) -> None:
        country, city = find_location(ip_address)
        self.urls.add_click(
            url, ip_address=ip_address, user_agent=user_agent, referrer=referrer, country=country, city=city
        )
