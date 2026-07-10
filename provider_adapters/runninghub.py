"""RunningHub OpenAPI models, workflows, uploads, and generation."""

from __future__ import annotations

import asyncio
import functools
import json
import math
import os
import random
import re
import time
import urllib.parse
import uuid
from typing import Any

import httpx
from fastapi import HTTPException

from app_services.env_config import (
    bearer_auth_value,
    provider_key_env,
    runninghub_wallet_key_env,
)
from app_services.provider_routing import (
    runninghub_endpoint_url,
    runninghub_openapi_url,
)
from app_services.runninghub_workflows import (
    runninghub_provider_workflow_config,
    runninghub_select_workflow_config,
    runninghub_workflow_store_key,
)
from provider_adapters.probe import classify_upstream_model, parse_upstream_models
from repositories.runninghub_workflows import load_runninghub_workflow_store


RUNNINGHUB_EXPORTS = (
    "runninghub_api_headers",
    "runninghub_json_headers",
    "runninghub_provider",
    "runninghub_api_key",
    "runninghub_app_headers",
    "runninghub_local_asset_path",
    "runninghub_output_ext",
    "rewrite_runninghub_file_url",
    "runninghub_extract_outputs",
    "runninghub_store_remote_output",
    "runninghub_fail_reason",
    "runninghub_infer_workflow_field_type",
    "runninghub_is_workflow_link_value",
    "runninghub_workflow_node_info_list",
    "runninghub_task_endpoint",
    "runninghub_endpoint_alias_for_model",
    "runninghub_registry_fallback",
    "runninghub_registry_items_from_raw",
    "runninghub_registry_model_from_id",
    "fetch_runninghub_llm_models",
    "fetch_runninghub_model_registry",
    "runninghub_model_id",
    "runninghub_registry_payload",
    "runninghub_models_payload",
    "runninghub_model_definition",
    "runninghub_schema_options",
    "runninghub_schema_value",
    "runninghub_schema_field",
    "runninghub_aspect_from_size",
    "runninghub_resolution_from_size",
    "runninghub_size_for_aspect",
    "runninghub_apply_schema_defaults",
    "runninghub_query_status",
    "runninghub_extract_task_id",
    "runninghub_extract_image",
    "runninghub_upload_reference",
    "wait_for_runninghub_image_task",
    "rh_field_kind",
    "rh_field_role",
    "_rh_natural_cmp",
    "_rh_field_cmp",
    "rh_sort_fields",
    "rh_field_indexes",
    "rh_default_value",
    "rh_is_seed_like_name",
    "normalize_seed_uint32",
    "sanitize_seed_like_workflow_values",
    "sanitize_runninghub_node_info_list",
    "rh_random_field_value",
    "runninghub_entry_config_from_model",
    "runninghub_upload_local_to_filename",
    "generate_runninghub_entry_image",
    "generate_runninghub_provider_image",
    "wait_for_runninghub_openapi_task",
    "generate_runninghub_video",
)


def configure_runninghub_adapter(**dependencies: Any) -> None:
    required = {
        "ONLINE_IMAGE_REFERENCE_MAX",
        "OUTPUT_INPUT_DIR",
        "OUTPUT_OUTPUT_DIR",
        "RUNNINGHUB_DEFAULT_IMAGE_MODELS",
        "RUNNINGHUB_DEFAULT_VIDEO_MODELS",
        "RUNNINGHUB_FALLBACK_CHAT_MODELS",
        "RUNNINGHUB_FILE_HOST_REWRITES",
        "RUNNINGHUB_LLM_MODELS_URLS",
        "RUNNINGHUB_MODEL_ENDPOINT_ALIASES",
        "RUNNINGHUB_MODEL_REGISTRY_URL",
        "RUNNINGHUB_WORKFLOW_LOCK",
        "STATIC_RUNNINGHUB_MODEL_REGISTRY_FILE",
        "VIDEO_POLL_TIMEOUT",
        "content_type_for_path",
        "extract_image",
        "get_api_provider_exact",
        "looks_like_html_response",
        "output_file_from_url",
        "output_path_for",
        "output_url_for",
        "parse_size_pair",
        "save_remote_video_to_output",
        "video_output_urls",
    }
    missing = sorted(required - dependencies.keys())
    if missing:
        raise RuntimeError(f"RunningHub adapter missing dependencies: {', '.join(missing)}")
    globals().update(dependencies)


def export_runninghub_adapter(target: dict[str, Any]) -> None:
    for name in RUNNINGHUB_EXPORTS:
        target[name] = globals()[name]

def runninghub_api_headers(provider):
    api_key = str((provider or {}).get("api_key") or "").strip() or runninghub_api_key(provider)
    if not api_key:
        raise HTTPException(status_code=400, detail="未配置 RunningHub API Key，请在 API 设置中填写。")
    return {"Authorization": bearer_auth_value(api_key), "Accept": "application/json", "Content-Type": "application/json"}

def runninghub_json_headers(provider):
    return runninghub_api_headers(provider)

def runninghub_provider():
    return get_api_provider_exact("runninghub")

def runninghub_api_key(provider=None, use_wallet=False, prefer_wallet=False):
    provider = provider or runninghub_provider()
    free_key = str((provider or {}).get("api_key") or "").strip() or os.getenv(provider_key_env(provider["id"]), "")
    wallet_key = str((provider or {}).get("wallet_api_key") or "").strip() or os.getenv(runninghub_wallet_key_env(), "")
    api_key = wallet_key if (use_wallet or prefer_wallet) and wallet_key else free_key
    if not api_key:
        raise HTTPException(status_code=400, detail="未配置 RunningHub API Key，请在 RH 设置中填写。")
    return api_key

def runninghub_app_headers(json_body=True, use_wallet=False):
    headers = {"Host": "www.runninghub.cn"}
    provider = runninghub_provider()
    if provider:
        free_key = os.getenv(provider_key_env(provider["id"]), "")
        wallet_key = os.getenv(runninghub_wallet_key_env(), "")
        api_key = wallet_key if use_wallet and wallet_key else free_key
        if api_key:
            headers["Authorization"] = bearer_auth_value(api_key)
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers

def runninghub_local_asset_path(url):
    text = str(url or "").strip()
    if not text:
        return None
    if text.startswith("/assets/input/") or text.startswith("/input/"):
        clean = urllib.parse.unquote(text.split("?", 1)[0]).replace("\\", "/")
        rel = clean[len("/assets/input/"):] if clean.startswith("/assets/input/") else clean[len("/input/"):]
        root = OUTPUT_INPUT_DIR
    elif text.startswith("/assets/output/"):
        clean = urllib.parse.unquote(text.split("?", 1)[0]).replace("\\", "/")
        rel = clean[len("/assets/output/"):]
        root = OUTPUT_OUTPUT_DIR
    elif text.startswith("/output/") or text.startswith("/assets/"):
        return output_file_from_url(text)
    else:
        return None
    rel = rel.lstrip("/")
    if not rel:
        return None
    path = os.path.abspath(os.path.join(root, rel))
    root_abs = os.path.abspath(root)
    if os.path.commonpath([root_abs, path]) != root_abs or not os.path.exists(path):
        return None
    return path

def runninghub_output_ext(remote, content_type=""):
    tail = str(remote or "").split("?", 1)[0].split("#", 1)[0]
    ext = os.path.splitext(tail)[1].lower().strip(".")
    allowed = {"png","jpg","jpeg","webp","gif","bmp","mp4","webm","mov","m4v","mkv","mp3","wav","ogg","m4a","flac","aac"}
    if ext in allowed:
        return ext
    ct = str(content_type or "").lower()
    if "mp4" in ct:
        return "mp4"
    if "webm" in ct:
        return "webm"
    if "quicktime" in ct:
        return "mov"
    if "mpeg" in ct:
        return "mp3"
    if "wav" in ct:
        return "wav"
    if "ogg" in ct:
        return "ogg"
    if "webp" in ct:
        return "webp"
    if "jpeg" in ct:
        return "jpg"
    return "png"

def rewrite_runninghub_file_url(url):
    text = str(url or "")
    if not text:
        return text
    try:
        parsed = urllib.parse.urlsplit(text)
    except Exception:
        return text
    target = RUNNINGHUB_FILE_HOST_REWRITES.get((parsed.netloc or "").lower())
    return parsed._replace(netloc=target).geturl() if target else text

def runninghub_extract_outputs(data):
    arr = []
    if isinstance(data, list):
        arr = data
    elif isinstance(data, dict):
        for key in ("outputs", "results", "files", "data"):
            value = data.get(key)
            if isinstance(value, list):
                arr = value
                break
        if not arr and (data.get("fileUrl") or data.get("url")):
            arr = [data]
    outputs = []
    for item in arr:
        if isinstance(item, str):
            outputs.append(rewrite_runninghub_file_url(item))
        elif isinstance(item, dict):
            url = item.get("fileUrl") or item.get("file_url") or item.get("url") or item.get("downloadUrl") or item.get("download_url")
            if isinstance(url, list):
                outputs.extend([rewrite_runninghub_file_url(u) for u in url if u])
            elif url:
                outputs.append(rewrite_runninghub_file_url(url))
    return outputs

async def runninghub_store_remote_output(client, remote):
    remote = rewrite_runninghub_file_url(remote)
    if not str(remote or "").startswith(("http://", "https://")):
        return remote
    response = await client.get(remote, follow_redirects=True)
    if not response.is_success:
        return remote
    ext = runninghub_output_ext(remote, response.headers.get("content-type", ""))
    filename = f"rh_{uuid.uuid4().hex[:12]}.{ext}"
    path = output_path_for(filename, "output")
    with open(path, "wb") as f:
        f.write(response.content)
    return output_url_for(filename, "output")

def runninghub_fail_reason(raw):
    data = raw.get("data") if isinstance(raw, dict) else None
    values = []
    if isinstance(data, dict):
        values.extend([data.get("failedReason"), data.get("failReason"), data.get("message"), data.get("error")])
    if isinstance(raw, dict):
        values.extend([raw.get("msg"), raw.get("message"), raw.get("error")])
    for value in values:
        if not value:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get("exception_message") or value.get("message") or json.dumps(value, ensure_ascii=False)
        return str(value)
    return ""

def runninghub_infer_workflow_field_type(field_name, field_value):
    key = f"{field_name or ''} {field_value or ''}".lower()
    if re.search(r"\b(image|img|mask|photo|picture)\b", key) or re.search(r"\.(png|jpe?g|webp|gif|bmp)(\?|$)", key, re.I):
        return "IMAGE"
    if re.search(r"\b(video|movie|mp4)\b", key) or re.search(r"\.(mp4|webm|mov|m4v|mkv)(\?|$)", key, re.I):
        return "VIDEO"
    if re.search(r"\b(audio|sound|music|voice)\b", key) or re.search(r"\.(mp3|wav|ogg|m4a|flac|aac)(\?|$)", key, re.I):
        return "AUDIO"
    text = str(field_value or "").strip()
    if text.lower() in {"true", "false"}:
        return "BOOLEAN"
    try:
        if text:
            float(text)
            return "NUMBER"
    except Exception:
        pass
    return "TEXT"

def runninghub_is_workflow_link_value(value):
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )

def runninghub_workflow_node_info_list(workflow_json):
    result = []
    if not isinstance(workflow_json, dict):
        return result
    for node_id, node_content in workflow_json.items():
        inputs = node_content.get("inputs") if isinstance(node_content, dict) else None
        if not isinstance(inputs, dict):
            continue
        for field_name, raw_value in inputs.items():
            if runninghub_is_workflow_link_value(raw_value):
                continue
            if isinstance(raw_value, (dict, list)):
                field_value = json.dumps(raw_value, ensure_ascii=False)
            elif raw_value is None:
                field_value = ""
            else:
                field_value = str(raw_value)
            result.append({
                "nodeId": str(node_id),
                "fieldName": str(field_name),
                "fieldValue": field_value,
                "fieldType": runninghub_infer_workflow_field_type(field_name, field_value),
                "source": "workflow",
            })
    return result

def runninghub_task_endpoint(provider, model):
    raw_model_path = str(model or "").strip()
    model_path = raw_model_path.strip("/")
    if not model_path:
        model_path = RUNNINGHUB_DEFAULT_IMAGE_MODELS[0]
    if raw_model_path.startswith("/openapi/"):
        return runninghub_endpoint_url(provider, raw_model_path)
    if model_path.startswith("openapi/"):
        return runninghub_endpoint_url(provider, f"/{model_path}")
    return runninghub_openapi_url(provider, model_path)

