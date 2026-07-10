"""Local ComfyUI workflow CRUD and execution routes."""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/workflows", tags=["workflows"])

BUILTIN_WORKFLOWS = {
    "Z-Image.json",
    "Z-Image-Enhance.json",
    "2511.json",
    "klein-enhance.json",
    "Flux2-Klein.json",
    "upscale.json",
}
CUSTOM_WORKFLOW_FOLDER = "custom"
LEGACY_CUSTOM_WORKFLOW_FOLDER = "\u81ea\u5b9a\u4e49"
WORKFLOW_NAME_RE = re.compile(
    rf"^(?:(?:{CUSTOM_WORKFLOW_FOLDER}|{LEGACY_CUSTOM_WORKFLOW_FOLDER})/)?"
    r"[a-zA-Z0-9_\u4e00-\u9fff.\-]+\.json$"
)

_workflow_dir = ""
_generate_request_factory: Optional[Callable[..., Any]] = None
_generate: Optional[Callable[[Any], Any]] = None


def configure_workflow_routes(
    *,
    workflow_dir: str,
    generate_request_factory: Callable[..., Any],
    generate_fn: Callable[[Any], Any],
) -> None:
    global _workflow_dir, _generate_request_factory, _generate
    _workflow_dir = workflow_dir
    _generate_request_factory = generate_request_factory
    _generate = generate_fn


def _require_configured() -> None:
    if not _workflow_dir or _generate_request_factory is None or _generate is None:
        raise RuntimeError("Workflow routes are not configured")


class WorkflowField(BaseModel):
    id: str
    node: str = ""
    input: str = ""
    name: str = ""
    type: str = "text"
    default: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    options: List[str] = Field(default_factory=list)
    random_enabled: bool = False


class WorkflowConfig(BaseModel):
    title: str = ""
    fields: List[WorkflowField] = Field(default_factory=list)
    mini_cards: Dict[str, Any] = Field(default_factory=dict)


class WorkflowUploadRequest(BaseModel):
    name: str
    workflow: Dict[str, Any]


class WorkflowRunRequest(BaseModel):
    fields: Dict[str, Any] = Field(default_factory=dict)
    config: WorkflowConfig
    client_id: str = ""


def workflow_path_from_name(name: str) -> str:
    _require_configured()
    if not WORKFLOW_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid workflow name")
    path = os.path.abspath(os.path.join(_workflow_dir, *name.split("/")))
    workflow_root = os.path.abspath(_workflow_dir)
    if os.path.commonpath([workflow_root, path]) != workflow_root:
        raise HTTPException(status_code=400, detail="Invalid workflow name")
    return path


def workflow_config_path(name: str) -> str:
    return workflow_path_from_name(name).replace(".json", ".config.json")


def is_builtin_workflow(name: str) -> bool:
    return "/" not in name and os.path.basename(name) in BUILTIN_WORKFLOWS


@router.get("")
def list_workflows():
    _require_configured()
    if not os.path.isdir(_workflow_dir):
        return {"workflows": []}
    items = []
    for root, dirs, files in os.walk(_workflow_dir):
        if os.path.abspath(root) == os.path.abspath(_workflow_dir):
            dirs[:] = [
                directory
                for directory in dirs
                if directory in {CUSTOM_WORKFLOW_FOLDER, LEGACY_CUSTOM_WORKFLOW_FOLDER}
            ]
        for filename in sorted(files):
            if not filename.endswith(".json") or filename.endswith(".config.json"):
                continue
            relative_name = os.path.relpath(
                os.path.join(root, filename),
                _workflow_dir,
            ).replace("\\", "/")
            if is_builtin_workflow(relative_name):
                continue
            config = {}
            config_path = workflow_config_path(relative_name)
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as config_file:
                        config = json.load(config_file) or {}
                except Exception:
                    config = {}
            items.append({
                "name": relative_name,
                "title": config.get("title") or filename.replace(".json", ""),
                "builtin": False,
                "field_count": len(config.get("fields") or []),
            })
    items.sort(key=lambda item: (
        0 if item["name"].startswith(f"{CUSTOM_WORKFLOW_FOLDER}/") else 1,
        item["title"],
    ))
    return {"workflows": items}


