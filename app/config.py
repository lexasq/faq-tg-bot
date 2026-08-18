from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    TELEGRAM_BOT_TOKEN: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    FIRESTORE_PROJECT_ID: str = ""
    LOG_LEVEL: str = "INFO"
    ENV: str = "dev"


def get_settings() -> Settings:
    return Settings()
