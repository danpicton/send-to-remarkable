from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_base_url: str = "http://localhost:8000"
    auth_mode: str = "proxy"
    auth_header: str = "X-Auth-Request-User"
    rmfakecloud_url: str = ""
    rmfakecloud_username: str = ""
    rmfakecloud_password: SecretStr = SecretStr("")
    rmfakecloud_verify_tls: bool = True
    rmfakecloud_ca_bundle: str | None = None
    fetch_timeout: float = Field(20, gt=0, le=120)
    conversion_timeout: float = Field(40, gt=0, le=120)
    rmfakecloud_timeout: float = Field(20, gt=0, le=120)
    max_page_bytes: int = Field(4 * 1024 * 1024, ge=1024, le=16 * 1024 * 1024)
    max_document_bytes: int = Field(20 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    max_article_chars: int = Field(200_000, ge=1000, le=1_000_000)
    max_conversions: int = Field(2, ge=1, le=4)
    worker_memory_mb: int = Field(768, ge=256, le=2048)
    temp_dir: Path = Path("/tmp/send-to-remarkable")

    @field_validator("app_base_url")
    @classmethod
    def public_origin(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("APP_BASE_URL must be an HTTP(S) origin without a path or credentials")
        return value.rstrip("/")

    @field_validator("rmfakecloud_url")
    @classmethod
    def cloud_origin(cls, value):
        if not value:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("RMFAKECLOUD_URL must be an HTTP(S) server URL")
        return value.rstrip("/")

    @model_validator(mode="after")
    def auth_config(self):
        if self.auth_mode not in ("proxy", "development"):
            raise ValueError("AUTH_MODE must be proxy or development")
        if not self.auth_header or any(c.isspace() for c in self.auth_header):
            raise ValueError("AUTH_HEADER must be a header name")
        return self
