"""HTTP API routes for AgentFlow tasks and uploads."""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import SessionLocal, get_db
from backend.graph.state import AgentState
from backend.graph.workflow import workflow
from backend.models.task import Task


_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".csv", ".json", ".txt"})
_MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_FILE_SIZE_MB", "10")) * 1024 * 1024

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter(prefix="/api")
TASK_EVENTS: dict[str, list[dict[str, Any]]] = {}


class TaskCreateRequest(BaseModel):
    """Request body for creating a task."""

    task: str = Field(min_length=1, max_length=2000)
    file_path: str | None = None

    @field_validator("task")
    @classmethod
    def task_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Task text must not be blank or whitespace only.")
        return stripped


class TaskCreateResponse(BaseModel):
    """Response returned after creating a task."""

    task_id: str


class TaskExecuteRequest(BaseModel):
    """Request body for starting task execution."""

    file_path: str | None = None


class TaskResponse(BaseModel):
    """Task response shape returned to the frontend."""

    task_id: str
    task: str
    file_path: str | None
    status: str
    result: dict[str, Any] | None
    error: str | None
    created_at: str
    updated_at: str
    execution_time: float | None
    agents_used: list[str]


@router.post("/tasks", response_model=TaskCreateResponse)
async def create_task(payload: TaskCreateRequest, db: Session = Depends(get_db)) -> TaskCreateResponse:
    """Create a new task and return its identifier."""

    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        task=payload.task,
        file_path=payload.file_path,
        status="pending",
        agents_used=[],
    )
    db.add(task)
    db.commit()
    TASK_EVENTS[task_id] = [_event("created", "Task created.", "idle")]
    return TaskCreateResponse(task_id=task_id)


