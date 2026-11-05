from app.config import REDIS_URL
from app.services import UrlShortenerService
from app.storage import RedisStorage

storage = RedisStorage(REDIS_URL)


def get_shortener_service() -> UrlShortenerService:
    return UrlShortenerService(storage)
