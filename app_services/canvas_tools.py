"""Canvas asset indexing, archives, workflow import/export, and group export."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
import urllib.parse
import uuid
import zipfile
from io import BytesIO
from typing import Any, List

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from repositories.asset_library import load_asset_library, save_asset_library
from routers.canvas_tools import (
    CanvasAssetCheckRequest,
    CanvasAssetDownloadRequest,
    CanvasWorkflowExportRequest,
    SmartCanvasGroupExportRequest,
)


CANVAS_TOOL_EXPORTS = (
    "list_canvas_assets",
    "smart_canvas_prompt_templates",
    "check_canvas_assets",
    "download_canvas_assets",
    "sanitize_export_filename",
    "canvas_workflow_collect_resource_refs",
    "canvas_workflow_unique_archive_name",
    "canvas_workflow_replace_strings",
    "canvas_workflow_payload",
    "build_canvas_workflow_archive",
    "export_canvas_workflow",
    "export_canvas_workflow_to_library",
    "upload_asset_library_workflows",
    "import_canvas_workflow",
    "smart_group_export_folder",
    "export_smart_canvas_group",
)


def configure_canvas_tool_service(**dependencies: Any) -> None:
    required = {
        "ASSETS_DIR",
        "BASE_DIR",
        "OUTPUT_DIR",
        "OUTPUT_INPUT_DIR",
        "asset_library_workflow_category",
        "builtin_prompt_templates",
        "canvas_assets_index",
        "fetch_remote_media_bytes",
        "filename_from_media_url",
        "local_media_file_by_basename",
        "make_workflow_library_item_from_bytes",
        "now_ms",
        "output_file_from_url",
        "prompt_template_markdown_path",
    }
    missing = sorted(required - dependencies.keys())
    if missing:
        raise RuntimeError(f"Canvas tool service missing dependencies: {', '.join(missing)}")
    globals().update(dependencies)


def export_canvas_tool_service(target: dict[str, Any]) -> None:
    for name in CANVAS_TOOL_EXPORTS:
        target[name] = globals()[name]

async def list_canvas_assets():
    # canvas_assets_index 会同步遍历并解析所有画布 JSON，放进线程池避免阻塞事件循环
    # （否则画布多时一次请求就会卡住整个 asyncio loop，连 WebSocket 一起掉线）。
    return await asyncio.to_thread(canvas_assets_index)

async def smart_canvas_prompt_templates():
    try:
        template_path = prompt_template_markdown_path()
        source = os.path.relpath(template_path, BASE_DIR).replace("\\", "/") if template_path else ""
        return {"templates": builtin_prompt_templates(), "source": source}
    except Exception as e:
        print(f"读取提示词模板失败: {e}")
        return {"templates": []}

async def check_canvas_assets(payload: CanvasAssetCheckRequest):
    result = {}
    for url in payload.urls[:3000]:
        text = str(url or "").strip()
        if not text:
            continue
        if text.startswith("/output/") or text.startswith("/assets/"):
            result[text] = bool(output_file_from_url(text))
        else:
            result[text] = True
    return {"exists": result}

async def download_canvas_assets(payload: CanvasAssetDownloadRequest):
    buffer = BytesIO()
    used_names = set()
    count = 0
    raw_items = payload.items or [{"url": url} for url in payload.urls]
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for raw in raw_items[:1000]:
            if isinstance(raw, dict):
                text = str(raw.get("url") or "").strip()
                requested_name = str(raw.get("name") or "").strip()
            else:
                text = str(raw or "").strip()
                requested_name = ""
            if not text:
                continue
            path = output_file_from_url(text)
            content = None
            content_type = ""
            if path and os.path.isfile(path):
                base = sanitize_export_filename(requested_name or os.path.basename(path), os.path.basename(path) or f"image-{count + 1}.png")
            else:
                local_by_name = local_media_file_by_basename(filename_from_media_url(text, ""))
                if local_by_name and os.path.isfile(local_by_name):
                    path = local_by_name
                    base = sanitize_export_filename(requested_name or os.path.basename(path), os.path.basename(path) or f"image-{count + 1}.png")
                else:
                    try:
                        remote = fetch_remote_media_bytes(text)
                    except Exception:
                        remote = None
                    if not remote:
                        continue
                    content, content_type = remote
                    base = sanitize_export_filename(requested_name or filename_from_media_url(text, f"image-{count + 1}.bin"), f"image-{count + 1}.bin")
            name, ext = os.path.splitext(base)
            archive_name = base
            suffix = 2
            while archive_name in used_names:
                archive_name = f"{name}-{suffix}{ext}"
                suffix += 1
            used_names.add(archive_name)
            if path and os.path.isfile(path):
                zf.write(path, archive_name)
            else:
                zf.writestr(archive_name, content)
            count += 1
    if count <= 0:
        raise HTTPException(status_code=404, detail="没有可下载的本地图片")
    buffer.seek(0)
    filename = re.sub(r'[\\/:*?"<>|]+', "_", payload.filename or "canvas-output-images.zip")
    if not filename.lower().endswith(".zip"):
        filename += ".zip"
    encoded = urllib.parse.quote(filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    return Response(buffer.getvalue(), media_type="application/zip", headers=headers)

def sanitize_export_filename(name: str, fallback: str) -> str:
    base = os.path.basename(str(name or "").strip()) or fallback
    base = re.sub(r'[\\/:*?"<>|]+', "_", base)
    return base or fallback

def canvas_workflow_collect_resource_refs(value, found=None):
    if found is None:
        found = []
    if isinstance(value, dict):
        for item in value.values():
            canvas_workflow_collect_resource_refs(item, found)
    elif isinstance(value, list):
        for item in value:
            canvas_workflow_collect_resource_refs(item, found)
    elif isinstance(value, str):
        text = value.strip()
        if (text.startswith("/assets/") or text.startswith("/output/")) and output_file_from_url(text):
            found.append(text)
    return found

def canvas_workflow_unique_archive_name(base, used):
    safe = sanitize_export_filename(base, "resource.bin")
    name, ext = os.path.splitext(safe)
    archive = safe
    idx = 2
    while archive in used:
        archive = f"{name}-{idx}{ext}"
        idx += 1
    used.add(archive)
    return archive

def canvas_workflow_replace_strings(value, mapping):
    if isinstance(value, dict):
        return {k: canvas_workflow_replace_strings(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [canvas_workflow_replace_strings(item, mapping) for item in value]
    if isinstance(value, str):
        return mapping.get(value, value)
    return value

def canvas_workflow_payload(nodes, connections, resources=None):
    return {
        "format": "infinite-canvas-workflow",
        "version": 1,
        "exported_at": now_ms(),
        "nodes": nodes or [],
        "connections": connections or [],
        "resources": resources or [],
    }

def build_canvas_workflow_archive(payload: CanvasWorkflowExportRequest) -> Tuple[bytes, Dict[str, Any]]:
    nodes_payload = payload.nodes or []
    connections_payload = payload.connections or []
    if not nodes_payload:
        raise HTTPException(status_code=400, detail="没有可导出的节点")
    buffer = BytesIO()
    resources = []
    used = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if payload.include_resources:
            for url in canvas_workflow_collect_resource_refs(nodes_payload):
                if any(item.get("url") == url for item in resources):
                    continue
                path = output_file_from_url(url)
                if not path or not os.path.isfile(path):
                    continue
                archive_name = canvas_workflow_unique_archive_name(os.path.basename(path), used)
                archive_path = f"resources/{archive_name}"
                zf.write(path, archive_path)
                resources.append({
                    "url": url,
                    "archive": archive_path,
                    "name": os.path.basename(path),
                    "size": os.path.getsize(path),
                })
        workflow = canvas_workflow_payload(nodes_payload, connections_payload, resources)
        zf.writestr("workflow.json", json.dumps(workflow, ensure_ascii=False, indent=2))
    buffer.seek(0)
    return buffer.getvalue(), {"resources": resources, "node_count": len(nodes_payload), "connection_count": len(connections_payload)}

async def export_canvas_workflow(payload: CanvasWorkflowExportRequest):
    archive, _ = build_canvas_workflow_archive(payload)
    filename = sanitize_export_filename(payload.filename or "canvas-workflow.zip", "canvas-workflow.zip")
    if not filename.lower().endswith(".zip"):
        filename += ".zip"
    encoded = urllib.parse.quote(filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    return Response(archive, media_type="application/zip", headers=headers)

async def export_canvas_workflow_to_library(payload: CanvasWorkflowExportRequest):
    archive, meta = build_canvas_workflow_archive(payload)
    filename = sanitize_export_filename(payload.filename or "canvas-workflow.zip", "canvas-workflow.zip")
    if not filename.lower().endswith(".zip"):
        filename += ".zip"
    lib = load_asset_library()
    _, cat = asset_library_workflow_category(lib, payload.library_id, payload.category_id)
    item = make_workflow_library_item_from_bytes(archive, filename, payload.name or os.path.splitext(filename)[0])
    item["node_count"] = meta.get("node_count") or len(payload.nodes or [])
    item["connection_count"] = meta.get("connection_count") or len(payload.connections or [])
    item["resource_count"] = len(meta.get("resources") or [])
    cat.setdefault("items", []).append(item)
    save_asset_library(lib)
    return {"library": lib, "item": item}

async def upload_asset_library_workflows(
    files: List[UploadFile] = File(...),
    library_id: str = Form(""),
    category_id: str = Form(""),
):
    lib = load_asset_library()
    _, cat = asset_library_workflow_category(lib, library_id, category_id)
    added = []
    for file in files[:100]:
        raw = await file.read()
        filename = file.filename or "canvas-workflow.zip"
        lower = filename.lower()
        if not (lower.endswith(".json") or lower.endswith(".zip") or raw[:2] == b"PK"):
            continue
        item = make_workflow_library_item_from_bytes(raw, filename, os.path.splitext(filename)[0])
        cat.setdefault("items", []).append(item)
        added.append(item)
    if not added:
        raise HTTPException(status_code=400, detail="没有可上传的工作流文件")
    save_asset_library(lib)
    return {"library": lib, "items": added}

async def import_canvas_workflow(file: UploadFile = File(...)):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件为空")
    name = str(file.filename or "").lower()
    resource_mapping = {}
    workflow = None
    try:
        if name.endswith(".zip") or raw[:2] == b"PK":
            with zipfile.ZipFile(BytesIO(raw), "r") as zf:
                candidates = [n for n in zf.namelist() if n.lower().endswith("workflow.json")]
                workflow_name = "workflow.json" if "workflow.json" in zf.namelist() else (candidates[0] if candidates else "")
                if not workflow_name:
                    raise HTTPException(status_code=400, detail="压缩包中没有 workflow.json")
                workflow = json.loads(zf.read(workflow_name).decode("utf-8-sig"))
                stamp = time.strftime("%Y%m%d-%H%M%S")
                import_dir = os.path.join(OUTPUT_INPUT_DIR, f"workflow_import_{stamp}_{uuid.uuid4().hex[:6]}")
                os.makedirs(import_dir, exist_ok=True)
                for res in workflow.get("resources") or []:
                    archive = str(res.get("archive") or "").replace("\\", "/").lstrip("/")
                    if not archive or archive not in zf.namelist():
                        continue
                    base = sanitize_export_filename(res.get("name") or os.path.basename(archive), os.path.basename(archive) or "resource.bin")
                    target = os.path.join(import_dir, f"{uuid.uuid4().hex[:8]}_{base}")
                    with zf.open(archive) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    rel = os.path.relpath(target, ASSETS_DIR).replace("\\", "/")
                    new_url = f"/assets/{rel}"
                    old_url = str(res.get("url") or "").strip()
                    if old_url:
                        resource_mapping[old_url] = new_url
                    resource_mapping[archive] = new_url
                    resource_mapping[f"./{archive}"] = new_url
                    resource_mapping[os.path.basename(archive)] = new_url
        else:
            workflow = json.loads(raw.decode("utf-8-sig"))
    except HTTPException:
        raise
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="无法读取压缩包") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法解析工作流文件：{exc}") from exc
    if isinstance(workflow, list):
        workflow = {"nodes": workflow, "connections": []}
    if not isinstance(workflow, dict):
        raise HTTPException(status_code=400, detail="工作流格式不正确")
    nodes_payload = workflow.get("nodes")
    connections_payload = workflow.get("connections")
    if nodes_payload is None and isinstance(workflow.get("workflow"), dict):
        nodes_payload = workflow["workflow"].get("nodes")
        connections_payload = workflow["workflow"].get("connections")
    if not isinstance(nodes_payload, list):
        raise HTTPException(status_code=400, detail="工作流 JSON 缺少 nodes")
    if not isinstance(connections_payload, list):
        connections_payload = []
    if resource_mapping:
        nodes_payload = canvas_workflow_replace_strings(nodes_payload, resource_mapping)
        connections_payload = canvas_workflow_replace_strings(connections_payload, resource_mapping)
    return {
        "workflow": canvas_workflow_payload(nodes_payload, connections_payload, workflow.get("resources") or []),
        "nodes": nodes_payload,
        "connections": connections_payload,
        "resource_map": resource_mapping,
    }

def smart_group_export_folder(folder: str, group_name: str) -> str:
    text = str(folder or "").strip()
    if text:
        path = os.path.abspath(os.path.expanduser(text))
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe_group = sanitize_export_filename(group_name or "group", "group")
        path = os.path.abspath(os.path.join(OUTPUT_DIR, "smart-groups", f"{safe_group}-{stamp}"))
    os.makedirs(path, exist_ok=True)
    return path

async def export_smart_canvas_group(payload: SmartCanvasGroupExportRequest):
    target_dir = smart_group_export_folder(payload.folder, payload.group_name)
    used_names = set()
    count = 0
    text_index = 1
    for item in payload.items[:2000]:
        kind = str(item.kind or "").lower()
        if kind == "text":
            text = str(item.text or "")
            if not text.strip():
                continue
            base = sanitize_export_filename(item.name or f"{text_index}.txt", f"{text_index}.txt")
            if not base.lower().endswith(".txt"):
                base += ".txt"
            text_index += 1
            name, ext = os.path.splitext(base)
            out_name = base
            suffix = 2
            while out_name in used_names:
                out_name = f"{name}-{suffix}{ext}"
                suffix += 1
            used_names.add(out_name)
            with open(os.path.join(target_dir, out_name), "w", encoding="utf-8") as f:
                f.write(text)
            count += 1
            continue
        src = output_file_from_url(item.url)
        if not src or not os.path.isfile(src):
            continue
        base = sanitize_export_filename(item.name or os.path.basename(src), os.path.basename(src) or f"asset-{count + 1}")
        name, ext = os.path.splitext(base)
        if not ext:
            _, src_ext = os.path.splitext(src)
            ext = src_ext or ".bin"
            base = name + ext
        out_name = base
        suffix = 2
        while out_name in used_names:
            out_name = f"{name}-{suffix}{ext}"
            suffix += 1
        used_names.add(out_name)
        shutil.copy2(src, os.path.join(target_dir, out_name))
        count += 1
    if count <= 0:
        raise HTTPException(status_code=404, detail="没有可导出的内容")
    return {"ok": True, "folder": target_dir, "count": count}
