"""Image, video, LLM, and cloud generation routes."""

from __future__ import annotations

import inspect
from typing import Any, Callable

from fastapi import APIRouter

from api_models import (
    CanvasLLMRequest,
    CanvasVideoRequest,
    CloudGenRequest,
    CloudPollRequest,
    GenerateRequest,
    ImageTaskQueryRequest,
    MsGenerateRequest,
    OnlineImageRequest,
)


router = APIRouter(tags=["generation"])
_handlers: dict[str, Callable[..., Any]] = {}


def configure_generation_routes(**handlers: Callable[..., Any]) -> None:
    global _handlers
    _handlers = handlers


async def _call(name: str, *args: Any) -> Any:
    handler = _handlers.get(name)
    if handler is None:
        raise RuntimeError(f"Generation route handler is not configured: {name}")
    result = handler(*args)
    return await result if inspect.isawaitable(result) else result


@router.post("/api/online-image")
async def online_image(payload: OnlineImageRequest):
    return await _call("online_image", payload)


@router.post("/api/image-task-query")
async def query_image_task(payload: ImageTaskQueryRequest):
    return await _call("query_image_task", payload)


@router.post("/api/canvas-image-tasks")
async def create_canvas_image_task(payload: OnlineImageRequest):
    return await _call("create_image_task", payload)


@router.get("/api/canvas-image-tasks/{task_id}")
async def get_canvas_image_task(task_id: str):
    return await _call("get_image_task", task_id)


@router.post("/api/canvas-comfy-tasks")
async def create_canvas_comfy_task(payload: GenerateRequest):
    return await _call("create_comfy_task", payload)


@router.get("/api/canvas-comfy-tasks/{task_id}")
async def get_canvas_comfy_task(task_id: str):
    return await _call("get_comfy_task", task_id)


@router.get("/api/image-params")
async def image_params(provider_id: str = "", model: str = ""):
    return await _call("image_params", provider_id, model)


@router.post("/api/canvas-video")
async def canvas_video(payload: CanvasVideoRequest):
    return await _call("canvas_video", payload)


@router.post("/api/canvas-llm")
async def canvas_llm(payload: CanvasLLMRequest):
    return await _call("canvas_llm", payload)


@router.post("/api/angle/poll_status")
async def poll_angle_cloud(request: CloudPollRequest):
    return await _call("poll_angle", request)


@router.post("/api/angle/generate")
async def generate_angle_cloud(request: CloudGenRequest):
    return await _call("generate_angle", request)


@router.post("/generate")
async def generate_cloud(request: CloudGenRequest):
    return await _call("generate_cloud", request)


@router.post("/api/ms/generate")
async def ms_generate(request: MsGenerateRequest):
    return await _call("ms_generate", request)


@router.post("/api/generate")
async def generate(request: GenerateRequest):
    return await _call("generate", request)
