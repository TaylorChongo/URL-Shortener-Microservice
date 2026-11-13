from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl

TagName = Annotated[str, Field(min_length=1, max_length=50)]


class ShortenRequest(BaseModel):
    url: HttpUrl = Field(
        description="The long URL to shorten. Must start with http:// or https://",
        examples=["https://www.amazon.com/Python-Crash-Course-3rd-Edition/dp/1718502702"],
    )
    tags: list[TagName] = Field(
        default=[],
        max_length=10,
        description="Optional labels for this link (up to 10)",
        examples=[["shopping", "books"]],
    )


class URLUpdate(BaseModel):
    url: HttpUrl | None = Field(
        default=None,
        description="The new long URL. Leave it out to keep the current one.",
        examples=["https://www.python.org"],
    )
    tags: list[TagName] | None = Field(
        default=None,
        max_length=10,
        description="The new list of tags (replaces the old ones). Leave it out to keep the current tags, send [] to remove all.",
        examples=[["learning"]],
    )


class URLResponse(BaseModel):
    id: int = Field(examples=[1])
    short_code: str = Field(description="The unique 6-character code", examples=["aB3xY9"])
    short_url: str = Field(description="The full short link to share", examples=["http://127.0.0.1:8000/api/aB3xY9"])
    original_url: str = Field(
        description="The long URL that was shortened",
        examples=["https://www.amazon.com/Python-Crash-Course-3rd-Edition/dp/1718502702"],
    )
    tags: list[str] = Field(examples=[["shopping", "books"]])
    click_count: int = Field(description="How many times the short link was opened", examples=[12])
    created_at: datetime


class TopURL(BaseModel):
    short_code: str = Field(examples=["aB3xY9"])
    original_url: str = Field(examples=["https://www.python.org/"])
    clicks: int = Field(examples=[12])


class DayClicks(BaseModel):
    day: date
    clicks: int = Field(examples=[5])


class TagCount(BaseModel):
    tag: str = Field(examples=["shopping"])
    urls: int = Field(examples=[3])


class StatsResponse(BaseModel):
    total_urls: int = Field(examples=[8])
    total_clicks: int = Field(examples=[42])
    top_urls: list[TopURL]
    clicks_last_7_days: list[DayClicks]
    urls_per_tag: list[TagCount]


class UserCreate(BaseModel):
    email: EmailStr = Field(examples=["ama@mail.com"])
    password: str = Field(min_length=8, max_length=72, examples=["secret123"])


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True) # allows reading the attributes using the dot notation without it, it can only accepts dictionary keys

    id: int = Field(examples=[1])
    email: str = Field(examples=["ama@mail.com"])
    is_active: bool = Field(examples=[True])
    created_at: datetime


class ErrorResponse(BaseModel):
    status_code: int = Field(examples=[404])
    message: str = Field(examples=["Short URL not found"])


class FieldError(BaseModel):
    field: str = Field(examples=["url"])
    message: str = Field(examples=["Input should be a valid URL, relative URL without a base"])


class ValidationErrorResponse(BaseModel):
    status_code: int = Field(examples=[422])
    message: str = Field(examples=["Invalid input"])
    errors: list[FieldError]
