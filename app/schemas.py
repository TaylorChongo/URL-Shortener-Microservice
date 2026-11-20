from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, FutureDatetime, HttpUrl

TagName = Annotated[str, Field(min_length=1, max_length=50)]
# 3 to 10 characters: letters, digits, "-" and "_" only (it becomes part of a web address)
CustomAlias = Annotated[str, Field(min_length=3, max_length=10, pattern=r"^[A-Za-z0-9_-]+$")]


class ShortenRequest(BaseModel):
    # The body Swagger pre-fills in "Try it out": short and valid, so "Execute" works straight away.
    # The optional fields are still listed in the schema below it.
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "url": "https://www.amazon.com/Python-Crash-Course-3rd-Edition/dp/1718502702",
                    "tags": ["books"],
                }
            ]
        }
    )

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
    custom_alias: CustomAlias | None = Field(
        default=None,
        description="Optional name for the link, e.g. 'my-cv' opens at /api/my-cv (3-10 letters, digits, - or _)",
        examples=["my-cv"],
    )
    title: str | None = Field(default=None, max_length=255, examples=["Python Crash Course"])
    description: str | None = Field(default=None, max_length=500, examples=["The book I recommend to beginners"])
    favicon: str | None = Field(default=None, max_length=2048, description="Address of the site's small icon")
    expires_at: FutureDatetime | None = Field(
        default=None,
        description="When the link stops working (must be in the future). Leave it out for a link that never expires.",
        examples=["2030-01-01T00:00:00Z"],
    )


class URLUpdate(BaseModel):
    # The body Swagger pre-fills in "Try it out": change just the title and the tags.
    model_config = ConfigDict(json_schema_extra={"examples": [{"title": "My new title", "tags": ["learning"]}]})

    # Leave a field out to keep its current value.
    # For optional fields (alias, title, description, favicon, expires_at), send null to clear them.
    # url, tags and is_active cannot be null, so their default is None only to mean "not sent".
    url: HttpUrl = Field(default=None, description="The new long URL", examples=["https://www.python.org"])
    tags: list[TagName] = Field(
        default=None,
        max_length=10,
        description="The new list of tags (replaces the old ones). Send [] to remove all.",
        examples=[["learning"]],
    )
    is_active: bool = Field(default=None, description="false switches the link off (it answers 410)", examples=[False])
    custom_alias: CustomAlias | None = Field(default=None, examples=["my-cv"])
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    favicon: str | None = Field(default=None, max_length=2048)
    expires_at: FutureDatetime | None = Field(
        default=None,
        description="Must be in the future. Send null to remove the expiry date.",
        examples=["2030-01-01T00:00:00Z"],
    )


class URLResponse(BaseModel):
    id: int = Field(examples=[1])
    short_code: str = Field(description="The unique 6-character code", examples=["aB3xY9"])
    short_url: str = Field(description="The full short link to share", examples=["http://127.0.0.1:8000/api/aB3xY9"])
    original_url: str = Field(
        description="The long URL that was shortened",
        examples=["https://www.amazon.com/Python-Crash-Course-3rd-Edition/dp/1718502702"],
    )
    custom_alias: str | None = Field(examples=["my-cv"])
    alias_url: str | None = Field(description="The short link using the alias", examples=["http://127.0.0.1:8000/api/my-cv"])
    title: str | None
    description: str | None
    favicon: str | None
    tags: list[str] = Field(examples=[["shopping", "books"]])
    click_count: int = Field(description="How many times the short link was opened", examples=[12])
    is_active: bool = Field(examples=[True])
    expires_at: datetime | None
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


class IPAddressCount(BaseModel):
    ip_address: str = Field(description="The last part is hidden to protect the visitor", examples=["196.216.180.xxx"])
    clicks: int = Field(examples=[5])


class UserAgentCount(BaseModel):
    user_agent: str = Field(examples=["Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) ..."])
    clicks: int = Field(examples=[5])


class CountryCount(BaseModel):
    country: str = Field(examples=["Ghana"])
    clicks: int = Field(examples=[12])


class CityCount(BaseModel):
    city: str = Field(examples=["Accra"])
    country: str = Field(examples=["Ghana"])
    clicks: int = Field(examples=[9])


class ReferrerCount(BaseModel):
    referrer: str = Field(description="The page visitors came from, or 'Direct'", examples=["https://twitter.com/ama/status/1"])
    clicks: int = Field(examples=[8])


class StatsResponse(BaseModel):
    total_urls: int = Field(examples=[8])
    total_clicks: int = Field(examples=[42])
    top_urls: list[TopURL]
    clicks_last_7_days: list[DayClicks]
    urls_per_tag: list[TagCount]
    # the visitor lists below are a Premium feature: null for free accounts
    detailed_analytics: bool = Field(description="true for premium and admin accounts: the visitor lists below are filled")
    clicks_per_ip_address: list[IPAddressCount] | None = None
    clicks_per_user_agent: list[UserAgentCount] | None = None
    clicks_per_country: list[CountryCount] | None = None
    clicks_per_city: list[CityCount] | None = None
    clicks_per_referrer: list[ReferrerCount] | None = None


class LinkAnalyticsResponse(BaseModel):
    short_code: str = Field(examples=["aB3xY9"])
    original_url: str = Field(examples=["https://www.python.org/"])
    total_clicks: int = Field(examples=[42])
    days: int = Field(description="How many days clicks_per_day covers", examples=[30])
    clicks_per_day: list[DayClicks] = Field(description="One entry per day, oldest first, including days with 0 clicks")
    clicks_per_country: list[CountryCount]
    clicks_per_city: list[CityCount]
    clicks_per_referrer: list[ReferrerCount]
    clicks_per_user_agent: list[UserAgentCount]
    clicks_per_ip_address: list[IPAddressCount]


class UserCreate(BaseModel):
    email: EmailStr = Field(examples=["ama@mail.com"])
    password: str = Field(min_length=8, max_length=72, examples=["secret123"])


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True) # allows reading the attributes using the dot notation without it, it can only accepts dictionary keys

    id: int = Field(examples=[1])
    email: str = Field(examples=["ama@mail.com"])
    is_active: bool = Field(examples=[True])
    is_premium: bool = Field(examples=[False])
    tier: str = Field(description="Account level: free, premium or admin", examples=["free"])
    created_at: datetime


class AdminUserUpdate(BaseModel):
    # Leave a field out to keep it. Neither field can be null.
    model_config = ConfigDict(json_schema_extra={"examples": [{"tier": "premium"}]})

    tier: Literal["free", "premium", "admin"] = Field(
        default=None, description="New account level. is_premium is set automatically (true for premium and admin)."
    )
    is_active: bool = Field(default=None, description="false disables the account: it can no longer log in")


class TokenResponse(BaseModel):
    access_token: str = Field(description="Send it with every request: Authorization: Bearer <access_token>")
    refresh_token: str = Field(description="Send it to /api/v1/auth/refresh to get a new access token")
    token_type: str = Field(default="bearer", examples=["bearer"])
    expires_in: int = Field(description="Seconds until the access token expires", examples=[1800])


class RefreshRequest(BaseModel):
    refresh_token: str = Field(description="The refresh token you received at login")


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = Field(default="bearer", examples=["bearer"])
    expires_in: int = Field(description="Seconds until the access token expires", examples=[1800])


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
