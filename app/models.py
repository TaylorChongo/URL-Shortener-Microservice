from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

url_tags = Table(
    "url_tags",
    Base.metadata,
    Column("url_id", ForeignKey("urls.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    urls: Mapped[list["URL"]] = relationship(back_populates="owner", passive_deletes=True)


class URL(Base):
    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(primary_key=True)
    short_code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    original_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    owner: Mapped["User"] = relationship(back_populates="urls")
    clicks: Mapped[list["Click"]] = relationship(back_populates="url", passive_deletes=True)
    tags: Mapped[list["Tag"]] = relationship(secondary=url_tags, back_populates="urls")


class Click(Base):
    __tablename__ = "clicks"

    id: Mapped[int] = mapped_column(primary_key=True)
    url_id: Mapped[int] = mapped_column(ForeignKey("urls.id", ondelete="CASCADE"), index=True)
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    url: Mapped["URL"] = relationship(back_populates="clicks")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)

    urls: Mapped[list["URL"]] = relationship(secondary=url_tags, back_populates="tags")
