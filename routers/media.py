"""Media preview, download, upload, and import routes."""

from __future__ import annotations

import inspect
from typing import Any, Callable, List

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel, Field


router = APIRouter(tags=["media"])
_handlers: dict[str, Callable[..., Any]] = {}


def configure_media_routes(**handlers: Callable[..., Any]) -> None:
    global _handlers
    _handlers = handlers


async def _call(name: str, *args: Any) -> Any:
    handler = _handlers.get(name)
    if handler is None:
        raise RuntimeError(f"Media route handler is not configured: {name}")
    result = handler(*args)
    return await result if inspect.isawaitable(result) else result


class Base64UploadRequest(BaseModel):
    data: str = ""
    name: str = ""
    content_type: str = ""


class TempShUploadRequest(BaseModel):
    url: str = ""


class CloudVideoUploadRequest(BaseModel):
    url: str = ""
    service: str = "auto"


class LocalImageImportRequest(BaseModel):
    path: str = ""
    paths: List[str] = Field(default_factory=list)


@router.get("/api/media-preview")
async def media_preview(url: str, w: int = 512):
    return await _call("media_preview", url, w)


@router.get("/api/image-jpeg")
async def image_jpeg(url: str, w: int = 0):
    return await _call("image_jpeg", url, w)


@router.get("/")
async def index():
    return await _call("index")


@router.get("/api/view")
async def view_image(filename: str, type: str = "input", subfolder: str = ""):
    return await _call("view_image", filename, type, subfolder)


@router.get("/api/download-output")
async def download_output(
    request: Request,
    url: str,
    name: str = "",
    inline: bool = False,
):
    return await _call("download_output", request, url, name, inline)


@router.post("/api/upload")
async def upload_image(files: List[UploadFile] = File(...)):
    return await _call("upload_image", files)


@router.post("/api/ai/upload")
async def upload_ai_reference(files: List[UploadFile] = File(...)):
    return await _call("upload_ai_reference", files)


@router.post("/api/ai/upload-base64")
async def upload_ai_base64(payload: Base64UploadRequest):
    return await _call("upload_ai_base64", payload)


@router.post("/api/comfyui/upload-base64")
async def upload_comfyui_base64(payload: Base64UploadRequest):
    return await _call("upload_comfyui_base64", payload)


@router.post("/api/temp-sh/upload")
async def temp_sh_upload(payload: TempShUploadRequest, request: Request):
    return await _call("temp_sh_upload", payload, request)


@router.post("/api/cloud-video/upload")
async def cloud_video_upload(payload: CloudVideoUploadRequest, request: Request):
    return await _call("cloud_video_upload", payload, request)


@router.post("/api/ai/import-local-image")
async def import_local_ai_reference(payload: LocalImageImportRequest, request: Request):
    return await _call("import_local_ai_reference", payload, request)
