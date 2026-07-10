"""Video-provider task polling, uploads, and dispatch."""

from __future__ import annotations

import asyncio
import base64
import os
import re
import time
import urllib.parse
from typing import Any

import httpx
from fastapi import HTTPException

from api_models import CanvasVideoRequest
from app_services.media_files import output_file_from_url
from app_services.provider_routing import (
    is_apimart_provider,
    is_jimeng_provider,
    is_runninghub_provider,
    is_volcengine_provider,
)
from provider_adapters.jimeng import generate_jimeng_video
from provider_adapters.runninghub import generate_runninghub_video


VIDEO_ADAPTER_EXPORTS = (
    "_collect_video_url",
    "video_output_urls",
    "video_api_root",
    "looks_like_html_response",
    "video_submit_url_candidates",
    "video_task_url_candidates",
    "humanize_video_task_failure",
    "wait_for_video_task",
    "apimart_video_size",
    "agnes_video_dimensions",
    "agnes_video_frame_count",
    "agnes_video_image_url",
    "wait_for_agnes_video_task",
    "generate_agnes_video",
    "_yuli_model_norm",
    "yuli_is_veo_openai_model",
    "yuli_openai_model_name",
    "yuli_openai_size",
    "yuli_video_seconds",
    "yuli_fetch_reference_bytes",
    "generate_yuli_openai_video",
    "volcengine_video_prompt_text",
    "canvas_video",
)


def configure_video_adapter(**dependencies: Any) -> None:
    required = {
        "AI_BASE_URL",
        "IMAGE_POLL_INTERVAL",
        "VIDEO_POLL_TIMEOUT",
        "VIDEO_URL_KEYS",
        "api_headers",
        "apimart_veo31_aspect",
        "apimart_veo31_duration",
        "apimart_veo31_model",
        "apimart_veo31_resolution",
        "apimart_video_duration",
        "apimart_video_reference_error",
        "apply_trusted_asset_prompt_index",
        "content_type_for_path",
        "extract_task_id",
        "get_api_provider",
        "invalid_video_image_preview",
        "is_agnes_provider",
        "is_apimart_veo31_model",
        "is_yuli_provider",
        "log_net_error",
        "looks_like_image_media_url",
        "probe_local_audio_duration_seconds",
        "provider_env_key_value",
        "reference_to_data_url",
        "save_remote_video_to_output",
        "selected_model",
        "upload_audio_for_apimart",
        "upload_image_for_apimart",
        "upload_local_video_to_cloud",
        "upload_video_for_apimart",
        "valid_apimart_video_image_input",
        "volcengine_content_role",
        "volcengine_media_reference_url",
        "volcengine_video_duration",
        "volcengine_video_reference_content_items",
        "volcengine_video_resolution",
    }
    missing = sorted(required - dependencies.keys())
    if missing:
        raise RuntimeError(f"Video adapter missing dependencies: {', '.join(missing)}")
    globals().update(dependencies)


def export_video_adapter(target: dict[str, Any]) -> None:
    for name in VIDEO_ADAPTER_EXPORTS:
        target[name] = globals()[name]

def _collect_video_url(value, urls):
    if not value:
        return
    if isinstance(value, str):
        if value.startswith("http://") or value.startswith("https://") or value.startswith("/output/") or value.startswith("/assets/"):
            urls.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _collect_video_url(item, urls)
        return
    if isinstance(value, dict):
        for key in ("videos", "outputs", "data", "result", "content"):
            if key in value:
                _collect_video_url(value.get(key), urls)
        for key in VIDEO_URL_KEYS:
            if key in value:
                _collect_video_url(value.get(key), urls)

def video_output_urls(raw):
    urls = []
    if not isinstance(raw, dict):
        return urls
    candidates = [raw]
    data = raw.get("data")
    content = raw.get("content")
    if isinstance(data, dict):
        candidates.append(data)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                candidates.append(item)
    if isinstance(content, dict):
        candidates.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                candidates.append(item)
    for node in list(candidates):
        result = node.get("result") if isinstance(node, dict) else None
        if isinstance(result, dict):
            candidates.append(result)
        elif isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    candidates.append(item)
    for node in candidates:
        if not isinstance(node, dict):
            continue
        for key in ("videos", "outputs", "content"):
            value = node.get(key)
            if value:
                _collect_video_url(value, urls)
        for key in VIDEO_URL_KEYS:
            if key in node:
                _collect_video_url(node.get(key), urls)
    deduped = []
    for url in urls:
        if isinstance(url, str) and url and url not in deduped:
            deduped.append(url)
    return deduped

def video_api_root(provider):
    base_url = (provider.get("base_url") or AI_BASE_URL).rstrip("/")
    if is_volcengine_provider(provider):
        if base_url.endswith("/api/v3"):
            base_url = base_url[: -len("/api/v3")]
        return base_url
    if base_url.endswith("/v1") or base_url.endswith("/v2"):
        base_url = base_url.rsplit("/", 1)[0]
    return base_url

def looks_like_html_response(text: str) -> bool:
    sample = str(text or "").lstrip()[:200].lower()
    return sample.startswith("<!doctype html") or sample.startswith("<html") or "<head" in sample

def video_submit_url_candidates(provider, base_url):
    if is_agnes_provider(provider):
        return [f"{base_url}/v1/videos"]
    if is_apimart_provider(provider):
        return [f"{base_url}/videos/generations" if base_url.endswith("/v1") else f"{base_url}/v1/videos/generations"]
    if is_volcengine_provider(provider):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.path and parsed.path.rstrip("/"):
            return [base_url]
        return [f"{base_url}/api/v3/contents/generations/tasks"]
    if is_yuli_provider(provider):
        return [f"{base_url}/v1/video/create"]
    return [f"{base_url}/v1/videos/generations", f"{base_url}/v2/videos/generations"]

