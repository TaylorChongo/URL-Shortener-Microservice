from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, String, Table, Text, false, func, true
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# The three account levels (roles). The database CHECK rule on users.tier allows only these.
TIERS = ("free", "premium", "admin")

url_tags = Table(
    "url_tags",
    Base.metadata,
    Column("url_id", ForeignKey("urls.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class User(Base):
    __tablename__ = "users"
    # tier can only be one of these three values (like Django's "choices")
    __table_args__ = (CheckConstraint("tier IN ('free', 'premium', 'admin')", name="ck_users_tier"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    is_premium: Mapped[bool] = mapped_column(default=False, server_default=false())
    tier: Mapped[str] = mapped_column(String(20), default="free", server_default="free")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    urls: Mapped[list["URL"]] = relationship(back_populates="owner", passive_deletes=True)


class URL(Base):
    __tablename__ = "urls"
    # "my links, newest first": filter by user_id, then read ids in order (no extra sort)
    __table_args__ = (
        Index("ix_urls_user_id_id", "user_id", "id"),
        # the stored counter can never go below zero (like Django's PositiveIntegerField)
        CheckConstraint("click_count >= 0", name="ck_urls_click_count_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    short_code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    custom_alias: Mapped[str | None] = mapped_column(String(10), unique=True, index=True)
    original_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(500))
    favicon: Mapped[str | None] = mapped_column(String(2048))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # stored number of visits, so reading it needs no counting
    click_count: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    owner: Mapped["User"] = relationship(back_populates="urls")
    clicks: Mapped[list["Click"]] = relationship(back_populates="url", passive_deletes=True)
    tags: Mapped[list["Tag"]] = relationship(secondary=url_tags, back_populates="urls")


# One user cannot shorten the same URL twice (different users can).
# The index stores md5(original_url), a short fingerprint, so it stays small even for very long URLs.
Index("uq_urls_user_id_original_url", URL.user_id, func.md5(URL.original_url), unique=True)


class Click(Base):
    __tablename__ = "clicks"
    # "clicks of these links (since a date)": filter by url_id, then by clicked_at
    __table_args__ = (Index("ix_clicks_url_id_clicked_at", "url_id", "clicked_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    url_id: Mapped[int] = mapped_column(ForeignKey("urls.id", ondelete="CASCADE"))
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # INET is Postgres's own IP address type: it stores IPv4 and IPv6 and rejects invalid addresses
    ip_address: Mapped[str] = mapped_column(INET)
    user_agent: Mapped[str] = mapped_column(Text)
    referrer: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))

    url: Mapped["URL"] = relationship(back_populates="clicks")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)

    urls: Mapped[list["URL"]] = relationship(secondary=url_tags, back_populates="tags")
