"""Prompt library CRUD routes."""

from __future__ import annotations

import uuid
from typing import Any, Callable, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from repositories.prompt_libraries import (
    find_prompt_library,
    load_prompt_libraries,
    normalize_prompt_library_item,
    public_prompt_libraries,
    save_prompt_libraries,
)


router = APIRouter(prefix="/api/prompt-libraries", tags=["prompt-libraries"])
PROMPT_BUILTIN_CATEGORY_IDS = {"view", "storyboard", "character", "product", "lighting", "custom"}
_sanitize_name: Optional[Callable[[Any, str], str]] = None
_now_ms: Optional[Callable[[], int]] = None


def configure_prompt_library_routes(
    *,
    sanitize_name_fn: Callable[[Any, str], str],
    now_ms_fn: Callable[[], int],
) -> None:
    global _sanitize_name, _now_ms
    _sanitize_name = sanitize_name_fn
    _now_ms = now_ms_fn


def _require_configured() -> None:
    if _sanitize_name is None or _now_ms is None:
        raise RuntimeError("Prompt library routes are not configured")


class PromptLibraryRequest(BaseModel):
    name: str = "\u63d0\u793a\u8bcd\u5e93"


class PromptLibraryItemRequest(BaseModel):
    library_id: str = ""
    name: str = "\u63d0\u793a\u8bcd"
    category: str = "custom"
    positive: str = ""
    negative: str = ""
    scene: str = ""


class PromptLibraryBatchDeleteRequest(BaseModel):
    ids: List[str] = Field(default_factory=list)


class PromptLibraryCategoryRequest(BaseModel):
    library_id: str = ""
    name: str = ""


@router.get("")
async def get_prompt_libraries():
    return {"library": public_prompt_libraries()}


@router.post("")
async def create_prompt_library(payload: PromptLibraryRequest):
    _require_configured()
    data = load_prompt_libraries()
    library = {
        "id": f"lib_{uuid.uuid4().hex[:12]}",
        "name": _sanitize_name(payload.name, "\u63d0\u793a\u8bcd\u5e93"),
        "type": "prompt",
        "categories": [],
        "items": [],
    }
    data.setdefault("libraries", []).append(library)
    data["active_library_id"] = library["id"]
    data = save_prompt_libraries(data)
    normalized = next(
        (item for item in data.get("libraries", []) if item.get("id") == library["id"]),
        library,
    )
    return {"library": public_prompt_libraries(data), "prompt_library": normalized}


@router.patch("/{library_id}")
async def rename_prompt_library(library_id: str, payload: PromptLibraryRequest):
    _require_configured()
    data = load_prompt_libraries()
    library = find_prompt_library(data, library_id)
    if not library or library.get("id") != library_id:
        raise HTTPException(status_code=404, detail="\u63d0\u793a\u8bcd\u5e93\u4e0d\u5b58\u5728")
    library["name"] = _sanitize_name(payload.name, library.get("name") or "\u63d0\u793a\u8bcd\u5e93")
    data = save_prompt_libraries(data)
    return {"library": public_prompt_libraries(data), "prompt_library": library}


@router.delete("/{library_id}")
async def delete_prompt_library(library_id: str):
    if library_id == "system":
        raise HTTPException(
            status_code=400,
            detail="\u7cfb\u7edf\u63d0\u793a\u8bcd\u5e93\u4e0d\u80fd\u5220\u9664\uff0c\u53ef\u4ee5\u5220\u9664\u5176\u4e2d\u7684\u63d0\u793a\u8bcd",
        )
    data = load_prompt_libraries()
    libraries = data.get("libraries", []) or []
    kept = [library for library in libraries if library.get("id") != library_id]
    if len(kept) == len(libraries):
        raise HTTPException(status_code=404, detail="\u63d0\u793a\u8bcd\u5e93\u4e0d\u5b58\u5728")
    data["libraries"] = kept
    if data.get("active_library_id") == library_id:
        data["active_library_id"] = "system"
    data = save_prompt_libraries(data)
    return {"library": public_prompt_libraries(data)}


@router.post("/items")
async def add_prompt_library_item(payload: PromptLibraryItemRequest):
    _require_configured()
    data = load_prompt_libraries()
    library = find_prompt_library(data, payload.library_id)
    if not library:
        raise HTTPException(status_code=404, detail="\u63d0\u793a\u8bcd\u5e93\u4e0d\u5b58\u5728")
    if not str(payload.positive or "").strip():
        raise HTTPException(status_code=400, detail="\u63d0\u793a\u8bcd\u5185\u5bb9\u4e0d\u80fd\u4e3a\u7a7a")
    item = normalize_prompt_library_item({
        "id": f"tpl_{uuid.uuid4().hex[:12]}",
        "name": payload.name,
        "category": payload.category,
        "positive": payload.positive,
        "negative": payload.negative,
        "scene": payload.scene,
        "created_at": _now_ms(),
        "updated_at": _now_ms(),
    })
    library.setdefault("items", []).insert(0, item)
    data["active_library_id"] = library.get("id") or data.get("active_library_id")
    data = save_prompt_libraries(data)
    return {"library": public_prompt_libraries(data), "item": item}


