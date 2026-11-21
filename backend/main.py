"""FastAPI application entrypoint for the AgentFlow backend."""

from __future__ import annotations

import hmac
import os
import re
import shutil
import time
import uuid
from collections import defaultdict
from threading import Lock
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from backend.api import routes
from backend.api.routes import router as api_router
from backend.api.websocket import router as websocket_router
from backend.database import init_db
from backend.observability import (
    HTTP_LATENCY,
    HTTP_REQUESTS,
    configure_logging,
    reset_request_id,
    set_request_id,
)

configure_logging()


_MAX_BODY_BYTES = 15 * 1024 * 1024  # 15 MB

_rate_timestamps: dict[str, list[float]] = defaultdict(list)
_rate_lock = Lock()
_RATE_LIMIT = 10
_RATE_WINDOW = 60  # seconds
_MIN_FREE_DISK_MB = 100
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length header exceeds 15 MB."""

    async def dispatch(
        self, request: Request, call_next: Callable[..., Awaitable[Response]]
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Request body too large."})
        return await call_next(request)


app = FastAPI(title="AgentFlow API", version="0.1.0")
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(BodySizeLimitMiddleware)


@app.on_event("startup")
async def startup() -> None:
    """Initialize backend resources."""

    init_db()


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check for health monitoring and Docker."""

    return {"status": "ok"}


@app.get("/health/ready")
async def readiness() -> JSONResponse:
    """Check the dependencies a task needs: database, LLM and disk space."""

    checks: dict[str, dict[str, Any]] = {}
    try:
        with routes.SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"ok": False, "detail": str(exc)}

    llm_problem = routes.check_llm()
    checks["llm"] = {"ok": True} if llm_problem is None else {"ok": False, "detail": llm_problem}

    free_mb = shutil.disk_usage(routes.UPLOAD_DIR).free // (1024 * 1024)
    checks["disk"] = {"ok": free_mb >= _MIN_FREE_DISK_MB, "free_mb": free_mb}

    ready = all(check["ok"] for check in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "degraded", "checks": checks},
    )


@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    """Prometheus metrics. Protected by a bearer token when METRICS_TOKEN is set."""

    token = os.getenv("METRICS_TOKEN", "")
    if token:
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            return PlainTextResponse("Unauthorized", status_code=401)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _is_within_rate_limit(client_ip: str) -> bool:
    """Return True when the IP has not exceeded 10 POST /api/tasks per minute."""

    now = time.monotonic()
    with _rate_lock:
        timestamps = [t for t in _rate_timestamps[client_ip] if now - t < _RATE_WINDOW]
        if len(timestamps) >= _RATE_LIMIT:
            _rate_timestamps[client_ip] = timestamps
            return False
        timestamps.append(now)
        _rate_timestamps[client_ip] = timestamps
        return True


@app.middleware("http")
async def rate_limit_post_tasks(
    request: Request, call_next: Callable[..., Awaitable[Response]]
) -> Response:
    """Limit POST /api/tasks to 10 requests per minute per client IP."""

    if request.method == "POST" and request.url.path == "/api/tasks":
        client_ip = request.client.host if request.client else "unknown"
        if not _is_within_rate_limit(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Try again in a minute."},
            )
    return await call_next(request)


@app.middleware("http")
async def observe_requests(
    request: Request, call_next: Callable[..., Awaitable[Response]]
) -> Response:
    """Attach a request id (logs + X-Request-ID header) and record HTTP metrics.

    Registered last, so it wraps every other middleware (429 and 413 included).
    """

    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if _REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
    token = set_request_id(request_id)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        # Route template ("/api/tasks/{task_id}/status"), never the raw path.
        route = getattr(request.scope.get("route"), "path", "unmatched")
        HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
        HTTP_LATENCY.labels(request.method, route).observe(time.perf_counter() - started)
        reset_request_id(token)


app.include_router(api_router)
app.include_router(websocket_router)
