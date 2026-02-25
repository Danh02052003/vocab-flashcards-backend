import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    mongo_url: str
    mongo_db: str
    openai_api_key: str
    tz: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    tz = (os.getenv("TZ") or "Asia/Ho_Chi_Minh").strip() or "Asia/Ho_Chi_Minh"
    return Settings(
        mongo_url=(os.getenv("MONGO_URL") or "").strip(),
        mongo_db=(os.getenv("MONGO_DB") or "").strip(),
        openai_api_key=(os.getenv("OPENAI_API_KEY") or "").strip(),
        tz=tz,
    )


def validate_mongo_settings(settings: Settings | None = None) -> Settings:
    cfg = settings or get_settings()
    if not cfg.mongo_url or not cfg.mongo_db:
        raise RuntimeError(
            "Missing required env vars: MONGO_URL and MONGO_DB. "
            "Copy .env.example to .env and set both values before starting the app."
        )
    return cfg
