from fastapi import FastAPI
from app.config import APP_ENV, DEBUG
from app.routes import router

def create_app() -> FastAPI:
    app = FastAPI(title="URL Shortener", debug=DEBUG)
    app.include_router(router)

    @app.get("/health")
    def health():
        return {"status": "ok", "env": APP_ENV}

    return app

app = create_app()
