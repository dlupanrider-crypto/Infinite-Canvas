"""Extracted canvas index services."""

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


CANVAS_INDEX_EXPORTS = (
    'now_ms',
    'canvas_asset_url_value',
    'canvas_asset_downloadable_url',
    'canvas_asset_kind',
    'canvas_asset_name',
    'iter_canvas_asset_values',
    'canvas_node_title',
    'extract_canvas_assets',
    'canvas_assets_index',
)


def configure_canvas_index(namespace: dict[str, Any]) -> None:
    required = {
        'CANVAS_DIR',
        'asset_library_media_kind',
        'canvas_record',
        'cleanup_expired_canvas_trash',
        'filename_from_media_url',
        'sanitize_asset_name',
    }
    missing = sorted(required - namespace.keys())
    if missing:
        raise RuntimeError(f"Canvas Index missing dependencies: {', '.join(missing)}")
    globals().update({name: namespace[name] for name in required})


def export_canvas_index(target: dict[str, Any]) -> None:
    for name in CANVAS_INDEX_EXPORTS:
        target[name] = globals()[name]


def now_ms():
    return int(time.time() * 1000)

def canvas_asset_url_value(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("url", "path", "src", "uri", "output", "output_url", "outputUrl", "video", "video_url", "videoUrl"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
    return ""

def canvas_asset_downloadable_url(url):
    text = str(url or "").strip()
    return text if text.startswith(("/output/", "/assets/", "http://", "https://")) else ""

def canvas_asset_kind(value, url=""):
    explicit = ""
    if isinstance(value, dict):
        explicit = str(value.get("kind") or value.get("mediaKind") or value.get("type") or "").lower()
    if "video" in explicit:
        return "video"
    if "audio" in explicit:
        return "audio"
    if "text" in explicit:
        return "text"
    if "workflow" in explicit:
        return "workflow"
    return asset_library_media_kind(url or canvas_asset_url_value(value))

def canvas_asset_name(value, url="", fallback="asset"):
    if isinstance(value, dict):
        for key in ("name", "filename", "file", "title"):
            name = str(value.get(key) or "").strip()
            if name:
                return sanitize_asset_name(name, fallback)
    return sanitize_asset_name(filename_from_media_url(url, fallback), fallback)

def iter_canvas_asset_values(value, path=""):
    if isinstance(value, dict):
        url = canvas_asset_downloadable_url(canvas_asset_url_value(value))
        if url:
            yield path, value, url
        for key, child in value.items():
            if key in {"run", "runs", "settings", "params", "metadata", "meta", "prompt", "text", "caption", "logs"}:
                continue
            yield from iter_canvas_asset_values(child, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_canvas_asset_values(child, f"{path}[{index}]")
    elif isinstance(value, str):
        url = canvas_asset_downloadable_url(value)
        if url:
            yield path, value, url

def canvas_node_title(node):
    if not isinstance(node, dict):
        return ""
    return str(node.get("title") or node.get("name") or node.get("label") or node.get("type") or "节点")[:120]

def extract_canvas_assets(canvas):
    record = canvas_record(canvas)
    canvas_id = str(record.get("id") or "")
    items = []
    seen = set()
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or f"node_{node_index}")
        node_title = canvas_node_title(node)
        for field_path, raw, url in iter_canvas_asset_values(node):
            dedupe_key = url
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            kind = canvas_asset_kind(raw, url)
            if kind not in {"image", "video", "audio", "text"}:
                continue
            fallback = f"{record.get('title') or 'canvas'}-{len(items) + 1}"
            item = {
                "id": hashlib.sha1(f"{canvas_id}:{url}".encode("utf-8")).hexdigest()[:24],
                "url": url,
                "name": canvas_asset_name(raw, url, fallback),
                "kind": kind,
                "canvas_id": canvas_id,
                "canvas_title": record.get("title") or "未命名画布",
                "canvas_kind": record.get("kind") or "classic",
                "canvas_icon": record.get("icon") or "layers",
                "canvas_owner": record.get("owner") or "",
                "canvas_color": record.get("color") or "",
                "canvas_created_at": record.get("created_at") or 0,
                "canvas_updated_at": record.get("updated_at") or 0,
                "node_id": node_id,
                "node_title": node_title,
                "node_type": str(node.get("type") or ""),
                "source_path": field_path,
                "created_at": node.get("created_at") or record.get("updated_at") or record.get("created_at") or 0,
            }
            if isinstance(raw, dict):
                for key in ("natural_w", "natural_h", "width", "height", "size", "duration", "runMs"):
                    if raw.get(key) is not None:
                        item[key] = raw.get(key)
            items.append(item)
    return items

def canvas_assets_index():
    canvases = []
    items = []
    canvas_counts = {"all": 0, "smart": 0, "classic": 0}
    item_counts = {"all": 0, "smart": 0, "classic": 0}
    cleanup_expired_canvas_trash()
    for filename in os.listdir(CANVAS_DIR):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(CANVAS_DIR, filename), "r", encoding="utf-8") as f:
                canvas = json.load(f)
        except Exception:
            continue
        if canvas.get("deleted_at"):
            continue
        record = canvas_record(canvas)
        canvas_items = extract_canvas_assets(canvas)
        record["asset_count"] = len(canvas_items)
        canvases.append(record)
        items.extend(canvas_items)
        kind = record.get("kind") or "classic"
        canvas_counts["all"] += 1
        canvas_counts[kind] = canvas_counts.get(kind, 0) + 1
        item_counts["all"] += len(canvas_items)
        item_counts[kind] = item_counts.get(kind, 0) + len(canvas_items)
    canvases.sort(key=lambda item: (0 if item.get("pinned") else 1, -int(item.get("updated_at") or item.get("created_at") or 0)))
    items.sort(key=lambda item: int(item.get("canvas_updated_at") or item.get("created_at") or 0), reverse=True)
    categories = [
        {"id": "all", "name": "全部画布", "count": item_counts.get("all", 0), "canvas_count": canvas_counts.get("all", 0)},
        {"id": "smart", "name": "智能画布", "count": item_counts.get("smart", 0), "canvas_count": canvas_counts.get("smart", 0)},
        {"id": "classic", "name": "普通画布", "count": item_counts.get("classic", 0), "canvas_count": canvas_counts.get("classic", 0)},
    ]
    return {"categories": categories, "canvases": canvases, "items": items}
