"""Codex and Gemini CLI provider adapters."""

from __future__ import annotations

import asyncio
import base64
import glob
import json
import math
import mimetypes
import os
import re
import shutil
import tempfile
import time
import urllib.parse
import uuid
from typing import Any

import httpx
from fastapi import HTTPException
from PIL import Image, ImageOps

try:
    CODEX_DEFAULT_TIMEOUT = max(30, min(3600, int(os.getenv("CODEX_CLI_TIMEOUT", "900"))))
except Exception:
    CODEX_DEFAULT_TIMEOUT = 900
try:
    GEMINI_CLI_DEFAULT_TIMEOUT = max(30, min(3600, int(os.getenv("GEMINI_CLI_TIMEOUT", "900"))))
except Exception:
    GEMINI_CLI_DEFAULT_TIMEOUT = 900


CLI_EXPORTS = (
    "codex_env_value",
    "codex_cli_executable",
    "codex_timeout",
    "codex_model_for_exec",
    "codex_decode_output",
    "run_codex_cli",
    "codex_output_image_files",
    "codex_output_url_from_path",
    "gpt_image_2_skill_executable",
    "gpt_image_2_skill_auth_file",
    "gpt_image_2_skill_auth_json",
    "gpt_image_2_skill_access_token",
    "gpt_image_2_skill_api_key",
    "gpt_image_2_skill_provider_args",
    "gpt_image_2_skill_model_arg",
    "gpt_image_2_skill_size_arg",
    "gpt_image_2_skill_prompt_arg",
    "parse_gpt_image_2_skill_output",
    "codex_postprocess_image_to_requested_size",
    "generate_codex_provider_image_via_gpt_image_2_skill",
    "codex_prepare_local_media",
    "codex_reference_paths",
    "codex_models_payload",
    "generate_codex_provider_image",
    "codex_chat_prompt",
    "codex_chat_text",
    "gemini_cli_env_value",
    "antigravity_cli_winget_candidates",
    "gemini_cli_executable",
    "is_antigravity_cli",
    "gemini_cli_display_name",
    "gemini_cli_timeout",
    "gemini_cli_image_timeout",
    "gemini_cli_model",
    "gemini_cli_text_from_raw",
    "gemini_cli_parse_stdout",
    "run_gemini_cli",
    "gemini_cli_models_payload",
    "gemini_cli_reference_note",
    "gemini_cli_reference_paths",
    "gemini_cli_image_size_instruction",
    "generate_gemini_cli_provider_image",
    "gemini_cli_chat_prompt",
    "gemini_cli_chat_text",
)


def configure_cli_adapters(**dependencies: Any) -> None:
    required = {
        "BASE_DIR",
        "CHAT_RATIO_SIZE_OPTIONS",
        "CODEX_DEFAULT_CHAT_MODELS",
        "CODEX_DEFAULT_IMAGE_MODELS",
        "GEMINI_CLI_DEFAULT_CHAT_MODELS",
        "GEMINI_CLI_DEFAULT_IMAGE_MODELS",
        "MAX_HISTORY_MESSAGES",
        "ONLINE_IMAGE_REFERENCE_MAX",
        "OUTPUT_OUTPUT_DIR",
        "jimeng_extract_json",
        "model_list_from_values",
        "normalize_gpt_image_2_size",
        "output_file_from_url",
        "output_url_for",
        "parse_size_pair",
        "read_api_env_value",
    }
    missing = sorted(required - dependencies.keys())
    if missing:
        raise RuntimeError(f"CLI adapters missing dependencies: {', '.join(missing)}")
    globals().update(dependencies)


def export_cli_adapter(target: dict[str, Any]) -> None:
    for name in CLI_EXPORTS:
        target[name] = globals()[name]

def codex_env_value(key):
    return os.getenv(key, "") or read_api_env_value(key)

def codex_cli_executable():
    configured = str(codex_env_value("CODEX_BIN") or "").strip()
    if configured:
        return configured
    return shutil.which("codex") or shutil.which("codex.exe") or shutil.which("codex.cmd") or ""

def codex_timeout(default=CODEX_DEFAULT_TIMEOUT):
    try:
        return max(30, min(3600, int(os.getenv("CODEX_CLI_TIMEOUT", str(default)) or default)))
    except Exception:
        return default

def codex_model_for_exec(model="", fallback=""):
    value = str(model or fallback or "").strip()
    low = value.lower()
    if not value or low.startswith("$imagegen") or low.startswith("gpt-image"):
        return ""
    return value

