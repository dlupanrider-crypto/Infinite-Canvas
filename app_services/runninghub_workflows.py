"""RunningHub workflow merge, synchronization, and field rules."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Optional

from repositories.runninghub_workflows import load_runninghub_workflow_store


_providers_path = ""
_default_base_url = "https://www.runninghub.cn"
_default_apps: list[dict[str, Any]] = []
_load_static_provider: Optional[Callable[[], Optional[dict[str, Any]]]] = None
_normalize_entry: Optional[Callable[[dict[str, Any], str], Optional[dict[str, Any]]]] = None
_normalize_entries: Optional[Callable[[Any, str], list[dict[str, Any]]]] = None
_is_link_value: Optional[Callable[[Any], bool]] = None
_infer_field_type: Optional[Callable[[str, Any], str]] = None
_load_providers: Optional[Callable[[], list[dict[str, Any]]]] = None
_save_providers: Optional[Callable[[list[dict[str, Any]]], None]] = None
_normalize_provider: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None
_now_ms: Optional[Callable[[], int]] = None


def configure_runninghub_workflow_service(
    *,
    providers_path: str,
    default_base_url: str,
    default_apps: list[dict[str, Any]],
    load_static_provider_fn: Callable[[], Optional[dict[str, Any]]],
    normalize_entry_fn: Callable[[dict[str, Any], str], Optional[dict[str, Any]]],
    normalize_entries_fn: Callable[[Any, str], list[dict[str, Any]]],
    is_link_value_fn: Callable[[Any], bool],
    infer_field_type_fn: Callable[[str, Any], str],
    load_providers_fn: Callable[[], list[dict[str, Any]]],
    save_providers_fn: Callable[[list[dict[str, Any]]], None],
    normalize_provider_fn: Callable[[dict[str, Any]], dict[str, Any]],
    now_ms_fn: Callable[[], int],
) -> None:
    global _providers_path, _default_base_url, _default_apps
    global _load_static_provider, _normalize_entry, _normalize_entries
    global _is_link_value, _infer_field_type, _load_providers, _save_providers
    global _normalize_provider, _now_ms
    _providers_path = providers_path
    _default_base_url = default_base_url
    _default_apps = default_apps
    _load_static_provider = load_static_provider_fn
    _normalize_entry = normalize_entry_fn
    _normalize_entries = normalize_entries_fn
    _is_link_value = is_link_value_fn
    _infer_field_type = infer_field_type_fn
    _load_providers = load_providers_fn
    _save_providers = save_providers_fn
    _normalize_provider = normalize_provider_fn
    _now_ms = now_ms_fn


def _require_configured() -> None:
    callbacks = (
        _load_static_provider,
        _normalize_entry,
        _normalize_entries,
        _is_link_value,
        _infer_field_type,
        _load_providers,
        _save_providers,
        _normalize_provider,
        _now_ms,
    )
    if not _providers_path or not all(callbacks):
        raise RuntimeError("RunningHub workflow service is not configured")


def runninghub_workflow_store_key(workflow_id: str) -> str:
    return str(workflow_id or "").strip()


def runninghub_workflow_config_has_payload(cfg: Any) -> bool:
    return isinstance(cfg, dict) and bool(cfg.get("fields") or cfg.get("workflowJson") or cfg.get("raw"))


def runninghub_normalize_field(raw: Any, fallback: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    fallback = fallback or {}
    if hasattr(raw, "dict"):
        raw = raw.dict()
    if not isinstance(raw, dict):
        raw = {}
    options = raw.get("options", fallback.get("options", []))
    if isinstance(options, str):
        options = [item.strip() for item in re.split(r"[\r\n,]+", options) if item.strip()]
    elif isinstance(options, list):
        options = [str(item).strip() for item in options if str(item).strip()]
    else:
        options = []
    field_id = str(
        raw.get("id")
        or raw.get("fieldId")
        or raw.get("key")
        or raw.get("nodeId")
        or fallback.get("id")
        or ""
    ).strip()
    node_id = str(raw.get("nodeId") or fallback.get("nodeId") or raw.get("node_id") or "").strip()
    field_name = str(
        raw.get("fieldName")
        or raw.get("inputName")
        or raw.get("name")
        or fallback.get("fieldName")
        or ""
    ).strip()
    field_value = raw.get("fieldValue")
    if field_value is None:
        field_value = raw.get("defaultValue")
    if field_value is None:
        field_value = raw.get("value")
    if field_value is None:
        field_value = fallback.get("fieldValue", "")
    if isinstance(field_value, (dict, list)):
        field_value = json.dumps(field_value, ensure_ascii=False)
    elif field_value is None:
        field_value = ""
    else:
        field_value = str(field_value)
    return {
        "id": field_id or f"{node_id}::{field_name}",
        "nodeId": node_id,
        "fieldName": field_name,
        "fieldValue": field_value,
        "fieldType": str(raw.get("fieldType") or fallback.get("fieldType") or "TEXT"),
        "label": str(raw.get("label") or raw.get("title") or field_name or fallback.get("label") or ""),
        "enabled": bool(raw.get("enabled", fallback.get("enabled", True))),
        "sourceFromUpstream": bool(raw.get("sourceFromUpstream", fallback.get("sourceFromUpstream", True))),
        "group": str(raw.get("group") or fallback.get("group") or ""),
        "note": str(raw.get("note") or fallback.get("note") or ""),
        "options": options,
        "random_enabled": bool(raw.get("random_enabled", fallback.get("random_enabled", False))),
        "min": raw.get("min", fallback.get("min", "")),
        "max": raw.get("max", fallback.get("max", "")),
        "step": raw.get("step", fallback.get("step", "")),
        "imageOrder": int(raw.get("imageOrder") or raw.get("image_order") or fallback.get("imageOrder") or 0),
        "required": bool(raw.get("required", fallback.get("required", False))),
    }


def runninghub_is_saved_link_field(field: Any) -> bool:
    _require_configured()
    if not isinstance(field, dict) or not isinstance(field.get("fieldValue"), str):
        return False
    text = field["fieldValue"].strip()
    if not (text.startswith("[") and text.endswith("]")):
        return False
    try:
        parsed = json.loads(text)
    except Exception:
        return False
    return _is_link_value(parsed)


def runninghub_collect_workflow_fields(workflow_json: Any) -> list[dict[str, Any]]:
    _require_configured()
    fields: list[dict[str, Any]] = []
    if not isinstance(workflow_json, dict):
        return fields
    for node_id, node_content in workflow_json.items():
        if not isinstance(node_content, dict) or not isinstance(node_content.get("inputs"), dict):
            continue
        for field_name, raw_value in node_content["inputs"].items():
            if _is_link_value(raw_value):
                continue
            if isinstance(raw_value, (dict, list)):
                field_value = json.dumps(raw_value, ensure_ascii=False)
            elif raw_value is None:
                field_value = ""
            else:
                field_value = str(raw_value)
            field_type = _infer_field_type(field_name, field_value)
            fields.append({
                "id": f"{node_id}::{field_name}",
                "nodeId": str(node_id),
                "fieldName": str(field_name),
                "fieldValue": field_value,
                "fieldType": field_type,
                "label": str(field_name),
                "enabled": False,
                "sourceFromUpstream": True,
                "group": str(
                    (node_content.get("_meta") or {}).get("title")
                    or node_content.get("class_type")
                    or node_content.get("_class")
                    or node_content.get("type")
                    or ""
                ),
                "note": "",
                "imageOrder": 0,
                "required": field_type == "IMAGE",
            })
    return fields


def runninghub_static_workflow_entry(workflow_id: str) -> Optional[dict[str, Any]]:
    _require_configured()
    key = runninghub_workflow_store_key(workflow_id)
    if not key:
        return None
    static_provider = _load_static_provider()
    for entry in (static_provider or {}).get("rh_workflows", []) or []:
        if runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id")) == key:
            return entry
    return None


def _workflow_config_from_entry(entry: dict[str, Any], source: str) -> Optional[dict[str, Any]]:
    key = runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id"))
    cfg = {
        "workflowId": key,
        "title": entry.get("title") or key,
        "description": entry.get("note") or entry.get("description") or "",
        "fields": [
            field
            for field in (runninghub_normalize_field(item) for item in (entry.get("fields") or []))
            if not runninghub_is_saved_link_field(field)
        ],
        "workflowJson": entry.get("workflowJson") if isinstance(entry.get("workflowJson"), dict) else {},
        "optionalImageMode": entry.get("optionalImageMode") or "prune-workflow",
        "raw": entry.get("raw") if isinstance(entry.get("raw"), dict) else {},
        "updatedAt": entry.get("updatedAt") or 0,
        "source": source,
    }
    return cfg if runninghub_workflow_config_has_payload(cfg) else None


def runninghub_static_workflow_config(workflow_id: str) -> Optional[dict[str, Any]]:
    entry = runninghub_static_workflow_entry(workflow_id)
    return _workflow_config_from_entry(entry, "static_template") if isinstance(entry, dict) else None


def runninghub_workflow_entry_from_config(
    cfg: Optional[dict[str, Any]],
    fallback: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    _require_configured()
    cfg = cfg or {}
    fallback = fallback if isinstance(fallback, dict) else {}
    key = runninghub_workflow_store_key(cfg.get("workflowId") or fallback.get("workflowId") or fallback.get("id"))
    if not key:
        return None
    return _normalize_entry({
        "id": key,
        "workflowId": key,
        "title": cfg.get("title") or fallback.get("title") or fallback.get("name") or f"\u5de5\u4f5c\u6d41 {key[-6:]}",
        "note": cfg.get("description") or fallback.get("note") or fallback.get("description") or "",
        "thumbnail": fallback.get("thumbnail") or "",
        "enabled": fallback.get("enabled", True),
        "fields": cfg.get("fields") or fallback.get("fields") or [],
        "workflowJson": cfg.get("workflowJson") if isinstance(cfg.get("workflowJson"), dict) else fallback.get("workflowJson") or {},
        "optionalImageMode": cfg.get("optionalImageMode") or fallback.get("optionalImageMode") or "prune-workflow",
        "raw": cfg.get("raw") if isinstance(cfg.get("raw"), dict) else fallback.get("raw") or {},
        "updatedAt": cfg.get("updatedAt") or fallback.get("updatedAt") or 0,
    }, "workflow")


def runninghub_saved_hidden_workflow_ids() -> set[str]:
    _require_configured()
    if not os.path.exists(_providers_path):
        return set()
    try:
        with open(_providers_path, "r", encoding="utf-8") as providers_file:
            raw = json.load(providers_file)
    except Exception:
        return set()
    hidden: set[str] = set()
    for provider in raw if isinstance(raw, list) else []:
        if not isinstance(provider, dict) or str(provider.get("id") or "").strip().lower() != "runninghub":
            continue
        for entry in provider.get("rh_workflows") or []:
            if not isinstance(entry, dict) or entry.get("hidden") is not True:
                continue
            key = runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id"))
            if key:
                hidden.add(key)
    return hidden


def runninghub_select_workflow_config(
    local_cfg: Any,
    provider_cfg: Any,
    workflow_id: str = "",
) -> Optional[dict[str, Any]]:
    if isinstance(local_cfg, dict) and isinstance(provider_cfg, dict):
        try:
            local_updated = int(local_cfg.get("updatedAt") or 0)
        except Exception:
            local_updated = 0
        try:
            provider_updated = int(provider_cfg.get("updatedAt") or 0)
        except Exception:
            provider_updated = 0
        return provider_cfg if provider_updated > local_updated else local_cfg
    if isinstance(local_cfg, dict):
        return local_cfg
    if isinstance(provider_cfg, dict):
        return provider_cfg
    return runninghub_static_workflow_config(workflow_id)


def runninghub_provider_with_workflow_store(provider: Any) -> Any:
    _require_configured()
    if not isinstance(provider, dict) or provider.get("id") != "runninghub":
        return provider
    store = load_runninghub_workflow_store()
    if not store:
        return provider
    merged = dict(provider)
    workflows = [dict(item) for item in (merged.get("rh_workflows") or []) if isinstance(item, dict)]
    hidden_ids = {
        runninghub_workflow_store_key(item.get("workflowId") or item.get("id"))
        for item in workflows
        if item.get("hidden") is True and runninghub_workflow_store_key(item.get("workflowId") or item.get("id"))
    }
    hidden_ids.update(runninghub_saved_hidden_workflow_ids())
    by_id = {
        runninghub_workflow_store_key(item.get("workflowId") or item.get("id")): item
        for item in workflows
        if runninghub_workflow_store_key(item.get("workflowId") or item.get("id"))
    }
    for workflow_id, cfg in store.items():
        if workflow_id in hidden_ids or not runninghub_workflow_config_has_payload(cfg):
            continue
        existing = by_id.get(workflow_id)
        selected = runninghub_select_workflow_config(existing, cfg, workflow_id)
        entry = runninghub_workflow_entry_from_config(selected, existing)
        if not entry:
            continue
        if existing is None:
            workflows.append(entry)
        else:
            existing.update(entry)
    merged["rh_workflows"] = _normalize_entries(workflows, "workflow")
    return merged


def runninghub_provider_workflow_config(workflow_id: str) -> Optional[dict[str, Any]]:
    _require_configured()
    key = runninghub_workflow_store_key(workflow_id)
    if not key or key in runninghub_saved_hidden_workflow_ids():
        return None
    provider = next((item for item in _load_providers() if item.get("id") == "runninghub"), None)
    if not provider:
        return None
    for entry in provider.get("rh_workflows") or []:
        if runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id")) != key:
            continue
        if entry.get("hidden") is True:
            return None
        return _workflow_config_from_entry(entry, "api_providers")
    return None


def sync_runninghub_workflow_to_provider(cfg: Any) -> None:
    _require_configured()
    if not isinstance(cfg, dict):
        return
    key = runninghub_workflow_store_key(cfg.get("workflowId"))
    if not key:
        return
    providers = _load_providers()
    provider = next((item for item in providers if item.get("id") == "runninghub"), None)
    if not provider:
        provider = {
            "id": "runninghub",
            "name": "RunningHub",
            "base_url": _default_base_url,
            "protocol": "runninghub",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": [],
            "chat_models": [],
            "video_models": [],
            "ms_loras": [],
            "ms_defaults_version": 0,
            "rh_apps": _default_apps,
            "rh_workflows": [],
        }
        providers.append(provider)
    workflows = provider.setdefault("rh_workflows", [])
    entry = next((
        item for item in workflows
        if runninghub_workflow_store_key(item.get("workflowId") or item.get("id")) == key
    ), None)
    if entry is None:
        entry = {
            "id": key,
            "workflowId": key,
            "title": cfg.get("title") or f"\u5de5\u4f5c\u6d41 {key[-6:]}",
            "note": cfg.get("description") or "",
            "thumbnail": "",
            "enabled": True,
        }
        workflows.append(entry)
    entry.update({
        "id": key,
        "workflowId": key,
        "title": cfg.get("title") or entry.get("title") or f"\u5de5\u4f5c\u6d41 {key[-6:]}",
        "note": cfg.get("description") or "",
        "fields": [
            field
            for field in (runninghub_normalize_field(item) for item in (cfg.get("fields") or []))
            if not runninghub_is_saved_link_field(field)
        ],
        "workflowJson": cfg.get("workflowJson") if isinstance(cfg.get("workflowJson"), dict) else {},
        "optionalImageMode": cfg.get("optionalImageMode") or "prune-workflow",
        "raw": cfg.get("raw") if isinstance(cfg.get("raw"), dict) else {},
        "updatedAt": cfg.get("updatedAt") or _now_ms(),
    })
    entry.setdefault("enabled", True)
    entry.setdefault("thumbnail", "")
    _save_providers([_normalize_provider(item) for item in providers])


def remove_runninghub_workflow_from_provider(workflow_id: str) -> None:
    _require_configured()
    key = runninghub_workflow_store_key(workflow_id)
    if not key:
        return
    providers = _load_providers()
    changed = False
    for provider in providers:
        if provider.get("id") != "runninghub":
            continue
        workflows = provider.get("rh_workflows") or []
        removed = next((
            item for item in workflows
            if runninghub_workflow_store_key(item.get("workflowId") or item.get("id")) == key
        ), None)
        kept = [
            item for item in workflows
            if runninghub_workflow_store_key(item.get("workflowId") or item.get("id")) != key
        ]
        static_provider = _load_static_provider()
        static_workflow = next((
            item for item in (static_provider or {}).get("rh_workflows", [])
            if runninghub_workflow_store_key(item.get("workflowId") or item.get("id")) == key
        ), None)
        if static_workflow:
            tombstone = _normalize_entry({
                **static_workflow,
                **(removed or {}),
                "enabled": False,
                "hidden": True,
            }, "workflow")
            if tombstone:
                kept.append(tombstone)
        if static_workflow or len(kept) != len(workflows):
            provider["rh_workflows"] = kept
            changed = True
    if changed:
        _save_providers([_normalize_provider(item) for item in providers])
