"""SQLAlchemy task model for persisted AgentFlow tasks."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


class Task(Base):
    """Persisted task execution record."""

    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_status", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    agents_used: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
