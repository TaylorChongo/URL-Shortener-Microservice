from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)  # preping helps check if the connection is still alive before using it, and if not, it will create a new one.

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False) # sessionmake is a factory for creating sessions.

class Base(DeclarativeBase): # SQL alchemy rule, we can't create a table that directly inherits the DeclarativeBase
    #the class that inherits directly from DeclarativeBase has to be treated as a Base, that's the rule.
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
