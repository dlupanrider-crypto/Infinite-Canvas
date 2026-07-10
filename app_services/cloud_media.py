"""Cloud media references, uploads, signing, and persisted outputs."""

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


CLOUD_MEDIA_EXPORTS = (
    'valid_video_image_input',
    'valid_apimart_video_image_input',
    'apply_trusted_asset_prompt_index',
    'public_base_url',
    'public_media_url_suffix',
    'local_asset_public_url',
    'openai_video_proxy_public_reference_url',
    'normalize_apimart_video_reference',
    'apimart_video_reference_error',
    'apimart_video_duration',
    'apimart_veo31_duration',
    'is_apimart_veo31_model',
    'apimart_veo31_model',
    'apimart_veo31_aspect',
    'apimart_veo31_resolution',
    'apimart_upload_file_payload',
    'invalid_video_image_preview',
    'extract_apimart_asset_url',
    'apimart_upload_payload_from_bytes',
    'apimart_upload_raw_file_payload',
    'is_transient_tls_error',
    'apimart_upload_post',
    'upload_image_for_apimart',
    'upload_video_for_apimart',
    'upload_audio_for_apimart',
    'upload_media_for_apimart',
    'apimart_avatar_asset_type',
    'extract_apimart_avatar_asset_uri',
    'submit_apimart_avatar_asset',
    'check_apimart_avatar_task',
    '_volc_hmac',
    'volcengine_sign_v4_headers',
    'volcengine_ark_asset_call',
    'volcengine_ensure_asset_group',
    'submit_volcengine_avatar_asset',
    'check_volcengine_avatar_task',
    'volcengine_public_asset_url',
    'local_media_path_for_cloud_upload',
    'local_video_path_for_cloud_upload',
    'upload_video_to_litterbox',
    'upload_video_to_temp_sh',
    'upload_local_video_to_cloud',
    'upload_local_video_to_temp_sh',
    'save_ai_image_to_output',
    'image_output_meta',
    'save_remote_video_to_output',
    'parse_size_pair',
    'chat_prompt_size_override',
)


def configure_cloud_media(namespace: dict[str, Any]) -> None:
    required = {
        'APIMART_UPLOAD_RETRY_ATTEMPTS',
        'AVATAR_TASK_DONE_STATUSES',
        'AVATAR_TASK_FAIL_STATUSES',
        'CHAT_RATIO_SIZE_OPTIONS',
        'PUBLIC_BASE_URL',
        'PUBLIC_MEDIA_BASE_URL',
        'VIDEO_POLL_TIMEOUT',
        'VOLCENGINE_ARK_ASSET_HOST',
        'VOLCENGINE_ARK_ASSET_REGION',
        'VOLCENGINE_ARK_ASSET_SERVICE',
        'VOLCENGINE_ARK_ASSET_VERSION',
        'VOLCENGINE_ARK_ASSET_VERSION',
        'api_headers',
        'content_type_for_path',
        'output_file_from_url',
        'output_path_for',
        'output_url_for',
        'read_api_env_value',
        'rewrite_runninghub_file_url',
        'video_api_root',
        'volcengine_access_key_value',
        'volcengine_secret_key_value',
    }
    missing = sorted(required - namespace.keys())
    if missing:
        raise RuntimeError(f"Cloud Media missing dependencies: {', '.join(missing)}")
    globals().update({name: namespace[name] for name in required})


def export_cloud_media(target: dict[str, Any]) -> None:
    for name in CLOUD_MEDIA_EXPORTS:
        target[name] = globals()[name]


def valid_video_image_input(value: str) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    return (
        value.startswith("http://") or
        value.startswith("https://") or
        value.startswith("asset://") or
        (value.startswith("data:image/") and ";base64," in value)
    )

def valid_apimart_video_image_input(value: str) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    return value.startswith("http://") or value.startswith("https://") or value.startswith("asset://")

def apply_trusted_asset_prompt_index(prompt: str, image_count: int, video_count: int, audio_count: int) -> str:
    """可信素材模式下，按平台规则在 prompt 里补「图片N/视频N/音频N」索引。
    若用户已手动引用了某类素材（如已写「图片1」），则不重复追加该类。"""
    text = str(prompt or "").strip()
    segments = []
    for label, count in (("图片", image_count), ("视频", video_count), ("音频", audio_count)):
        if count <= 0:
            continue
        if any(f"{label}{i}" in text for i in range(1, count + 1)):
            continue
        segments.append("、".join(f"{label}{i}" for i in range(1, count + 1)))
    if not segments:
        return text
    hint = "参考素材：" + "，".join(segments) + "。"
    return f"{text}\n{hint}" if text else hint

def public_base_url() -> str:
    # 实时读 API/.env 且文件优先：公网隧道重启后地址会变，隧道脚本只改 .env；
    # 启动时 load_env_file 会把旧值复制进 os.environ，若 env 优先会永远读到过期地址
    value = (
        read_api_env_value("PUBLIC_MEDIA_BASE_URL") or
        os.getenv("PUBLIC_MEDIA_BASE_URL") or
        PUBLIC_MEDIA_BASE_URL or
        read_api_env_value("PUBLIC_BASE_URL") or
        os.getenv("PUBLIC_BASE_URL") or
        PUBLIC_BASE_URL or
        ""
    ).strip().rstrip("/")
    if value and re.match(r"^https?://", value, re.I):
        return value
    return ""

def public_media_url_suffix() -> str:
    token = str(os.getenv("PUBLIC_MEDIA_TOKEN") or "").strip()
    return f"?token={urllib.parse.quote(token)}" if token else ""

