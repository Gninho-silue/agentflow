"""The production smoke test used by the deploy workflow (no network here)."""

from __future__ import annotations

import json
from typing import Any

import pytest

# scripts/ is not copied into the backend image; the plain pytest job covers it.
smoke_test = pytest.importorskip("scripts.smoke_test")


class FakeHttp:
    """Scripted responses keyed by (method, path); each key pops its next answer."""

    def __init__(self, answers: dict[tuple[str, str], list[tuple[int, Any]]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, url: str, body: dict | None = None) -> tuple[int, Any]:
        path = url.split("://", 1)[1].split("/", 1)[1]
        self.calls.append((method, "/" + path))
        queue = self.answers[(method, "/" + path)]
        return queue.pop(0) if len(queue) > 1 else queue[0]


def test_waits_until_the_new_commit_is_live() -> None:
    http = FakeHttp(
        {
            ("GET", "/health/ready"): [
                (200, {"status": "ready", "version": "old"}),
                (503, {"status": "degraded", "version": "new"}),
                (200, {"status": "ready", "version": "new"}),
            ]
        }
    )
    smoke_test.wait_for_version("https://api", "new", http=http, timeout=10, interval=0)
    assert len(http.calls) == 3


def test_gives_up_when_the_commit_never_arrives() -> None:
    http = FakeHttp({("GET", "/health/ready"): [(200, {"status": "ready", "version": "old"})]})
    with pytest.raises(smoke_test.SmokeTestError, match="never served commit new"):
        smoke_test.wait_for_version("https://api", "new", http=http, timeout=0, interval=0)


def test_runs_a_real_task_end_to_end() -> None:
    http = FakeHttp(
        {
            ("POST", "/api/tasks"): [(200, {"task_id": "t1"})],
            ("POST", "/api/tasks/t1/execute"): [(200, {"status": "running"})],
            ("GET", "/api/tasks/t1/status"): [
                (200, {"status": "running"}),
                (200, {"status": "completed", "result": {"report": "# Report\n42"}}),
            ],
        }
    )
    report = smoke_test.run_task("https://api", http=http, timeout=10, interval=0)
    assert "42" in report


def test_failed_task_fails_the_smoke_test() -> None:
    http = FakeHttp(
        {
            ("POST", "/api/tasks"): [(200, {"task_id": "t1"})],
            ("POST", "/api/tasks/t1/execute"): [(200, {"status": "running"})],
            ("GET", "/api/tasks/t1/status"): [(200, {"status": "error", "error": "LLM down"})],
        }
    )
    with pytest.raises(smoke_test.SmokeTestError, match="LLM down"):
        smoke_test.run_task("https://api", http=http, timeout=10, interval=0)


def test_frontend_check_looks_for_the_app_shell() -> None:
    ok = FakeHttp({("GET", "/"): [(200, '<html><title>AgentFlow · Multi-agent</title><div id="root">')]})
    smoke_test.check_frontend("https://web", http=ok)
    broken = FakeHttp({("GET", "/"): [(200, "<html>404</html>")]})
    with pytest.raises(smoke_test.SmokeTestError):
        smoke_test.check_frontend("https://web", http=broken)


def test_payloads_are_json(monkeypatch: pytest.MonkeyPatch) -> None:
    assert json.loads(json.dumps(smoke_test.TASK))["task"]
