"""Extracted update transport services."""

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


UPDATE_TRANSPORT_EXPORTS = (
    'github_get',
    'github_json',
    'github_bytes',
    'download_github_update_files',
    'modelscope_update_file_list',
    'modelscope_file_bytes',
    'download_modelscope_update_files',
    'safe_update_target',
    'safe_static_dir',
    'schedule_self_restart',
    'github_update_file_list',
    'staged_update_file_list',
    'stage_update_from_source',
)


def configure_update_transport(namespace: dict[str, Any]) -> None:
    required = {
        'BASE_DIR',
        'GITHUB_RAW_ROOT',
        'GITHUB_TREE_CACHE',
        'GITHUB_TREE_URL',
        'MODELSCOPE_FILE_API_ROOT',
        'MODELSCOPE_TREE_URL',
        'STATIC_DIR',
        'update_allowed_file',
    }
    missing = sorted(required - namespace.keys())
    if missing:
        raise RuntimeError(f"Update Transport missing dependencies: {', '.join(missing)}")
    globals().update({name: namespace[name] for name in required})


def export_update_transport(target: dict[str, Any]) -> None:
    for name in UPDATE_TRANSPORT_EXPORTS:
        target[name] = globals()[name]


def github_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 30) -> requests.Response:
    try:
        response = requests.get(
            url,
            headers=headers or {},
            timeout=timeout,
            proxies=urllib.request.getproxies() or None,
        )
    except requests.RequestException as exc:
        raise urllib.error.URLError(str(exc)) from exc
    if response.status_code >= 400 or response.status_code == 304:
        raise urllib.error.HTTPError(url, response.status_code, response.reason, response.headers, None)
    return response

def github_json(url: str, use_etag_cache: bool = False):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Infinite-Canvas-Updater",
    }
    cache_key = url
    if use_etag_cache and cache_key == GITHUB_TREE_URL:
        if GITHUB_TREE_CACHE["data"] and time.time() < GITHUB_TREE_CACHE["expires_at"]:
            return GITHUB_TREE_CACHE["data"]
        if GITHUB_TREE_CACHE["etag"]:
            headers["If-None-Match"] = GITHUB_TREE_CACHE["etag"]
    try:
        resp = github_get(url, headers=headers, timeout=30)
        etag = resp.headers.get("ETag", "")
        payload = json.loads(resp.content.decode("utf-8", errors="replace"))
        if use_etag_cache and cache_key == GITHUB_TREE_URL:
            GITHUB_TREE_CACHE.update({
                "etag": etag,
                "data": payload,
                "expires_at": time.time() + 600,  # 10 分钟内复用
            })
        return payload
    except urllib.error.HTTPError as exc:
        # 304 表示对方树未变，沿用缓存
        if exc.code == 304 and use_etag_cache and GITHUB_TREE_CACHE["data"]:
            GITHUB_TREE_CACHE["expires_at"] = time.time() + 600
            return GITHUB_TREE_CACHE["data"]
        raise

def github_bytes(url: str) -> bytes:
    resp = github_get(url, headers={"User-Agent": "Infinite-Canvas-Updater"}, timeout=60)
    return resp.content

def download_github_update_files(files: List[str], staging_root: str) -> None:
    staging_root_abs = os.path.abspath(staging_root)
    for rel in files:
        safe_update_target(rel)
        raw_url = f"{GITHUB_RAW_ROOT}/{urllib.parse.quote(rel, safe='/')}"
        data = github_bytes(raw_url)
        stage_path = os.path.abspath(os.path.join(staging_root_abs, *rel.split("/")))
        if os.path.commonpath([staging_root_abs, stage_path]) != staging_root_abs:
            raise ValueError(f"更新暂存路径不安全：{rel}")
        os.makedirs(os.path.dirname(stage_path), exist_ok=True)
        with open(stage_path, "wb") as f:
            f.write(data)

def modelscope_update_file_list() -> List[str]:
    """通过 ModelScope 仓库文件 API 列出所有允许更新的文件（不依赖 git）。"""
    resp = github_get(MODELSCOPE_TREE_URL, headers={"User-Agent": "Infinite-Canvas-Updater"}, timeout=30)
    payload = json.loads(resp.content.decode("utf-8", errors="replace"))
    files_node = ((payload.get("Data") or {}).get("Files")) or []
    out: List[str] = []
    for entry in files_node:
        if not isinstance(entry, dict):
            continue
        if entry.get("Type") != "blob":
            continue
        path = str(entry.get("Path") or "").replace("\\", "/")
        if update_allowed_file(path):
            out.append(path)
    return sorted(set(out))

def modelscope_file_bytes(rel: str) -> bytes:
    url = MODELSCOPE_FILE_API_ROOT + urllib.parse.quote(rel, safe="/")
    resp = github_get(url, headers={"User-Agent": "Infinite-Canvas-Updater"}, timeout=60)
    return resp.content

def download_modelscope_update_files(staging_root: str) -> List[str]:
    # 用 HTTP 仓库文件 API 下载（与 GitHub raw 同样思路），不依赖本机安装 Git。
    # 之前用 git clone 会要求目标机装 Git for Windows，很多用户没装 → 一键更新失败。
    files = modelscope_update_file_list()
    if not files:
        raise RuntimeError("ModelScope 未返回任何文件")
    if "main.py" not in files or "VERSION" not in files:
        raise RuntimeError("ModelScope 更新源缺少 main.py 或 VERSION")
    if not any(f.startswith("static/") for f in files):
        raise RuntimeError("ModelScope 未返回 static 文件，已取消更新")
    staging_root_abs = os.path.abspath(staging_root)
    for rel in files:
        safe_update_target(rel)
        data = modelscope_file_bytes(rel)
        stage_path = os.path.abspath(os.path.join(staging_root_abs, *rel.split("/")))
        if os.path.commonpath([staging_root_abs, stage_path]) != staging_root_abs:
            raise ValueError(f"更新暂存路径不安全：{rel}")
        os.makedirs(os.path.dirname(stage_path), exist_ok=True)
        with open(stage_path, "wb") as f:
            f.write(data)
    return files

def safe_update_target(path: str) -> str:
    rel = str(path or "").replace("\\", "/").lstrip("/")
    if not update_allowed_file(rel):
        raise ValueError(f"更新文件不在允许范围：{rel}")
    target = os.path.abspath(os.path.join(BASE_DIR, *rel.split("/")))
    base = os.path.abspath(BASE_DIR)
    if os.path.commonpath([base, target]) != base:
        raise ValueError(f"更新路径不安全：{rel}")
    return target

def safe_static_dir() -> str:
    target = os.path.abspath(STATIC_DIR)
    expected = os.path.abspath(os.path.join(BASE_DIR, "static"))
    base = os.path.abspath(BASE_DIR)
    if target != expected or os.path.commonpath([base, target]) != base:
        raise RuntimeError(f"static 路径不安全：{target}")
    return target

def schedule_self_restart(delay_seconds: int = 3) -> bool:
    """派生脱离父进程的小脚本，等几秒后启动启动服务脚本，并干掉当前 PID。"""
    delay = max(1, int(delay_seconds or 3))
    pid = os.getpid()
    try:
        if os.name == "nt":
            launcher = os.path.join(BASE_DIR, "启动服务.bat")
            if not os.path.exists(launcher):
                launcher = os.path.join(BASE_DIR, "start.bat")
            bat_path = os.path.join(BASE_DIR, "_self_restart.bat")
            log_path = os.path.join(BASE_DIR, "_self_restart.log")
            script = (
                "@echo off\r\n"
                "chcp 65001 >nul\r\n"
                "setlocal\r\n"
                f"set \"APP_DIR={BASE_DIR}\"\r\n"
                f"set \"LAUNCHER={launcher}\"\r\n"
                f"set \"LOG_FILE={log_path}\"\r\n"
                "echo [%date% %time%] restart scheduled >> \"%LOG_FILE%\"\r\n"
                f"timeout /t {delay} /nobreak >nul\r\n"
                "echo [%date% %time%] stopping old process >> \"%LOG_FILE%\"\r\n"
                f"taskkill /F /PID {pid} >nul 2>&1\r\n"
                "timeout /t 2 /nobreak >nul\r\n"
                "cd /d \"%APP_DIR%\"\r\n"
                "if exist \"%LAUNCHER%\" (\r\n"
                "  echo [%date% %time%] starting launcher: %LAUNCHER% >> \"%LOG_FILE%\"\r\n"
                "  start \"ComfyUI-API-Modelscope\" /D \"%APP_DIR%\" cmd /k call \"%LAUNCHER%\"\r\n"
                ") else (\r\n"
                "  echo [%date% %time%] launcher missing, fallback to python main.py >> \"%LOG_FILE%\"\r\n"
                "  if exist \"%APP_DIR%\\python\\python.exe\" (\r\n"
                "    start \"ComfyUI-API-Modelscope\" /D \"%APP_DIR%\" cmd /k \"\"%APP_DIR%\\python\\python.exe\" main.py\"\r\n"
                "  ) else (\r\n"
                "    start \"ComfyUI-API-Modelscope\" /D \"%APP_DIR%\" cmd /k python main.py\r\n"
                "  )\r\n"
                ")\r\n"
                "del \"%~f0\"\r\n"
            )
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(script)
            subprocess.Popen(
                ["cmd", "/c", bat_path],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        else:
            launcher = os.path.join(BASE_DIR, "mac-启动服务.command")
            if not os.path.exists(launcher):
                launcher = os.path.join(BASE_DIR, "start.sh")
            sh_path = os.path.join(BASE_DIR, "_self_restart.sh")
            script = (
                "#!/bin/sh\n"
                f"sleep {delay}\n"
                f"kill -9 {pid} 2>/dev/null\n"
                f"cd \"{BASE_DIR}\"\n"
                f"if [ -x \"{launcher}\" ]; then nohup \"{launcher}\" >/dev/null 2>&1 &\n"
                f"elif [ -f \"{launcher}\" ]; then nohup /bin/sh \"{launcher}\" >/dev/null 2>&1 &\n"
                "fi\n"
                "rm -- \"$0\"\n"
            )
            with open(sh_path, "w", encoding="utf-8") as f:
                f.write(script)
            os.chmod(sh_path, 0o755)
            subprocess.Popen(
                ["/bin/sh", sh_path],
                start_new_session=True,
                close_fds=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True
    except Exception as exc:
        logging.exception("schedule_self_restart failed: %s", exc)
        return False

def github_update_file_list() -> Tuple[List[str], List[str], List[str]]:
    tree_data = github_json(GITHUB_TREE_URL, use_etag_cache=True)
    entries = tree_data.get("tree") or []
    static_files = []
    root_files = []
    for entry in entries:
        path = str(entry.get("path") or "").replace("\\", "/")
        if entry.get("type") == "blob" and update_allowed_file(path):
            if path.startswith("static/"):
                static_files.append(path)
            else:
                root_files.append(path)
    if "main.py" not in root_files:
        root_files.append("main.py")
    if "VERSION" not in root_files:
        root_files.append("VERSION")
    static_files = sorted(set(static_files))
    root_files = sorted(set(root_files))
    files = root_files + static_files
    if not static_files:
        raise RuntimeError("GitHub 未返回 static 文件，已取消更新")
    return root_files, static_files, files

def staged_update_file_list(staging_root: str) -> Tuple[List[str], List[str], List[str]]:
    root_files = []
    static_files = []
    for root_dir, _, names in os.walk(staging_root):
        for name in names:
            path = os.path.abspath(os.path.join(root_dir, name))
            rel = os.path.relpath(path, staging_root).replace("\\", "/")
            if not update_allowed_file(rel):
                continue
            if rel.startswith("static/"):
                static_files.append(rel)
            else:
                root_files.append(rel)
    if "main.py" not in root_files or "VERSION" not in root_files:
        raise RuntimeError("更新源缺少 main.py 或 VERSION")
    if not static_files:
        raise RuntimeError("更新源未返回 static 文件，已取消更新")
    root_files = sorted(set(root_files))
    static_files = sorted(set(static_files))
    return root_files, static_files, root_files + static_files

def stage_update_from_source(source: str, staging_root: str) -> Tuple[List[str], List[str], List[str]]:
    """下载指定源的更新文件到 staging，返回 (root_files, static_files, files)。失败抛异常。"""
    if source == "modelscope":
        download_modelscope_update_files(staging_root)
        return staged_update_file_list(staging_root)
    root_files, static_files, files = github_update_file_list()
    download_github_update_files(files, staging_root)
    return root_files, static_files, files
