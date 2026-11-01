from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from yarl import URL


def normalize_origin(value: str) -> str:
    if any(char.isspace() or ord(char) < 32 for char in value) or "\\" in value:
        raise ValueError("Origins must not contain whitespace or backslashes")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or "*" in parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("Use an exact HTTP(S) origin without a path or credentials")
    # Validate ports, canonicalise case/IDNA, and omit default ports and trailing slashes.
    return str(URL(value).origin())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_base_url: str = "http://localhost:8000"
    app_allowed_origins: list[str] | None = None
    auth_mode: str = "proxy"
    auth_session_secret: SecretStr = SecretStr("")
    auth_session_days: int = Field(30, ge=1, le=90)
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
        return normalize_origin(value)

    @field_validator("app_allowed_origins")
    @classmethod
    def allowed_origins(cls, values):
        if values is None:
            return None
        if not values:
            raise ValueError("APP_ALLOWED_ORIGINS must contain at least one origin")
        origins = list(dict.fromkeys(normalize_origin(value) for value in values))
        authorities = [urlsplit(origin).netloc for origin in origins]
        if len(set(authorities)) != len(authorities):
            raise ValueError("Configure only one public scheme for each host/port")
        return origins

    @property
    def public_origins(self) -> list[str]:
        return (
            self.app_allowed_origins
            if self.app_allowed_origins is not None
            else [self.app_base_url]
        )

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
        if self.auth_mode not in ("proxy", "development", "session"):
            raise ValueError("AUTH_MODE must be proxy, session or development")
        if not self.auth_header or any(c.isspace() for c in self.auth_header):
            raise ValueError("AUTH_HEADER must be a header name")
        if self.auth_mode == "session":
            if len(self.auth_session_secret.get_secret_value()) < 32:
                raise ValueError(
                    "Session mode requires AUTH_SESSION_SECRET of at least 32 characters"
                )
            if not self.rmfakecloud_username or not self.rmfakecloud_password.get_secret_value():
                raise ValueError(
                    "Session mode requires RMFAKECLOUD_USERNAME and RMFAKECLOUD_PASSWORD"
                )
            if any(not origin.startswith("https://") for origin in self.public_origins):
                raise ValueError("Session mode requires HTTPS public origins")
        return self
