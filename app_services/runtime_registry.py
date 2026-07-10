"""Extracted runtime registry services."""

from __future__ import annotations

import asyncio
import base64
import datetime
import functools
import glob
import hashlib
import hmac
import html
import json
import math
import mimetypes
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import httpx
import requests
from fastapi import HTTPException
from PIL import Image, ImageOps


RUNTIME_REGISTRY_EXPORTS = (
    'model_list',
    'provider_env_key_value',
    'runninghub_wallet_key_value',
    'volcengine_access_key_value',
    'volcengine_secret_key_value',
    'volcengine_provider_api_key',
    'default_api_providers',
    'merge_default_api_providers',
    'normalize_model_list',
    'model_list_from_values',
    'normalize_runninghub_entry',
    'normalize_runninghub_entries',
    'runninghub_entry_id',
    'static_runninghub_thumbnail_url',
    'apply_runninghub_system_thumbnails',
    'merge_runninghub_entry_overlay',
    'merge_runninghub_system_entries',
    'load_static_runninghub_provider',
    'merge_runninghub_provider_with_static',
    'preserve_runninghub_hidden_overrides',
    'get_primary_provider_id',
    'get_api_provider',
    'get_api_provider_exact',
    'modelscope_provider_config',
    'modelscope_api_key',
    'modelscope_api_root',
    'modelscope_image_api_root',
)


def configure_runtime_registry(namespace: dict[str, Any]) -> None:
    required = {
        'CODEX_DEFAULT_CHAT_MODELS',
        'CODEX_DEFAULT_IMAGE_MODELS',
        'GEMINI_CLI_DEFAULT_CHAT_MODELS',
        'GEMINI_CLI_DEFAULT_IMAGE_MODELS',
        'JIMENG_DEFAULT_IMAGE_MODELS',
        'JIMENG_DEFAULT_VIDEO_MODELS',
        'JIMENG_LEGACY_IMAGE_MODELS',
        'JIMENG_LEGACY_VIDEO_MODELS',
        'MODELSCOPE_API_KEY',
        'MODELSCOPE_CHAT_BASE_URL',
        'MODELSCOPE_CHAT_MODELS',
        'MODELSCOPE_DEFAULTS_VERSION',
        'MODELSCOPE_DEFAULT_CHAT_MODELS',
        'MODELSCOPE_DEFAULT_IMAGE_MODELS',
        'MODELSCOPE_DEFAULT_LORAS',
        'RUNNINGHUB_DEFAULT_APPS',
        'RUNNINGHUB_DEFAULT_BASE_URL',
        'RUNNINGHUB_DEFAULT_WORKFLOWS',
        'RUNNINGHUB_THUMBNAIL_EXTS',
        'STATIC_DIR',
        'STATIC_RUNNINGHUB_API_PROVIDERS_FILE',
        'STATIC_RUNNINGHUB_DIR',
        'STATIC_RUNNINGHUB_THUMBNAIL_DIR',
        'VOLCENGINE_DEFAULT_BASE_URL',
        'VOLCENGINE_DEFAULT_PROJECT_NAME',
        'VOLCENGINE_DEFAULT_REGION',
        'is_jimeng_provider',
        'load_api_providers',
        'normalize_ms_loras',
        'normalize_provider',
        'provider_key_env',
        'read_api_env_value',
        'runninghub_normalize_field',
        'runninghub_wallet_key_env',
        'selected_model',
        'strip_auth_scheme',
        'volcengine_access_key_env',
        'volcengine_secret_key_env',
    }
    missing = sorted(required - namespace.keys())
    if missing:
        raise RuntimeError(f"Runtime Registry missing dependencies: {', '.join(missing)}")
    globals().update({name: namespace[name] for name in required})


def export_runtime_registry(target: dict[str, Any]) -> None:
    for name in RUNTIME_REGISTRY_EXPORTS:
        target[name] = globals()[name]


