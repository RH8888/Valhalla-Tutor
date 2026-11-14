from app.core.config import Settings


def test_settings_default_values():
    settings = Settings(
        POSTGRES_SERVER="db.example.com",
        POSTGRES_PORT=5432,
        POSTGRES_USER="myuser",
        POSTGRES_PASSWORD="mypassword",
        POSTGRES_DB="testdb",
    )
    assert settings.DEFAULT_TIMEZONE == "Asia/Tehran"
    assert settings.PORT == 8000
    assert settings.sync_database_url == (
        "postgresql+psycopg2://myuser:mypassword@db.example.com:5432/testdb"
    )


def test_settings_custom_database_url():
    settings = Settings(
        DATABASE_URL="postgresql://user:pass@localhost:5432/custom_db"
    )
    assert settings.sync_database_url == (
        "postgresql+psycopg2://user:pass@localhost:5432/custom_db"
    )

