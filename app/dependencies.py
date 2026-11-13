from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import REDIS_URL
from app.database import get_db
from app.repositories import UserRepository
from app.services import UrlShortenerService
from app.storage import RedisStorage

storage = RedisStorage(REDIS_URL)


def get_shortener_service() -> UrlShortenerService:
    return UrlShortenerService(storage)


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)