@router.patch("/items/{item_id}")
async def update_prompt_library_item(item_id: str, payload: PromptLibraryItemRequest):
    _require_configured()
    data = load_prompt_libraries()
    for library in data.get("libraries", []) or []:
        if payload.library_id and library.get("id") != payload.library_id:
            continue
        for index, item in enumerate(library.get("items", []) or []):
            if item.get("id") != item_id:
                continue
            updated = normalize_prompt_library_item({
                **item,
                "name": payload.name or item.get("name"),
                "category": payload.category or item.get("category"),
                "positive": payload.positive or item.get("positive"),
                "negative": payload.negative,
                "scene": payload.scene,
                "updated_at": _now_ms(),
            })
            library["items"][index] = updated
            data = save_prompt_libraries(data)
            return {"library": public_prompt_libraries(data), "item": updated}
    raise HTTPException(status_code=404, detail="\u63d0\u793a\u8bcd\u4e0d\u5b58\u5728")


@router.delete("/items/{item_id}")
async def delete_prompt_library_item(item_id: str):
    data = load_prompt_libraries()
    removed = False
    for library in data.get("libraries", []) or []:
        before = len(library.get("items", []) or [])
        library["items"] = [
            item for item in library.get("items", []) or []
            if item.get("id") != item_id
        ]
        removed = removed or len(library["items"]) != before
    if not removed:
        raise HTTPException(status_code=404, detail="\u63d0\u793a\u8bcd\u4e0d\u5b58\u5728")
    data = save_prompt_libraries(data)
    return {"library": public_prompt_libraries(data), "removed": 1}


@router.post("/items/delete")
async def batch_delete_prompt_library_items(payload: PromptLibraryBatchDeleteRequest):
    ids = {str(item) for item in payload.ids if str(item)}
    if not ids:
        raise HTTPException(status_code=400, detail="\u6ca1\u6709\u9009\u62e9\u63d0\u793a\u8bcd")
    data = load_prompt_libraries()
    removed = 0
    for library in data.get("libraries", []) or []:
        kept = []
        for item in library.get("items", []) or []:
            if item.get("id") in ids:
                removed += 1
            else:
                kept.append(item)
        library["items"] = kept
    data = save_prompt_libraries(data)
    return {"library": public_prompt_libraries(data), "removed": removed}


@router.post("/categories")
async def add_prompt_library_category(payload: PromptLibraryCategoryRequest):
    _require_configured()
    data = load_prompt_libraries()
    library = find_prompt_library(data, payload.library_id) or find_prompt_library(data, "system")
    if not library:
        raise HTTPException(status_code=404, detail="\u63d0\u793a\u8bcd\u5e93\u4e0d\u5b58\u5728")
    existing = {
        str(category.get("id"))
        for category in library.get("categories") or []
        if isinstance(category, dict)
    } | PROMPT_BUILTIN_CATEGORY_IDS
    category_id = f"pcat_{uuid.uuid4().hex[:10]}"
    while category_id in existing:
        category_id = f"pcat_{uuid.uuid4().hex[:10]}"
    category = {
        "id": category_id,
        "name": _sanitize_name(payload.name, "\u65b0\u5206\u7ec4"),
    }
    library.setdefault("categories", []).append(category)
    data = save_prompt_libraries(data)
    return {"library": public_prompt_libraries(data), "category": category}


@router.patch("/categories/{category_id}")
async def rename_prompt_library_category(
    category_id: str,
    payload: PromptLibraryCategoryRequest,
):
    _require_configured()
    name = _sanitize_name(payload.name, "")
    if not name:
        raise HTTPException(status_code=400, detail="\u5206\u7ec4\u540d\u79f0\u4e0d\u80fd\u4e3a\u7a7a")
    data = load_prompt_libraries()
    updated = False
    for library in data.get("libraries", []) or []:
        for category in library.get("categories") or []:
            if isinstance(category, dict) and category.get("id") == category_id:
                category["name"] = name
                updated = True
    if not updated:
        raise HTTPException(status_code=404, detail="\u5206\u7ec4\u4e0d\u5b58\u5728")
    data = save_prompt_libraries(data)
    return {"library": public_prompt_libraries(data)}


@router.delete("/categories/{category_id}")
async def delete_prompt_library_category(category_id: str):
    data = load_prompt_libraries()
    found = False
    for library in data.get("libraries", []) or []:
        categories = library.get("categories") or []
        kept = [
            category for category in categories
            if not (isinstance(category, dict) and category.get("id") == category_id)
        ]
        if len(kept) == len(categories):
            continue
        found = True
        library["categories"] = kept
        fallback = next(
            (
                str(category.get("id"))
                for category in kept
                if isinstance(category, dict) and category.get("id")
            ),
            "",
        )
        for item in library.get("items", []) or []:
            if isinstance(item, dict) and item.get("category") == category_id:
                item["category"] = fallback
    if not found:
        raise HTTPException(status_code=404, detail="\u5206\u7ec4\u4e0d\u5b58\u5728")
    data = save_prompt_libraries(data)
    return {"library": public_prompt_libraries(data)}
