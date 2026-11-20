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

    def list_all(self, limit: int, offset: int) -> list[User]:
        statement = select(User).order_by(User.id).limit(limit).offset(offset)
        return list(self.db.scalars(statement))

    def update(self, user: User, changes: dict) -> User:
        # changes only holds the fields to change, e.g. {"tier": "premium"} or {"is_active": False}
        if "tier" in changes:
            # is_premium always follows the tier, so the two can never disagree
            changes["is_premium"] = changes["tier"] != "free"
        for field_name, value in changes.items():
            setattr(user, field_name, value)
        self.db.commit()
        return user


def clean_tag_names(names: list[str]) -> list[str]:
    # " Shopping", "shopping" -> ["shopping"]: trimmed, lowercase, no repeats
    clean_names = []
    for name in names:
        name = name.strip().lower()
        if name and name not in clean_names:
            clean_names.append(name)
    return clean_names


class TagRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_create(self, names: list[str]) -> list[Tag]:
        clean_names = clean_tag_names(names)

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

    def get_user_link_for_url(self, user_id: int, original_url: str) -> URL | None:
        # "does this user already have a link for this URL?"
        # comparing md5(...) lets Postgres use the uq_urls_user_id_original_url index;
        # the plain comparison makes sure it really is the same URL
        statement = select(URL).where(
            URL.user_id == user_id,
            func.md5(URL.original_url) == func.md5(original_url),
            URL.original_url == original_url,
        )
        return self.db.scalar(statement)

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

    def get_for_user(self, user_id: int, code: str) -> URL | None:
        # "this user's link whose short code OR custom alias is <code>" (both have a unique index)
        statement = (
            select(URL)
            .where(or_(URL.short_code == code, URL.custom_alias == code), URL.user_id == user_id)
            .options(selectinload(URL.tags))
        )
        return self.db.scalar(statement)

    def list_for_user(self, user_id: int, limit: int, offset: int, tag: str | None = None) -> list[URL]:
        statement = select(URL).where(URL.user_id == user_id)
        if tag is not None:
            # "links for which SOME tag has this name" -> EXISTS (...) through url_tags
            statement = statement.where(URL.tags.any(Tag.name == tag))
        statement = (
            statement.options(selectinload(URL.tags))
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

    def add_click(
        self,
        url: URL,
        ip_address: str,
        user_agent: str,
        referrer: str | None,
        country: str | None,
        city: str | None,
    ) -> None:
        click = Click(
            url_id=url.id,
            ip_address=ip_address,
            user_agent=user_agent,
            referrer=referrer,
            country=country,
            city=city,
        )
        self.db.add(click)
        # +1 is done by Postgres ("current value + 1"), so two visits at the same moment are both counted
        self.db.execute(update(URL).where(URL.id == url.id).values(click_count=URL.click_count + 1))
        # one commit: the visit row and the counter are saved together
        self.db.commit()

    def count_urls(self, user_id: int) -> int:
        return self.db.scalar(select(func.count(URL.id)).where(URL.user_id == user_id))

    def count_active_urls(self, user_id: int) -> int:
        # "active" = switched on AND not expired (no expiry date, or one still in the future)
        now = datetime.now(timezone.utc)
        statement = select(func.count(URL.id)).where(
            URL.user_id == user_id,
            URL.is_active.is_(True),
            or_(URL.expires_at.is_(None), URL.expires_at > now),
        )
        return self.db.scalar(statement)

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

    def only_these_clicks(self, statement, user_id: int | None, url_id: int | None):
        # The click statistics work for all of one user's links (user_id)
        # or for a single link (url_id). One link needs no join: clicks.url_id is enough.
        if url_id is not None:
            return statement.where(Click.url_id == url_id)
        return statement.join(Click.url).where(URL.user_id == user_id)

    def clicks_per_day(self, user_id: int | None, days: int, url_id: int | None = None) -> list:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        day = func.date(Click.clicked_at).label("day")
        statement = select(day, func.count(Click.id).label("clicks")).where(Click.clicked_at >= since)
        statement = self.only_these_clicks(statement, user_id, url_id).group_by(day).order_by(day)
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

    def clicks_grouped_by(self, user_id: int | None, column, limit: int, url_id: int | None = None) -> list:
        # "count the clicks per value of <column>, most first" (for a user's links, or one link)
        # used for ip_address, user_agent, country and referrer
        click_count = func.count(Click.id).label("clicks")
        statement = select(column.label("value"), click_count)
        statement = (
            self.only_these_clicks(statement, user_id, url_id)
            .group_by(column)
            .order_by(click_count.desc(), column)
            .limit(limit)
        )
        return list(self.db.execute(statement))

    def clicks_per_city(self, user_id: int | None, limit: int, url_id: int | None = None) -> list:
        # grouped by city AND country, so two towns with the same name stay apart
        click_count = func.count(Click.id).label("clicks")
        statement = select(Click.city, Click.country, click_count)
        statement = (
            self.only_these_clicks(statement, user_id, url_id)
            .group_by(Click.city, Click.country)
            .order_by(click_count.desc(), Click.city)
            .limit(limit)
        )
        return list(self.db.execute(statement))
