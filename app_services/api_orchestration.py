"""API endpoint orchestration for tools and generation tasks."""

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
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import httpx
import requests
from fastapi import File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from PIL import Image, ImageOps

from api_models import (
    AIReference,
    CanvasLLMRequest,
    CanvasVideoRequest,
    GenerateRequest,
    ImageTaskQueryRequest,
    OnlineImageRequest,
    TokenRequest,
)


API_ORCHESTRATION_EXPORTS = (
    'index',
    'view_image',
    'download_output',
    'upload_image',
    'upload_ai_reference',
    'upload_ai_base64',
    'upload_comfyui_base64',
    'runninghub_app_info',
    'runninghub_submit',
    'runninghub_workflow_submit',
    'runninghub_workflow_info',
    'list_runninghub_workflows',
    'get_runninghub_workflow',
    'fetch_runninghub_workflow',
    'save_runninghub_workflow',
    'delete_runninghub_workflow',
    'runninghub_query',
    'runninghub_upload_asset',
    'codex_status',
    'codex_help',
    'gemini_cli_status',
    'gemini_cli_help',
    'jimeng_status',
    'jimeng_credit',
    'jimeng_logout',
    'jimeng_login_start',
    'jimeng_login_status',
    'jimeng_help',
    'jimeng_query_media',
    'ai_config',
    'ai_models',
    'get_global_token',
    'build_online_image_result',
    'online_image',
    'query_image_task',
    'run_canvas_image_task',
    'create_canvas_image_task',
    'get_canvas_image_task',
    'run_canvas_comfy_task',
    'create_canvas_comfy_task',
    'get_canvas_comfy_task',
    'build_image_param_fields',
    'image_params',
    'canvas_llm',
)


def configure_api_orchestration(namespace: dict[str, Any]) -> None:
    required = {
        'AI_API_KEY',
        'AI_BASE_URL',
        'AI_REQUEST_TIMEOUT',
        'BASE_DIR',
        'CANVAS_TASKS',
        'CANVAS_TASK_LOCK',
        'CHAT_MODEL',
        'CHAT_MODELS',
        'CODEX_DEFAULT_CHAT_MODELS',
        'COMFYUI_INSTANCES',
        'GEMINI_CLI_DEFAULT_CHAT_MODELS',
        'GLOBAL_CONFIG_FILE',
        'GLOBAL_LOOP',
        'IMAGE_MODEL',
        'IMAGE_MODELS',
        'IMAGE_PARAM_RATIOS',
        'IMAGE_PARAM_RESOLUTIONS',
        'IMAGE_TASK_FAILED_STATUSES',
        'JIMENG_LOGIN_SESSION',
        'JIMENG_MIN_CLI_VERSION',
        'JimengPendingError',
        'MAX_HISTORY_MESSAGES',
        'MODELSCOPE_CHAT_MODELS',
        'ONLINE_IMAGE_REFERENCE_MAX',
        'RUNNINGHUB_WORKFLOW_LOCK',
        'VIDEO_MODELS',
        '_local_upload_kind_ext',
        'codex_chat_text',
        'codex_cli_executable',
        'codex_decode_output',
        'content_type_for_path',
        'extract_images',
        'extract_task_id',
        'extract_task_id_from_text',
        'fetch_image_task_payload',
        'filename_from_media_url',
        'friendly_chat_error_detail',
        'friendly_image_error_detail',
        'gemini_cli_chat_text',
        'gemini_cli_display_name',
        'gemini_cli_executable',
        'generate',
        'get_api_provider',
        'gpt_image_2_skill_executable',
        'image_output_meta',
        'image_references',
        'image_task_fail_reason',
        'image_task_status',
        'is_antigravity_cli',
        'is_apimart_provider',
        'is_codex_provider',
        'is_gemini_cli_provider',
        'is_gpt_image_2_model',
        'is_image_reference_value',
        'is_runninghub_provider',
        'is_video_reference_value',
        'is_volcengine_provider',
        'jimeng_cli_executable',
        'jimeng_cli_version',
        'jimeng_command',
        'jimeng_login_qr_from_text',
        'jimeng_login_reader',
        'jimeng_login_text',
        'jimeng_pending_payload',
        'jimeng_query_result',
        'jimeng_store_outputs',
        'load_api_providers',
        'load_runninghub_workflow_store',
        'local_media_file_by_basename',
        'log_net_error',
        'manager',
        'media_reference_to_url',
        'modelscope_api_key',
        'now_ms',
        'output_file_from_url',
        'output_path_for',
        'output_url_for',
        'public_api_providers',
        'remove_runninghub_workflow_from_provider',
        'resolve_chat_provider',
        'rewrite_runninghub_file_url',
        'run_jimeng_cli',
        'runninghub_api_key',
        'runninghub_app_headers',
        'runninghub_collect_workflow_fields',
        'runninghub_endpoint_url',
        'runninghub_extract_outputs',
        'runninghub_fail_reason',
        'runninghub_is_saved_link_field',
        'runninghub_local_asset_path',
        'runninghub_provider',
        'runninghub_provider_workflow_config',
        'runninghub_saved_hidden_workflow_ids',
        'runninghub_select_workflow_config',
        'runninghub_store_remote_output',
        'runninghub_workflow_node_info_list',
        'runninghub_workflow_store_key',
        'sanitize_export_filename',
        'sanitize_runninghub_node_info_list',
        'sanitize_seed_like_workflow_values',
        'save_ai_image_to_output',
        'save_runninghub_workflow_store',
        'save_to_history',
        'selected_model',
        'static_html_response',
        'sync_runninghub_workflow_to_provider',
        'text_from_chat_response',
        'unwrap_apimart_response',
        'video_reference_to_frame_data_urls',
    }
    missing = sorted(required - namespace.keys())
    if missing:
        raise RuntimeError(f"Api Orchestration missing dependencies: {', '.join(missing)}")
    globals().update({name: namespace[name] for name in required})


def export_api_orchestration(target: dict[str, Any]) -> None:
    for name in API_ORCHESTRATION_EXPORTS:
        target[name] = globals()[name]


async def index():
    return static_html_response("index.html")

def view_image(filename: str, type: str = "input", subfolder: str = ""):
    # 先按原逻辑去各 ComfyUI 后端找
    for addr in COMFYUI_INSTANCES:
        try:
            url = f"http://{addr}/view"
            params = {"filename": filename, "type": type, "subfolder": subfolder}
            r = requests.get(url, params=params, timeout=1)
            if r.status_code == 200:
                return Response(content=r.content, media_type=r.headers.get('Content-Type'))
        except Exception:
            continue
    # 后端都拿不到时回退本地 assets/<input|output>/
    # 适用场景：画布通过 /api/ai/upload 把参考图直接落到本地 assets/input/，
    # 但 ComfyUI 的 input 可能因为重启/清理而丢失，导致 enhance/klein 等页面预览对比图 404
    if not subfolder and type in ("input", "output"):
        safe_name = os.path.basename(filename or "")
        if safe_name:
            local_path = output_path_for(safe_name, "input" if type == "input" else "output")
            if os.path.isfile(local_path):
                return FileResponse(local_path, media_type=content_type_for_path(local_path))
    raise HTTPException(status_code=404, detail="Image not found on any available backend")

