from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.config import ACCESS_TOKEN_MINUTES, JWT_SECRET_KEY, REFRESH_TOKEN_DAYS

password_hash = PasswordHash((BcryptHasher(),))

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


# ---------- JWT tokens ----------

class InvalidTokenError(Exception):
    pass


def create_token(user_id: int, token_type: str, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    content = {
        "sub": str(user_id),  # "subject": who the token belongs to
        "type": token_type,   # "access" or "refresh", so one can't be used as the other
        "iat": now,           # issued at
        "exp": now + lifetime,  # expires at: PyJWT refuses the token after this moment
    }
    return jwt.encode(content, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_access_token(user_id: int) -> str:
    return create_token(user_id, "access", timedelta(minutes=ACCESS_TOKEN_MINUTES))


def create_refresh_token(user_id: int) -> str:
    return create_token(user_id, "refresh", timedelta(days=REFRESH_TOKEN_DAYS))


def read_token(token: str, expected_type: str) -> int:
    """Check the signature, the expiry and the type, then return the user id."""
    try:
        content = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise InvalidTokenError("Token has expired")
    except jwt.InvalidTokenError:
        raise InvalidTokenError("Invalid token")

    if content.get("type") != expected_type:
        raise InvalidTokenError(f"Wrong token type: expected the {expected_type} token")

    return int(content["sub"])
