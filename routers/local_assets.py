"""Local asset management routes."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, List

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/local-assets", tags=["local-assets"])
_handlers: dict[str, Callable[..., Awaitable[Any]]] = {}


def configure_local_asset_routes(**handlers: Callable[..., Awaitable[Any]]) -> None:
    global _handlers
    _handlers = handlers


def _handler(name: str) -> Callable[..., Awaitable[Any]]:
    handler = _handlers.get(name)
    if handler is None:
        raise RuntimeError(f"Local asset route handler is not configured: {name}")
    return handler


class LocalAssetCaptionRequest(BaseModel):
    names: List[str] = Field(default_factory=list)
    provider: str = "comfly"
    model: str = ""
    ms_model: str = ""
    prompt: str = "\u63cf\u8ff0\u56fe\u7247"


class LocalAssetCaptionSaveRequest(BaseModel):
    name: str = ""
    caption: str = ""


class LocalAssetClassifyRequest(BaseModel):
    names: List[str] = Field(default_factory=list)
    provider: str = "comfly"
    model: str = ""
    ms_model: str = ""
    prompt: str = ""


class LocalAssetUrlImportItem(BaseModel):
    url: str = ""
    name: str = ""
    data: str = ""
    content_type: str = ""


class LocalAssetUrlImportRequest(BaseModel):
    items: List[LocalAssetUrlImportItem] = Field(default_factory=list)
    folder: str = ""
    classify: bool = False
    provider: str = "comfly"
    model: str = ""
    ms_model: str = ""
    prompt: str = ""


class LocalAssetFolderRequest(BaseModel):
    parent: str = ""
    path: str = ""
    name: str = ""


class LocalAssetRenameRequest(BaseModel):
    path: str = ""
    name: str = ""


@router.post("/upload")
async def upload_local_assets(
    files: List[UploadFile] = File(...),
    folder: str = Form(""),
):
    return await _handler("upload")(files, folder)


@router.post("/import-urls")
async def import_local_assets_from_urls(payload: LocalAssetUrlImportRequest):
    return await _handler("import_urls")(payload)


@router.get("")
async def list_local_assets():
    return await _handler("list")()


@router.post("/folders")
async def create_local_asset_folder(payload: LocalAssetFolderRequest, request: Request):
    return await _handler("create_folder")(payload, request)


@router.patch("/folders")
async def rename_local_asset_folder(payload: LocalAssetFolderRequest, request: Request):
    return await _handler("rename_folder")(payload, request)


@router.patch("/items")
async def rename_local_asset_item(payload: LocalAssetRenameRequest, request: Request):
    return await _handler("rename_item")(payload, request)


@router.post("/delete")
async def delete_local_assets(payload: dict, request: Request):
    return await _handler("delete")(payload, request)


@router.post("/move")
async def move_local_assets(payload: dict, request: Request):
    return await _handler("move")(payload, request)


@router.post("/caption")
async def caption_local_assets(payload: LocalAssetCaptionRequest):
    return await _handler("caption")(payload)


@router.post("/classify")
async def classify_local_assets(payload: LocalAssetClassifyRequest):
    return await _handler("classify")(payload)


@router.patch("/caption")
async def save_local_asset_caption(payload: LocalAssetCaptionSaveRequest):
    return await _handler("save_caption")(payload)
