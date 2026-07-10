"""Media storage, previews, local imports, and asset file operations."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import uuid
from typing import Any

import requests
from fastapi import HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageOps


MEDIA_FILE_EXPORTS = (
    "output_storage",
    "output_url_for",
    "output_path_for",
    "output_file_from_url",
    "image_has_alpha",
    "media_preview_cache_paths",
    "is_video_preview_file",
    "generate_video_preview_image",
    "media_preview",
    "image_jpeg",
    "local_media_file_by_basename",
    "filename_from_media_url",
    "fetch_remote_media_bytes",
    "origin_from_url",
    "ensure_same_origin_request",
    "normalize_local_image_path",
    "import_local_image_file",
    "asset_library_media_kind",
    "asset_library_safe_extension",
    "unique_asset_category_dir",
    "remove_asset_library_file",
    "make_asset_library_item",
)


def configure_media_files(**dependencies: Any) -> None:
    required = {
        "ASSETS_DIR",
        "ASSET_LIBRARY_DIR",
        "LOCAL_IMAGE_IMPORT_EXTS",
        "LOCAL_IMAGE_IMPORT_MAX_BYTES",
        "MEDIA_PREVIEW_DIR",
        "OUTPUT_DIR",
        "OUTPUT_INPUT_DIR",
        "OUTPUT_OUTPUT_DIR",
        "now_ms",
        "rewrite_runninghub_file_url",
        "sanitize_asset_name",
        "sanitize_export_filename",
    }
    missing = sorted(required - dependencies.keys())
    if missing:
        raise RuntimeError(f"Media files service missing dependencies: {', '.join(missing)}")
    globals().update(dependencies)


def export_media_files(target: dict[str, Any]) -> None:
    for name in MEDIA_FILE_EXPORTS:
        target[name] = globals()[name]

def output_storage(category="output"):
    return (OUTPUT_INPUT_DIR, "input") if category == "input" else (OUTPUT_OUTPUT_DIR, "output")

def output_url_for(filename, category="output"):
    _, subdir = output_storage(category)
    return f"/assets/{subdir}/{filename}"

def output_path_for(filename, category="output"):
    folder, _ = output_storage(category)
    return os.path.join(folder, filename)

def output_file_from_url(url):
    if isinstance(url, dict):
        url = url.get("url", "")
    if not url or not (url.startswith("/output/") or url.startswith("/assets/")):
        return None
    clean = urllib.parse.unquote(url.split("?", 1)[0]).replace("\\", "/")
    if clean.startswith("/assets/"):
        root = ASSETS_DIR
        rel = clean[len("/assets/"):]
    else:
        root = OUTPUT_DIR
        rel = clean[len("/output/"):]
    rel = rel.lstrip("/")
    if not rel:
        return None
    path = os.path.abspath(os.path.join(root, rel))
    output_root = os.path.abspath(root)
    if os.path.commonpath([output_root, path]) != output_root or not os.path.exists(path):
        return None
    return path

def image_has_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA"):
        return True
    if img.mode == "P":
        return "transparency" in img.info
    return False

def media_preview_cache_paths(path: str, width: int):
    stat = os.stat(path)
    key = hashlib.sha1(
        f"{os.path.abspath(path)}|{stat.st_mtime_ns}|{stat.st_size}|{width}".encode("utf-8", "ignore")
    ).hexdigest()
    return (
        os.path.join(MEDIA_PREVIEW_DIR, f"{key}.webp"),
        os.path.join(MEDIA_PREVIEW_DIR, f"{key}.png"),
    )

def is_video_preview_file(path: str) -> bool:
    return os.path.splitext(str(path or "").split("?", 1)[0])[1].lower() in {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"}

def generate_video_preview_image(path: str, width: int) -> Image.Image:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法生成视频预览图")
    fd, frame_path = tempfile.mkstemp(prefix="media_preview_frame_", suffix=".jpg")
    os.close(fd)
    try:
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", "0.5",
            "-i", path,
            "-frames:v", "1",
            "-vf", f"scale='min({width},iw)':-2",
            frame_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0 or not os.path.exists(frame_path) or os.path.getsize(frame_path) <= 0:
            raise RuntimeError((proc.stderr or "ffmpeg 未能抽取视频首帧").strip()[:300])
        with Image.open(frame_path) as frame:
            img = ImageOps.exif_transpose(frame).copy()
            img.thumbnail((width, width), Image.LANCZOS)
            return img.convert("RGB")
    finally:
        try:
            os.remove(frame_path)
        except OSError:
            pass

async def media_preview(url: str, w: int = 512):
    path = output_file_from_url(url)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="媒体文件不存在")

    width = max(64, min(2048, int(w or 512)))
    webp_path, png_path = media_preview_cache_paths(path, width)

    if os.path.exists(webp_path):
        return FileResponse(webp_path, media_type="image/webp")
    if os.path.exists(png_path):
        return FileResponse(png_path, media_type="image/png")

    def _build_preview():
        # 同步 PIL 处理 + 落盘，放到线程里执行，避免阻塞事件循环（几十张首次生成会卡死整个 loop → 缩略图全空白）
        os.makedirs(MEDIA_PREVIEW_DIR, exist_ok=True)
        if is_video_preview_file(path):
            img = generate_video_preview_image(path, width)
        else:
            with Image.open(path) as source:
                img = ImageOps.exif_transpose(source)
                img.thumbnail((width, width), Image.LANCZOS)
                img = img.convert("RGBA" if image_has_alpha(img) else "RGB")
        try:
            img.save(webp_path, format="WEBP", quality=80, method=1)   # method=1 生成更快（缩略图不追求极致压缩）
            return webp_path, "image/webp"
        except Exception:
            img.save(png_path, format="PNG")
            return png_path, "image/png"

    try:
        out_path, media_type = await asyncio.to_thread(_build_preview)
        return FileResponse(out_path, media_type=media_type)
    except Exception as exc:
        raise HTTPException(status_code=415, detail=f"无法生成预览图：{exc}") from exc

async def image_jpeg(url: str, w: int = 0):
    """把任意图片转成 JPEG 返回（带缓存）。给不支持 WebP 等格式显示的客户端（PS UXP）用。
    w>0 时同时缩放到该宽度（缩略图）；w=0 输出原尺寸。"""
    path = output_file_from_url(url)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    width = max(0, min(4096, int(w or 0)))
    stat = os.stat(path)
    key = hashlib.sha1(f"{os.path.abspath(path)}|{stat.st_mtime_ns}|{stat.st_size}|{width}|jpg".encode("utf-8", "ignore")).hexdigest()
    cache_path = os.path.join(MEDIA_PREVIEW_DIR, f"{key}.jpg")
    if os.path.exists(cache_path):
        return FileResponse(cache_path, media_type="image/jpeg")

    def _build():
        os.makedirs(MEDIA_PREVIEW_DIR, exist_ok=True)
        with Image.open(path) as src:
            img = ImageOps.exif_transpose(src)
            if width:
                img.thumbnail((width, width), Image.LANCZOS)
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                rgba = img.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
            img.save(cache_path, format="JPEG", quality=86)
        return cache_path

    try:
        out_path = await asyncio.to_thread(_build)
        return FileResponse(out_path, media_type="image/jpeg")
    except Exception as exc:
        raise HTTPException(status_code=415, detail=f"无法转换图片：{exc}") from exc

def local_media_file_by_basename(name: str):
    safe = os.path.basename(urllib.parse.unquote(str(name or "")))
    if not safe:
        return None
    roots = [
        OUTPUT_OUTPUT_DIR,
        OUTPUT_INPUT_DIR,
        os.path.join(ASSETS_DIR, "output"),
        os.path.join(ASSETS_DIR, "input"),
        os.path.join(ASSETS_DIR, "library"),
    ]
    for root in roots:
        path = os.path.abspath(os.path.join(root, safe))
        root_abs = os.path.abspath(root)
        if os.path.commonpath([root_abs, path]) == root_abs and os.path.isfile(path):
            return path
    return None

def filename_from_media_url(url: str, fallback: str = "download.bin") -> str:
    path = urllib.parse.urlsplit(str(url or "")).path
    name = os.path.basename(urllib.parse.unquote(path))
    return sanitize_export_filename(name or fallback, fallback)

def fetch_remote_media_bytes(url: str, timeout: float = 30.0, max_bytes: int = 200 * 1024 * 1024):
    text = rewrite_runninghub_file_url(str(url or "").strip())
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    with requests.get(text, stream=True, timeout=timeout, headers={"User-Agent": "ComfyUI-API-Modelscope/1.0"}) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type") or "application/octet-stream"
        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=1024 * 256):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(status_code=413, detail="文件太大，无法下载")
            chunks.append(chunk)
        return b"".join(chunks), content_type

def origin_from_url(value):
    parsed = urllib.parse.urlparse(str(value or ""))
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".lower()

def ensure_same_origin_request(request: Request):
    host = str(request.headers.get("host") or "").lower()
    expected = f"{request.url.scheme}://{host}".lower() if host else ""
    origin = origin_from_url(request.headers.get("origin", ""))
    referer = origin_from_url(request.headers.get("referer", ""))
    actual = origin or referer
    if expected and actual != expected:
        raise HTTPException(status_code=403, detail="只允许从当前页面导入本地图片")

def normalize_local_image_path(value):
    text = str(value or "").strip().strip('"').strip("'")
    if not text:
        raise HTTPException(status_code=400, detail="本地图片路径为空")
    if text.lower().startswith("file:"):
        parsed = urllib.parse.urlparse(text)
        if parsed.scheme.lower() != "file":
            raise HTTPException(status_code=400, detail="只支持本地图片路径")
        if parsed.netloc and re.match(r"^[a-zA-Z]:$", parsed.netloc) and os.name == "nt":
            path = f"{parsed.netloc}{urllib.request.url2pathname(parsed.path or '')}"
        elif parsed.netloc and parsed.netloc.lower() not in ("localhost",):
            raise HTTPException(status_code=400, detail="只支持本机图片路径")
        else:
            path = urllib.request.url2pathname(parsed.path or "")
    else:
        path = text
    path = path.strip().strip('"').strip("'")
    if re.match(r"^/[a-zA-Z]:[\\/]", path):
        path = path[1:]
    if re.match(r"^[a-zA-Z]:[\\/]", path):
        return os.path.abspath(path)
    if path.startswith("/") and os.name != "nt":
        return os.path.abspath(path)
    raise HTTPException(status_code=400, detail="只支持本机绝对图片路径")

def import_local_image_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in LOCAL_IMAGE_IMPORT_EXTS:
        raise HTTPException(status_code=400, detail="仅支持 PNG、JPG、JPEG、WEBP、GIF 图片")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="本地图片不存在或无法读取")
    try:
        size = os.path.getsize(path)
    except OSError:
        raise HTTPException(status_code=404, detail="本地图片不存在或无法读取")
    if size <= 0:
        raise HTTPException(status_code=400, detail="本地图片为空")
    if size > LOCAL_IMAGE_IMPORT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="本地图片过大，请使用 50MB 以内的图片")
    try:
        with Image.open(path) as img:
            img.verify()
    except Exception:
        raise HTTPException(status_code=400, detail="文件不是可识别的图片")
    filename = f"ai_ref_{uuid.uuid4().hex[:12]}{ext}"
    dest = output_path_for(filename, "input")
    try:
        shutil.copyfile(path, dest)
    except OSError:
        raise HTTPException(status_code=500, detail="导入本地图片失败")
    return {"url": output_url_for(filename, "input"), "name": os.path.basename(path) or filename, "kind": "image"}

def asset_library_media_kind(path: str, content_type: str = "") -> str:
    ext = os.path.splitext(path or "")[1].lower()
    ct = (content_type or "").lower()
    if ext in {".json", ".zip"}:
        return "workflow"
    if ext in {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"} or ct.startswith("video/"):
        return "video"
    if ext in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"} or ct.startswith("audio/"):
        return "audio"
    return "image"

def asset_library_safe_extension(path: str, kind: str) -> str:
    ext = os.path.splitext(path or "")[1].lower()
    allowed = {
        "image": {".png", ".jpg", ".jpeg", ".webp", ".gif"},
        "video": {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"},
        "audio": {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"},
        "workflow": {".json", ".zip"},
    }
    fallback = {"image": ".png", "video": ".mp4", "audio": ".mp3", "workflow": ".zip"}
    return ext if ext in allowed.get(kind, allowed["image"]) else fallback.get(kind, ".png")

def unique_asset_category_dir(library, base_name: str) -> str:
    """为资产库分组生成一个唯一、文件系统安全的子文件夹名（library/<dir>/）。
    以分组名为基础（保留中文），与同库其它分组的 dir 及磁盘上已存在的文件夹去重。"""
    base = sanitize_asset_name(base_name, "分组").strip(" .") or "分组"
    existing = {
        str(c.get("dir")) for c in (library.get("categories") or [])
        if isinstance(c, dict) and c.get("dir")
    }
    candidate = base
    i = 2
    while candidate in existing or os.path.exists(os.path.join(ASSET_LIBRARY_DIR, candidate)):
        candidate = f"{base}_{i}"
        i += 1
    return candidate

def remove_asset_library_file(item) -> None:
    """删除资产对应的本地文件（仅限 library 副本，删了不影响 /output 原图）。日志不影响主流程。"""
    try:
        url = item.get("url") if isinstance(item, dict) else ""
        path = output_file_from_url(url)
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception as exc:
        print(f"删除资产文件失败: {exc}")

def make_asset_library_item(src: str, name: str = "", subdir: str = "") -> Tuple[str, Dict[str, Any]]:
    kind = asset_library_media_kind(src)
    ext = asset_library_safe_extension(src, kind)
    safe_name = sanitize_asset_name(name or os.path.basename(src), "asset")
    if not os.path.splitext(safe_name)[1]:
        safe_name += ext
    dest_name = f"lib_{uuid.uuid4().hex[:12]}_{safe_name}"
    subdir = str(subdir or "").strip("/").strip()
    if subdir:
        dest_dir = os.path.join(ASSET_LIBRARY_DIR, subdir)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, dest_name)
        rel = f"{subdir}/{dest_name}"
    else:
        dest_path = os.path.join(ASSET_LIBRARY_DIR, dest_name)
        rel = dest_name
    shutil.copy2(src, dest_path)
    item = {
        "id": f"asset_{uuid.uuid4().hex[:12]}",
        "name": os.path.splitext(safe_name)[0][:120],
        "url": "/assets/library/" + urllib.parse.quote(rel, safe="/"),
        "kind": kind,
        "created_at": now_ms(),
    }
    return dest_name, item
    return lib

ASSET_CLASSIFICATION_PROMPT = """请识别这张图片，输出严格 JSON，不要 Markdown，不要解释。
目标是给素材库做非常全面的筛选分类。所有字段都用中文短标签数组，尽量具体但不要虚构。
JSON 结构：
{
  "summary": "一句话描述",
  "categories": {
    "environment": ["室内/室外/自然/城市/棚拍/商业空间等环境大类"],
    "scene": ["室内/室外/棚拍/街景/自然/商业空间等"],
    "space": ["卧室/餐厅/客厅/厨房/浴室/办公室/店铺/展厅/户外道路等"],
    "subject": ["人物/模特/产品/家具/建筑/食物/动物/车辆/植物等"],
    "model": ["无人/单人模特/多人模特/男性模特/女性模特/儿童模特/半身模特/全身模特/手部模特等"],
    "people": ["无人/单人/多人/男性/女性/儿童/半身/全身/手部特写等"],
    "style": ["写实/摄影/插画/3D/极简/奢华/复古/现代/电商/电影感等"],
    "lighting": ["自然光/硬光/柔光/逆光/侧光/夜景/暖光/冷光/高对比/低对比等"],
    "color": ["白色/黑色/暖色/冷色/高饱和/低饱和/莫兰迪/金属色等"],
    "composition": ["近景/中景/远景/俯拍/仰拍/正面/侧面/居中/留白/对称/特写等"],
    "mood": ["温馨/高级/清爽/科技/自然/浪漫/神秘/活力/安静等"],
    "use_case": ["广告/电商主图/海报/社媒/样机/参考图/背景/角色参考/空间参考等"],
    "objects": ["画面中重要物体"],
    "materials": ["木材/金属/玻璃/布料/皮革/石材/陶瓷等"],
    "quality": ["高清/模糊/低清/噪点/水印/截图/透明背景等"]
  },
  "tags": ["综合关键词，20个以内"]
}
要求：只返回可解析 JSON；每个数组最多 8 项；如果不确定就省略该标签。"""

ASSET_CLASSIFICATION_DIMENSION_NAMES = {
    "environment": "环境",
    "scene": "场景",
    "space": "空间",
    "subject": "主体",
    "model": "模特",
    "people": "人物",
    "style": "风格",
    "lighting": "光影",
    "color": "色彩",
    "composition": "构图",
    "mood": "氛围",
    "use_case": "用途",
    "objects": "物体",
    "materials": "材质",
    "quality": "质量",
}
