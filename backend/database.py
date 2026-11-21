"""SQLite database setup for AgentFlow."""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from backend.models.task import Base


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agentflow.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create database tables if they do not already exist."""

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Tiny migration for databases created before a column existed (SQLite)."""

    columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
    if "owner_hash" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN owner_hash VARCHAR(64)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_owner_hash ON tasks (owner_hash)"))


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session for FastAPI dependencies."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
