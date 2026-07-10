"""JSON storage for user-configured RunningHub workflows."""

from __future__ import annotations

import json
import os
from typing import Any


_workflow_store_path = ""
_data_dir = ""


def configure_runninghub_workflow_storage(*, workflow_store_path: str, data_dir: str) -> None:
    global _workflow_store_path, _data_dir
    _workflow_store_path = workflow_store_path
    _data_dir = data_dir


def _require_configured() -> None:
    if not _workflow_store_path or not _data_dir:
        raise RuntimeError("RunningHub workflow storage is not configured")


def runninghub_workflow_store_path() -> str:
    _require_configured()
    return _workflow_store_path


def load_runninghub_workflow_store() -> dict[str, Any]:
    _require_configured()
    if not os.path.exists(_workflow_store_path):
        return {}
    try:
        with open(_workflow_store_path, "r", encoding="utf-8") as workflow_file:
            data = json.load(workflow_file)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_runninghub_workflow_store(store: dict[str, Any]) -> None:
    _require_configured()
    os.makedirs(_data_dir, exist_ok=True)
    with open(_workflow_store_path, "w", encoding="utf-8") as workflow_file:
        json.dump(store, workflow_file, ensure_ascii=False, indent=2)