def video_task_url_candidates(provider, base_url, task_id, submit_url=""):
    if is_agnes_provider(provider):
        quoted_id = urllib.parse.quote(str(task_id), safe="")
        return [
            f"{base_url}/agnesapi?{urllib.parse.urlencode({'video_id': task_id})}",
            f"{base_url}/v1/videos/{quoted_id}",
        ]
    if is_apimart_provider(provider):
        task_path = f"{base_url}/tasks/{task_id}" if base_url.endswith("/v1") else f"{base_url}/v1/tasks/{task_id}"
        return [f"{task_path}?language=zh"]
    if is_volcengine_provider(provider):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.path and parsed.path.rstrip("/"):
            return [f"{base_url}/{task_id}"]
        return [f"{base_url}/api/v3/contents/generations/tasks/{task_id}"]
    if is_yuli_provider(provider):
        # 玉玉API 两种视频格式：OpenAI（/v1/videos/{id}）与原生（/v1/video/query?id=）。
        # 两个都试，谁返回成功就用谁，兼容 veo OpenAI 路径与 doubao 原生路径。
        return [f"{base_url}/v1/videos/{task_id}", f"{base_url}/v1/video/query?id={task_id}"]
    v1_task = f"{base_url}/v1/videos/generations/{task_id}"
    v1_generic_task = f"{base_url}/v1/tasks/{task_id}"
    v2_task = f"{base_url}/v2/videos/generations/{task_id}"
    if "/v2/videos/generations" in str(submit_url or ""):
        return [v2_task, v1_task, v1_generic_task]
    return [v1_task, v1_generic_task, v2_task]

VIDEO_TASK_SUCCESS_STATUSES = {
    "SUCCESS", "SUCCEED", "SUCCEEDED", "COMPLETED", "COMPLETE",
    "DONE", "FINISHED", "FINISH", "OK", "READY",
}
VIDEO_TASK_FAILURE_STATUSES = {
    "FAILURE", "FAILED", "FAIL", "ERROR", "ERRORED",
    "CANCELED", "CANCELLED", "TIMEOUT", "TIMEDOUT", "REJECTED", "EXPIRED",
}

def humanize_video_task_failure(reason) -> str:
    """把上游视频任务的失败原因转成对用户友好的中文提示。
    目前主要处理 veo（Google）的内容安全过滤码。"""
    text = str(reason or "").strip()
    upper = text.upper()
    # veo 知名人物/真人面孔过滤
    if "PROMINENT_PEOPLE_FILTER" in upper or "PROMINENT_PEOPLE" in upper:
        return (
            "视频生成被上游内容安全策略拦截：检测到提示词或参考图里包含知名人物 / 真人面孔"
            f"（错误码：{text}）。\n\n"
            "这不是代码错误，而是 veo（Google）的内容审核规则——它会拒绝生成涉及真实/知名人物的视频。\n\n"
            "建议这样处理：\n"
            "  1. 去掉提示词里的人名、明星、公众人物等指向具体真人的描述；\n"
            "  2. 换用非真人参考图，例如插画、AI 头像、卡通形象、商品图、场景图；\n"
            "  3. 如果用了真人照片做参考图，先做模糊/遮挡/转成明显的二次元插画风，或干脆只用文字提示词测试。"
        )
    # veo 其它常见安全过滤
    if "SAFETY" in upper or "CONTENT_FILTER" in upper or "POLICY" in upper:
        return (
            "视频生成被上游内容安全策略拦截"
            f"（错误码：{text}）。\n\n"
            "这是 veo 的内容审核规则，提示词或参考图触发了安全过滤。\n"
            "请调整提示词/参考图后重试，避免涉及真人、暴力、敏感或受限内容。"
        )
    return f"视频生成任务失败：{text}"

async def wait_for_video_task(client, provider, task_id, submit_url=""):
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} 未配置 Base URL")
    task_urls = video_task_url_candidates(provider, base_url, task_id, submit_url)
    deadline = time.monotonic() + VIDEO_POLL_TIMEOUT
    delay = max(2.0, IMAGE_POLL_INTERVAL)
    last_payload = {}
    while time.monotonic() < deadline:
        await asyncio.sleep(delay)
        raw = None
        last_error = None
        for task_url in task_urls:
            try:
                response = await client.get(task_url, headers=api_headers(provider=provider))
                response.raise_for_status()
                raw = response.json()
                break
            except Exception as exc:
                last_error = exc
                continue
        if raw is None:
            if last_error:
                raise last_error
            raise HTTPException(status_code=502, detail=f"视频任务查询失败：{task_id}")
        last_payload = raw
        task_data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        status = str(task_data.get("status") or task_data.get("task_status") or raw.get("status") or raw.get("task_status") or "").upper()
        if status in VIDEO_TASK_SUCCESS_STATUSES:
            return raw
        # 部分上游（如玉玉API）status 字段非标准或为空，但已经返回了视频 URL ——
        # 只要不是明确的失败状态，且拿到了真实视频地址，就直接当成功处理。
        if status not in VIDEO_TASK_FAILURE_STATUSES and video_output_urls(raw):
            return raw
        if status in VIDEO_TASK_FAILURE_STATUSES:
            error = task_data.get("error") if isinstance(task_data.get("error"), dict) else {}
            reason = task_data.get("fail_reason") or task_data.get("message") or error.get("message") or raw.get("error") or raw.get("message") or str(raw)
            raise HTTPException(status_code=502, detail=humanize_video_task_failure(reason))
        delay = min(delay * 1.6, 12)
    raise HTTPException(status_code=504, detail=f"视频生成任务超时：{last_payload or task_id}")