def model_list(env_name, primary, defaults):
    configured = os.getenv(env_name, "")
    configured_values = [item.strip() for item in configured.split(",") if item.strip()]
    values = configured_values or [primary, *defaults]
    deduped = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped

def provider_env_key_value(provider_id: str) -> str:
    provider_id = str(provider_id or "").strip().lower()
    env_key = provider_key_env(provider_id)
    key = os.getenv(env_key, "") or read_api_env_value(env_key)
    if key:
        return key
    if provider_id == "modelscope":
        return MODELSCOPE_API_KEY or ""
    return ""

def runninghub_wallet_key_value() -> str:
    env_key = runninghub_wallet_key_env()
    return os.getenv(env_key, "") or read_api_env_value(env_key)

def volcengine_access_key_value() -> str:
    env_key = volcengine_access_key_env()
    return os.getenv(env_key, "") or read_api_env_value(env_key)

def volcengine_secret_key_value() -> str:
    env_key = volcengine_secret_key_env()
    return os.getenv(env_key, "") or read_api_env_value(env_key)

def volcengine_provider_api_key(explicit_key: str = "") -> str:
    explicit_key = str(explicit_key or "").strip()
    if explicit_key:
        return explicit_key
    return provider_env_key_value("volcengine")

def default_api_providers():
    # 独立入口平台强制保留，其他平台均可自定义增删
    return [
        {
            "id": "modelscope",
            "name": "ModelScope",
            "base_url": MODELSCOPE_CHAT_BASE_URL,
            "protocol": "openai",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": MODELSCOPE_DEFAULT_IMAGE_MODELS,
            "chat_models": MODELSCOPE_CHAT_MODELS,
            "video_models": [],
            "ms_loras": MODELSCOPE_DEFAULT_LORAS,
            "ms_defaults_version": MODELSCOPE_DEFAULTS_VERSION,
        },
        {
            "id": "runninghub",
            "name": "RunningHub",
            "base_url": RUNNINGHUB_DEFAULT_BASE_URL,
            "protocol": "runninghub",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": [],
            "chat_models": [],
            "video_models": [],
            "ms_loras": [],
            "ms_defaults_version": 0,
            "rh_apps": RUNNINGHUB_DEFAULT_APPS,
            "rh_workflows": RUNNINGHUB_DEFAULT_WORKFLOWS,
        },
        {
            "id": "volcengine",
            "name": "火山引擎",
            "base_url": VOLCENGINE_DEFAULT_BASE_URL,
            "protocol": "volcengine",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": [],
            "chat_models": [],
            "video_models": [],
            "ms_loras": [],
            "ms_defaults_version": 0,
            "volcengine_project_name": VOLCENGINE_DEFAULT_PROJECT_NAME,
            "volcengine_region": VOLCENGINE_DEFAULT_REGION,
        },
    ]

