"""Cloud image generation and local ComfyUI task orchestration."""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
import urllib.request
from typing import Any

import httpx
import requests
from fastapi import HTTPException

from api_models import CloudGenRequest, CloudPollRequest, GenerateRequest, MsGenerateRequest


GENERATION_SERVICE_EXPORTS = (
    "poll_angle_cloud",
    "generate_angle_cloud",
    "generate_cloud",
    "ms_generate",
    "generate",
)


def configure_generation_service(**dependencies: Any) -> None:
    required = {
        "BACKEND_LOCAL_LOAD",
        "CLIENT_ID",
        "COMFYUI_HISTORY_TIMEOUT",
        "COMFYUI_INSTANCES",
        "GLOBAL_LOOP",
        "LOAD_LOCK",
        "NEXT_TASK_ID",
        "QUEUE",
        "QUEUE_LOCK",
        "WORKFLOW_DIR",
        "WORKFLOW_PATH",
        "collect_comfy_file_items",
        "collect_required_comfy_media",
        "comfy_class_is_debug_text",
        "comfy_class_is_preview",
        "comfy_output_kind",
        "comfy_text_values_from_output",
        "convert_output_to_jpg",
        "download_comfy_output",
        "get_comfy_history",
        "manager",
        "modelscope_api_key",
        "modelscope_image_api_root",
        "modelscope_image_url",
        "modelscope_size",
        "output_path_for",
        "output_url_for",
        "reserve_best_backend",
        "save_comfy_text_output",
        "save_to_history",
        "selected_model",
    }
    missing = sorted(required - dependencies.keys())
    if missing:
        raise RuntimeError(
            f"Generation service missing dependencies: {', '.join(missing)}"
        )
    globals().update(dependencies)


def export_generation_service(target: dict[str, Any]) -> None:
    for name in GENERATION_SERVICE_EXPORTS:
        target[name] = globals()[name]