def runninghub_endpoint_alias_for_model(model):
    model_id = str(model or "").strip().strip("/")
    if not model_id:
        return ""
    direct = RUNNINGHUB_MODEL_ENDPOINT_ALIASES.get(model_id)
    if direct:
        return direct
    lowered = model_id.lower()
    if lowered.startswith("gpt-image-2.0/") or lowered.startswith("gpt-image-2/"):
        if "/text-to-image-" in lowered or lowered.endswith("/text-to-image"):
            return "rhart-image-g-2/text-to-image"
        if "/edit-" in lowered or lowered.endswith("/edit"):
            return "rhart-image-g-2/image-to-image"
        if "/image-to-image-" in lowered or lowered.endswith("/image-to-image"):
            return "rhart-image-g-2/image-to-image"
    if lowered.startswith("nano-banana/"):
        if "/text-to-image-" in lowered or lowered.endswith("/text-to-image"):
            return "rhart-image-v1/text-to-image"
        if "/edit-" in lowered or lowered.endswith("/edit"):
            return "rhart-image-v1/edit"
    return ""

def runninghub_registry_fallback():
    image = [
        {"name_en": "gpt-image-2.0/text-to-image-channel-low-price", "endpoint": "rhart-image-g-2/text-to-image", "output_type": "image"},
        {"name_en": "gpt-image-2.0/edit-channel-low-price", "endpoint": "rhart-image-g-2/image-to-image", "output_type": "image"},
        {"name_en": "gpt-image-2/text-to-image-official-stable", "endpoint": "rhart-image-g-2-official/text-to-image", "output_type": "image"},
        {"name_en": "gpt-image-2/image-to-image-official-stable", "endpoint": "rhart-image-g-2-official/image-to-image", "output_type": "image"},
        {"name_en": "nano-banana/text-to-image-official-stable", "endpoint": "rhart-image-v1-official/text-to-image", "output_type": "image"},
        {"name_en": "nano-banana/edit-official-stable", "endpoint": "rhart-image-v1-official/edit", "output_type": "image"},
    ]
    video = [
        {"name_en": "google/veo3.1-fast/text-to-video-channel-low-price", "endpoint": "rhart-video-v3.1-fast/text-to-video", "output_type": "video"},
        {"name_en": "sora-2/text-to-video-official-stable", "endpoint": "rhart-video-s-official/text-to-video", "output_type": "video"},
        {"name_en": "seedance-2.0-global/text-to-video", "endpoint": "bytedance/seedance-2.0-global/text-to-video", "output_type": "video"},
        {"name_en": "seedance-2.0-global/image-to-video", "endpoint": "bytedance/seedance-2.0-global/image-to-video", "output_type": "video"},
    ]
    return image + video

def runninghub_registry_items_from_raw(raw):
    candidates = [raw]
    if isinstance(raw, dict):
        candidates.extend([
            raw.get("data"),
            raw.get("models"),
            raw.get("list"),
            raw.get("items"),
            raw.get("records"),
            raw.get("result"),
        ])
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
        if isinstance(candidate, dict):
            nested = (
                candidate.get("models")
                or candidate.get("list")
                or candidate.get("items")
                or candidate.get("records")
                or candidate.get("data")
            )
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []

def runninghub_registry_model_from_id(model_id, output_type=""):
    model_id = str(model_id or "").strip()
    if not model_id:
        return None
    output_type = str(output_type or "").strip().lower() or classify_upstream_model(model_id)
    return {"name_en": model_id, "endpoint": model_id, "output_type": output_type}

async def fetch_runninghub_llm_models(provider=None):
    headers = runninghub_api_headers(provider)
    errors = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for url in RUNNINGHUB_LLM_MODELS_URLS:
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code >= 400 or looks_like_html_response(resp.text):
                    errors.append(f"{url}: HTTP {resp.status_code} {resp.text[:180]}")
                    continue
                raw = resp.json() if resp.text else {}
                grouped, ids = parse_upstream_models(raw, "openai")
                if ids:
                    return [runninghub_registry_model_from_id(mid, "chat") for mid in ids], {"source": url, "count": len(ids)}
                errors.append(f"{url}: empty")
            except Exception as exc:
                errors.append(f"{url}: {str(exc)[:180]}")
    return [], {"source": "", "count": 0, "errors": errors[-3:]}