def local_asset_public_url(value: str) -> str:
    text = str(value or "").strip()
    if not text.startswith(("/output/", "/assets/")):
        return ""
    if not output_file_from_url(text):
        return ""
    base = public_base_url()
    if not base:
        return ""
    return f"{base}{urllib.parse.quote(text, safe='/:?&=%#.-_~')}{public_media_url_suffix()}"

async def openai_video_proxy_public_reference_url(ref) -> str:
    """异步生图（openai-video-proxy）的参考图公网化。
    不走公网隧道（暴露本机服务风险高）：本地文件上传图床（Litterbox/temp.sh，72h 短链），
    与 RS 模式同一通道；真正的公网 URL 原样透传；若手动配置了 PUBLIC_MEDIA_BASE_URL 则作为兜底。"""
    raw = ref.get("url", "") if isinstance(ref, dict) else ref
    text = str(raw or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlsplit(text)
    local_path = ""
    if parsed.scheme in {"http", "https"}:
        host = (parsed.hostname or "").lower()
        if host in {"127.0.0.1", "localhost", "::1"} or re.match(r"^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)", host):
            local_path = urllib.parse.unquote(parsed.path or "")
        else:
            return text
    elif text.startswith(("/output/", "/assets/")):
        local_path = text
    if local_path and output_file_from_url(local_path):
        upload_error = ""
        try:
            uploaded = await upload_local_video_to_cloud(local_path)
            url = str((uploaded or {}).get("url") or "")
            if url.startswith(("http://", "https://")):
                return url
        except HTTPException as exc:
            upload_error = str(exc.detail)
        public_url = local_asset_public_url(local_path)
        if public_url:
            return public_url
        raise HTTPException(
            status_code=400,
            detail=f"参考图上传图床失败，无法转成公网 URL：{upload_error[:200] or '未知错误'}。请检查网络后重试。"
        )
    raise HTTPException(status_code=400, detail=f"参考图不是公网 URL，无法传给上游：{text[:160]}")

def normalize_apimart_video_reference(value: str) -> str:
    text = str(value or "").strip()
    if valid_apimart_video_image_input(text):
        return text
    return local_asset_public_url(text)

def apimart_video_reference_error(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "空的视频地址"
    if text.startswith(("/output/", "/assets/")):
        if not output_file_from_url(text):
            return "这是本地画布文件路径，但后端没有找到对应文件，请重新上传视频后再试。"
        return (
            "这是本地画布文件，APIMart 无法访问 127.0.0.1/局域网路径；"
            "请在 API/.env 配置 PUBLIC_MEDIA_BASE_URL 或 PUBLIC_BASE_URL 为可公网访问的媒体地址（例如内网穿透 HTTPS 地址），"
            "或改用公网 http/https 视频 URL、审核后的 asset:// 地址。"
        )
    if text.startswith("data:") or text.startswith("blob:") or text.startswith("file:"):
        return (
            "APIMart 的 video_urls 不支持 data/blob/file 地址；"
            "请改用公网 http/https 视频 URL，或审核后的 asset:// 地址。"
        )
    return "APIMart 的 video_urls 只支持公网 http/https URL 或 asset:// 私域素材 URL。"

def apimart_video_duration(duration) -> int:
    try:
        value = int(duration)
    except Exception:
        value = 5
    return max(4, min(15, value))

def apimart_veo31_duration(duration) -> int:
    try:
        value = int(duration)
    except Exception:
        value = 8
    # APIMart VEO 3.1 currently accepts a narrower duration window than
    # the generic UI. Clamp instead of silently forcing every request to 8s.
    return max(4, min(8, value))

def is_apimart_veo31_model(model: str) -> bool:
    return str(model or "").strip().lower().startswith("veo3.1")

def apimart_veo31_model(model: str) -> str:
    value = str(model or "").strip().lower()
    aliases = {
        "veo3.1": "veo3.1-fast",
        "veo3.1-pro": "veo3.1-quality",
        "veo3.1-preview": "veo3.1-fast",
    }
    value = aliases.get(value, value or "veo3.1-fast")
    allowed = {"veo3.1-fast", "veo3.1-quality", "veo3.1-lite"}
    return value if value in allowed else "veo3.1-fast"

def apimart_veo31_aspect(aspect: str) -> str:
    value = str(aspect or "16:9").strip()
    return value if value in {"16:9", "9:16"} else "16:9"

def apimart_veo31_resolution(resolution: str) -> str:
    value = str(resolution or "").strip().lower()
    aliases = {"": "720p", "auto": "720p", "480p": "720p", "780p": "720p", "1080": "1080p", "4k": "4k"}
    value = aliases.get(value, value)
    return value if value in {"720p", "1080p", "4k"} else "720p"

def apimart_upload_file_payload(path: str):
    """Return (filename, bytes, content_type), keeping APIMart VEO images under the documented 10MB limit."""
    max_bytes = 9_500_000
    size = os.path.getsize(path)
    if size <= max_bytes:
        with open(path, "rb") as fh:
            return os.path.basename(path), fh.read(), content_type_for_path(path)
    with Image.open(path) as img:
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        quality = 92
        while quality >= 62:
            buf = BytesIO()
            bg.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
            if len(data) <= max_bytes:
                name = os.path.splitext(os.path.basename(path))[0] + ".jpg"
                return name, data, "image/jpeg"
            quality -= 8
    raise ValueError("图片超过 10MB，且压缩后仍无法满足 VEO3.1 图片限制")

def invalid_video_image_preview(value: str) -> str:
    text = str(value or "")
    if text.startswith("data:"):
        return text.split(";base64,", 1)[0] + ";base64,..."
    return text[:120]

def extract_apimart_asset_url(payload):
    if isinstance(payload, list):
        for item in payload:
            found = extract_apimart_asset_url(item)
            if found:
                return found
        return ""
    if not isinstance(payload, dict):
        return ""
    url_keys = ("url", "asset_url", "assetUrl", "uri", "file_url", "fileUrl")
    for key in url_keys:
        value = str(payload.get(key) or "").strip()
        if valid_apimart_video_image_input(value):
            return value
    id_keys = ("asset_id", "assetId", "file_id", "fileId", "id")
    for key in id_keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value if value.startswith("asset://") else f"asset://{value}"
    for key in ("data", "file", "asset", "result"):
        found = extract_apimart_asset_url(payload.get(key))
        if found:
            return found
    return ""

def apimart_upload_payload_from_bytes(data: bytes, mime: str, name_hint: str = "image"):
    """把内存中的图片字节按 APIMart 的 10MB 限制压缩为可上传 payload。"""
    max_bytes = 9_500_000
    ext = mimetypes.guess_extension(mime or "image/png") or ".png"
    if len(data) <= max_bytes and (mime or "").lower() in ("image/png", "image/jpeg", "image/webp"):
        return f"{name_hint}{ext}", data, (mime or "image/png")
    with Image.open(BytesIO(data)) as img:
        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        if has_alpha:
            base = img.convert("RGBA")
            bg = Image.new("RGB", base.size, (255, 255, 255))
            bg.paste(base, mask=base.split()[-1])
            target = bg
        else:
            target = img.convert("RGB")
        quality = 92
        while quality >= 62:
            buf = BytesIO()
            target.save(buf, format="JPEG", quality=quality, optimize=True)
            payload = buf.getvalue()
            if len(payload) <= max_bytes:
                return f"{name_hint}.jpg", payload, "image/jpeg"
            quality -= 8
    raise ValueError("data URL 图片超过 10MB，且压缩后仍无法满足 APIMart 限制")

def apimart_upload_raw_file_payload(path: str):
    with open(path, "rb") as fh:
        return os.path.basename(path), fh.read(), content_type_for_path(path)

def is_transient_tls_error(exc) -> bool:
    """识别可重试的瞬时 TLS/传输错误，如 SSLV3_ALERT_BAD_RECORD_MAC、EOF occurred 等，
    这类错误多由连接池中被污染/复用坏掉的 TLS 连接引起，换新连接重试通常即可成功。"""
    if isinstance(exc, httpx.TransportError):
        return True
    msg = f"{type(exc).__name__}: {exc}".upper()
    return any(token in msg for token in (
        "SSL", "BAD RECORD MAC", "EOF OCCURRED", "DECRYPTION FAILED", "WRONG VERSION NUMBER",
    ))

async def apimart_upload_post(client, upload_url, headers, file_tuple, timeout=60):
    """上传文件到 APIMart，对瞬时 TLS 错误自动重试；重试时改用全新连接，避免复用坏掉的 TLS 连接。
    file_tuple 形如 (filename, content_bytes, content_type)，content 为已读入内存的 bytes，可跨重试复用。"""
    last_exc = None
    for attempt in range(APIMART_UPLOAD_RETRY_ATTEMPTS):
        files = {"file": file_tuple}
        try:
            if attempt == 0:
                return await client.post(upload_url, headers=headers, files=files, timeout=timeout)
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=20.0, read=max(120.0, float(timeout)), write=120.0, pool=20.0),
                follow_redirects=True,
            ) as fresh:
                return await fresh.post(upload_url, headers=headers, files=files, timeout=timeout)
        except Exception as e:
            if not is_transient_tls_error(e) or attempt == APIMART_UPLOAD_RETRY_ATTEMPTS - 1:
                raise
            last_exc = e
            print(f"APIMart 上传遇到瞬时 TLS 错误，换新连接重试（第 {attempt + 1} 次）：{e}")
            await asyncio.sleep(0.6 * (attempt + 1))
    if last_exc:
        raise last_exc

