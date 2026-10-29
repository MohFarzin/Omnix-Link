from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Egg cwd is /home/container — keep .env + sqlite next to app.py
_ROOT = Path(__file__).resolve().parents[1]
_ENV = _ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV) if _ENV.exists() else ".env",
        extra="ignore",
    )

    app_name: str = "Omnix Link"
    app_url: str = "http://127.0.0.1:8787"
    secret_key: str = "dev-only-change-me"
    database_url: str = f"sqlite:///{(_ROOT / 'data' / 'omnix_link.sqlite').as_posix()}"

    google_client_id: str = ""
    google_client_secret: str = ""
    discord_client_id: str = ""
    discord_client_secret: str = ""

    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    kick_client_id: str = ""
    kick_client_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
