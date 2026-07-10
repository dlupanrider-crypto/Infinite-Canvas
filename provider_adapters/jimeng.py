"""Jimeng CLI execution, media preparation, and result parsing."""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import uuid
from typing import Any

import httpx
from fastapi import HTTPException

from api_models import CanvasVideoRequest

try:
    JIMENG_DEFAULT_POLL_SECONDS = max(
        1,
        min(3600, int(os.getenv("JIMENG_POLL_SECONDS", "900"))),
    )
except Exception:
    JIMENG_DEFAULT_POLL_SECONDS = 900


JIMENG_EXPORTS = (
    "JIMENG_MIN_CLI_VERSION",
    "jimeng_env_value",
    "jimeng_use_wsl",
    "jimeng_cli_executable",
    "decode_utf16_auto",
    "decode_wsl_output",
    "jimeng_wsl_base_args",
    "jimeng_clean_wsl_stderr",
    "windows_path_to_wsl",
    "wsl_path_to_windows",
    "jimeng_cli_path_arg",
    "jimeng_poll_seconds",
    "jimeng_extract_json",
    "run_jimeng_cli",
    "jimeng_parse_version",
    "jimeng_cli_version",
    "jimeng_command",
    "jimeng_decode_cli_output",
    "jimeng_login_text",
    "jimeng_login_qr_from_text",
    "jimeng_login_reader",
    "jimeng_submit_id",
    "JimengPendingError",
    "jimeng_queue_info",
    "jimeng_pending_payload",
    "jimeng_failure_reason",
    "jimeng_collect_media_values",
    "jimeng_output_values",
    "jimeng_ratio_from_size",
    "jimeng_normalize_image_model",
    "jimeng_image_model_version",
    "jimeng_image_resolution",
    "jimeng_video_resolution",
    "jimeng_video_duration_range",
    "jimeng_video_duration",
    "jimeng_transition_duration",
    "jimeng_video_model_version",
    "jimeng_video_resolution_arg",
    "jimeng_video_ratio_arg",
    "jimeng_append_model_resolution_args",
    "jimeng_video_ref_role",
    "jimeng_video_ref_url",
    "jimeng_local_output_url",
    "jimeng_store_output_value",
    "jimeng_query_result",
    "jimeng_store_outputs",
    "jimeng_prepare_local_media",
    "generate_jimeng_provider_image",
    "generate_jimeng_video",
)


def configure_jimeng_adapter(**dependencies: Any) -> None:
    required = {
        "BASE_DIR",
        "JIMENG_LOGIN_SESSION",
        "OUTPUT_OUTPUT_DIR",
        "content_type_for_path",
        "output_file_from_url",
        "output_path_for",
        "output_url_for",
        "parse_size_pair",
        "read_api_env_value",
        "save_ai_image_to_output",
        "save_remote_video_to_output",
    }
    missing = sorted(required - dependencies.keys())
    if missing:
        raise RuntimeError(f"Jimeng adapter missing dependencies: {', '.join(missing)}")
    globals().update(dependencies)


def export_jimeng_adapter(target: dict[str, Any]) -> None:
    for name in JIMENG_EXPORTS:
        target[name] = globals()[name]

def jimeng_env_value(key):
    return os.getenv(key, "") or read_api_env_value(key)

def jimeng_use_wsl():
    value = str(jimeng_env_value("JIMENG_USE_WSL") or "").strip().lower()
    return value in {"1", "true", "yes", "on", "wsl"}

def jimeng_cli_executable():
    if jimeng_use_wsl():
        return shutil.which("wsl.exe") or shutil.which("wsl") or "wsl.exe"
    configured = str(
        jimeng_env_value("JIMENG_BIN")
        or jimeng_env_value("DREAMINA_BIN")
        or ""
    ).strip()
    if configured:
        return configured
    return shutil.which("dreamina") or shutil.which("dreamina.exe") or shutil.which("dreamina.cmd") or ""

def decode_utf16_auto(raw: bytes) -> str:
    # WSL/Windows interop emits UTF-16 for null-heavy diagnostics, but the
    # endianness varies by source (console vs proxy vs subprocess), so a
    # hard-coded "utf-16le" silently byte-swaps UTF-16BE text into garbage
    # (e.g. "localhost" -> 氀漀挀愀氀栀漀猀琀). Decode both ways and keep
    # whichever produces more plain ASCII, since diagnostics are ASCII-heavy.
    try:
        le = raw.decode("utf-16le", errors="ignore")
    except Exception:
        le = ""
    try:
        be = raw.decode("utf-16be", errors="ignore")
    except Exception:
        be = ""
    def ascii_score(text):
        return sum(1 for ch in text if 0x20 <= ord(ch) <= 0x7e)
    return le if ascii_score(le) >= ascii_score(be) else be

