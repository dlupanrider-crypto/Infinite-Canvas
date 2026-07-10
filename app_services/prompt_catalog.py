"""Extracted prompt catalog services."""

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


PROMPT_CATALOG_EXPORTS = (
    'prompt_template_markdown_path',
    'prompt_template_category',
    'extract_prompt_template_section',
    'parse_prompt_template_markdown',
)


def configure_prompt_catalog(namespace: dict[str, Any]) -> None:
    required = {
        'PROMPT_TEMPLATE_EN',
        'PROMPT_TEMPLATE_PATHS',
    }
    missing = sorted(required - namespace.keys())
    if missing:
        raise RuntimeError(f"Prompt Catalog missing dependencies: {', '.join(missing)}")
    globals().update({name: namespace[name] for name in required})


def export_prompt_catalog(target: dict[str, Any]) -> None:
    for name in PROMPT_CATALOG_EXPORTS:
        target[name] = globals()[name]


def prompt_template_markdown_path() -> str:
    for path in PROMPT_TEMPLATE_PATHS:
        if os.path.exists(path):
            return path
    return ""

def prompt_template_category(name: str, scene: str) -> str:
    text = f"{name} {scene}"
    if any(k in text for k in ["光影", "灯光", "光效", "电影级"]):
        return "lighting"
    if any(k in text for k in ["视角", "全景", "VR", "镜头", "俯拍", "仰拍", "景别", "构图", "透视"]):
        return "view"
    if any(k in text for k in ["角色", "脸部", "表情", "Actor", "服装"]):
        return "character"
    if any(k in name for k in ["产品", "电商", "工业"]):
        return "product"
    return "storyboard"

def extract_prompt_template_section(block: str, title: str) -> str:
    pattern = rf"###\s*{re.escape(title)}\s*\n(?P<body>.*?)(?=\n###\s+|\Z)"
    match = re.search(pattern, block, re.S)
    if not match:
        return ""
    body = match.group("body").strip()
    fence = re.search(r"```(?:\w+)?\s*\n(?P<code>.*?)\n```", body, re.S)
    return (fence.group("code") if fence else body).strip()

def parse_prompt_template_markdown(text: str):
    templates = []
    matches = list(re.finditer(r"^##\s*预设\s*(\d+)\s*[：:]\s*(.+?)\s*$", text, re.M))
    for index, match in enumerate(matches):
        number = match.group(1).strip()
        name = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end]
        scene = extract_prompt_template_section(block, "适用场景")
        positive = extract_prompt_template_section(block, "正向提示词")
        negative = extract_prompt_template_section(block, "负向提示词")
        params_raw = extract_prompt_template_section(block, "平台参数建议")
        params = {}
        for line in params_raw.splitlines():
            item = re.match(r"[-*]\s*\*\*(.+?)\*\*\s*[：:]\s*(.+)", line.strip())
            if item:
                params[item.group(1).strip()] = item.group(2).strip()
        if not positive:
            continue
        templates.append({
            "id": f"builtin_md_{number}",
            "number": number,
            "name": name,
            "name_en": PROMPT_TEMPLATE_EN.get(name, {}).get("name", name),
            "category": prompt_template_category(name, scene),
            "scene": scene,
            "scene_en": PROMPT_TEMPLATE_EN.get(name, {}).get("scene", scene),
            "positive": positive,
            "negative": negative,
            "params": params,
            "builtin": True,
        })
    return templates
