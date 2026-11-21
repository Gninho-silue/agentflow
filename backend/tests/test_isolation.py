"""Each visitor only sees and controls their own tasks; uploads stay uploads."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from backend.api import routes

ALICE = {"X-Client-ID": "alice-0123456789abcdef0123"}
BOB = {"X-Client-ID": "bob-0123456789abcdef012345"}


def create(client: TestClient, headers: dict[str, str], **body: object) -> str:
    response = client.post("/api/tasks", json={"task": "What is six times seven?", **body}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["task_id"]


# --- Visitor identity ---------------------------------------------------------


@pytest.mark.parametrize("method,path", [("GET", "/api/tasks"), ("DELETE", "/api/tasks"), ("POST", "/api/upload")])
def test_requests_without_client_id_are_rejected(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, headers={"X-Client-ID": ""})
    assert response.status_code == 400
    assert "X-Client-ID" in response.json()["detail"]


@pytest.mark.parametrize("bad", ["short", "has spaces in it 123456", "x" * 200, "semi;colon;0123456789abcdef"])
def test_malformed_client_ids_are_rejected(client: TestClient, bad: str) -> None:
    assert client.get("/api/tasks", headers={"X-Client-ID": bad}).status_code == 400


# --- Isolation ----------------------------------------------------------------


def test_visitors_only_list_their_own_tasks(client: TestClient) -> None:
    alice_task = create(client, ALICE)
    bob_task = create(client, BOB)

    assert [t["task_id"] for t in client.get("/api/tasks", headers=ALICE).json()] == [alice_task]
    assert [t["task_id"] for t in client.get("/api/tasks", headers=BOB).json()] == [bob_task]


def test_other_visitors_tasks_look_like_they_do_not_exist(client: TestClient) -> None:
    task_id = create(client, ALICE)

    assert client.get(f"/api/tasks/{task_id}/status", headers=BOB).status_code == 404
    assert client.post(f"/api/tasks/{task_id}/execute", headers=BOB).status_code == 404
    assert client.delete(f"/api/tasks/{task_id}", headers=BOB).status_code == 404
    assert client.get(f"/api/tasks/{task_id}/status", headers=ALICE).status_code == 200


def test_clear_all_only_clears_my_history(client: TestClient) -> None:
    create(client, ALICE)
    create(client, ALICE)
    bob_task = create(client, BOB)
    routes.TASK_EVENTS[bob_task].append({"type": "agent_update"})

    assert client.delete("/api/tasks", headers=ALICE).json() == {"deleted": 2}
    assert client.get("/api/tasks", headers=ALICE).json() == []
    assert [t["task_id"] for t in client.get("/api/tasks", headers=BOB).json()] == [bob_task]
    assert bob_task in routes.TASK_EVENTS


def test_websocket_requires_the_owner(client: TestClient) -> None:
    task_id = create(client, ALICE)
    client.post(f"/api/tasks/{task_id}/execute", headers=ALICE)

    with client.websocket_connect(f"/ws/{task_id}?client_id={BOB['X-Client-ID']}") as ws:
        assert ws.receive_json() == {"type": "error", "message": "Task not found."}
    with client.websocket_connect(f"/ws/{task_id}") as ws:
        assert ws.receive_json() == {"type": "error", "message": "Task not found."}
    with client.websocket_connect(f"/ws/{task_id}?client_id={ALICE['X-Client-ID']}") as ws:
        first = ws.receive_json()
    assert first["type"] in {"agent_update", "task", "code_attempt"}


def test_tasks_store_a_hash_not_the_client_id(client: TestClient) -> None:
    task_id = create(client, ALICE)
    with routes.SessionLocal() as db:
        owner = db.get(routes.Task, task_id).owner_hash
    assert owner and ALICE["X-Client-ID"] not in owner and len(owner) == 64


# --- file_path must be one of our uploads --------------------------------------


@pytest.mark.parametrize("path_factory", ["etc_passwd", "backend_source", "outside_tmp", "missing_upload"])
def test_file_path_outside_uploads_is_refused(client: TestClient, tmp_path: Path, path_factory: str) -> None:
    outside = tmp_path / "secret.csv"
    outside.write_text("token\nTOP-SECRET\n", encoding="utf-8")
    candidates = {
        "etc_passwd": "/etc/passwd",
        "backend_source": str(Path(routes.__file__).resolve()),
        "outside_tmp": str(outside),
        "missing_upload": str(routes.UPLOAD_DIR / "does-not-exist.csv"),
    }
    path = candidates[path_factory]

    response = client.post("/api/tasks", json={"task": "Read it", "file_path": path}, headers=ALICE)
    assert response.status_code == 400
    assert "upload" in response.json()["detail"].lower()

    task_id = create(client, ALICE)
    response = client.post(f"/api/tasks/{task_id}/execute", json={"file_path": path}, headers=ALICE)
    assert response.status_code == 400


def test_uploaded_file_can_be_used(client: TestClient) -> None:
    upload = client.post(
        "/api/upload", files={"file": ("data.csv", b"a,b\n1,2\n", "text/csv")}, headers=ALICE
    ).json()["file_path"]
    task_id = create(client, ALICE, file_path=upload)
    assert client.get(f"/api/tasks/{task_id}/status", headers=ALICE).json()["file_path"] == upload


# --- Existing databases -------------------------------------------------------


def test_init_db_adds_the_owner_column_to_an_old_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend import database

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tasks (id VARCHAR(36) PRIMARY KEY, task TEXT NOT NULL, status VARCHAR(24))"))
    monkeypatch.setattr(database, "engine", engine)

    database.init_db()

    assert "owner_hash" in {column["name"] for column in inspect(engine).get_columns("tasks")}
    engine.dispose()
