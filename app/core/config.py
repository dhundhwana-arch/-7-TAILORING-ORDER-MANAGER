"""Environment-driven configuration for Module 07 (Tailoring Order Manager)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

WEAK_SECRET_PLACEHOLDERS = {
    "",
    "changeme",
    "secret",
    "CHANGE_ME_BEFORE_PRODUCTION_USE_STRONG_RANDOM_SECRET",
    "CHANGE_ME_BEFORE_PRODUCTION_USE_STRONG_TRACKING_SECRET",
}


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "Tailoring Order Manager (Module 07)"
    APP_VERSION: str = "0.1.0"
    APP_ENV: Literal["development", "testing", "staging", "production"] = "development"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "sqlite:///./tailoring_orders.db"

    AUTH_SECRET_KEY: str = Field(
        default="dev-only-module07-hmac-secret-do-not-use-in-prod-2026"
    )
    TRACKING_TOKEN_SECRET: str = Field(
        default="dev-only-module07-tracking-secret-do-not-use-in-prod-2026"
    )
    AUTH_DEV_HEADER_ENABLED: bool = True
    AUTH_TOKEN_TTL_SECONDS: int = 3600

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 120
    TRACKING_RATE_LIMIT_PER_MINUTE: int = 30

    INTEGRATION_MODE: Literal["mock", "http"] = "mock"
    MODULE_02_FABRIC_BASE_URL: str = "http://localhost:8002"
    MODULE_03_DESIGN_BASE_URL: str = "http://localhost:8003"
    MODULE_04_PREVIEW_BASE_URL: str = "http://localhost:8004"
    MODULE_05_PRICING_BASE_URL: str = "http://localhost:8005"
    MODULE_06_MEASUREMENT_BASE_URL: str = "http://localhost:8006"
    INTEGRATION_HTTP_TIMEOUT_SECONDS: float = 5.0

    NOTIFICATION_PROVIDER: Literal["mock", "disabled"] = "mock"

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.APP_ENV == "production":
            if self.AUTH_DEV_HEADER_ENABLED:
                raise ValueError(
                    "AUTH_DEV_HEADER_ENABLED must be false when APP_ENV=production."
                )
            if (
                self.AUTH_SECRET_KEY in WEAK_SECRET_PLACEHOLDERS
                or "dev-only" in self.AUTH_SECRET_KEY
                or len(self.AUTH_SECRET_KEY) < 32
            ):
                raise ValueError(
                    "AUTH_SECRET_KEY must be a strong secret (>=32 chars) in production."
                )
            if (
                self.TRACKING_TOKEN_SECRET in WEAK_SECRET_PLACEHOLDERS
                or "dev-only" in self.TRACKING_TOKEN_SECRET
                or len(self.TRACKING_TOKEN_SECRET) < 32
            ):
                raise ValueError(
                    "TRACKING_TOKEN_SECRET must be a strong secret (>=32 chars) in production."
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
