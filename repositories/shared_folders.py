"""Registered shared-folder storage and path-safe tree scanning."""

from __future__ import annotations

import json
import os
import urllib.parse
import uuid
from threading import Lock
from typing import Any, Callable, Optional

from fastapi import HTTPException


SHARED_MEDIA_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".mp4", ".webm", ".mov", ".m4v", ".mkv",
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac",
}
SHARED_SCAN_MAX_ENTRIES = 8000

_registry_path = ""
_data_dir = ""
_base_dir = ""
_lock: Optional[Lock] = None
_media_kind: Optional[Callable[[str], str]] = None
_now_ms: Optional[Callable[[], int]] = None


def configure_shared_folder_storage(
    *,
    registry_path: str,
    data_dir: str,
    base_dir: str,
    lock: Lock,
    media_kind_fn: Callable[[str], str],
    now_ms_fn: Callable[[], int],
) -> None:
    global _registry_path, _data_dir, _base_dir, _lock, _media_kind, _now_ms
    _registry_path = registry_path
    _data_dir = data_dir
    _base_dir = base_dir
    _lock = lock
    _media_kind = media_kind_fn
    _now_ms = now_ms_fn


def _require_configured() -> None:
    if not all((_registry_path, _data_dir, _base_dir, _lock, _media_kind, _now_ms)):
        raise RuntimeError("Shared folder storage is not configured")


def shared_folders_load() -> dict[str, list[dict[str, Any]]]:
    _require_configured()
    try:
        with open(_registry_path, "r", encoding="utf-8") as registry_file:
            data = json.load(registry_file)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    folders = data.get("folders")
    if not isinstance(folders, list):
        folders = []
    return {"folders": [folder for folder in folders if isinstance(folder, dict)]}


def shared_folders_save(data: dict[str, Any]) -> None:
    _require_configured()
    os.makedirs(_data_dir, exist_ok=True)
    with open(_registry_path, "w", encoding="utf-8") as registry_file:
        json.dump(data, registry_file, ensure_ascii=False, indent=2)


def shared_folder_by_id(folder_id: str) -> Optional[dict[str, Any]]:
    return next(
        (
            entry for entry in shared_folders_load().get("folders", [])
            if entry.get("id") == folder_id
        ),
        None,
    )


def shared_folder_abs(entry: Any) -> str:
    _require_configured()
    relative_path = (entry or {}).get("rel") or ""
    return os.path.normpath(os.path.join(_base_dir, relative_path))


def shared_resolve_register(path: str) -> tuple[str, str]:
    _require_configured()
    raw = (path or "").strip().strip('"').strip("'")
    if not raw:
        raise HTTPException(status_code=400, detail="\u8bf7\u63d0\u4f9b\u6587\u4ef6\u5939\u8def\u5f84")
    candidate = raw if os.path.isabs(raw) else os.path.join(_base_dir, raw)
    absolute_path = os.path.normpath(os.path.abspath(candidate))
    base = os.path.normpath(os.path.abspath(_base_dir))
    try:
        common = os.path.commonpath([absolute_path, base])
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="\u53ea\u5141\u8bb8\u767b\u8bb0\u9879\u76ee\u76ee\u5f55\u5185\u7684\u6587\u4ef6\u5939",
        ) from exc
    if common != base:
        raise HTTPException(
            status_code=400,
            detail="\u53ea\u5141\u8bb8\u767b\u8bb0\u9879\u76ee\u76ee\u5f55\u5185\u7684\u6587\u4ef6\u5939",
        )
    if absolute_path == base:
        raise HTTPException(
            status_code=400,
            detail="\u4e0d\u80fd\u76f4\u63a5\u767b\u8bb0\u9879\u76ee\u6839\u76ee\u5f55\uff0c\u8bf7\u9009\u62e9\u5b50\u6587\u4ef6\u5939",
        )
    if not os.path.isdir(absolute_path):
        raise HTTPException(status_code=400, detail="\u6587\u4ef6\u5939\u4e0d\u5b58\u5728")
    return absolute_path, os.path.relpath(absolute_path, base)


