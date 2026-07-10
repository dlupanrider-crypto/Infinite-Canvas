"""Asset library and category management routes."""

from __future__ import annotations

import os
import shutil
import uuid
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from repositories.asset_library import (
    find_asset_category_with_library,
    find_asset_library,
    load_asset_library,
    save_asset_library,
)


router = APIRouter(prefix="/api/asset-library", tags=["asset-library"])
_asset_root = ""
_sanitize_name: Optional[Callable[[Any, str], str]] = None
_unique_category_dir: Optional[Callable[[dict[str, Any], str], str]] = None
_remove_item_file: Optional[Callable[[dict[str, Any]], None]] = None


def configure_asset_library_routes(
    *,
    asset_root: str,
    sanitize_name_fn: Callable[[Any, str], str],
    unique_category_dir_fn: Callable[[dict[str, Any], str], str],
    remove_item_file_fn: Callable[[dict[str, Any]], None],
) -> None:
    global _asset_root, _sanitize_name, _unique_category_dir, _remove_item_file
    _asset_root = asset_root
    _sanitize_name = sanitize_name_fn
    _unique_category_dir = unique_category_dir_fn
    _remove_item_file = remove_item_file_fn


def _require_configured() -> None:
    if not _asset_root or not all((_sanitize_name, _unique_category_dir, _remove_item_file)):
        raise RuntimeError("Asset library routes are not configured")


class AssetLibraryCategoryRequest(BaseModel):
    name: str = ""
    type: str = "image"
    library_id: str = ""


class AssetLibraryRequest(BaseModel):
    name: str = ""


class AssetLibraryRenameRequest(BaseModel):
    name: str = ""
    library_id: str = ""


@router.get("")
async def get_asset_library():
    return {"library": load_asset_library()}


@router.post("/libraries")
async def create_asset_library(payload: AssetLibraryRequest):
    _require_configured()
    data = load_asset_library()
    library = {
        "id": f"lib_{uuid.uuid4().hex[:12]}",
        "name": _sanitize_name(payload.name, "\u8d44\u4ea7\u5e93"),
        "type": "asset",
        "categories": [
            {
                "id": f"cat_{uuid.uuid4().hex[:12]}",
                "name": "\u9ed8\u8ba4\u5206\u7ec4",
                "type": "image",
                "items": [],
            },
            {
                "id": f"wf_{uuid.uuid4().hex[:12]}",
                "name": "\u5de5\u4f5c\u6d41",
                "type": "workflow",
                "items": [],
            },
        ],
    }
    data.setdefault("libraries", []).append(library)
    data["active_library_id"] = library["id"]
    save_asset_library(data)
    return {"library": data, "asset_library": library}


@router.patch("/libraries/{library_id}")
async def rename_asset_library(library_id: str, payload: AssetLibraryRenameRequest):
    _require_configured()
    data = load_asset_library()
    library = find_asset_library(data, library_id)
    if not library or library.get("id") != library_id:
        raise HTTPException(status_code=404, detail="\u8d44\u4ea7\u5e93\u4e0d\u5b58\u5728")
    library["name"] = _sanitize_name(payload.name, library.get("name") or "\u8d44\u4ea7\u5e93")
    save_asset_library(data)
    return {"library": data, "asset_library": library}


@router.delete("/libraries/{library_id}")
async def delete_asset_library(library_id: str):
    data = load_asset_library()
    libraries = data.get("libraries") or []
    if len(libraries) <= 1:
        raise HTTPException(status_code=400, detail="\u81f3\u5c11\u4fdd\u7559\u4e00\u4e2a\u8d44\u4ea7\u5e93")
    if not any(item.get("id") == library_id for item in libraries):
        raise HTTPException(status_code=404, detail="\u8d44\u4ea7\u5e93\u4e0d\u5b58\u5728")
    data["libraries"] = [item for item in libraries if item.get("id") != library_id]
    if data.get("active_library_id") == library_id:
        data["active_library_id"] = data["libraries"][0].get("id")
    save_asset_library(data)
    return {"library": data}


@router.post("/categories")
async def create_asset_library_category(payload: AssetLibraryCategoryRequest):
    _require_configured()
    data = load_asset_library()
    library = find_asset_library(data, payload.library_id)
    if not library:
        raise HTTPException(status_code=404, detail="\u8d44\u4ea7\u5e93\u4e0d\u5b58\u5728")
    category_type = "workflow" if str(payload.type or "").lower() == "workflow" else "image"
    category = {
        "id": f"cat_{uuid.uuid4().hex[:12]}",
        "name": _sanitize_name(payload.name, "\u65b0\u6587\u4ef6\u5939"),
        "type": category_type,
        "items": [],
    }
    if category_type == "image":
        category["dir"] = _unique_category_dir(library, payload.name)
        os.makedirs(os.path.join(_asset_root, category["dir"]), exist_ok=True)
    library.setdefault("categories", []).append(category)
    data["active_library_id"] = library.get("id") or data.get("active_library_id")
    save_asset_library(data)
    return {"library": data, "category": category}


@router.patch("/categories/{category_id}")
async def rename_asset_library_category(
    category_id: str,
    payload: AssetLibraryRenameRequest,
):
    _require_configured()
    data = load_asset_library()
    _, category = find_asset_category_with_library(data, category_id, payload.library_id)
    if not category:
        raise HTTPException(status_code=404, detail="\u5206\u7c7b\u4e0d\u5b58\u5728")
    category["name"] = _sanitize_name(payload.name, category.get("name") or "\u65b0\u6587\u4ef6\u5939")
    save_asset_library(data)
    return {"library": data, "category": category}


@router.delete("/categories/{category_id}")
async def delete_asset_library_category(category_id: str, library_id: str = ""):
    _require_configured()
    data = load_asset_library()
    library, category = find_asset_category_with_library(data, category_id, library_id)
    if not category:
        raise HTTPException(status_code=404, detail="\u5206\u7c7b\u4e0d\u5b58\u5728")
    if (
        category.get("type") == "workflow"
        and category_id == "workflows"
        and (library.get("id") or "") == "default"
    ):
        raise HTTPException(
            status_code=400,
            detail="\u9ed8\u8ba4\u5de5\u4f5c\u6d41\u5206\u7c7b\u4e0d\u80fd\u5220\u9664",
        )
    for item in category.get("items") or []:
        _remove_item_file(item)
    category_dir = str(category.get("dir") or "").strip("/").strip()
    if category_dir:
        target = os.path.abspath(os.path.join(_asset_root, category_dir))
        root = os.path.abspath(_asset_root)
        if target.startswith(root + os.sep) and os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
    library["categories"] = [
        item for item in library.get("categories", [])
        if item.get("id") != category_id
    ]
    save_asset_library(data)
    return {"library": data}
