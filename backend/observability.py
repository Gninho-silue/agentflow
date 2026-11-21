"""Logs and metrics for AgentFlow (no external service needed).

Logs
    One JSON object per line (``LOG_FORMAT=json``, default) or readable text
    (``LOG_FORMAT=text``), level from ``LOG_LEVEL`` (default ``INFO``). Every
    record carries ``task_id`` and ``request_id`` from context variables, so a
    whole run can be followed with one filter (e.g. ``task_id="..."``).

Metrics
    Prometheus counters and histograms, served on ``/metrics``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import time
from collections.abc import Iterator
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from prometheus_client import Counter, Histogram

LOGGER_NAME = "agentflow"
logger = logging.getLogger(LOGGER_NAME)

_task_id: ContextVar[str | None] = ContextVar("task_id", default=None)
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else was passed with ``extra=``.
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


# --- Context ------------------------------------------------------------------


@contextlib.contextmanager
def task_context(task_id: str) -> Iterator[None]:
    """Tag every log record emitted inside the block with ``task_id``."""

    token = _task_id.set(task_id)
    try:
        yield
    finally:
        _task_id.reset(token)


def set_request_id(request_id: str | None) -> Any:
    return _request_id.set(request_id)


def reset_request_id(token: Any) -> None:
    _request_id.reset(token)


def _install_record_factory() -> None:
    """Add task_id / request_id to every record (works with any handler, caplog included)."""

    previous = logging.getLogRecordFactory()
    if getattr(previous, "_agentflow", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.task_id = _task_id.get()
        record.request_id = _request_id.get()
        return record

    factory._agentflow = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


_install_record_factory()


# --- Formatting ---------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """Format a record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_") and value is not None:
                data[key] = value
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str, ensure_ascii=False)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        task = getattr(record, "task_id", None)
        return f"{line} [task={task}]" if task else line


def configure_logging() -> None:
    """Send AgentFlow logs to stdout in the configured format (idempotent)."""

    handler = logging.StreamHandler(sys.stdout)
    if os.getenv("LOG_FORMAT", "json").strip().lower() == "text":
        handler.setFormatter(_TextFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    else:
        handler.setFormatter(JsonFormatter())
    handler._agentflow = True  # type: ignore[attr-defined]

    logger.handlers = [h for h in logger.handlers if not getattr(h, "_agentflow", False)]
    logger.addHandler(handler)
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    logger.propagate = True  # keeps pytest's caplog working


# --- Metrics ------------------------------------------------------------------

_DURATION_BUCKETS = (0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)

HTTP_REQUESTS = Counter(
    "agentflow_http_requests_total", "HTTP requests handled.", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "agentflow_http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
TASKS = Counter("agentflow_tasks_total", "Finished tasks by final status.", ["status"])
TASK_DURATION = Histogram(
    "agentflow_task_duration_seconds", "End-to-end task duration.", buckets=_DURATION_BUCKETS
)
AGENT_DURATION = Histogram(
    "agentflow_agent_duration_seconds", "Time spent in each agent.", ["agent"], buckets=_DURATION_BUCKETS
)
LLM_REQUESTS = Counter(
    "agentflow_llm_requests_total", "LLM calls by outcome.", ["provider", "model", "outcome"]
)
LLM_LATENCY = Histogram(
    "agentflow_llm_latency_seconds", "LLM call latency.", ["provider", "model"], buckets=_DURATION_BUCKETS
)
CODE_ATTEMPTS = Counter(
    "agentflow_code_attempts_total", "CodeAgent attempts by outcome.", ["outcome"]
)
SANDBOX_RUNS = Counter(
    "agentflow_sandbox_runs_total", "Sandbox executions by outcome (ok, error, timeout).", ["outcome"]
)
SANDBOX_DURATION = Histogram(
    "agentflow_sandbox_duration_seconds", "Sandbox execution wall time.", buckets=_DURATION_BUCKETS
)


class LLMMetricsCallback(BaseCallbackHandler):
    """LangChain callback recording latency and outcome of every chat model call."""

    def __init__(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model
        self._started: dict[UUID, float] = {}

    def on_chat_model_start(self, serialized: Any, messages: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._started[run_id] = time.perf_counter()

    def on_llm_start(self, serialized: Any, prompts: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._started[run_id] = time.perf_counter()

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._record(run_id, "success")

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._record(run_id, "error")
        logger.warning("LLM call failed: %s", error, extra={"provider": self.provider, "model": self.model})

    def _record(self, run_id: UUID, outcome: str) -> None:
        started = self._started.pop(run_id, None)
        LLM_REQUESTS.labels(self.provider, self.model, outcome).inc()
        if started is not None:
            LLM_LATENCY.labels(self.provider, self.model).observe(time.perf_counter() - started)
