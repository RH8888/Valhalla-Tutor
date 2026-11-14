from functools import lru_cache
from typing import Optional
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Valhalla Tutor"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

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

    # Security Configuration
    SECRET_KEY: str = "dev-secret-key-please-change-in-production-min-32-chars"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

