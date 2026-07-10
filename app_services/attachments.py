"""Attachment parsing, extraction, and asset classification."""

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

ATTACHMENTS_EXPORTS = (
    '_local_upload_classification_path',
    '_safe_asset_tag',
    'normalize_asset_classification',
    'parse_asset_classification_text',
    '_read_local_upload_classification',
    '_write_local_upload_classification',
    'asset_classification_prompt',
    'classify_image_with_provider',
    'classify_asset_image_best_effort',
    'migrate_asset_library_into_dirs',
    'asset_library_workflow_category',
    'make_workflow_library_item_from_bytes',
    'image_path_to_data_url',
    'builtin_prompt_templates',
    'sanitize_asset_name',
    'content_type_for_path',
    'is_image_reference_value',
    'is_video_reference_value',
    'convert_output_to_jpg',
    'reference_to_data_url',
    'is_image_reference',
    'image_references',
    '_xml_local_name',
    '_xlsx_join_text',
    '_xlsx_shared_strings',
    '_xlsx_sheet_paths',
    '_xlsx_cell_text',
    'read_xlsx_attachment',
    'xlsx_embedded_image_data_urls',
    'attachment_embedded_image_data_urls',
    'read_text_attachment',
    'attachment_text_blocks',
    'media_reference_to_url',
    'is_private_asset_url',
    'volcengine_media_reference_url',
    'looks_like_image_media_url',
    'volcengine_content_role',
    'volcengine_video_duration',
    'volcengine_video_resolution',
    'is_volcengine_seedance2_model',
    'probe_local_audio_duration_seconds',
    'volcengine_video_reference_content_items',
    'video_reference_to_frame_data_urls',
    'compress_data_url_image',
    'modelscope_image_url',
)


def configure_attachments(namespace: dict[str, Any]) -> None:
    required = {
        'ASSETS_DIR',
        'ASSET_LIBRARY_DIR',
        'CHAT_ATTACHMENT_MAX',
        'EXCEL_MAX_COLS_PER_ROW',
        'EXCEL_MAX_ROWS_PER_SHEET',
        'EXCEL_MAX_SHEETS',
        'LOCAL_UPLOAD_DIR',
        'MAX_ATTACHMENT_TEXT_CHARS',
        'OUTPUT_DIR',
        'TEXT_ATTACHMENT_EXTS',
        'XLSX_IMAGE_EXTS',
        'caption_image_with_provider',
        'find_asset_library',
        'get_primary_provider_id',
        'load_asset_library',
        'now_ms',
        'output_file_from_url',
        'parse_prompt_template_markdown',
        'prompt_template_markdown_path',
        'sanitize_export_filename',
        'save_asset_library',
        'unique_asset_category_dir',
    }
    missing = sorted(required - namespace.keys())
    if missing:
        raise RuntimeError(f"Attachments missing dependencies: {', '.join(missing)}")
    globals().update({name: namespace[name] for name in required})


def export_attachments(target: dict[str, Any]) -> None:
    for name in ATTACHMENTS_EXPORTS:
        target[name] = globals()[name]


def _local_upload_classification_path(filename):
    return os.path.splitext(os.path.join(LOCAL_UPLOAD_DIR, filename))[0] + ".classification.json"

def _safe_asset_tag(value, limit=24):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = re.sub(r"^[#＃]+", "", text).strip(" ,，、;；|/")
    return text[:limit]