async def fetch_runninghub_model_registry(provider=None, include_fallback=True, include_meta=False):
    urls = [
        ("openapi", runninghub_openapi_url(provider, "models")),
        ("github", RUNNINGHUB_MODEL_REGISTRY_URL),
    ]
    if os.path.exists(STATIC_RUNNINGHUB_MODEL_REGISTRY_FILE):
        urls.append(("local", STATIC_RUNNINGHUB_MODEL_REGISTRY_FILE))
    headers = runninghub_api_headers(provider)
    errors = []
    source = ""
    items = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for source_name, url in urls:
            try:
                if source_name == "local":
                    with open(url, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                else:
                    req_headers = headers if source_name == "openapi" else {"Accept": "application/json"}
                    resp = await client.get(url, headers=req_headers)
                    if resp.status_code >= 400 or looks_like_html_response(resp.text):
                        errors.append(f"{source_name}: HTTP {resp.status_code} {resp.text[:180]}")
                        continue
                    raw = resp.json() if resp.text else []
                parsed = runninghub_registry_items_from_raw(raw)
                if parsed:
                    items = parsed
                    source = source_name
                    break
                errors.append(f"{source_name}: empty")
            except Exception as exc:
                errors.append(f"{source_name}: {str(exc)[:180]}")
                continue
    llm_items, llm_meta = await fetch_runninghub_llm_models(provider)
    combined = [*items]
    seen = {runninghub_model_id(item) for item in combined if runninghub_model_id(item)}
    for item in llm_items:
        mid = runninghub_model_id(item)
        if mid and mid not in seen:
            combined.append(item)
            seen.add(mid)
    if combined:
        meta = {
            "source": source or "llm",
            "openapi_count": len(items),
            "llm_count": len(llm_items),
            "llm_source": llm_meta.get("source") or "",
            "errors": [*errors[-3:], *((llm_meta.get("errors") or [])[-3:])],
        }
        return (combined, meta) if include_meta else combined
    if include_fallback:
        fallback = runninghub_registry_fallback()
        meta = {
            "source": "fallback",
            "openapi_count": 0,
            "llm_count": 0,
            "llm_source": "",
            "errors": [*errors[-3:], *((llm_meta.get("errors") or [])[-3:])],
        }
        return (fallback, meta) if include_meta else fallback
    raise HTTPException(status_code=502, detail=f"拉取 RunningHub 模型注册表失败：{'; '.join(errors[-4:]) or 'unknown error'}")

def runninghub_model_id(item):
    if not isinstance(item, dict):
        return ""
    return str(item.get("name_en") or item.get("id") or item.get("name") or item.get("endpoint") or "").strip()

def runninghub_registry_payload(items):
    grouped = {"image": [], "chat": RUNNINGHUB_FALLBACK_CHAT_MODELS[:], "video": []}
    all_ids = []
    for item in items or []:
        mid = runninghub_model_id(item)
        if not mid:
            continue
        output_type = str(item.get("output_type") or item.get("outputType") or "").strip().lower()
        if output_type in ("image", "video"):
            grouped[output_type].append(mid)
            all_ids.append(mid)
    for model in RUNNINGHUB_DEFAULT_IMAGE_MODELS:
        if model not in grouped["image"]:
            grouped["image"].append(model)
            all_ids.append(model)
    for model in RUNNINGHUB_DEFAULT_VIDEO_MODELS:
        if model not in grouped["video"]:
            grouped["video"].append(model)
            all_ids.append(model)
    for model in RUNNINGHUB_FALLBACK_CHAT_MODELS:
        if model not in all_ids:
            all_ids.append(model)
    for key in grouped:
        grouped[key] = sorted(set(grouped[key]))
    return {
        "total": len(set(all_ids)),
        "image_models": grouped["image"],
        "chat_models": grouped["chat"],
        "video_models": grouped["video"],
        "all": sorted(set(all_ids)),
        "protocol": "runninghub",
    }

async def runninghub_models_payload(provider=None):
    registry, meta = await fetch_runninghub_model_registry(provider, include_fallback=True, include_meta=True)
    payload = runninghub_registry_payload(registry)
    payload["raw"] = {"registry_count": len(registry), **meta}
    if meta.get("source") == "fallback":
        payload["message"] = "RunningHub 模型接口未返回完整列表，当前显示内置兜底模型。"
    else:
        payload["message"] = f"RunningHub 模型列表来自 {meta.get('source')}"
    return payload

async def runninghub_model_definition(provider, model):
    requested = str(model or "").strip().strip("/")
    registry = await fetch_runninghub_model_registry(provider, include_fallback=True)
    for item in registry:
        mid = runninghub_model_id(item)
        endpoint = str(item.get("endpoint") or "").strip().strip("/")
        if requested and requested in {mid, endpoint, f"/openapi/v2/{endpoint}", f"openapi/v2/{endpoint}"}:
            if endpoint:
                return item
            alias = runninghub_endpoint_alias_for_model(mid or requested)
            if alias:
                patched = dict(item)
                patched["endpoint"] = alias
                return patched
            return item
    endpoint = requested
    if endpoint.startswith("/openapi/v2/"):
        endpoint = endpoint[len("/openapi/v2/"):]
    elif endpoint.startswith("openapi/v2/"):
        endpoint = endpoint[len("openapi/v2/"):]
    endpoint = runninghub_endpoint_alias_for_model(requested) or endpoint
    return {"name_en": requested, "endpoint": endpoint or RUNNINGHUB_DEFAULT_IMAGE_MODELS[0], "output_type": classify_upstream_model(requested), "params": []}

def runninghub_schema_options(field):
    values = []
    for item in (field or {}).get("options") or []:
        if isinstance(item, dict):
            value = item.get("value")
        else:
            value = item
        if value is not None and str(value) != "":
            values.append(str(value))
    return values

def runninghub_schema_value(field, preferred=None):
    preferred = "" if preferred is None else str(preferred).strip()
    options = runninghub_schema_options(field)
    if preferred and (not options or preferred in options):
        return preferred
    default = (field or {}).get("defaultValue")
    if default is not None and str(default) != "":
        return default
    return options[0] if options else preferred

def runninghub_schema_field(params, *keys):
    wanted = {str(k).lower() for k in keys if k}
    for field in params or []:
        if not isinstance(field, dict):
            continue
        names = {str(field.get("fieldKey") or "").lower(), str(field.get("label") or "").lower()}
        if names & wanted:
            return field
    return None

def runninghub_aspect_from_size(size, fallback="1:1"):
    width, height = parse_size_pair(size)
    if width and height:
        divisor = math.gcd(width, height) or 1
        return f"{width // divisor}:{height // divisor}"
    raw = str(size or "").strip().lower()
    if re.fullmatch(r"(auto|\d+\s*:\s*\d+)", raw):
        return raw.replace(" ", "")
    return fallback

def runninghub_resolution_from_size(size, fallback="2k"):
    width, height = parse_size_pair(size)
    if width and height:
        long_edge = max(width, height)
        if long_edge >= 3200:
            return "4k"
        if long_edge >= 1400:
            return "2k"
        return "1k"
    raw = str(size or "").strip().lower()
    return raw if raw in {"1k", "2k", "4k", "480p", "720p", "1080p", "native1080p"} else fallback

def runninghub_size_for_aspect(aspect_ratio, fallback="1280x720"):
    ratio = str(aspect_ratio or "").strip()
    return {
        "9:16": "720x1280",
        "16:9": "1280x720",
        "1:1": "1024x1024",
        "4:3": "1024x768",
        "3:4": "768x1024",
    }.get(ratio, fallback)

def runninghub_apply_schema_defaults(body, params):
    for field in params or []:
        if not isinstance(field, dict):
            continue
        key = str(field.get("fieldKey") or "").strip()
        if not key or key in body:
            continue
        default = field.get("defaultValue")
        options = runninghub_schema_options(field)
        if default is None or default == "":
            if field.get("required") is True and options:
                default = options[0]
            else:
                continue
        ftype = str(field.get("type") or "").upper()
        if ftype == "BOOLEAN":
            body[key] = bool(default) if not isinstance(default, str) else default.lower() == "true"
        elif ftype in {"INT", "INTEGER"}:
            try:
                body[key] = int(default)
            except Exception:
                body[key] = default
        elif ftype == "FLOAT":
            try:
                body[key] = float(default)
            except Exception:
                body[key] = default
        else:
            body[key] = default
    return body

def runninghub_query_status(raw):
    if not isinstance(raw, dict):
        return ""
    values = [
        raw.get("status"),
        raw.get("state"),
        raw.get("taskStatus"),
        raw.get("task_status"),
    ]
    data = raw.get("data")
    if isinstance(data, dict):
        values.extend([data.get("status"), data.get("state"), data.get("taskStatus"), data.get("task_status")])
    for value in values:
        if value is not None:
            return str(value).lower()
    return ""

def runninghub_extract_task_id(raw):
    if not isinstance(raw, dict):
        return ""
    for key in ("taskId", "task_id", "id"):
        if raw.get(key):
            return str(raw[key])
    data = raw.get("data")
    if isinstance(data, dict):
        for key in ("taskId", "task_id", "id"):
            if data.get(key):
                return str(data[key])
    return ""

def runninghub_extract_image(raw):
    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail="RunningHub 返回格式不是 JSON 对象")
    containers = [raw]
    data = raw.get("data")
    if isinstance(data, dict):
        containers.append(data)
    for container in containers:
        results = container.get("results") or container.get("result") or container.get("outputs") or container.get("output")
        if isinstance(results, dict):
            results = [results]
        if isinstance(results, list):
            for item in results:
                if isinstance(item, str) and item.startswith(("http://", "https://")):
                    return {"type": "url", "value": rewrite_runninghub_file_url(item)}
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "url" and item.get("value"):
                    return {"type": "url", "value": rewrite_runninghub_file_url(item["value"])}
                if item.get("type") == "b64" and item.get("value"):
                    return {"type": "b64", "value": item["value"], "mime_type": item.get("mime_type") or "image/png"}
                url = item.get("url") or item.get("fileUrl") or item.get("file_url") or item.get("download_url") or item.get("imageUrl") or item.get("image_url")
                if isinstance(url, list) and url:
                    url = url[0]
                if isinstance(url, str) and url:
                    return {"type": "url", "value": rewrite_runninghub_file_url(url)}
    image = extract_image(raw)
    if image.get("type") == "url":
        image["value"] = rewrite_runninghub_file_url(image.get("value"))
    return image