async def upload_image_for_apimart(client, provider, ref_url: str) -> str:
    """把本地图片转成上游可接受的输入。
    按 APIMart 文档上传到 /v1/uploads/images，拿到可用于生成接口的 http/https URL。
    绝不把 /output/* 或 /assets/* 这类本地路径直接传给上游。
    返回上游可用 URL；返回值以 "ERR:" 开头表示具体失败原因（供前端展示）。"""
    ref_url = str(ref_url or "").strip()
    if not ref_url:
        return "ERR:空地址"
    # 已经是网络 URL 或 asset:// → 直接可用，无需上传
    if ref_url.startswith("http://") or ref_url.startswith("https://") or ref_url.startswith("asset://"):
        return ref_url
    base_url = video_api_root(provider)
    upload_url = f"{base_url}/v1/uploads/images"
    # data URL: 解码后直接上传到 APIMart
    if ref_url.startswith("data:"):
        try:
            if ";base64," not in ref_url:
                return "ERR:不支持的 data URL（缺少 base64 段）"
            header, encoded = ref_url.split(";base64,", 1)
            mime = header.split(":", 1)[1].split(";", 1)[0] if ":" in header else "image/png"
            raw = base64.b64decode(encoded)
            filename, content, ct = apimart_upload_payload_from_bytes(raw, mime, name_hint="canvas_image")
            resp = await apimart_upload_post(client, upload_url, api_headers(json_body=False, provider=provider), (filename, content, ct), timeout=60)
            if resp.status_code in (200, 201):
                rj = resp.json()
                url = extract_apimart_asset_url(rj)
                if valid_apimart_video_image_input(url):
                    return url
                print(f"APIMart 上传 data URL 返回中未找到可用 asset/url: {str(rj)[:300]}")
                return "ERR:APIMart 上传响应未包含可用 URL"
            print(f"APIMart 上传 data URL 失败 ({resp.status_code}): {resp.text[:300]}")
            return f"ERR:APIMart 上传失败({resp.status_code})"
        except ValueError as e:
            return f"ERR:{e}"
        except Exception as e:
            print(f"APIMart 上传 data URL 异常: {e}")
            return f"ERR:上传异常 {e}"
    # 本地 /output/ 或 /assets/ 路径：先确认文件存在再上传
    if ref_url.startswith("/output/") or ref_url.startswith("/assets/"):
        path = output_file_from_url(ref_url)
        if not path:
            print(f"APIMart 上传跳过：本地文件不存在 {ref_url}")
            return "ERR:本地文件不存在或已被删除"
        try:
            filename, content, ct = apimart_upload_file_payload(path)
            resp = await apimart_upload_post(client, upload_url, api_headers(json_body=False, provider=provider), (filename, content, ct), timeout=60)
            if resp.status_code in (200, 201):
                rj = resp.json()
                url = extract_apimart_asset_url(rj)
                if valid_apimart_video_image_input(url):
                    return url
                print(f"APIMart 文件上传返回中未找到可用 asset/url: {str(rj)[:300]}")
                return "ERR:APIMart 上传响应未包含可用 URL"
            print(f"APIMart 文件上传失败 ({resp.status_code}): {resp.text[:300]}")
            return f"ERR:APIMart 上传失败({resp.status_code})"
        except ValueError as e:
            return f"ERR:{e}"
        except Exception as e:
            print(f"APIMart 文件上传异常: {e}")
            return f"ERR:上传异常 {e}"
    return "ERR:不支持的图片来源（仅支持 http/https/asset/data 或本地 /output/ /assets/ 路径）"

