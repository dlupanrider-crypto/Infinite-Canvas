"""Shared provider request/response protocol helpers."""

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
from fastapi import HTTPException, Request, UploadFile
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

IMAGE_TASK_SUCCESS_STATUSES = {
    "SUCCESS", "SUCCESSFUL", "SUCCEED", "SUCCEEDED", "COMPLETED", "COMPLETE",
    "DONE", "FINISHED", "OK", "READY",
}
IMAGE_TASK_FAILED_STATUSES = {
    "FAILURE", "FAILED", "FAIL", "ERROR", "ERRORED", "CANCELED",
    "CANCELLED", "TIMEOUT", "REJECTED", "EXPIRED",
}

PROVIDER_RUNTIME_EXPORTS = (
    'IMAGE_TASK_SUCCESS_STATUSES',
    'IMAGE_TASK_FAILED_STATUSES',
    'display_title',
    'resolve_chat_provider',
    'log_net_error',
    'api_headers',
    'selected_model',
    'looks_like_vision_chat_model',
    'preferred_chat_model',
    'modelscope_size',
    'unwrap_apimart_response',
    'text_from_chat_response',
    'text_delta_from_chat_chunk',
    'sse_event',
    'looks_like_generated_image_url',
    'extract_image_flexible',
    'extract_images',
    'extract_image',
    'extract_task_id',
    'extract_task_id_from_text',
    'images_api_unsupported',
    'responses_image_size_instruction',
    'responses_proxy_tool_size',
    'responses_input_image_url',
    'responses_no_image_detail',
    'responses_output_text_image',
    '_responses_wrap',
    'post_openai_responses',
    'post_openai_responses_stream',
    'is_yuli_provider',
    'is_agnes_provider',
    'avatar_platform_for_provider',
    'provider_supports_avatar',
    'jimeng_pending_exception_handler',
    'image_task_url_for_provider',
    'image_task_data',
    'image_task_status',
    'image_task_fail_reason',
    'httpx_request_with_transient_retries',
    'fetch_image_task_payload',
    'wait_for_image_task',
)


def configure_provider_runtime(namespace: dict[str, Any]) -> None:
    required = {
        'AI_API_KEY',
        'AI_BASE_URL',
        'APIMART_IMAGE_INITIAL_POLL_DELAY',
        'APIMART_IMAGE_POLL_INTERVAL',
        'APIMART_IMAGE_TASK_TIMEOUT',
        'AVATAR_SUPPORTED_PLATFORMS',
        'CHAT_MODEL',
        'IMAGE_BASE64_KEY_HINTS',
        'IMAGE_CONTAINER_KEY_HINTS',
        'IMAGE_OUTPUT_KEY_HINTS',
        'IMAGE_POLL_INTERVAL',
        'IMAGE_TASK_TIMEOUT',
        'MODELSCOPE_CHAT_MODELS',
        'RESPONSES_POLL_INTERVAL',
        'RESPONSES_POLL_MAX_SECONDS',
        'RESPONSES_REJECT_STATUSES',
        'RUNNINGHUB_LLM_BASE_URL',
        'bearer_auth_value',
        'effective_protocol',
        'get_api_provider',
        'is_apimart_provider',
        'is_codex_provider',
        'is_gemini_cli_provider',
        'is_volcengine_provider',
        'jimeng_pending_payload',
        'modelscope_api_key',
        'modelscope_api_root',
        'normalize_image_request_mode',
        'output_file_from_url',
        'provider_env_key_value',
        'reference_to_data_url',
        'upload_local_video_to_cloud',
    }
    missing = sorted(required - namespace.keys())
    if missing:
        raise RuntimeError(f"Provider Runtime missing dependencies: {', '.join(missing)}")
    globals().update({name: namespace[name] for name in required})


def export_provider_runtime(target: dict[str, Any]) -> None:
    for name in PROVIDER_RUNTIME_EXPORTS:
        target[name] = globals()[name]


def display_title(text):
    title = re.sub(r"\s+", " ", text or "").strip()
    return title[:24] or "新对话"

