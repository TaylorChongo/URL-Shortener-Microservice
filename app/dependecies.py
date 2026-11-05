from app.services import UrlShortenerService
from app.storage import InMemoryStorage

storage = InMemoryStorage()


def get_shortener_service() -> UrlShortenerService:
    return UrlShortenerService(storage)

