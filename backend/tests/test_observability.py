"""Structured logs, request IDs, Prometheus metrics and readiness checks."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from backend import observability
from backend.api import routes


def sample(name: str, **labels: str) -> float:
    """Sum every series of ``name`` whose labels include ``labels``."""

    return sum(
        s.value
        for metric in REGISTRY.collect()
        for s in metric.samples
        if s.name == name and all(s.labels.get(k) == v for k, v in labels.items())
    )


def create_and_run(client: TestClient) -> str:
    task_id = client.post("/api/tasks", json={"task": "What is six times seven?"}).json()["task_id"]
    client.post(f"/api/tasks/{task_id}/execute")
    return task_id


# --- Logs -------------------------------------------------------------------


def test_json_formatter_outputs_one_json_object_per_line() -> None:
    record = logging.LogRecord("agentflow.test", logging.WARNING, __file__, 1, "hello %s", ("world",), None)
    record.task_id = "t-1"
    record.request_id = "r-1"
    record.attempt = 2

    line = observability.JsonFormatter().format(record)
    data = json.loads(line)

    assert "\n" not in line
    assert data["level"] == "warning"
    assert data["logger"] == "agentflow.test"
    assert data["message"] == "hello world"
    assert data["task_id"] == "t-1"
    assert data["request_id"] == "r-1"
    assert data["attempt"] == 2
    assert data["timestamp"].endswith("Z")


def test_json_formatter_includes_exceptions() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    data = json.loads(observability.JsonFormatter().format(record))
    assert "ValueError: boom" in data["exception"]


def test_task_context_tags_every_record(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("agentflow.test")
    with caplog.at_level(logging.INFO, logger="agentflow"):
        with observability.task_context("task-42"):
            logger.info("inside")
        logger.info("outside")

    inside, outside = caplog.records[-2:]
    assert inside.task_id == "task-42"
    assert outside.task_id is None


def test_workflow_logs_carry_the_task_id(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="agentflow"):
        task_id = create_and_run(client)

    tagged = [r for r in caplog.records if getattr(r, "task_id", None) == task_id]
    messages = [r.getMessage() for r in tagged]
    assert any("Task started" in m for m in messages)
    assert any("Task finished" in m for m in messages)
    assert any(getattr(r, "agent", None) == "code_agent" for r in tagged)


def test_backend_has_no_print_calls() -> None:
    from pathlib import Path

    backend = Path(observability.__file__).parent
    offenders = [
        str(path.relative_to(backend))
        for path in backend.rglob("*.py")
        if "tests" not in path.parts
        and path.name != "_child.py"  # the sandbox child talks to its parent through files
        and any(line.lstrip().startswith("print(") for line in path.read_text(encoding="utf-8").splitlines())
    ]
    assert offenders == []


# --- Request IDs ------------------------------------------------------------


def test_request_id_is_generated(client: TestClient) -> None:
    request_id = client.get("/health").headers["x-request-id"]
    assert len(request_id) == 32


def test_valid_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "abc-123_DEF"})
    assert response.headers["x-request-id"] == "abc-123_DEF"


def test_unsafe_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "bad id\nwith newline" + "x" * 100})
    assert response.headers["x-request-id"] != "bad id"
    assert len(response.headers["x-request-id"]) == 32


# --- Metrics ----------------------------------------------------------------


def test_metrics_endpoint_exposes_prometheus_text(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "agentflow_tasks_total" in response.text
    assert "agentflow_http_requests_total" in response.text


def test_task_run_updates_metrics(client: TestClient) -> None:
    before = {
        "completed": sample("agentflow_tasks_total", status="completed"),
        "code_agent": sample("agentflow_agent_duration_seconds_count", agent="code_agent"),
        "attempt_ok": sample("agentflow_code_attempts_total", outcome="success"),
        "sandbox_ok": sample("agentflow_sandbox_runs_total", outcome="ok"),
        "llm_ok": sample("agentflow_llm_requests_total", outcome="success"),
        "task_duration": sample("agentflow_task_duration_seconds_count"),
        "http": sample("agentflow_http_requests_total", method="POST", route="/api/tasks", status="200"),
    }

    create_and_run(client)

    assert sample("agentflow_tasks_total", status="completed") == before["completed"] + 1
    assert sample("agentflow_agent_duration_seconds_count", agent="code_agent") == before["code_agent"] + 1
    assert sample("agentflow_code_attempts_total", outcome="success") == before["attempt_ok"] + 1
    assert sample("agentflow_sandbox_runs_total", outcome="ok") == before["sandbox_ok"] + 1
    assert sample("agentflow_llm_requests_total", outcome="success") == before["llm_ok"] + 3  # plan, code, report
    assert sample("agentflow_task_duration_seconds_count") == before["task_duration"] + 1
    assert sample("agentflow_http_requests_total", method="POST", route="/api/tasks", status="200") == before["http"] + 1


def test_http_metrics_use_route_templates_not_raw_paths(client: TestClient) -> None:
    client.get("/api/tasks/some-random-id/status")
    text = client.get("/metrics").text
    assert 'route="/api/tasks/{task_id}/status"' in text
    assert "some-random-id" not in text


def test_failed_attempts_and_sandbox_errors_are_counted(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.graph.workflow import create_workflow
    from backend.tests.helpers import PLAN_WITHOUT_FILE, REPORT, fake_llm

    monkeypatch.setattr(
        routes, "workflow", create_workflow(llm=fake_llm(PLAN_WITHOUT_FILE, "print(1 / 0)", "print(42)", REPORT))
    )
    failed_before = sample("agentflow_code_attempts_total", outcome="failure")
    errors_before = sample("agentflow_sandbox_runs_total", outcome="error")

    create_and_run(client)

    assert sample("agentflow_code_attempts_total", outcome="failure") == failed_before + 1
    assert sample("agentflow_sandbox_runs_total", outcome="error") == errors_before + 1


def test_unavailable_llm_counts_as_error_task(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "check_llm", lambda: "Ollama is not reachable.")
    before = sample("agentflow_tasks_total", status="error")
    create_and_run(client)
    assert sample("agentflow_tasks_total", status="error") == before + 1


def test_metrics_token_protects_the_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_TOKEN", "s3cret-token")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200


# --- Readiness --------------------------------------------------------------


def test_readiness_reports_each_dependency(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == {"ok": True}
    assert body["checks"]["llm"] == {"ok": True}
    assert body["checks"]["disk"]["ok"] is True
    assert body["checks"]["disk"]["free_mb"] > 0


def test_readiness_is_degraded_without_llm(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "check_llm", lambda: "Ollama is not reachable at http://x.")
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["llm"] == {"ok": False, "detail": "Ollama is not reachable at http://x."}


def test_liveness_stays_minimal(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_readiness_reports_the_deployed_commit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")
    assert client.get("/health/ready").json()["version"] == "abc123"
    monkeypatch.delenv("RENDER_GIT_COMMIT")
    assert client.get("/health/ready").json()["version"] == "dev"