def apimart_video_size(size):
    value = str(size or "16:9").strip()
    if value == "keep_ratio":
        return "adaptive"
    allowed = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"}
    return value if value in allowed else "16:9"

def agnes_video_dimensions(aspect_ratio="", resolution=""):
    ratio = str(aspect_ratio or "16:9").strip()
    width, height = {
        "16:9": (1152, 648),
        "9:16": (648, 1152),
        "4:3": (1024, 768),
        "3:4": (768, 1024),
        "1:1": (768, 768),
        "21:9": (1280, 544),
        "9:21": (544, 1280),
    }.get(ratio, (1152, 768))
    scale = {"480p": 0.625, "720p": 1.0, "780p": 1.0, "1080p": 1.5}.get(str(resolution or "").strip().lower(), 1.0)
    width = max(64, int(round(width * scale / 8) * 8))
    height = max(64, int(round(height * scale / 8) * 8))
    return width, height

def agnes_video_frame_count(duration, fps=24):
    try:
        seconds = max(1, min(18, int(duration or 5)))
    except Exception:
        seconds = 5
    try:
        frame_rate = max(1, min(60, int(fps or 24)))
    except Exception:
        frame_rate = 24
    target = min(441, max(9, seconds * frame_rate))
    n = max(1, round((target - 1) / 8))
    return min(441, max(9, 8 * n + 1)), frame_rate

async def agnes_video_image_url(ref):
    url = str(getattr(ref, "url", "") or "").strip()
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    uploaded = await upload_local_video_to_cloud(url, "auto")
    return uploaded.get("url") or ""

async def wait_for_agnes_video_task(client, provider, video_id, model):
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} 未配置 Base URL")
    query_url = f"{base_url}/agnesapi?{urllib.parse.urlencode({'video_id': video_id, 'model_name': model})}"
    legacy_url = f"{base_url}/v1/videos/{urllib.parse.quote(str(video_id), safe='')}"
    deadline = time.monotonic() + VIDEO_POLL_TIMEOUT
    delay = 5.0
    last_payload = {}
    while time.monotonic() < deadline:
        await asyncio.sleep(delay)
        raw = None
        last_error = None
        for url in (query_url, legacy_url):
            try:
                response = await client.get(url, headers=api_headers(provider=provider, model=model))
                response.raise_for_status()
                raw = response.json()
                break
            except Exception as exc:
                last_error = exc
        if raw is None:
            if last_error:
                raise last_error
            raise HTTPException(status_code=502, detail=f"Agnes 视频任务查询失败：{video_id}")
        last_payload = raw
        task_data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        status = str(task_data.get("status") or raw.get("status") or "").upper()
        if status in VIDEO_TASK_SUCCESS_STATUSES or video_output_urls(raw):
            return raw
        if status in VIDEO_TASK_FAILURE_STATUSES:
            error = task_data.get("error") if isinstance(task_data.get("error"), dict) else {}
            reason = task_data.get("message") or error.get("message") or raw.get("error") or raw.get("message") or str(raw)
            raise HTTPException(status_code=502, detail=humanize_video_task_failure(reason))
        delay = min(delay * 1.35, 12)
    raise HTTPException(status_code=504, detail=f"Agnes 视频生成任务超时：{last_payload or video_id}")

async def generate_agnes_video(client, payload, provider, base_url, requested_model):
    model = selected_model(requested_model, "agnes-video-v2.0")
    width, height = agnes_video_dimensions(payload.aspect_ratio, payload.resolution)
    num_frames, frame_rate = agnes_video_frame_count(payload.duration, 24)
    body = {
        "model": model,
        "prompt": str(payload.prompt or ""),
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "frame_rate": frame_rate,
    }
    image_urls = []
    image_roles = []
    for ref in (payload.images or [])[:4]:
        url = await agnes_video_image_url(ref)
        if url:
            image_urls.append(url)
            image_roles.append(str(getattr(ref, "role", "") or "").strip().lower())
    if len(image_urls) == 1:
        body["image"] = image_urls[0]
    elif len(image_urls) > 1:
        body["extra_body"] = {"image": image_urls}
        has_frame_roles = any(role in {"first_frame", "last_frame"} for role in image_roles)
        if payload.multimodal or has_frame_roles:
            body["extra_body"]["mode"] = "keyframes"
    if payload.seed is not None:
        body["seed"] = payload.seed
    submit_url = f"{base_url}/v1/videos"
    response = await client.post(submit_url, headers=api_headers(provider=provider, model=model), json=body)
    response.raise_for_status()
    raw = response.json()
    video_id = str(raw.get("video_id") or "").strip()
    task_id = str(raw.get("task_id") or raw.get("id") or "").strip()
    result = raw
    if video_id and not video_output_urls(raw):
        result = await wait_for_agnes_video_task(client, provider, video_id, model)
    elif task_id and not video_output_urls(raw):
        result = await wait_for_video_task(client, provider, task_id, submit_url)
    urls = video_output_urls(result)
    if not urls:
        raise HTTPException(status_code=502, detail=f"Agnes 视频生成成功但没有返回视频：{result}")
    local_urls = [await save_remote_video_to_output(url) for url in urls]
    return {"videos": local_urls, "task_id": task_id or video_id, "video_id": video_id or None, "raw": result}