@router.post("/tasks/{task_id}/execute")
async def execute_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    payload: TaskExecuteRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Start the agent workflow in the background and return immediately."""

    task = _get_task_model(task_id, db)
    if task.status == "running":
        return {"task_id": task_id, "status": "running"}

    if payload is not None and payload.file_path is not None:
        task.file_path = payload.file_path
    task.status = "running"
    task.updated_at = datetime.now(timezone.utc)
    db.commit()
    TASK_EVENTS.setdefault(task_id, []).append(_event("supervisor", "Workflow queued.", "running"))
    background_tasks.add_task(_run_workflow, task_id)
    return {"task_id": task_id, "status": "running"}


@router.get("/tasks/{task_id}/status", response_model=TaskResponse)
async def get_task_status(task_id: str, db: Session = Depends(get_db)) -> TaskResponse:
    """Return task status and final result when available."""

    return _to_response(_get_task_model(task_id, db))


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)) -> dict[str, str]:
    """Upload a file for a future AgentFlow task."""

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{suffix or '(none)'}' is not allowed. Upload a .csv, .json, or .txt file.",
        )

    contents = await file.read()
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB size limit.",
        )

    safe_filename = f"{uuid.uuid4()}{suffix}"
    save_path = UPLOAD_DIR / safe_filename

    # Path traversal protection — resolved path must stay inside UPLOAD_DIR
    if not str(save_path.resolve()).startswith(str(UPLOAD_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid file path.")

    try:
        save_path.write_bytes(contents)
        return {"file_path": str(save_path)}
    except Exception:
        raise HTTPException(status_code=500, detail="File upload failed.")


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(db: Session = Depends(get_db)) -> list[TaskResponse]:
    """List all past tasks, newest first."""

    tasks = db.scalars(select(Task).order_by(Task.created_at.desc())).all()
    return [_to_response(task) for task in tasks]


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    """Delete a single task from history."""

    task = _get_task_model(task_id, db)
    db.delete(task)
    db.commit()
    TASK_EVENTS.pop(task_id, None)
    return {"deleted": True}


@router.delete("/tasks")
async def delete_all_tasks(db: Session = Depends(get_db)) -> dict[str, int]:
    """Delete all task history records."""

    tasks = db.scalars(select(Task)).all()
    deleted_count = len(tasks)
    for task in tasks:
        db.delete(task)
    db.commit()
    TASK_EVENTS.clear()
    return {"deleted": deleted_count}


def get_task_response(task_id: str) -> TaskResponse:
    """Fetch a task response outside request dependency injection."""

    with SessionLocal() as db:
        return _to_response(_get_task_model(task_id, db))


def _run_workflow(task_id: str) -> None:
    """Run LangGraph for a task and persist the final state."""

    db = SessionLocal()
    started_at = time.perf_counter()
    try:
        task = _get_task_model(task_id, db)
        initial_state: AgentState = {
            "task": task.task,
            "subtasks": [],
            "current_agent": "planner",
            "file_data": None,
            "code_output": None,
            "chart_path": None,
            "report": None,
            "messages": [HumanMessage(content=task.task)],
            "status": "running",
            "error": None,
            "file_path": task.file_path,
            "agents_needed": [],
            "execution_order": [],
            "completed_agents": [],
        }

        final_state = initial_state
        for chunk in workflow.stream(initial_state):
            node_name, state = next(iter(chunk.items()))
            final_state = state
            TASK_EVENTS.setdefault(task_id, []).append(
                _event(node_name, _latest_message(state.get("messages", [])), state.get("status", "running"))
            )

        task.status = final_state["status"]
        task.error = final_state.get("error")
        task.result = _serialize_state(final_state)
        task.agents_used = _agents_used(final_state)
        task.execution_time = round(time.perf_counter() - started_at, 3)
        task.updated_at = datetime.now(timezone.utc)
        db.commit()
        TASK_EVENTS.setdefault(task_id, []).append(_event("supervisor", f"Workflow {task.status}.", task.status))
    except Exception as exc:
        task = db.get(Task, task_id)
        if task is not None:
            task.status = "error"
            task.error = str(exc)
            task.execution_time = round(time.perf_counter() - started_at, 3)
            task.updated_at = datetime.now(timezone.utc)
            db.commit()
        TASK_EVENTS.setdefault(task_id, []).append(_event("supervisor", str(exc), "error"))
    finally:
        db.close()


def _get_task_model(task_id: str, db: Session) -> Task:
    """Fetch a task model or raise a 404 error."""

    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


def _to_response(task: Task) -> TaskResponse:
    """Convert a SQLAlchemy task model into an API response."""

    return TaskResponse(
        task_id=task.id,
        task=task.task,
        file_path=task.file_path,
        status=task.status,
        result=task.result,
        error=task.error,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
        execution_time=task.execution_time,
        agents_used=task.agents_used or [],
    )


def _event(agent: str, message: str, status: str) -> dict[str, Any]:
    """Build a websocket-friendly progress event."""

    return {
        "type": "agent_update",
        "agent": agent,
        "message": message,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _latest_message(messages: list[BaseMessage]) -> str:
    """Return the latest LangChain message content as text."""

    if not messages:
        return "Agent completed a workflow step."
    return str(messages[-1].content)


def _serialize_state(state: AgentState) -> dict[str, Any]:
    """Convert AgentState into JSON-safe API data."""

    return {
        "task": state.get("task"),
        "subtasks": state.get("subtasks", []),
        "current_agent": state.get("current_agent"),
        "file_data": state.get("file_data"),
        "file_path": state.get("file_path"),
        "code_output": state.get("code_output"),
        "chart_path": state.get("chart_path"),
        "report": state.get("report"),
        "status": state.get("status"),
        "error": state.get("error"),
        "completed_agents": state.get("completed_agents", []),
        "agents_needed": state.get("agents_needed", []),
        "execution_order": state.get("execution_order", []),
        "messages": [str(message.content) for message in state.get("messages", [])],
    }


def _agents_used(state: AgentState) -> list[str]:
    """Infer the agents used during a workflow run."""

    used = ["planner"]
    used.extend(state.get("completed_agents", []))
    if "supervisor" not in used:
        used.append("supervisor")
    return used
