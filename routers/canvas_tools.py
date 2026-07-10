"""Canvas asset and workflow import/export routes."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field


router = APIRouter(tags=["canvas-tools"])
_handlers: dict[str, Callable[..., Any]] = {}


def configure_canvas_tool_routes(**handlers: Callable[..., Any]) -> None:
    global _handlers
    _handlers = handlers


async def _call(name: str, *args: Any) -> Any:
    handler = _handlers.get(name)
    if handler is None:
        raise RuntimeError(f"Canvas tool route handler is not configured: {name}")
    result = handler(*args)
    return await result if inspect.isawaitable(result) else result


class CanvasAssetCheckRequest(BaseModel):
    urls: List[str] = Field(default_factory=list)


class CanvasAssetDownloadRequest(BaseModel):
    urls: List[str] = Field(default_factory=list)
    items: List[Dict[str, Any]] = Field(default_factory=list)
    filename: str = "canvas-output-images.zip"


class CanvasWorkflowExportRequest(BaseModel):
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    connections: List[Dict[str, Any]] = Field(default_factory=list)
    filename: str = "canvas-workflow.zip"
    include_resources: bool = True
    library_id: str = ""
    category_id: str = ""
    name: str = ""


class SmartCanvasGroupExportItem(BaseModel):
    kind: str = ""
    url: str = ""
    text: str = ""
    name: str = ""


class SmartCanvasGroupExportRequest(BaseModel):
    folder: str = ""
    group_name: str = "group"
    items: List[SmartCanvasGroupExportItem] = Field(default_factory=list)


@router.get("/api/canvas-assets")
async def list_canvas_assets():
    return await _call("list_assets")


@router.get("/api/smart-canvas/prompt-templates")
async def smart_canvas_prompt_templates():
    return await _call("prompt_templates")


@router.post("/api/canvas-assets/check")
async def check_canvas_assets(payload: CanvasAssetCheckRequest):
    return await _call("check_assets", payload)


@router.post("/api/canvas-assets/download")
async def download_canvas_assets(payload: CanvasAssetDownloadRequest):
    return await _call("download_assets", payload)


@router.post("/api/canvas-workflows/export")
async def export_canvas_workflow(payload: CanvasWorkflowExportRequest):
    return await _call("export_workflow", payload)


@router.post("/api/canvas-workflows/export-to-library")
async def export_canvas_workflow_to_library(payload: CanvasWorkflowExportRequest):
    return await _call("export_to_library", payload)


@router.post("/api/asset-library/workflows/upload")
async def upload_asset_library_workflows(
    files: List[UploadFile] = File(...),
    library_id: str = Form(""),
    category_id: str = Form(""),
):
    return await _call("upload_workflows", files, library_id, category_id)


@router.post("/api/canvas-workflows/import")
async def import_canvas_workflow(file: UploadFile = File(...)):
    return await _call("import_workflow", file)


@router.post("/api/smart-canvas/group-export")
async def export_smart_canvas_group(payload: SmartCanvasGroupExportRequest):
    return await _call("export_group", payload)
