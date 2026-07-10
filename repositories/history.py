"""Generation history persistence."""

from __future__ import annotations

import json
import os
from threading import Lock
from typing import Any, Callable, Optional


_history_path = ""
_lock: Optional[Lock] = None
_resolve_output_file: Optional[Callable[[str], Optional[str]]] = None


def configure_history_storage(
    *,
    history_path: str,
    lock: Lock,
    resolve_output_file_fn: Callable[[str], Optional[str]],
) -> None:
    global _history_path, _lock, _resolve_output_file
    _history_path = history_path
    _lock = lock
    _resolve_output_file = resolve_output_file_fn


def _require_configured() -> None:
    if not _history_path or _lock is None or _resolve_output_file is None:
        raise RuntimeError("History storage is not configured")


def list_history(history_type: Optional[str] = None) -> list[dict[str, Any]]:
    _require_configured()
    if not os.path.exists(_history_path):
        return []
    try:
        with open(_history_path, "r", encoding="utf-8") as history_file:
            data = json.load(history_file)
    except Exception as exc:
        print(f"Failed to read history file: {exc}")
        return []
    if not isinstance(data, list):
        return []
    if history_type:
        data = [
            item for item in data
            if isinstance(item, dict) and item.get("type", "zimage") == history_type
        ]
    data = [
        item for item in data
        if isinstance(item, dict) and item.get("images")
    ]
    data.sort(
        key=lambda item: float(item.get("timestamp", 0))
        if isinstance(item.get("timestamp", 0), (int, float))
        else 0,
        reverse=True,
    )
    return data


def delete_history_record(timestamp: Any) -> dict[str, Any]:
    _require_configured()
    if not os.path.exists(_history_path):
        return {"success": False, "message": "History file not found"}
    try:
        target_record = None
        with _lock:
            with open(_history_path, "r", encoding="utf-8") as history_file:
                history = json.load(history_file)
            kept = []
            for item in history if isinstance(history, list) else []:
                item_timestamp = item.get("timestamp", 0)
                if (
                    isinstance(timestamp, (int, float))
                    and isinstance(item_timestamp, (int, float))
                    and abs(float(item_timestamp) - float(timestamp)) < 0.001
                ) or (
                    not (
                        isinstance(timestamp, (int, float))
                        and isinstance(item_timestamp, (int, float))
                    )
                    and str(item_timestamp) == str(timestamp)
                ):
                    target_record = item
                else:
                    kept.append(item)
            if target_record:
                with open(_history_path, "w", encoding="utf-8") as history_file:
                    json.dump(kept, history_file, ensure_ascii=False, indent=4)
        if not target_record:
            return {"success": False, "message": "Record not found"}
        for image_url in target_record.get("images", []):
            file_path = _resolve_output_file(image_url)
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as exc:
                    print(f"Failed to delete file {file_path}: {exc}")
        return {"success": True}
    except Exception as exc:
        print(f"Delete history error: {exc}")
        return {"success": False, "message": str(exc)}
