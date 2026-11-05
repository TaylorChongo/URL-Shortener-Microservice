from pydantic import BaseModel, Field, HttpUrl


class ShortenRequest(BaseModel):
    url: HttpUrl = Field(
        description="The long URL to shorten. Must start with http:// or https://",
        examples=["https://www.amazon.com/Python-Crash-Course-3rd-Edition/dp/1718502702"],
    )


class ShortenResponse(BaseModel):
    short_code: str = Field(description="The unique 6-character code", examples=["aB3xY9"])
    short_url: str = Field(description="The full short link to share", examples=["http://127.0.0.1:8000/api/aB3xY9"])
    original_url: str = Field(
        description="The long URL that was shortened",
        examples=["https://www.amazon.com/Python-Crash-Course-3rd-Edition/dp/1718502702"],
    )


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