def merge_default_api_providers(providers, inject_missing=True):
    merged = [dict(item) for item in providers]
    # 强制保留独立入口平台（不再强制 comfly）
    ms_default = next((d for d in default_api_providers() if d["id"] == "modelscope"), None)
    if ms_default:
        current = next((item for item in merged if item.get("id") == "modelscope"), None)
        if not current:
            if inject_missing:
                merged.append(ms_default)
        else:
            if not current.get("base_url"):
                current["base_url"] = ms_default["base_url"]
            seeded_version = int(current.get("ms_defaults_version") or 0)
            if seeded_version < MODELSCOPE_DEFAULTS_VERSION:
                image_models = model_list_from_values([*MODELSCOPE_DEFAULT_IMAGE_MODELS, *(current.get("image_models") or [])])
                chat_models = model_list_from_values([*MODELSCOPE_DEFAULT_CHAT_MODELS, *(current.get("chat_models") or [])])
                loras = normalize_ms_loras([*MODELSCOPE_DEFAULT_LORAS, *(current.get("ms_loras") or [])])
                current["image_models"] = image_models
                current["chat_models"] = chat_models
                current["ms_loras"] = loras
                current["ms_defaults_version"] = MODELSCOPE_DEFAULTS_VERSION
    rh_default = load_static_runninghub_provider() or next((d for d in default_api_providers() if d["id"] == "runninghub"), None)
    if rh_default:
        current = next((item for item in merged if item.get("id") == "runninghub"), None)
        if not current:
            if inject_missing:
                merged.append(rh_default)
        else:
            if not current.get("base_url"):
                current["base_url"] = rh_default["base_url"]
            if not current.get("protocol") or current.get("protocol") == "openai":
                current["protocol"] = "runninghub"
            current["image_models"] = model_list_from_values(current.get("image_models") or [])
            current["chat_models"] = model_list_from_values(current.get("chat_models") or [])
            current["video_models"] = model_list_from_values(current.get("video_models") or [])
            current["rh_apps"] = merge_runninghub_system_entries(rh_default.get("rh_apps") or [], current.get("rh_apps") or [], "app")
            current["rh_workflows"] = merge_runninghub_system_entries(rh_default.get("rh_workflows") or [], current.get("rh_workflows") or [], "workflow")
    volc_default = next((d for d in default_api_providers() if d["id"] == "volcengine"), None)
    if volc_default:
        current = next((item for item in merged if item.get("id") == "volcengine"), None)
        legacy = next((item for item in merged if item.get("id") != "volcengine" and str(item.get("protocol") or "").lower() == "volcengine"), None)
        if not current:
            if legacy:
                legacy_image_models = model_list_from_values(legacy.get("image_models") or [])
                legacy_video_models = model_list_from_values(legacy.get("video_models") or [])
                current = {
                    **volc_default,
                    "base_url": legacy.get("base_url") or volc_default["base_url"],
                    "image_models": legacy_image_models or model_list_from_values(volc_default.get("image_models") or []),
                    "chat_models": model_list_from_values(legacy.get("chat_models") or []),
                    "video_models": legacy_video_models,
                }
                merged.append(current)
            elif inject_missing:
                merged.append(volc_default)
        else:
            if not current.get("base_url"):
                current["base_url"] = volc_default["base_url"]
            current["protocol"] = "volcengine"
            current["volcengine_project_name"] = str(current.get("volcengine_project_name") or VOLCENGINE_DEFAULT_PROJECT_NAME).strip() or VOLCENGINE_DEFAULT_PROJECT_NAME
            current["volcengine_region"] = str(current.get("volcengine_region") or VOLCENGINE_DEFAULT_REGION).strip() or VOLCENGINE_DEFAULT_REGION
    # 即梦 CLI 不再是强制保留的默认平台：仅在用户已添加了即梦协议的平台时，规范化其默认模型/地址。
    for current in merged:
        if not is_jimeng_provider(current):
            continue
        current["protocol"] = "jimeng"
        current["base_url"] = ""
        current["image_models"] = model_list_from_values([
            *[item for item in (current.get("image_models") or []) if str(item or "").strip() not in JIMENG_LEGACY_IMAGE_MODELS],
            *JIMENG_DEFAULT_IMAGE_MODELS,
        ])
        current["video_models"] = model_list_from_values([
            *[item for item in (current.get("video_models") or []) if str(item or "").strip() not in JIMENG_LEGACY_VIDEO_MODELS],
            *JIMENG_DEFAULT_VIDEO_MODELS,
        ])
    # OpenAI/Antigravity CLI 和即梦一样作为协议使用：用户选中 CLI 协议时再规范化模型与地址，不强制额外注入平台。
    for current in merged:
        current_protocol = str((current or {}).get("protocol") or "").strip().lower()
        if current_protocol not in {"codex", "gemini-cli"}:
            continue
        current["protocol"] = current_protocol
        current["base_url"] = ""
        default_image_models = CODEX_DEFAULT_IMAGE_MODELS if current_protocol == "codex" else GEMINI_CLI_DEFAULT_IMAGE_MODELS
        default_chat_models = CODEX_DEFAULT_CHAT_MODELS if current_protocol == "codex" else GEMINI_CLI_DEFAULT_CHAT_MODELS
        image_models = current.get("image_models") or []
        if current_protocol == "codex":
            image_models = [item for item in image_models if str(item or "").strip().lower() != "$imagegen"]
        current["image_models"] = model_list_from_values([*image_models, *default_image_models])
        current["chat_models"] = model_list_from_values([*(current.get("chat_models") or []), *default_chat_models])
        current["video_models"] = []
    return merged

