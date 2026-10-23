import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Override sqlalchemy.url from DATABASE_URL_UNPOOLED or DATABASE_URL env var
current_url = config.get_main_option("sqlalchemy.url")
db_url = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("DATABASE_URL")
if db_url and (
    not current_url
    or current_url == "postgresql+psycopg://postgres:postgres@localhost:5432/plantpulse"
):
    if db_url.startswith("postgresql://") and not db_url.startswith(
        "postgresql+psycopg://"
    ):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    try:
        from db import ensure_ipv4_database_url

        db_url = ensure_ipv4_database_url(db_url)
    except ImportError:
        pass
    config.set_main_option("sqlalchemy.url", db_url)

target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
