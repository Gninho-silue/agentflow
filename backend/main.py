"""FastAPI application entrypoint for the AgentFlow backend."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import os
import re
import shutil
import time
import uuid
from collections import defaultdict
from datetime import timedelta
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
from backend.maintenance import cleanup_expired
from backend.observability import (
    HTTP_LATENCY,
    HTTP_REQUESTS,
    configure_logging,
    logger,
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


def cors_origins() -> list[str]:
    """Allowed browser origins: CORS_ORIGINS (comma-separated) or local Vite dev."""

    raw = os.getenv("CORS_ORIGINS", "")
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    if "*" in origins:
        raise ValueError("CORS_ORIGINS must list explicit origins, not '*'.")
    return origins or ["http://localhost:5173", "http://127.0.0.1:5173"]


async def _retention_loop() -> None:
    """Every hour, delete tasks and files older than RETENTION_HOURS (default 24)."""

    max_age = timedelta(hours=float(os.getenv("RETENTION_HOURS", "24")))
    while True:
        try:
            with routes.SessionLocal() as db:
                await asyncio.to_thread(cleanup_expired, db, routes.UPLOAD_DIR, max_age, routes.TASK_EVENTS)
        except Exception:  # noqa: BLE001 - never kill the loop
            logger.exception("Retention cleanup failed")
        await asyncio.sleep(3600)


app = FastAPI(title="AgentFlow API", version="0.1.0")
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(BodySizeLimitMiddleware)


@app.on_event("startup")
async def startup() -> None:
    """Initialize backend resources."""

    init_db()
    if os.getenv("RETENTION_HOURS", "24") != "0":
        app.state.retention_task = asyncio.create_task(_retention_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    task = getattr(app.state, "retention_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


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
        content={
            "status": "ready" if ready else "degraded",
            # Render sets RENDER_GIT_COMMIT: the CD smoke test waits for its own commit.
            "version": os.getenv("RENDER_GIT_COMMIT") or "dev",
            "checks": checks,
        },
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


def client_ip(request: Request) -> str:
    """Client address for rate limiting.

    Behind a reverse proxy (Render), set TRUSTED_PROXY_HOPS to the number of
    proxies that append to X-Forwarded-For. The address is read from the right:
    whatever a client writes on the left cannot be used to dodge the limit.
    """

    peer = request.client.host if request.client else "unknown"
    try:
        hops = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))
    except ValueError:
        hops = 0
    if hops <= 0:
        return peer
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    if len(forwarded) >= hops:
        return forwarded[-hops]
    return peer


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
        if not _is_within_rate_limit(client_ip(request)):
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
