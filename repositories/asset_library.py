import json
import os
import re
import uuid


AVATAR_LEGACY_FLAT_FIELDS = (
    "platform",
    "provider_id",
    "project_name",
    "avatar_task_id",
    "avatar_status",
    "avatar_detail",
    "asset_uri",
    "asset_id",
    "registered_at",
)

_ASSET_LIBRARY_PATH = ""
_DATA_DIR = ""
_NOW_MS = None
_NAME_SANITIZER = None
_UPDATED_CALLBACK = None


def configure_asset_library_storage(asset_library_path, data_dir, now_ms_fn, name_sanitizer=None, updated_callback=None):
    global _ASSET_LIBRARY_PATH, _DATA_DIR, _NOW_MS, _NAME_SANITIZER, _UPDATED_CALLBACK
    _ASSET_LIBRARY_PATH = asset_library_path
    _DATA_DIR = data_dir
    _NOW_MS = now_ms_fn
    _NAME_SANITIZER = name_sanitizer
    _UPDATED_CALLBACK = updated_callback


def _now_ms():
    return int(_NOW_MS()) if _NOW_MS else 0


def _sanitize_asset_name(name, fallback="asset"):
    if _NAME_SANITIZER:
        return _NAME_SANITIZER(name, fallback)
    name = re.sub(r'[\\/:*?"<>|]+', "_", str(name or fallback)).strip()
    return name[:120] or fallback


def default_asset_library():
    categories = [
        {"id": "characters", "name": "角色", "type": "image", "items": []},
        {"id": "scenes", "name": "场景", "type": "image", "items": []},
        {"id": "workflows", "name": "工作流", "type": "workflow", "items": []},
    ]
    return {
        "active_library_id": "default",
        "libraries": [{"id": "default", "name": "默认资产库", "type": "asset", "categories": categories}],
        "categories": categories,
        "updated_at": _now_ms(),
    }


def normalize_asset_library(lib):
    if not isinstance(lib, dict):
        lib = default_asset_library()
    legacy_categories = lib.get("categories") if isinstance(lib.get("categories"), list) else None
    libraries = lib.get("libraries") if isinstance(lib.get("libraries"), list) else []
    if not libraries:
        libraries = [
            {
                "id": "default",
                "name": "默认资产库",
                "type": "asset",
                "categories": legacy_categories or default_asset_library()["categories"],
            }
        ]
    for library in libraries:
        library["id"] = re.sub(r"[^A-Za-z0-9_-]+", "_", str(library.get("id") or f"lib_{uuid.uuid4().hex[:8]}"))[:40]
        library["name"] = _sanitize_asset_name(library.get("name") or "资产库", "资产库")
        cats = library.get("categories") if isinstance(library.get("categories"), list) else []
        if library.get("id") == "default" and not any(c.get("type") == "workflow" for c in cats):
            cats.append({"id": "workflows", "name": "工作流", "type": "workflow", "items": []})
        for cat in cats:
            for item in cat.get("items") or []:
                migrate_asset_item_registrations(item)
        library["categories"] = cats
    active = str(lib.get("active_library_id") or libraries[0].get("id") or "default")
    if not any(item.get("id") == active for item in libraries):
        active = libraries[0].get("id") or "default"
    active_library = next((item for item in libraries if item.get("id") == active), libraries[0])
    lib["libraries"] = libraries
    lib["active_library_id"] = active
    lib["categories"] = active_library.get("categories") or []
    lib["updated_at"] = int(lib.get("updated_at") or _now_ms())
    sort_asset_library_items(lib)
    return lib


def migrate_asset_item_registrations(item):
    if not isinstance(item, dict):
        return
    regs = item.get("registrations")
    if not isinstance(regs, dict):
        regs = {}
    legacy_platform = str(item.get("platform") or "").strip()
    if legacy_platform and legacy_platform not in regs and (item.get("asset_uri") or item.get("avatar_task_id")):
        regs[legacy_platform] = {
            "provider_id": item.get("provider_id") or "",
            "project_name": item.get("project_name") or "default",
            "task_id": item.get("avatar_task_id") or "",
            "status": item.get("avatar_status") or "",
            "detail": item.get("avatar_detail") or "",
            "asset_uri": item.get("asset_uri") or "",
            "asset_id": item.get("asset_id") or "",
            "registered_at": item.get("registered_at") or 0,
        }
    item["registrations"] = regs if isinstance(regs, dict) else {}
    for key in AVATAR_LEGACY_FLAT_FIELDS:
        item.pop(key, None)


def load_asset_library():
    if not os.path.exists(_ASSET_LIBRARY_PATH):
        lib = default_asset_library()
        save_asset_library(lib)
        return lib
    try:
        with open(_ASSET_LIBRARY_PATH, "r", encoding="utf-8") as f:
            lib = json.load(f)
    except Exception:
        lib = default_asset_library()
    return normalize_asset_library(lib)


def sort_asset_library_items(lib):
    cats = list(lib.get("categories", []))
    for library in lib.get("libraries", []) if isinstance(lib.get("libraries"), list) else []:
        cats.extend(library.get("categories") or [])
    seen = set()
    for cat in cats:
        if id(cat) in seen:
            continue
        seen.add(id(cat))
        items = cat.get("items")
        if isinstance(items, list):

            def created_at_key(item):
                if not isinstance(item, dict):
                    return 0
                try:
                    return int(float(item.get("created_at") or 0))
                except (TypeError, ValueError):
                    return 0

            items.sort(key=created_at_key, reverse=True)


def save_asset_library(lib):
    lib = normalize_asset_library(lib)
    sort_asset_library_items(lib)
    lib["updated_at"] = _now_ms()
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_ASSET_LIBRARY_PATH, "w", encoding="utf-8") as f:
        json.dump(lib, f, ensure_ascii=False, indent=2)
    if _UPDATED_CALLBACK:
        _UPDATED_CALLBACK(int(lib["updated_at"]))
    return lib


def find_asset_category(lib, category_id):
    for cat in lib.get("categories", []):
        if cat.get("id") == category_id:
            return cat
    return None


def find_asset_library(lib, library_id=""):
    lib = normalize_asset_library(lib)
    library_id = str(library_id or lib.get("active_library_id") or "").strip()
    return next((item for item in lib.get("libraries", []) if item.get("id") == library_id), None) or (lib.get("libraries") or [None])[0]


def find_asset_category_in_library(lib, category_id, library_id=""):
    library = find_asset_library(lib, library_id)
    if not library:
        return None
    for cat in library.get("categories", []):
        if cat.get("id") == category_id:
            return cat
    return None


def find_asset_category_with_library(lib, category_id, library_id=""):
    lib = normalize_asset_library(lib)
    preferred = str(library_id or "").strip()
    libraries = lib.get("libraries", []) or []
    if preferred:
        libraries = [item for item in libraries if item.get("id") == preferred]
    for library in libraries:
        for cat in library.get("categories", []) or []:
            if cat.get("id") == category_id:
                return library, cat
    return None, None
