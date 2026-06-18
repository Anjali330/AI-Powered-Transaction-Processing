"""
Run as: .venv\Scripts\python.exe migrate.py
Runs alembic upgrade head with DATABASE_URL pointed at localhost
so migrations work from the host machine against the Docker postgres container.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://app:app@localhost:5432/transactions"

from alembic.config import Config
from alembic import command

cfg = Config("alembic.ini")
command.upgrade(cfg, "head")