def download_output(request: Request, url: str, name: str = "", inline: bool = False):
    url = rewrite_runninghub_file_url(url)
    path = output_file_from_url(url)
    if not path:
        path = local_media_file_by_basename(filename_from_media_url(url, ""))
    if path:
        filename = sanitize_export_filename(os.path.basename(name) if name else os.path.basename(path), os.path.basename(path))
        return FileResponse(path, media_type=content_type_for_path(path), filename=None if inline else filename)
    # 远程文件：流式代理，绝不把整段视频/大文件读进内存（否则多个视频同时代理会撑爆内存、拖垮单进程服务）。
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="无效的下载地址")
    try:
        upstream_headers = {"User-Agent": "ComfyUI-API-Modelscope/1.0"}
        range_header = request.headers.get("range")
        if range_header:
            upstream_headers["Range"] = range_header
        upstream = requests.get(
            url, stream=True, timeout=(10, 60),
            headers=upstream_headers,
        )
        upstream.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"远程文件下载失败：{exc}")
    content_type = upstream.headers.get("content-type") or "application/octet-stream"
    fallback = filename_from_media_url(url, "download.bin")
    filename = sanitize_export_filename(os.path.basename(name) if name else fallback, fallback)
    disposition = "inline" if inline else "attachment"
    headers = {"Content-Disposition": f"{disposition}; filename*=UTF-8''{urllib.parse.quote(filename)}"}
    content_length = upstream.headers.get("content-length")
    if content_length:
        headers["Content-Length"] = content_length
    for key in ("content-range", "accept-ranges"):
        value = upstream.headers.get(key)
        if value:
            headers["-".join(part.capitalize() for part in key.split("-"))] = value

    def stream_remote():
        try:
            for chunk in upstream.iter_content(chunk_size=256 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(stream_remote(), media_type=content_type, headers=headers, status_code=upstream.status_code)

async def upload_image(files: List[UploadFile] = File(...)):
    uploaded_files = []
    files_content = []
    for file in files:
        content = await file.read()
        files_content.append((file, content))

    for file, content in files_content:
        success_count = 0
        last_result = None
        for addr in COMFYUI_INSTANCES:
            try:
                files_data = {'image': (file.filename, content, file.content_type)}
                response = requests.post(f"http://{addr}/upload/image", files=files_data, timeout=5)
                if response.status_code == 200:
                    last_result = response.json()
                    success_count += 1
            except Exception as e:
                print(f"Upload error for {addr}: {e}")

        if success_count > 0 and last_result:
            uploaded_files.append({"comfy_name": last_result.get("name", file.filename)})
        else:
            raise HTTPException(status_code=500, detail="Failed to upload to any backend")

    return {"files": uploaded_files}

async def upload_ai_reference(files: List[UploadFile] = File(...)):
    uploaded = []
    image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    video_exts = {".mp4", ".webm", ".mov", ".m4v", ".flv"}
    audio_exts = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
    doc_exts = {".pdf", ".txt", ".md", ".markdown", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".json", ".zip", ".yaml", ".yml", ".log"}
    max_upload_bytes = 50 * 1024 * 1024
    for file in files:
        content = await file.read()
        if not content:
            continue
        if len(content) > max_upload_bytes:
            raise HTTPException(status_code=413, detail=f"{file.filename or '文件'} 超过 50MB，无法上传")
        ext = os.path.splitext(file.filename or "")[1].lower()
        content_type = (file.content_type or "").lower()
        kind = "image"
        if ext in video_exts or content_type.startswith("video/"):
            kind = "video"
            if ext not in video_exts:
                ext = ".webm" if "webm" in content_type else ".mov" if "quicktime" in content_type else ".mp4"
        elif ext in audio_exts or content_type.startswith("audio/"):
            kind = "audio"
            if ext not in audio_exts:
                ext = ".wav" if "wav" in content_type else ".ogg" if "ogg" in content_type else ".m4a" if "mp4" in content_type else ".mp3"
        elif ext in image_exts or content_type.startswith("image/"):
            kind = "image"
            if ext not in image_exts:
                ext = ".jpg" if "jpeg" in content_type else ".webp" if "webp" in content_type else ".gif" if "gif" in content_type else ".png"
        elif ext in doc_exts or content_type.startswith(("text/", "application/")):
            kind = "file"
            if not ext:
                ext = mimetypes.guess_extension(content_type) or ".bin"
        else:
            kind = "file"
            if not ext:
                ext = ".bin"
        filename = f"ai_ref_{uuid.uuid4().hex[:12]}{ext}"
        path = output_path_for(filename, "input")
        with open(path, "wb") as f:
            f.write(content)
        uploaded.append({"url": output_url_for(filename, "input"), "name": file.filename or filename, "kind": kind, "mime": content_type})
    return {"files": uploaded}

async def upload_ai_base64(payload: Base64UploadRequest):
    """以 base64 JSON 方式上传字节到 assets/input，返回 /assets 地址。
    给不便用 multipart/FormData 的客户端（如 PS UXP 面板）用——UXP 的 fetch+FormData 经常发不出有效 multipart。"""
    raw = (payload.data or "").strip()
    ct = (payload.content_type or "").split(";", 1)[0].strip().lower()
    if raw.startswith("data:"):
        header, _, raw = raw.partition(",")
        if not ct:
            ct = header[5:].split(";", 1)[0].strip().lower()
    try:
        content = base64.b64decode(raw, validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="数据无法解码")
    if not content:
        raise HTTPException(status_code=400, detail="内容为空")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="超过 50MB")
    kind, ext = _local_upload_kind_ext(payload.name or "", ct or "image/png")
    if kind is None:
        kind, ext = "image", ".png"
    filename = f"ai_ref_{uuid.uuid4().hex[:12]}{ext}"
    path = output_path_for(filename, "input")
    with open(path, "wb") as f:
        f.write(content)
    return {"files": [{"url": output_url_for(filename, "input"), "name": payload.name or filename, "kind": kind}]}

async def upload_comfyui_base64(payload: Base64UploadRequest):
    """base64 方式把图片传到 ComfyUI 各后端的 input 目录，返回 comfy 用文件名（供 UXP 做 ComfyUI 图生图）。"""
    raw = (payload.data or "").strip()
    ct = (payload.content_type or "").split(";", 1)[0].strip().lower()
    if raw.startswith("data:"):
        header, _, raw = raw.partition(",")
        if not ct:
            ct = header[5:].split(";", 1)[0].strip().lower()
    try:
        content = base64.b64decode(raw, validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="数据无法解码")
    if not content:
        raise HTTPException(status_code=400, detail="内容为空")
    _, ext = _local_upload_kind_ext(payload.name or "", ct or "image/png")
    filename = f"dx_{uuid.uuid4().hex[:12]}{ext or '.png'}"
    comfy_name = None
    for addr in COMFYUI_INSTANCES:
        try:
            resp = requests.post(f"http://{addr}/upload/image",
                                 files={'image': (filename, content, ct or 'image/png')}, timeout=10)
            if resp.status_code == 200:
                comfy_name = resp.json().get("name", filename)
        except Exception as exc:
            print(f"ComfyUI base64 upload error for {addr}: {exc}")
    if not comfy_name:
        raise HTTPException(status_code=502, detail="上传到 ComfyUI 失败")
    return {"name": comfy_name}

