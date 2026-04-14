from __future__ import annotations

from pydantic import EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_password: str = "change-me"
    app_secret_key: str = "change-me-too"
    db_url: str = "sqlite:///job_tracker.sqlite3"

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    reminder_to: EmailStr | None = None

    # Chrome extension capture API (localhost)
    capture_api_token: str = "change-me-capture-token"
    capture_api_host: str = "127.0.0.1"
    capture_api_port: int = 8765


settings = Settings()