def resolve_chat_provider(provider: str, model: str, ms_model: str):
    if provider == "modelscope":
        clean_token = modelscope_api_key()
        if not clean_token:
            raise HTTPException(status_code=400, detail="未配置 ModelScope API Key，请在 API 设置中填写。")
        base = modelscope_api_root()
        hdrs = {"Authorization": bearer_auth_value(clean_token), "Content-Type": "application/json"}
        mdl = selected_model(ms_model or model, MODELSCOPE_CHAT_MODELS[0] if MODELSCOPE_CHAT_MODELS else "MiniMax/MiniMax-M2.7")
        return base, hdrs, mdl
    api_provider = get_api_provider(provider or "")
    if is_codex_provider(api_provider):
        raise HTTPException(status_code=400, detail="OpenAI CLI 使用本机 codex 登录态，不需要 API Key。请使用画布/聊天里的 OpenAI CLI 专用通道。")
    if is_gemini_cli_provider(api_provider):
        raise HTTPException(status_code=400, detail="Antigravity CLI 使用本机 agy 登录态，不需要 API Key。请使用画布/聊天里的 Antigravity CLI 专用通道。")
    base_root = (api_provider.get("base_url") or AI_BASE_URL).rstrip("/")
    if not base_root:
        raise HTTPException(status_code=400, detail=f"{api_provider.get('name') or api_provider['id']} 未配置 Base URL")
    default_model = preferred_chat_model(api_provider)
    mdl = selected_model(model, default_model)
    protocol = effective_protocol(api_provider, mdl)
    if protocol == "gemini":
        base = base_root if base_root.endswith("/v1beta") else base_root + "/v1beta"
    elif protocol == "volcengine":
        base = base_root if base_root.endswith("/api/v3") else base_root + "/api/v3"
    elif protocol == "runninghub":
        base = RUNNINGHUB_LLM_BASE_URL
    else:
        base = base_root if base_root.endswith("/v1") else base_root + "/v1"
    hdrs = api_headers(provider=api_provider, model=mdl)
    return base, hdrs, mdl

def log_net_error(context, exc, url=""):
    """把网络请求异常的完整链路（含底层 SSL/socket 原因）打到控制台，方便排查 VPN/代理问题。
    httpx 通常把真正的 SSL/连接错误包在 __cause__/__context__ 里，这里把整条链都打出来，
    并附上请求 URL 与当前生效的系统代理，便于判断是「代理瞬时 TLS 错误」还是「线路不通」。
    日志本身绝不能影响主流程，全部包在 try 里。"""
    try:
        chain = []
        cur = exc
        seen = 0
        while cur is not None and seen < 6:
            chain.append(f"{type(cur).__module__}.{type(cur).__name__}: {str(cur)[:200]}")
            nxt = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
            if nxt is cur:
                break
            cur = nxt
            seen += 1
        if not url:
            req = getattr(exc, "request", None)
            if req is not None:
                url = str(getattr(req, "url", "") or "")
        try:
            proxies = urllib.request.getproxies() or "无"
        except Exception:
            proxies = "?"
        print(f"[NET-ERR] {context} | url={url or '?'} | sys_proxy={proxies} | " + " <- ".join(chain), flush=True)
    except Exception:
        try:
            print(f"[NET-ERR] {context} | {type(exc).__name__}: {exc}", flush=True)
        except Exception:
            pass

def api_headers(json_body=True, provider=None, model=""):
    if provider:
        if is_codex_provider(provider) or is_gemini_cli_provider(provider):
            raise HTTPException(status_code=400, detail="CLI 协议使用本机登录态，不需要 API Key。当前入口应走对应 CLI 专用通道。")
        api_key = provider_env_key_value(provider["id"])
        provider_name = provider.get("name") or provider["id"]
        if not api_key:
            raise HTTPException(status_code=400, detail=f"未配置 {provider_name} 的 API Key，请在 API 平台管理中填写。")
    else:
        api_key = AI_API_KEY
        if not api_key:
            raise HTTPException(status_code=400, detail="未配置 COMFLY_API_KEY，请在 API/.env 中填写。")
    if provider and effective_protocol(provider, model) == "gemini":
        headers = {"Accept": "application/json", "x-goog-api-key": api_key}
    else:
        headers = {"Accept": "application/json", "Authorization": bearer_auth_value(api_key)}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers

def selected_model(requested, fallback):
    model = (requested or fallback).strip()
    if not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if len(model) > 240 or any(ord(ch) < 32 or ord(ch) == 127 for ch in model):
        raise HTTPException(status_code=400, detail=f"模型名称不合法：{model}")
    return model

