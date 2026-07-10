"""JSON-backed prompt library storage and normalization."""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Callable, Optional


_prompt_library_path = ""
_data_dir = ""
_now_ms: Optional[Callable[[], int]] = None
_name_sanitizer: Optional[Callable[[Any, str], str]] = None
_builtin_templates: Optional[Callable[[], list[dict[str, Any]]]] = None


def configure_prompt_library_storage(
    *,
    prompt_library_path: str,
    data_dir: str,
    now_ms_fn: Callable[[], int],
    name_sanitizer: Callable[[Any, str], str],
    builtin_templates_fn: Callable[[], list[dict[str, Any]]],
) -> None:
    global _prompt_library_path, _data_dir, _now_ms, _name_sanitizer, _builtin_templates
    _prompt_library_path = prompt_library_path
    _data_dir = data_dir
    _now_ms = now_ms_fn
    _name_sanitizer = name_sanitizer
    _builtin_templates = builtin_templates_fn


def _require_configured() -> None:
    if not all((_prompt_library_path, _data_dir, _now_ms, _name_sanitizer, _builtin_templates)):
        raise RuntimeError("Prompt library storage is not configured")


def _now() -> int:
    _require_configured()
    return int(_now_ms())


def _sanitize(name: Any, fallback: str) -> str:
    _require_configured()
    return _name_sanitizer(name, fallback)


def normalize_prompt_category_id(category: Any = "custom") -> str:
    category_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(category or "custom"))[:40] or "custom"
    return "custom" if category_id in {"mine", "my", "personal"} else category_id


def normalize_prompt_library_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        item = {}
    fallback_name = "\u63d0\u793a\u8bcd"
    return {
        "id": re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            str(item.get("id") or item.get("item_id") or f"tpl_{uuid.uuid4().hex[:12]}"),
        )[:60],
        "name": _sanitize(item.get("name") or fallback_name, fallback_name),
        "category": normalize_prompt_category_id(item.get("category") or "custom"),
        "scene": str(item.get("scene") or "").strip()[:500],
        "positive": str(item.get("positive") or item.get("text") or "").strip(),
        "negative": str(item.get("negative") or "").strip(),
        "params": item.get("params") if isinstance(item.get("params"), dict) else {},
        "created_at": int(item.get("created_at") or _now()),
        "updated_at": int(item.get("updated_at") or item.get("created_at") or _now()),
    }


def default_prompt_template_categories() -> list[dict[str, str]]:
    return [
        {"id": "view", "name": "\u89c6\u89d2"},
        {"id": "storyboard", "name": "\u5206\u955c"},
        {"id": "character", "name": "\u89d2\u8272"},
        {"id": "product", "name": "\u4ea7\u54c1"},
        {"id": "lighting", "name": "\u5149\u5f71"},
        {"id": "custom", "name": "\u6211\u7684"},
    ]


def seed_system_prompt_library() -> dict[str, Any]:
    _require_configured()
    return {
        "id": "system",
        "name": "\u7cfb\u7edf\u63d0\u793a\u8bcd\u5e93",
        "type": "prompt",
        "items": _builtin_templates(),
        "categories": default_prompt_template_categories(),
    }


def default_prompt_libraries() -> dict[str, Any]:
    return {
        "active_library_id": "system",
        "libraries": [seed_system_prompt_library()],
        "updated_at": _now(),
    }


