"""Generation history and queue-status routes."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from repositories.history import delete_history_record, list_history


router = APIRouter(tags=["history"])
_queue_status: Optional[Callable[[str], dict[str, int]]] = None


def configure_history_routes(
    *,
    queue_status_fn: Callable[[str], dict[str, int]],
) -> None:
    global _queue_status
    _queue_status = queue_status_fn


class DeleteHistoryRequest(BaseModel):
    timestamp: Any


@router.get("/api/history")
async def get_history_api(type: str = None):
    return list_history(type)


@router.get("/api/queue_status")
async def get_queue_status(client_id: str):
    if _queue_status is None:
        raise RuntimeError("History routes are not configured")
    return _queue_status(client_id)


@router.post("/api/history/delete")
async def delete_history(request: DeleteHistoryRequest):
    return delete_history_record(request.timestamp)