async def runninghub_upload_reference(client, provider, ref):
    path = output_file_from_url(ref.get("url", ""))
    if not path:
        value = ref.get("url", "")
        return value if str(value).startswith(("http://", "https://")) else ""
    upload_url = runninghub_openapi_url(provider, "media/upload/binary")
    headers = {"Authorization": bearer_auth_value(runninghub_api_key(provider)), "Accept": "application/json"}
    with open(path, "rb") as fh:
        files = {"file": (os.path.basename(path), fh, content_type_for_path(path))}
        response = await client.post(upload_url, headers=headers, files=files, timeout=120)
    response.raise_for_status()
    raw = response.json()
    data = raw.get("data") if isinstance(raw, dict) else None
    candidates = [raw, data] if isinstance(data, dict) else [raw]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        value = item.get("download_url") or item.get("downloadUrl") or item.get("url") or item.get("fileUrl") or item.get("file_url")
        if value:
            return str(value)
    raise HTTPException(status_code=502, detail=f"RunningHub 上传图片未返回 download_url：{raw}")

async def wait_for_runninghub_image_task(client, provider, task_id):
    query_url = runninghub_openapi_url(provider, "query")
    deadline = time.monotonic() + 1800
    last_payload = None
    while time.monotonic() < deadline:
        await asyncio.sleep(2)
        response = await client.post(query_url, headers=runninghub_api_headers(provider), json={"taskId": task_id})
        response.raise_for_status()
        raw = response.json()
        last_payload = raw
        status = runninghub_query_status(raw)
        if status in {"success", "succeeded", "completed", "complete", "finished", "finish", "done", "3"}:
            return raw
        if status in {"failed", "fail", "error", "canceled", "cancelled", "4"}:
            raise HTTPException(status_code=502, detail=f"RunningHub 任务失败：{raw}")
        try:
            return {"data": {"results": [runninghub_extract_image(raw)]}}
        except HTTPException:
            pass
    raise HTTPException(status_code=504, detail=f"RunningHub 生图任务超时：{last_payload}")

RUNNINGHUB_ENTRY_MODEL_RE = re.compile(r"^(app|workflow):(.+)$")

def rh_field_kind(field):
    field = field or {}
    t = str(field.get("fieldType") or "").strip().upper()
    if t == "IMAGE":
        return "image"
    if t == "VIDEO":
        return "video"
    if t == "AUDIO":
        return "audio"
    if t == "SLIDER":
        return "slider"
    if t in ("NUMBER", "FLOAT", "INTEGER", "INT"):
        return "number"
    if t in ("BOOLEAN", "BOOL"):
        return "boolean"
    key = f"{field.get('fieldName') or ''} {field.get('fieldValue') or ''}".lower()
    if re.search(r"\b(image|img|mask|photo|picture)\b", key) or re.search(r"\.(png|jpe?g|webp|gif|bmp)(\?|$)", key, re.I):
        return "image"
    if re.search(r"\b(video|movie|mp4)\b", key) or re.search(r"\.(mp4|webm|mov|m4v|mkv)(\?|$)", key, re.I):
        return "video"
    if re.search(r"\b(audio|sound|music|voice)\b", key) or re.search(r"\.(mp3|wav|ogg|m4a|flac|aac)(\?|$)", key, re.I):
        return "audio"
    return "text"

def rh_field_role(field):
    kind = rh_field_kind(field)
    if kind in ("image", "video", "audio", "number", "slider", "boolean"):
        return kind
    field = field or {}
    text = f"{field.get('fieldName') or ''} {field.get('label') or ''} {field.get('group') or ''}".lower()
    if re.search(r"prompt|positive|negative|text|caption|description|关键词|提示词|正向|负向", text):
        return "prompt"
    return "text"

def _rh_natural_cmp(x, y):
    if x == y:
        return 0
    if x.isdigit() and y.isdigit():
        ix, iy = int(x), int(y)
        return (ix > iy) - (ix < iy)
    return (x > y) - (x < y)

def _rh_field_cmp(a, b):
    ak, bk = rh_field_kind(a), rh_field_kind(b)
    if ak == "image" and bk == "image":
        try:
            ao = int(a.get("imageOrder") or 0) or 9999
        except Exception:
            ao = 9999
        try:
            bo = int(b.get("imageOrder") or 0) or 9999
        except Exception:
            bo = 9999
        if ao != bo:
            return ao - bo
    if ak == "image" and bk != "image":
        return -1
    if ak != "image" and bk == "image":
        return 1
    node_cmp = _rh_natural_cmp(str(a.get("nodeId") or ""), str(b.get("nodeId") or ""))
    if node_cmp != 0:
        return node_cmp
    fa, fb = str(a.get("fieldName") or ""), str(b.get("fieldName") or "")
    return (fa > fb) - (fa < fb)

