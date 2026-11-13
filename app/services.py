import secrets
import string

from app.models import URL
from app.repositories import TagRepository, URLRepository

ALPHABET = string.ascii_letters + string.digits
CODE_LENGTH = 6


class UrlShortenerService:
    def __init__(self, urls: URLRepository, tags: TagRepository) -> None:
        self.urls = urls
        self.tags = tags

    def generate_code(self) -> str:
        code = ""
        for _ in range(CODE_LENGTH):
            code += secrets.choice(ALPHABET)
        return code

    def shorten(self, user_id: int, original_url: str, tag_names: list[str]) -> URL:
        code = self.generate_code()
        while self.urls.code_exists(code):
            code = self.generate_code()

        tags = self.tags.get_or_create(tag_names)
        return self.urls.create(user_id=user_id, short_code=code, original_url=original_url, tags=tags)

    def open(self, short_code: str) -> str | None:
        url = self.urls.get_by_code(short_code)
        if url is None:
            return None

        self.urls.add_click(url)
        return url.original_url
