from decouple import config

APP_ENV = config("APP_ENV", default="development")
DEBUG = config("DEBUG", default=False, cast=bool)
BASE_URL = config("BASE_URL", default="http://127.0.0.1:8000")
DATABASE_URL = config("DATABASE_URL")