def normalize_prompt_template_categories(
    *category_lists: Any,
    include_defaults: bool = True,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_category(category: Any) -> None:
        if not isinstance(category, dict):
            return
        category_id = normalize_prompt_category_id(category.get("id") or category.get("name") or "custom")
        if category_id in seen:
            return
        seen.add(category_id)
        normalized.append({
            "id": category_id,
            "name": _sanitize(category.get("name") or category_id, category_id),
        })

    for categories in category_lists:
        if isinstance(categories, list):
            for category in categories:
                add_category(category)
    if include_defaults and not normalized:
        for category in default_prompt_template_categories():
            add_category(category)
    return normalized


def normalize_prompt_libraries(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = default_prompt_libraries()
    raw_libraries = data.get("libraries") if isinstance(data.get("libraries"), list) else []
    raw_libraries = [library for library in raw_libraries if isinstance(library, dict)]
    if not any(library.get("id") == "system" for library in raw_libraries):
        raw_libraries = [seed_system_prompt_library(), *raw_libraries]

    libraries: list[dict[str, Any]] = []
    seen_library_ids: set[str] = set()
    for raw in raw_libraries:
        is_system = raw.get("id") == "system"
        library_id = "system" if is_system else (
            re.sub(
                r"[^A-Za-z0-9_-]+",
                "_",
                str(raw.get("id") or f"lib_{uuid.uuid4().hex[:12]}"),
            )[:60]
            or f"lib_{uuid.uuid4().hex[:12]}"
        )
        if library_id in seen_library_ids:
            continue
        seen_library_ids.add(library_id)

        items: list[dict[str, Any]] = []
        seen_item_ids: set[str] = set()
        for raw_item in raw.get("items") if isinstance(raw.get("items"), list) else []:
            if not isinstance(raw_item, dict):
                continue
            item = normalize_prompt_library_item(raw_item)
            item_id = item.get("id") or f"tpl_{uuid.uuid4().hex[:12]}"
            if item_id in seen_item_ids:
                continue
            seen_item_ids.add(item_id)
            items.append(item)

        default_name = "\u7cfb\u7edf\u63d0\u793a\u8bcd\u5e93" if is_system else "\u63d0\u793a\u8bcd\u5e93"
        raw_categories = raw.get("categories") if isinstance(raw.get("categories"), list) else []
        if not is_system:
            builtin_ids = {"view", "storyboard", "character", "product", "lighting", "custom"}
            raw_categories = [
                category
                for category in raw_categories
                if isinstance(category, dict)
                and normalize_prompt_category_id(category.get("id") or category.get("name") or "") not in builtin_ids
            ]
        libraries.append({
            "id": library_id,
            "name": _sanitize(raw.get("name") or default_name, default_name),
            "type": "prompt",
            "readonly": False,
            "system": is_system,
            "categories": normalize_prompt_template_categories(
                raw_categories,
                include_defaults=is_system,
            ),
            "items": items,
        })

    active_library_id = str(data.get("active_library_id") or "system")
    if not any(library["id"] == active_library_id for library in libraries):
        active_library_id = (
            "system"
            if any(library["id"] == "system" for library in libraries)
            else (libraries[0]["id"] if libraries else "system")
        )
    return {
        "active_library_id": active_library_id,
        "libraries": libraries,
        "updated_at": int(data.get("updated_at") or _now()),
    }


def load_prompt_libraries() -> dict[str, Any]:
    _require_configured()
    if not os.path.exists(_prompt_library_path):
        return save_prompt_libraries(default_prompt_libraries())
    try:
        with open(_prompt_library_path, "r", encoding="utf-8") as prompt_file:
            data = json.load(prompt_file)
    except Exception:
        data = default_prompt_libraries()
    if not isinstance(data, dict):
        data = default_prompt_libraries()
    normalized = normalize_prompt_libraries(data)
    if (
        normalized.get("active_library_id") != data.get("active_library_id")
        or normalized.get("libraries") != data.get("libraries")
    ):
        return save_prompt_libraries(normalized)
    return normalized


def save_prompt_libraries(data: Any) -> dict[str, Any]:
    _require_configured()
    normalized = normalize_prompt_libraries(data)
    normalized["updated_at"] = _now()
    os.makedirs(_data_dir, exist_ok=True)
    with open(_prompt_library_path, "w", encoding="utf-8") as prompt_file:
        json.dump(normalized, prompt_file, ensure_ascii=False, indent=2)
    return normalized


def public_prompt_libraries(data: Any = None) -> dict[str, Any]:
    normalized = normalize_prompt_libraries(data or load_prompt_libraries())
    libraries = normalized.get("libraries") or []
    return {
        "active_library_id": normalized.get("active_library_id")
        or (libraries[0].get("id") if libraries else None)
        or "system",
        "libraries": libraries,
        "updated_at": normalized.get("updated_at") or _now(),
    }


def find_prompt_library(data: Any, library_id: str = "") -> Optional[dict[str, Any]]:
    if not isinstance(data, dict):
        return None
    libraries = data.get("libraries") if isinstance(data.get("libraries"), list) else []
    target_id = str(library_id or data.get("active_library_id") or "").strip()
    return next((item for item in libraries if item.get("id") == target_id), None) or (
        libraries[0] if libraries else None
    )
