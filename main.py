import json
import uuid
import base64
import hashlib
import hmac
import datetime
import urllib.request
import urllib.parse
import urllib.error
import os
import re
import random
import sys
import subprocess
import time
import traceback
import shutil
import glob
import asyncio
import logging
import requests
import zipfile
import mimetypes
import tempfile
import math
import shlex
import functools
import html
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional, Tuple
from threading import Lock
import httpx
from PIL import Image, ImageOps
from io import BytesIO
from app_bootstrap import configure_application
from app_dependencies import install_dependencies
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from fastapi.middleware.cors import CORSMiddleware

install_dependencies(globals())

install_quiet_access_log_filter()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(workflows_router)
app.include_router(comfyui_config_router)
app.include_router(update_router)
app.include_router(canvases_router)
app.include_router(conversations_router)
app.include_router(asset_library_router)
app.include_router(prompt_libraries_router)
app.include_router(provider_config_router)
app.include_router(shared_folders_router)
app.include_router(provider_probe_router)
app.include_router(asset_items_router)
app.include_router(local_assets_router)
app.include_router(runninghub_router)
app.include_router(cli_tools_router)
app.include_router(history_router)
app.include_router(media_router)
app.include_router(runtime_info_router)
app.include_router(chat_router)
app.include_router(canvas_tools_router)
app.include_router(generation_router)

# --- WebSocket 状态管理器 ---
manager = ConnectionManager()
GLOBAL_LOOP = None
APP_VERSION = "2026.07.6"
GITHUB_REPO_URL = "https://github.com/hero8152/Infinite-Canvas"
GITHUB_VERSION_URL = "https://raw.githubusercontent.com/hero8152/Infinite-Canvas/main/VERSION"
GITHUB_TREE_URL = "https://api.github.com/repos/hero8152/Infinite-Canvas/git/trees/main?recursive=1"
GITHUB_RAW_ROOT = "https://raw.githubusercontent.com/hero8152/Infinite-Canvas/main"
GITHUB_UPDATE_NOTES_URL = GITHUB_RAW_ROOT + "/static/update-notes.json"
MODELSCOPE_REPO_URL = "https://modelscope.ai/studios/daniel8152/Infinite-Canvas"
MODELSCOPE_RAW_ROOT = "https://www.modelscope.ai/studios/daniel8152/Infinite-Canvas/raw/main"
# ModelScope 仓库默认分支为 master；raw 网页路径会返回 HTML，必须用仓库文件 API 才能拿到纯文本
# 注意：.ai 站命名空间为小写 daniel8152，API 路径大小写敏感（推送/文件 API 用大写会 404/拒绝）
MODELSCOPE_FILE_API_ROOT = "https://www.modelscope.ai/api/v1/studio/daniel8152/Infinite-Canvas/repo?Revision=master&FilePath="
MODELSCOPE_VERSION_URL = MODELSCOPE_FILE_API_ROOT + "VERSION"
MODELSCOPE_UPDATE_NOTES_URL = MODELSCOPE_FILE_API_ROOT + "static/update-notes.json"
MODELSCOPE_TREE_URL = "https://www.modelscope.ai/api/v1/studio/daniel8152/Infinite-Canvas/repo/files?Revision=master&Recursive=true"

@app.on_event("startup")
async def startup_event():
    global GLOBAL_LOOP
    GLOBAL_LOOP = asyncio.get_running_loop()
    sync_static_html_versions()
    # 启动时整理资产库：给所有图片分组（含默认角色/场景）建好文件夹，并把根目录里的旧素材归整进去。
    try:
        await asyncio.to_thread(migrate_asset_library_into_dirs)
    except Exception as exc:
        print(f"资产库分组整理失败: {exc}")
    # 修复历史遗留的双重扩展名素材（foo.png.png → foo.png），否则这些卡片无法显示
    try:
        await asyncio.to_thread(migrate_double_extension_uploads)
    except Exception as exc:
        print(f"修复双重扩展名素材失败: {exc}")
    # 纠正内容与扩展名不符的图片（如 WebP 内容却叫 .png），否则严格客户端解不出来
    try:
        await asyncio.to_thread(migrate_mislabeled_image_extensions)
    except Exception as exc:
        print(f"纠正图片扩展名失败: {exc}")

@app.websocket("/ws/stats")
async def websocket_endpoint(websocket: WebSocket, client_id: str = None):
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        await manager.disconnect(websocket, client_id)
    except Exception as e:
        print(f"WS Error: {e}")
        await manager.disconnect(websocket, client_id)

