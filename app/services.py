import secrets
import string

from app.storage import InMemoryStorage

ALPHABET = string.ascii_letters + string.digits
CODE_LENGTH = 6


class UrlShortenerService:
    def __init__(self, storage: InMemoryStorage) -> None:
        self.storage = storage

    def generate_code(self) -> str:
        code = ""
        for _ in range(CODE_LENGTH):
            code += secrets.choice(ALPHABET)
        return code

    def shorten(self, url: str) -> str:
        code = self.generate_code()
        while self.storage.exists(code):
            code = self.generate_code()
        self.storage.save(code, url)
        return code

    def get_original_url(self, short_code: str) -> str | None:
        return self.storage.get(short_code)