def looks_like_vision_chat_model(model):
    lc = str(model or "").strip().lower()
    if not lc:
        return False
    vision_keys = [
        "vision", "vl-", "-vl-", "internvl", "qvq", "qwen-vl",
        "doubao-vision", "glm-4v", "minicpm-v",
    ]
    return any(key in lc for key in vision_keys)

def preferred_chat_model(provider):
    values = [str(item or "").strip() for item in (provider.get("chat_models") or [CHAT_MODEL])]
    models = [item for item in values if item]
    if not models:
        return CHAT_MODEL
    if is_volcengine_provider(provider):
        endpoint_models = [item for item in models if item.lower().startswith("ep-")]
        if endpoint_models:
            return endpoint_models[0]
        text_like_models = [item for item in models if not looks_like_vision_chat_model(item)]
        if text_like_models:
            return text_like_models[0]
    return models[0]

def modelscope_size(value, fallback="1024x1024"):
    size = str(value or fallback).strip().lower().replace("*", "x")
    if re.fullmatch(r"\d{2,5}x\d{2,5}", size):
        return size
    raise HTTPException(status_code=400, detail=f"ModelScope size 格式不正确：{value or fallback}，应为 WxH，例如 1024x1024")

def unwrap_apimart_response(raw):
    """APIMart 将标准 OpenAI 响应包在 {"code":200,"data":{...}} 里；如果检测到就解包。"""
    if isinstance(raw, dict) and "data" in raw and isinstance(raw.get("data"), dict) and "choices" not in raw:
        return raw["data"]
    return raw

def text_from_chat_response(data):
    data = unwrap_apimart_response(data)
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or "")
        return "\n".join(part for part in parts if part)
    return str(content)

def text_delta_from_chat_chunk(data):
    choices = data.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    content = delta.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or "")
        return "".join(parts)
    return str(content) if content else ""

def sse_event(data):
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

def looks_like_generated_image_url(value):
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith("data:image/"):
        return True
    clean = text.split("?", 1)[0].split("#", 1)[0].lower()
    return text.startswith(("http://", "https://", "/output/", "/assets/")) and re.search(r"\.(png|jpe?g|webp|gif|bmp|tiff?)$", clean)

def extract_image_flexible(value, depth=0):
    if depth > 8 or value is None:
        return None
    if isinstance(value, str):
        return {"type": "url", "value": value} if looks_like_generated_image_url(value) else None
    if isinstance(value, list):
        for item in value:
            found = extract_image_flexible(item, depth + 1)
            if found:
                return found
        return None
    if not isinstance(value, dict):
        return None
    for key in IMAGE_BASE64_KEY_HINTS:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return {"type": "b64", "value": item.strip(), "mime_type": value.get("mime_type") or value.get("mimeType") or "image/png"}
    for key in IMAGE_OUTPUT_KEY_HINTS:
        item = value.get(key)
        if isinstance(item, str) and looks_like_generated_image_url(item):
            return {"type": "url", "value": item}
        found = extract_image_flexible(item, depth + 1)
        if found:
            return found
    for key in IMAGE_CONTAINER_KEY_HINTS:
        found = extract_image_flexible(value.get(key), depth + 1)
        if found:
            return found
    return None