# --- 配置区域 ---

CLIENT_ID = str(uuid.uuid4())
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR = os.path.join(BASE_DIR, "workflows")
WORKFLOW_PATH = os.path.join(WORKFLOW_DIR, "Z-Image.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")
STATIC_RUNNINGHUB_DIR = os.path.join(STATIC_DIR, "runninghub")
STATIC_RUNNINGHUB_THUMBNAIL_DIR = os.path.join(STATIC_RUNNINGHUB_DIR, "thumbnails")
STATIC_RUNNINGHUB_API_PROVIDERS_FILE = os.path.join(STATIC_RUNNINGHUB_DIR, "api_providers.json")
STATIC_RUNNINGHUB_MODEL_REGISTRY_FILE = os.path.join(STATIC_RUNNINGHUB_DIR, "models_registry.json")
configure_static_versioning(
    base_dir=BASE_DIR,
    static_dir=STATIC_DIR,
    github_update_notes_url=GITHUB_UPDATE_NOTES_URL,
    modelscope_update_notes_url=MODELSCOPE_UPDATE_NOTES_URL,
)
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
OUTPUT_INPUT_DIR = os.path.join(ASSETS_DIR, "input")
OUTPUT_OUTPUT_DIR = os.path.join(ASSETS_DIR, "output")
ASSET_LIBRARY_DIR = os.path.join(ASSETS_DIR, "library")
LOCAL_UPLOAD_DIR = os.path.join(ASSETS_DIR, "uploads")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
API_ENV_FILE = os.path.join(BASE_DIR, "API", ".env")
DATA_DIR = os.path.join(BASE_DIR, "data")
CONVERSATION_DIR = os.path.join(DATA_DIR, "conversations")
CANVAS_DIR = os.path.join(DATA_DIR, "canvases")
PROJECTS_PATH = os.path.join(DATA_DIR, "projects.json")
MEDIA_PREVIEW_DIR = os.path.join(DATA_DIR, "media_previews")
ASSET_LIBRARY_PATH = os.path.join(DATA_DIR, "asset_library.json")
PROMPT_LIBRARY_PATH = os.path.join(DATA_DIR, "prompt_libraries.json")
API_PROVIDERS_FILE = os.path.join(DATA_DIR, "api_providers.json")
RUNNINGHUB_WORKFLOW_STORE_FILE = os.path.join(DATA_DIR, "runninghub_workflows.json")
SHARED_FOLDERS_FILE = os.path.join(DATA_DIR, "shared_folders.json")
GLOBAL_CONFIG_FILE = os.path.join(BASE_DIR, "global_config.json")
CANVAS_TRASH_RETENTION_MS = 30 * 24 * 60 * 60 * 1000
LOCAL_IMAGE_IMPORT_MAX_BYTES = int(os.getenv("LOCAL_IMAGE_IMPORT_MAX_BYTES", str(50 * 1024 * 1024)))
LOCAL_IMAGE_IMPORT_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
RUNNINGHUB_THUMBNAIL_EXTS = (".jpg",)

QUEUE = []
QUEUE_LOCK = Lock()
HISTORY_LOCK = Lock()
GLOBAL_CONFIG_LOCK = Lock()
CONVERSATION_LOCK = Lock()
CANVAS_LOCK = Lock()
LOAD_LOCK = Lock()
RUNNINGHUB_WORKFLOW_LOCK = Lock()
NEXT_TASK_ID = 1
UPDATE_LOCK = Lock()
JIMENG_LOGIN_SESSION = {
    "proc": None,
    "stdout": "",
    "stderr": "",
    "started_at": 0.0,
}