async def runninghub_app_info(webappId: str = ""):
    webapp_id = str(webappId or "").strip()
    if not webapp_id:
        raise HTTPException(status_code=400, detail="webappId 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider)
    url = runninghub_endpoint_url(provider, f"/api/webapp/apiCallDemo?apiKey={urllib.parse.quote(api_key)}&webappId={urllib.parse.quote(webapp_id)}")
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=120.0, write=30.0, pool=20.0)) as client:
        try:
            response = await client.get(url, headers=runninghub_app_headers(False))
            raw = response.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text[:500]) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"请求 RunningHub 应用信息失败：{exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=json.dumps(raw, ensure_ascii=False)[:500])
    if isinstance(raw, dict) and raw.get("code") not in (0, "0", None):
        raise HTTPException(status_code=400, detail=raw.get("msg") or f"RunningHub 查询失败 code={raw.get('code')}")
    data = raw.get("data") if isinstance(raw, dict) else {}
    return {"success": True, "data": data or {}}

async def runninghub_submit(payload: RunningHubSubmitRequest):
    webapp_id = str(payload.webappId or "").strip()
    if not webapp_id:
        raise HTTPException(status_code=400, detail="webappId 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider, use_wallet=payload.useWallet)
    body = {
        "apiKey": api_key,
        "webappId": webapp_id,
        "nodeInfoList": sanitize_runninghub_node_info_list(payload.nodeInfoList or []),
    }
    instance_type = str(payload.instanceType or "").strip()
    if instance_type:
        body["instanceType"] = instance_type
    url = runninghub_endpoint_url(provider, "/task/openapi/ai-app/run")
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=180.0, write=120.0, pool=20.0)) as client:
        try:
            response = await client.post(url, headers=runninghub_app_headers(True, payload.useWallet), json=body)
            raw = response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"提交 RunningHub 任务失败：{exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=json.dumps(raw, ensure_ascii=False)[:800])
    if isinstance(raw, dict) and raw.get("code") in (0, "0"):
        task_id = raw.get("data", {}).get("taskId") if isinstance(raw.get("data"), dict) else ""
        if not task_id:
            raise HTTPException(status_code=502, detail=f"RunningHub 未返回 taskId：{raw}")
        return {"success": True, "data": {"taskId": task_id, "raw": raw}}
    raise HTTPException(status_code=400, detail=(raw.get("msg") if isinstance(raw, dict) else "") or f"RunningHub 提交失败：{raw}")

async def runninghub_workflow_submit(payload: RunningHubWorkflowSubmitRequest):
    workflow_id = str(payload.workflowId or "").strip()
    if not workflow_id:
        raise HTTPException(status_code=400, detail="workflowId 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider, use_wallet=payload.useWallet)
    body = {
        "apiKey": api_key,
        "workflowId": workflow_id,
        "addMetadata": True,
    }
    if payload.nodeInfoList:
        body["nodeInfoList"] = sanitize_runninghub_node_info_list(payload.nodeInfoList)
    workflow_payload = payload.workflow
    if workflow_payload:
        if isinstance(workflow_payload, (dict, list)):
            body["workflow"] = json.dumps(sanitize_seed_like_workflow_values(workflow_payload), ensure_ascii=False)
        else:
            body["workflow"] = str(workflow_payload)
    url = runninghub_endpoint_url(provider, "/task/openapi/create")
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=180.0, write=120.0, pool=20.0)) as client:
        try:
            response = await client.post(url, headers=runninghub_app_headers(True, payload.useWallet), json=body)
            raw = response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"提交 RunningHub 工作流失败：{exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=json.dumps(raw, ensure_ascii=False)[:800])
    if isinstance(raw, dict) and raw.get("code") in (0, "0"):
        task_id = raw.get("data", {}).get("taskId") if isinstance(raw.get("data"), dict) else ""
        if not task_id:
            raise HTTPException(status_code=502, detail=f"RunningHub 工作流未返回 taskId：{raw}")
        return {"success": True, "data": {"taskId": task_id, "raw": raw}}
    raise HTTPException(status_code=400, detail=(raw.get("msg") if isinstance(raw, dict) else "") or f"RunningHub 工作流提交失败：{raw}")

async def runninghub_workflow_info(workflowId: str = ""):
    workflow_id = str(workflowId or "").strip()
    if not workflow_id:
        raise HTTPException(status_code=400, detail="workflowId 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider)
    url = runninghub_endpoint_url(provider, "/api/openapi/getJsonApiFormat")
    body = {"apiKey": api_key, "workflowId": workflow_id}
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=180.0, write=60.0, pool=20.0)) as client:
        try:
            response = await client.post(url, headers=runninghub_app_headers(True), json=body)
            raw = response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"拉取 RunningHub 工作流参数失败：{exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=json.dumps(raw, ensure_ascii=False)[:800])
    if not isinstance(raw, dict) or raw.get("code") not in (0, "0"):
        raise HTTPException(status_code=400, detail=(raw.get("msg") if isinstance(raw, dict) else "") or f"RunningHub 工作流参数拉取失败：{raw}")
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    prompt = data.get("prompt")
    workflow_json = {}
    if isinstance(prompt, str) and prompt.strip():
        try:
            workflow_json = json.loads(prompt)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"RunningHub 工作流 JSON 解析失败：{exc}") from exc
    elif isinstance(prompt, dict):
        workflow_json = prompt
    node_info_list = runninghub_workflow_node_info_list(workflow_json)
    return {"success": True, "data": {"workflowId": workflow_id, "nodeInfoList": node_info_list, "raw": raw}}

def list_runninghub_workflows():
    providers = load_api_providers()
    hidden_ids = runninghub_saved_hidden_workflow_ids()
    for provider in providers:
        if provider.get("id") != "runninghub":
            continue
        for entry in provider.get("rh_workflows") or []:
            workflow_id = runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id"))
            if workflow_id and entry.get("hidden") is True:
                hidden_ids.add(workflow_id)
    with RUNNINGHUB_WORKFLOW_LOCK:
        store = load_runninghub_workflow_store()
    merged = {workflow_id: cfg for workflow_id, cfg in store.items() if isinstance(cfg, dict) and workflow_id not in hidden_ids}
    for provider in providers:
        if provider.get("id") != "runninghub":
            continue
        for entry in provider.get("rh_workflows") or []:
            workflow_id = runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id"))
            if not workflow_id:
                continue
            if entry.get("hidden") is True:
                merged.pop(workflow_id, None)
                continue
            provider_cfg = runninghub_provider_workflow_config(workflow_id)
            if provider_cfg:
                merged[workflow_id] = runninghub_select_workflow_config(merged.get(workflow_id), provider_cfg, workflow_id)
    items = []
    for workflow_id, cfg in merged.items():
        if not isinstance(cfg, dict):
            continue
        items.append({
            "workflowId": workflow_id,
            "title": cfg.get("title") or workflow_id,
            "fieldCount": len(cfg.get("fields") or []),
            "updatedAt": cfg.get("updatedAt"),
            "description": cfg.get("description") or "",
        })
    items.sort(key=lambda item: item["title"])
    return {"workflows": items}

def get_runninghub_workflow(workflow_id: str):
    key = runninghub_workflow_store_key(workflow_id)
    if not key:
        raise HTTPException(status_code=400, detail="workflowId 必填")
    with RUNNINGHUB_WORKFLOW_LOCK:
        store = load_runninghub_workflow_store()
    cfg = store.get(key)
    provider_cfg = runninghub_provider_workflow_config(key)
    cfg = runninghub_select_workflow_config(cfg, provider_cfg, key)
    if not isinstance(cfg, dict):
        raise HTTPException(status_code=404, detail="RunningHub 工作流未找到")
    return {"workflow": cfg}