def shared_child_abs(folder_abs: str, relative_path: str) -> str:
    relative_path = (relative_path or "").replace("\\", "/").lstrip("/")
    absolute_path = os.path.normpath(os.path.join(folder_abs, relative_path))
    base = os.path.normpath(os.path.abspath(folder_abs))
    try:
        common = os.path.commonpath([os.path.abspath(absolute_path), base])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="\u975e\u6cd5\u8def\u5f84") from exc
    if common != base:
        raise HTTPException(status_code=400, detail="\u975e\u6cd5\u8def\u5f84")
    return absolute_path


def list_shared_folders() -> list[dict[str, Any]]:
    folders = []
    for entry in shared_folders_load().get("folders", []):
        absolute_path = shared_folder_abs(entry)
        folders.append({
            "id": entry.get("id"),
            "name": entry.get("name") or os.path.basename(absolute_path) or absolute_path,
            "rel": entry.get("rel") or "",
            "path": absolute_path,
            "exists": os.path.isdir(absolute_path),
            "created_at": entry.get("created_at"),
        })
    return folders


def register_shared_folder(path: str, name: str) -> dict[str, Any]:
    _require_configured()
    absolute_path, relative_path = shared_resolve_register(path)
    with _lock:
        data = shared_folders_load()
        for entry in data.get("folders", []):
            if os.path.normpath(shared_folder_abs(entry)) == os.path.normpath(absolute_path):
                entry["name"] = name
                shared_folders_save(data)
                return {**entry, "path": absolute_path, "exists": True}
        entry = {
            "id": f"shared_{uuid.uuid4().hex[:12]}",
            "name": name,
            "rel": relative_path,
            "created_at": _now_ms(),
        }
        data.setdefault("folders", []).append(entry)
        shared_folders_save(data)
    return {**entry, "path": absolute_path, "exists": True}


def unregister_shared_folder(folder_id: str) -> None:
    _require_configured()
    with _lock:
        data = shared_folders_load()
        before = len(data.get("folders", []))
        data["folders"] = [
            folder for folder in data.get("folders", [])
            if folder.get("id") != folder_id
        ]
        if len(data["folders"]) == before:
            raise HTTPException(
                status_code=404,
                detail="\u5171\u4eab\u6587\u4ef6\u5939\u4e0d\u5b58\u5728",
            )
        shared_folders_save(data)


def scan_shared_tree(
    folder_id: str,
    folder_abs: str,
    relative_prefix: str = "",
    display: str = "",
    counter: Optional[dict[str, int]] = None,
) -> dict[str, Any]:
    _require_configured()
    if counter is None:
        counter = {"n": 0}
    node = {
        "id": f"{folder_id}:{relative_prefix or '__root__'}",
        "name": display or os.path.basename(folder_abs) or folder_abs,
        "path": relative_prefix,
        "items": [],
        "children": [],
    }
    try:
        entries = sorted(os.scandir(folder_abs), key=lambda entry: (not entry.is_dir(), entry.name.lower()))
    except OSError:
        return node
    for entry in entries:
        if counter["n"] >= SHARED_SCAN_MAX_ENTRIES:
            break
        if entry.name.startswith((".", "._")):
            continue
        child_relative = f"{relative_prefix}/{entry.name}".lstrip("/")
        if entry.is_dir():
            child = scan_shared_tree(folder_id, entry.path, child_relative, entry.name, counter)
            if child["items"] or child["children"]:
                node["children"].append(child)
            continue
        if not entry.is_file() or os.path.splitext(entry.name)[1].lower() not in SHARED_MEDIA_EXTS:
            continue
        counter["n"] += 1
        try:
            stat = entry.stat()
            size = stat.st_size
            modified = int(stat.st_mtime * 1000)
        except OSError:
            size = 0
            modified = 0
        node["items"].append({
            "id": f"{folder_id}:{child_relative}",
            "name": entry.name,
            "url": f"/api/shared-folders/{folder_id}/file?path={urllib.parse.quote(child_relative)}",
            "kind": _media_kind(entry.name),
            "size": size,
            "lastModified": modified,
            "relativePath": child_relative,
            "folderId": folder_id,
        })
    return node
