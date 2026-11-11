from logging.config import fileConfig
from sqlalchemy import create_engine, pool
from alembic import context

from backend.config import settings
from backend.database import Base
# Import all SQLAlchemy models to ensure complete metadata registration
import backend.models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def get_database_url() -> str:
    """Retrieves and normalizes the database URL for migrations."""
    configured_url = config.get_main_option("sqlalchemy.url") or settings.DATABASE_URL
    if configured_url.startswith("postgres://"):
        configured_url = configured_url.replace("postgres://", "postgresql://", 1)
    return configured_url

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_database_url()
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
    url = get_database_url()
    connectable = create_engine(
        url,
        poolclass=pool.NullPool,
    )

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
