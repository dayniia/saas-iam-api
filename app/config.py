from functools import lru_cache
import warnings

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SECRET = "change-me-to-a-long-random-string-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Team Access Control API"
    debug: bool = False
    secret_key: str = _DEFAULT_SECRET
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    database_url: str = "postgresql+asyncpg://tac:tac@localhost:5432/tac"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]
    rate_limit_login: str = "10/minute"
    rate_limit_refresh: str = "20/minute"
    rate_limit_invite: str = "10/minute"

    @model_validator(mode="after")
    def warn_on_default_secret(self) -> "Settings":
        if self.secret_key == _DEFAULT_SECRET:
            warnings.warn(
                "SECRET_KEY is set to the default insecure value. "
                "Set a strong random SECRET_KEY before deploying to production.",
                RuntimeWarning,
                stacklevel=2,
            )
        return self

    @property
    def access_token_expire_seconds(self) -> int:
        return self.access_token_expire_minutes * 60

    @property
    def refresh_token_expire_seconds(self) -> int:
        return self.refresh_token_expire_days * 24 * 60 * 60


@lru_cache
def get_settings() -> Settings:
    return Settings()