async def poll_angle_cloud(req: CloudPollRequest):
    api_root = modelscope_image_api_root()
    clean_token = modelscope_api_key(req.api_key)
    if not clean_token:
        raise HTTPException(status_code=400, detail="未提供 ModelScope API Key")

    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Content-Type": "application/json",
        "X-ModelScope-Async-Mode": "true"
    }
    task_id = req.task_id
    print(f"Resuming polling for Angle Task: {task_id}")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for i in range(300):
                await asyncio.sleep(2)
                result = await client.get(
                    f"{api_root}/tasks/{task_id}",
                    headers={**headers, "X-ModelScope-Task-Type": "image_generation"},
                )
                result.raise_for_status()
                data = result.json()
                status = str(data.get("task_status") or "").upper()

                if status == "SUCCEED":
                    img_url = data["output_images"][0]
                    local_path = ""
                    try:
                        async with httpx.AsyncClient() as dl_client:
                            img_res = await dl_client.get(img_url)
                            if img_res.status_code == 200:
                                filename = f"cloud_angle_{int(time.time())}.png"
                                file_path = output_path_for(filename, "output")
                                with open(file_path, "wb") as f:
                                    f.write(img_res.content)
                                local_path = output_url_for(filename, "output")
                            else:
                                local_path = img_url
                    except Exception:
                        local_path = img_url

                    record = {"timestamp": time.time(), "prompt": f"Resumed {task_id}", "images": [local_path], "type": "angle"}
                    save_to_history(record)
                    if req.client_id:
                        await manager.send_personal_message({"type": "cloud_status", "status": "SUCCEED", "task_id": task_id}, req.client_id)
                    return {"url": local_path}

                elif status in {"FAILED", "FAIL", "ERROR", "CANCELED", "CANCELLED", "TIMEOUT", "REVOKED"}:
                    if req.client_id:
                        await manager.send_personal_message({"type": "cloud_status", "status": "FAILED", "task_id": task_id}, req.client_id)
                    raise HTTPException(status_code=502, detail=f"ModelScope task failed: {data}")

                if i % 5 == 0 and req.client_id:
                    await manager.send_personal_message({
                        "type": "cloud_status", "status": f"{status} ({i}/300)",
                        "task_id": task_id, "progress": i, "total": 300
                    }, req.client_id)

            if req.client_id:
                await manager.send_personal_message({"type": "cloud_status", "status": "TIMEOUT", "task_id": task_id}, req.client_id)
            return {"status": "timeout", "task_id": task_id, "message": "Task still pending"}

    except HTTPException:
        raise
    except Exception as e:
        print(f"Angle polling error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

async def generate_angle_cloud(req: CloudGenRequest):
    api_root = modelscope_image_api_root()
    clean_token = modelscope_api_key(req.api_key)
    if not clean_token:
        raise HTTPException(status_code=400, detail="未提供 ModelScope API Key")

    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Content-Type": "application/json",
        "X-ModelScope-Async-Mode": "true"
    }
    model = selected_model(req.model, "Qwen/Qwen-Image-Edit-2511")
    payload = {
        "model": model,
        "prompt": req.prompt.strip(),
        "image_url": [modelscope_image_url(url, max_size=1536) for url in req.image_urls]
    }
    if req.resolution:
        payload["size"] = modelscope_size(req.resolution)
    if req.loras is not None:
        payload["loras"] = req.loras

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            submit_res = await client.post(f"{api_root}/images/generations", headers=headers, json=payload)
            if submit_res.status_code != 200:
                try:
                    detail = submit_res.json()
                except:
                    detail = submit_res.text
                raise HTTPException(status_code=submit_res.status_code, detail=detail)

            task_id = submit_res.json().get("task_id")
            print(f"Angle Task submitted, ID: {task_id}")

            for i in range(300):
                await asyncio.sleep(2)
                result = await client.get(
                    f"{api_root}/tasks/{task_id}",
                    headers={**headers, "X-ModelScope-Task-Type": "image_generation"},
                )
                result.raise_for_status()
                data = result.json()
                status = str(data.get("task_status") or "").upper()

                if status == "SUCCEED":
                    img_url = data["output_images"][0]
                    local_path = ""
                    try:
                        async with httpx.AsyncClient() as dl_client:
                            img_res = await dl_client.get(img_url)
                            if img_res.status_code == 200:
                                filename = f"cloud_angle_{int(time.time())}.png"
                                file_path = output_path_for(filename, "output")
                                with open(file_path, "wb") as f:
                                    f.write(img_res.content)
                                local_path = output_url_for(filename, "output")
                            else:
                                local_path = img_url
                    except Exception:
                        local_path = img_url

                    record = {"timestamp": time.time(), "prompt": req.prompt, "images": [local_path], "type": "angle"}
                    save_to_history(record)
                    if req.client_id:
                        await manager.send_personal_message({"type": "cloud_status", "status": "SUCCEED", "task_id": task_id}, req.client_id)
                    if GLOBAL_LOOP:
                        asyncio.run_coroutine_threadsafe(manager.broadcast_new_image(record), GLOBAL_LOOP)
                    return {"url": local_path, "task_id": task_id}

                elif status in {"FAILED", "FAIL", "ERROR", "CANCELED", "CANCELLED", "TIMEOUT", "REVOKED"}:
                    if req.client_id:
                        await manager.send_personal_message({"type": "cloud_status", "status": "FAILED", "task_id": task_id}, req.client_id)
                    raise HTTPException(status_code=502, detail=f"ModelScope task failed: {data}")

                if i % 5 == 0 and req.client_id:
                    await manager.send_personal_message({
                        "type": "cloud_status", "status": f"{status} ({i}/300)",
                        "task_id": task_id, "progress": i, "total": 300
                    }, req.client_id)

            if req.client_id:
                await manager.send_personal_message({"type": "cloud_status", "status": "TIMEOUT", "task_id": task_id}, req.client_id)
            return {"status": "timeout", "task_id": task_id, "message": "Task still pending"}

    except HTTPException:
        raise
    except Exception as e:
        print(f"Angle generation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# --- ModelScope Z-Image 云端生图 ---

async def generate_cloud(req: CloudGenRequest):
    api_root = modelscope_image_api_root()
    clean_token = modelscope_api_key(req.api_key)
    if not clean_token:
        raise HTTPException(status_code=400, detail="未提供 ModelScope API Key")

    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "Tongyi-MAI/Z-Image-Turbo",
        "prompt": req.prompt.strip(),
        "size": modelscope_size(req.resolution),
        "n": 1
    }
    if req.loras is not None:
        payload["loras"] = req.loras

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            submit_res = await client.post(
                f"{api_root}/images/generations",
                headers={**headers, "X-ModelScope-Async-Mode": "true"},
                json=payload
            )
            if submit_res.status_code != 200:
                try:
                    detail = submit_res.json()
                except:
                    detail = submit_res.text
                raise HTTPException(status_code=submit_res.status_code, detail=detail)

            task_id = submit_res.json().get("task_id")
            print(f"Z-Image Task submitted, ID: {task_id}")

            for i in range(200):
                await asyncio.sleep(3)
                result = await client.get(
                    f"{api_root}/tasks/{task_id}",
                    headers={**headers, "X-ModelScope-Task-Type": "image_generation"},
                )
                result.raise_for_status()
                data = result.json()
                status = str(data.get("task_status") or "").upper()

                if i % 5 == 0:
                    print(f"Task {task_id} status check {i}: {status}")

                if status == "SUCCEED":
                    img_url = data["output_images"][0]
                    local_path = ""
                    try:
                        async with httpx.AsyncClient() as dl_client:
                            img_res = await dl_client.get(img_url)
                            if img_res.status_code == 200:
                                filename = f"cloud_{int(time.time())}.png"
                                file_path = output_path_for(filename, "output")
                                with open(file_path, "wb") as f:
                                    f.write(img_res.content)
                                local_path = output_url_for(filename, "output")
                            else:
                                local_path = img_url
                    except Exception as dl_e:
                        print(f"Download error: {dl_e}")
                        local_path = img_url

                    record = {"timestamp": time.time(), "prompt": req.prompt, "images": [local_path], "type": "cloud"}
                    save_to_history(record)
                    try:
                        await manager.broadcast_new_image(record)
                    except Exception:
                        pass
                    return {"url": local_path}

                elif status in {"FAILED", "FAIL", "ERROR", "CANCELED", "CANCELLED", "TIMEOUT", "REVOKED"}:
                    raise HTTPException(status_code=502, detail=f"ModelScope task failed: {data}")

            raise Exception("Cloud generation timeout")

    except HTTPException:
        raise
    except Exception as e:
        print(f"Cloud generation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# --- ModelScope 通用图片生成（支持图生图） ---

async def ms_generate(req: MsGenerateRequest):
    api_root = modelscope_image_api_root()
    clean_token = modelscope_api_key(req.api_key)
    if not clean_token:
        raise HTTPException(status_code=400, detail="未配置 ModelScope API Key，请在 API 设置中填写，或重新保存 ModelScope Token。")

    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Content-Type": "application/json",
        "X-ModelScope-Async-Mode": "true"
    }
    payload = {
        "model": req.model,
        "prompt": req.prompt.strip(),
    }
    if req.width and req.height:
        payload["width"] = req.width
        payload["height"] = req.height
        payload["size"] = modelscope_size(req.size or f"{req.width}x{req.height}")
    elif req.size:
        payload["size"] = modelscope_size(req.size)
    if req.image_urls:
        payload["image_url"] = [modelscope_image_url(url, max_size=1536) for url in req.image_urls]
    if req.loras is not None:
        payload["loras"] = req.loras

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            submit_res = await client.post(
                f"{api_root}/images/generations",
                headers=headers,
                json=payload
            )
            if submit_res.status_code != 200:
                try:
                    detail = submit_res.json()
                except:
                    detail = submit_res.text
                raise HTTPException(status_code=submit_res.status_code, detail=detail)

            task_id = submit_res.json().get("task_id")
            print(f"MS Generate Task submitted ({req.model}), ID: {task_id}")

            TERMINAL_FAILED_STATUSES = {"FAILED", "FAIL", "ERROR", "CANCELED", "CANCELLED", "TIMEOUT", "REVOKED"}

            for i in range(300):
                await asyncio.sleep(2)
                try:
                    result = await client.get(
                        f"{api_root}/tasks/{task_id}",
                        headers={**headers, "X-ModelScope-Task-Type": "image_generation"},
                    )
                    data = result.json()
                    status = data.get("task_status")
                    print(f"MS Task {task_id} poll {i}: status={status}")

                    if status == "SUCCEED":
                        img_url = data["output_images"][0]
                        local_path = ""
                        try:
                            async with httpx.AsyncClient() as dl_client:
                                img_res = await dl_client.get(img_url)
                                if img_res.status_code == 200:
                                    filename = f"ms_{req.model.replace('/', '_').replace(':', '_')}_{int(time.time())}.png"
                                    file_path = output_path_for(filename, "output")
                                    with open(file_path, "wb") as f:
                                        f.write(img_res.content)
                                    local_path = output_url_for(filename, "output")
                                else:
                                    local_path = img_url
                        except Exception:
                            local_path = img_url

                        record = {
                            "timestamp": time.time(),
                            "prompt": req.prompt,
                            "images": [local_path],
                            "type": "klein",
                            "model": req.model,
                        }
                        save_to_history(record)
                        if GLOBAL_LOOP:
                            asyncio.run_coroutine_threadsafe(manager.broadcast_new_image(record), GLOBAL_LOOP)
                        return {"url": local_path, "task_id": task_id}

                    elif status in TERMINAL_FAILED_STATUSES:
                        error_info = data.get("error_info") or data.get("message") or data.get("detail") or str(data)
                        raise HTTPException(status_code=502, detail=f"MS task {status}: {error_info}")

                except HTTPException:
                    raise
                except Exception as loop_e:
                    print(f"MS polling error: {loop_e}")
                    continue

            raise HTTPException(status_code=504, detail="MS 生图超时")

    except HTTPException:
        raise
    except Exception as e:
        print(f"MS generate error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# --- 本地 ComfyUI 生图 ---

def generate(req: GenerateRequest):
    global NEXT_TASK_ID
    current_task = None
    target_backend = None
    with QUEUE_LOCK:
        task_id = NEXT_TASK_ID
        NEXT_TASK_ID += 1
        current_task = {"task_id": task_id, "client_id": req.client_id}
        QUEUE.append(current_task)

    try:
        required_images = collect_required_comfy_media(req.params)

        target_backend = reserve_best_backend(required_images)

        for image_name in required_images:
            need_sync = False
            try:
                check_url = f"http://{target_backend}/view?filename={urllib.parse.quote(image_name)}&type=input"
                resp = requests.get(check_url, stream=True, timeout=0.5)
                resp.close()
                if resp.status_code != 200:
                    need_sync = True
            except:
                need_sync = True

            if need_sync:
                image_content = None
                image_type = "image/png"
                for addr in COMFYUI_INSTANCES:
                    if addr == target_backend: continue
                    try:
                        src_url = f"http://{addr}/view?filename={urllib.parse.quote(image_name)}&type=input"
                        r = requests.get(src_url, timeout=5)
                        if r.status_code == 200:
                            image_content = r.content
                            image_type = r.headers.get("Content-Type", "image/png")
                            break
                    except: continue

                if image_content:
                    try:
                        files = {'image': (image_name, image_content, image_type)}
                        requests.post(f"http://{target_backend}/upload/image", files=files, timeout=10)
                    except Exception as e:
                        print(f"Sync upload failed: {e}")

        workflow_path = os.path.join(WORKFLOW_DIR, req.workflow_json)
        if not os.path.exists(workflow_path) and req.workflow_json == "Z-Image.json":
            workflow_path = WORKFLOW_PATH
        if not os.path.exists(workflow_path):
            raise Exception(f"Workflow file not found: {req.workflow_json}")

        with open(workflow_path, 'r', encoding='utf-8') as f:
            workflow = json.load(f)

        seed = random.randint(1, 4294967295)

        if "23" in workflow and req.prompt:
            workflow["23"]["inputs"]["text"] = req.prompt
        if "144" in workflow:
            workflow["144"]["inputs"]["width"] = req.width
            workflow["144"]["inputs"]["height"] = req.height
        if "22" in workflow:
            workflow["22"]["inputs"]["seed"] = seed
        if "158" in workflow:
            workflow["158"]["inputs"]["noise_seed"] = seed
        for node_id in ["146", "181"]:
            if node_id in workflow and "inputs" in workflow[node_id] and "seed" in workflow[node_id]["inputs"]:
                workflow[node_id]["inputs"]["seed"] = seed
        if "184" in workflow and "inputs" in workflow["184"] and "seed" in workflow["184"]["inputs"]:
            workflow["184"]["inputs"]["seed"] = seed
        if "172" in workflow and "inputs" in workflow["172"] and "seed" in workflow["172"]["inputs"]:
            workflow["172"]["inputs"]["seed"] = seed
        if "14" in workflow and "inputs" in workflow["14"] and "seed" in workflow["14"]["inputs"]:
            workflow["14"]["inputs"]["seed"] = seed

        for node_id, node_inputs in req.params.items():
            if node_id in workflow:
                if "inputs" not in workflow[node_id]:
                    workflow[node_id]["inputs"] = {}
                for input_name, value in node_inputs.items():
                    workflow[node_id]["inputs"][input_name] = value

        p = {"prompt": workflow, "client_id": CLIENT_ID}
        data = json.dumps(p).encode('utf-8')
        try:
            post_req = urllib.request.Request(f"http://{target_backend}/prompt", data=data)
            prompt_id = json.loads(urllib.request.urlopen(post_req, timeout=10).read())['prompt_id']
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            raise Exception(f"HTTP Error {e.code}: {error_body}")

        history_data = None
        for i in range(COMFYUI_HISTORY_TIMEOUT):
            try:
                res = get_comfy_history(target_backend, prompt_id)
                if prompt_id in res:
                    history_data = res[prompt_id]
                    break
            except Exception:
                pass
            time.sleep(1)

        if not history_data:
            raise Exception("ComfyUI 渲染超时")

        local_images = []
        local_videos = []
        local_audios = []
        local_texts = []
        local_files = []
        local_items = []
        local_urls = []
        current_timestamp = time.time()
        if 'outputs' in history_data:
            # 先把所有节点的输出收集为候选（带上 class_type），再决定下载哪些，
            # 避免把冗余的预览/对比图、调试文本一起下载进结果（后端层过滤，历史记录也更干净）。
            workflow_nodes = workflow if isinstance(workflow, dict) else {}
            def _class_type_of(nid):
                node_def = workflow_nodes.get(str(nid))
                return str(node_def.get("class_type") or "") if isinstance(node_def, dict) else ""
            file_candidates = []   # (node_id, class_type, output_key, item, kind)
            text_candidates = []   # (node_id, class_type, text, name)
            for node_id in history_data['outputs']:
                node_output = history_data['outputs'][node_id]
                class_type = _class_type_of(node_id)
                for output_key, item in collect_comfy_file_items(node_output):
                    file_candidates.append((node_id, class_type, output_key, item, comfy_output_kind(item)))
                for text, name in comfy_text_values_from_output(node_output):
                    text_candidates.append((node_id, class_type, text, name))

            # 只要存在“非预览节点”产出的图片，就把 PreviewImage/对比节点的图片视为冗余丢弃；
            # 若整个工作流只有预览图（没有 SaveImage 等），则保留预览图作为唯一结果，避免零输出。
            has_primary_image = any(
                kind == "image" and not comfy_class_is_preview(ct)
                for (_nid, ct, _ok, _it, kind) in file_candidates
            )
            prefix = f"{req.type}_{int(current_timestamp)}_"
            for node_id, class_type, output_key, item, kind in file_candidates:
                if kind == "image" and has_primary_image and comfy_class_is_preview(class_type):
                    continue  # 跳过冗余的预览/对比图
                local_path = download_comfy_output(target_backend, item, prefix=prefix)
                if kind == "image" and req.convert_to_jpg:
                    local_path = convert_output_to_jpg(local_path)
                name = os.path.basename(str(item.get("filename") or "")) or os.path.basename(str(local_path).split("?", 1)[0])
                entry = {
                    "url": local_path,
                    "kind": kind,
                    "name": name,
                    "node_id": str(node_id),
                    "output_key": str(output_key),
                    "class_type": class_type,
                }
                if kind == "image":
                    local_images.append(local_path)
                elif kind == "video":
                    local_videos.append(local_path)
                elif kind == "audio":
                    local_audios.append(local_path)
                elif kind == "text":
                    local_texts.append(local_path)
                else:
                    local_files.append(local_path)
                local_items.append(entry)
                local_urls.append(local_path)

            # 默认抑制 show/utility 类节点的调试文本，避免 .txt 噪声混入结果。
            for node_id, class_type, text, name in text_candidates:
                if comfy_class_is_debug_text(class_type):
                    continue
                local_path = save_comfy_text_output(text, prefix=prefix, name=name)
                entry = {
                    "url": local_path,
                    "kind": "text",
                    "name": os.path.basename(str(local_path).split("?", 1)[0]),
                    "node_id": str(node_id),
                    "output_key": "text",
                    "class_type": class_type,
                }
                local_texts.append(local_path)
                local_items.append(entry)
                local_urls.append(local_path)

        result = {
            "prompt": req.prompt if req.prompt else "Detail Enhance",
            "images": local_images,
            "videos": local_videos,
            "audios": local_audios,
            "texts": local_texts,
            "files": local_files,
            "items": local_items,
            "outputs": local_urls,
            "seed": seed,
            "timestamp": current_timestamp,
            "type": req.type,
            "workflow_json": req.workflow_json,
            "task_id": task_id,
            "prompt_id": prompt_id,
            "backend": target_backend,
            "params": req.params
        }
        save_to_history(result)
        if GLOBAL_LOOP:
            asyncio.run_coroutine_threadsafe(manager.broadcast_new_image(result), GLOBAL_LOOP)
        return result

    except Exception as e:
        return {"images": [], "error": str(e)}
    finally:
        if target_backend:
            with LOAD_LOCK:
                if BACKEND_LOCAL_LOAD.get(target_backend, 0) > 0:
                    BACKEND_LOCAL_LOAD[target_backend] -= 1
        if current_task:
            with QUEUE_LOCK:
                if current_task in QUEUE:
                    QUEUE.remove(current_task)