def normalize_model_list(values):
    return model_list_from_values(values)

def model_list_from_values(values):
    deduped = []
    for value in values or []:
        item = str(value or "").strip()
        if item and item not in deduped:
            selected_model(item, item)
            deduped.append(item)
    return deduped

def normalize_runninghub_entry(raw, kind):
    if not isinstance(raw, dict):
        return None
    raw_id = raw.get("appId") if kind == "app" else raw.get("workflowId")
    entry_id = str(raw_id or raw.get("id") or "").strip()
    match = re.search(r"/run/(ai-app|workflow)/([0-9A-Za-z_-]+)", entry_id)
    if match:
        entry_id = match.group(2)
    if not entry_id:
        return None
    title = re.sub(r"\s+", " ", str(raw.get("title") or raw.get("name") or "").strip())[:80]
    note = str(raw.get("note") or raw.get("description") or "").strip()[:500]
    thumb = str(raw.get("thumbnail") or "").strip()
    if len(thumb) > 1500000:
        thumb = ""
    entry = {
        "id": entry_id[:80],
        "title": title or (f"AI 应用 {entry_id[-6:]}" if kind == "app" else f"工作流 {entry_id[-6:]}"),
        "note": note,
        "thumbnail": thumb,
        "enabled": bool(raw.get("enabled", True)),
    }
    if raw.get("hidden") is True:
        entry["hidden"] = True
    fields = raw.get("fields")
    if isinstance(fields, list):
        entry["fields"] = [runninghub_normalize_field(field) for field in fields if isinstance(field, dict)]
    if kind == "workflow":
        mode = str(raw.get("optionalImageMode") or raw.get("optional_image_mode") or "prune-workflow").strip()
        entry["optionalImageMode"] = mode or "prune-workflow"
        workflow_json = raw.get("workflowJson") or raw.get("workflow_json")
        if isinstance(workflow_json, dict):
            entry["workflowJson"] = workflow_json
    raw_payload = raw.get("raw")
    if isinstance(raw_payload, dict):
        entry["raw"] = raw_payload
    try:
        updated_at = int(raw.get("updatedAt") or raw.get("updated_at") or 0)
        if updated_at > 0:
            entry["updatedAt"] = updated_at
    except Exception:
        pass
    if kind == "app":
        entry["appId"] = entry["id"]
    else:
        entry["workflowId"] = entry["id"]
    return entry

def normalize_runninghub_entries(values, kind):
    normalized = []
    seen = set()
    for raw in values or []:
        entry = normalize_runninghub_entry(raw, kind)
        if not entry or entry["id"] in seen:
            continue
        seen.add(entry["id"])
        normalized.append(entry)
    return normalized

def runninghub_entry_id(entry, kind):
    if not isinstance(entry, dict):
        return ""
    raw_id = entry.get("workflowId") if kind == "workflow" else entry.get("appId")
    return str(raw_id or entry.get("id") or "").strip()

