from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import APP_ENV, DEBUG
from app.errors import (
    http_exception_handler,
    unexpected_exception_handler,
    validation_exception_handler,
)
from app.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="URL Shortener", debug=DEBUG)
    app.include_router(router)

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)

    @app.get("/health")
    def health():
        return {"status": "ok", "env": APP_ENV}

    return app


app = create_app()
