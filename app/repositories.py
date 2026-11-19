from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import URL, Click, Tag, User, url_tags


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

    def code_exists(self, code: str) -> bool:
        # a code is taken if it is used as a short code OR as a custom alias
        statement = select(URL.id).where(or_(URL.short_code == code, URL.custom_alias == code))
        return self.db.scalar(statement) is not None

    def create(self, user_id: int, short_code: str, original_url: str, tags: list[Tag], details: dict) -> URL:
        # details holds the optional fields: custom_alias, title, description, favicon, expires_at
        url = URL(user_id=user_id, short_code=short_code, original_url=original_url, tags=tags, **details)
        self.db.add(url)
        self.db.commit()
        return url

    def get_by_code(self, code: str) -> URL | None:
        # a link opens with its short code or with its custom alias (both have a unique index)
        statement = select(URL).where(or_(URL.short_code == code, URL.custom_alias == code))
        return self.db.scalar(statement)

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

    def update(self, url: URL, changes: dict, tags: list[Tag] | None) -> URL:
        # changes only holds the fields the user sent, e.g. {"title": "New", "expires_at": None}
        for field_name, value in changes.items():
            setattr(url, field_name, value)
        if tags is not None:
            url.tags = tags
        self.db.commit()
        return url

    def delete(self, url: URL) -> None:
        self.db.delete(url)
        self.db.commit()

    def add_click(self, url: URL, ip_address: str, user_agent: str, referrer: str | None) -> None:
        click = Click(url_id=url.id, ip_address=ip_address, user_agent=user_agent, referrer=referrer)
        self.db.add(click)
        # +1 is done by Postgres ("current value + 1"), so two visits at the same moment are both counted
        self.db.execute(update(URL).where(URL.id == url.id).values(click_count=URL.click_count + 1))
        # one commit: the visit row and the counter are saved together
        self.db.commit()

    def count_urls(self, user_id: int) -> int:
        return self.db.scalar(select(func.count(URL.id)).where(URL.user_id == user_id))

    def count_clicks(self, user_id: int) -> int:
        # add up the stored counters; coalesce turns "no links" (NULL) into 0
        statement = select(func.coalesce(func.sum(URL.click_count), 0)).where(URL.user_id == user_id)
        return self.db.scalar(statement)

    def top_urls(self, user_id: int, limit: int) -> list:
        statement = (
            select(URL.short_code, URL.original_url, URL.click_count.label("clicks"))
            .where(URL.user_id == user_id)
            .order_by(URL.click_count.desc(), URL.id.desc())
            .limit(limit)
        )
        return list(self.db.execute(statement))

    def clicks_per_day(self, user_id: int, days: int) -> list:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        day = func.date(Click.clicked_at).label("day")
        statement = (
            select(day, func.count(Click.id).label("clicks"))
            .join(Click.url)
            .where(URL.user_id == user_id, Click.clicked_at >= since)
            .group_by(day)
            .order_by(day)
        )
        return list(self.db.execute(statement))

    def urls_per_tag(self, user_id: int) -> list:
        url_count = func.count(URL.id).label("urls")
        statement = (
            select(Tag.name, url_count)
            .join(url_tags, url_tags.c.tag_id == Tag.id)
            .join(URL, URL.id == url_tags.c.url_id)
            .where(URL.user_id == user_id)
            .group_by(Tag.name)
            .order_by(url_count.desc(), Tag.name)
        )
        return list(self.db.execute(statement))
