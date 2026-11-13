from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import URL, Click, Tag, User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(User.email == email))

    def get_by_id(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def create(self, email: str, hashed_password: str) -> User:
        user = User(email=email, hashed_password=hashed_password)
        self.db.add(user)
        self.db.commit()
        return user


class TagRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_create(self, names: list[str]) -> list[Tag]:
        clean_names = []
        for name in names:
            name = name.strip().lower()
            if name and name not in clean_names:
                clean_names.append(name)

        if not clean_names:
            return []

        existing_tags = list(self.db.scalars(select(Tag).where(Tag.name.in_(clean_names))))
        existing_names = [tag.name for tag in existing_tags]

        new_tags = [Tag(name=name) for name in clean_names if name not in existing_names]
        self.db.add_all(new_tags)

        return existing_tags + new_tags


class URLRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def code_exists(self, short_code: str) -> bool:
        return self.db.scalar(select(URL.id).where(URL.short_code == short_code)) is not None

    def create(self, user_id: int, short_code: str, original_url: str, tags: list[Tag]) -> URL:
        url = URL(user_id=user_id, short_code=short_code, original_url=original_url, tags=tags)
        self.db.add(url)
        self.db.commit()
        return url

    def get_by_code(self, short_code: str) -> URL | None:
        return self.db.scalar(select(URL).where(URL.short_code == short_code))

    def get_for_user(self, user_id: int, url_id: int) -> URL | None:
        statement = (
            select(URL)
            .where(URL.id == url_id, URL.user_id == user_id)
            .options(selectinload(URL.tags))
        )
        return self.db.scalar(statement)

    def list_for_user(self, user_id: int, limit: int, offset: int) -> list[URL]:
        statement = (
            select(URL)
            .where(URL.user_id == user_id)
            .options(selectinload(URL.tags))
            .order_by(URL.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(statement))

    def update(self, url: URL, original_url: str | None, tags: list[Tag] | None) -> URL:
        if original_url is not None:
            url.original_url = original_url
        if tags is not None:
            url.tags = tags
        self.db.commit()
        return url

    def delete(self, url: URL) -> None:
        self.db.delete(url)
        self.db.commit()

    def add_click(self, url: URL) -> None:
        self.db.add(Click(url_id=url.id))
        self.db.commit()