def codex_decode_output(stdout, stderr):
    out_text = (stdout or b"").decode("utf-8", errors="replace").strip()
    err_text = (stderr or b"").decode("utf-8", errors="replace").strip()
    return out_text, err_text

async def run_codex_cli(prompt, model="", image_paths=None, timeout=None, output_last_message=True):
    exe = codex_cli_executable()
    if not exe:
        raise HTTPException(status_code=400, detail="未找到 OpenAI Codex CLI。请先运行 CLI/windows/openai/install_openai_codex_cli.bat，并完成 codex 登录。")
    image_paths = [str(path) for path in (image_paths or []) if path and os.path.isfile(str(path))]
    last_path = ""
    args = [
        exe,
        "exec",
        "--cd",
        BASE_DIR,
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
    ]
    exec_model = codex_model_for_exec(model)
    if exec_model:
        args.extend(["--model", exec_model])
    for path in image_paths:
        args.extend(["--image", path])
    if output_last_message:
        fd, last_path = tempfile.mkstemp(prefix="codex_last_", suffix=".txt", dir=OUTPUT_OUTPUT_DIR)
        os.close(fd)
        args.extend(["--output-last-message", last_path])
    args.append("-")
    prompt_bytes = str(prompt or "").encode("utf-8")
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=BASE_DIR,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=prompt_bytes), timeout=timeout or codex_timeout())
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="OpenAI Codex CLI 执行超时。可设置 CODEX_CLI_TIMEOUT 增大等待时间。") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"未找到 OpenAI Codex CLI：{exe}") from exc
    out_text, err_text = codex_decode_output(stdout, stderr)
    last_text = ""
    if last_path and os.path.exists(last_path):
        try:
            with open(last_path, "r", encoding="utf-8-sig") as f:
                last_text = f.read().strip()
        except Exception:
            last_text = ""
        try:
            os.remove(last_path)
        except Exception:
            pass
    if proc.returncode != 0:
        message = err_text or out_text or last_text or f"exit={proc.returncode}"
        raise HTTPException(status_code=502, detail=f"OpenAI Codex CLI 调用失败：{message[:1200]}")
    return {"text": last_text or out_text, "_stdout": out_text, "_stderr": err_text}

def codex_output_image_files(since_time=0):
    exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    root = os.path.abspath(OUTPUT_OUTPUT_DIR)
    files = []
    try:
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in exts:
                continue
            mtime = os.path.getmtime(path)
            if mtime + 1 < float(since_time or 0):
                continue
            files.append((mtime, path))
    except Exception:
        return []
    return [path for _mtime, path in sorted(files, reverse=True)]

def codex_output_url_from_path(path):
    path = os.path.abspath(str(path or ""))
    root = os.path.abspath(OUTPUT_OUTPUT_DIR)
    try:
        if os.path.commonpath([root, path]) == root:
            return output_url_for(os.path.basename(path), "output")
    except Exception:
        return ""
    return ""

def gpt_image_2_skill_executable():
    configured = str(codex_env_value("GPT_IMAGE_2_SKILL_BIN") or "").strip()
    if configured:
        return configured
    return (
        shutil.which("gpt-image-2-skill")
        or shutil.which("gpt-image-2-skill.exe")
        or shutil.which("gpt-image-2-skill.cmd")
        or ""
    )

