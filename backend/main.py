"""FastAPI application entrypoint for the AgentFlow backend."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from threading import Lock
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from backend.api.routes import router as api_router
from backend.api.websocket import router as websocket_router
from backend.database import init_db


_MAX_BODY_BYTES = 15 * 1024 * 1024  # 15 MB

_rate_timestamps: dict[str, list[float]] = defaultdict(list)
_rate_lock = Lock()
_RATE_LIMIT = 10
_RATE_WINDOW = 60  # seconds


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


app.include_router(api_router)
app.include_router(websocket_router)
