from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


_INSECURE_SECRET_KEYS = {
    "dev-secret-key-please-change-in-production-min-32-chars",
    "replace_with_strong_random_secret_key_min_32_chars",
    "changeme",
    "secret",
}

_INSECURE_DB_PASSWORDS = {
    "postgres",
    "replace_with_strong_random_db_password",
    "changeme",
}


class Settings(BaseSettings):
    APP_NAME: str = "Valhalla Tutor"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Timezone Configuration: Default is Asia/Tehran, but user timezones remain configurable
    DEFAULT_TIMEZONE: str = "Asia/Tehran"

    # Server Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # PostgreSQL Database Configuration
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "valhalla_db"
    DATABASE_URL: Optional[str] = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 15
    DB_POOL_RECYCLE: int = 1800

    # Security Configuration
    SECRET_KEY: str = "dev-secret-key-please-change-in-production-min-32-chars"
    TRUSTED_PROXIES: str = "127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8"

    # Uploads Configuration
    UPLOAD_DIR: str = "uploads"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @computed_field
    @property
    def sync_database_url(self) -> str:
        if self.DATABASE_URL:
            # Normalize postgres:// or postgresql:// to postgresql+psycopg2://
            url = self.DATABASE_URL
            if url.startswith("postgresql://"):
                return url.replace("postgresql://", "postgresql+psycopg2://", 1)
            if url.startswith("postgres://"):
                return url.replace("postgres://", "postgresql+psycopg2://", 1)
            return url
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    def validate_production_settings(self) -> None:
        """Fail closed when running in production with insecure or default credentials."""
        if (self.ENVIRONMENT or "").strip().lower() != "production":
            return

        secret = (self.SECRET_KEY or "").strip()
        if (
            len(secret) < 32
            or secret.lower() in _INSECURE_SECRET_KEYS
            or secret.lower().startswith(("dev-secret-key", "replace_with_"))
        ):
            raise RuntimeError(
                "Refusing to start in production with default or weak SECRET_KEY (minimum 32 non-default chars)."
            )

        if self.DATABASE_URL:
            parsed = urlparse(self.DATABASE_URL)
            if parsed.scheme.startswith("postgres"):
                db_password = (parsed.password or "").strip()
                if (
                    not db_password
                    or db_password.lower() in _INSECURE_DB_PASSWORDS
                    or db_password.lower().startswith("replace_with_")
                ):
                    raise RuntimeError(
                        "Refusing to start in production with default or empty PostgreSQL password in DATABASE_URL."
                    )
        else:
            db_password = (self.POSTGRES_PASSWORD or "").strip()
            if (
                not db_password
                or db_password.lower() in _INSECURE_DB_PASSWORDS
                or db_password.lower().startswith("replace_with_")
            ):
                raise RuntimeError(
                    "Refusing to start in production with default or empty POSTGRES_PASSWORD."
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

