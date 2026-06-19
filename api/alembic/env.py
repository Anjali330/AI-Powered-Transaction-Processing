import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# api/alembic/env.py  →  parents[0]=alembic/  parents[1]=api/  parents[2]=project_root/
API_DIR = Path(__file__).resolve().parents[1]       # api/
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # project_root/

# Ensure `app.*` imports resolve when alembic is invoked from any working directory
sys.path.insert(0, str(API_DIR))

# Load .env from project root for local dev — silently skip in Docker (env vars injected via env_file)
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Copy .env.example to .env and fill in the value."
    )
config.set_main_option("sqlalchemy.url", database_url)

# Import all models so their metadata is registered
import app.models  # noqa: F401, E402
from app.database import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