async def fetch_runninghub_workflow(payload: RunningHubWorkflowConfig):
    workflow_id = runninghub_workflow_store_key(payload.workflowId)
    if not workflow_id:
        raise HTTPException(status_code=400, detail="workflowId 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider)
    url = runninghub_endpoint_url(provider, "/api/openapi/getJsonApiFormat")
    body = {"apiKey": api_key, "workflowId": workflow_id}
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=180.0, write=60.0, pool=20.0)) as client:
        try:
            response = await client.post(url, headers=runninghub_app_headers(True), json=body)
            raw = response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to fetch RunningHub workflow parameters: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=json.dumps(raw, ensure_ascii=False)[:800])
    if not isinstance(raw, dict) or raw.get("code") not in (0, "0"):
        raise HTTPException(status_code=400, detail=(raw.get("msg") if isinstance(raw, dict) else "") or f"RunningHub workflow fetch failed: {raw}")
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    prompt = data.get("prompt")
    workflow_json = {}
    if isinstance(prompt, str) and prompt.strip():
        try:
            workflow_json = json.loads(prompt)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to parse RunningHub workflow JSON: {exc}") from exc
    elif isinstance(prompt, dict):
        workflow_json = prompt
    fields = runninghub_collect_workflow_fields(workflow_json)
    return {"success": True, "data": {"workflowId": workflow_id, "title": payload.title or workflow_id, "description": payload.description or "", "fields": fields, "workflowJson": workflow_json, "raw": raw}}

def save_runninghub_workflow(workflow_id: str, payload: RunningHubWorkflowConfig):
    key = runninghub_workflow_store_key(workflow_id)
    if not key:
        raise HTTPException(status_code=400, detail="workflowId 必填")
    fields = [
        field for field in (runninghub_normalize_field(item) for item in (payload.fields or []))
        if not runninghub_is_saved_link_field(field)
    ]
    cfg = {
        "workflowId": key,
        "title": (payload.title or key).strip() or key,
        "description": payload.description or "",
        "fields": fields,
        "workflowJson": payload.workflowJson or {},
        "optionalImageMode": payload.optionalImageMode or "prune-workflow",
        "raw": payload.raw or {},
        "updatedAt": now_ms(),
    }
    with RUNNINGHUB_WORKFLOW_LOCK:
        store = load_runninghub_workflow_store()
        store[key] = cfg
        save_runninghub_workflow_store(store)
    sync_runninghub_workflow_to_provider(cfg)
    return {"success": True, "workflow": cfg}

def delete_runninghub_workflow(workflow_id: str):
    key = runninghub_workflow_store_key(workflow_id)
    if not key:
        raise HTTPException(status_code=400, detail="workflowId 必填")
    with RUNNINGHUB_WORKFLOW_LOCK:
        store = load_runninghub_workflow_store()
        provider_cfg = runninghub_provider_workflow_config(key)
        if key not in store and not provider_cfg:
            raise HTTPException(status_code=404, detail="RunningHub 工作流未找到")
        store.pop(key, None)
        save_runninghub_workflow_store(store)
    remove_runninghub_workflow_from_provider(key)
    return {"success": True}

async def runninghub_query(taskId: str = ""):
    task_id = str(taskId or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="taskId 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider)
    url = runninghub_endpoint_url(provider, "/task/openapi/outputs")
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=240.0, write=30.0, pool=20.0)) as client:
        try:
            response = await client.post(url, headers=runninghub_app_headers(True), json={"apiKey": api_key, "taskId": task_id})
            raw = response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"查询 RunningHub 任务失败：{exc}") from exc
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=json.dumps(raw, ensure_ascii=False)[:800])
        code = raw.get("code") if isinstance(raw, dict) else None
        status = "PENDING"
        urls = []
        image_items = []
        if code in (0, "0"):
            status = "SUCCESS"
            for remote in runninghub_extract_outputs(raw.get("data")):
                try:
                    local_url = await runninghub_store_remote_output(client, remote)
                except Exception:
                    local_url = remote
                urls.append(local_url)
                image_items.append(image_output_meta(local_url))
        elif code in (804, "804"):
            status = "RUNNING"
        elif code in (813, "813"):
            status = "QUEUED"
        elif code in (805, "805"):
            status = "FAILED"
        else:
            status = "UNKNOWN"
        return {"success": True, "data": {"status": status, "urls": urls, "image_items": image_items, "failReason": runninghub_fail_reason(raw), "code": code, "raw": raw}}

async def runninghub_upload_asset(payload: RunningHubUploadAssetRequest):
    source_url = rewrite_runninghub_file_url(str(payload.url or "").strip())
    if not source_url:
        raise HTTPException(status_code=400, detail="url 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider, use_wallet=payload.useWallet)
    filename = "asset.bin"
    content_type = "application/octet-stream"
    content = b""
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=240.0, write=240.0, pool=20.0), follow_redirects=True) as client:
        path = runninghub_local_asset_path(source_url)
        if path:
            filename = os.path.basename(path)
            content_type = content_type_for_path(path)
            with open(path, "rb") as f:
                content = f.read()
        elif source_url.startswith(("http://", "https://")):
            response = await client.get(source_url)
            if not response.is_success:
                raise HTTPException(status_code=400, detail=f"下载素材失败 HTTP {response.status_code}")
            content = response.content
            content_type = response.headers.get("content-type") or content_type
            filename = os.path.basename(urllib.parse.urlsplit(source_url).path) or filename
        else:
            raise HTTPException(status_code=400, detail=f"不支持的素材地址：{source_url}")
        if not content:
            raise HTTPException(status_code=400, detail="素材为空，无法上传到 RunningHub")
        upload_url = runninghub_endpoint_url(provider, "/task/openapi/upload")
        files = {"file": (filename, content, content_type)}
        data = {"apiKey": api_key, "fileType": "input"}
        try:
            response = await client.post(upload_url, headers=runninghub_app_headers(False, payload.useWallet), data=data, files=files)
            raw = response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"上传素材到 RunningHub 失败：{exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=json.dumps(raw, ensure_ascii=False)[:800])
    if isinstance(raw, dict) and raw.get("code") in (0, "0") and isinstance(raw.get("data"), dict) and raw["data"].get("fileName"):
        return {"success": True, "data": {"fileName": raw["data"]["fileName"], "fileType": raw["data"].get("fileType") or content_type}}
    raise HTTPException(status_code=400, detail=(raw.get("msg") if isinstance(raw, dict) else "") or f"RunningHub 上传失败：{raw}")