async def upload_video_for_apimart(client, provider, ref_url: str) -> str:
    """尽力把本地参考视频转换为 APIMart 可接受的 http/https 或 asset:// URL。
    文档只公开了图片上传；如果视频上传端点不可用，会回退到 PUBLIC_BASE_URL 方案。"""
    ref_url = str(ref_url or "").strip()
    if not ref_url:
        return "ERR:空地址"
    if valid_apimart_video_image_input(ref_url):
        return ref_url
    public_url = local_asset_public_url(ref_url)
    if public_url:
        return public_url
    if not (ref_url.startswith("/output/") or ref_url.startswith("/assets/")):
        return f"ERR:{apimart_video_reference_error(ref_url)}"
    path = output_file_from_url(ref_url)
    if not path:
        return "ERR:本地视频不存在或已被删除"
    ct = content_type_for_path(path)
    if not ct.startswith("video/"):
        return "ERR:参考视频不是可识别的视频文件"
    if str(os.getenv("APIMART_TRY_VIDEO_UPLOAD") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        return f"ERR:{apimart_video_reference_error(ref_url)}"
    base_url = video_api_root(provider)
    filename, content, content_type = apimart_upload_raw_file_payload(path)
    upload_paths = ("/v1/uploads/videos", "/v1/uploads/files", "/v1/uploads/images")
    last_error = ""
    for upload_path in upload_paths:
        upload_url = f"{base_url}{upload_path}"
        try:
            files = {"file": (filename, content, content_type)}
            resp = await client.post(upload_url, headers=api_headers(json_body=False, provider=provider), files=files, timeout=180)
            if resp.status_code in (200, 201):
                rj = resp.json()
                url = extract_apimart_asset_url(rj)
                if valid_apimart_video_image_input(url):
                    return url
                last_error = "上传响应未包含可用 URL"
                print(f"APIMart 视频上传返回中未找到可用 asset/url ({upload_path}): {str(rj)[:300]}")
                continue
            last_error = f"{upload_path} 返回 {resp.status_code}: {resp.text[:200]}"
            print(f"APIMart 视频上传失败 {last_error}")
        except Exception as e:
            last_error = f"{upload_path} 异常：{e}"
            print(f"APIMart 视频上传异常: {last_error}")
    return f"ERR:APIMart 未提供可用的视频文件上传入口（{last_error}）。请配置 PUBLIC_BASE_URL，或使用公网 http/https / asset:// 视频地址。"

async def upload_audio_for_apimart(client, provider, ref_url: str) -> str:
    """把本地参考音频转换为 APIMart 可接受的 http/https 或 asset:// URL。
    优先用公网地址（PUBLIC_BASE_URL），否则尝试上传到 APIMart 文件端点。
    返回值以 "ERR:" 开头表示失败原因。"""
    ref_url = str(ref_url or "").strip()
    if not ref_url:
        return "ERR:空地址"
    if valid_apimart_video_image_input(ref_url):
        return ref_url
    public_url = local_asset_public_url(ref_url)
    if public_url:
        return public_url
    base_url = video_api_root(provider)
    upload_paths = ("/v1/uploads/audios", "/v1/uploads/files", "/v1/uploads/images")
    last_error = ""
    if ref_url.startswith("data:"):
        if ";base64," not in ref_url:
            return "ERR:不支持的 data URL（缺少 base64 段）"
        header, encoded = ref_url.split(";base64,", 1)
        mime = header.split(":", 1)[1].split(";", 1)[0] if ":" in header else "audio/mpeg"
        try:
            raw = base64.b64decode(encoded)
        except Exception as exc:
            return f"ERR:音频 data URL 解码失败：{exc}"
        ext = mimetypes.guess_extension(mime) or ".mp3"
        filename, content, content_type = (f"canvas_audio{ext}", raw, mime or "audio/mpeg")
    elif ref_url.startswith("/output/") or ref_url.startswith("/assets/"):
        path = output_file_from_url(ref_url)
        if not path:
            return "ERR:本地音频不存在或已被删除"
        ct = content_type_for_path(path)
        if not ct.startswith("audio/"):
            return "ERR:参考音频不是可识别的音频文件"
        filename, content, content_type = apimart_upload_raw_file_payload(path)
    else:
        return f"ERR:{apimart_video_reference_error(ref_url)}"
    for upload_path in upload_paths:
        upload_url = f"{base_url}{upload_path}"
        try:
            files = {"file": (filename, content, content_type)}
            resp = await client.post(upload_url, headers=api_headers(json_body=False, provider=provider), files=files, timeout=180)
            if resp.status_code in (200, 201):
                rj = resp.json()
                url = extract_apimart_asset_url(rj)
                if valid_apimart_video_image_input(url):
                    return url
                last_error = "上传响应未包含可用 URL"
                continue
            last_error = f"{upload_path} 返回 {resp.status_code}: {resp.text[:200]}"
        except Exception as exc:
            last_error = f"{upload_path} 异常：{exc}"
    return f"ERR:APIMart 未提供可用的音频文件上传入口（{last_error}）。请配置 PUBLIC_BASE_URL，或使用公网 http/https / asset:// 音频地址。"

async def upload_media_for_apimart(client, provider, ref_url: str, kind: str) -> str:
    """按 kind 分派到对应的 APIMart 上传器，拿回上游可用的 http/https/asset:// URL。"""
    if kind == "video":
        return await upload_video_for_apimart(client, provider, ref_url)
    if kind == "audio":
        return await upload_audio_for_apimart(client, provider, ref_url)
    return await upload_image_for_apimart(client, provider, ref_url)

def apimart_avatar_asset_type(kind: str) -> str:
    return {"video": "Video", "audio": "Audio"}.get(str(kind or "").lower(), "Image")

def extract_apimart_avatar_asset_uri(payload) -> str:
    """从 /v1/tasks 审核结果里取出 asset://<id> 形式的可信素材 URI。"""
    if isinstance(payload, list):
        for item in payload:
            found = extract_apimart_avatar_asset_uri(item)
            if found:
                return found
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("asset_url", "assetUrl", "uri", "url"):
        value = str(payload.get(key) or "").strip()
        if value.startswith("asset://"):
            return value
    for key in ("usable_assets", "assets", "result", "data"):
        found = extract_apimart_avatar_asset_uri(payload.get(key))
        if found:
            return found
    asset_id = str(payload.get("asset_id") or payload.get("assetId") or "").strip()
    if asset_id:
        return f"asset://{asset_id}"
    return ""

async def submit_apimart_avatar_asset(provider, public_url: str, name: str, kind: str, project_name: str = "default", group_name: str = "") -> str:
    """把一个公网可访问的素材提交到 APIMart private-avatar 审核，立即返回任务 ID（不阻塞轮询）。"""
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} 未配置 Base URL")
    register_url = f"{base_url}/v1/seedance2/private-avatar"
    body = {
        "project_name": str(project_name or "default").strip() or "default",
        "asset_type": apimart_avatar_asset_type(kind),
        "group": {"name": (group_name or name or "数字人素材")[:60]},
        "assets": [{"url": public_url, "name": (name or "asset")[:60]}],
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(register_url, headers=api_headers(provider=provider), json=body, timeout=120)
        if resp.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail=f"APIMart 数字人注册失败（{resp.status_code}）：{resp.text[:300]}")
        data = resp.json()
        task = data.get("data") if isinstance(data.get("data"), dict) else data
        task_id = str(task.get("id") or task.get("task_id") or "").strip()
        if not task_id:
            raise HTTPException(status_code=502, detail=f"APIMart 数字人注册返回中未找到任务 ID：{str(data)[:300]}")
        return task_id

