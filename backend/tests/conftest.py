"""Shared fixtures for AgentFlow backend tests.

Rules: tests never call a real LLM (scripted fake models only) and never touch
the developer's ``agentflow.db`` or ``uploads/`` folder.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Must be set before ``backend.api.routes`` is imported (read at import time).
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="agentflow-tests-"))
os.environ["UPLOAD_DIR"] = str(_TEST_ROOT / "uploads")
os.environ["RETENTION_HOURS"] = "0"  # no background cleanup loop in tests

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.tests.helpers import PLAN_WITHOUT_FILE, REPORT, fake_llm  # noqa: E402


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """A tiny sales CSV file."""

    path = tmp_path / "sales.csv"
    path.write_text("category,total\nA,10\nB,5\nA,7\n", encoding="utf-8")
    return path


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator["TestClient"]:  # noqa: F821
    """FastAPI TestClient with an isolated SQLite DB and a fake-LLM workflow."""

    from fastapi.testclient import TestClient

    import backend.main as main
    from backend.api import routes
    from backend.database import get_db
    from backend.graph.workflow import create_workflow
    from backend.models.task import Base

    monkeypatch.chdir(tmp_path)  # charts and relative paths land in tmp_path

    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db() -> Iterator[object]:
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(routes, "SessionLocal", testing_session)
    monkeypatch.setattr(
        routes,
        "workflow",
        create_workflow(llm=fake_llm(PLAN_WITHOUT_FILE, "print(6 * 7)", REPORT)),
    )
    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(routes, "check_llm", lambda: None)  # never probe a real LLM
    main.app.dependency_overrides[get_db] = override_get_db
    main._rate_timestamps.clear()
    routes.TASK_EVENTS.clear()

    with TestClient(main.app) as test_client:
        test_client.headers["X-Client-ID"] = "test-visitor-0123456789abcdef"
        yield test_client

    main.app.dependency_overrides.clear()
    main._rate_timestamps.clear()
    engine.dispose()