def extract_images(data):
    found = []
    seen = set()

    def add_image(item):
        if not isinstance(item, dict):
            return
        img_type = item.get("type") or "url"
        value = item.get("value")
        if not value:
            return
        key = (img_type, value)
        if key in seen:
            return
        seen.add(key)
        found.append(item)

    def collect(value, depth=0):
        if depth > 8 or value is None:
            return
        if isinstance(value, str):
            if looks_like_generated_image_url(value):
                add_image({"type": "url", "value": value})
            return
        if isinstance(value, list):
            for item in value:
                collect(item, depth + 1)
            return
        if not isinstance(value, dict):
            return
        if value.get("type") == "image_generation_call":
            result = value.get("result")
            if isinstance(result, str) and result.strip():
                add_image({
                    "type": "b64",
                    "value": result.strip(),
                    "mime_type": value.get("mime_type") or value.get("mimeType") or "image/png",
                })
            else:
                collect(result, depth + 1)
        for key in IMAGE_BASE64_KEY_HINTS:
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                add_image({
                    "type": "b64",
                    "value": item.strip(),
                    "mime_type": value.get("mime_type") or value.get("mimeType") or "image/png",
                })
        for key in IMAGE_OUTPUT_KEY_HINTS:
            item = value.get(key)
            if isinstance(item, str) and looks_like_generated_image_url(item):
                add_image({"type": "url", "value": item})
            else:
                collect(item, depth + 1)
        for key in IMAGE_CONTAINER_KEY_HINTS:
            collect(value.get(key), depth + 1)

    candidates = data.get("candidates") if isinstance(data, dict) else None
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content") or {}
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                inline = part.get("inlineData") or part.get("inline_data") or {}
                if not isinstance(inline, dict):
                    continue
                value = inline.get("data")
                if value:
                    add_image({
                        "type": "b64",
                        "value": value,
                        "mime_type": inline.get("mimeType") or inline.get("mime_type") or "image/png",
                    })

    current = data
    if isinstance(current, dict) and isinstance(current.get("data"), dict) and isinstance(current["data"].get("result"), dict):
        current = current["data"]
    if isinstance(current, dict) and isinstance(current.get("result"), dict):
        for item in current["result"].get("images") or []:
            if not isinstance(item, dict):
                collect(item)
                continue
            url = item.get("url")
            if isinstance(url, list):
                for one in url:
                    collect(one)
            else:
                collect(url)
            collect(item)

    collect(data)
    if isinstance(data, dict) and isinstance(data.get("data"), dict) and isinstance(data["data"].get("data"), dict):
        collect(data["data"]["data"])
    if found:
        return found
    raise HTTPException(status_code=502, detail="无法识别生图接口返回格式")

def extract_image(data):
    try:
        images = extract_images(data)
        if images:
            return images[0]
    except HTTPException:
        pass
    candidates = data.get("candidates") if isinstance(data, dict) else None
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content") or {}
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                inline = part.get("inlineData") or part.get("inline_data") or {}
                if not isinstance(inline, dict):
                    continue
                value = inline.get("data")
                if value:
                    return {
                        "type": "b64",
                        "value": value,
                        "mime_type": inline.get("mimeType") or inline.get("mime_type") or "image/png",
                    }
    if isinstance(data.get("data"), dict) and isinstance(data["data"].get("result"), dict):
        data = data["data"]
    if isinstance(data.get("result"), dict):
        result_images = data["result"].get("images") or []
        if result_images:
            first = result_images[0]
            url = first.get("url")
            if isinstance(url, list) and url:
                return {"type": "url", "value": url[0]}
            if isinstance(url, str) and url:
                return {"type": "url", "value": url}
    flexible = extract_image_flexible(data)
    if flexible:
        return flexible
    if isinstance(data.get("data"), dict) and isinstance(data["data"].get("data"), dict):
        data = data["data"]["data"]
    images = data.get("data") or []
    if not isinstance(images, list) or not images:
        raise HTTPException(status_code=502, detail="生图接口没有返回图片数据")
    first = images[0]
    if first.get("url"):
        return {"type": "url", "value": first["url"]}
    if first.get("b64_json"):
        return {"type": "b64", "value": first["b64_json"]}
    flexible = extract_image_flexible(first)
    if flexible:
        return flexible
    raise HTTPException(status_code=502, detail="无法识别生图接口返回格式")

def extract_task_id(data):
    if data.get("task_id"):
        return str(data["task_id"])
    if data.get("taskId"):
        return str(data["taskId"])
    if data.get("submit_id"):
        return str(data["submit_id"])
    if data.get("video_id"):
        return str(data["video_id"])
    if data.get("videoId"):
        return str(data["videoId"])
    if data.get("id") and str(data.get("id", "")).startswith("task"):
        return str(data["id"])
    nested = data.get("data")
    if isinstance(nested, list) and nested:
        first = nested[0]
        if isinstance(first, dict):
            return extract_task_id(first)
    if isinstance(nested, dict):
        return extract_task_id(nested)
    return None

def extract_task_id_from_text(text):
    value = str(text or "")
    match = re.search(r"(?:task_id|taskId|task id)\s*[=:：]\s*([A-Za-z0-9_.:-]+)", value, re.IGNORECASE)
    return match.group(1) if match else ""