async def codex_status():
    exe = codex_cli_executable()
    image2_exe = gpt_image_2_skill_executable()
    if not exe:
        return {
            "installed": False,
            "logged_in": False,
            "image2_helper_installed": bool(image2_exe),
            "image2_helper_path": image2_exe,
            "message": "未找到 OpenAI Codex CLI，请先安装。",
        }
    try:
        proc = await asyncio.create_subprocess_exec(
            exe,
            "--version",
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        out_text, err_text = codex_decode_output(stdout, stderr)
        ok = proc.returncode == 0
        helper_message = "GPT Image 2 helper 已安装，OpenAI CLI 生图会使用 GPT Image 2。" if image2_exe else "未找到 GPT Image 2 helper，OpenAI CLI 生图不可用；已禁用 Codex 内置 $imagegen 回退。"
        return {
            "installed": ok,
            "logged_in": None,
            "version": out_text or err_text,
            "path": exe,
            "image2_helper_installed": bool(image2_exe),
            "image2_helper_path": image2_exe,
            "message": f"OpenAI Codex CLI 已安装。{helper_message} 登录状态会在首次执行 codex exec 时由 CLI 校验。" if ok else (err_text or out_text or "Codex CLI 检测失败"),
            "raw": {"stdout": out_text, "stderr": err_text, "returncode": proc.returncode},
        }
    except Exception as exc:
        return {
            "installed": False,
            "logged_in": False,
            "path": exe,
            "image2_helper_installed": bool(image2_exe),
            "image2_helper_path": image2_exe,
            "message": f"Codex CLI 检测失败：{exc}",
        }

async def codex_help(payload: CodexHelpRequest):
    exe = codex_cli_executable()
    if not exe:
        raise HTTPException(status_code=400, detail="未找到 OpenAI Codex CLI。")
    allowed = {"", "exec", "login", "logout", "doctor", "mcp", "app", "update"}
    command = str(payload.command or "").strip()
    if command not in allowed:
        raise HTTPException(status_code=400, detail="不允许的 Codex CLI 命令")
    args = [exe]
    if command:
        args.append(command)
    args.append("--help")
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=BASE_DIR,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
    out_text, err_text = codex_decode_output(stdout, stderr)
    if proc.returncode != 0:
        raise HTTPException(status_code=502, detail=(err_text or out_text or f"exit={proc.returncode}")[:1000])
    return {"text": out_text or err_text, "raw": {"stdout": out_text, "stderr": err_text}}

async def gemini_cli_status():
    exe = gemini_cli_executable()
    display_name = gemini_cli_display_name(exe)
    if not exe:
        return {
            "installed": False,
            "logged_in": False,
            "provider": "antigravity",
            "message": "未找到 Antigravity CLI，请先安装。",
        }
    try:
        proc = await asyncio.create_subprocess_exec(
            exe,
            "--version",
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        out_text, err_text = codex_decode_output(stdout, stderr)
        ok = proc.returncode == 0
        is_agy = is_antigravity_cli(exe)
        return {
            "installed": ok,
            "logged_in": None,
            "version": out_text or err_text,
            "path": exe,
            "provider": "antigravity" if is_agy else "gemini",
            "message": f"{display_name} 已安装。登录状态会在首次执行 {'agy' if is_agy else 'gemini'} 时由 CLI 校验。" if ok else (err_text or out_text or f"{display_name} 检测失败"),
            "raw": {"stdout": out_text, "stderr": err_text, "returncode": proc.returncode},
        }
    except Exception as exc:
        return {
            "installed": False,
            "logged_in": False,
            "path": exe,
            "provider": "antigravity" if is_antigravity_cli(exe) else "gemini",
            "message": f"{display_name} 检测失败：{exc}",
        }

async def gemini_cli_help(payload: GeminiCliHelpRequest):
    exe = gemini_cli_executable()
    if not exe:
        raise HTTPException(status_code=400, detail="未找到 Antigravity CLI。")
    is_agy = is_antigravity_cli(exe)
    allowed = {"", "help", "install", "models", "plugin", "plugins", "update", "changelog"} if is_agy else {"", "help", "mcp", "extensions"}
    command = str(payload.command or "").strip()
    if command not in allowed:
        raise HTTPException(status_code=400, detail=f"不允许的 {gemini_cli_display_name(exe)} 命令")
    args = [exe]
    if command:
        args.append(command)
    args.append("--help")
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=BASE_DIR,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
    out_text, err_text = codex_decode_output(stdout, stderr)
    if proc.returncode != 0:
        raise HTTPException(status_code=502, detail=(err_text or out_text or f"exit={proc.returncode}")[:1000])
    return {"text": out_text or err_text, "raw": {"stdout": out_text, "stderr": err_text}}

async def jimeng_status():
    exe = jimeng_cli_executable()
    if not exe:
        return {"installed": False, "logged_in": False, "message": "未找到 dreamina CLI"}
    version, version_text = await jimeng_cli_version()
    version_str = ".".join(str(part) for part in version) if version else None
    version_ok = version >= JIMENG_MIN_CLI_VERSION if version else None
    min_version_str = ".".join(str(part) for part in JIMENG_MIN_CLI_VERSION)
    try:
        raw = await run_jimeng_cli(["user_credit"], timeout=30)
        return {
            "installed": True,
            "logged_in": True,
            "raw": raw,
            "cli_version": version_str,
            "version_ok": version_ok,
            "min_version": min_version_str,
        }
    except HTTPException as exc:
        return {
            "installed": True,
            "logged_in": False,
            "message": str(exc.detail),
            "cli_version": version_str,
            "version_ok": version_ok,
            "min_version": min_version_str,
        }

async def jimeng_credit():
    raw = await run_jimeng_cli(["user_credit"], timeout=30)
    return {"success": True, "raw": raw}

async def jimeng_logout():
    raw = await run_jimeng_cli(["logout"], timeout=30)
    return {"success": True, "raw": raw}

async def jimeng_login_start():
    old_proc = JIMENG_LOGIN_SESSION.get("proc")
    if old_proc and getattr(old_proc, "returncode", None) is None:
        try:
            old_proc.terminate()
        except Exception:
            pass
    exe = jimeng_cli_executable()
    if not exe:
        raise HTTPException(status_code=400, detail="未找到 dreamina CLI")
    JIMENG_LOGIN_SESSION.update({"proc": None, "stdout": "", "stderr": "", "started_at": time.time()})
    args = ["login", "--headless"]
    command = jimeng_command(args, exe)
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"未找到即梦 CLI：{exe}") from exc
    JIMENG_LOGIN_SESSION["proc"] = proc
    asyncio.create_task(jimeng_login_reader(proc))
    await asyncio.sleep(2)
    text = jimeng_login_text()
    if proc.returncode not in (None, 0) and ("unknown" in text.lower() or "no such option" in text.lower()):
        # 旧版 CLI 可能没有 --headless，退回 debug 输出。
        JIMENG_LOGIN_SESSION.update({"proc": None, "stdout": "", "stderr": "", "started_at": time.time()})
        proc = await asyncio.create_subprocess_exec(
            *jimeng_command(["login", "--debug"], exe),
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        JIMENG_LOGIN_SESSION["proc"] = proc
        asyncio.create_task(jimeng_login_reader(proc))
        await asyncio.sleep(2)
        text = jimeng_login_text()
    return {
        "success": True,
        "running": JIMENG_LOGIN_SESSION.get("proc") is not None and JIMENG_LOGIN_SESSION["proc"].returncode is None,
        "text": text,
        "qr_url": jimeng_login_qr_from_text(text),
        "started_at": JIMENG_LOGIN_SESSION.get("started_at") or 0,
    }

async def jimeng_login_status():
    proc = JIMENG_LOGIN_SESSION.get("proc")
    text = jimeng_login_text()
    running = proc is not None and getattr(proc, "returncode", None) is None
    logged_in = False
    credit_raw = None
    if not running:
        try:
            credit_raw = await run_jimeng_cli(["user_credit"], timeout=20)
            logged_in = True
        except HTTPException:
            logged_in = False
    return {
        "success": True,
        "running": running,
        "logged_in": logged_in,
        "text": text,
        "qr_url": jimeng_login_qr_from_text(text),
        "raw": credit_raw,
    }

async def jimeng_help(payload: JimengHelpRequest):
    command = str(payload.command or "").strip()
    allowed = {"", "login", "logout", "user_credit", "text2image", "image2image", "image_upscale", "text2video", "image2video", "multimodal2video", "frames2video", "multiframe2video", "list_task", "query_result"}
    if command not in allowed:
        raise HTTPException(status_code=400, detail="不支持的帮助命令")
    args = [command, "-h"] if command else ["-h"]
    raw = await run_jimeng_cli(args, timeout=30, raw_text=True)
    text = raw.get("_stdout") or ""
    if raw.get("_stderr"):
        text = f"{text}\n{raw.get('_stderr')}".strip()
    return {"success": True, "command": command, "text": text, "raw": raw}

async def jimeng_query_media(payload: JimengQueryMediaRequest):
    """按 submit_id 续查即梦任务：出图返回 succeeded+urls；仍排队返回 pending+queue_info；失败返回 failed。
    供画布「排队中」卡片自动轮询与手动查询复用。"""
    submit_id = str(payload.submit_id or "").strip()
    if not submit_id:
        raise HTTPException(status_code=400, detail="缺少 submit_id")
    kind = str(payload.kind or "image").strip().lower()
    if kind not in ("image", "video", "audio"):
        kind = "image"
    queried = await jimeng_query_result(submit_id, kind)
    try:
        urls = await jimeng_store_outputs(queried, kind, allow_query=False)
        return {"status": "succeeded", "submit_id": submit_id, "kind": kind, "urls": urls}
    except JimengPendingError as exc:
        return {"status": "pending", "submit_id": submit_id, "kind": kind, "queue_info": exc.queue_info, "message": jimeng_pending_payload(exc)["message"]}
    except HTTPException as exc:
        return {"status": "failed", "submit_id": submit_id, "kind": kind, "error": str(getattr(exc, "detail", "") or exc)}

async def ai_config():
    preferred_chat_model = next((m for m in CHAT_MODELS if m == "gpt-5.5"), CHAT_MODELS[0] if CHAT_MODELS else CHAT_MODEL)
    providers = public_api_providers()
    return {
        "base_url": AI_BASE_URL,
        "chat_model": preferred_chat_model,
        "image_model": IMAGE_MODEL,
        "chat_models": CHAT_MODELS,
        "image_models": IMAGE_MODELS,
        "video_models": VIDEO_MODELS,
        "comfy_instances": COMFYUI_INSTANCES,
        "api_providers": providers,
        "has_api_key": bool(AI_API_KEY),
        "ms_chat_models": MODELSCOPE_CHAT_MODELS,
        "has_ms_key": bool(modelscope_api_key()),
    }

async def ai_models():
    return {"chat_models": CHAT_MODELS, "image_models": IMAGE_MODELS, "video_models": VIDEO_MODELS}

async def get_global_token():
    # 优先读 env，回退到 global_config.json（兼容旧数据）
    saved_token = modelscope_api_key()
    if saved_token:
        return {"token": saved_token}
    if os.path.exists(GLOBAL_CONFIG_FILE):
        try:
            with open(GLOBAL_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return {"token": config.get("modelscope_token", "")}
        except:
            pass
    return {"token": ""}

async def build_online_image_result(payload: OnlineImageRequest):
    provider = get_api_provider(payload.provider_id)
    default_model = (provider.get("image_models") or [IMAGE_MODEL])[0]
    model = selected_model(payload.model, default_model)
    refs = [ref.dict() for ref in payload.reference_images if ref.url]
    image_refs = image_references(refs)
    count = max(1, min(8, int(payload.n or 1)))
    async def generate_one():
        image_data, raw_item = await generate_ai_image(payload.prompt, payload.size, payload.quality, model, image_refs, provider["id"])
        try:
            image_items = extract_images(raw_item) if isinstance(raw_item, dict) else [image_data]
        except HTTPException:
            image_items = [image_data]
        local_urls = []
        local_items = []
        for item in image_items:
            local_url = await save_ai_image_to_output(item, prefix="online_")
            if local_url:
                local_urls.append(local_url)
                local_items.append(image_output_meta(local_url, item))
        return local_urls, local_items, raw_item
    try:
        generated = await asyncio.gather(*(generate_one() for _ in range(count)))
    except httpx.HTTPStatusError as exc:
        log_net_error(f"生图 HTTP状态错误 provider={provider.get('id')} model={model} size={payload.size}", exc)
        text = exc.response.text or ''
        friendly = friendly_image_error_detail(text, payload.size, model)
        detail = friendly or f"上游生图接口错误：{text[:300]}"
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        log_net_error(f"生图 网络/TLS错误 provider={provider.get('id')} model={model}", exc)
        raise HTTPException(status_code=502, detail=f"请求上游生图接口失败：{exc}") from exc

    local_urls = [url for urls, _items, _raw in generated for url in (urls or []) if url]
    local_items = [item for _urls, items, _raw in generated for item in (items or []) if item.get("url")]
    raw = generated[0][2] if generated else {}
    if not local_urls:
        provider_name = provider.get("name") or provider["id"]
        raw_text = json.dumps(raw, ensure_ascii=False)[:800] if isinstance(raw, (dict, list)) else str(raw)[:800]
        raise HTTPException(status_code=502, detail=f"{provider_name} 没有返回图片：{raw_text}")
    result = {
        "prompt": payload.prompt,
        "images": local_urls,
        "image_items": local_items,
        "timestamp": time.time(),
        "type": "online",
        "model": model,
        "provider_id": provider["id"],
        "provider_name": provider.get("name") or provider["id"],
        "task_id": extract_task_id(raw) if isinstance(raw, dict) else None,
        "request_id": raw.get("id") if isinstance(raw, dict) else None,
        "params": {"provider_id": provider["id"], "model": model, "size": payload.size, "quality": payload.quality, "n": count, "reference_images": refs},
        "raw_usage": raw.get("usage") if isinstance(raw, dict) else None,
    }
    save_to_history(result)
    if GLOBAL_LOOP:
        asyncio.run_coroutine_threadsafe(manager.broadcast_new_image(result), GLOBAL_LOOP)
    return result

async def online_image(payload: OnlineImageRequest):
    return await build_online_image_result(payload)

async def query_image_task(payload: ImageTaskQueryRequest):
    provider = get_api_provider(payload.provider_id)
    task_id = str(payload.task_id or "").strip()
    if is_runninghub_provider(provider):
        api_key = runninghub_api_key(provider)
        url = runninghub_endpoint_url(provider, "/task/openapi/outputs")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=240.0, write=30.0, pool=20.0)) as client:
                response = await client.post(url, headers=runninghub_app_headers(True), json={"apiKey": api_key, "taskId": task_id})
                response.raise_for_status()
                raw = response.json()
                code = raw.get("code") if isinstance(raw, dict) else None
                if code in (0, "0"):
                    local_urls = []
                    local_items = []
                    for remote in runninghub_extract_outputs(raw.get("data")):
                        try:
                            local_url = await runninghub_store_remote_output(client, remote)
                        except Exception:
                            local_url = rewrite_runninghub_file_url(remote)
                        if local_url:
                            local_urls.append(local_url)
                            local_items.append(image_output_meta(local_url))
                    result = {
                        "status": "succeeded",
                        "prompt": "",
                        "images": local_urls,
                        "image_items": local_items,
                        "timestamp": time.time(),
                        "type": "online",
                        "model": "",
                        "provider_id": provider["id"],
                        "provider_name": provider.get("name") or provider["id"],
                        "task_id": task_id,
                        "request_id": "",
                        "params": {"provider_id": provider["id"]},
                        "raw": raw,
                    }
                    save_to_history(result)
                    if GLOBAL_LOOP:
                        asyncio.run_coroutine_threadsafe(manager.broadcast_new_image(result), GLOBAL_LOOP)
                    return result
                if code in (805, "805"):
                    return {
                        "status": "failed",
                        "task_id": task_id,
                        "provider_id": provider["id"],
                        "provider_name": provider.get("name") or provider["id"],
                        "error": runninghub_fail_reason(raw),
                        "raw": raw,
                    }
                return {
                    "status": "running",
                    "task_id": task_id,
                    "provider_id": provider["id"],
                    "provider_name": provider.get("name") or provider["id"],
                    "message": "RunningHub 任务仍在生成中",
                    "raw": raw,
                }
        except httpx.HTTPStatusError as exc:
            text = exc.response.text or ""
            raise HTTPException(status_code=exc.response.status_code, detail=f"查询 RunningHub 任务失败：{text[:300]}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"查询 RunningHub 任务失败：{exc}") from exc
    timeout = httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=20.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            raw = await fetch_image_task_payload(client, task_id, provider)
    except httpx.HTTPStatusError as exc:
        log_net_error(f"查询生图任务 HTTP状态错误 provider={provider.get('id')} task_id={task_id}", exc)
        text = exc.response.text or ""
        raise HTTPException(status_code=exc.response.status_code, detail=f"查询上游生图任务失败：{text[:300]}") from exc
    except httpx.HTTPError as exc:
        log_net_error(f"查询生图任务 网络/TLS错误 provider={provider.get('id')} task_id={task_id}", exc)
        raise HTTPException(status_code=502, detail=f"查询上游生图任务失败：{exc}") from exc

    status = image_task_status(raw)
    image_items = []
    try:
        image_items = extract_images(raw)
    except HTTPException:
        image_items = []
    if image_items:
        local_urls = []
        local_items = []
        for item in image_items:
            local_url = await save_ai_image_to_output(item, prefix="online_")
            if local_url:
                local_urls.append(local_url)
                local_items.append(image_output_meta(local_url, item))
        result = {
            "status": "succeeded",
            "prompt": "",
            "images": local_urls,
            "image_items": local_items,
            "timestamp": time.time(),
            "type": "online",
            "model": "",
            "provider_id": provider["id"],
            "provider_name": provider.get("name") or provider["id"],
            "task_id": task_id,
            "request_id": raw.get("id") if isinstance(raw, dict) else "",
            "params": {"provider_id": provider["id"]},
            "raw": raw,
        }
        save_to_history(result)
        if GLOBAL_LOOP:
            asyncio.run_coroutine_threadsafe(manager.broadcast_new_image(result), GLOBAL_LOOP)
        return result
    if status in IMAGE_TASK_FAILED_STATUSES:
        return {
            "status": "failed",
            "task_id": task_id,
            "provider_id": provider["id"],
            "provider_name": provider.get("name") or provider["id"],
            "error": image_task_fail_reason(raw),
            "raw": raw,
        }
    return {
        "status": "running",
        "task_id": task_id,
        "provider_id": provider["id"],
        "provider_name": provider.get("name") or provider["id"],
        "message": "任务仍在生成中",
        "raw": raw,
    }

async def run_canvas_image_task(task_id: str, payload: OnlineImageRequest):
    with CANVAS_TASK_LOCK:
        if task_id in CANVAS_TASKS:
            CANVAS_TASKS[task_id]["status"] = "running"
            CANVAS_TASKS[task_id]["updated_at"] = time.time()
    try:
        result = await build_online_image_result(payload)
        with CANVAS_TASK_LOCK:
            CANVAS_TASKS[task_id].update({
                "status": "succeeded",
                "result": result,
                "error": "",
                "updated_at": time.time(),
            })
    except JimengPendingError as exc:
        # 即梦云端还在排队：标记为 jimeng_pending，前端据 submit_id 持久续查（任务未丢失）
        info = jimeng_pending_payload(exc)
        with CANVAS_TASK_LOCK:
            CANVAS_TASKS[task_id].update({
                "status": "jimeng_pending",
                "jimeng_pending": True,
                "submit_id": exc.submit_id,
                "kind": exc.kind,
                "queue_info": exc.queue_info,
                "message": info["message"],
                "error": "",
                "updated_at": time.time(),
            })
    except Exception as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        status_code = getattr(exc, "status_code", 500)
        upstream_task_id = getattr(exc, "upstream_task_id", "") or extract_task_id_from_text(detail)
        with CANVAS_TASK_LOCK:
            CANVAS_TASKS[task_id].update({
                "status": "failed",
                "error": str(detail),
                "status_code": status_code,
                "upstream_task_id": upstream_task_id,
                "updated_at": time.time(),
            })

async def create_canvas_image_task(payload: OnlineImageRequest):
    task_id = f"canvas_img_{uuid.uuid4().hex}"
    with CANVAS_TASK_LOCK:
        CANVAS_TASKS[task_id] = {
            "id": task_id,
            "type": "online-image",
            "status": "queued",
            "created_at": time.time(),
            "updated_at": time.time(),
            "result": None,
            "error": "",
            "provider_id": payload.provider_id,
            "model": payload.model,
        }
    asyncio.create_task(run_canvas_image_task(task_id, payload))
    return {"task_id": task_id, "status": "queued"}

async def get_canvas_image_task(task_id: str):
    with CANVAS_TASK_LOCK:
        task = dict(CANVAS_TASKS.get(task_id) or {})
    if not task:
        raise HTTPException(status_code=404, detail="画布任务不存在，可能服务已重启或任务已过期")
    return task

async def run_canvas_comfy_task(task_id: str, payload: GenerateRequest):
    with CANVAS_TASK_LOCK:
        if task_id in CANVAS_TASKS:
            CANVAS_TASKS[task_id]["status"] = "running"
            CANVAS_TASKS[task_id]["updated_at"] = time.time()
    try:
        result = await asyncio.to_thread(generate, payload)
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(str(result.get("error") or "ComfyUI 生成失败"))
        with CANVAS_TASK_LOCK:
            CANVAS_TASKS[task_id].update({
                "status": "succeeded",
                "result": result,
                "error": "",
                "updated_at": time.time(),
            })
    except Exception as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        status_code = getattr(exc, "status_code", 500)
        with CANVAS_TASK_LOCK:
            CANVAS_TASKS[task_id].update({
                "status": "failed",
                "error": str(detail),
                "status_code": status_code,
                "updated_at": time.time(),
            })

async def create_canvas_comfy_task(payload: GenerateRequest):
    task_id = f"canvas_comfy_{uuid.uuid4().hex}"
    with CANVAS_TASK_LOCK:
        CANVAS_TASKS[task_id] = {
            "id": task_id,
            "type": "comfy",
            "status": "queued",
            "created_at": time.time(),
            "updated_at": time.time(),
            "result": None,
            "error": "",
            "workflow_json": payload.workflow_json,
        }
    asyncio.create_task(run_canvas_comfy_task(task_id, payload))
    return {"task_id": task_id, "status": "queued"}

async def get_canvas_comfy_task(task_id: str):
    with CANVAS_TASK_LOCK:
        task = dict(CANVAS_TASKS.get(task_id) or {})
    if not task:
        raise HTTPException(status_code=404, detail="ComfyUI 任务不存在，可能服务已重启或任务已过期")
    return task

def build_image_param_fields(engine: str, provider: dict, model: str):
    """返回某平台/引擎的图像生成参数字段定义。客户端按 type 动态渲染并回填到生成请求。
    字段 key 直接对应 OnlineImageRequest 的字段名（size/quality/n/reference_images）。"""
    gpt_auto_size = engine == "api" and is_gpt_image_2_model(model)
    image_resolutions = ([{"value": "auto", "label": "自动"}] + IMAGE_PARAM_RESOLUTIONS) if gpt_auto_size else IMAGE_PARAM_RESOLUTIONS
    size_field = {
        "key": "size", "type": "size", "label": "尺寸",
        "ratios": IMAGE_PARAM_RATIOS, "resolutions": image_resolutions,
        "default": {"ratio": "1:1", "resolution": "auto" if gpt_auto_size else "1k"},
    }
    count_field = {
        "key": "n", "type": "int", "label": "数量", "control": "chips",
        "options": [1, 2, 3, 4], "default": 1,
    }
    refs_field = {"key": "reference_images", "type": "refs", "label": "参考图", "max": ONLINE_IMAGE_REFERENCE_MAX}

    if engine == "runninghub":
        # RunningHub 参数按 app/工作流动态，需先选工作流再用 /api/runninghub/workflow-info 拉字段。
        return [{"key": "_rh_notice", "type": "notice",
                 "label": "RunningHub 工作流参数将按所选工作流动态加载（开发中）。"}]

    fields = [size_field]
    if engine in ("api", "volcengine"):
        fields.append({
            "key": "quality", "type": "select", "label": "质量", "control": "chips",
            "options": [
                {"value": "auto", "label": "自动"},
                {"value": "low", "label": "低"},
                {"value": "medium", "label": "中"},
                {"value": "high", "label": "高"},
            ],
            "default": "auto",
        })
    fields.append(count_field)
    fields.append(refs_field)
    return fields

async def image_params(provider_id: str = "", model: str = ""):
    providers = load_api_providers()
    provider = next((p for p in providers if p.get("id") == (provider_id or "").strip().lower()), None) or {}
    if is_runninghub_provider(provider):
        engine = "runninghub"
    elif (provider_id or "").strip().lower() == "modelscope":
        engine = "modelscope"
    elif is_volcengine_provider(provider):
        engine = "volcengine"
    else:
        engine = "api"
    return {
        "engine": engine,
        "submit": "/api/canvas-image-tasks",
        "fields": build_image_param_fields(engine, provider, model),
    }

async def canvas_llm(payload: CanvasLLMRequest):
    _provider = get_api_provider(payload.provider)
    if is_codex_provider(_provider):
        model = selected_model(payload.model, (_provider.get("chat_models") or CODEX_DEFAULT_CHAT_MODELS)[0])
        payload.model = model
        text, raw = await codex_chat_text(payload, payload.messages)
        return {"text": text, "model": model, "raw_usage": None, "raw": raw}
    if is_gemini_cli_provider(_provider):
        model = selected_model(payload.model, (_provider.get("chat_models") or GEMINI_CLI_DEFAULT_CHAT_MODELS)[0])
        payload.model = model
        text, raw = await gemini_cli_chat_text(payload, payload.messages)
        return {"text": text, "model": model, "raw_usage": None, "raw": raw}
    chat_base, chat_hdrs, model = resolve_chat_provider(payload.provider, payload.model, payload.ms_model)
    # 判断协议：APIMart 异步 vs 标准 OpenAI
    _llm_provider = get_api_provider(payload.provider) if payload.provider not in ("modelscope",) else {}
    _is_apimart = is_apimart_provider(_llm_provider)
    system_prompt = (payload.system_prompt or "").strip()
    upstream_messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
    for item in payload.messages[-MAX_HISTORY_MESSAGES:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            upstream_messages.append({"role": role, "content": content})
    # 构造用户消息：有图片/视频时用 OpenAI/Gemini 多模态格式
    image_inputs = [img for img in (payload.images or []) if is_image_reference_value(img)]
    video_inputs = [video for video in (payload.videos or []) if is_video_reference_value(video)]
    if image_inputs or video_inputs:
        content_parts = [{"type": "text", "text": payload.message}]
        ok_imgs = 0
        for img in image_inputs[:8]:
            if not img or not isinstance(img, str):
                continue
            ref_url = media_reference_to_url(img, max_image_size=1024)
            if not ref_url:
                continue
            content_parts.append({"type": "image_url", "image_url": {"url": ref_url}})
            ok_imgs += 1
        ok_videos = 0
        for video in video_inputs[:3]:
            if not video or not isinstance(video, str):
                continue
            frame_urls = await video_reference_to_frame_data_urls(video, max_frames=6, max_size=768)
            if frame_urls:
                ok_videos += 1
                content_parts.append({"type": "text", "text": f"以下是视频 {ok_videos} 按时间顺序抽取的关键帧，请结合这些画面理解视频内容。"})
                for frame_url in frame_urls:
                    content_parts.append({"type": "image_url", "image_url": {"url": frame_url}})
            else:
                ref_url = media_reference_to_url(video)
                if not ref_url:
                    continue
                content_parts.append({"type": "video_url", "video_url": {"url": ref_url}})
                ok_videos += 1
        print(f"[canvas-llm] model={model} provider={payload.provider} text_len={len(payload.message)} images={ok_imgs}/{len(payload.images)} videos={ok_videos}/{len(payload.videos)}")
        upstream_messages.append({"role": "user", "content": content_parts})
    else:
        upstream_messages.append({"role": "user", "content": payload.message})
    raw = None
    try:
        async with httpx.AsyncClient(timeout=AI_REQUEST_TIMEOUT) as client:
            req_body = {"model": model, "messages": upstream_messages}
            if _is_apimart:
                req_body["stream"] = False   # APIMart 默认流式，强制关闭
            response = await client.post(
                f"{chat_base}/chat/completions",
                headers=chat_hdrs,
                json=req_body,
            )
            response.raise_for_status()
            if not response.content:
                raise HTTPException(status_code=502, detail="上游接口返回了空响应")
            raw = response.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text or ""
        friendly = friendly_chat_error_detail(body, model, _llm_provider)
        raise HTTPException(status_code=exc.response.status_code, detail=friendly or f"上游接口错误：{body}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"请求上游接口失败：{exc}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"解析上游响应失败：{exc}") from exc
    try:
        text = text_from_chat_response(raw).strip() if isinstance(raw, dict) else ""
        text = text or "接口返回了空回复。"
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"解析回复内容失败：{exc}") from exc
    raw_data = unwrap_apimart_response(raw) if isinstance(raw, dict) else {}
    return {"text": text, "model": model, "raw_usage": raw_data.get("usage")}
