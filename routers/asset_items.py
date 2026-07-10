"""Asset-library item operation routes."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/asset-library/items", tags=["asset-items"])
_handlers: dict[str, Callable[..., Awaitable[Any]]] = {}


def configure_asset_item_routes(**handlers: Callable[..., Awaitable[Any]]) -> None:
    global _handlers
    _handlers = handlers


def _handler(name: str) -> Callable[..., Awaitable[Any]]:
    handler = _handlers.get(name)
    if handler is None:
        raise RuntimeError(f"Asset item route handler is not configured: {name}")
    return handler


class AssetLibraryAddRequest(BaseModel):
    category_id: str = ""
    url: str = ""
    name: str = ""
    library_id: str = ""


class AssetLibraryBatchAddRequest(BaseModel):
    category_id: str = ""
    library_id: str = ""
    items: List[AssetLibraryAddRequest] = Field(default_factory=list)


class AssetLibraryRenameRequest(BaseModel):
    name: str = ""
    library_id: str = ""


class AssetLibraryBatchDeleteRequest(BaseModel):
    ids: List[str] = Field(default_factory=list)
    library_id: str = ""


class AssetLibraryBatchMoveRequest(BaseModel):
    ids: List[str] = Field(default_factory=list)
    library_id: str = ""
    target_library_id: str = ""
    target_category_id: str = ""


class AssetLibraryBatchCropRequest(BaseModel):
    ids: List[str] = Field(default_factory=list)
    library_id: str = ""
    target_library_id: str = ""
    target_category_id: str = ""
    mode: str = "square"


class AssetAvatarRegisterRequest(BaseModel):
    library_id: str = ""
    provider_id: str = ""
    project_name: str = "default"
    group_name: str = ""


class AssetLibraryClassifyRequest(BaseModel):
    library_id: str = ""
    ids: List[str] = Field(default_factory=list)
    provider: str = "comfly"
    model: str = ""
    ms_model: str = ""
    prompt: str = ""


@router.post("")
async def add_asset_library_item(payload: AssetLibraryAddRequest):
    return await _handler("add_item")(payload)


@router.post("/batch")
async def batch_add_asset_library_items(payload: AssetLibraryBatchAddRequest):
    return await _handler("batch_add")(payload)


@router.patch("/{item_id}")
async def rename_asset_library_item(item_id: str, payload: AssetLibraryRenameRequest):
    return await _handler("rename")(item_id, payload)


@router.post("/classify")
async def classify_asset_library_items(payload: AssetLibraryClassifyRequest):
    return await _handler("classify")(payload)


@router.post("/{item_id}/register-avatar")
async def register_asset_library_avatar(item_id: str, payload: AssetAvatarRegisterRequest):
    return await _handler("register_avatar")(item_id, payload)


@router.post("/{item_id}/avatar-status")
async def check_asset_library_avatar(item_id: str, payload: AssetAvatarRegisterRequest):
    return await _handler("avatar_status")(item_id, payload)


@router.delete("/{item_id}")
async def delete_asset_library_item(item_id: str, library_id: str = ""):
    return await _handler("delete")(item_id, library_id)


@router.post("/delete")
async def batch_delete_asset_library_items(payload: AssetLibraryBatchDeleteRequest):
    return await _handler("batch_delete")(payload)


@router.post("/move")
async def batch_move_asset_library_items(payload: AssetLibraryBatchMoveRequest):
    return await _handler("move")(payload)


@router.post("/crop")
async def batch_crop_asset_library_items(payload: AssetLibraryBatchCropRequest):
    return await _handler("crop")(payload)
