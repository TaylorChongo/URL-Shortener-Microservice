import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import APP_ENV, DEBUG
from app.errors import (
    http_exception_handler,
    unexpected_exception_handler,
    validation_exception_handler,
)
from app.middleware import log_requests
from app.routes import router


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("uvicorn.access").disabled = True
    
    app = FastAPI(
        title="URL Shortener",
        description="Turn long URLs into short codes, and redirect short codes back to the original URL.",
        version="1.0.0",
        debug=DEBUG,
    )
    app.include_router(router)
    app.add_middleware(BaseHTTPMiddleware, dispatch=log_requests)

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)

    @app.get("/health", tags=["health"], summary="Check that the service is running")
    def health():
        return {"status": "ok", "env": APP_ENV}

    return app


app = create_app()
