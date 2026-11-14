from logging.config import fileConfig
from sqlalchemy import create_engine
from alembic import context

from app.core.config import settings
from app.core.database import engine
from app.models import Base

# Alembic Config object
config = context.config

# Interpret config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set model's MetaData object for 'autogenerate' support
target_metadata = Base.metadata

# Ensure sqlalchemy.url is populated from Pydantic settings if not explicitly specified
raw_url = config.get_main_option("sqlalchemy.url")
if not raw_url or "driver://user:pass" in raw_url:
    config.set_main_option("sqlalchemy.url", settings.sync_database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = config.attributes.get("connection", None)
    if connectable is None:
        url = config.get_main_option("sqlalchemy.url")
        if url == settings.sync_database_url:
            connectable = engine
        else:
            connectable = create_engine(url)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