# ---- 玉玉API（yuli.host）OpenAI 视频格式：/v1/videos（multipart，支持 seconds 时长）----
def _yuli_model_norm(model: str) -> str:
    return str(model or "").strip().lower().replace("_", "").replace(".", "").replace("-", "")

def yuli_is_veo_openai_model(model: str) -> bool:
    # OpenAI multipart 格式当前只支持 veo_3_1 和 veo_3_1-fast
    return _yuli_model_norm(model) in {"veo31", "veo31fast"}

def yuli_openai_model_name(model: str) -> str:
    return "veo_3_1-fast" if _yuli_model_norm(model) == "veo31fast" else "veo_3_1"

def yuli_openai_size(aspect_ratio: str) -> str:
    value = str(aspect_ratio or "").strip()
    if value == "9:16":
        return "9x16"
    return "16x9"

def yuli_video_seconds(duration) -> str:
    try:
        value = int(duration)
    except Exception:
        value = 8
    if value <= 0:
        value = 8
    return str(value)

async def yuli_fetch_reference_bytes(client, ref_url):
    """把参考图（input_reference 垫图）取成 (filename, bytes, mime)，
    支持 /output、/assets 本地文件、data URL、http(s) URL。失败返回 None。"""
    ref_url = str(ref_url or "").strip()
    if not ref_url:
        return None
    if ref_url.startswith("data:"):
        header, _, b64 = ref_url.partition(",")
        mime = (header[5:].split(";")[0] or "image/png").strip()
        try:
            raw = base64.b64decode(b64)
        except Exception:
            return None
        ext = (mime.split("/")[-1] or "png").split("+")[0]
        return (f"input_reference.{ext}", raw, mime)
    path = output_file_from_url(ref_url)
    if path:
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except Exception:
            return None
        mime = content_type_for_path(path)
        return (os.path.basename(path) or "input_reference", raw, mime)
    if ref_url.startswith("http://") or ref_url.startswith("https://"):
        try:
            resp = await client.get(ref_url)
            resp.raise_for_status()
            raw = resp.content
        except Exception:
            return None
        mime = (resp.headers.get("content-type") or "image/png").split(";")[0].strip()
        ext = (mime.split("/")[-1] or "png").split("+")[0]
        return (f"input_reference.{ext}", raw, mime)
    return None

async def generate_yuli_openai_video(client, payload, provider, base_url, requested_model):
    """玉玉API veo3.1 走 OpenAI multipart 格式 /v1/videos，支持 seconds 时长控制。"""
    submit_url = f"{base_url}/v1/videos"
    data = {
        "model": yuli_openai_model_name(requested_model),
        "prompt": str(payload.prompt or ""),
        "seconds": yuli_video_seconds(payload.duration),
        "size": yuli_openai_size(payload.aspect_ratio),
        "watermark": "true" if payload.watermark else "false",
    }
    files = {}
    for ref in (payload.images or [])[:1]:
        ref_file = await yuli_fetch_reference_bytes(client, getattr(ref, "url", ""))
        if ref_file:
            files["input_reference"] = ref_file
            break
    headers = api_headers(json_body=False, provider=provider)
    if files:
        response = await client.post(submit_url, headers=headers, data=data, files=files)
    else:
        # 文生视频无垫图时，仍以 multipart/form-data 提交（把文本字段作为表单分块），
        # 避免 httpx 在只有 data 时退化成 application/x-www-form-urlencoded。
        multipart_fields = {key: (None, value) for key, value in data.items()}
        response = await client.post(submit_url, headers=headers, files=multipart_fields)
    response.raise_for_status()
    try:
        raw = response.json()
    except Exception as exc:
        resp_text = (response.text or "")[:500]
        raise HTTPException(status_code=502, detail=f"玉玉API 视频接口返回非 JSON 响应（状态 {response.status_code}）：{resp_text}") from exc
    task_id = raw.get("id") or extract_task_id(raw) or raw.get("task_id")
    result = raw
    if task_id and not video_output_urls(raw):
        result = await wait_for_video_task(client, provider, task_id, submit_url)
    urls = video_output_urls(result)
    if not urls:
        raise HTTPException(status_code=502, detail=f"视频生成成功但没有返回视频：{result}")
    local_urls = [await save_remote_video_to_output(url) for url in urls]
    return {"videos": local_urls, "task_id": task_id, "raw": result}

def volcengine_video_prompt_text(prompt, aspect_ratio="", duration=None):
    text = str(prompt or "").strip()
    suffixes = []
    ratio = str(aspect_ratio or "").strip()
    if ratio:
        suffixes.append(f"--ratio {ratio}")
    if not suffixes:
        return text
    suffix_text = " ".join(suffixes)
    return f"{text} {suffix_text}".strip() if text else suffix_text