def images_api_unsupported(response):
    text = str(getattr(response, "text", "") or "").lower()
    return "images api is not supported" in text or "not supported for this platform" in text

def responses_image_size_instruction(size: str) -> str:
    """RS 中转多为网页版逆向：结构化 size 参数（tool.size / 顶层 size / --size 尾注）全被无视，
    只有内部模型能“听懂”的自然语言比例要求有效（实测中文明确说横版+比例+禁止正方形可让
    1:1 变成 3:2 横版）。这里生成中英双语的强化指令。"""
    match = re.match(r"^\s*(\d{2,5})\s*[xX*]\s*(\d{2,5})\s*$", str(size or ""))
    if not match:
        return ""
    width, height = int(match.group(1)), int(match.group(2))
    if width <= 0 or height <= 0:
        return ""
    if width == height:
        return "请生成正方形图片（宽高比 1:1）。Generate a SQUARE image (aspect ratio 1:1)."
    from fractions import Fraction
    ratio = Fraction(width, height).limit_denominator(32)
    rw, rh = ratio.numerator, ratio.denominator
    if width > height:
        zh_shape, en_shape = "横版（宽幅）", "LANDSCAPE (wide)"
    else:
        zh_shape, en_shape = "竖版（长幅）", "PORTRAIT (tall)"
    return (
        f"请生成{zh_shape}图片：宽高比 {rw}:{rh}，目标尺寸为宽 {width} × 高 {height} 像素，绝对不要输出正方形（1:1）。"
        f" Generate a {en_shape} image with aspect ratio {rw}:{rh}, target size {width}x{height} pixels (width x height)."
        f" Never output a square 1:1 image. Do not swap width and height."
    )

def responses_proxy_tool_size(size: str) -> str:
    """部分 RS 中转把 image_generation.size 当成 height x width；这里只对 RS 模式做兼容翻转。"""
    match = re.match(r"^\s*(\d{2,5})\s*[xX*]\s*(\d{2,5})\s*$", str(size or ""))
    if not match:
        return str(size or "").strip()
    width, height = match.group(1), match.group(2)
    return f"{height}x{width}" if width != height else f"{width}x{height}"

async def responses_input_image_url(ref) -> str:
    """RS / Responses 的 input_image。
    本机/内网 URL 不能透传（上游拉不到会挂到 Cloudflare 120s 超时/524）。
    本地文件优先上传图床（同视频卡片的 Litterbox/temp.sh 通道）换公网短链——
    几 MB 的 base64 请求体会让部分中转源站处理超时，公网 URL 让请求体和文生图一样小；
    图床不可用时回退内联 base64（Responses 协议两种都支持）。"""
    raw = ref.get("url", "") if isinstance(ref, dict) else ref
    text = str(raw or "").strip()
    if not text:
        return ""
    local_path = text
    if re.match(r"^https?://", text, re.I):
        parsed = urllib.parse.urlsplit(text)
        host = (parsed.hostname or "").lower()
        if host in {"127.0.0.1", "localhost", "::1"} or re.match(r"^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)", host):
            local_path = urllib.parse.unquote(parsed.path or "")
        else:
            return text
    if not output_file_from_url(local_path):
        return ""
    try:
        uploaded = await upload_local_video_to_cloud(local_path)
        url = str((uploaded or {}).get("url") or "")
        if url.startswith(("http://", "https://")):
            return url
    except HTTPException as exc:
        print(f"RS 参考图上传图床失败，回退内联 base64：{exc.detail}")
    except Exception as exc:
        print(f"RS 参考图上传图床异常，回退内联 base64：{exc}")
    data_url = reference_to_data_url({"url": local_path}, max_size=1536)
    return data_url if data_url.startswith("data:") else ""

def responses_no_image_detail(data) -> str:
    if not isinstance(data, dict):
        return ""
    details = []
    error = data.get("error")
    if isinstance(error, dict):
        msg = error.get("message") or error.get("detail") or error.get("code")
        if msg:
            details.append(str(msg))
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        details.append(output_text.strip()[:300])
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "image_generation_call":
                continue
            status = item.get("status")
            if status:
                details.append(f"image_generation_call.status={status}")
            item_error = item.get("error")
            if isinstance(item_error, dict):
                msg = item_error.get("message") or item_error.get("detail") or item_error.get("code")
                if msg:
                    details.append(str(msg))
            elif isinstance(item_error, str) and item_error.strip():
                details.append(item_error.strip())
    joined = "；".join(dict.fromkeys(details))
    return f"RS / Responses 没有返回图片数据{f'：{joined}' if joined else ''}"

