"""Production smoke test run by .github/workflows/deploy.yml after each deploy.

1. Wait until the backend serves the new commit and is ready (LLM included).
2. Run one real task end to end through the public API.
3. Check that the frontend serves the app shell.

Standard library only, so it runs on a bare GitHub runner:

    python scripts/smoke_test.py --api https://… --web https://… --commit <sha>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

Http = Callable[..., tuple[int, Any]]

TASK = {"task": "Compute 6 times 7 with Python and report the result in one sentence."}
_USER_AGENT = "AgentFlow-smoke-test/1.0"


class SmokeTestError(RuntimeError):
    """The deployment is not healthy."""


def http(method: str, url: str, body: dict | None = None) -> tuple[int, Any]:
    """Tiny JSON/text HTTP client; returns (status, parsed JSON or text)."""

    data = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=data, method=method, headers={"User-Agent": _USER_AGENT})
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=60) as response:  # noqa: S310 - URLs come from CLI args
            status, raw = response.status, response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        status, raw = exc.code, exc.read().decode("utf-8", "replace")
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


def wait_for_version(api: str, commit: str, http: Http = http, timeout: float = 900, interval: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            status, body = http("GET", f"{api}/health/ready")
        except OSError as exc:  # cold start, deploy switching over...
            status, body = 0, {"error": str(exc)}
        if status == 200 and isinstance(body, dict) and body.get("version") == commit:
            print(f"Backend serves {commit} and is ready.")
            return
        if time.monotonic() >= deadline:
            raise SmokeTestError(f"The backend never served commit {commit} in a ready state. Last answer: {status} {body}")
        print(f"Waiting for backend: {status} {body if isinstance(body, dict) else ''}")
        time.sleep(interval)


def run_task(api: str, http: Http = http, timeout: float = 300, interval: float = 5) -> str:
    status, created = http("POST", f"{api}/api/tasks", TASK)
    if status != 200:
        raise SmokeTestError(f"Task creation failed: {status} {created}")
    task_id = created["task_id"]
    http("POST", f"{api}/api/tasks/{task_id}/execute", {})

    deadline = time.monotonic() + timeout
    while True:
        _, task = http("GET", f"{api}/api/tasks/{task_id}/status")
        if task.get("status") == "completed":
            report = (task.get("result") or {}).get("report") or ""
            if not report.strip():
                raise SmokeTestError("Task completed with an empty report.")
            print(f"Task {task_id} completed.")
            return report
        if task.get("status") == "error":
            raise SmokeTestError(f"Task {task_id} failed: {task.get('error')}")
        if time.monotonic() >= deadline:
            raise SmokeTestError(f"Task {task_id} did not finish within {timeout:.0f}s.")
        time.sleep(interval)


def check_frontend(web: str, http: Http = http, api: str | None = None) -> None:
    status, page = http("GET", f"{web}/")
    if status != 200 or not isinstance(page, str) or "<title>AgentFlow" not in page or 'id="root"' not in page:
        raise SmokeTestError(f"Frontend did not serve the app shell: {status}")
    if api:
        # The API URL is baked into the bundle at build time: make sure it is the real one.
        match = re.search(r'src="(/assets/[^"]+\.js)"', page)
        if not match:
            raise SmokeTestError("Frontend page has no JavaScript bundle.")
        _, bundle = http("GET", f"{web}{match.group(1)}")
        if not isinstance(bundle, str) or api not in bundle:
            raise SmokeTestError(f"Frontend bundle does not point at {api} (check VITE_API_BASE_URL).")
    print("Frontend serves the app shell" + (f" built for {api}." if api else "."))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    parser.add_argument("--web", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    api, web = args.api.rstrip("/"), args.web.rstrip("/")
    try:
        wait_for_version(api, args.commit)
        run_task(api)
        check_frontend(web, api=api)
    except SmokeTestError as exc:
        print(f"::error::{exc}")
        return 1
    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
