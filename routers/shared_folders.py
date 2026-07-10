"""Registered shared-folder routes."""

from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from repositories.asset_library import (
    find_asset_category_in_library,
    load_asset_library,
    save_asset_library,
)
from repositories.shared_folders import (
    SHARED_MEDIA_EXTS,
    list_shared_folders,
    register_shared_folder,
    scan_shared_tree,
    shared_child_abs,
    shared_folder_abs,
    shared_folder_by_id,
    unregister_shared_folder,
)


router = APIRouter(prefix="/api/shared-folders", tags=["shared-folders"])
_sanitize_name: Optional[Callable[[Any, str], str]] = None
_content_type: Optional[Callable[[str], str]] = None
_make_asset_item: Optional[Callable[[str, str, str], tuple[str, dict[str, Any]]]] = None
_classify_image: Optional[Callable[[str], Awaitable[Optional[dict[str, Any]]]]] = None
_resolve_local_file: Optional[Callable[[str], Optional[str]]] = None


def configure_shared_folder_routes(
    *,
    sanitize_name_fn: Callable[[Any, str], str],
    content_type_fn: Callable[[str], str],
    make_asset_item_fn: Callable[[str, str, str], tuple[str, dict[str, Any]]],
    classify_image_fn: Callable[[str], Awaitable[Optional[dict[str, Any]]]],
    resolve_local_file_fn: Callable[[str], Optional[str]],
) -> None:
    global _sanitize_name, _content_type, _make_asset_item
    global _classify_image, _resolve_local_file
    _sanitize_name = sanitize_name_fn
    _content_type = content_type_fn
    _make_asset_item = make_asset_item_fn
    _classify_image = classify_image_fn
    _resolve_local_file = resolve_local_file_fn


def _require_configured() -> None:
    if not all((_sanitize_name, _content_type, _make_asset_item, _classify_image, _resolve_local_file)):
        raise RuntimeError("Shared folder routes are not configured")


class SharedFolderRegister(BaseModel):
    path: str = ""
    name: str = ""


class SharedFolderImport(BaseModel):
    library_id: str = ""
    category_id: str = ""
    folder_id: str = ""
    paths: List[str] = Field(default_factory=list)


@router.get("")
async def get_shared_folders():
    return {"folders": list_shared_folders()}


@router.post("")
async def create_shared_folder(payload: SharedFolderRegister):
    _require_configured()
    absolute_path = payload.path
    fallback = os.path.basename(str(absolute_path or "").rstrip("/\\")) or "\u5171\u4eab\u6587\u4ef6\u5939"
    name = _sanitize_name(payload.name or fallback, "\u5171\u4eab\u6587\u4ef6\u5939")
    return {"folder": register_shared_folder(payload.path, name)}


@router.delete("/{folder_id}")
async def delete_shared_folder(folder_id: str):
    unregister_shared_folder(folder_id)
    return {"ok": True}


@router.get("/{folder_id}/tree")
async def get_shared_folder_tree(folder_id: str):
    entry = shared_folder_by_id(folder_id)
    if not entry:
        raise HTTPException(status_code=404, detail="\u5171\u4eab\u6587\u4ef6\u5939\u4e0d\u5b58\u5728")
    absolute_path = shared_folder_abs(entry)
    if not os.path.isdir(absolute_path):
        raise HTTPException(status_code=404, detail="\u6587\u4ef6\u5939\u5df2\u4e0d\u5b58\u5728")
    tree = scan_shared_tree(
        folder_id,
        absolute_path,
        "",
        entry.get("name") or os.path.basename(absolute_path),
    )
    return {
        "folder": {"id": folder_id, "name": entry.get("name"), "path": absolute_path},
        "tree": tree,
    }


@router.get("/{folder_id}/file")
async def get_shared_folder_file(folder_id: str, path: str = ""):
    _require_configured()
    entry = shared_folder_by_id(folder_id)
    if not entry:
        raise HTTPException(status_code=404, detail="\u5171\u4eab\u6587\u4ef6\u5939\u4e0d\u5b58\u5728")
    absolute_path = shared_child_abs(shared_folder_abs(entry), path)
    if not os.path.isfile(absolute_path):
        raise HTTPException(status_code=404, detail="\u6587\u4ef6\u4e0d\u5b58\u5728")
    if os.path.splitext(absolute_path)[1].lower() not in SHARED_MEDIA_EXTS:
        raise HTTPException(status_code=400, detail="\u4e0d\u652f\u6301\u7684\u6587\u4ef6\u7c7b\u578b")
    return FileResponse(absolute_path, media_type=_content_type(absolute_path))


@router.post("/import")
async def import_shared_folder_files(payload: SharedFolderImport):
    _require_configured()
    entry = shared_folder_by_id(payload.folder_id)
    if not entry:
        raise HTTPException(status_code=404, detail="\u5171\u4eab\u6587\u4ef6\u5939\u4e0d\u5b58\u5728")
    folder_abs = shared_folder_abs(entry)
    data = load_asset_library()
    category = find_asset_category_in_library(data, payload.category_id, payload.library_id)
    if not category:
        raise HTTPException(status_code=404, detail="\u5206\u7c7b\u4e0d\u5b58\u5728")
    if category.get("type") != "image":
        raise HTTPException(
            status_code=400,
            detail="\u8be5\u5206\u7c7b\u6682\u4e0d\u652f\u6301\u6dfb\u52a0\u5a92\u4f53",
        )
    added = []
    for relative_path in payload.paths[:200]:
        absolute_path = shared_child_abs(folder_abs, relative_path)
        if (
            not os.path.isfile(absolute_path)
            or os.path.splitext(absolute_path)[1].lower() not in SHARED_MEDIA_EXTS
        ):
            continue
        _, item = _make_asset_item(
            absolute_path,
            os.path.basename(absolute_path),
            category.get("dir") or "",
        )
        if item.get("kind") == "image":
            local_path = _resolve_local_file(item.get("url") or "") or absolute_path
            classification = await _classify_image(local_path)
            if classification:
                item["classification"] = classification
        category.setdefault("items", []).append(item)
        added.append(item)
    save_asset_library(data)
    return {"library": data, "items": added}
