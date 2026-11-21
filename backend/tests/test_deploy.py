"""Deployment settings: CORS, retention cleanup and the Render blueprint."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api import routes
from backend.maintenance import cleanup_expired
from backend.models.task import Base, Task

ROOT = Path(__file__).resolve().parents[2]


# --- CORS -------------------------------------------------------------------


def test_cors_origins_default_to_local_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.main import cors_origins

    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert cors_origins() == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_cors_origins_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.main import cors_origins

    monkeypatch.setenv("CORS_ORIGINS", " https://agentflow.vercel.app/ , https://silue.dev ,")
    assert cors_origins() == ["https://agentflow.vercel.app", "https://silue.dev"]


def test_cors_wildcard_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.main import cors_origins

    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ValueError, match="explicit"):
        cors_origins()


def test_only_allowed_origins_get_cors_headers(client: TestClient) -> None:
    allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
    denied = client.get("/health", headers={"Origin": "https://evil.example"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in denied.headers


# --- Retention cleanup ------------------------------------------------------


@pytest.fixture
def db_session(tmp_path: Path):  # noqa: ANN201
    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _age(path: Path, hours: float) -> None:
    stamp = time.time() - hours * 3600
    os.utime(path, (stamp, stamp))


def test_cleanup_removes_tasks_and_files_older_than_24h(db_session, tmp_path: Path) -> None:  # noqa: ANN001
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    old_upload = uploads / "old.csv"
    new_upload = uploads / "new.csv"
    old_chart = uploads / "chart_old.png"
    new_chart = uploads / "chart_new.png"
    for path in (old_upload, new_upload, old_chart, new_chart):
        path.write_text("x", encoding="utf-8")
    for path in (old_upload, old_chart):
        _age(path, 25)

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Task(id="old", task="old", file_path=str(old_upload), status="completed", created_at=now - timedelta(hours=25)),
            Task(id="new", task="new", file_path=str(new_upload), status="completed", created_at=now - timedelta(hours=1)),
        ]
    )
    db_session.commit()
    routes.TASK_EVENTS["old"] = [{"type": "agent_update"}]
    routes.TASK_EVENTS["new"] = [{"type": "agent_update"}]

    removed = cleanup_expired(db_session, uploads, max_age=timedelta(hours=24), events=routes.TASK_EVENTS)

    assert removed == {"tasks": 1, "files": 2}
    assert [t.id for t in db_session.query(Task).all()] == ["new"]
    assert not old_upload.exists() and not old_chart.exists()
    assert new_upload.exists() and new_chart.exists()
    assert "old" not in routes.TASK_EVENTS and "new" in routes.TASK_EVENTS


def test_cleanup_never_leaves_the_upload_directory(db_session, tmp_path: Path) -> None:  # noqa: ANN001
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    outside = tmp_path / "keep-me.txt"
    outside.write_text("x", encoding="utf-8")
    db_session.add(
        Task(
            id="evil",
            task="x",
            file_path=str(outside),
            status="completed",
            created_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
    )
    db_session.commit()

    cleanup_expired(db_session, uploads, max_age=timedelta(hours=24), events={})

    assert outside.exists()


def test_running_tasks_are_not_deleted(db_session, tmp_path: Path) -> None:  # noqa: ANN001
    db_session.add(
        Task(id="busy", task="x", status="running", created_at=datetime.now(timezone.utc) - timedelta(hours=30))
    )
    db_session.commit()
    cleanup_expired(db_session, tmp_path, max_age=timedelta(hours=24), events={})
    assert db_session.get(Task, "busy") is not None


# --- Render blueprint -------------------------------------------------------


@pytest.mark.skipif(
    not (ROOT / "render.yaml").is_file(),
    reason="render.yaml is not copied into the backend image; the plain pytest job covers it",
)
def test_render_blueprint_is_safe_and_complete() -> None:
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    (service,) = blueprint["services"]
    env = {item["key"]: item for item in service["envVars"]}

    assert service["type"] == "web"
    assert service["runtime"] == "docker"
    assert service["dockerfilePath"] == "./backend/Dockerfile"
    assert service["dockerContext"] == "."
    assert service["healthCheckPath"] == "/health"
    assert service["plan"] == "free"
    # Continuous deployment is driven by the deploy workflow (after CI), not by Render.
    assert service["autoDeployTrigger"] == "off"
    assert "autoDeploy" not in service

    assert env["LLM_PROVIDER"]["value"] == "groq"
    # Secrets are never written in the repo: filled in the Render dashboard.
    assert env["GROQ_API_KEY"] == {"key": "GROQ_API_KEY", "sync": False}
    assert env["CORS_ORIGINS"] == {"key": "CORS_ORIGINS", "sync": False}
    assert env["LLM_MODEL"] == {"key": "LLM_MODEL", "sync": False}
    assert env["METRICS_TOKEN"] == {"key": "METRICS_TOKEN", "generateValue": True}
    assert int(env["SANDBOX_MEMORY_MB"]["value"]) <= 512


# --- Client IP behind a proxy -----------------------------------------------


def _request(peer: str, forwarded: str | None):  # noqa: ANN202
    from starlette.requests import Request

    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_client_ip_ignores_forwarded_header_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.main import client_ip

    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    assert client_ip(_request("10.0.0.1", "1.2.3.4")) == "10.0.0.1"


def test_client_ip_reads_from_the_right_behind_one_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.main import client_ip

    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    # A client can put anything on the left; the proxy appends the real address.
    assert client_ip(_request("10.0.0.1", "6.6.6.6, 203.0.113.7")) == "203.0.113.7"
    assert client_ip(_request("10.0.0.1", None)) == "10.0.0.1"


def test_spoofed_forwarded_for_cannot_bypass_rate_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    for index in range(10):
        headers = {"X-Forwarded-For": f"9.9.9.{index}, 203.0.113.7"}
        assert client.post("/api/tasks", json={"task": "hello"}, headers=headers).status_code == 200
    blocked = client.post("/api/tasks", json={"task": "hello"}, headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.7"})
    assert blocked.status_code == 429