@router.get("/{name:path}")
def get_workflow(name: str):
    path = workflow_path_from_name(name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Workflow not found")
    with open(path, "r", encoding="utf-8") as workflow_file:
        workflow = json.load(workflow_file)
    config = {"title": name.replace(".json", ""), "fields": []}
    config_path = workflow_config_path(name)
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as config_file:
                config = json.load(config_file) or config
        except Exception:
            pass
    return {"name": name, "workflow": workflow, "config": config, "builtin": is_builtin_workflow(name)}


@router.post("")
def upload_workflow(payload: WorkflowUploadRequest):
    name = os.path.basename(payload.name.strip())
    if not name.endswith(".json"):
        name += ".json"
    if not WORKFLOW_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="\u5de5\u4f5c\u6d41\u540d\u79f0\u4e0d\u5408\u6cd5\uff0c\u8bf7\u4f7f\u7528\u4e2d\u6587/\u82f1\u6587/\u6570\u5b57/_-.",
        )
    if not isinstance(payload.workflow, dict) or not payload.workflow:
        raise HTTPException(status_code=400, detail="\u5de5\u4f5c\u6d41 JSON \u4e3a\u7a7a")
    sample = next(iter(payload.workflow.values()), None)
    if not isinstance(sample, dict) or "class_type" not in sample:
        raise HTTPException(
            status_code=400,
            detail="\u4e0d\u662f\u6709\u6548\u7684 ComfyUI API \u5de5\u4f5c\u6d41 JSON\uff08\u9700\u5305\u542b class_type\uff09",
        )
    custom_dir = os.path.join(_workflow_dir, CUSTOM_WORKFLOW_FOLDER)
    os.makedirs(custom_dir, exist_ok=True)
    stored_name = f"{CUSTOM_WORKFLOW_FOLDER}/{name}"
    with open(workflow_path_from_name(stored_name), "w", encoding="utf-8") as workflow_file:
        json.dump(payload.workflow, workflow_file, ensure_ascii=False, indent=2)
    return {"name": stored_name}


@router.put("/{name:path}/config")
def save_workflow_config(name: str, payload: WorkflowConfig):
    path = workflow_path_from_name(name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Workflow not found")
    config = payload.dict()
    with open(workflow_config_path(name), "w", encoding="utf-8") as config_file:
        json.dump(config, config_file, ensure_ascii=False, indent=2)
    return {"config": config}


@router.delete("/{name:path}")
def delete_workflow(name: str):
    if is_builtin_workflow(name):
        raise HTTPException(status_code=400, detail="\u5185\u7f6e\u5de5\u4f5c\u6d41\u4e0d\u53ef\u5220\u9664")
    path = workflow_path_from_name(name)
    config_path = workflow_config_path(name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Workflow not found")
    os.remove(path)
    if os.path.exists(config_path):
        os.remove(config_path)
    return {"ok": True}


@router.post("/{name:path}/run")
def run_workflow(name: str, payload: WorkflowRunRequest):
    if not os.path.exists(workflow_path_from_name(name)):
        raise HTTPException(status_code=404, detail="Workflow not found")
    params: Dict[str, Dict[str, Any]] = {}
    for field in payload.config.fields:
        if not field.node or not field.input:
            continue
        if field.id not in payload.fields:
            continue
        value = payload.fields[field.id]
        if field.type in ("number", "slider"):
            try:
                value = float(value) if field.step and field.step < 1 else int(float(value))
            except Exception:
                pass
        elif field.type == "boolean":
            value = bool(value)
        elif field.type == "dropdown" and isinstance(value, str):
            text = value.strip()
            try:
                if text and ("." in text or "e" in text.lower()):
                    value = float(text)
                elif text and text.lstrip("-").isdigit():
                    value = int(text)
            except (ValueError, TypeError):
                pass
        params.setdefault(field.node, {})[field.input] = value
    request = _generate_request_factory(
        prompt="",
        workflow_json=name,
        params=params,
        type="workflow-test",
        client_id=payload.client_id or str(uuid.uuid4()),
    )
    return _generate(request)