async def check_apimart_avatar_task(provider, task_id: str) -> Dict[str, Any]:
    """查询一次 APIMart 审核任务。返回 {status: Active/Processing/Failed, asset_uri, detail}。"""
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} 未配置 Base URL")
    task_url = f"{base_url}/v1/tasks/{task_id}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(task_url, headers=api_headers(provider=provider), timeout=60)
        if resp.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail=f"查询审核状态失败（{resp.status_code}）：{resp.text[:200]}")
        payload = resp.json()
    node = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    status = str(node.get("status") or "").strip().lower()
    if status in AVATAR_TASK_DONE_STATUSES:
        asset_uri = extract_apimart_avatar_asset_uri(payload)
        if not asset_uri:
            return {"status": "Failed", "asset_uri": "", "detail": "审核完成，但未返回可用的 asset:// 地址（可能部分素材被拒）。"}
        return {"status": "Active", "asset_uri": asset_uri, "detail": ""}
    if status in AVATAR_TASK_FAIL_STATUSES:
        return {"status": "Failed", "asset_uri": "", "detail": f"审核未通过（{status}）。"}
    return {"status": "Processing", "asset_uri": "", "detail": "审核中"}

def _volc_hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

def volcengine_sign_v4_headers(ak: str, sk: str, action: str, body_str: str,
                               service: str = None,
                               region: str = None,
                               version: str = None,
                               host: str = None) -> Dict[str, str]:
    service = service or VOLCENGINE_ARK_ASSET_SERVICE
    region = region or VOLCENGINE_ARK_ASSET_REGION
    version = version or VOLCENGINE_ARK_ASSET_VERSION
    host = host or VOLCENGINE_ARK_ASSET_HOST
    """火山引擎 OpenAPI 签名 V4（POST + JSON body）。返回需随请求发送的鉴权头。"""
    method = "POST"
    content_type = "application/json"
    now = datetime.datetime.now(datetime.timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    payload_hash = hashlib.sha256(body_str.encode("utf-8")).hexdigest()
    # 查询串按键排序：Action < Version
    canonical_query = f"Action={urllib.parse.quote(action, safe='')}&Version={urllib.parse.quote(version, safe='')}"
    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        f"x-content-sha256:{payload_hash}\n"
        f"x-date:{x_date}\n"
    )
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical_request = "\n".join([method, "/", canonical_query, canonical_headers, signed_headers, payload_hash])
    algorithm = "HMAC-SHA256"
    credential_scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = "\n".join([
        algorithm, x_date, credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    k_date = _volc_hmac(sk.encode("utf-8"), short_date)
    k_region = _volc_hmac(k_date, region)
    k_service = _volc_hmac(k_region, service)
    k_signing = _volc_hmac(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"{algorithm} Credential={ak}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Content-Type": content_type,
        "Host": host,
        "X-Date": x_date,
        "X-Content-Sha256": payload_hash,
        "Authorization": authorization,
    }

async def volcengine_ark_asset_call(client, action: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """调用一次火山 Ark Assets OpenAPI，返回 Result 内容；出错抛 HTTPException。"""
    ak = volcengine_access_key_value()
    sk = volcengine_secret_key_value()
    if not ak or not sk:
        raise HTTPException(status_code=400, detail="未配置火山引擎 AK/SK，请在 API 设置中填写 Access Key ID / Secret Access Key。")
    body_str = json.dumps(body, ensure_ascii=False)
    headers = volcengine_sign_v4_headers(ak, sk, action, body_str)
    url = f"https://{VOLCENGINE_ARK_ASSET_HOST}/?Action={urllib.parse.quote(action, safe='')}&Version={urllib.parse.quote(VOLCENGINE_ARK_ASSET_VERSION, safe='')}"
    resp = await client.post(url, headers=headers, content=body_str.encode("utf-8"), timeout=120)
    try:
        payload = resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"火山 {action} 返回非 JSON（{resp.status_code}）：{resp.text[:300]}")
    meta = payload.get("ResponseMetadata") if isinstance(payload, dict) else None
    if isinstance(meta, dict) and isinstance(meta.get("Error"), dict):
        err = meta["Error"]
        code = err.get("Code") or err.get("CodeN") or ""
        msg = err.get("Message") or ""
        raise HTTPException(status_code=502, detail=f"火山 {action} 失败：{code} {msg}".strip())
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"火山 {action} 失败（{resp.status_code}）：{resp.text[:300]}")
    result = payload.get("Result") if isinstance(payload, dict) and isinstance(payload.get("Result"), dict) else None
    return result if result is not None else (payload if isinstance(payload, dict) else {})

async def volcengine_ensure_asset_group(client, project_name: str, group_name: str) -> str:
    """复用同名素材组合，没有则新建。返回 GroupId。"""
    name = (group_name or "可信素材").strip()[:60] or "可信素材"
    project_name = (project_name or "default").strip() or "default"
    # 先按 Name 模糊查找复用
    try:
        listed = await volcengine_ark_asset_call(client, "ListAssetGroups", {
            "Filter": {"Name": name, "GroupType": "AIGC"},
            "PageNumber": 1, "PageSize": 10, "ProjectName": project_name,
        })
        for item in (listed.get("Items") or []):
            if str(item.get("Name") or "").strip() == name and str(item.get("ProjectName") or "default") == project_name:
                gid = str(item.get("Id") or "").strip()
                if gid:
                    return gid
    except HTTPException:
        pass  # 查询失败不致命，继续走新建
    created = await volcengine_ark_asset_call(client, "CreateAssetGroup", {
        "Name": name, "Description": name, "ProjectName": project_name,
    })
    gid = str(created.get("Id") or "").strip()
    if not gid:
        raise HTTPException(status_code=502, detail=f"火山 CreateAssetGroup 未返回 GroupId：{str(created)[:200]}")
    return gid

async def submit_volcengine_avatar_asset(public_url: str, name: str, kind: str,
                                         project_name: str = "default", group_name: str = "") -> str:
    """把公网可访问素材提交到火山 Ark 私域素材库（异步）。返回 Asset Id 作为任务 ID。"""
    async with httpx.AsyncClient(timeout=120) as client:
        group_id = await volcengine_ensure_asset_group(client, project_name, group_name)
        created = await volcengine_ark_asset_call(client, "CreateAsset", {
            "GroupId": group_id,
            "URL": public_url,
            "AssetType": apimart_avatar_asset_type(kind),
            "Name": (name or "asset")[:60],
            "ProjectName": (project_name or "default").strip() or "default",
        })
    asset_id = str(created.get("Id") or "").strip()
    if not asset_id:
        raise HTTPException(status_code=502, detail=f"火山 CreateAsset 未返回 Asset Id：{str(created)[:200]}")
    return asset_id

async def check_volcengine_avatar_task(asset_id: str, project_name: str = "default") -> Dict[str, Any]:
    """查询一次火山素材状态。返回 {status: Active/Processing/Failed, asset_uri, detail}。"""
    async with httpx.AsyncClient(timeout=60) as client:
        info = await volcengine_ark_asset_call(client, "GetAsset", {
            "Id": asset_id,
            "ProjectName": (project_name or "default").strip() or "default",
        })
    status = str(info.get("Status") or "").strip()
    if status == "Active":
        return {"status": "Active", "asset_uri": f"asset://{asset_id}", "detail": ""}
    if status == "Failed":
        return {"status": "Failed", "asset_uri": "", "detail": "火山素材处理失败，无法用于推理。"}
    return {"status": "Processing", "asset_uri": "", "detail": "火山素材处理中"}

def volcengine_public_asset_url(url: str) -> str:
    """火山 CreateAsset 要求 URL 公网可访问；本地文件需 PUBLIC_BASE_URL，否则返回 ERR:。"""
    text = str(url or "").strip()
    if text.startswith("http://") or text.startswith("https://"):
        return text
    public = local_asset_public_url(text)
    if public:
        return public
    return "ERR:火山要求素材是公网可访问的 http/https URL；本地画布文件需配置 PUBLIC_BASE_URL/PUBLIC_MEDIA_BASE_URL 暴露为公网地址。"

def local_media_path_for_cloud_upload(ref_url: str, allowed_prefixes=("image/", "video/")) -> str:
    ref_url = str(ref_url or "").strip()
    if not ref_url:
        raise HTTPException(status_code=400, detail="没有可上传的媒体文件")
    if ref_url.startswith("http://") or ref_url.startswith("https://"):
        return ""
    if not (ref_url.startswith("/output/") or ref_url.startswith("/assets/")):
        raise HTTPException(status_code=400, detail="云端上传只支持画布里的本地图片或视频文件")
    path = output_file_from_url(ref_url)
    if not path:
        raise HTTPException(status_code=404, detail="本地媒体文件不存在或已被删除")
    ct = content_type_for_path(path)
    if not any(ct.startswith(prefix) for prefix in allowed_prefixes):
        raise HTTPException(status_code=400, detail="请选择图片或视频文件再上传云端")
    max_bytes = int(os.getenv("TEMP_SH_MAX_BYTES", str(4 * 1024 * 1024 * 1024)))
    size = os.path.getsize(path)
    if size > max_bytes:
        raise HTTPException(status_code=400, detail=f"媒体文件超过云端上传大小限制：{size} bytes")
    return path

def local_video_path_for_cloud_upload(ref_url: str) -> str:
    return local_media_path_for_cloud_upload(ref_url, ("video/",))

async def upload_video_to_litterbox(path: str, source_url: str) -> Dict[str, str]:
    upload_url = os.getenv("LITTERBOX_UPLOAD_URL", "https://litterbox.catbox.moe/resources/internals/api.php").strip() or "https://litterbox.catbox.moe/resources/internals/api.php"
    time_value = os.getenv("LITTERBOX_TIME", "72h").strip() or "72h"
    ct = content_type_for_path(path)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=600.0, write=600.0, pool=20.0), follow_redirects=True) as client:
            with open(path, "rb") as fh:
                files = {"fileToUpload": (os.path.basename(path), fh, ct)}
                data = {"reqtype": "fileupload", "time": time_value}
                response = await client.post(upload_url, data=data, files=files)
        if not response.is_success:
            raise HTTPException(status_code=response.status_code, detail=f"Litterbox 上传失败：{response.text[:300]}")
        direct_url = response.text.strip().splitlines()[0].strip()
        if not re.match(r"^https?://", direct_url, re.I):
            raise HTTPException(status_code=502, detail=f"Litterbox 返回了无法识别的链接：{response.text[:300]}")
        return {"url": direct_url, "source": source_url, "name": os.path.basename(path), "expires": time_value, "service": "litterbox"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Litterbox 上传异常：{exc}") from exc

async def upload_video_to_temp_sh(path: str, source_url: str) -> Dict[str, str]:
    upload_url = os.getenv("TEMP_SH_UPLOAD_URL", "https://temp.sh/upload").strip() or "https://temp.sh/upload"
    ct = content_type_for_path(path)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=600.0, write=600.0, pool=20.0), follow_redirects=True) as client:
            with open(path, "rb") as fh:
                files = {"file": (os.path.basename(path), fh, ct)}
                response = await client.post(upload_url, files=files)
        if not response.is_success:
            raise HTTPException(status_code=response.status_code, detail=f"Temp.sh 上传失败：{response.text[:300]}")
        direct_url = response.text.strip().splitlines()[0].strip()
        if not re.match(r"^https?://", direct_url, re.I):
            raise HTTPException(status_code=502, detail=f"Temp.sh 返回了无法识别的链接：{response.text[:300]}")
        return {"url": direct_url, "source": source_url, "name": os.path.basename(path), "expires": "3 days", "service": "temp.sh"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Temp.sh 上传异常：{exc}") from exc

async def upload_local_video_to_cloud(ref_url: str, service: str = "auto") -> Dict[str, str]:
    ref_url = str(ref_url or "").strip()
    if ref_url.startswith("http://") or ref_url.startswith("https://"):
        return {"url": ref_url, "source": ref_url, "service": "existing"}
    path = local_media_path_for_cloud_upload(ref_url)
    service = str(service or os.getenv("CLOUD_VIDEO_UPLOAD_SERVICE", "auto") or "auto").strip().lower()
    if service in {"litterbox", "catbox"}:
        return await upload_video_to_litterbox(path, ref_url)
    if service in {"temp", "temp.sh", "tempsh"}:
        return await upload_video_to_temp_sh(path, ref_url)
    errors = []
    for name, func in (("litterbox", upload_video_to_litterbox), ("temp.sh", upload_video_to_temp_sh)):
        try:
            return await func(path, ref_url)
        except HTTPException as exc:
            errors.append(f"{name}: {exc.detail}")
    raise HTTPException(status_code=502, detail="云端上传失败：" + "；".join(errors))

async def upload_local_video_to_temp_sh(ref_url: str) -> Dict[str, str]:
    return await upload_local_video_to_cloud(ref_url, "auto")

async def save_ai_image_to_output(image_data, prefix="online_", category="output"):
    filename = f"{prefix}{uuid.uuid4().hex[:10]}.png"
    path = output_path_for(filename, category)
    if image_data["type"] == "b64":
        mime_type = str(image_data.get("mime_type") or "").lower()
        if "jpeg" in mime_type or "jpg" in mime_type:
            filename = filename[:-4] + ".jpg"
            path = output_path_for(filename, category)
        elif "webp" in mime_type:
            filename = filename[:-4] + ".webp"
            path = output_path_for(filename, category)
        with open(path, "wb") as f:
            f.write(base64.b64decode(image_data["value"]))
        return output_url_for(filename, category)
    value = image_data["value"]
    if value.startswith("/output/") or value.startswith("/assets/"):
        return value
    value = rewrite_runninghub_file_url(value)
    try:
        timeout = httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=20.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(value)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if "jpeg" in content_type or "jpg" in content_type:
                filename = filename[:-4] + ".jpg"
                path = output_path_for(filename, category)
            elif "webp" in content_type:
                filename = filename[:-4] + ".webp"
                path = output_path_for(filename, category)
            with open(path, "wb") as f:
                f.write(response.content)
            return output_url_for(filename, category)
    except Exception as e:
        print(f"保存上游图片失败: {e}; url={value}")
        return value

def image_output_meta(url, source_item=None):
    meta = {"url": url, "kind": "image"}
    if not url:
        return meta
    parsed_name = os.path.basename(urllib.parse.urlparse(str(url)).path)
    if parsed_name:
        meta["name"] = parsed_name
    if isinstance(source_item, dict):
        for key in ("natural_w", "natural_h", "width", "height", "w", "h", "layout_w", "layout_h"):
            try:
                value = int(float(source_item.get(key) or 0))
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                meta[key] = value
    path = output_file_from_url(url)
    if path and os.path.exists(path):
        try:
            with Image.open(path) as img:
                width, height = img.size
            if width > 0 and height > 0:
                meta.update({
                    "natural_w": width,
                    "natural_h": height,
                    "width": width,
                    "height": height,
                })
        except Exception:
            pass
    return meta

async def save_remote_video_to_output(url, prefix="video_", category="output"):
    if not url:
        return ""
    if url.startswith("/output/") or url.startswith("/assets/"):
        return url
    video_exts = {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv", ".flv"}
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return url
    clean_ext = os.path.splitext(parsed.path)[1].lower()
    stem = f"{prefix}{uuid.uuid4().hex[:10]}"
    filename = f"{stem}{clean_ext if clean_ext in video_exts else '.mp4'}"
    path = output_path_for(filename, category)
    try:
        timeout = httpx.Timeout(connect=20.0, read=VIDEO_POLL_TIMEOUT, write=60.0, pool=20.0)
        headers = {
            "User-Agent": "ComfyUI-API-Modelscope/1.0",
            "Accept": "video/*,application/octet-stream,*/*;q=0.8",
        }
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "text/html" in content_type or "application/json" in content_type:
                raise RuntimeError(f"unexpected video content type: {content_type}")
            ext = clean_ext
            if ext in video_exts:
                filename = f"{stem}{ext}"
                path = output_path_for(filename, category)
            elif "webm" in content_type:
                filename = f"{stem}.webm"
                path = output_path_for(filename, category)
            elif "quicktime" in content_type or "mov" in content_type:
                filename = f"{stem}.mov"
                path = output_path_for(filename, category)
            elif "x-matroska" in content_type or "mkv" in content_type:
                filename = f"{stem}.mkv"
                path = output_path_for(filename, category)
            elif "x-flv" in content_type or "flv" in content_type:
                filename = f"{stem}.flv"
                path = output_path_for(filename, category)
            with open(path, "wb") as f:
                f.write(response.content)
            if os.path.getsize(path) <= 0:
                raise RuntimeError("empty video response")
            return output_url_for(filename, category)
    except Exception as e:
        print(f"保存上游视频失败: {e}")
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        return url

def parse_size_pair(size):
    match = re.fullmatch(r"\s*(\d+)\s*[xX*]\s*(\d+)\s*", str(size or ""))
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))