def responses_output_text_image(raw):
    """兜底解析：部分 RS 中转不返回标准 image_generation_call，而是把生图结果
    以 output_text 里的 markdown 图片链接（![...](url)）或裸图片 URL 返回。"""
    texts = []
    def collect(value, depth=0):
        if depth > 6 or len(texts) > 40:
            return
        if isinstance(value, str):
            if value.strip():
                texts.append(value)
            return
        if isinstance(value, list):
            for item in value:
                collect(item, depth + 1)
            return
        if isinstance(value, dict):
            for key in ("output", "content", "text", "output_text", "message", "response"):
                if key in value:
                    collect(value[key], depth + 1)
    collect(raw)
    for text in texts:
        match = re.search(r"!\[[^\]]*\]\((https?://[^)\s]+)\)", text)
        if match:
            return {"type": "url", "value": match.group(1)}
        match = re.search(r"https?://[^\s)\"'<>]+\.(?:png|jpe?g|webp|gif)(?:\?[^\s)\"'<>]*)?", text, re.I)
        if match:
            return {"type": "url", "value": match.group(0)}
    return None

def _responses_wrap(url, status_code, payload):
    return httpx.Response(
        status_code,
        headers={"content-type": "application/json"},
        content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        request=httpx.Request("POST", url),
    )

async def post_openai_responses(client, url, headers, body):
    """RS / Responses 请求。图片编辑经常超过 120 秒，非流式请求会被中转前面的
    Cloudflare 读超时掐断（Error 524）。策略按可靠性排序：
    1) background:true 后台任务 + 轮询 GET /v1/responses/{id}（每个请求都秒回，彻底绕开超时）；
    2) 后台模式被拒（4xx 参数类错误）→ SSE 流式；
    3) 流式也被拒 → 非流式直接请求。
    5xx/超时一律不自动重试，避免上游已开始生成后重复扣费。"""
    bg_body = dict(body)
    bg_body["background"] = True
    try:
        resp = await client.post(url, headers=headers, json=bg_body)
    except httpx.HTTPError as e:
        print(f"RS background 请求传输失败，改走流式：{e}")
        return await post_openai_responses_stream(client, url, headers, body)
    if resp.status_code in RESPONSES_REJECT_STATUSES:
        print(f"RS background 模式被拒（{resp.status_code}），改走流式：{resp.text[:200]}")
        return await post_openai_responses_stream(client, url, headers, body)
    if resp.status_code >= 400:
        if resp.status_code == 524:
            return _responses_wrap(url, 502, {"error": {"message": (
                "中转在 background 模式下仍然 524 超时：该渠道对 /v1/responses 的 background/stream 都不透传，"
                "无法完成超过 120 秒的图片编辑。请换支持 Responses 透传的渠道。上游原文："
                f"{resp.text[:300]}"
            )}})
        return resp
    try:
        data = resp.json()
    except ValueError:
        return resp
    status = str((data or {}).get("status") or "").lower()
    rid = str((data or {}).get("id") or "").strip()
    if status not in {"queued", "in_progress", "processing", "pending", "running"} or not rid:
        return resp  # 中转忽略 background 直接同步返回了结果（或未知结构），交给下游解析
    # 轮询后台任务
    retrieve_url = f"{url.rstrip('/')}/{urllib.parse.quote(rid)}"
    deadline = time.monotonic() + RESPONSES_POLL_MAX_SECONDS
    transient_failures = 0
    while time.monotonic() < deadline:
        await asyncio.sleep(RESPONSES_POLL_INTERVAL)
        try:
            poll = await client.get(retrieve_url, headers=headers)
        except httpx.HTTPError as e:
            transient_failures += 1
            if transient_failures > 5:
                return _responses_wrap(url, 502, {"error": {"message": f"RS 后台任务轮询连续失败：{e}（任务 id={rid}）"}})
            continue
        if poll.status_code >= 400:
            transient_failures += 1
            if transient_failures > 5:
                return _responses_wrap(url, 502, {"error": {"message": f"RS 后台任务轮询失败（{poll.status_code}）：{poll.text[:200]}（任务 id={rid}）"}})
            continue
        transient_failures = 0
        try:
            data = poll.json()
        except ValueError:
            continue
        status = str((data or {}).get("status") or "").lower()
        if status == "completed":
            return _responses_wrap(url, 200, data)
        if status in {"failed", "cancelled", "incomplete"}:
            return _responses_wrap(url, 502, data)
    return _responses_wrap(url, 502, {"error": {"message": f"RS 后台任务超过 {int(RESPONSES_POLL_MAX_SECONDS)}s 仍未完成（任务 id={rid}）"}})

