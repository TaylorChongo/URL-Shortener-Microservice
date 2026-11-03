from fastapi import FastAPI
from app.config import APP_ENV, DEBUG

def create_app() -> FastAPI:
    app = FastAPI(title="URL Shortener", debug=DEBUG)

    @app.get("/health")
    def health():
        return {"status": "ok", "env": APP_ENV}

    return app

app = create_app()
