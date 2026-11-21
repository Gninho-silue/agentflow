"""HTTP API tests (FastAPI TestClient, isolated DB, fake-LLM workflow)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import routes


def create(client: TestClient, task: str = "What is six times seven?", **extra: object) -> str:
    response = client.post("/api/tasks", json={"task": task, **extra})
    assert response.status_code == 200, response.text
    return response.json()["task_id"]


# --- Health -----------------------------------------------------------------


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


# --- Create -----------------------------------------------------------------


def test_create_task_returns_id_and_pending_status(client: TestClient) -> None:
    task_id = create(client, task="  Compute something  ")
    status = client.get(f"/api/tasks/{task_id}/status").json()

    assert status["task_id"] == task_id
    assert status["task"] == "Compute something"  # stripped
    assert status["status"] == "pending"
    assert status["result"] is None
    assert status["agents_used"] == []


@pytest.mark.parametrize("task", ["", "   ", "x" * 2001])
def test_create_task_rejects_invalid_text(client: TestClient, task: str) -> None:
    assert client.post("/api/tasks", json={"task": task}).status_code == 422


def test_create_task_requires_task_field(client: TestClient) -> None:
    assert client.post("/api/tasks", json={}).status_code == 422


# --- Execute + status -------------------------------------------------------


def test_execute_runs_workflow_and_persists_result(client: TestClient) -> None:
    task_id = create(client)

    response = client.post(f"/api/tasks/{task_id}/execute")
    assert response.json() == {"task_id": task_id, "status": "running"}

    # TestClient runs background tasks before returning, so the run is finished.
    status = client.get(f"/api/tasks/{task_id}/status").json()
    assert status["status"] == "completed"
    assert status["error"] is None
    assert status["execution_time"] is not None
    assert status["agents_used"] == ["planner", "code_agent", "reporter", "supervisor"]
    assert status["result"]["code_output"] == "42"
    assert status["result"]["report"].startswith("# Summary")

    events = routes.TASK_EVENTS[task_id]
    assert events[0]["agent"] == "created"
    updates = [e for e in events if e["type"] == "agent_update"]
    assert [e["agent"] for e in updates[2:-1]] == ["planner", "code_agent", "reporter", "supervisor"]
    assert [e["type"] for e in events].count("code_attempt") == 1
    assert events[-1]["status"] == "completed"


def test_code_attempts_are_persisted_and_streamed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.graph.workflow import create_workflow
    from backend.tests.helpers import PLAN_WITHOUT_FILE, REPORT, fake_llm

    monkeypatch.setattr(
        routes,
        "workflow",
        create_workflow(llm=fake_llm(PLAN_WITHOUT_FILE, "print(1 / 0)", "print(6 * 7)", REPORT)),
    )
    task_id = create(client)
    client.post(f"/api/tasks/{task_id}/execute")

    result = client.get(f"/api/tasks/{task_id}/status").json()["result"]
    assert [a["attempt"] for a in result["code_attempts"]] == [1, 2]
    assert result["code_attempts"][0]["error"] == "division by zero"

    attempt_events = [e for e in routes.TASK_EVENTS[task_id] if e["type"] == "code_attempt"]
    assert [e["attempt"] for e in attempt_events] == [1, 2]
    assert attempt_events[0]["code"] == "print(1 / 0)"
    assert attempt_events[0]["error"] == "division by zero"
    assert "ZeroDivisionError" in attempt_events[0]["traceback"]
    assert attempt_events[1]["error"] is None

    with client.websocket_connect(f"/ws/{task_id}") as ws:
        streamed = []
        while (message := ws.receive_json())["type"] != "complete":
            streamed.append(message)
    assert [m["attempt"] for m in streamed if m["type"] == "code_attempt"] == [1, 2]


def test_execute_unknown_task_returns_404(client: TestClient) -> None:
    assert client.post("/api/tasks/does-not-exist/execute").status_code == 404


def test_status_unknown_task_returns_404(client: TestClient) -> None:
    assert client.get("/api/tasks/does-not-exist/status").status_code == 404


def test_execute_with_file_path_updates_task(client: TestClient) -> None:
    task_id = create(client)
    client.post(f"/api/tasks/{task_id}/execute", json={"file_path": "uploads/data.csv"})
    assert client.get(f"/api/tasks/{task_id}/status").json()["file_path"] == "uploads/data.csv"


def test_workflow_crash_marks_task_as_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CrashingWorkflow:
        def stream(self, _state: object) -> object:
            raise RuntimeError("graph crashed")

    monkeypatch.setattr(routes, "workflow", CrashingWorkflow())
    task_id = create(client)
    client.post(f"/api/tasks/{task_id}/execute")

    status = client.get(f"/api/tasks/{task_id}/status").json()
    assert status["status"] == "error"
    assert status["error"] == "graph crashed"
    assert routes.TASK_EVENTS[task_id][-1]["status"] == "error"


# --- List + delete ----------------------------------------------------------


def test_list_tasks_newest_first(client: TestClient) -> None:
    first = create(client, task="first task")
    second = create(client, task="second task")

    ids = [t["task_id"] for t in client.get("/api/tasks").json()]
    assert ids == [second, first]


def test_delete_task(client: TestClient) -> None:
    task_id = create(client)

    assert client.delete(f"/api/tasks/{task_id}").json() == {"deleted": True}
    assert client.get(f"/api/tasks/{task_id}/status").status_code == 404
    assert task_id not in routes.TASK_EVENTS
    assert client.delete(f"/api/tasks/{task_id}").status_code == 404


def test_delete_all_tasks(client: TestClient) -> None:
    create(client)
    create(client)

    assert client.delete("/api/tasks").json() == {"deleted": 2}
    assert client.get("/api/tasks").json() == []


# --- Upload -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["data.csv", "data.JSON", "notes.txt"])
def test_upload_accepts_allowed_types(client: TestClient, name: str) -> None:
    response = client.post("/api/upload", files={"file": (name, b"a,b\n1,2\n", "text/plain")})

    assert response.status_code == 200
    saved = Path(response.json()["file_path"])
    assert saved.parent.resolve() == routes.UPLOAD_DIR.resolve()
    assert saved.suffix == Path(name).suffix.lower()
    assert saved.stem != Path(name).stem  # renamed to a random UUID
    assert saved.read_bytes() == b"a,b\n1,2\n"


@pytest.mark.parametrize("name", ["script.py", "evil.exe", "archive.csv.zip", "noextension"])
def test_upload_rejects_disallowed_types(client: TestClient, name: str) -> None:
    response = client.post("/api/upload", files={"file": (name, b"data", "text/plain")})
    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]


def test_upload_rejects_files_over_size_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "_MAX_UPLOAD_BYTES", 10)
    response = client.post("/api/upload", files={"file": ("big.csv", b"x" * 11, "text/csv")})
    assert response.status_code == 400
    assert "size limit" in response.json()["detail"]


def test_request_body_over_15mb_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/upload",
        content=b"x",
        headers={"content-length": str(16 * 1024 * 1024), "content-type": "text/plain"},
    )
    assert response.status_code == 413


def test_upload_path_traversal_filename_is_neutralized(client: TestClient) -> None:
    response = client.post(
        "/api/upload", files={"file": ("../../etc/passwd.txt", b"x", "text/plain")}
    )
    assert response.status_code == 200
    saved = Path(response.json()["file_path"])
    assert saved.parent.resolve() == routes.UPLOAD_DIR.resolve()


# --- Rate limiting ----------------------------------------------------------


def test_create_task_is_rate_limited_to_10_per_minute(client: TestClient) -> None:
    for _ in range(10):
        assert client.post("/api/tasks", json={"task": "hello"}).status_code == 200

    response = client.post("/api/tasks", json={"task": "hello"})
    assert response.status_code == 429
    assert "Too many requests" in response.json()["detail"]


def test_rate_limit_only_applies_to_task_creation(client: TestClient) -> None:
    for _ in range(12):
        assert client.get("/api/tasks").status_code == 200


def test_rate_limit_window_expires(client: TestClient) -> None:
    import backend.main as main

    for _ in range(10):
        client.post("/api/tasks", json={"task": "hello"})
    assert client.post("/api/tasks", json={"task": "hello"}).status_code == 429

    # Age every recorded request past the 60 s window.
    for ip, stamps in main._rate_timestamps.items():
        main._rate_timestamps[ip] = [t - 61 for t in stamps]
    assert client.post("/api/tasks", json={"task": "hello"}).status_code == 200


# --- WebSocket --------------------------------------------------------------


def test_websocket_streams_events_then_final_task(client: TestClient) -> None:
    task_id = create(client)
    client.post(f"/api/tasks/{task_id}/execute")

    messages = []
    with client.websocket_connect(f"/ws/{task_id}") as ws:
        while True:
            message = ws.receive_json()
            messages.append(message)
            if message["type"] == "complete":
                break

    types = [m["type"] for m in messages]
    assert types[0] == "agent_update"
    assert types[-2:] == ["task", "complete"]
    assert messages[-2]["task"]["status"] == "completed"
    assert messages[-1] == {"type": "complete", "status": "completed"}


def test_websocket_unknown_task_sends_error(client: TestClient) -> None:
    with client.websocket_connect("/ws/does-not-exist") as ws:
        assert ws.receive_json() == {"type": "error", "message": "Task not found."}
