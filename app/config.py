from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./widget_platform.db"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "development-only-change-me-replace-with-32-bytes"
    public_base_url: str = "http://localhost:8000"
    geo_provider_a_url: str = "https://ip-api.com/json/{ip}"
    geo_provider_b_url: str = "https://ipapi.co/{ip}/json/"
    notification_mode: str = "log"
    failure_alert_webhook_url: str | None = None
    rate_limit_ip_per_minute: int = 10
    rate_limit_widget_per_minute: int = 30
    max_public_payload_bytes: int = 16_384
    trust_proxy_headers: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