def chat_prompt_size_override(message, current_size=""):
    text = str(message or "")
    direct = re.search(r"(?<!\d)([1-9]\d{2,4})\s*[xX×*]\s*([1-9]\d{2,4})(?!\d)", text)
    if direct:
        width, height = int(direct.group(1)), int(direct.group(2))
        if width >= 256 and height >= 256:
            return f"{width}x{height}"

    normalized = (
        text.replace("：", ":")
        .replace("﹕", ":")
        .replace("∶", ":")
        .replace("比", ":")
        .replace("／", "/")
        .replace("/", ":")
    )
    ratio_match = re.search(r"(?<!\d)(1|2|3|4|9|16)\s*:\s*(1|2|3|4|9|16)(?!\d)", normalized)
    if not ratio_match:
        return ""
    ratio = f"{int(ratio_match.group(1))}:{int(ratio_match.group(2))}"
    options = CHAT_RATIO_SIZE_OPTIONS.get(ratio)
    if not options:
        return ""
    width, height = parse_size_pair(current_size)
    wants_4k = bool(re.search(r"(?i)\b4\s*k\b|4K|超清|超高分辨率", text))
    wants_2k = bool(re.search(r"(?i)\b2\s*k\b|2K|高清|高分辨率", text))
    long_edge = max(width, height)
    if wants_4k or long_edge >= 2400:
        return options[2] if len(options) > 2 else options[-1]
    if wants_2k or long_edge >= 1500:
        return options[1] if len(options) > 1 else options[0]
    return options[0]