def normalize_asset_classification(raw):
    if not isinstance(raw, dict):
        raw = {}
    categories = raw.get("categories") if isinstance(raw.get("categories"), dict) else {}
    clean_categories = {}
    flat = []
    for key, values in categories.items():
        norm_key = re.sub(r"[^A-Za-z0-9_-]+", "_", str(key or "").strip().lower())[:40]
        if not norm_key:
            continue
        if isinstance(values, str):
            values = re.split(r"[,，、/|;；\n]+", values)
        if not isinstance(values, list):
            continue
        clean_values = []
        seen = set()
        for value in values:
            tag = _safe_asset_tag(value)
            if not tag or tag in seen:
                continue
            seen.add(tag)
            clean_values.append(tag)
            flat.append({"dimension": norm_key, "label": ASSET_CLASSIFICATION_DIMENSION_NAMES.get(norm_key, norm_key), "tag": tag})
            if len(clean_values) >= 8:
                break
        if clean_values:
            clean_categories[norm_key] = clean_values
    tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
    clean_tags = []
    seen_tags = set()
    for value in tags:
        tag = _safe_asset_tag(value)
        if not tag or tag in seen_tags:
            continue
        seen_tags.add(tag)
        clean_tags.append(tag)
        flat.append({"dimension": "tags", "label": "标签", "tag": tag})
        if len(clean_tags) >= 20:
            break
    seen_flat = set()
    flat_unique = []
    for item in flat:
        key = f"{item['dimension']}::{item['tag']}"
        if key in seen_flat:
            continue
        seen_flat.add(key)
        flat_unique.append(item)
    return {
        "summary": str(raw.get("summary") or "").strip()[:240],
        "categories": clean_categories,
        "tags": clean_tags,
        "flat": flat_unique,
        "updated_at": now_ms(),
    }