def static_runninghub_thumbnail_url(entry_id, kind):
    entry_id = re.sub(r"[^0-9A-Za-z_-]", "", str(entry_id or "").strip())
    kind_prefix = "workflow" if kind == "workflow" else "app"
    if not entry_id:
        return ""
    candidates = []
    for name in (f"{kind_prefix}-{entry_id}", entry_id):
        for ext in RUNNINGHUB_THUMBNAIL_EXTS:
            candidates.append((STATIC_RUNNINGHUB_THUMBNAIL_DIR, f"{name}{ext}"))
            candidates.append((STATIC_RUNNINGHUB_DIR, f"{name}{ext}"))
    for root, filename in candidates:
        path = os.path.abspath(os.path.join(root, filename))
        if not path.startswith(os.path.abspath(STATIC_RUNNINGHUB_DIR) + os.sep):
            continue
        if os.path.exists(path) and os.path.isfile(path):
            rel = os.path.relpath(path, STATIC_DIR).replace(os.sep, "/")
            return f"/static/{urllib.parse.quote(rel, safe='/._-')}?v={int(os.path.getmtime(path))}"
    return ""

def apply_runninghub_system_thumbnails(entries, kind):
    result = []
    for entry in normalize_runninghub_entries(entries or [], kind):
        if not entry.get("thumbnail"):
            thumb = static_runninghub_thumbnail_url(runninghub_entry_id(entry, kind), kind)
            if thumb:
                entry["thumbnail"] = thumb
        result.append(entry)
    return result

def merge_runninghub_entry_overlay(system_entry, user_entry):
    # 系统模板只提供默认值；同 ID 的用户配置优先，允许用户修改/隐藏内置模板。
    if not isinstance(system_entry, dict):
        return user_entry
    if not isinstance(user_entry, dict):
        return system_entry
    merged = {**system_entry, **user_entry}
    if not merged.get("thumbnail") and system_entry.get("thumbnail"):
        merged["thumbnail"] = system_entry.get("thumbnail")
    return merged

def merge_runninghub_system_entries(system_entries, user_entries, kind):
    merged = []
    index = {}
    hidden_ids = set()
    for entry in apply_runninghub_system_thumbnails(system_entries or [], kind):
        entry_id = runninghub_entry_id(entry, kind)
        if not entry_id:
            continue
        index[entry_id] = len(merged)
        merged.append(entry)
    for entry in apply_runninghub_system_thumbnails(user_entries or [], kind):
        entry_id = runninghub_entry_id(entry, kind)
        if not entry_id:
            continue
        if entry.get("hidden") is True:
            hidden_ids.add(entry_id)
            if entry_id in index:
                merged.pop(index[entry_id])
                index = {runninghub_entry_id(item, kind): idx for idx, item in enumerate(merged)}
            continue
        if entry_id in index:
            merged[index[entry_id]] = merge_runninghub_entry_overlay(merged[index[entry_id]], entry)
        else:
            index[entry_id] = len(merged)
            merged.append(entry)
    return [entry for entry in merged if runninghub_entry_id(entry, kind) not in hidden_ids]