async def post_openai_responses_stream(client, url, headers, body):
    """RS / Responses 的 SSE 流式请求：流式从一开始就持续有事件字节返回，
    不会触发中转的 Cloudflare 120s 读超时。收到 response.completed 后
    把完整 response 对象包装成普通 httpx.Response，下游解析逻辑不变。"""
    request = httpx.Request("POST", url)

    def wrap(status_code, payload):
        return _responses_wrap(url, status_code, payload)

    stream_body = dict(body)
    stream_body["stream"] = True
    try:
        async with client.stream("POST", url, headers=headers, json=stream_body) as resp:
            ctype = (resp.headers.get("content-type") or "").lower()
            if resp.status_code >= 400 or "text/event-stream" not in ctype:
                content = await resp.aread()
                # 个别中转不支持 responses 流式（对 stream 参数直接报错）→ 回退一次非流式。
                # 仅对“请求被拒绝”类状态码回退，5xx/超时不重试，避免上游已开始生成后重复扣费。
                if resp.status_code in {400, 404, 405, 415, 422}:
                    print(f"RS 流式请求被拒（{resp.status_code}），回退非流式：{content[:200]!r}")
                    return await client.post(url, headers=headers, json=body)
                return httpx.Response(resp.status_code, headers=resp.headers, content=content, request=request)
            completed = None
            error_payload = None
            partial_b64 = ""
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    event = json.loads(chunk)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                etype = str(event.get("type") or "")
                if etype in {"response.completed", "response.incomplete"} and isinstance(event.get("response"), dict):
                    completed = event["response"]
                elif etype == "response.failed":
                    failed = event.get("response")
                    error_payload = failed if isinstance(failed, dict) else {"error": {"message": "response.failed"}}
                elif etype == "error":
                    message = event.get("message") or event.get("error") or chunk[:300]
                    error_payload = {"error": {"message": str(message)}}
                elif etype.endswith("partial_image") and isinstance(event.get("partial_image_b64"), str):
                    partial_b64 = event["partial_image_b64"]
            if completed is None and error_payload is None and partial_b64:
                # 流被提前掐断但已收到分片图：用最后一张分片兜底
                completed = {"output": [{"type": "image_generation_call", "status": "completed", "result": partial_b64}]}
            if completed is not None:
                return wrap(200, completed)
            return wrap(502, error_payload or {"error": {"message": "RS 流式响应结束但没有 response.completed 事件"}})
    except httpx.HTTPError as e:
        print(f"RS 流式请求传输失败，回退非流式：{e}")
        return await client.post(url, headers=headers, json=body)

def is_yuli_provider(provider):
    # 玉玉API（yuli.host）的视频接口走自有格式（/v1/video/create + /v1/video/query），
    # 与通用 OpenAI /v1/videos/generations 不同，需单独识别。
    base_url = str((provider or {}).get("base_url") or "").lower()
    return "yuli.host" in base_url

def is_agnes_provider(provider, model=""):
    base_url = str((provider or {}).get("base_url") or "").lower()
    model_id = str(model or "").strip().lower()
    return "apihub.agnes-ai.com" in base_url or model_id.startswith("agnes-video-")

def avatar_platform_for_provider(provider) -> str:
    if not provider:
        return ""
    if is_apimart_provider(provider):
        return "apimart"
    if is_volcengine_provider(provider):
        return "volcengine"
    return ""

def provider_supports_avatar(provider) -> bool:
    return avatar_platform_for_provider(provider) in AVATAR_SUPPORTED_PLATFORMS

async def jimeng_pending_exception_handler(request: Request, exc: JimengPendingError):
    # 轮询超时但任务还在云端排队：返回 202 + submit_id，让前端保持「排队中」卡片并续查
    return JSONResponse(status_code=202, content=jimeng_pending_payload(exc))

