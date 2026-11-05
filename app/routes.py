from fastapi import APIRouter, Depends, status

from app.config import BASE_URL
from app.dependencies import get_shortener_service
from app.schemas import ShortenRequest, ShortenResponse
from app.services import UrlShortenerService


router = APIRouter(prefix="/api", tags=["shortener"])

@router.post("/shorten", response_model=ShortenResponse, status_code=status.HTTP_201_CREATED)
def create_short_url(
        body: ShortenRequest,
        service: UrlShortenerService = Depends(get_shortener_service)
) -> ShortenResponse:
    original_url = str(body.url)
    code = service.shorten(original_url)

    return ShortenResponse(
        short_code = code,
        short_url = f"{BASE_URL}/api/{code}",
        original_url = original_url
    )
    