"""Asset-library item add, classify, avatar, move, crop, and delete services."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import httpx
from fastapi import HTTPException
from PIL import Image

from api_models import CanvasLLMRequest
from app_services.media_files import (
    asset_library_media_kind,
    make_asset_library_item,
    output_file_from_url,
    remove_asset_library_file,
)
from app_services.provider_routing import (
    is_apimart_provider,
    is_codex_provider,
    is_gemini_cli_provider,
)
from provider_adapters.cli import codex_chat_text, gemini_cli_chat_text
from provider_adapters.image import friendly_chat_error_detail
from repositories.asset_library import (
    find_asset_category_in_library,
    load_asset_library,
    save_asset_library,
)
from routers.asset_items import (
    AssetAvatarRegisterRequest,
    AssetLibraryAddRequest,
    AssetLibraryBatchAddRequest,
    AssetLibraryBatchCropRequest,
    AssetLibraryBatchDeleteRequest,
    AssetLibraryBatchMoveRequest,
    AssetLibraryClassifyRequest,
    AssetLibraryRenameRequest,
)


ASSET_ITEM_EXPORTS = (
    "add_asset_library_item",
    "batch_add_asset_library_items",
    "caption_image_with_provider",
    "rename_asset_library_item",
    "find_asset_item_in_library",
    "classify_asset_library_items",
    "register_asset_library_avatar",
    "check_asset_library_avatar",
    "delete_asset_library_item",
    "batch_delete_asset_library_items",
    "batch_move_asset_library_items",
    "batch_crop_asset_library_items",
)


def configure_asset_item_service(**dependencies: Any) -> None:
    required = {
        "AI_REQUEST_TIMEOUT",
        "AVATAR_SUPPORTED_PLATFORMS",
        "CODEX_DEFAULT_CHAT_MODELS",
        "GEMINI_CLI_DEFAULT_CHAT_MODELS",
        "VIDEO_POLL_TIMEOUT",
        "VOLCENGINE_DEFAULT_PROJECT_NAME",
        "avatar_platform_for_provider",
        "check_apimart_avatar_task",
        "check_volcengine_avatar_task",
        "classify_asset_image_best_effort",
        "classify_image_with_provider",
        "get_api_provider",
        "image_path_to_data_url",
        "log_net_error",
        "now_ms",
        "resolve_chat_provider",
        "sanitize_asset_name",
        "selected_model",
        "submit_apimart_avatar_asset",
        "submit_volcengine_avatar_asset",
        "text_from_chat_response",
        "upload_media_for_apimart",
        "valid_apimart_video_image_input",
        "volcengine_public_asset_url",
    }
    missing = sorted(required - dependencies.keys())
    if missing:
        raise RuntimeError(f"Asset item service missing dependencies: {', '.join(missing)}")
    globals().update(dependencies)


def export_asset_item_service(target: dict[str, Any]) -> None:
    for name in ASSET_ITEM_EXPORTS:
        target[name] = globals()[name]

async def add_asset_library_item(payload: AssetLibraryAddRequest):
    lib = load_asset_library()
    cat = find_asset_category_in_library(lib, payload.category_id, payload.library_id)
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    if cat.get("type") != "image":
        raise HTTPException(status_code=400, detail="该分类暂不支持添加媒体")
    src = output_file_from_url(payload.url)
    if not src:
        raise HTTPException(status_code=400, detail="只支持保存本地 /assets 或 /output 媒体")
    _, item = make_asset_library_item(src, payload.name or os.path.basename(src), subdir=cat.get("dir") or "")
    if item.get("kind") == "image":
        classification = await classify_asset_image_best_effort(output_file_from_url(item.get("url") or "") or src)
        if classification:
            item["classification"] = classification
    cat.setdefault("items", []).append(item)
    save_asset_library(lib)
    return {"library": lib, "item": item}

async def batch_add_asset_library_items(payload: AssetLibraryBatchAddRequest):
    added = []
    lib = load_asset_library()
    cat = find_asset_category_in_library(lib, payload.category_id, payload.library_id)
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    if cat.get("type") != "image":
        raise HTTPException(status_code=400, detail="该分类暂不支持添加媒体")
    for entry in (payload.items or [])[:200]:
        entry.category_id = payload.category_id
        entry.library_id = payload.library_id
        src = output_file_from_url(entry.url)
        if not src:
            continue
        _, item = make_asset_library_item(src, entry.name or os.path.basename(src), subdir=cat.get("dir") or "")
        if item.get("kind") == "image":
            classification = await classify_asset_image_best_effort(output_file_from_url(item.get("url") or "") or src)
            if classification:
                item["classification"] = classification
        cat.setdefault("items", []).append(item)
        added.append(item)
    save_asset_library(lib)
    return {"library": lib, "items": added}

async def caption_image_with_provider(abs_path, prompt, provider_id, model, ms_model=""):
    llm_provider = get_api_provider(provider_id) if provider_id not in ("modelscope",) else {}
    if is_codex_provider(llm_provider):
        resolved_model = selected_model(model, (llm_provider.get("chat_models") or CODEX_DEFAULT_CHAT_MODELS)[0])
        payload = CanvasLLMRequest(
            message=(prompt or "描述图片").strip() or "描述图片",
            provider=provider_id or "codex",
            model=resolved_model,
            images=[abs_path],
        )
        text, _raw = await codex_chat_text(payload, [])
        return text, resolved_model
    if is_gemini_cli_provider(llm_provider):
        resolved_model = selected_model(model, (llm_provider.get("chat_models") or GEMINI_CLI_DEFAULT_CHAT_MODELS)[0])
        payload = CanvasLLMRequest(
            message=(prompt or "描述图片").strip() or "描述图片",
            provider=provider_id or "gemini-cli",
            model=resolved_model,
            images=[abs_path],
        )
        text, _raw = await gemini_cli_chat_text(payload, [])
        return text, resolved_model
    chat_base, chat_hdrs, resolved_model = resolve_chat_provider(provider_id, model, ms_model)
    is_apimart = is_apimart_provider(llm_provider)
    prompt_text = (prompt or "描述图片").strip() or "描述图片"
    data_url = image_path_to_data_url(abs_path, max_size=1024)
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }]
    raw = None
    try:
        async with httpx.AsyncClient(timeout=AI_REQUEST_TIMEOUT) as client:
            req_body = {"model": resolved_model, "messages": messages}
            if is_apimart:
                req_body["stream"] = False
            response = await client.post(
                f"{chat_base}/chat/completions",
                headers=chat_hdrs,
                json=req_body,
            )
            response.raise_for_status()
            raw = response.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text or ""
        friendly = friendly_chat_error_detail(body, resolved_model, llm_provider)
        raise HTTPException(status_code=exc.response.status_code, detail=friendly or f"上游接口错误：{body}") from exc
    except httpx.HTTPError as exc:
        log_net_error(f"对话 网络/TLS错误 provider={llm_provider} model={resolved_model}", exc)
        raise HTTPException(status_code=502, detail=f"请求上游接口失败：{exc}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"解析上游响应失败：{exc}") from exc
    text = text_from_chat_response(raw).strip() if isinstance(raw, dict) else ""
    return text or "接口返回了空回复。", resolved_model

async def rename_asset_library_item(item_id: str, payload: AssetLibraryRenameRequest):
    lib = load_asset_library()
    for library in lib.get("libraries", []):
        for cat in library.get("categories", []):
            for item in cat.get("items", []):
                if item.get("id") == item_id:
                    item["name"] = sanitize_asset_name(payload.name, item.get("name") or "asset")
                    save_asset_library(lib)
                    return {"library": lib, "item": item}
    raise HTTPException(status_code=404, detail="资产不存在")

def find_asset_item_in_library(lib, item_id, library_id=""):
    for library in lib.get("libraries", []):
        if library_id and library.get("id") != library_id:
            continue
        for cat in library.get("categories", []):
            for item in cat.get("items", []):
                if item.get("id") == item_id:
                    return item
    return None

async def classify_asset_library_items(payload: AssetLibraryClassifyRequest):
    lib = load_asset_library()
    results = []
    changed = False
    for item_id in (payload.ids or [])[:80]:
        item = find_asset_item_in_library(lib, item_id, payload.library_id)
        result = {"id": item_id, "ok": False, "classification": None, "error": ""}
        if not item:
            result["error"] = "资产不存在"
            results.append(result)
            continue
        if asset_library_media_kind(item.get("url") or "") != "image" and item.get("kind") != "image":
            result["error"] = "仅支持图片素材智能分类"
            results.append(result)
            continue
        path = output_file_from_url(item.get("url") or "")
        if not path or not os.path.isfile(path):
            result["error"] = "文件不存在"
            results.append(result)
            continue
        try:
            classification = await classify_image_with_provider(path, payload.provider, payload.model, payload.ms_model, payload.prompt)
            item["classification"] = classification
            changed = True
            result.update({"ok": True, "classification": classification})
        except Exception as exc:
            result["error"] = str(getattr(exc, "detail", "") or exc)
        results.append(result)
    if changed:
        save_asset_library(lib)
    return {"library": lib, "count": sum(1 for item in results if item.get("ok")), "items": results}

async def register_asset_library_avatar(item_id: str, payload: AssetAvatarRegisterRequest):
    lib = load_asset_library()
    target_item = find_asset_item_in_library(lib, item_id, payload.library_id)
    if not target_item:
        raise HTTPException(status_code=404, detail="资产不存在")
    provider = get_api_provider(payload.provider_id)
    platform = avatar_platform_for_provider(provider)
    if platform not in AVATAR_SUPPORTED_PLATFORMS:
        name = (provider or {}).get("name") or (provider or {}).get("id") or "该平台"
        raise HTTPException(status_code=400, detail=f"「{name}」暂不支持数字人/真人认证（目前仅 APIMart 可用，火山等平台待接入官方资产 API）。")
    kind = str(target_item.get("kind") or "image").lower()
    if kind not in ("image", "video", "audio"):
        kind = "image"
    if platform == "apimart":
        project_name = str(payload.project_name or "default").strip() or "default"
        async with httpx.AsyncClient(timeout=VIDEO_POLL_TIMEOUT) as client:
            public_url = await upload_media_for_apimart(client, provider, target_item.get("url") or "", kind)
        if not valid_apimart_video_image_input(public_url):
            reason = public_url[4:] if isinstance(public_url, str) and public_url.startswith("ERR:") else "无法获取公网可访问地址"
            raise HTTPException(status_code=400, detail=f"素材无法提交到 APIMart：{reason}\n请配置 PUBLIC_BASE_URL，或确认本地文件存在。")
        task_id = await submit_apimart_avatar_asset(
            provider, public_url, target_item.get("name") or "asset", kind,
            project_name=project_name, group_name=payload.group_name,
        )
    elif platform == "volcengine":
        # 火山以 API 设置里配置的 ProjectName 为准（必须与视频生成 key 的项目一致）
        project_name = str(provider.get("volcengine_project_name") or VOLCENGINE_DEFAULT_PROJECT_NAME).strip() or VOLCENGINE_DEFAULT_PROJECT_NAME
        public_url = volcengine_public_asset_url(target_item.get("url") or "")
        if public_url.startswith("ERR:"):
            raise HTTPException(status_code=400, detail=public_url[4:])
        task_id = await submit_volcengine_avatar_asset(
            public_url, target_item.get("name") or "asset", kind,
            project_name=project_name, group_name=payload.group_name or "",
        )
    else:
        raise HTTPException(status_code=400, detail="该平台的认证后端尚未接入。")
    regs = target_item.get("registrations")
    if not isinstance(regs, dict):
        regs = {}
    regs[platform] = {
        "provider_id": provider["id"],
        "project_name": project_name,
        "task_id": task_id,
        "status": "Processing",
        "detail": "已提交，审核中",
        "asset_uri": "",
        "asset_id": "",
        "registered_at": now_ms(),
    }
    target_item["registrations"] = regs
    save_asset_library(lib)
    return {"library": lib, "item": target_item}

async def check_asset_library_avatar(item_id: str, payload: AssetAvatarRegisterRequest):
    lib = load_asset_library()
    target_item = find_asset_item_in_library(lib, item_id, payload.library_id)
    if not target_item:
        raise HTTPException(status_code=404, detail="资产不存在")
    regs = target_item.get("registrations") if isinstance(target_item.get("registrations"), dict) else {}
    provider = get_api_provider(payload.provider_id or "")
    platform = avatar_platform_for_provider(provider)
    if platform not in AVATAR_SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=400, detail="该平台暂不支持数字人/真人认证审核。")
    reg = regs.get(platform) if isinstance(regs.get(platform), dict) else {}
    task_id = str(reg.get("task_id") or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="该素材还没有提交到这个平台的认证审核。")
    if platform == "apimart":
        result = await check_apimart_avatar_task(provider, task_id)
    elif platform == "volcengine":
        result = await check_volcengine_avatar_task(
            task_id, str(reg.get("project_name") or VOLCENGINE_DEFAULT_PROJECT_NAME).strip() or VOLCENGINE_DEFAULT_PROJECT_NAME,
        )
    else:
        raise HTTPException(status_code=400, detail="该平台的认证后端尚未接入。")
    reg["status"] = result["status"]
    reg["detail"] = result.get("detail") or ""
    if result["status"] == "Active" and result.get("asset_uri"):
        reg["asset_uri"] = result["asset_uri"]
        reg["asset_id"] = result["asset_uri"].replace("asset://", "")
    regs[platform] = reg
    target_item["registrations"] = regs
    save_asset_library(lib)
    return {"library": lib, "item": target_item}

async def delete_asset_library_item(item_id: str):
    lib = load_asset_library()
    removed = None
    for library in lib.get("libraries", []):
        for cat in library.get("categories", []):
            keep = []
            for item in cat.get("items", []):
                if item.get("id") == item_id:
                    removed = item
                else:
                    keep.append(item)
            cat["items"] = keep
    if not removed:
        raise HTTPException(status_code=404, detail="资产不存在")
    remove_asset_library_file(removed)  # 同时删除本地文件，避免磁盘上堆积
    save_asset_library(lib)
    return {"library": lib}

async def batch_delete_asset_library_items(payload: AssetLibraryBatchDeleteRequest):
    ids = {str(item) for item in (payload.ids or []) if str(item)}
    if not ids:
        raise HTTPException(status_code=400, detail="没有选择资产")
    lib = load_asset_library()
    removed = 0
    removed_items = []
    for library in lib.get("libraries", []):
        if payload.library_id and library.get("id") != payload.library_id:
            continue
        for cat in library.get("categories", []):
            keep = []
            for item in cat.get("items", []):
                if item.get("id") in ids:
                    removed += 1
                    removed_items.append(item)
                else:
                    keep.append(item)
            cat["items"] = keep
    for item in removed_items:  # 批量删除同时清理本地文件
        remove_asset_library_file(item)
    save_asset_library(lib)
    return {"library": lib, "removed": removed}

async def batch_move_asset_library_items(payload: AssetLibraryBatchMoveRequest):
    ids = {str(item) for item in (payload.ids or []) if str(item)}
    if not ids:
        raise HTTPException(status_code=400, detail="没有选择资产")
    lib = load_asset_library()
    target_cat = find_asset_category_in_library(lib, payload.target_category_id, payload.target_library_id)
    if not target_cat:
        raise HTTPException(status_code=404, detail="目标分组不存在")
    target_type = target_cat.get("type") or "image"
    moved = []
    for library in lib.get("libraries", []):
        if payload.library_id and library.get("id") != payload.library_id:
            continue
        for cat in library.get("categories", []):
            if (cat.get("type") or "image") != target_type:
                continue
            keep = []
            for item in cat.get("items", []):
                if item.get("id") in ids:
                    moved.append(item)
                else:
                    keep.append(item)
            cat["items"] = keep
    existing_ids = {item.get("id") for item in target_cat.get("items", [])}
    for item in moved:
        if item.get("id") not in existing_ids:
            target_cat.setdefault("items", []).append(item)
            existing_ids.add(item.get("id"))
    save_asset_library(lib)
    return {"library": lib, "moved": len(moved)}

async def batch_crop_asset_library_items(payload: AssetLibraryBatchCropRequest):
    ids = {str(item) for item in (payload.ids or []) if str(item)}
    if not ids:
        raise HTTPException(status_code=400, detail="没有选择资产")
    lib = load_asset_library()
    target_cat = None
    if payload.target_category_id:
        target_cat = find_asset_category_in_library(lib, payload.target_category_id, payload.target_library_id)
        if not target_cat:
            raise HTTPException(status_code=404, detail="目标分组不存在")
        if target_cat.get("type") != "image":
            raise HTTPException(status_code=400, detail="目标分组不支持媒体")
    added = []
    for library in lib.get("libraries", []):
        if payload.library_id and library.get("id") != payload.library_id:
            continue
        for cat in library.get("categories", []):
            if cat.get("type") != "image":
                continue
            source_items = [item for item in (cat.get("items", []) or []) if item.get("id") in ids]
            for item in source_items:
                src = output_file_from_url(item.get("url") or "")
                if not src or not os.path.isfile(src):
                    continue
                try:
                    with Image.open(src) as img:
                        img = img.convert("RGBA")
                        w, h = img.size
                        side = min(w, h)
                        if side <= 0:
                            continue
                        left = max(0, (w - side) // 2)
                        top = max(0, (h - side) // 2)
                        cropped = img.crop((left, top, left + side, top + side))
                        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                        tmp_path = tmp.name
                        tmp.close()
                        try:
                            cropped.save(tmp_path, "PNG")
                            base_name = os.path.splitext(item.get("name") or "asset")[0] + "_crop.png"
                            dest_cat = target_cat or cat
                            _, next_item = make_asset_library_item(tmp_path, base_name, subdir=dest_cat.get("dir") or "")
                            dest_cat.setdefault("items", []).append(next_item)
                            added.append(next_item)
                        finally:
                            try:
                                os.remove(tmp_path)
                            except Exception:
                                pass
                except Exception:
                    continue
    save_asset_library(lib)
    return {"library": lib, "added": len(added), "items": added}

# --- GPT 对话 ---
