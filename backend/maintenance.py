"""Retention for the public demo: delete tasks and files older than a cut-off."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.task import Task
from backend.observability import logger


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except (ValueError, OSError):
        return False


def cleanup_expired(
    db: Session,
    upload_dir: Path,
    max_age: timedelta,
    events: dict[str, Any],
) -> dict[str, int]:
    """Delete finished tasks older than ``max_age`` and stale files in ``upload_dir``.

    Running tasks are kept. Only files inside ``upload_dir`` are ever deleted,
    whatever a task's ``file_path`` says.
    """

    cutoff = datetime.now(timezone.utc) - max_age
    removed_tasks = 0
    removed_files = 0

    for task in db.scalars(select(Task).where(Task.status != "running")).all():
        created = task.created_at if task.created_at.tzinfo else task.created_at.replace(tzinfo=timezone.utc)
        if created >= cutoff:
            continue
        if task.file_path:
            path = Path(task.file_path)
            if _inside(path, upload_dir) and path.is_file():
                path.unlink(missing_ok=True)
                removed_files += 1
        events.pop(task.id, None)
        db.delete(task)
        removed_tasks += 1
    db.commit()

    # Charts and orphaned uploads are judged by their modification time.
    cutoff_ts = time.time() - max_age.total_seconds()
    if upload_dir.is_dir():
        for path in upload_dir.iterdir():
            if path.is_file() and not path.is_symlink() and path.stat().st_mtime < cutoff_ts:
                path.unlink(missing_ok=True)
                removed_files += 1

    if removed_tasks or removed_files:
        logger.info(
            "Retention cleanup removed %s tasks and %s files",
            removed_tasks,
            removed_files,
            extra={"removed_tasks": removed_tasks, "removed_files": removed_files},
        )
    return {"tasks": removed_tasks, "files": removed_files}