def image_task_url_for_provider(provider, task_id):
    base_url = (provider.get("base_url") if provider else AI_BASE_URL).rstrip("/")
    # 异步生图（openai-video-proxy）模式优先于 apimart 协议判断：
    # 提交走 /v1/videos，轮询必须走 /v1/videos/{id}；否则 protocol=apimart 的平台会错走 /v1/tasks/{id}
    if normalize_image_request_mode((provider or {}).get("image_request_mode")) == "openai-video-proxy":
        return f"{base_url}/videos/{task_id}" if base_url.endswith("/v1") else f"{base_url}/v1/videos/{task_id}"
    if is_apimart_provider(provider):
        return f"{base_url}/tasks/{task_id}" if base_url.endswith("/v1") else f"{base_url}/v1/tasks/{task_id}"
    return f"{base_url}/images/tasks/{task_id}" if base_url.endswith("/v1") else f"{base_url}/v1/images/tasks/{task_id}"

def image_task_data(payload):
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}

def image_task_status(payload):
    task_data = image_task_data(payload)
    return str(task_data.get("status") or task_data.get("task_status") or "").upper()

def image_task_fail_reason(payload):
    task_data = image_task_data(payload)
    error = task_data.get("error") if isinstance(task_data.get("error"), dict) else {}
    return task_data.get("fail_reason") or task_data.get("message") or error.get("message") or (payload.get("message") if isinstance(payload, dict) else "") or "生图任务失败"

async def httpx_request_with_transient_retries(client, method, url, attempts=2, retry_delay=1.2, **kwargs):
    attempts = max(1, int(attempts or 1))
    last_exc = None
    retry_statuses = {502, 503, 504, 520, 522, 524}
    for attempt in range(attempts):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code in retry_statuses and attempt + 1 < attempts:
                await asyncio.sleep(retry_delay * (attempt + 1))
                continue
            return response
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
            last_exc = exc
            if attempt + 1 >= attempts:
                raise
            print(f"[HTTPX-RETRY] {method} {url} transient error: {exc}; retry {attempt + 2}/{attempts}", flush=True)
            await asyncio.sleep(retry_delay * (attempt + 1))
    if last_exc:
        raise last_exc
    raise httpx.HTTPError(f"请求失败：{method} {url}")

async def fetch_image_task_payload(client, task_id, provider=None):
    task_url = image_task_url_for_provider(provider, task_id)
    response = await httpx_request_with_transient_retries(
        client,
        "GET",
        task_url,
        attempts=3,
        headers=api_headers(provider=provider),
    )
    response.raise_for_status()
    return response.json()

async def wait_for_image_task(client, task_id, provider=None):
    is_apimart = is_apimart_provider(provider)
    timeout = APIMART_IMAGE_TASK_TIMEOUT if is_apimart else IMAGE_TASK_TIMEOUT
    interval = APIMART_IMAGE_POLL_INTERVAL if is_apimart else IMAGE_POLL_INTERVAL
    initial_delay = APIMART_IMAGE_INITIAL_POLL_DELAY if is_apimart else 0
    deadline = time.monotonic() + timeout
    last_payload = {}
    while time.monotonic() < deadline:
        if initial_delay:
            await asyncio.sleep(min(initial_delay, max(0.0, deadline - time.monotonic())))
            initial_delay = 0
            if time.monotonic() >= deadline:
                break
        last_payload = await fetch_image_task_payload(client, task_id, provider)
        status = image_task_status(last_payload)
        if not status:
            try:
                if extract_image(last_payload):
                    return last_payload
            except HTTPException:
                pass
        if status in IMAGE_TASK_SUCCESS_STATUSES:
            return last_payload
        if status in IMAGE_TASK_FAILED_STATUSES:
            raise HTTPException(status_code=502, detail=f"生图任务失败：{image_task_fail_reason(last_payload)}")
        await asyncio.sleep(min(interval, max(0.0, deadline - time.monotonic())))
    raw_text = json.dumps(last_payload, ensure_ascii=False)[:800] if last_payload else ""
    extra = f"，最后响应：{raw_text}" if raw_text else ""
    raise HTTPException(status_code=504, detail=f"生图任务超时（已等待 {int(timeout)} 秒），task_id={task_id}{extra}")
