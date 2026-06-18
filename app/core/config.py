from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    bot_username: str | None = Field(default=None, alias="BOT_USERNAME")
    telegram_payment_provider_token: str = Field(default="", alias="TELEGRAM_PAYMENT_PROVIDER_TOKEN")
    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")

    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    callback_secret: str = Field(alias="CALLBACK_SECRET", min_length=24)
    payment_currency_default: str = Field(default="RUB", alias="PAYMENT_CURRENCY_DEFAULT")
    invoice_ttl_seconds: int = Field(default=900, alias="INVOICE_TTL_SECONDS", ge=60, le=86_400)

    webhook_mode: bool = Field(default=False, alias="WEBHOOK_MODE")
    webhook_url: str | None = Field(default=None, alias="WEBHOOK_URL")
    webhook_host: str = Field(default="0.0.0.0", alias="WEBHOOK_HOST")
    webhook_port: int = Field(default=8080, alias="WEBHOOK_PORT", ge=1, le=65535)
    create_tables_on_startup: bool = Field(default=False, alias="CREATE_TABLES_ON_STARTUP")
    maintenance_mode: bool = Field(default=False, alias="MAINTENANCE_MODE")

    rate_limit_messages_per_minute: int = Field(default=30, alias="RATE_LIMIT_MESSAGES_PER_MINUTE")
    rate_limit_callbacks_per_minute: int = Field(default=60, alias="RATE_LIMIT_CALLBACKS_PER_MINUTE")
    order_rate_limit_per_hour: int = Field(default=20, alias="ORDER_RATE_LIMIT_PER_HOUR")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("payment_currency_default")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("currency must be an ISO-4217 code")
        return value

    @property
    def admin_ids(self) -> list[int]:
        ids: list[int] = []
        for raw in self.admin_ids_raw.split(","):
            raw = raw.strip()
            if not raw:
                continue
            ids.append(int(raw))
        return ids


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