def rh_sort_fields(fields):
    return sorted(list(fields or []), key=functools.cmp_to_key(_rh_field_cmp))

def rh_field_indexes(fields):
    counters = {"image": 0, "video": 0, "audio": 0}
    mapping = {}
    for field in rh_sort_fields(fields):
        kind = rh_field_kind(field)
        if kind in counters:
            mapping[(str(field.get("nodeId") or ""), str(field.get("fieldName") or ""))] = counters[kind]
            counters[kind] += 1
    return mapping

def rh_default_value(field):
    value = (field or {}).get("fieldValue")
    if isinstance(value, list):
        value = value[0] if value else ""
    if value is None or isinstance(value, dict):
        return ""
    return str(value)

SEED_UINT32_MAX = 4294967295

def rh_is_seed_like_name(*parts) -> bool:
    text = " ".join(str(part or "") for part in parts).lower()
    return any(key in text for key in ("seed", "noise", "随机", "种子", "噪"))

def normalize_seed_uint32(value):
    try:
        if isinstance(value, bool):
            return value
        raw = str(value).strip()
        if not raw:
            return value
        num = int(float(raw))
    except Exception:
        return value
    if 0 <= num <= SEED_UINT32_MAX:
        return value
    safe = ((abs(num) - 1) % SEED_UINT32_MAX) + 1
    return str(safe) if isinstance(value, str) else safe

def sanitize_seed_like_workflow_values(value, parent_key=""):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if rh_is_seed_like_name(key) and not isinstance(item, (dict, list)):
                result[key] = normalize_seed_uint32(item)
            else:
                result[key] = sanitize_seed_like_workflow_values(item, key)
        return result
    if isinstance(value, list):
        return [sanitize_seed_like_workflow_values(item, parent_key) for item in value]
    if rh_is_seed_like_name(parent_key):
        return normalize_seed_uint32(value)
    return value

def sanitize_runninghub_node_info_list(items):
    result = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        clean = dict(item)
        if rh_is_seed_like_name(clean.get("fieldName"), clean.get("label"), clean.get("note")):
            clean["fieldValue"] = normalize_seed_uint32(clean.get("fieldValue"))
        result.append(clean)
    return result

def rh_random_field_value(field):
    def _num(raw, default):
        try:
            s = str(raw).strip()
            if s == "" or s.lower() == "none":
                return default
            return float(s)
        except Exception:
            return default
    looks_seed = rh_is_seed_like_name((field or {}).get("fieldName"), (field or {}).get("label"), (field or {}).get("note"))
    lo = _num((field or {}).get("min"), 0.0)
    hi = _num((field or {}).get("max"), float(SEED_UINT32_MAX) if looks_seed else 999999.0)
    if looks_seed:
        hi = min(hi, float(SEED_UINT32_MAX))
        lo = max(0.0, min(lo, hi))
    if hi < lo:
        lo, hi = hi, lo
    step = _num((field or {}).get("step"), 1.0)
    value = random.uniform(lo, hi)
    if step and step > 0:
        value = lo + round((value - lo) / step) * step
    if float(step).is_integer() and float(lo).is_integer() and float(hi).is_integer():
        return str(int(round(value)))
    return str(value)

def runninghub_entry_config_from_model(provider, model):
    """解析 model=app:ID / workflow:ID，返回 {kind,id,fields,optionalImageMode,workflowJson} 或 None。"""
    text = str(model or "").strip()
    match = RUNNINGHUB_ENTRY_MODEL_RE.match(text)
    if not match:
        return None
    kind = match.group(1)
    entry_id = match.group(2).strip()
    if not entry_id:
        return None
    if kind == "workflow":
        key = runninghub_workflow_store_key(entry_id)
        with RUNNINGHUB_WORKFLOW_LOCK:
            store = load_runninghub_workflow_store()
        cfg = runninghub_select_workflow_config(store.get(key), runninghub_provider_workflow_config(key), key)
        if not isinstance(cfg, dict):
            # 退回到 provider 列表中的内联条目
            entry = next(
                (e for e in (provider.get("rh_workflows") or []) if runninghub_entry_id(e, "workflow") == entry_id),
                None,
            )
            if not entry:
                return None
            cfg = {
                "fields": entry.get("fields") or [],
                "optionalImageMode": entry.get("optionalImageMode") or "prune-workflow",
                "workflowJson": entry.get("workflowJson") if isinstance(entry.get("workflowJson"), dict) else {},
            }
        return {
            "kind": "workflow",
            "id": entry_id,
            "fields": cfg.get("fields") or [],
            "optionalImageMode": cfg.get("optionalImageMode") or "prune-workflow",
            "workflowJson": cfg.get("workflowJson") if isinstance(cfg.get("workflowJson"), dict) else {},
        }
    entry = next(
        (e for e in (provider.get("rh_apps") or []) if runninghub_entry_id(e, "app") == entry_id),
        None,
    )
    if not entry:
        return None
    return {
        "kind": "app",
        "id": entry_id,
        "fields": entry.get("fields") or [],
        "optionalImageMode": "",
        "workflowJson": {},
    }

async def runninghub_upload_local_to_filename(client, provider, url, use_wallet=False):
    """把本地/远程素材上传到 RunningHub /task/openapi/upload，返回 fileName（供 nodeInfoList 使用）。"""
    text = str(url or "").strip()
    if not text:
        return ""
    path = runninghub_local_asset_path(text)
    if path:
        filename = os.path.basename(path)
        content_type = content_type_for_path(path)
        with open(path, "rb") as fh:
            content = fh.read()
    elif text.startswith(("http://", "https://")):
        response = await client.get(text, follow_redirects=True)
        response.raise_for_status()
        content = response.content
        content_type = response.headers.get("content-type") or "application/octet-stream"
        filename = os.path.basename(urllib.parse.urlsplit(text).path) or "asset.bin"
    else:
        return ""
    if not content:
        return ""
    api_key = runninghub_api_key(provider, use_wallet=use_wallet)
    upload_url = runninghub_endpoint_url(provider, "/task/openapi/upload")
    files = {"file": (filename, content, content_type)}
    data = {"apiKey": api_key, "fileType": "input"}
    response = await client.post(upload_url, headers=runninghub_app_headers(False, use_wallet), data=data, files=files)
    raw = response.json()
    if isinstance(raw, dict) and raw.get("code") in (0, "0") and isinstance(raw.get("data"), dict) and raw["data"].get("fileName"):
        return raw["data"]["fileName"]
    raise HTTPException(status_code=502, detail=(raw.get("msg") if isinstance(raw, dict) else "") or f"RunningHub 上传素材失败：{raw}")

async def generate_runninghub_entry_image(prompt, size, model, reference_images, provider, entry):
    """运行 RunningHub 工作流 / AI 应用（与智能画布一致的运行方式），返回首张图片结果。"""
    kind = entry["kind"]
    entry_id = entry["id"]
    fields = rh_sort_fields([f for f in (entry.get("fields") or []) if isinstance(f, dict) and f.get("enabled") is True])
    idx_map = rh_field_indexes(fields)
    use_wallet = False
    timeout = httpx.Timeout(connect=20.0, read=1800.0, write=240.0, pool=20.0)
    aspect = runninghub_aspect_from_size(size, "")
    resolution = runninghub_resolution_from_size(size, "")
    width, height = parse_size_pair(size)
    def requested_size_field_value(field):
        names = {
            str(field.get("fieldName") or "").strip().lower(),
            str(field.get("fieldKey") or "").strip().lower(),
            str(field.get("label") or "").strip().lower(),
        }
        if aspect and names & {"aspectratio", "aspect_ratio", "ratio"}:
            return runninghub_schema_value(field, aspect)
        if resolution and "resolution" in names:
            return runninghub_schema_value(field, resolution)
        if width and "width" in names:
            return width
        if height and "height" in names:
            return height
        return None
    async with httpx.AsyncClient(timeout=timeout) as client:
        uploaded = []
        for ref in (reference_images or [])[:ONLINE_IMAGE_REFERENCE_MAX]:
            ref_url = ref.get("url") if isinstance(ref, dict) else ref
            if not ref_url:
                continue
            file_name = await runninghub_upload_local_to_filename(client, provider, ref_url, use_wallet)
            if file_name:
                uploaded.append(file_name)

        node_info_list = []
        prompt_text = str(prompt or "").strip()
        for field in fields:
            node_id = str(field.get("nodeId") or "").strip()
            field_name = str(field.get("fieldName") or "").strip()
            if not node_id or not field_name:
                continue
            kind_f = rh_field_kind(field)
            if kind_f in ("image", "video", "audio"):
                if kind_f != "image":
                    continue  # 在线生图仅提供图片素材
                index = idx_map.get((node_id, field_name), 0)
                value = uploaded[index] if index < len(uploaded) else ""
                if not value:
                    # 工作流可选图（required!=True）无输入则跳过；必填图回退默认值
                    if field.get("required") is True:
                        value = rh_default_value(field)
                        if not value:
                            continue
                    else:
                        continue
                node_info_list.append({"nodeId": node_id, "fieldName": field_name, "fieldValue": value})
            elif rh_field_role(field) == "prompt":
                value = prompt_text or rh_default_value(field)
                node_info_list.append({"nodeId": node_id, "fieldName": field_name, "fieldValue": value})
            elif kind_f == "number" and field.get("random_enabled") is True:
                node_info_list.append({"nodeId": node_id, "fieldName": field_name, "fieldValue": rh_random_field_value(field)})
            else:
                value = requested_size_field_value(field)
                if value is None:
                    value = rh_default_value(field)
                node_info_list.append({"nodeId": node_id, "fieldName": field_name, "fieldValue": value})

        api_key = runninghub_api_key(provider, use_wallet=use_wallet)
        if kind == "workflow":
            submit_url = runninghub_endpoint_url(provider, "/task/openapi/create")
            body = {"apiKey": api_key, "workflowId": entry_id, "addMetadata": True}
            if node_info_list:
                body["nodeInfoList"] = node_info_list
        else:
            submit_url = runninghub_endpoint_url(provider, "/task/openapi/ai-app/run")
            body = {"apiKey": api_key, "webappId": entry_id, "nodeInfoList": node_info_list}

        response = await client.post(submit_url, headers=runninghub_app_headers(True, use_wallet), json=body)
        raw = response.json()
        if not (isinstance(raw, dict) and raw.get("code") in (0, "0")):
            raise HTTPException(status_code=502, detail=(raw.get("msg") if isinstance(raw, dict) else "") or f"RunningHub 提交失败：{raw}")
        task_id = raw.get("data", {}).get("taskId") if isinstance(raw.get("data"), dict) else ""
        if not task_id:
            raise HTTPException(status_code=502, detail=f"RunningHub 未返回 taskId：{raw}")

        query_url = runninghub_endpoint_url(provider, "/task/openapi/outputs")
        deadline = time.monotonic() + 1800
        last_payload = None
        while time.monotonic() < deadline:
            await asyncio.sleep(2.5)
            query_response = await client.post(query_url, headers=runninghub_app_headers(True), json={"apiKey": api_key, "taskId": task_id})
            query_raw = query_response.json()
            last_payload = query_raw
            code = query_raw.get("code") if isinstance(query_raw, dict) else None
            if code in (0, "0"):
                outputs = runninghub_extract_outputs(query_raw.get("data"))
                for remote in outputs:
                    if str(remote or "").startswith(("http://", "https://", "/output/", "/assets/")):
                        return {"type": "url", "value": str(remote)}, query_raw
                raise HTTPException(status_code=502, detail=f"RunningHub 任务无图片输出：{query_raw}")
            if code in (805, "805"):
                raise HTTPException(status_code=502, detail=f"RunningHub 任务失败：{runninghub_fail_reason(query_raw) or query_raw}")
            # 804 运行中 / 813 排队中 / 其他状态继续轮询
        raise HTTPException(status_code=504, detail=f"RunningHub 任务超时：{last_payload}")

