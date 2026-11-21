"""WebSocket endpoint for streaming AgentFlow task progress."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.api.routes import TASK_EVENTS, get_task_response
from backend.observability import logger, task_context


router = APIRouter()


@router.websocket("/ws/{task_id}")
async def task_websocket(websocket: WebSocket, task_id: str) -> None:
    """Stream task progress events to a frontend client."""

    await websocket.accept()
    last_index = 0
    try:
        while True:
            try:
                task = get_task_response(task_id)
            except Exception:
                await websocket.send_json({"type": "error", "message": "Task not found."})
                await websocket.close()
                return

            events = TASK_EVENTS.get(task_id, [])
            for event in events[last_index:]:
                await websocket.send_json(event)
            last_index = len(events)

            if task.status in {"completed", "error"}:
                await websocket.send_json({"type": "task", "task": task.model_dump()})
                if task.status == "completed":
                    await websocket.send_json({"type": "complete", "status": "completed"})
                else:
                    await websocket.send_json({"type": "complete", "status": "error"})
                await asyncio.sleep(0.05)
                await websocket.close()
                return

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        with task_context(task_id):
            logger.exception("WebSocket stream failed: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": "Workflow failed."})
            await websocket.close()
        except Exception:
            pass
