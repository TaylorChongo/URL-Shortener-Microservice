from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.repositories import TagRepository, URLRepository, UserRepository
from app.security import verify_password
from app.services import UrlShortenerService

basic_auth = HTTPBasic()


def get_shortener_service(db: Session = Depends(get_db)) -> UrlShortenerService:
    return UrlShortenerService(URLRepository(db), TagRepository(db))


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_current_user(
    credentials: HTTPBasicCredentials = Depends(basic_auth),
    users: UserRepository = Depends(get_user_repository),
) -> User:
    user = users.get_by_email(credentials.username.lower())

    if user is None or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled")

    return user
