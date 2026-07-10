"""Canvas and project management routes."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from repositories.canvases import (
    canvas_record,
    delete_project_and_reassign,
    list_canvases,
    list_deleted_canvases,
    list_projects,
    load_canvas,
    new_canvas,
    new_project,
    normalize_canvas_kind,
    project_record,
    purge_canvas,
    restore_canvas,
    save_canvas,
    soft_delete_canvas,
    update_canvas_metadata,
    update_project,
)


router = APIRouter(tags=["canvases"])
_broadcast_canvas_updated: Optional[Callable[[str, int, str], Awaitable[None]]] = None
_now_ms: Optional[Callable[[], int]] = None


def configure_canvas_routes(
    *,
    broadcast_canvas_updated_fn: Callable[[str, int, str], Awaitable[None]],
    now_ms_fn: Callable[[], int],
) -> None:
    global _broadcast_canvas_updated, _now_ms
    _broadcast_canvas_updated = broadcast_canvas_updated_fn
    _now_ms = now_ms_fn


def _require_configured() -> None:
    if _broadcast_canvas_updated is None or _now_ms is None:
        raise RuntimeError("Canvas routes are not configured")


class CanvasCreateRequest(BaseModel):
    title: str = "\u672a\u547d\u540d\u753b\u5e03"
    icon: str = "layers"
    kind: str = "classic"
    project: Optional[str] = None
    board_x: Optional[float] = None
    board_y: Optional[float] = None


class CanvasMetaUpdate(BaseModel):
    title: Optional[str] = None
    icon: Optional[str] = None
    owner: Optional[str] = None
    color: Optional[str] = None
    pinned: Optional[bool] = None
    project: Optional[str] = None
    board_x: Optional[float] = None
    board_y: Optional[float] = None


class ProjectCreateRequest(BaseModel):
    name: str = "\u65b0\u9879\u76ee"


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    order: Optional[int] = None


class CanvasSaveRequest(BaseModel):
    title: str = "\u672a\u547d\u540d\u753b\u5e03"
    icon: str = "layers"
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    connections: List[Dict[str, Any]] = Field(default_factory=list)
    viewport: Dict[str, Any] = Field(default_factory=dict)
    logs: List[Dict[str, Any]] = Field(default_factory=list)
    settings: Dict[str, Any] = Field(default_factory=dict)
    client_id: str = ""
    base_updated_at: int = 0


@router.get("/api/canvases")
async def canvases():
    return {"canvases": list_canvases()}


@router.get("/api/projects")
async def get_projects():
    return {"projects": list_projects()}


@router.post("/api/projects")
async def create_project(payload: ProjectCreateRequest):
    return {"project": project_record(new_project(payload.name))}


@router.post("/api/projects/{project_id}")
async def edit_project(project_id: str, payload: ProjectUpdateRequest):
    return {"project": update_project(project_id, name=payload.name, order=payload.order)}


@router.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    return {"ok": True, "moved": delete_project_and_reassign(project_id)}


@router.get("/api/canvases/trash")
async def trashed_canvases():
    return {"canvases": list_deleted_canvases(), "retention_days": 30}


@router.post("/api/canvases")
async def create_canvas(payload: CanvasCreateRequest):
    return {
        "canvas": new_canvas(
            payload.title,
            payload.icon,
            payload.kind,
            payload.project,
            payload.board_x,
            payload.board_y,
        )
    }


@router.get("/api/canvases/{canvas_id}/meta")
async def get_canvas_meta(canvas_id: str):
    canvas = load_canvas(canvas_id)
    return {
        "id": canvas.get("id"),
        "updated_at": canvas.get("updated_at", 0),
        "title": canvas.get("title", "\u672a\u547d\u540d\u753b\u5e03"),
        "icon": canvas.get("icon", "layers"),
        "kind": normalize_canvas_kind(canvas.get("kind")),
    }


@router.post("/api/canvases/{canvas_id}/meta")
async def update_canvas_meta(canvas_id: str, payload: CanvasMetaUpdate):
    return {"canvas": update_canvas_metadata(canvas_id, **payload.dict())}


@router.get("/api/canvases/{canvas_id}")
async def get_canvas(canvas_id: str):
    return {"canvas": load_canvas(canvas_id)}


@router.post("/api/canvases/{canvas_id}/touch")
async def touch_canvas(canvas_id: str):
    canvas = load_canvas(canvas_id)
    save_canvas(canvas)
    return {"canvas": canvas_record(canvas), "updated_at": canvas.get("updated_at", 0)}


@router.put("/api/canvases/{canvas_id}")
async def update_canvas(canvas_id: str, payload: CanvasSaveRequest):
    _require_configured()
    canvas = load_canvas(canvas_id)
    current_updated_at = int(canvas.get("updated_at") or 0)
    if payload.base_updated_at and current_updated_at and payload.base_updated_at < current_updated_at:
        raise HTTPException(status_code=409, detail={
            "message": "\u753b\u5e03\u5df2\u88ab\u5176\u4ed6\u9875\u9762\u66f4\u65b0\uff0c\u5df2\u62d2\u7edd\u65e7\u7248\u672c\u8986\u76d6\u3002",
            "canvas": canvas,
            "updated_at": current_updated_at,
        })
    canvas["title"] = (payload.title or canvas.get("title") or "\u672a\u547d\u540d\u753b\u5e03")[:80]
    canvas["icon"] = (payload.icon or canvas.get("icon") or "layers")[:32]
    canvas["kind"] = normalize_canvas_kind(canvas.get("kind"))
    canvas["nodes"] = payload.nodes
    canvas["connections"] = payload.connections
    canvas["viewport"] = (
        payload.viewport
        if canvas["kind"] == "smart"
        else canvas.get("viewport") or {"x": 0, "y": 0, "scale": 1}
    )
    canvas["logs"] = payload.logs[-500:]
    canvas["settings"] = payload.settings or {}
    save_canvas(canvas)
    updated_at = int(canvas.get("updated_at") or _now_ms())
    await _broadcast_canvas_updated(canvas_id, updated_at, payload.client_id)
    return {"canvas": canvas}


@router.delete("/api/canvases/{canvas_id}")
async def delete_canvas(canvas_id: str):
    soft_delete_canvas(canvas_id)
    return {"ok": True}


@router.post("/api/canvases/{canvas_id}/restore")
async def restore_deleted_canvas(canvas_id: str):
    return {"canvas": restore_canvas(canvas_id)}


@router.delete("/api/canvases/{canvas_id}/purge")
async def purge_deleted_canvas(canvas_id: str):
    purge_canvas(canvas_id)
    return {"ok": True}