def decode_wsl_output(data: bytes) -> str:
    data = data or b""
    if not data:
        return ""

    # WSL can mix UTF-16 diagnostics with UTF-8 command output in the same
    # stream. Decode per line so a WSL proxy warning does not corrupt CLI errors.
    if b"\x00" in data[:400]:
        lines = []
        for raw_line in data.splitlines():
            if not raw_line:
                lines.append("")
                continue
            sample = raw_line[:200]
            nul_ratio = sample.count(0) / max(1, len(sample))
            if nul_ratio > 0.2:
                try:
                    lines.append(decode_utf16_auto(raw_line))
                    continue
                except Exception:
                    pass
            lines.append(raw_line.decode("utf-8-sig", errors="ignore"))
        return "\n".join(lines)
    if b"\x00" in data[:200]:
        try:
            return decode_utf16_auto(data)
        except Exception:
            pass
    return data.decode("utf-8-sig", errors="ignore")

def jimeng_wsl_base_args(exe="wsl.exe"):
    configured = str(jimeng_env_value("JIMENG_WSL_DISTRO") or "").strip()
    names = []
    try:
        proc = subprocess.run(
            [exe, "-l", "-q"],
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        names = [
            line.replace("\x00", "").strip().lstrip("*").strip()
            for line in decode_wsl_output(proc.stdout).splitlines()
            if line.replace("\x00", "").strip()
        ]
    except Exception:
        names = []
    if configured and (not names or configured in names):
        return ["-d", configured]
    if configured and names:
        print(f"JIMENG_WSL_DISTRO={configured} 不存在，已回退自动选择。可用发行版：{names}")
    try:
        ubuntu = next((name for name in names if re.match(r"^Ubuntu($|-)", name)), "")
        if ubuntu:
            return ["-d", ubuntu]
    except Exception:
        pass
    return []

def jimeng_clean_wsl_stderr(text):
    lines = []
    skip_next_warning_context = False
    for line in str(text or "").splitlines():
        clean = line.replace("\x00", "").strip()
        low = clean.lower()
        is_proxy_warning = "localhost" in low and "wsl" in low and ("nat" in low or "proxy" in low or "代理" in clean)
        is_python_warning = "requestsdependencywarning" in low or (skip_next_warning_context and clean.startswith("warnings.warn("))
        skip_next_warning_context = "requestsdependencywarning" in low
        if clean and not is_proxy_warning and not is_python_warning:
            lines.append(clean)
    return "\n".join(lines).strip()

def windows_path_to_wsl(path):
    text = str(path or "").replace("\\", "/")
    match = re.match(r"^([A-Za-z]):/(.*)$", text)
    if match:
        return f"/mnt/{match.group(1).lower()}/{match.group(2)}"
    return text

def wsl_path_to_windows(path):
    text = str(path or "").strip()
    match = re.match(r"^/mnt/([A-Za-z])/(.*)$", text)
    if match:
        tail = match.group(2).replace("/", "\\")
        return f"{match.group(1).upper()}:\\{tail}"
    return text

def jimeng_cli_path_arg(path):
    return windows_path_to_wsl(path) if jimeng_use_wsl() else path

def jimeng_poll_seconds(default=JIMENG_DEFAULT_POLL_SECONDS):
    try:
        return max(1, min(3600, int(os.getenv("JIMENG_POLL_SECONDS", str(default)) or default)))
    except Exception:
        return default

def jimeng_extract_json(text):
    text = str(text or "").strip()
    if not text:
        return {}
    decoder = json.JSONDecoder()
    parsed = []
    for i, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            obj, _end = decoder.raw_decode(text[i:])
            if not text[:i].strip():
                return obj
            parsed.append((i, obj))
        except Exception:
            continue
    def score(item):
        _idx, obj = item
        if not isinstance(obj, dict):
            return 1
        keys = {str(key).lower() for key in obj.keys()}
        weight = 0
        for key in ("submit_id", "gen_status", "result_json", "images", "videos", "data", "total_credit"):
            if key in keys:
                weight += 10
        return weight
    return max(parsed, key=score)[1] if parsed else {"text": text}

async def run_jimeng_cli(args, timeout=120, raw_text=False):
    exe = jimeng_cli_executable()
    if not exe:
        raise HTTPException(status_code=400, detail="未找到 dreamina CLI。请先安装：curl -fsSL https://jimeng.jianying.com/cli | bash，并完成 dreamina login。")
    clean_args = [str(arg) for arg in args if str(arg) != ""]
    command = jimeng_command(clean_args, exe)
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"即梦 CLI 执行超时：{' '.join(command[:3])}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"未找到即梦 CLI：{exe}") from exc
    out_text, clean_err_text = jimeng_decode_cli_output(stdout, stderr)
    if proc.returncode != 0:
        message = clean_err_text or out_text or f"exit={proc.returncode}"
        raise HTTPException(status_code=502, detail=f"即梦 CLI 调用失败：{message[:1000]}")
    # 帮助等纯文本输出不应被 JSON 提取吞掉（如 [0.5, 8] 会被误判为结果）
    if raw_text:
        return {"_stdout": out_text, "_stderr": clean_err_text}
    raw = jimeng_extract_json(f"{out_text}\n{clean_err_text}".strip())
    if isinstance(raw, dict):
        raw.setdefault("_stdout", out_text)
        if clean_err_text:
            raw.setdefault("_stderr", clean_err_text)
    return raw

# 旧版 dreamina CLI 将 submit_id 用 16 位 hex，v1.4.2 起升级为 UUID，
# 与当前轮询逻辑不兼容。这里做尽力而为的版本探测，失败不阻断主流程。
JIMENG_MIN_CLI_VERSION = (1, 4, 2)

def jimeng_parse_version(text):
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", str(text or ""))
    if not match:
        return None
    return tuple(int(part) for part in match.groups())

async def jimeng_cli_version():
    for flag in ("--version", "-V", "version"):
        try:
            raw = await run_jimeng_cli([flag], timeout=15)
        except HTTPException:
            continue
        text = raw if isinstance(raw, str) else (raw.get("_stdout") or raw.get("_stderr") or "" if isinstance(raw, dict) else "")
        version = jimeng_parse_version(text)
        if version:
            return version, str(text).strip()
    return None, ""

def jimeng_command(clean_args, exe=None):
    exe = exe or jimeng_cli_executable()
    if jimeng_use_wsl():
        shell_line = (
            ". ~/.profile >/dev/null 2>&1 || true; . ~/.bashrc >/dev/null 2>&1 || true; "
            "DREAMINA_BIN=$(command -v dreamina || find \"$HOME\" -maxdepth 4 -type f -name dreamina 2>/dev/null | head -n 1); "
            "if [ -z \"$DREAMINA_BIN\" ]; then echo 'dreamina CLI not found in WSL' >&2; exit 127; fi; "
            "\"$DREAMINA_BIN\" " + " ".join(shlex.quote(arg) for arg in clean_args)
        )
        return [exe, *jimeng_wsl_base_args(exe), "-e", "sh", "-lc", shell_line]
    return [exe, *clean_args]

def jimeng_decode_cli_output(stdout, stderr):
    out_text = (decode_wsl_output(stdout) if jimeng_use_wsl() else stdout.decode("utf-8", errors="replace")).strip()
    err_text = (decode_wsl_output(stderr) if jimeng_use_wsl() else stderr.decode("utf-8", errors="replace")).strip()
    clean_err_text = jimeng_clean_wsl_stderr(err_text) if jimeng_use_wsl() else err_text
    return out_text, clean_err_text

def jimeng_login_text():
    parts = []
    for key in ("stdout", "stderr"):
        value = str(JIMENG_LOGIN_SESSION.get(key) or "").strip()
        if value:
            parts.append(value)
    return "\n".join(parts).strip()

def jimeng_login_qr_from_text(text):
    text = str(text or "")
    candidates = []
    patterns = [
        r"(https?://[^\s\"'<>]+)",
        r"(dreamina://[^\s\"'<>]+)",
        r"(data:image/[^\s\"'<>]+)",
    ]
    for pattern in patterns:
        candidates.extend(re.findall(pattern, text))
    for value in candidates:
        if "login" in value.lower() or "qr" in value.lower() or value.startswith(("data:image", "dreamina://")):
            return value
    return candidates[0] if candidates else ""

async def jimeng_login_reader(proc):
    async def read_stream(stream, key):
        while True:
            chunk = await stream.readline()
            if not chunk:
                break
            text = (decode_wsl_output(chunk) if jimeng_use_wsl() else chunk.decode("utf-8", errors="replace"))
            if key == "stderr":
                text = jimeng_clean_wsl_stderr(text)
            if text:
                JIMENG_LOGIN_SESSION[key] = str(JIMENG_LOGIN_SESSION.get(key) or "") + text
    await asyncio.gather(read_stream(proc.stdout, "stdout"), read_stream(proc.stderr, "stderr"))

def jimeng_submit_id(raw):
    found = []
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in {"submit_id", "submitid", "task_id", "taskid"} and item:
                    found.append(str(item))
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(raw)
    return found[0] if found else ""

class JimengPendingError(Exception):
    """即梦任务还在云端排队/生成（轮询超时但未失败）。submit_id 可用于后续续查。"""
    def __init__(self, submit_id, kind="image", queue_info=None, raw=None):
        self.submit_id = str(submit_id or "")
        self.kind = kind or "image"
        self.queue_info = queue_info if isinstance(queue_info, dict) else {}
        self.raw = raw
        super().__init__(f"jimeng pending submit_id={self.submit_id}")

def jimeng_queue_info(raw):
    """从即梦原始返回里就近取出 queue_info（含 queue_idx/queue_length/queue_status）。"""
    found = []
    def visit(value):
        if isinstance(value, dict):
            qi = value.get("queue_info")
            if isinstance(qi, dict) and qi:
                found.append(qi)
            for item in value.values():
                if isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(raw)
    return found[0] if found else {}

def jimeng_pending_payload(exc: "JimengPendingError"):
    qi = exc.queue_info or {}
    idx = qi.get("queue_idx")
    length = qi.get("queue_length")
    if idx is not None and length is not None:
        msg = f"即梦云端排队中（第 {idx}/{length} 位），任务未丢失，可继续等待或手动查询。submit_id={exc.submit_id}"
    else:
        msg = f"即梦任务仍在生成中，任务未丢失。submit_id={exc.submit_id}"
    return {
        "jimeng_pending": True,
        "submit_id": exc.submit_id,
        "kind": exc.kind,
        "queue_info": qi,
        "message": msg,
    }

def jimeng_failure_reason(raw):
    found = []
    def visit(value):
        if isinstance(value, dict):
            status = str(value.get("gen_status") or value.get("status") or "").strip().lower()
            reason = value.get("fail_reason") or value.get("failReason") or value.get("error") or value.get("message") or value.get("msg")
            if reason and (status in {"fail", "failed", "error"} or "fail" in str(reason).lower() or "invalid param" in str(reason).lower()):
                found.append(str(reason))
            for item in value.values():
                if isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(raw)
    return found[0] if found else ""

def jimeng_collect_media_values(value, outputs):
    media_ext = re.compile(r"\.(png|jpe?g|webp|gif|bmp|mp4|webm|mov|m4v|avi|mkv)(\?|#|$)", re.I)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return
        if text.startswith(("http://", "https://", "/output/", "/assets/", "file://")) or media_ext.search(text):
            outputs.append(text)
        return
    if isinstance(value, list):
        for item in value:
            jimeng_collect_media_values(item, outputs)
        return
    if isinstance(value, dict):
        for key in (
            "url", "urls", "image", "images", "image_url", "image_urls",
            "video", "videos", "video_url", "video_urls", "output", "outputs",
            "result", "results", "file", "files", "path", "paths",
            "download_url", "download_urls", "downloadUrl", "file_path", "filePath",
        ):
            if key in value:
                jimeng_collect_media_values(value.get(key), outputs)
        for item in value.values():
            if isinstance(item, (dict, list)):
                jimeng_collect_media_values(item, outputs)

def jimeng_output_values(raw):
    outputs = []
    jimeng_collect_media_values(raw, outputs)
    deduped = []
    for value in outputs:
        if value not in deduped:
            deduped.append(value)
    return deduped

JIMENG_RATIO_CHOICES = [(21, 9), (16, 9), (3, 2), (4, 3), (1, 1), (3, 4), (2, 3), (9, 16)]
def jimeng_ratio_from_size(size, fallback="1:1"):
    width, height = parse_size_pair(size)
    if not width or not height:
        return fallback
    ratio = width / max(1, height)
    left, right = min(JIMENG_RATIO_CHOICES, key=lambda item: abs(ratio - item[0] / item[1]))
    return f"{left}:{right}"

# 官方 dreamina 支持的图片模型（来自 text2image/image2image -h）。
# image2image 不支持 3.0/3.1。
JIMENG_TEXT2IMAGE_MODELS = {"3.0", "3.1", "4.0", "4.1", "4.5", "4.6", "5.0"}
JIMENG_IMAGE2IMAGE_MODELS = {"4.0", "4.1", "4.5", "4.6", "5.0"}

def jimeng_normalize_image_model(model):
    match = re.search(r"(\d+\.\d+)", str(model or ""))
    return match.group(1) if match else ""

def jimeng_image_model_version(model, mode="text2image"):
    version = jimeng_normalize_image_model(model)
    allowed = JIMENG_IMAGE2IMAGE_MODELS if mode == "image2image" else JIMENG_TEXT2IMAGE_MODELS
    return version if version in allowed else ""

def jimeng_image_resolution(model, size, mode="text2image"):
    text = str(model or "").lower()
    if "4k" in text:
        desired = "4k"
    elif "1k" in text:
        desired = "1k"
    elif "2k" in text:
        desired = "2k"
    else:
        width, height = parse_size_pair(size)
        desired = "4k" if max(width, height) > 2048 else "2k"
    # 按官方规则收敛到模型允许的分辨率
    version = jimeng_normalize_image_model(model)
    if mode == "image2image":
        # image2image 只支持 2k/4k
        return "4k" if desired == "4k" else "2k"
    if version in ("3.0", "3.1"):
        # 3.0/3.1 只支持 1k/2k
        return "1k" if desired == "1k" else "2k"
    # 4.x/5.0 只支持 2k/4k
    return "4k" if desired == "4k" else "2k"

# 仅 VIP seedance 支持 1080P；其余模型最高 720P（官方无 480P 选项）
JIMENG_VIDEO_1080P_MODELS = {"seedance2.0_vip", "seedance2.0fast_vip"}

def jimeng_video_resolution(model, resolution):
    version = jimeng_video_model_version(model)
    requested = str(resolution or "").strip().upper()
    if requested not in {"480P", "720P", "1080P"}:
        text = str(model or "").lower()
        requested = "1080P" if "1080" in text else "720P"
    if requested == "1080P" and version in JIMENG_VIDEO_1080P_MODELS:
        return "1080P"
    return "720P"

# 各模型支持的时长区间（秒）：3.0 系列 3-10，3.5pro 4-12，seedance 4-15
def jimeng_video_duration_range(model):
    version = jimeng_video_model_version(model)
    if version in ("3.0", "3.0fast", "3.0pro"):
        return 3, 10
    if version == "3.5pro":
        return 4, 12
    return 4, 15

def jimeng_video_duration(duration, model=None):
    low, high = jimeng_video_duration_range(model)
    default = max(low, min(high, 5))
    try:
        text = str(duration).strip() if duration is not None else ""
        value = default if text == "" else int(text)
    except Exception:
        value = default
    return max(low, min(high, value))

def jimeng_transition_duration(total_duration, transition_count):
    count = max(1, int(transition_count or 1))
    try:
        total = float(total_duration or 5)
    except Exception:
        total = 5.0
    return max(0.5, min(8.0, total / count))

def jimeng_video_model_version(model):
    value = str(model or "").strip()
    low = value.lower()
    aliases = {
        "seedance2.0fast_vip": "seedance2.0fast_vip",
        "seedance2.0_vip": "seedance2.0_vip",
        "seedance2.0fast": "seedance2.0fast",
        "seedance2.0": "seedance2.0",
        "3.0_fast": "3.0fast",
        "3.0fast": "3.0fast",
        "3.0_pro": "3.0pro",
        "3.0pro": "3.0pro",
        "3.5_pro": "3.5pro",
        "3.5pro": "3.5pro",
        "3.0": "3.0",
    }
    for key, mapped in aliases.items():
        if key in low:
            return mapped
    return ""

def jimeng_video_resolution_arg(model, resolution):
    return jimeng_video_resolution(model, resolution).lower()

def jimeng_video_ratio_arg(aspect_ratio):
    value = str(aspect_ratio or "").strip()
    allowed = {"1:1", "3:4", "16:9", "4:3", "9:16", "21:9"}
    if value in allowed:
        return value
    return ""

def jimeng_append_model_resolution_args(args, payload: CanvasVideoRequest, include_model=False):
    model_version = jimeng_video_model_version(payload.model)
    if include_model and model_version:
        args.append(f"--model_version={model_version}")
    if payload.resolution:
        args.append(f"--video_resolution={jimeng_video_resolution_arg(payload.model, payload.resolution)}")

def jimeng_video_ref_role(ref):
    role = getattr(ref, "role", "")
    if isinstance(ref, dict):
        role = ref.get("role", role)
    return str(role or "").lower()

def jimeng_video_ref_url(ref):
    url = getattr(ref, "url", "")
    if isinstance(ref, dict):
        url = ref.get("url", url)
    return str(url or "").strip()

def jimeng_local_output_url(path, kind="image"):
    path = os.path.abspath(str(path or ""))
    if not os.path.isfile(path):
        return ""
    output_root = os.path.abspath(OUTPUT_OUTPUT_DIR)
    try:
        if os.path.commonpath([output_root, path]) == output_root:
            return output_url_for(os.path.basename(path), "output")
    except Exception:
        pass
    ext = os.path.splitext(path)[1].lower()
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"}
    if ext not in allowed:
        ct = content_type_for_path(path)
        ext = ".mp4" if ct.startswith("video/") else ".png"
    prefix = "jimeng_video_" if kind == "video" else "jimeng_"
    filename = f"{prefix}{uuid.uuid4().hex[:10]}{ext}"
    dest = output_path_for(filename, "output")
    shutil.copyfile(path, dest)
    return output_url_for(filename, "output")

async def jimeng_store_output_value(value, kind="image"):
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("/output/") or text.startswith("/assets/"):
        return text
    if text.startswith("file://"):
        text = urllib.parse.unquote(urllib.parse.urlparse(text).path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", text):
            text = text[1:]
    if jimeng_use_wsl() and text.startswith("/mnt/"):
        text = wsl_path_to_windows(text)
    if text.startswith(("http://", "https://")):
        if kind == "video":
            return await save_remote_video_to_output(text, prefix="jimeng_video_")
        return await save_ai_image_to_output({"type": "url", "value": text}, prefix="jimeng_")
    if os.path.isfile(text):
        return jimeng_local_output_url(text, kind)
    return ""

async def jimeng_query_result(submit_id, kind="image"):
    args = [
        "query_result",
        f"--submit_id={submit_id}",
        f"--download_dir={jimeng_cli_path_arg(OUTPUT_OUTPUT_DIR)}",
    ]
    return await run_jimeng_cli(args, timeout=min(300, jimeng_poll_seconds() + 60))

async def jimeng_store_outputs(raw, kind="image", allow_query=True):
    failure = jimeng_failure_reason(raw)
    if failure:
        raise HTTPException(status_code=502, detail=f"即梦生成失败：{failure}")
    values = jimeng_output_values(raw)
    urls = []
    for value in values:
        local_url = await jimeng_store_output_value(value, kind)
        if local_url and local_url not in urls:
            urls.append(local_url)
    if urls:
        return urls
    submit_id = jimeng_submit_id(raw)
    if submit_id and allow_query:
        queried = await jimeng_query_result(submit_id, kind)
        try:
            return await jimeng_store_outputs(queried, kind, allow_query=False)
        except HTTPException as exc:
            if getattr(exc, "status_code", None) == 502:
                status_text = json.dumps(queried, ensure_ascii=False)[:800] if isinstance(queried, (dict, list)) else str(queried)[:800]
                raise HTTPException(status_code=502, detail=f"即梦任务已返回但没有下载到媒体：{status_text}") from exc
            raise
    status_text = json.dumps(raw, ensure_ascii=False)[:800] if isinstance(raw, (dict, list)) else str(raw)[:800]
    if submit_id:
        raise JimengPendingError(submit_id, kind, jimeng_queue_info(raw), raw)
    raise HTTPException(status_code=502, detail=f"即梦 CLI 未返回可用媒体结果：{status_text}")

async def jimeng_prepare_local_media(ref_url, kind="image"):
    text = str(ref_url or "").strip()
    if not text:
        return "", []
    if text.startswith("/output/") or text.startswith("/assets/"):
        path = output_file_from_url(text)
        if path:
            return path, []
        raise HTTPException(status_code=404, detail=f"即梦参考素材不存在：{text}")
    if text.startswith("file://"):
        path = urllib.parse.unquote(urllib.parse.urlparse(text).path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        if os.path.isfile(path):
            return path, []
    if os.path.isfile(text):
        return text, []
    suffix = ".mp4" if kind == "video" else (".mp3" if kind == "audio" else ".png")
    temp_paths = []
    if text.startswith("data:"):
        if ";base64," not in text:
            raise HTTPException(status_code=400, detail="即梦参考素材 data URL 缺少 base64 数据")
        header, encoded = text.split(";base64,", 1)
        mime = header.split(":", 1)[1].split(";", 1)[0] if ":" in header else ""
        suffix = mimetypes.guess_extension(mime) or suffix
        fd, path = tempfile.mkstemp(prefix="jimeng_ref_", suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64decode(encoded))
        temp_paths.append(path)
        return path, temp_paths
    if text.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=20.0), follow_redirects=True) as client:
            response = await client.get(text)
            response.raise_for_status()
            clean_path = urllib.parse.urlparse(text).path
            suffix = os.path.splitext(clean_path)[1] or mimetypes.guess_extension(response.headers.get("content-type", "")) or suffix
            fd, path = tempfile.mkstemp(prefix="jimeng_ref_", suffix=suffix)
            with os.fdopen(fd, "wb") as f:
                f.write(response.content)
            temp_paths.append(path)
            return path, temp_paths
    raise HTTPException(status_code=400, detail=f"即梦 CLI 只支持本地文件参考素材，无法读取：{text[:120]}")

async def generate_jimeng_provider_image(prompt, size, model, reference_images=None, provider=None):
    refs = [ref for ref in (reference_images or []) if ref.get("url")]
    temp_paths = []
    try:
        args = []
        if refs:
            image_path, created = await jimeng_prepare_local_media(refs[0].get("url"), "image")
            temp_paths.extend(created)
            model_version = jimeng_image_model_version(model, "image2image")
            args = [
                "image2image",
                f"--images={jimeng_cli_path_arg(image_path)}",
                f"--prompt={prompt}",
                f"--resolution_type={jimeng_image_resolution(model, size, 'image2image')}",
                f"--poll={jimeng_poll_seconds()}",
            ]
            if model_version:
                args.append(f"--model_version={model_version}")
        else:
            model_version = jimeng_image_model_version(model, "text2image")
            args = [
                "text2image",
                f"--prompt={prompt}",
                f"--ratio={jimeng_ratio_from_size(size)}",
                f"--resolution_type={jimeng_image_resolution(model, size, 'text2image')}",
                f"--poll={jimeng_poll_seconds()}",
            ]
            if model_version:
                args.append(f"--model_version={model_version}")
        raw = await run_jimeng_cli(args, timeout=jimeng_poll_seconds() + 120)
        urls = await jimeng_store_outputs(raw, "image")
        return {"type": "url", "value": urls[0]}, raw
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass

async def generate_jimeng_video(payload: CanvasVideoRequest, provider):
    image_refs = [ref for ref in (payload.images or []) if jimeng_video_ref_url(ref)]
    video_refs = [url for url in (payload.videos or []) if str(url or "").strip()]
    audio_refs = [url for url in (payload.audios or []) if str(url or "").strip()][:3]
    duration = jimeng_video_duration(payload.duration, payload.model)
    temp_paths = []
    try:
        if payload.multimodal or video_refs or audio_refs:
            image_paths = []
            video_paths = []
            audio_paths = []
            for ref in image_refs[:9]:
                image_path, created = await jimeng_prepare_local_media(jimeng_video_ref_url(ref), "image")
                temp_paths.extend(created)
                image_paths.append(image_path)
            for ref_url in video_refs[:3]:
                video_path, created = await jimeng_prepare_local_media(ref_url, "video")
                temp_paths.extend(created)
                video_paths.append(video_path)
            for ref_url in audio_refs:
                audio_path, created = await jimeng_prepare_local_media(ref_url, "audio")
                temp_paths.extend(created)
                audio_paths.append(audio_path)
            args = [
                "multimodal2video",
                f"--prompt={payload.prompt}",
                f"--duration={duration}",
                f"--poll={jimeng_poll_seconds()}",
            ]
            ratio = jimeng_video_ratio_arg(payload.aspect_ratio)
            if ratio:
                args.append(f"--ratio={ratio}")
            jimeng_append_model_resolution_args(args, payload, include_model=True)
            for image_path in image_paths:
                args.append(f"--image={jimeng_cli_path_arg(image_path)}")
            for video_path in video_paths:
                args.append(f"--video={jimeng_cli_path_arg(video_path)}")
            for audio_path in audio_paths:
                args.append(f"--audio={jimeng_cli_path_arg(audio_path)}")
        elif len(image_refs) >= 2:
            first_frame = next((ref for ref in image_refs if jimeng_video_ref_role(ref) == "first_frame"), None)
            last_frame = next((ref for ref in image_refs if jimeng_video_ref_role(ref) == "last_frame"), None)
            if first_frame and last_frame:
                first_path, created = await jimeng_prepare_local_media(jimeng_video_ref_url(first_frame), "image")
                temp_paths.extend(created)
                last_path, created = await jimeng_prepare_local_media(jimeng_video_ref_url(last_frame), "image")
                temp_paths.extend(created)
                args = [
                    "frames2video",
                    f"--first={jimeng_cli_path_arg(first_path)}",
                    f"--last={jimeng_cli_path_arg(last_path)}",
                    f"--prompt={payload.prompt}",
                    f"--duration={duration}",
                    f"--poll={jimeng_poll_seconds()}",
                ]
                jimeng_append_model_resolution_args(args, payload, include_model=True)
            else:
                image_paths = []
                for ref in image_refs:
                    image_path, created = await jimeng_prepare_local_media(jimeng_video_ref_url(ref), "image")
                    temp_paths.extend(created)
                    image_paths.append(image_path)
                args = [
                    "multiframe2video",
                    f"--images={','.join(jimeng_cli_path_arg(path) for path in image_paths)}",
                    f"--prompt={payload.prompt}",
                    f"--duration={duration}",
                    f"--poll={jimeng_poll_seconds()}",
                ]
                jimeng_append_model_resolution_args(args, payload, include_model=True)
        elif image_refs:
            image_path, created = await jimeng_prepare_local_media(jimeng_video_ref_url(image_refs[0]), "image")
            temp_paths.extend(created)
            ratio = jimeng_video_ratio_arg(payload.aspect_ratio)
            if ratio:
                args = [
                    "multimodal2video",
                    f"--image={jimeng_cli_path_arg(image_path)}",
                    f"--prompt={payload.prompt}",
                    f"--duration={duration}",
                    f"--ratio={ratio}",
                    f"--poll={jimeng_poll_seconds()}",
                ]
                jimeng_append_model_resolution_args(args, payload, include_model=True)
            else:
                args = [
                    "image2video",
                    f"--image={jimeng_cli_path_arg(image_path)}",
                    f"--prompt={payload.prompt}",
                    f"--duration={duration}",
                    f"--poll={jimeng_poll_seconds()}",
                ]
                jimeng_append_model_resolution_args(args, payload, include_model=True)
        else:
            args = [
                "text2video",
                f"--prompt={payload.prompt}",
                f"--duration={duration}",
                f"--ratio={payload.aspect_ratio or '16:9'}",
                f"--video_resolution={jimeng_video_resolution(payload.model, payload.resolution)}",
                f"--poll={jimeng_poll_seconds()}",
            ]
            model_version = jimeng_video_model_version(payload.model)
            if model_version:
                args.append(f"--model_version={model_version}")
        raw = await run_jimeng_cli(args, timeout=jimeng_poll_seconds() + 180)
        urls = await jimeng_store_outputs(raw, "video")
        return {"videos": urls, "task_id": jimeng_submit_id(raw) or None, "raw": raw}
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass

IMAGE_TASK_SUCCESS_STATUSES = {"SUCCESS", "SUCCESSFUL", "SUCCEED", "SUCCEEDED", "COMPLETED", "COMPLETE", "DONE", "FINISHED", "OK", "READY"}
IMAGE_TASK_FAILED_STATUSES = {"FAILURE", "FAILED", "FAIL", "ERROR", "ERRORED", "CANCELED", "CANCELLED", "TIMEOUT", "REJECTED", "EXPIRED"}