PROVIDER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{2,40}$")
SUPPORTED_PROVIDER_PROTOCOLS = {"openai", "apimart", "gemini", "gemini-cli", "volcengine", "runninghub", "jimeng", "codex"}
SUPPORTED_IMAGE_REQUEST_MODES = {"openai", "openai-json", "openai-video-proxy", "openai-responses"}
RUNNINGHUB_DEFAULT_BASE_URL = "https://www.runninghub.cn"
RUNNINGHUB_OPENAPI_BASE_URL = "https://www.runninghub.cn/openapi/v2"
RUNNINGHUB_MODEL_REGISTRY_URL = "https://raw.githubusercontent.com/HM-RunningHub/ComfyUI_RH_OpenAPI/main/models_registry.json"
RUNNINGHUB_LLM_BASE_URL = "https://llm.runninghub.cn/v1"
RUNNINGHUB_FILE_HOST_REWRITES = {
    "rh-images-1252422369.cos.ap-beijing.myqcloud.com": "rh-images.xiaoyaoyou.com",
}
LINGJING_DEFAULT_BASE_URL = "https://apistudio.vip"
RUNNINGHUB_LLM_MODELS_URLS = [
    "https://llm.runninghub.cn/v1/models",
    "https://llm.runninghub.ai/v1/models",
]
RUNNINGHUB_FALLBACK_CHAT_MODELS = [
    "google/gemini-3.1-flash-lite-preview",
    "qwen/qwen3-vl-235b-a22b-instruct",
    "qwen/qwen-plus",
    "openai/gpt-5.1",
]
JIMENG_DEFAULT_IMAGE_MODELS = [
    "5.0",
    "4.6",
    "4.5",
    "4.1",
    "4.0",
    "3.1",
    "3.0",
]
JIMENG_DEFAULT_VIDEO_MODELS = [
    "seedance2.0_vip",
    "seedance2.0fast_vip",
    "seedance2.0",
    "seedance2.0fast",
    "3.5pro",
    "3.0pro",
    "3.0",
    "3.0fast",
]
CODEX_DEFAULT_IMAGE_MODELS = ["gpt-image-2"]
CODEX_DEFAULT_CHAT_MODELS = ["gpt-5.5"]
GEMINI_CLI_DEFAULT_IMAGE_MODELS = ["auto"]
GEMINI_CLI_DEFAULT_CHAT_MODELS = ["auto"]
try:
    CODEX_DEFAULT_TIMEOUT = max(30, min(3600, int(os.getenv("CODEX_CLI_TIMEOUT", "900"))))
except Exception:
    CODEX_DEFAULT_TIMEOUT = 900
try:
    GEMINI_CLI_DEFAULT_TIMEOUT = max(30, min(3600, int(os.getenv("GEMINI_CLI_TIMEOUT", "900"))))
except Exception:
    GEMINI_CLI_DEFAULT_TIMEOUT = 900
AGNES_DEFAULT_VIDEO_MODELS = ["agnes-video-v2.0"]
JIMENG_LEGACY_IMAGE_MODELS = {
    "jimeng-image-2k",
    "jimeng-image-4k",
}
JIMENG_LEGACY_VIDEO_MODELS = {
    "jimeng-video-720p",
    "jimeng-video-1080p",
}
try:
    JIMENG_DEFAULT_POLL_SECONDS = max(1, min(3600, int(os.getenv("JIMENG_POLL_SECONDS", "900"))))
except Exception:
    JIMENG_DEFAULT_POLL_SECONDS = 900
VOLCENGINE_DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
VOLCENGINE_DEFAULT_PROJECT_NAME = "default"
VOLCENGINE_DEFAULT_REGION = "cn-beijing"
RUNNINGHUB_DEFAULT_IMAGE_MODELS = [
    "gpt-image-2.0/text-to-image-channel-low-price",
    "gpt-image-2.0/edit-channel-low-price",
    "gpt-image-2/text-to-image-official-stable",
    "gpt-image-2/image-to-image-official-stable",
    "nano-banana/text-to-image-official-stable",
    "nano-banana/edit-official-stable",
]
RUNNINGHUB_DEFAULT_VIDEO_MODELS = [
    "google/veo3.1-fast/text-to-video-channel-low-price",
    "sora-2/text-to-video-official-stable",
    "seedance-2.0-global/text-to-video",
    "seedance-2.0-global/image-to-video",
]
RUNNINGHUB_MODEL_ENDPOINT_ALIASES = {
    "gpt-image-2.0/text-to-image-channel-low-price": "rhart-image-g-2/text-to-image",
    "gpt-image-2/text-to-image-channel-low-price": "rhart-image-g-2/text-to-image",
    "gpt-image-2.0/edit-channel-low-price": "rhart-image-g-2/image-to-image",
    "gpt-image-2/edit-channel-low-price": "rhart-image-g-2/image-to-image",
    "gpt-image-2.0/image-to-image-channel-low-price": "rhart-image-g-2/image-to-image",
    "gpt-image-2/image-to-image-channel-low-price": "rhart-image-g-2/image-to-image",
    "nano-banana/text-to-image-channel-low-price": "rhart-image-v1/text-to-image",
    "nano-banana/edit-channel-low-price": "rhart-image-v1/edit",
}
RUNNINGHUB_DEFAULT_APPS = [
    {
        "id": "2058517022748798977",
        "appId": "2058517022748798977",
        "title": "2511-风格迁移",
        "note": "",
        "thumbnail": "",
        "enabled": True,
        "fields": [
            {
                "id": "100::image",
                "nodeId": "100",
                "fieldName": "image",
                "fieldValue": "pasted/57ef7dc980b6446bca366caaf3f94eb12b22b23f78aa30e294b39cabd7d0187b.png",
                "fieldType": "IMAGE",
                "label": "image",
                "enabled": True,
                "sourceFromUpstream": True,
                "group": "AI 应用参数",
                "note": "image",
                "options": [],
                "random_enabled": False,
                "min": "",
                "max": "",
                "step": "",
                "imageOrder": 0,
                "required": False,
            },
            {
                "id": "112::image",
                "nodeId": "112",
                "fieldName": "image",
                "fieldValue": "8cff63ee4b3e0285ca85ab90a52e26746df84ed0dec0be9d76c679cbb62a247d.png",
                "fieldType": "IMAGE",
                "label": "image",
                "enabled": True,
                "sourceFromUpstream": True,
                "group": "AI 应用参数",
                "note": "image",
                "options": [],
                "random_enabled": False,
                "min": "",
                "max": "",
                "step": "",
                "imageOrder": 0,
                "required": False,
            },
            {
                "id": "14::seed",
                "nodeId": "14",
                "fieldName": "seed",
                "fieldValue": "3250470112",
                "fieldType": "INT",
                "label": "seed",
                "enabled": True,
                "sourceFromUpstream": True,
                "group": "AI 应用参数",
                "note": "seed",
                "options": [],
                "random_enabled": True,
                "min": "1",
                "max": "4294967295",
                "step": "1",
                "imageOrder": 0,
                "required": False,
            },
        ],
    },
    {
        "id": "1997622492837646338",
        "appId": "1997622492837646338",
        "title": "2511-光线迁移",
        "note": "",
        "thumbnail": "",
        "enabled": True,
    },
]
RUNNINGHUB_DEFAULT_WORKFLOWS = [
    {
        "id": "2058554058318897153",
        "workflowId": "2058554058318897153",
        "title": "GPT-Image-2-图片编辑",
        "note": "",
        "thumbnail": "",
        "enabled": True,
        "optionalImageMode": "prune-workflow",
    },
    {
        "id": "2058541134623891458",
        "workflowId": "2058541134623891458",
        "title": "NanoBanana-2-图片编辑",
        "note": "",
        "thumbnail": "",
        "enabled": True,
        "optionalImageMode": "prune-workflow",
    },
]

configure_env_config(
    api_env_file=API_ENV_FILE,
    data_dir=DATA_DIR,
)


ensure_runtime_config_files()
load_env_file()

COMFYUI_INSTANCES = [s.strip() for s in os.getenv("COMFYUI_INSTANCES", "127.0.0.1:8188").split(",") if s.strip()]
COMFYUI_ADDRESS = COMFYUI_INSTANCES[0]

AI_BASE_URL = os.getenv("COMFLY_BASE_URL", "https://ai.comfly.chat").rstrip("/")
AI_API_KEY = os.getenv("COMFLY_API_KEY", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
PUBLIC_MEDIA_BASE_URL = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip().rstrip("/")
MODELSCOPE_API_KEY = os.getenv("MODELSCOPE_API_KEY", "")
MODELSCOPE_CHAT_BASE_URL = "https://api-inference.modelscope.cn/v1"
MODELSCOPE_DEFAULT_IMAGE_MODELS = [
    "Tongyi-MAI/Z-Image-Turbo",
    "Qwen/Qwen-Image-2512",
    "Qwen/Qwen-Image-Edit-2511",
    "black-forest-labs/FLUX.2-klein-9B",
]
MODELSCOPE_DEFAULT_CHAT_MODELS = [
    "Qwen/Qwen3-235B-A22B",
    "Qwen/Qwen3-VL-235B-A22B-Instruct",
    "MiniMax/MiniMax-M2.7:MiniMax",
]
_MODELSCOPE_CONFIGURED_CHAT_MODELS = [m.strip() for m in os.getenv("MODELSCOPE_CHAT_MODELS", "").split(",") if m.strip()]
MODELSCOPE_CHAT_MODELS = list(dict.fromkeys([m for m in [*MODELSCOPE_DEFAULT_CHAT_MODELS, *_MODELSCOPE_CONFIGURED_CHAT_MODELS] if m]))
MODELSCOPE_DEFAULT_IMAGE_MODEL = MODELSCOPE_DEFAULT_IMAGE_MODELS[0]
MODELSCOPE_DEFAULT_CHAT_MODEL = "Qwen/Qwen3-235B-A22B"
MODELSCOPE_DEFAULT_LORAS = [
    {
        "id": "Daniel8152/film",
        "name": "Z-Image Film",
        "target_model": "Tongyi-MAI/Z-Image-Turbo",
        "strength": 0.8,
        "enabled": True,
        "note": "",
    },
    {
        "id": "Daniel8152/Qwen-Image-2512-Film",
        "name": "Qwen Image 2512 Film",
        "target_model": "Qwen/Qwen-Image-2512",
        "strength": 0.8,
        "enabled": True,
        "note": "",
    },
    {
        "id": "Daniel8152/Klein-enhance",
        "name": "Klein enhance",
        "target_model": "black-forest-labs/FLUX.2-klein-9B",
        "strength": 0.8,
        "enabled": True,
        "note": "",
    },
]
MODELSCOPE_DEFAULTS_VERSION = 3
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "You are a helpful assistant.")
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "30"))
AI_REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "1800"))
IMAGE_POLL_INTERVAL = float(os.getenv("IMAGE_POLL_INTERVAL", "2"))
IMAGE_TASK_TIMEOUT = float(os.getenv("IMAGE_TASK_TIMEOUT", str(AI_REQUEST_TIMEOUT)))
COMFYUI_HISTORY_TIMEOUT = int(float(os.getenv("COMFYUI_HISTORY_TIMEOUT", "1800")))
# 下载 ComfyUI 产物的 socket 超时（秒，作用于连接和每次 read）。没有它时一次网络卡顿会让 urlopen 永久挂起，
# 导致 generate() 不返回、画布卡片一直转圈拿不到结果。给得足够大以容纳大视频/大图的正常下载。
COMFYUI_DOWNLOAD_TIMEOUT = float(os.getenv("COMFYUI_DOWNLOAD_TIMEOUT", "120"))
APIMART_IMAGE_TASK_TIMEOUT = float(os.getenv("APIMART_IMAGE_TASK_TIMEOUT", "1800"))
APIMART_IMAGE_POLL_INTERVAL = float(os.getenv("APIMART_IMAGE_POLL_INTERVAL", "5"))
APIMART_IMAGE_INITIAL_POLL_DELAY = float(os.getenv("APIMART_IMAGE_INITIAL_POLL_DELAY", "10"))
VIDEO_POLL_TIMEOUT = float(os.getenv("VIDEO_POLL_TIMEOUT", "1800"))
ONLINE_IMAGE_PROMPT_MAX_LENGTH = int(os.getenv("ONLINE_IMAGE_PROMPT_MAX_LENGTH", "20000"))
VIDEO_PROMPT_MAX_LENGTH = int(os.getenv("VIDEO_PROMPT_MAX_LENGTH", "4000"))
LLM_MESSAGE_MAX_LENGTH = int(os.getenv("LLM_MESSAGE_MAX_LENGTH", "20000"))
CHAT_ATTACHMENT_MAX = int(os.getenv("CHAT_ATTACHMENT_MAX", "20"))
ONLINE_IMAGE_REFERENCE_MAX = int(os.getenv("ONLINE_IMAGE_REFERENCE_MAX", "20"))

FIELD_LABELS = {
    "prompt": "提示词",
    "message": "文本",
    "system_prompt": "系统提示词",
}

def friendly_validation_error(errors):
    parts = []
    for err in errors or []:
        loc = [str(item) for item in err.get("loc", []) if item != "body"]
        field = loc[-1] if loc else ""
        label = FIELD_LABELS.get(field, field or "请求参数")
        ctx = err.get("ctx") or {}
        limit = ctx.get("limit_value") or ctx.get("max_length") or ctx.get("min_length")
        err_type = str(err.get("type") or "")
        msg = str(err.get("msg") or "")
        if "max_length" in err_type or "at most" in msg:
            parts.append(f"{label}过长：当前内容超过后端上限 {limit} 个字符。请拆分为多个提示词节点，或先用 LLM 节点压缩后再生成。")
        elif "min_length" in err_type:
            parts.append(f"{label}不能为空。")
        else:
            parts.append(f"{label}格式不正确：{msg}")
    return "\n".join(parts) or "请求参数不正确。"

@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": friendly_validation_error(exc.errors()), "errors": exc.errors()},
    )


def reload_env_globals():
    """保存 API 设置后，将 os.environ 里最新的值同步回模块级全局变量，
    避免保存后需要重启才能生效。"""
    global MODELSCOPE_API_KEY, AI_API_KEY, AI_BASE_URL
    global IMAGE_MODELS, CHAT_MODELS, VIDEO_MODELS, MODELSCOPE_CHAT_MODELS
    MODELSCOPE_API_KEY = os.getenv("MODELSCOPE_API_KEY", "")
    AI_API_KEY = os.getenv("COMFLY_API_KEY", "")
    AI_BASE_URL = os.getenv("COMFLY_BASE_URL", "https://ai.comfly.chat").rstrip("/")
    IMAGE_MODELS = model_list("IMAGE_MODELS", os.getenv("IMAGE_MODEL", IMAGE_MODEL), ["nano-banana-pro"])
    CHAT_MODELS = model_list("CHAT_MODELS", os.getenv("CHAT_MODEL", CHAT_MODEL), ["gpt-4o-mini", "gemini-3.1-flash-image-preview-2k"])
    VIDEO_MODELS = model_list("VIDEO_MODELS", "veo3-fast", [
        "veo2", "veo2-fast", "veo2-pro",
        "veo3", "veo3-fast", "veo3-pro",
        "veo3.1", "veo3.1-fast", "veo3.1-quality", "veo3.1-lite",
        "sora-2", "sora-2-pro",
        "wan2.6-t2v", "wan2.6-i2v",
        "wan2.5-t2v-preview", "wan2.5-i2v-preview",
        "wan2.2-t2v-plus", "wan2.2-i2v-plus", "wan2.2-i2v-flash",
        "doubao-seedance-2-0-260128",
        "doubao-seedance-2-0-fast-260128",
        "doubao-seedance-1-5-pro-251215",
        "doubao-seedance-1-0-pro-250528",
        "doubao-seedance-1-0-lite-t2v-250428",
        "doubao-seedance-1-0-lite-i2v-250428",
    ])
    _configured = [m.strip() for m in os.getenv("MODELSCOPE_CHAT_MODELS", "").split(",") if m.strip()]
    MODELSCOPE_CHAT_MODELS = list(dict.fromkeys([m for m in [*MODELSCOPE_DEFAULT_CHAT_MODELS, *_configured] if m]))
    configure_runtime_registry(globals())

CHAT_MODELS = model_list("CHAT_MODELS", CHAT_MODEL, ["gpt-4o-mini", "gemini-3.1-flash-image-preview-2k"])
IMAGE_MODELS = model_list("IMAGE_MODELS", IMAGE_MODEL, ["nano-banana-pro"])
VIDEO_MODELS = model_list("VIDEO_MODELS", "veo3-fast", [
    # —— Veo 系列 ——
    "veo2", "veo2-fast", "veo2-pro",
    "veo3", "veo3-fast", "veo3-pro",
    "veo3.1", "veo3.1-fast", "veo3.1-quality", "veo3.1-lite",
    # —— Sora ——
    "sora-2", "sora-2-pro",
    # —— 阿里 通义万相 ——
    "wan2.6-t2v", "wan2.6-i2v",
    "wan2.5-t2v-preview", "wan2.5-i2v-preview",
    "wan2.2-t2v-plus", "wan2.2-i2v-plus", "wan2.2-i2v-flash",
    # —— 火山 豆包 Seedance ——
    "doubao-seedance-2-0-260128",
    "doubao-seedance-2-0-fast-260128",
    "doubao-seedance-1-5-pro-251215",
    "doubao-seedance-1-0-pro-250528",
    "doubao-seedance-1-0-lite-t2v-250428",
    "doubao-seedance-1-0-lite-i2v-250428",
])



























BACKEND_LOCAL_LOAD = {addr: 0 for addr in COMFYUI_INSTANCES}

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(OUTPUT_INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_OUTPUT_DIR, exist_ok=True)
os.makedirs(ASSET_LIBRARY_DIR, exist_ok=True)
os.makedirs(LOCAL_UPLOAD_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(WORKFLOW_DIR, exist_ok=True)
os.makedirs(CONVERSATION_DIR, exist_ok=True)
os.makedirs(CANVAS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

# --- Pydantic 模型 ---






STATIC_PROMPT_TEMPLATE_MD = os.path.join(STATIC_DIR, "system-prompts", "infinite-canvas-prompt-templates.md")
PROMPT_TEMPLATE_PATHS = [STATIC_PROMPT_TEMPLATE_MD]
PROMPT_TEMPLATE_EN = {
    "多机位九宫格": {
        "name": "9-Angle Multi-Camera Grid",
        "scene": "Show the same subject or scene from 9 camera angles for character turnarounds, product views, or space scouting.",
    },
    "多机位九宫格4K": {
        "name": "9-Angle Multi-Camera Grid 4K",
        "scene": "A high-resolution 9-angle reference sheet for print-grade output, large displays, and fine material study.",
    },
    "剧情推演四宫格": {
        "name": "4-Panel Story Progression",
        "scene": "Preview four consecutive story beats or emotional stages for storyboard planning and narrative rhythm tests.",
    },
    "角色脸部三视图": {
        "name": "Character Face 3-View Sheet",
        "scene": "Front, side, and three-quarter face references for Actor ID locking and expression consistency.",
    },
    "产品三视图": {
        "name": "Product 3-View Sheet",
        "scene": "Front, side, and top product views for industrial design, ecommerce detail pages, and technical documents.",
    },
    "25宫格连贯分镜": {
        "name": "25-Panel Continuous Storyboard",
        "scene": "A full 5x5 storyboard for continuous scene or action flow, useful for film previews and motion continuity tests.",
    },
    "电影级光影校正": {
        "name": "Cinematic Lighting Comparison",
        "scene": "Compare the same subject or scene under different lighting conditions for mood, color, and lighting choices.",
    },
    "角色设定参考表（胸口特写+全身三视图）": {
        "name": "Character Reference Sheet: Portrait + Full-Body Views",
        "scene": "A consistency reference combining a face anchor and full-body front, side, and back views for Actor ID and costume lock.",
    },
    "6种基础表情胸像（2×3六宫格）": {
        "name": "6 Basic Expression Busts",
        "scene": "Six basic expressions of the same character for expression consistency, emotion baselines, and Seedance Talk-to-Edit reference.",
    },
    "360全景图": {
        "name": "360 Panorama VR Image",
        "scene": "Generate a seamless 360-degree VR panorama with continuous left and right edges and natural pole transitions.",
    },
}





GITHUB_TREE_CACHE: Dict[str, Any] = {"etag": "", "data": None, "expires_at": 0.0}













UPDATE_SOURCE_LABELS = {"github": "GitHub", "modelscope": "ModelScope"}


CANVAS_TASKS: Dict[str, Dict[str, Any]] = {}
CANVAS_TASK_LOCK = Lock()

MEDIA_INPUT_KEYS = ("image", "video", "audio", "mask", "filename", "file")
MEDIA_INPUT_EXT_RE = re.compile(r"\.(png|jpe?g|webp|gif|bmp|tiff?|mp4|webm|mov|m4v|avi|mkv|mp3|wav|m4a|aac|ogg|flac)(?:\?|$)", re.I)

# --- 辅助工具 ---

# 纯预览/对比类节点：其输出只用于界面展示（PreviewImage、rgthree 的 Image Comparer 等），
# 工作流里通常还有 SaveImage 产出真正结果，故有正式产出时应丢弃这些冗余预览/对比图。
COMFY_PREVIEW_CLASS_HINTS = ("previewimage", "comparer", "imagecompare", "image compare")
# show/utility 类调试文本节点：ShowText、各种 *Anything、CR Text、MathExpression、note 等，
# 它们的 ui 文本基本是调试信息，不应混进最终结果。
COMFY_DEBUG_TEXT_CLASS_HINTS = (
    "showtext", "show text", "showanything", "show any", "preview any", "previewany",
    "displaytext", "display text", "display any", "anything everywhere", "convertanything",
    "easy show", "note", "mathexpression", "cr text", "text multiline", "string function",
    "debug",
)










IMAGE_OUTPUT_KEY_HINTS = (
    "url", "image_url", "imageUrl", "image", "output_url", "outputUrl",
    "result_url", "resultUrl", "download_url", "downloadUrl", "asset_url", "assetUrl",
)
IMAGE_CONTAINER_KEY_HINTS = (
    "images", "image", "output", "outputs", "result", "results", "data", "items", "files",
)
IMAGE_BASE64_KEY_HINTS = ("b64_json", "base64", "image_base64", "imageBase64")

RESPONSES_REJECT_STATUSES = {400, 404, 405, 415, 422}
RESPONSES_POLL_INTERVAL = 5.0
RESPONSES_POLL_MAX_SECONDS = 1500.0

# ---- 数字人/真人认证：平台无关分发 ----
# 认证是一个跨平台功能。每个平台用不同的资产 API 实现，但对外是统一入口。
# 新增平台时：在 avatar_platform_for_provider 里加一条识别，并把平台键加进
# AVATAR_SUPPORTED_PLATFORMS，再在 register/avatar-status 端点里补一个分发分支即可。
AVATAR_SUPPORTED_PLATFORMS = {"apimart", "volcengine"}  # 已接入官方资产 API 的平台

SHARED_FOLDERS_LOCK = Lock()

TEXT_ATTACHMENT_EXTS = {".txt", ".md", ".markdown", ".json", ".csv", ".log", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".xml", ".yaml", ".yml"}
XLSX_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
EXCEL_MAX_SHEETS = 8
EXCEL_MAX_ROWS_PER_SHEET = 80
EXCEL_MAX_COLS_PER_ROW = 30
MAX_ATTACHMENT_TEXT_CHARS = 12000

APIMART_UPLOAD_RETRY_ATTEMPTS = 3

AVATAR_TASK_DONE_STATUSES = {"completed", "complete", "succeeded", "success", "active", "done"}
AVATAR_TASK_FAIL_STATUSES = {"failed", "fail", "error", "rejected", "canceled", "cancelled", "expired"}

# ---- 火山 Ark 私域素材资产（Assets）API：AK/SK 签名 V4 + CreateAssetGroup/CreateAsset/GetAsset ----
VOLCENGINE_ARK_ASSET_HOST = "open.volcengineapi.com"
VOLCENGINE_ARK_ASSET_SERVICE = "ark"
VOLCENGINE_ARK_ASSET_REGION = "cn-beijing"
VOLCENGINE_ARK_ASSET_VERSION = "2024-01-01"

CHAT_RATIO_SIZE_OPTIONS = {
    "1:1": ("1024x1024", "1536x1536", "2048x2048"),
    "2:3": ("720x1080", "1024x1536", "1365x2048"),
    "3:2": ("1080x720", "1536x1024", "2048x1365"),
    "3:4": ("1008x1344", "1536x2048", "2448x3264"),
    "4:3": ("1344x1008", "2048x1536", "3264x2448"),
    "9:16": ("720x1280", "1080x1920", "1440x2560"),
    "16:9": ("1280x720", "1920x1080", "2560x1440"),
}

# GPT-Image-2 限制：长边最大 3840，主要受最大像素限制（约 829 万 = 3840x2160）。
# 这里只用于上游报错后给出友好的像素上限提示；不对尺寸做任何缩小（用户选什么就原样发送）。
GPT_IMAGE2_MAX_EDGE = 3840
GPT_IMAGE2_MAX_PIXELS = 8_294_400
GPT_IMAGE2_MIN_PIXELS = 655_360

# --- 在线生图 (COMFLY) ---

# --- 图像生成参数 schema（供客户端动态渲染参数表单，避免把参数写死在前端） ---
IMAGE_PARAM_RATIOS = [
    {"value": "1:1", "label": "1:1"},
    {"value": "3:4", "label": "3:4"},
    {"value": "4:3", "label": "4:3"},
    {"value": "16:9", "label": "16:9"},
    {"value": "9:16", "label": "9:16"},
    {"value": "2:3", "label": "2:3"},
    {"value": "3:2", "label": "3:2"},
]
IMAGE_PARAM_RESOLUTIONS = [
    {"value": "1k", "label": "1K"},
    {"value": "2k", "label": "2K"},
    {"value": "4k", "label": "4K"},
]

# --- Canvas Video ---

VIDEO_URL_KEYS = (
    "url", "video_url", "videoUrl", "mp4_url", "mp4Url",
    "output", "output_url", "outputUrl", "download_url", "downloadUrl",
    "video", "src", "uri", "preview_url", "previewUrl", "path",
    "last_frame_url", "lastFrameUrl", "remixed_from_video_id",
)

# --- 对话管理 ---




configure_application(globals())

if __name__ == "__main__":
    import uvicorn
    # 关闭服务端协议级 WebSocket ping：部分客户端（如 PS UXP 面板）不会自动回 pong，
    # 默认 20s ping/20s 超时会把这些连接每隔一会儿就踢掉造成"频繁断连"。
    # 客户端有自己的应用层心跳 + 断线重连兜底，这里禁用协议 ping 更稳。
    uvicorn.run(app, host="0.0.0.0", port=3000,
                ws_ping_interval=None, ws_ping_timeout=None)