def load_static_runninghub_provider():
    if not os.path.exists(STATIC_RUNNINGHUB_API_PROVIDERS_FILE):
        return None
    try:
        with open(STATIC_RUNNINGHUB_API_PROVIDERS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        candidates = raw if isinstance(raw, list) else raw.get("providers") if isinstance(raw, dict) else []
        if isinstance(raw, dict) and raw.get("id") == "runninghub":
            candidates = [raw]
        for item in candidates or []:
            if isinstance(item, dict) and str(item.get("id") or "").strip().lower() == "runninghub":
                provider = normalize_provider(item)
                provider["rh_apps"] = apply_runninghub_system_thumbnails(provider.get("rh_apps") or [], "app")
                provider["rh_workflows"] = apply_runninghub_system_thumbnails(provider.get("rh_workflows") or [], "workflow")
                return provider
    except Exception as e:
        print(f"加载 static RunningHub 配置失败: {e}")
    return None

def merge_runninghub_provider_with_static(provider):
    static_provider = load_static_runninghub_provider()
    if not static_provider:
        return provider
    if not isinstance(provider, dict):
        return static_provider
    merged = {**static_provider, **provider}
    merged["protocol"] = "runninghub"
    merged["image_models"] = model_list_from_values(provider.get("image_models") or [])
    merged["chat_models"] = model_list_from_values(provider.get("chat_models") or [])
    merged["video_models"] = model_list_from_values(provider.get("video_models") or [])
    merged["rh_apps"] = merge_runninghub_system_entries(static_provider.get("rh_apps") or [], provider.get("rh_apps") or [], "app")
    merged["rh_workflows"] = merge_runninghub_system_entries(static_provider.get("rh_workflows") or [], provider.get("rh_workflows") or [], "workflow")
    return normalize_provider(merged)

def preserve_runninghub_hidden_overrides(provider):
    if not isinstance(provider, dict) or provider.get("id") != "runninghub":
        return provider
    static_provider = load_static_runninghub_provider()
    if not static_provider:
        return provider
    provider = dict(provider)
    for list_key, kind in (("rh_apps", "app"), ("rh_workflows", "workflow")):
        current = normalize_runninghub_entries(provider.get(list_key) or [], kind)
        current_ids = {runninghub_entry_id(item, kind) for item in current}
        for static_entry in static_provider.get(list_key) or []:
            entry_id = runninghub_entry_id(static_entry, kind)
            if entry_id and entry_id not in current_ids:
                tombstone = normalize_runninghub_entry({**static_entry, "enabled": False, "hidden": True}, kind)
                if tombstone:
                    current.append(tombstone)
        provider[list_key] = current
    return provider

def get_primary_provider_id(providers=None):
    """返回当前首选 provider 的 id；优先 primary=True 的，否则取第一个非 modelscope 的，再次取第一个。"""
    providers = providers if providers is not None else load_api_providers()
    primary = next((p for p in providers if p.get("primary") and p.get("enabled", True)), None)
    if primary:
        return primary["id"]
    non_ms = next((p for p in providers if p["id"] != "modelscope" and p.get("enabled", True)), None)
    if non_ms:
        return non_ms["id"]
    return providers[0]["id"] if providers else "modelscope"

def get_api_provider(provider_id="comfly"):
    providers = load_api_providers()
    target = (provider_id or "").strip().lower()
    # 兼容旧的 "comfly" 硬编码：若 comfly 不存在或未指定，回退到首选 provider
    if not target or not any(p["id"] == target for p in providers):
        target = get_primary_provider_id(providers)
    provider = next((p for p in providers if p["id"] == target), None)
    if not provider:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台：{target}")
    if not provider.get("enabled", True):
        raise HTTPException(status_code=400, detail=f"API 平台已禁用：{provider.get('name') or target}")
    return provider

def get_api_provider_exact(provider_id: str):
    providers = load_api_providers()
    target = (provider_id or "").strip().lower()
    provider = next((p for p in providers if p["id"] == target), None)
    if not provider:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台：{target or '(empty)'}。新增平台未保存时请使用当前表单拉取模型。")
    if not provider.get("enabled", True):
        raise HTTPException(status_code=400, detail=f"API 平台已禁用：{provider.get('name') or target}")
    return provider

def modelscope_provider_config():
    return get_api_provider_exact("modelscope")

def modelscope_api_key(explicit_key: str = ""):
    return (
        strip_auth_scheme(explicit_key, "Bearer")
        or strip_auth_scheme(provider_env_key_value("modelscope"), "Bearer")
        or strip_auth_scheme(MODELSCOPE_API_KEY, "Bearer")
    )

def modelscope_api_root(provider=None):
    provider = provider or modelscope_provider_config()
    base_root = str((provider or {}).get("base_url") or MODELSCOPE_CHAT_BASE_URL).strip().rstrip("/")
    if not base_root:
        base_root = MODELSCOPE_CHAT_BASE_URL
    return base_root if base_root.endswith("/v1") else f"{base_root}/v1"

def modelscope_image_api_root():
    return MODELSCOPE_CHAT_BASE_URL.rstrip("/")