def gpt_image_2_skill_auth_file():
    configured = str(codex_env_value("GPT_IMAGE_2_SKILL_AUTH_FILE") or codex_env_value("CODEX_AUTH_FILE") or "").strip()
    if configured:
        return configured
    user_profile = os.getenv("USERPROFILE", "").strip()
    candidates = [
        os.path.join(user_profile, ".codex", "auth.json") if user_profile else "",
        os.path.join(os.path.expanduser("~"), ".codex", "auth.json"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return candidates[0] if candidates and candidates[0] else ""

def gpt_image_2_skill_auth_json(auth_file=""):
    path = str(auth_file or "").strip()
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def gpt_image_2_skill_access_token(auth_data):
    if not isinstance(auth_data, dict):
        return ""
    for key in ("access_token", "accessToken"):
        value = str(auth_data.get(key) or "").strip()
        if value:
            return value
    tokens = auth_data.get("tokens")
    if isinstance(tokens, dict):
        for key in ("access_token", "accessToken"):
            value = str(tokens.get(key) or "").strip()
            if value:
                return value
    return ""

def gpt_image_2_skill_api_key(auth_data=None):
    for key in ("GPT_IMAGE_2_SKILL_API_KEY", "OPENAI_API_KEY"):
        value = str(codex_env_value(key) or "").strip()
        if value:
            return value
    if isinstance(auth_data, dict):
        value = str(auth_data.get("OPENAI_API_KEY") or auth_data.get("api_key") or auth_data.get("apiKey") or "").strip()
        if value:
            return value
    return ""

def gpt_image_2_skill_provider_args(auth_file=""):
    auth_data = gpt_image_2_skill_auth_json(auth_file)
    if gpt_image_2_skill_access_token(auth_data):
        return ["--provider", "codex", "--auth-file", auth_file] if auth_file else ["--provider", "codex"], "codex"
    api_key = gpt_image_2_skill_api_key(auth_data)
    if api_key:
        return ["--provider", "openai", "--api-key", api_key], "openai"
    return (["--provider", "codex", "--auth-file", auth_file] if auth_file else ["--provider", "codex"]), "codex"

def gpt_image_2_skill_model_arg(model="", provider="openai"):
    value = str(model or "").strip()
    low = value.lower()
    provider = str(provider or "").strip().lower()
    if provider == "codex":
        if not value or low.startswith("$imagegen") or low.startswith("gpt-image"):
            return "gpt-5.4"
        return value
    if not value or low.startswith("$imagegen"):
        return "gpt-image-2"
    return value

def gpt_image_2_skill_size_arg(size="", model="", prompt="", provider="openai"):
    text = " ".join([str(size or ""), str(model or ""), str(prompt or "")]).lower()
    size_text = str(size or "").strip()
    if str(provider or "").strip().lower() == "codex":
        if "1k" in text or "1024" in text:
            return "1K"
        if "2k" in text or "2048" in text:
            return "2K"
        if "4k" in text or "3840" in text:
            return "4K"
        width, height = parse_size_pair(size_text)
        if 0 < max(width, height) < 1800:
            return "1K"
        if 1800 <= max(width, height) < 3000:
            return "2K"
        return "4K"
    match = re.search(r"(\d{3,5})\s*[x×*]\s*(\d{3,5})", size_text, flags=re.I)
    if match:
        width = int(match.group(1))
        height = int(match.group(2))
        if width > 0 and height > 0:
            return normalize_gpt_image_2_size(f"{width}x{height}")
    ratio_match = re.fullmatch(r"\s*(\d{1,2})\s*:\s*(\d{1,2})\s*", size_text)
    if ratio_match:
        ratio = f"{int(ratio_match.group(1))}:{int(ratio_match.group(2))}"
        options = CHAT_RATIO_SIZE_OPTIONS.get(ratio)
        if options:
            if "4k" in text or "3840" in text:
                return options[-1]
            if "1k" in text or "1024" in text:
                return options[0]
            return options[1] if len(options) > 1 else options[0]
    if "4k" in text or "3840" in text:
        return "4K"
    if "1k" in text or "1024" in text:
        return "1K"
    return "2K"

def gpt_image_2_skill_prompt_arg(prompt="", size="", provider="openai"):
    prompt_text = str(prompt or "").strip()
    if str(provider or "").strip().lower() != "codex":
        return prompt_text
    size_arg = gpt_image_2_skill_size_arg(size, "", prompt, provider)
    size_text = str(size or "").strip()
    width, height = parse_size_pair(size_text)
    ratio_text = ""
    if width and height:
        divisor = math.gcd(width, height) or 1
        ratio_text = f"{width // divisor}:{height // divisor}"
    else:
        ratio_match = re.fullmatch(r"\s*(\d{1,2})\s*:\s*(\d{1,2})\s*", size_text)
        if ratio_match:
            width = int(ratio_match.group(1))
            height = int(ratio_match.group(2))
            ratio_text = f"{width}:{height}"
    if not ratio_text:
        return f"{prompt_text} 画质要求：目标输出 {size_arg} 高分辨率图片。 Image quality requirement: output a {size_arg} high-resolution image."
    orientation_zh = "横版/宽幅" if width > height else ("竖版/长幅" if height > width else "正方形")
    orientation_en = "landscape/wide" if width > height else ("portrait/tall" if height > width else "square")
    return (
        f"{prompt_text} "
        f"画质要求：目标输出 {size_arg} 高分辨率图片。"
        f"画幅要求：必须生成 {orientation_zh} 图片，宽高比 {ratio_text}。"
        f"请不要交换宽高，不要输出反向比例。"
        f" Image quality requirement: output a {size_arg} high-resolution image."
        f" Canvas requirement: generate a {orientation_en} image with aspect ratio {ratio_text}; "
        "do not swap width and height."
    )

def parse_gpt_image_2_skill_output(stdout_text="", stderr_text=""):
    items = []
    for line in (stdout_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except Exception:
            continue
    if not items and stdout_text:
        try:
            parsed = json.loads(stdout_text)
            items = parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            pass
    paths = []
    for item in items:
        if not isinstance(item, dict):
            continue
        candidates = [
            item.get("path"),
            item.get("file"),
            item.get("output"),
            item.get("out"),
            item.get("url"),
        ]
        for image in item.get("images") or []:
            if isinstance(image, dict):
                candidates.extend([image.get("path"), image.get("file"), image.get("url")])
            else:
                candidates.append(image)
        for candidate in candidates:
            value = str(candidate or "").strip()
            if value:
                paths.append(value)
    text = stdout_text or stderr_text or ""
    pattern = r"([A-Za-z]:\\[^\r\n\"'<>]+\.(?:png|jpe?g|webp|gif)|/[^\r\n\"'<>]+\.(?:png|jpe?g|webp|gif))"
    paths.extend(re.findall(pattern, text, flags=re.I))
    return items, paths

def codex_postprocess_image_to_requested_size(path="", requested_size="", provider=""):
    provider_text = str(provider or "").strip().lower()
    if provider_text not in {"codex", "gemini-cli"}:
        return ""
    width, height = parse_size_pair(requested_size)
    if not width or not height or not path or not os.path.isfile(path):
        return ""
    try:
        with Image.open(path) as img:
            img.load()
            if img.width == width and img.height == height:
                return ""
            resample = getattr(Image, "Resampling", Image).LANCZOS
            oriented = ImageOps.exif_transpose(img)
            converted = oriented.convert("RGBA") if oriented.mode in ("RGBA", "LA", "P") else oriented.convert("RGB")
            resized = ImageOps.fit(converted, (width, height), method=resample, centering=(0.5, 0.5))
            base, _ext = os.path.splitext(path)
            upscaled_path = f"{base}_upscaled_{width}x{height}.png"
            resized.save(upscaled_path, format="PNG")
            return upscaled_path
    except Exception as exc:
        label = "Gemini CLI" if provider_text == "gemini-cli" else "Codex GPT Image 2"
        print(f"{label} 图片尺寸后处理失败：{exc}")
        return ""

async def generate_codex_provider_image_via_gpt_image_2_skill(prompt, size, model, ref_paths=None):
    exe = gpt_image_2_skill_executable()
    if not exe:
        return None
    ref_paths = [str(path) for path in (ref_paths or []) if path and os.path.isfile(str(path))]
    auth_file = gpt_image_2_skill_auth_file()
    provider_args, tool_provider = gpt_image_2_skill_provider_args(auth_file)
    out_path = os.path.join(OUTPUT_OUTPUT_DIR, f"gpt_image_2_{uuid.uuid4().hex}.png")
    mode = "edit" if ref_paths else "generate"
    args = [
        exe,
        "--json",
        "--json-events",
    ]
    args.extend(provider_args)
    args.extend([
        "images",
        mode,
        "--prompt",
        gpt_image_2_skill_prompt_arg(prompt, size, tool_provider),
        "--out",
        out_path,
        "--model",
        gpt_image_2_skill_model_arg(model, tool_provider),
        "--format",
        "png",
        "--size",
        gpt_image_2_skill_size_arg(size, model, prompt, tool_provider),
        "--quality",
        "high",
    ])
    for path in ref_paths:
        args.extend(["--ref-image", path])
    if ref_paths and tool_provider == "openai":
        args.extend(["--input-fidelity", "high"])
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=codex_timeout())
    except asyncio.TimeoutError as exc:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        raise HTTPException(status_code=504, detail="GPT Image 2 Skill 执行超时。可设置 CODEX_CLI_TIMEOUT 增大等待时间。") from exc
    except FileNotFoundError:
        return None
    out_text, err_text = codex_decode_output(stdout, stderr)
    if proc.returncode != 0:
        message = err_text or out_text or f"exit={proc.returncode}"
        raise HTTPException(status_code=502, detail=f"GPT Image 2 Skill 调用失败：{message[:1200]}")
    parsed, reported_paths = parse_gpt_image_2_skill_output(out_text, err_text)
    candidate_paths = []
    if os.path.isfile(out_path):
        candidate_paths.append(out_path)
    candidate_paths.extend([path for path in reported_paths if path and os.path.isfile(path)])
    urls = []
    for path in candidate_paths:
        processed_path = codex_postprocess_image_to_requested_size(path, size, tool_provider)
        url = codex_output_url_from_path(processed_path or path)
        if url:
            urls.append(url)
    if not urls:
        status_text = (out_text or err_text or "")[:1200]
        raise HTTPException(status_code=502, detail=f"GPT Image 2 Skill 已返回，但没有在输出目录发现图片：{status_text}")
    return {"type": "url", "value": urls[0]}, {
        "images": urls,
        "text": out_text,
        "provider": "codex",
        "tool": "gpt-image-2-skill",
        "tool_provider": tool_provider,
        "raw": parsed or {"stdout": out_text, "stderr": err_text},
    }

async def codex_prepare_local_media(ref_url):
    text = str(ref_url or "").strip()
    if not text:
        return "", []
    if text.startswith(("/output/", "/assets/")):
        path = output_file_from_url(text)
        if path:
            return path, []
        raise HTTPException(status_code=404, detail=f"OpenAI CLI 参考素材不存在：{text}")
    if text.startswith("file://"):
        path = urllib.parse.unquote(urllib.parse.urlparse(text).path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        if os.path.isfile(path):
            return path, []
    if os.path.isfile(text):
        return text, []
    temp_paths = []
    suffix = ".png"
    if text.startswith("data:"):
        if ";base64," not in text:
            raise HTTPException(status_code=400, detail="OpenAI CLI 参考素材 data URL 缺少 base64 数据")
        header, encoded = text.split(";base64,", 1)
        mime = header.split(":", 1)[1].split(";", 1)[0] if ":" in header else ""
        suffix = mimetypes.guess_extension(mime) or suffix
        fd, path = tempfile.mkstemp(prefix="codex_ref_", suffix=suffix)
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
            fd, path = tempfile.mkstemp(prefix="codex_ref_", suffix=suffix)
            with os.fdopen(fd, "wb") as f:
                f.write(response.content)
            temp_paths.append(path)
            return path, temp_paths
    raise HTTPException(status_code=400, detail=f"OpenAI CLI 无法读取参考素材：{text[:120]}")

async def codex_reference_paths(reference_images=None):
    paths = []
    temp_paths = []
    try:
        for ref in (reference_images or [])[:ONLINE_IMAGE_REFERENCE_MAX]:
            url = ref.get("url") if isinstance(ref, dict) else getattr(ref, "url", "")
            if not url:
                continue
            path, created = await codex_prepare_local_media(url)
            if path:
                paths.append(path)
            temp_paths.extend(created)
        return paths, temp_paths
    except Exception:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass
        raise

def codex_models_payload(raw=None):
    all_models = [*CODEX_DEFAULT_IMAGE_MODELS, *CODEX_DEFAULT_CHAT_MODELS]
    return {
        "ok": True,
        "protocol": "codex",
        "status": 200,
        "message": "OpenAI Codex CLI 可用，模型列表来自本机 CLI 默认配置。",
        "model_count": len(all_models),
        "total": len(all_models),
        "image_models": CODEX_DEFAULT_IMAGE_MODELS,
        "chat_models": CODEX_DEFAULT_CHAT_MODELS,
        "video_models": [],
        "all": all_models,
        "raw": raw or {},
    }

async def generate_codex_provider_image(prompt, size, model, reference_images=None, provider=None):
    ref_paths, temp_paths = await codex_reference_paths(reference_images)
    try:
        skill_result = await generate_codex_provider_image_via_gpt_image_2_skill(prompt, size, model, ref_paths)
        if skill_result:
            return skill_result
        raise HTTPException(status_code=400, detail="未找到 GPT Image 2 helper，OpenAI CLI 生图已禁用 $imagegen 回退。请先安装 gpt-image-2-skill 后再生成图片。")
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass

def codex_chat_prompt(payload, history_messages=None):
    parts = []
    system_prompt = str(getattr(payload, "system_prompt", "") or "").strip()
    if system_prompt:
        parts.append(f"系统要求：\n{system_prompt}")
    for item in (history_messages or [])[-MAX_HISTORY_MESSAGES:]:
        role = str(item.get("role") or "").strip()
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            label = "用户" if role == "user" else "助手"
            parts.append(f"{label}：\n{content}")
    message = str(getattr(payload, "message", "") or "").strip()
    parts.append(f"用户：\n{message}")
    parts.append("请直接回答用户，输出纯文本，不要修改项目文件。")
    return "\n\n".join(part for part in parts if part).strip()

async def codex_chat_text(payload, history_messages=None):
    image_paths = []
    temp_paths = []
    try:
        image_values = []
        if hasattr(payload, "images"):
            image_values.extend([{"url": item} for item in (getattr(payload, "images", None) or []) if item])
        if hasattr(payload, "reference_images"):
            image_values.extend([ref.dict() for ref in (getattr(payload, "reference_images", None) or []) if getattr(ref, "url", "")])
        image_paths, temp_paths = await codex_reference_paths(image_values)
        raw = await run_codex_cli(
            codex_chat_prompt(payload, history_messages),
            model=getattr(payload, "model", "") or CODEX_DEFAULT_CHAT_MODELS[0],
            image_paths=image_paths,
            timeout=codex_timeout(),
            output_last_message=True,
        )
        text = str(raw.get("text") or "").strip()
        return text or "Codex CLI 返回了空回复。", raw
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass

def gemini_cli_env_value(key):
    return os.getenv(key, "") or read_api_env_value(key)

def antigravity_cli_winget_candidates():
    patterns = [
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Microsoft", "WinGet", "Packages", "Google.AntigravityCLI_*", "agy.exe"),
        os.path.join(os.getenv("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages", "Google.AntigravityCLI_*", "agy.exe"),
    ]
    candidates = []
    for pattern in patterns:
        if not pattern:
            continue
        candidates.extend(glob.glob(pattern))
    return sorted(dict.fromkeys(path for path in candidates if os.path.exists(path)), reverse=True)

def gemini_cli_executable():
    for key in ("ANTIGRAVITY_BIN", "AGY_BIN", "GEMINI_BIN"):
        configured = str(gemini_cli_env_value(key) or "").strip().strip('"')
        if configured:
            return configured
    for name in ("agy", "agy.exe"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in antigravity_cli_winget_candidates():
        return candidate
    return shutil.which("gemini") or shutil.which("gemini.exe") or shutil.which("gemini.cmd") or ""

def is_antigravity_cli(exe):
    text = str(exe or "").lower()
    return os.path.basename(text).startswith("agy") or "antigravity" in text

def gemini_cli_display_name(exe=None):
    return "Antigravity CLI" if is_antigravity_cli(exe or gemini_cli_executable()) else "Gemini CLI"

def gemini_cli_timeout(default=GEMINI_CLI_DEFAULT_TIMEOUT):
    try:
        return max(30, min(3600, int(os.getenv("GEMINI_CLI_TIMEOUT", str(default)) or default)))
    except Exception:
        return default

def gemini_cli_image_timeout():
    raw = os.getenv("ANTIGRAVITY_IMAGE_TIMEOUT") or os.getenv("GEMINI_CLI_IMAGE_TIMEOUT") or "300"
    try:
        return max(60, min(1800, int(raw)))
    except Exception:
        return 300

def gemini_cli_model(model="", fallback=""):
    value = str(model or fallback or "").strip()
    return value or "auto"

def gemini_cli_text_from_raw(raw, fallback_text=""):
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        for key in ("response", "text", "content", "message", "output"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        candidates = []
        for value in raw.values():
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        text = gemini_cli_text_from_raw(item)
                        if text:
                            candidates.append(text)
                    elif isinstance(item, str) and item.strip():
                        candidates.append(item.strip())
        if candidates:
            return "\n".join(candidates).strip()
    if isinstance(raw, list):
        parts = [gemini_cli_text_from_raw(item) for item in raw]
        return "\n".join(part for part in parts if part).strip()
    return str(fallback_text or "").strip()

def gemini_cli_parse_stdout(out_text):
    text = str(out_text or "").strip()
    if not text:
        return {}, ""
    try:
        raw = json.loads(text)
        return raw, gemini_cli_text_from_raw(raw, text)
    except Exception:
        pass
    parsed = jimeng_extract_json(text)
    if isinstance(parsed, (dict, list)) and parsed != {"text": text}:
        return parsed, gemini_cli_text_from_raw(parsed, text)
    return {"text": text}, text

async def run_gemini_cli(prompt, model="", timeout=None, allow_tools=False):
    exe = gemini_cli_executable()
    if not exe:
        raise HTTPException(status_code=400, detail="未找到 Antigravity CLI。请先安装 Google Antigravity CLI，并完成 agy 登录。")
    timeout_seconds = timeout or gemini_cli_timeout()
    if is_antigravity_cli(exe):
        args = [exe, "--print-timeout", f"{int(timeout_seconds)}s"]
        selected = gemini_cli_model(model)
        if selected and selected != "auto":
            args.extend(["--model", selected])
        if allow_tools:
            args.append("--dangerously-skip-permissions")
        args.extend(["-p", str(prompt or "")])
    else:
        args = [
            exe,
            "--model",
            gemini_cli_model(model),
            "--output-format",
            "json",
            "--skip-trust",
        ]
        if allow_tools:
            args.extend(["--approval-mode", "yolo"])
        args.extend(["--prompt", str(prompt or "")])
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        raise HTTPException(status_code=504, detail=f"{gemini_cli_display_name(exe)} 执行超时。可设置 GEMINI_CLI_TIMEOUT 增大等待时间。") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"未找到 {gemini_cli_display_name(exe)}：{exe}") from exc
    out_text, err_text = codex_decode_output(stdout, stderr)
    raw, text = gemini_cli_parse_stdout(out_text)
    if proc.returncode != 0:
        message = err_text or out_text or f"exit={proc.returncode}"
        raise HTTPException(status_code=502, detail=f"{gemini_cli_display_name(exe)} 调用失败：{message[:1200]}")
    return {"text": text or out_text, "raw": raw, "_stdout": out_text, "_stderr": err_text}

def gemini_cli_models_payload(raw=None):
    all_models = [*GEMINI_CLI_DEFAULT_IMAGE_MODELS, *GEMINI_CLI_DEFAULT_CHAT_MODELS]
    all_models = model_list_from_values(all_models)
    return {
        "ok": True,
        "protocol": "gemini-cli",
        "status": 200,
        "message": "Antigravity CLI 可用，模型列表使用 auto 默认模型。",
        "model_count": len(all_models),
        "total": len(all_models),
        "image_models": GEMINI_CLI_DEFAULT_IMAGE_MODELS,
        "chat_models": GEMINI_CLI_DEFAULT_CHAT_MODELS,
        "video_models": [],
        "all": all_models,
        "raw": raw or {},
    }

def gemini_cli_reference_note(reference_images=None):
    refs = []
    temp_paths = []
    for ref in (reference_images or [])[:ONLINE_IMAGE_REFERENCE_MAX]:
        url = ref.get("url") if isinstance(ref, dict) else getattr(ref, "url", "")
        if not url:
            continue
        refs.append(url)
    return refs, temp_paths

async def gemini_cli_reference_paths(reference_images=None):
    return await codex_reference_paths(reference_images)

def gemini_cli_image_size_instruction(size="", model=""):
    size_text = str(size or "").strip()
    model_text = str(model or "").strip()
    match = re.match(r"^\s*(\d{2,5})\s*[xX*]\s*(\d{2,5})\s*$", size_text)
    if match:
        width, height = int(match.group(1)), int(match.group(2))
        if width > 0 and height > 0:
            orientation = "正方形" if width == height else ("横版" if width > height else "竖版")
            return (
                f"目标输出分辨率：{width}x{height} 像素（宽 x 高），画面方向：{orientation}。"
                f"最终保存到输出目录的图片文件实际像素必须是 {width}x{height}。"
                "如果生成器先得到较小图片，请在保存前放大或导出到目标尺寸，不要返回 1024px 小图。"
            )
    combined = f"{size_text} {model_text}".lower()
    if "4k" in combined:
        return "目标输出为 4K 高分辨率图片；最终保存文件需要达到当前画幅对应的 4K 像素尺寸，不要默认输出 1024px 小图。"
    if "2k" in combined:
        return "目标输出为 2K 高分辨率图片；最终保存文件需要达到当前画幅对应的 2K 像素尺寸，不要默认输出 1024px 小图。"
    return f"尺寸/比例参考：{size_text or 'auto'}。如果可以指定分辨率，请优先输出高分辨率图片。"

async def generate_gemini_cli_provider_image(prompt, size, model, reference_images=None, provider=None):
    ref_paths, temp_paths = await gemini_cli_reference_paths(reference_images)
    since = time.time()
    try:
        ref_text = ""
        if ref_paths:
            ref_text = "\n参考图片本地路径：\n" + "\n".join(ref_paths)
        size_context = f"{model or ''} {prompt or ''}"
        image_prompt = (
            f"你正在为 Infinite Canvas 生成图片。\n"
            f"任务：{prompt}\n\n"
            f"{gemini_cli_image_size_instruction(size, size_context)}\n"
            f"{ref_text}\n\n"
            f"如果当前 Antigravity CLI/模型支持图片生成或图片编辑，请把最终图片保存到这个本地目录：{OUTPUT_OUTPUT_DIR}\n"
            "文件格式优先 png 或 jpg。只输出最终文件路径和一句简短说明；不要修改项目代码，不要创建额外文档。\n"
            "如果你无法真正创建图片文件，请在 60 秒内直接回复“无法生成图片文件”，不要只写计划，也不要持续尝试。"
        )
        raw = await run_gemini_cli(
            image_prompt,
            model=model or GEMINI_CLI_DEFAULT_IMAGE_MODELS[0],
            timeout=gemini_cli_image_timeout() if is_antigravity_cli(gemini_cli_executable()) else gemini_cli_timeout(),
            allow_tools=True,
        )
        files = codex_output_image_files(since)
        urls = []
        for path in files:
            processed_path = codex_postprocess_image_to_requested_size(path, size, "gemini-cli")
            url = codex_output_url_from_path(processed_path or path)
            if url and url not in urls:
                urls.append(url)
        if not urls:
            text = f"{raw.get('text') or raw.get('_stdout') or ''}\n{raw.get('_stderr') or ''}"
            pattern = r"([A-Za-z]:\\[^\r\n\"'<>]+\.(?:png|jpe?g|webp|gif)|/[^\r\n\"'<>]+\.(?:png|jpe?g|webp|gif))"
            for match in re.findall(pattern, text, flags=re.I):
                match_path = match.strip()
                processed_path = codex_postprocess_image_to_requested_size(match_path, size, "gemini-cli")
                url = codex_output_url_from_path(processed_path or match_path)
                if url and url not in urls:
                    urls.append(url)
        if not urls:
            status_text = (raw.get("text") or raw.get("_stdout") or raw.get("_stderr") or "")[:1200]
            raise HTTPException(status_code=502, detail=f"{gemini_cli_display_name()} 已返回，但没有在输出目录发现图片：{status_text}")
        return {"type": "url", "value": urls[0]}, {"images": urls, "text": raw.get("text"), "provider": "gemini-cli", "raw": raw.get("raw")}
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass

def gemini_cli_chat_prompt(payload, history_messages=None):
    parts = []
    system_prompt = str(getattr(payload, "system_prompt", "") or "").strip()
    if system_prompt:
        parts.append(f"系统要求：\n{system_prompt}")
    for item in (history_messages or [])[-MAX_HISTORY_MESSAGES:]:
        role = str(item.get("role") or "").strip()
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            label = "用户" if role == "user" else "助手"
            parts.append(f"{label}：\n{content}")
    message = str(getattr(payload, "message", "") or "").strip()
    parts.append(f"用户：\n{message}")
    image_values = []
    if hasattr(payload, "images"):
        image_values.extend([{"url": item} for item in (getattr(payload, "images", None) or []) if item])
    if hasattr(payload, "reference_images"):
        image_values.extend([ref.dict() for ref in (getattr(payload, "reference_images", None) or []) if getattr(ref, "url", "")])
    refs = []
    temp_paths = []
    return "\n\n".join(part for part in parts if part).strip(), image_values

async def gemini_cli_chat_text(payload, history_messages=None):
    temp_paths = []
    try:
        prompt, image_values = gemini_cli_chat_prompt(payload, history_messages)
        image_paths, temp_paths = await gemini_cli_reference_paths(image_values)
        if image_paths:
            prompt = f"{prompt}\n\n可参考的本地图片路径：\n" + "\n".join(image_paths)
        prompt = f"{prompt}\n\n请直接回答用户，输出纯文本，不要修改项目文件。"
        raw = await run_gemini_cli(
            prompt,
            model=getattr(payload, "model", "") or GEMINI_CLI_DEFAULT_CHAT_MODELS[0],
            timeout=gemini_cli_timeout(),
            allow_tools=False,
        )
        text = str(raw.get("text") or "").strip()
        return text or f"{gemini_cli_display_name()} 返回了空回复。", raw
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass
