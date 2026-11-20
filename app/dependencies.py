from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.repositories import TagRepository, URLRepository, UserRepository
from app.security import InvalidTokenError, read_token
from app.services import UrlShortenerService

# Reads "Authorization: Bearer <access token>" from each request.
# tokenUrl tells Swagger where to log in, so its "Authorize" button shows a login form.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_shortener_service(db: Session = Depends(get_db)) -> UrlShortenerService:
    return UrlShortenerService(URLRepository(db), TagRepository(db))


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_url_repository(db: Session = Depends(get_db)) -> URLRepository:
    return URLRepository(db)


def get_tag_repository(db: Session = Depends(get_db)) -> TagRepository:
    return TagRepository(db)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    users: UserRepository = Depends(get_user_repository),
) -> User:
    try:
        user_id = read_token(token, expected_type="access")
    except InvalidTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = users.get_by_id(user_id)
    if user is None:
        # the account was deleted after the token was made
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled")

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    # guard for admin-only routes: logged in (checked by get_current_user) AND tier "admin"
    if current_user.tier != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins only")
    return current_user
