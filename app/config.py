from decouple import config

APP_ENV = config("APP_ENV", default="development")
DEBUG = config("DEBUG", default=False, cast=bool)
BASE_URL = config("BASE_URL", default="http://127.0.0.1:8000")
DATABASE_URL = config("DATABASE_URL")
GEOIP_DATABASE_PATH = config("GEOIP_DATABASE_PATH", default="data/dbip-city-lite.mmdb")

# JWT: no default for the secret on purpose, the app refuses to start without one
JWT_SECRET_KEY = config("JWT_SECRET_KEY")
ACCESS_TOKEN_MINUTES = config("ACCESS_TOKEN_MINUTES", default=30, cast=int)
REFRESH_TOKEN_DAYS = config("REFRESH_TOKEN_DAYS", default=7, cast=int)

# how many login attempts one address may make, e.g. "5/minute"
LOGIN_RATE_LIMIT = config("LOGIN_RATE_LIMIT", default="5/minute")