async def generate_runninghub_provider_image(prompt, size, model, reference_images=None, provider=None):
    entry = runninghub_entry_config_from_model(provider, model)
    if entry:
        return await generate_runninghub_entry_image(prompt, size, model, reference_images, provider, entry)
    model_def = await runninghub_model_definition(provider, model)
    endpoint = runninghub_task_endpoint(provider, model_def.get("endpoint") or model)
    params = model_def.get("params") if isinstance(model_def.get("params"), list) else []
    aspect = runninghub_aspect_from_size(size, "1:1")
    resolution = runninghub_resolution_from_size(size, "2k")
    body = {"prompt": prompt}
    if runninghub_schema_field(params, "aspectRatio"):
        field = runninghub_schema_field(params, "aspectRatio")
        body["aspectRatio"] = runninghub_schema_value(field, aspect)
    elif runninghub_schema_field(params, "ratio"):
        field = runninghub_schema_field(params, "ratio")
        body["ratio"] = runninghub_schema_value(field, aspect)
    if runninghub_schema_field(params, "resolution"):
        field = runninghub_schema_field(params, "resolution")
        body["resolution"] = runninghub_schema_value(field, resolution)
    width, height = parse_size_pair(size)
    if width and height:
        if runninghub_schema_field(params, "width"):
            body["width"] = width
        if runninghub_schema_field(params, "height"):
            body["height"] = height
    quality_field = runninghub_schema_field(params, "quality")
    if quality_field:
        body["quality"] = runninghub_schema_value(quality_field, "medium")
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=1800.0, write=180.0, pool=20.0)) as client:
        image_urls = []
        for ref in (reference_images or [])[:ONLINE_IMAGE_REFERENCE_MAX]:
            url = await runninghub_upload_reference(client, provider, ref)
            if url:
                image_urls.append(url)
        if image_urls:
            image_field = runninghub_schema_field(params, "imageUrls", "imageUrl", "images", "image")
            key = str((image_field or {}).get("fieldKey") or "imageUrls")
            if key.endswith("s") or (image_field or {}).get("multipleInputs") is True:
                body[key] = image_urls
            else:
                body[key] = image_urls[0]
        runninghub_apply_schema_defaults(body, params)
        response = await client.post(endpoint, headers=runninghub_json_headers(provider), json=body)
        response.raise_for_status()
        raw = response.json()
        try:
            return runninghub_extract_image(raw), raw
        except HTTPException:
            task_id = runninghub_extract_task_id(raw)
            if not task_id:
                raise HTTPException(status_code=502, detail=f"RunningHub 未返回 taskId 或图片结果：{raw}")
        result = await wait_for_runninghub_image_task(client, provider, task_id)
        return runninghub_extract_image(result), result

async def wait_for_runninghub_openapi_task(client, provider, task_id, output_kind=""):
    query_url = runninghub_openapi_url(provider, "query")
    deadline = time.monotonic() + 1800
    last_payload = None
    while time.monotonic() < deadline:
        await asyncio.sleep(3)
        response = await client.post(query_url, headers=runninghub_json_headers(provider), json={"taskId": task_id})
        response.raise_for_status()
        raw = response.json()
        last_payload = raw
        status = runninghub_query_status(raw).upper()
        if status in {"SUCCESS", "SUCCEEDED", "COMPLETED", "COMPLETE", "FINISHED", "DONE", "3"}:
            return raw
        if status in {"FAILED", "FAIL", "ERROR", "CANCEL", "CANCELED", "CANCELLED", "4"}:
            raise HTTPException(status_code=502, detail=f"RunningHub 任务失败：{runninghub_fail_reason(raw) or raw}")
        if output_kind == "video" and video_output_urls(raw):
            return raw
    raise HTTPException(status_code=504, detail=f"RunningHub 任务超时：{last_payload or task_id}")

async def generate_runninghub_video(payload, provider):
    model_def = await runninghub_model_definition(provider, payload.model)
    endpoint = runninghub_task_endpoint(provider, model_def.get("endpoint") or payload.model)
    params = model_def.get("params") if isinstance(model_def.get("params"), list) else []
    body = {"prompt": str(payload.prompt or "")}
    aspect = str(payload.aspect_ratio or "16:9").strip() or "16:9"
    if runninghub_schema_field(params, "aspectRatio"):
        field = runninghub_schema_field(params, "aspectRatio")
        body["aspectRatio"] = runninghub_schema_value(field, aspect)
    if runninghub_schema_field(params, "ratio"):
        field = runninghub_schema_field(params, "ratio")
        body["ratio"] = runninghub_schema_value(field, aspect)
    if runninghub_schema_field(params, "size"):
        field = runninghub_schema_field(params, "size")
        body["size"] = runninghub_schema_value(field, runninghub_size_for_aspect(aspect))
    if runninghub_schema_field(params, "duration"):
        field = runninghub_schema_field(params, "duration")
        body["duration"] = runninghub_schema_value(field, str(max(1, min(60, int(payload.duration or 5)))))
    if runninghub_schema_field(params, "resolution"):
        field = runninghub_schema_field(params, "resolution")
        body["resolution"] = runninghub_schema_value(field, str(payload.resolution or "720p").lower())
    if runninghub_schema_field(params, "generateAudio"):
        body["generateAudio"] = bool(payload.generate_audio)
    if runninghub_schema_field(params, "watermark"):
        body["watermark"] = bool(payload.watermark)
    async with httpx.AsyncClient(timeout=VIDEO_POLL_TIMEOUT) as client:
        image_urls = []
        for ref in (payload.images or [])[:10]:
            ref_url = getattr(ref, "url", "") or ""
            if ref_url:
                up = await runninghub_upload_reference(client, provider, {"url": ref_url})
                if up:
                    image_urls.append(up)
        if image_urls:
            image_field = runninghub_schema_field(params, "imageUrls", "imageUrl", "firstFrameImage", "lastFrameImage", "referenceImages")
            key = str((image_field or {}).get("fieldKey") or "imageUrls")
            if key in {"firstFrameImage", "first_frame_image"}:
                body[key] = image_urls[0]
                last_field = runninghub_schema_field(params, "lastFrameImage", "last_frame_image")
                if len(image_urls) > 1 and last_field:
                    body[str(last_field.get("fieldKey"))] = image_urls[1]
            elif key.endswith("s") or (image_field or {}).get("multipleInputs") is True:
                body[key] = image_urls
            else:
                body[key] = image_urls[0]
        runninghub_apply_schema_defaults(body, params)
        response = await client.post(endpoint, headers=runninghub_json_headers(provider), json=body)
        response.raise_for_status()
        raw = response.json()
        task_id = runninghub_extract_task_id(raw)
        result = raw
        if task_id and not video_output_urls(raw):
            result = await wait_for_runninghub_openapi_task(client, provider, task_id, "video")
        urls = video_output_urls(result)
        if not urls:
            outputs = runninghub_extract_outputs(result.get("data") if isinstance(result, dict) else result)
            urls = [url for url in outputs if str(url).startswith(("http://", "https://", "/output/", "/assets/"))]
        if not urls:
            raise HTTPException(status_code=502, detail=f"RunningHub 视频生成成功但没有返回视频：{result}")
        local_urls = [await save_remote_video_to_output(url, prefix="rh_video_") for url in urls]
        return {"videos": local_urls, "task_id": task_id, "raw": result}