def parse_asset_classification_text(text):
    value = str(text or "").strip()
    if not value:
        return normalize_asset_classification({})
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\s*```$", "", value).strip()
    try:
        data = json.loads(value)
    except Exception:
        match = re.search(r"\{.*\}", value, re.S)
        data = json.loads(match.group(0)) if match else {}
    return normalize_asset_classification(data)

def _read_local_upload_classification(filename):
    path = _local_upload_classification_path(filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return normalize_asset_classification(json.load(f))
    except Exception:
        return None

def _write_local_upload_classification(filename, classification):
    path = _local_upload_classification_path(filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalize_asset_classification(classification), f, ensure_ascii=False, indent=2)

def asset_classification_prompt(extra_prompt=""):
    extra = str(extra_prompt or "").strip()
    if not extra:
        return ASSET_CLASSIFICATION_PROMPT
    return ASSET_CLASSIFICATION_PROMPT + "\n\n用户补充分类要求：\n" + extra[:4000]

async def classify_image_with_provider(abs_path, provider_id="", model="", ms_model="", prompt=""):
    text, resolved_model = await caption_image_with_provider(
        abs_path,
        asset_classification_prompt(prompt),
        provider_id or get_primary_provider_id(),
        model,
        ms_model,
    )
    classification = parse_asset_classification_text(text)
    classification["model"] = resolved_model
    classification["provider"] = provider_id or get_primary_provider_id()
    return classification

async def classify_asset_image_best_effort(abs_path, provider_id="", model="", ms_model="", prompt=""):
    try:
        return await classify_image_with_provider(abs_path, provider_id, model, ms_model, prompt)
    except Exception as exc:
        print(f"素材智能分类失败: {exc}")
        return None

def migrate_asset_library_into_dirs():
    """一次性整理：给所有图片分组（含默认的角色/场景）补上真实文件夹，并把仍在 library/ 根目录的
    素材文件搬进各自分组的文件夹、同步更新 URL。幂等：已经在子文件夹里的不动；可安全反复执行。"""
    try:
        lib = load_asset_library()
    except Exception as exc:
        print(f"资产库分组整理：加载失败 {exc}")
        return
    changed = False
    for library in lib.get("libraries", []) or []:
        for cat in library.get("categories", []) or []:
            if (cat.get("type") or "image") != "image":
                continue
            if not cat.get("dir"):
                cat["dir"] = unique_asset_category_dir(library, cat.get("name") or "分组")
                changed = True
            cat_dir = str(cat.get("dir") or "").strip("/").strip()
            if not cat_dir:
                continue
            try:
                os.makedirs(os.path.join(ASSET_LIBRARY_DIR, cat_dir), exist_ok=True)
            except Exception as exc:
                print(f"资产库分组整理：建文件夹失败 {exc}")
                continue
            for item in (cat.get("items") or []):
                raw_url = urllib.parse.unquote(str(item.get("url") or "").split("?", 1)[0])
                m = re.match(r"^/assets/library/([^/]+)$", raw_url)  # 仅匹配仍在根目录的文件
                if not m:
                    continue
                fname = m.group(1)
                src = os.path.join(ASSET_LIBRARY_DIR, fname)
                if not os.path.isfile(src):
                    continue
                dst = os.path.join(ASSET_LIBRARY_DIR, cat_dir, fname)
                try:
                    if not os.path.exists(dst):
                        shutil.move(src, dst)
                    item["url"] = "/assets/library/" + urllib.parse.quote(f"{cat_dir}/{fname}", safe="/")
                    changed = True
                except Exception as exc:
                    print(f"资产库分组整理：搬运 {fname} 失败 {exc}")
    if changed:
        try:
            save_asset_library(lib)
        except Exception as exc:
            print(f"资产库分组整理：保存失败 {exc}")

def asset_library_workflow_category(lib, library_id="", category_id=""):
    library = find_asset_library(lib, library_id)
    if not library:
        raise HTTPException(status_code=404, detail="资产库不存在")
    categories = library.setdefault("categories", [])
    cat = None
    if category_id:
        cat = next((c for c in categories if c.get("id") == category_id), None)
        if not cat:
            raise HTTPException(status_code=404, detail="工作流分类不存在")
        if cat.get("type") != "workflow":
            raise HTTPException(status_code=400, detail="目标分组不是工作流分类")
    if not cat:
        cat = next((c for c in categories if c.get("type") == "workflow"), None)
    if not cat:
        cat = {"id": f"wf_{uuid.uuid4().hex[:12]}", "name": "工作流", "type": "workflow", "items": []}
        categories.append(cat)
    lib["active_library_id"] = library.get("id") or lib.get("active_library_id")
    return library, cat

def make_workflow_library_item_from_bytes(raw: bytes, filename: str, name: str = "") -> Dict[str, Any]:
    if not raw:
        raise HTTPException(status_code=400, detail="工作流文件为空")
    safe_filename = sanitize_export_filename(filename or "canvas-workflow.zip", "canvas-workflow.zip")
    ext = os.path.splitext(safe_filename)[1].lower()
    if ext not in {".json", ".zip"}:
        safe_filename += ".zip"
        ext = ".zip"
    dest_name = f"workflow_{uuid.uuid4().hex[:12]}_{safe_filename}"
    dest_path = os.path.join(ASSET_LIBRARY_DIR, dest_name)
    os.makedirs(ASSET_LIBRARY_DIR, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(raw)
    display_name = sanitize_asset_name(name or os.path.splitext(safe_filename)[0], "工作流")
    return {
        "id": f"wf_{uuid.uuid4().hex[:12]}",
        "name": display_name[:120],
        "url": f"/assets/library/{dest_name}",
        "kind": "workflow",
        "type": "workflow",
        "format": "zip" if ext == ".zip" else "json",
        "size": len(raw),
        "created_at": now_ms(),
    }

def image_path_to_data_url(path, max_size=1024):
    if max_size:
        try:
            with Image.open(path) as img:
                img.load()
                if max(img.size) > max_size:
                    img.thumbnail((max_size, max_size), Image.LANCZOS)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                buf = BytesIO()
                fmt = "PNG" if img.mode == "RGBA" else "JPEG"
                img.save(buf, format=fmt, quality=88 if fmt == "JPEG" else None)
                encoded = base64.b64encode(buf.getvalue()).decode("ascii")
                mime = "image/png" if fmt == "PNG" else "image/jpeg"
                return f"data:{mime};base64,{encoded}"
        except Exception as e:
            print(f"shared caption image resize failed: {e}")
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{content_type_for_path(path)};base64,{encoded}"

def builtin_prompt_templates():
    try:
        template_path = prompt_template_markdown_path()
        if not template_path:
            return []
        with open(template_path, "r", encoding="utf-8") as f:
            return parse_prompt_template_markdown(f.read())
    except Exception as e:
        print(f"读取提示词模板失败: {e}")
        return []

def sanitize_asset_name(name, fallback="asset"):
    name = re.sub(r'[\\/:*?"<>|]+', "_", str(name or fallback)).strip()
    return name[:120] or fallback

def content_type_for_path(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in [".mp4", ".m4v"]:
        return "video/mp4"
    if ext == ".webm":
        return "video/webm"
    if ext == ".mov":
        return "video/quicktime"
    if ext == ".avi":
        return "video/x-msvideo"
    if ext == ".mkv":
        return "video/x-matroska"
    if ext == ".flv":
        return "video/x-flv"
    if ext == ".mp3":
        return "audio/mpeg"
    if ext == ".wav":
        return "audio/wav"
    if ext == ".m4a":
        return "audio/mp4"
    if ext == ".aac":
        return "audio/aac"
    if ext == ".ogg":
        return "audio/ogg"
    if ext == ".flac":
        return "audio/flac"
    if ext == ".gif":
        return "image/gif"
    if ext in [".jpg", ".jpeg"]:
        return "image/jpeg"
    if ext == ".webp":
        return "image/webp"
    if ext == ".txt":
        return "text/plain; charset=utf-8"
    if ext == ".json":
        return "application/json; charset=utf-8"
    if ext == ".csv":
        return "text/csv; charset=utf-8"
    if ext == ".md":
        return "text/markdown; charset=utf-8"
    if ext == ".srt":
        return "application/x-subrip; charset=utf-8"
    if ext == ".vtt":
        return "text/vtt; charset=utf-8"
    if ext == ".png":
        return "image/png"
    return "application/octet-stream"

def is_image_reference_value(value):
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("data:image/"):
        return True
    if value.startswith("data:"):
        return False
    if value.startswith("/output/") or value.startswith("/assets/"):
        path = output_file_from_url(value)
        return bool(path and content_type_for_path(path).startswith("image/"))
    clean = value.split("?", 1)[0].lower()
    if re.search(r"\.(mp4|webm|mov|m4v|avi|mkv|mp3|wav|m4a|aac|ogg|flac)$", clean):
        return False
    return True

def is_video_reference_value(value):
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("data:video/"):
        return True
    if value.startswith("data:"):
        return False
    if value.startswith("/output/") or value.startswith("/assets/"):
        path = output_file_from_url(value)
        return bool(path and content_type_for_path(path).startswith("video/"))
    clean = value.split("?", 1)[0].lower()
    return bool(re.search(r"\.(mp4|webm|mov|m4v|avi|mkv)$", clean))

def convert_output_to_jpg(url, quality=88):
    path = output_file_from_url(url)
    if not path:
        return url
    root, ext = os.path.splitext(path)
    if ext.lower() in [".jpg", ".jpeg"]:
        return url
    jpg_path = f"{root}.jpg"
    try:
        with Image.open(path) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
            img.save(jpg_path, "JPEG", quality=quality, optimize=True)
        try:
            root = ASSETS_DIR if os.path.commonpath([os.path.abspath(ASSETS_DIR), os.path.abspath(jpg_path)]) == os.path.abspath(ASSETS_DIR) else OUTPUT_DIR
        except ValueError:
            root = OUTPUT_DIR
        rel = os.path.relpath(jpg_path, root).replace("\\", "/")
        prefix = "/assets" if root == ASSETS_DIR else "/output"
        return f"{prefix}/{rel}"
    except Exception as e:
        print(f"转换 JPG 失败: {e}")
        return url

def reference_to_data_url(ref, max_size=None):
    """把本地输出文件转为 data URL（base64）。max_size 限制最长边像素，避免 payload 过大。"""
    path = output_file_from_url(ref.get("url", ""))
    if not path:
        return ref.get("url", "")
    if max_size:
        try:
            with Image.open(path) as img:
                img.load()
                w, h = img.size
                if max(w, h) > max_size:
                    img.thumbnail((max_size, max_size), Image.LANCZOS)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                buf = BytesIO()
                fmt = "PNG" if img.mode == "RGBA" else "JPEG"
                img.save(buf, format=fmt, quality=88 if fmt == "JPEG" else None)
                encoded = base64.b64encode(buf.getvalue()).decode("ascii")
                mime = "image/png" if fmt == "PNG" else "image/jpeg"
                return f"data:{mime};base64,{encoded}"
        except Exception as e:
            print(f"reference resize failed, fallback to raw: {e}")
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{content_type_for_path(path)};base64,{encoded}"

def is_image_reference(ref):
    if not isinstance(ref, dict):
        return False
    kind = str(ref.get("kind") or "").strip().lower()
    mime = str(ref.get("mime") or "").strip().lower()
    url = str(ref.get("url") or "").strip().lower()
    if kind:
        return kind == "image"
    if mime:
        return mime.startswith("image/")
    return bool(re.search(r"\.(png|jpe?g|webp|gif|bmp|tiff?)(\?|#|$)", url))

def image_references(refs):
    return [ref for ref in (refs or []) if is_image_reference(ref)]

def _xml_local_name(tag):
    return str(tag or "").rsplit("}", 1)[-1]

def _xlsx_join_text(node):
    parts = []
    for child in node.iter():
        if _xml_local_name(child.tag) == "t" and child.text:
            parts.append(child.text)
    return "".join(parts).strip()

def _xlsx_shared_strings(archive):
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    values = []
    for node in root:
        if _xml_local_name(node.tag) == "si":
            values.append(_xlsx_join_text(node))
    return values

def _xlsx_sheet_paths(archive):
    names = set(archive.namelist())
    fallback = [(os.path.basename(name).rsplit(".", 1)[0], name) for name in sorted(names) if re.match(r"xl/worksheets/sheet\d+\.xml$", name)]
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {}
        for rel in rels:
            rid = rel.attrib.get("Id")
            target = rel.attrib.get("Target") or ""
            if not rid or not target:
                continue
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            rel_map[rid] = target.replace("\\", "/")
        result = []
        for sheet in workbook.iter():
            if _xml_local_name(sheet.tag) != "sheet":
                continue
            title = sheet.attrib.get("name") or "Sheet"
            rid = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rel_map.get(rid, "")
            if target in names:
                result.append((title, target))
        return result or fallback
    except Exception:
        return fallback

def _xlsx_cell_text(cell, shared_strings):
    cell_type = cell.attrib.get("t", "")
    value_node = None
    formula_node = None
    inline_node = None
    for child in cell:
        name = _xml_local_name(child.tag)
        if name == "v":
            value_node = child
        elif name == "f":
            formula_node = child
        elif name == "is":
            inline_node = child
    raw_value = (value_node.text if value_node is not None else "") or ""
    formula = (formula_node.text if formula_node is not None else "") or ""
    if cell_type == "s" and raw_value.isdigit():
        idx = int(raw_value)
        value = shared_strings[idx] if 0 <= idx < len(shared_strings) else raw_value
    elif cell_type == "inlineStr" and inline_node is not None:
        value = _xlsx_join_text(inline_node)
    elif cell_type == "b":
        value = "TRUE" if raw_value == "1" else "FALSE" if raw_value == "0" else raw_value
    else:
        value = raw_value
    value = str(value or "").strip()
    if formula and value:
        return f"{value} [={formula}]"
    if formula:
        return f"={formula}"
    return value

def read_xlsx_attachment(path, limit=None):
    if limit is None:
        limit = MAX_ATTACHMENT_TEXT_CHARS
    parts = []
    used = 0
    with zipfile.ZipFile(path) as archive:
        shared = _xlsx_shared_strings(archive)
        sheets = _xlsx_sheet_paths(archive)
        media_count = sum(1 for name in archive.namelist() if name.startswith("xl/media/") and os.path.splitext(name)[1].lower() in XLSX_IMAGE_EXTS)
        parts.append(f"Excel 工作簿：{os.path.basename(path)}")
        if media_count:
            parts.append(f"内嵌图片数量：{media_count}（已作为图片参考一并提供给模型）")
        for sheet_index, (sheet_name, sheet_path) in enumerate(sheets[:EXCEL_MAX_SHEETS], start=1):
            try:
                root = ET.fromstring(archive.read(sheet_path))
            except Exception:
                continue
            rows = []
            for row in root.iter():
                if _xml_local_name(row.tag) != "row":
                    continue
                cells = []
                for cell in row:
                    if _xml_local_name(cell.tag) != "c":
                        continue
                    ref = cell.attrib.get("r") or ""
                    value = _xlsx_cell_text(cell, shared)
                    if value:
                        cells.append(f"{ref}={value}" if ref else value)
                    if len(cells) >= EXCEL_MAX_COLS_PER_ROW:
                        break
                if cells:
                    row_ref = row.attrib.get("r") or str(len(rows) + 1)
                    rows.append(f"第 {row_ref} 行：" + " | ".join(cells))
                if len(rows) >= EXCEL_MAX_ROWS_PER_SHEET:
                    break
            if rows:
                section = f"\n工作表 {sheet_index}：{sheet_name}\n" + "\n".join(rows)
            else:
                section = f"\n工作表 {sheet_index}：{sheet_name}\n（未读取到非空单元格）"
            if used + len(section) > limit:
                remain = max(0, limit - used)
                if remain:
                    parts.append(section[:remain])
                parts.append("\n（Excel 内容较长，已截断）")
                break
            parts.append(section)
            used += len(section)
    return "\n".join(parts).strip()[:limit]

def xlsx_embedded_image_data_urls(path, max_images=4, max_size=1536):
    urls = []
    try:
        with zipfile.ZipFile(path) as archive:
            media = [name for name in archive.namelist() if name.startswith("xl/media/") and os.path.splitext(name)[1].lower() in XLSX_IMAGE_EXTS]
            for name in sorted(media)[:max_images]:
                try:
                    raw = archive.read(name)
                    with Image.open(BytesIO(raw)) as img:
                        img.load()
                        if max(img.size) > max_size:
                            img.thumbnail((max_size, max_size), Image.LANCZOS)
                        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                            bg = Image.new("RGB", img.size, (255, 255, 255))
                            bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
                            img = bg
                        elif img.mode != "RGB":
                            img = img.convert("RGB")
                        buf = BytesIO()
                        img.save(buf, format="JPEG", quality=88, optimize=True)
                        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
                        urls.append(f"data:image/jpeg;base64,{encoded}")
                except Exception as exc:
                    print(f"[chat] failed to extract xlsx image {name}: {exc}")
    except Exception as exc:
        print(f"[chat] failed to read xlsx images {path}: {exc}")
    return urls

def attachment_embedded_image_data_urls(refs, max_images=4):
    urls = []
    for ref in (refs or []):
        if not isinstance(ref, dict) or is_image_reference(ref):
            continue
        path = output_file_from_url(ref.get("url", ""))
        if not path or os.path.splitext(path)[1].lower() != ".xlsx":
            continue
        urls.extend(xlsx_embedded_image_data_urls(path, max_images=max(0, max_images - len(urls))))
        if len(urls) >= max_images:
            break
    return urls[:max_images]

def read_text_attachment(path, limit=None):
    if limit is None:
        limit = MAX_ATTACHMENT_TEXT_CHARS
    ext = os.path.splitext(path or "")[1].lower()
    if not path or not os.path.isfile(path):
        return ""
    try:
        if ext == ".xlsx":
            return read_xlsx_attachment(path, limit)
        if ext == ".xls":
            return "这是旧版 .xls 二进制 Excel 文件，当前内置解析器暂不支持直接读取内容。请另存为 .xlsx 后重新上传。"
        if ext == ".docx":
            with zipfile.ZipFile(path) as archive:
                raw = archive.read("word/document.xml")
            root = ET.fromstring(raw)
            parts = []
            for node in root.iter():
                if node.tag.endswith("}t") and node.text:
                    parts.append(node.text)
                elif node.tag.endswith("}p"):
                    parts.append("\n")
            return html.unescape("".join(parts)).strip()[:limit]
        if ext in TEXT_ATTACHMENT_EXTS:
            with open(path, "rb") as f:
                data = f.read(min(os.path.getsize(path), limit * 4))
            for encoding in ("utf-8-sig", "utf-8", "gb18030"):
                try:
                    return data.decode(encoding, errors="strict").strip()[:limit]
                except UnicodeDecodeError:
                    continue
            return data.decode("utf-8", errors="replace").strip()[:limit]
    except Exception as exc:
        print(f"[chat] failed to read attachment text {path}: {exc}")
    return ""

def attachment_text_blocks(refs, limit_each=None):
    if limit_each is None:
        limit_each = MAX_ATTACHMENT_TEXT_CHARS
    blocks = []
    for ref in (refs or [])[:CHAT_ATTACHMENT_MAX]:
        if not isinstance(ref, dict) or is_image_reference(ref):
            continue
        path = output_file_from_url(ref.get("url", ""))
        text = read_text_attachment(path, limit_each) if path else ""
        if not text:
            continue
        name = ref.get("name") or os.path.basename(path)
        blocks.append(f"附件：{name}\n{text}")
    return blocks

def media_reference_to_url(value, max_image_size=None):
    if not isinstance(value, str) or not value:
        return ""
    if value.startswith("/output/") or value.startswith("/assets/"):
        return reference_to_data_url({"url": value}, max_size=max_image_size)
    return value

def is_private_asset_url(value: str) -> bool:
    return isinstance(value, str) and value.strip().startswith("asset://")

def volcengine_media_reference_url(value, max_image_size=1536):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value:
        return ""
    if is_private_asset_url(value):
        return value
    if value.startswith("/output/") or value.startswith("/assets/"):
        return reference_to_data_url({"url": value}, max_size=max_image_size)
    return value

def looks_like_image_media_url(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text.startswith("data:image/"):
        return True
    if text.startswith("asset://"):
        return False
    path = urllib.parse.urlparse(text).path or text
    return bool(re.search(r"\.(png|jpe?g|webp|gif|bmp|tiff)$", path))

def volcengine_content_role(role: str, kind: str = "image") -> Optional[str]:
    value = str(role or "").strip().lower()
    allowed = {
        "first_frame", "last_frame", "reference_image",
        "reference_video", "reference_audio", "video", "audio", "image"
    }
    if value in allowed:
        if value == "audio" and kind == "audio":
            return "reference_audio"
        return "reference_video" if value == "video" and kind == "video" else value
    if kind == "audio":
        return "reference_audio"
    if kind == "video":
        return "reference_video"
    # 修复：未显式指定 role 的纯生图请求不应兜底为 reference_image，
    # 否则火山后端会误判为 r2v(参考图生视频)，导致 seedance/seedream 等生图模型失败。
    return None

def volcengine_video_duration(duration) -> int:
    try:
        value = int(duration)
    except Exception:
        value = 5
    return max(1, min(60, value))

def volcengine_video_resolution(value: str) -> str:
    text = str(value or "").strip().lower()
    aliases = {"": "", "auto": "", "480": "480p", "720": "720p", "1080": "1080p"}
    text = aliases.get(text, text)
    return text if text in {"480p", "720p", "1080p"} else ""

def is_volcengine_seedance2_model(model: str) -> bool:
    value = str(model or "").strip().lower().replace("_", "-").replace(".", "-")
    return "seedance-2-0" in value

def probe_local_audio_duration_seconds(value: str) -> Optional[float]:
    path = output_file_from_url(value)
    if not path or not os.path.isfile(path):
        return None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode != 0:
            return None
        duration = float(str(proc.stdout or "").strip())
        return duration if math.isfinite(duration) and duration > 0 else None
    except Exception:
        return None

async def volcengine_video_reference_content_items(value, max_frames=4, max_size=768):
    text = str(value or "").strip()
    if not text:
        return []
    if is_private_asset_url(text):
        return [{
            "type": "video_url",
            "video_url": {"url": text},
            "role": "reference_video",
        }]
    frame_urls = await video_reference_to_frame_data_urls(text, max_frames=max_frames, max_size=max_size)
    return [
        {
            "type": "image_url",
            "image_url": {"url": frame_url},
            "role": "reference_image",
        }
        for frame_url in frame_urls
        if frame_url
    ]

async def video_reference_to_frame_data_urls(value, max_frames=6, max_size=768):
    if not isinstance(value, str) or not value:
        return []
    path = output_file_from_url(value)
    cleanup_path = ""
    if not path and value.startswith(("http://", "https://")):
        suffix = os.path.splitext(urllib.parse.urlparse(value).path)[1] or ".mp4"
        fd, cleanup_path = tempfile.mkstemp(prefix="canvas_llm_video_", suffix=suffix)
        os.close(fd)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=120.0, write=30.0, pool=10.0)) as client:
                response = await client.get(value)
                response.raise_for_status()
                with open(cleanup_path, "wb") as f:
                    f.write(response.content)
            path = cleanup_path
        except Exception as e:
            print(f"[canvas-llm] video download failed: {e}")
            if cleanup_path and os.path.exists(cleanup_path):
                try: os.remove(cleanup_path)
                except OSError: pass
            return []
    if not path or not os.path.exists(path):
        return []
    frame_dir = tempfile.mkdtemp(prefix="canvas_llm_frames_")
    try:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return []
        pattern = os.path.join(frame_dir, "frame_%03d.jpg")
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", path,
            "-vf", f"fps=1,scale='min({max_size},iw)':-2",
            "-frames:v", str(max(1, max_frames)),
            pattern
        ]
        proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode != 0:
            print(f"[canvas-llm] ffmpeg frame extract failed: {proc.stderr[:300]}")
            return []
        frames = []
        for name in sorted(os.listdir(frame_dir)):
            if not name.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            frame_path = os.path.join(frame_dir, name)
            with open(frame_path, "rb") as f:
                frames.append(f"data:image/jpeg;base64,{base64.b64encode(f.read()).decode('ascii')}")
        return frames
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)
        if cleanup_path and os.path.exists(cleanup_path):
            try: os.remove(cleanup_path)
            except OSError: pass

def compress_data_url_image(value, max_size=1536, jpeg_quality=88):
    if not isinstance(value, str) or not value.startswith("data:image/") or ";base64," not in value:
        return value
    header, encoded = value.split(";base64,", 1)
    try:
        raw = base64.b64decode(encoded)
        with Image.open(BytesIO(raw)) as img:
            img.load()
            if max_size and max(img.size) > max_size:
                img.thumbnail((max_size, max_size), Image.LANCZOS)
            has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
            if has_alpha:
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                fmt, mime = "PNG", "image/png"
            else:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                fmt, mime = "JPEG", "image/jpeg"
            buf = BytesIO()
            if fmt == "JPEG":
                img.save(buf, format=fmt, quality=jpeg_quality, optimize=True)
            else:
                img.save(buf, format=fmt, optimize=True)
            return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
    except Exception as e:
        print(f"data url image compress failed, fallback to raw: {e}")
        return value

def modelscope_image_url(value, max_size=1536):
    if not value:
        return value
    if isinstance(value, str) and (value.startswith("/output/") or value.startswith("/assets/")):
        return reference_to_data_url({"url": value}, max_size=max_size)
    return value