async def canvas_video(payload: CanvasVideoRequest):
    provider = get_api_provider(payload.provider_id)
    if is_jimeng_provider(provider):
        return await generate_jimeng_video(payload, provider)
    if is_runninghub_provider(provider):
        try:
            return await generate_runninghub_video(payload, provider)
        except httpx.HTTPStatusError as exc:
            text = exc.response.text
            raise HTTPException(status_code=exc.response.status_code, detail=f"RunningHub 视频接口错误：{text}") from exc
        except httpx.HTTPError as exc:
            log_net_error(f"视频(RunningHub) 网络/TLS错误 model={payload.model}", exc)
            raise HTTPException(status_code=502, detail=f"请求 RunningHub 视频接口失败：{exc}") from exc
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} 未配置 Base URL")
    api_key = provider_env_key_value(provider["id"])
    if not api_key:
        raise HTTPException(status_code=400, detail=f"未配置 {provider.get('name') or provider['id']} 的 API Key，请在 API 设置中填写。")
    is_apimart = is_apimart_provider(provider)
    is_volcengine = is_volcengine_provider(provider)
    is_yuli = is_yuli_provider(provider)
    is_agnes = is_agnes_provider(provider, payload.model)
    volc_is_proxy = bool(is_volcengine and urllib.parse.urlparse(base_url).path.rstrip("/"))
    submit_urls = video_submit_url_candidates(provider, base_url)
    submit_url = submit_urls[0]
    requested_model = selected_model(payload.model, "agnes-video-v2.0" if is_agnes else "veo3-fast")
    is_veo31 = is_apimart and is_apimart_veo31_model(requested_model)
    if is_agnes:
        try:
            async with httpx.AsyncClient(timeout=VIDEO_POLL_TIMEOUT) as agnes_client:
                return await generate_agnes_video(agnes_client, payload, provider, base_url, requested_model)
        except httpx.HTTPStatusError as exc:
            text = exc.response.text
            raise HTTPException(status_code=exc.response.status_code, detail=f"Agnes 视频接口错误：{text}") from exc
        except httpx.HTTPError as exc:
            log_net_error(f"视频(Agnes) 网络/TLS错误 model={requested_model}", exc)
            raise HTTPException(status_code=502, detail=f"请求 Agnes 视频接口失败：{exc}") from exc
    # 玉玉API veo3.1 走 OpenAI multipart 格式（支持 seconds 时长）；其余模型（doubao 等）
    # 沿用下方原生 /v1/video/create JSON 流程。
    if is_yuli and yuli_is_veo_openai_model(requested_model):
        try:
            async with httpx.AsyncClient(timeout=VIDEO_POLL_TIMEOUT) as yuli_client:
                return await generate_yuli_openai_video(yuli_client, payload, provider, base_url, requested_model)
        except httpx.HTTPStatusError as exc:
            text = exc.response.text
            raise HTTPException(status_code=exc.response.status_code, detail=f"上游视频接口错误：{text}") from exc
        except httpx.HTTPError as exc:
            log_net_error(f"视频(玉玉) 网络/TLS错误 model={requested_model}", exc)
            raise HTTPException(status_code=502, detail=f"请求上游视频接口失败：{exc}") from exc
    try:
        async with httpx.AsyncClient(timeout=VIDEO_POLL_TIMEOUT) as client:
            # --- 构造图片载荷 ---
            if is_apimart:
                # APIMart 只接受 http/https 或 asset:// URL，先上传本地图片取回网络 URL
                image_with_roles = []
                invalid_images = []  # 每项为 (原始 URL, 失败原因)
                video_payload = []
                invalid_videos = []
                for ref_url in payload.videos[:3]:
                    ref_url = str(ref_url or "").strip()
                    if not ref_url:
                        continue
                    normalized_video_url = await upload_video_for_apimart(client, provider, ref_url)
                    if valid_apimart_video_image_input(normalized_video_url):
                        video_payload.append(normalized_video_url)
                    else:
                        reason = normalized_video_url[4:] if isinstance(normalized_video_url, str) and normalized_video_url.startswith("ERR:") else apimart_video_reference_error(ref_url)
                        invalid_videos.append((ref_url, reason))
                if invalid_videos:
                    first_url, first_reason = invalid_videos[0]
                    sample = invalid_video_image_preview(first_url)
                    raise HTTPException(
                        status_code=400,
                        detail=f"输入视频无法转换为 APIMart 支持的格式：{sample}\n原因：{first_reason}"
                    )
                apimart_model = apimart_veo31_model(requested_model) if is_veo31 else ""
                if apimart_model == "veo3.1-lite" and payload.images:
                    raise HTTPException(status_code=400, detail="veo3.1-lite 不支持图片输入，请改用 veo3.1-fast 或 veo3.1-quality。")
                image_limit = 0 if apimart_model == "veo3.1-lite" else (3 if is_veo31 else 9)
                for ref in payload.images[:image_limit]:
                    if not ref.url:
                        continue
                    role = str(ref.role or "").strip()
                    if not is_veo31 and role in {"first_frame", "last_frame", "reference_image"}:
                        up_url = await upload_image_for_apimart(client, provider, ref.url)
                        if valid_apimart_video_image_input(up_url):
                            image_with_roles.append({"url": up_url, "role": role})
                        else:
                            reason = up_url[4:] if isinstance(up_url, str) and up_url.startswith("ERR:") else "未知错误"
                            invalid_images.append((ref.url, reason))
                image_payload = []
                if not image_with_roles:
                    for ref in payload.images[:image_limit]:
                        if not ref.url:
                            continue
                        up_url = await upload_image_for_apimart(client, provider, ref.url)
                        if valid_apimart_video_image_input(up_url):
                            image_payload.append(up_url)
                        else:
                            reason = up_url[4:] if isinstance(up_url, str) and up_url.startswith("ERR:") else "未知错误"
                            invalid_images.append((ref.url, reason))
                if payload.images and not image_with_roles and not image_payload:
                    first_url, first_reason = invalid_images[0] if invalid_images else ("", "未知错误")
                    sample = invalid_video_image_preview(first_url)
                    raise HTTPException(status_code=400, detail=f"输入图片无法转换为视频接口支持的格式：{sample}\n原因：{first_reason}\n请确认本地文件存在且不超过 10MB；VEO3.1 需要图片是 APIMart 可访问的 http/https / asset:// / data URL。")
                # --- APIMart 请求体 ---
                if is_veo31:
                    model = apimart_model
                    body = {
                        "prompt": payload.prompt,
                        "model": model,
                        "duration": apimart_veo31_duration(payload.duration),
                        "aspect_ratio": apimart_veo31_aspect(payload.aspect_ratio),
                        "resolution": apimart_veo31_resolution(payload.resolution),
                    }
                    if image_payload and model != "veo3.1-lite":
                        video_images = image_payload[:3]
                        if model == "veo3.1-quality" and len(video_images) > 2:
                            video_images = video_images[:2]
                        body["image_urls"] = video_images
                        if len(video_images) == 2:
                            body["generation_type"] = "frame"
                        elif len(video_images) >= 3 and model != "veo3.1-quality":
                            body["generation_type"] = "reference"
                    if model != "veo3.1-lite":
                        body["official_fallback"] = False
                else:
                    body = {
                        "prompt": payload.prompt,
                        "model": selected_model(payload.model, "doubao-seedance-2.0"),
                        "duration": apimart_video_duration(payload.duration),
                        "size": apimart_video_size(payload.aspect_ratio or payload.size),
                        "resolution": payload.resolution or "480p",
                    }
                    if image_with_roles and video_payload:
                        raise HTTPException(status_code=400, detail="APIMart Seedance 的 image_with_roles 不能和 video_urls 同时使用，请只保留图片首尾帧或参考视频其中一种。")
                    if image_with_roles:
                        body["image_with_roles"] = image_with_roles
                    elif image_payload:
                        body["image_urls"] = image_payload[:9]
                    if video_payload:
                        body["video_urls"] = video_payload
                    audio_payload = []
                    invalid_audios = []
                    for ref_url in (payload.audios or [])[:3]:
                        ref_url = str(ref_url or "").strip()
                        if not ref_url:
                            continue
                        normalized_audio_url = await upload_audio_for_apimart(client, provider, ref_url)
                        if valid_apimart_video_image_input(normalized_audio_url):
                            audio_payload.append(normalized_audio_url)
                        else:
                            reason = normalized_audio_url[4:] if isinstance(normalized_audio_url, str) and normalized_audio_url.startswith("ERR:") else "未知错误"
                            invalid_audios.append((ref_url, reason))
                    if invalid_audios:
                        first_url, first_reason = invalid_audios[0]
                        raise HTTPException(status_code=400, detail=f"参考音频无法转换为 APIMart 支持的地址：{invalid_video_image_preview(first_url)}\n原因：{first_reason}")
                    if audio_payload:
                        body["audio_urls"] = audio_payload
                    if payload.trusted_asset:
                        img_count = len(body.get("image_urls") or []) or len(image_with_roles)
                        body["prompt"] = apply_trusted_asset_prompt_index(
                            body["prompt"], img_count, len(video_payload), len(audio_payload)
                        )
                    if payload.seed is not None:
                        body["seed"] = payload.seed
                    if payload.return_last_frame:
                        body["return_last_frame"] = True
                    if payload.generate_audio:
                        body["generate_audio"] = True
            else:
                # 非 APIMart：data URL 方式（OpenAI / ComflyAI 接口）
                if is_volcengine and not volc_is_proxy:
                    text = str(payload.prompt or "").strip()
                    volc_model = selected_model(payload.model, "doubao-seedance-2-0-fast-260128")
                    body = {
                        "model": volc_model,
                        "content": [
                            {
                                "type": "text",
                                "text": text,
                            }
                        ],
                    }
                    # 火山方舟视频接口（含 Seedance 2.0 图生视频）均通过 body 的 duration 字段控制时长；
                    # 之前对 seedance-2.0 + 参考图的情况省略了 duration，导致接口回退到默认 5s。
                    body["duration"] = volcengine_video_duration(payload.duration)
                    if payload.aspect_ratio:
                        body["ratio"] = payload.aspect_ratio
                    resolution = volcengine_video_resolution(payload.resolution)
                    if resolution:
                        body["resolution"] = resolution
                    if payload.watermark:
                        body["watermark"] = True
                    if payload.generate_audio:
                        body["generate_audio"] = True
                    if payload.camerafixed:
                        body["camerafixed"] = True
                    image_like_urls = set()
                    frame_roles_used = {"first_frame": False, "last_frame": False}
                    volc_video_count = 0

                    def append_volcengine_image(url: str, role: str):
                        if role in {"first_frame", "last_frame"}:
                            if frame_roles_used.get(role):
                                return False
                            frame_roles_used[role] = True
                        elif role != "reference_image":
                            return False
                        body["content"].append({
                            "type": "image_url",
                            "image_url": {"url": url},
                            "role": role,
                        })
                        image_like_urls.add(url)
                        return True

                    for ref in payload.images[:9]:
                        url = volcengine_media_reference_url(ref.url, max_image_size=1536)
                        if not url:
                            continue
                        role = volcengine_content_role(ref.role, "image")
                        if role in {"first_frame", "last_frame"}:
                            append_volcengine_image(url, role)
                        elif payload.multimodal:
                            # 智能多帧/多参模式：多张图作为参考图提交，不能全部伪装成首帧。
                            append_volcengine_image(url, "reference_image")
                        elif not frame_roles_used["first_frame"]:
                            # 普通图生视频没有显式 role 时，只取第一张作为首帧。
                            append_volcengine_image(url, "first_frame")
                    for url in (payload.videos or [])[:3]:
                        text_url = str(url or "").strip()
                        if not text_url:
                            continue
                        media_url = volcengine_media_reference_url(text_url, max_image_size=1536 if looks_like_image_media_url(text_url) else None)
                        if not media_url:
                            continue
                        if media_url in image_like_urls or looks_like_image_media_url(media_url):
                            append_volcengine_image(media_url, "reference_image" if payload.multimodal else "first_frame")
                            continue
                        video_items = await volcengine_video_reference_content_items(media_url)
                        body["content"].extend(video_items)
                        volc_video_count += 1
                    for url in (payload.audios or [])[:3]:
                        duration = probe_local_audio_duration_seconds(url)
                        if duration is not None and (duration < 1.8 or duration > 15.2):
                            raise HTTPException(
                                status_code=400,
                                detail=f"参考音频时长 {duration:.2f} 秒超出范围：方舟 Seedance 参考音频要求在 1.8 ~ 15.2 秒之间，请裁剪后再插入。"
                            )
                        audio_url = volcengine_media_reference_url(url, max_image_size=None)
                        if not audio_url:
                            continue
                        body["content"].append({
                            "type": "audio_url",
                            "audio_url": {"url": audio_url},
                            "role": volcengine_content_role("", "audio"),
                        })
                    if payload.trusted_asset and body["content"] and body["content"][0].get("type") == "text":
                        body["content"][0]["text"] = apply_trusted_asset_prompt_index(
                            body["content"][0].get("text") or "", len(image_like_urls), volc_video_count, 0
                        )
                    if payload.seed is not None:
                        body["seed"] = payload.seed
                elif is_yuli:
                    # 玉玉API（yuli.host）视频走自有 veo 统一格式：POST /v1/video/create。
                    # 字段：model / prompt / images[]（http(s) URL）/ enhance_prompt /
                    # enable_upsample / aspect_ratio（仅 16:9、9:16）。无 duration 字段，
                    # 时长由模型本身决定，所以这里不传 duration/seconds。
                    yuli_images = []
                    for ref in payload.images[:3]:
                        ref_url = str(getattr(ref, "url", "") or "").strip()
                        if not ref_url:
                            continue
                        if ref_url.startswith("http://") or ref_url.startswith("https://"):
                            yuli_images.append(ref_url)
                        else:
                            # 本地/dataURL 图片转成 data URL 兜底传递
                            data_url = reference_to_data_url(ref.dict(), max_size=1536)
                            if data_url:
                                yuli_images.append(data_url)
                    prompt_text = str(payload.prompt or "")
                    # veo 只支持英文提示词：仅在含中文等非 ASCII 字符时才开启翻译增强，
                    # 纯英文原样传递（避免增强改写时引入人物等触发安全过滤的描述）。
                    needs_enhance = any(ord(ch) > 127 for ch in prompt_text)
                    body = {
                        "model": selected_model(payload.model, "veo3.1-fast"),
                        "prompt": prompt_text,
                        "enhance_prompt": needs_enhance,
                    }
                    if yuli_images:
                        body["images"] = yuli_images
                    ratio = str(payload.aspect_ratio or "").strip()
                    if ratio in {"16:9", "9:16"}:
                        body["aspect_ratio"] = ratio
                    if payload.enable_upsample:
                        body["enable_upsample"] = True
                else:
                    image_payload = []
                    for ref in payload.images[:4]:
                        if ref.url:
                            image_payload.append(reference_to_data_url(ref.dict(), max_size=1536))
                    body = {
                        "prompt": payload.prompt,
                        "model": selected_model(payload.model, "veo3-fast"),
                        "duration": payload.duration,
                        "watermark": payload.watermark,
                    }
                    if payload.aspect_ratio:
                        body["aspect_ratio"] = payload.aspect_ratio
                        body["ratio"] = payload.aspect_ratio
                    if payload.size:
                        body["size"] = payload.size
                    if payload.resolution:
                        body["resolution"] = payload.resolution
                    if image_payload:
                        body["images"] = image_payload
                    if payload.videos:
                        body["videos"] = [v for v in payload.videos if v]
                    if payload.enhance_prompt:
                        body["enhance_prompt"] = True
                    if payload.enable_upsample:
                        body["enable_upsample"] = True
                    if payload.seed is not None:
                        body["seed"] = payload.seed
                    if payload.camerafixed:
                        body["camerafixed"] = True
                    if payload.return_last_frame:
                        body["return_last_frame"] = True
                    if payload.generate_audio:
                        body["generate_audio"] = True
            # --- 发起视频生成请求 ---
            raw = None
            html_response = None
            last_response = None
            last_json_error = None
            total_candidates = len(submit_urls)
            for idx, candidate_url in enumerate(submit_urls):
                submit_url = candidate_url
                is_last = idx == total_candidates - 1
                response = await client.post(submit_url, headers=api_headers(provider=provider), json=body)
                last_response = response
                if response.status_code >= 400:
                    # 404/405（或直接返回网页 HTML）通常表示该平台不支持这个端点路径——
                    # 例如有的站点只实现了统一格式的 /v2/videos/generations，而我们先试了 /v1。
                    # 这种情况要继续尝试下一个候选端点（关键修复：以前在这里直接 raise_for_status，
                    # 第一个 /v1 报错就抛出，永远轮不到 /v2，表现为“接口错误”）。
                    # 其它错误（模型不支持/时长/额度等请求被拒）说明端点是存在的，直接抛出交给外层友好提示。
                    endpoint_missing = response.status_code in (404, 405) or looks_like_html_response(response.text)
                    if endpoint_missing and not is_last:
                        continue
                    response.raise_for_status()
                try:
                    raw = response.json()
                    break
                except Exception as exc:
                    last_json_error = exc
                    if looks_like_html_response(response.text):
                        html_response = response
                        continue
                    if not is_last:
                        continue
                    resp_text = response.text[:500]
                    raise HTTPException(status_code=502, detail=f"上游视频接口返回非 JSON 响应（状态 {response.status_code}）：{resp_text}")
            if raw is None:
                resp = html_response or last_response
                status_code = getattr(resp, "status_code", 200)
                resp_text = (getattr(resp, "text", "") or "")[:500]
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"上游视频接口返回了网页 HTML，而不是 JSON（状态 {status_code}）。\n\n"
                        f"这通常表示 API 设置里的 Base URL 指到了第三方聚合平台的管理后台/网页入口，"
                        f"或该平台不支持当前视频接口路径。请确认 Base URL 是接口地址，例如以 /v1 结尾的 OpenAI 兼容地址，"
                        f"并确认该平台实际支持视频生成端点。\n\n原始响应：{resp_text}"
                    )
                ) from last_json_error
            task_id = extract_task_id(raw) or raw.get("task_id") or raw.get("id")
            result = raw
            if task_id and not video_output_urls(raw):
                result = await wait_for_video_task(client, provider, task_id, submit_url)
            urls = video_output_urls(result)
            if not urls:
                raise HTTPException(status_code=502, detail=f"视频生成成功但没有返回视频：{result}")
            local_urls = [await save_remote_video_to_output(url) for url in urls]
            return {"videos": local_urls, "task_id": task_id, "raw": result}
    except httpx.HTTPStatusError as exc:
        text = exc.response.text
        try:
            requested_model = body.get("model", "") or payload.model or ""
        except NameError:
            requested_model = payload.model or ""
        provider_name = provider.get('name') or provider['id']
        # 1) 模型名不在上游支持范围 → 从错误信息里抽取合法列表展示
        valid_models_match = re.search(r"not in\s*\[([^\]]+)\]", text)
        if valid_models_match:
            valid_models = [m.strip() for m in valid_models_match.group(1).split(",") if m.strip()]
            sample = valid_models[:30]
            more = f"（共 {len(valid_models)} 个，仅显示前 {len(sample)} 个）" if len(valid_models) > len(sample) else ""
            hint = (
                f"上游「{provider_name}」不识别模型「{requested_model}」。\n\n"
                f"上游支持的视频模型清单{more}：\n  {', '.join(sample)}\n\n"
                f"请到「API 设置」里把视频模型改成上面列表中的一个。"
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        # 2) 模型名合法但账号没开通通道
        if "channel not found" in text or "model_not_found" in text:
            hint = (
                f"上游「{provider_name}」识别了模型「{requested_model}」，但你的 API Key 账号下**没有该模型的可用通道**。\n\n"
                f"原因：你的账号没开通这个模型的访问权限（付费/订阅相关）。\n\n"
                f"解决方法：\n"
                f"  1. 登录 {provider.get('base_url') or '上游平台'} 控制台，开通该模型 / 充值；\n"
                f"  2. 或在「API 设置」里把视频模型改成你账号已开通的型号（如 veo3-fast / veo2-fast / sora-2 等）。"
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        if "text.duration" in text or "specified duration is not supported" in text:
            hint = (
                f"上游「{provider_name}」模型「{requested_model}」不支持当前时长参数。\n\n"
                f"不同视频模型支持的时长不一样；如果选择了模型不支持的时长，上游可能报错，"
                f"也可能自动按平台默认时长生成，例如 5 秒。\n\n"
                f"请把视频时长切回该模型支持的值，或改用支持更长时长的视频模型。"
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        if "audio duration" in text.lower():
            too_long = "less than or equal" in text.lower() or "15.2" in text
            bound_hint = "太长（超过 15.2 秒）" if too_long else "太短（不足 1.8 秒）"
            hint = (
                f"上游「{provider_name}」模型「{requested_model}」拒绝了参考音频：时长{bound_hint}。\n\n"
                f"方舟 Seedance 的参考音频时长必须在 1.8 ~ 15.2 秒之间，"
                f"请把音频裁剪到这个区间后再作为参考音频输入。"
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        if "inputimagesensitivecontentdetected" in text.lower() or "privacyinformation" in text.lower() or "may contain real person" in text.lower():
            hint = (
                f"上游「{provider_name}」拦截了输入参考图，原因是图片里可能包含真人身份/隐私信息。\n\n"
                f"这不是代码协议错误，而是火山视频模型的内容安全策略。\n\n"
                f"建议你这样处理：\n"
                f"  1. 改用非真人参考图，例如插画、AI 头像、商品图、场景图；\n"
                f"  2. 先把真人脸做模糊、遮挡、裁掉，或转成明显的二次元/插画风；\n"
                f"  3. 如果只是想做文生视频，先去掉参考图只保留文字提示词测试。"
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        raise HTTPException(status_code=exc.response.status_code, detail=f"上游视频接口错误：{text}") from exc
    except httpx.HTTPError as exc:
        log_net_error(f"视频 网络/TLS错误 provider={provider.get('id')} model={payload.model}", exc)
        raise HTTPException(status_code=502, detail=f"请求上游视频接口失败：{exc}") from exc

# --- Canvas LLM ---
