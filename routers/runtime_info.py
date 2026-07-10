"""Runtime configuration and model-list routes."""

from __future__ import annotations

import inspect
from typing import Any, Callable

from fastapi import APIRouter


router = APIRouter(tags=["runtime-info"])
_handlers: dict[str, Callable[..., Any]] = {}


def configure_runtime_info_routes(**handlers: Callable[..., Any]) -> None:
    global _handlers
    _handlers = handlers


async def _call(name: str) -> Any:
    handler = _handlers.get(name)
    if handler is None:
        raise RuntimeError(f"Runtime info route handler is not configured: {name}")
    result = handler()
    return await result if inspect.isawaitable(result) else result


@router.get("/api/config")
async def ai_config():
    return await _call("config")


@router.get("/api/models")
async def ai_models():
    return await _call("models")


@router.get("/api/config/token")
async def get_global_token():
    return await _call("token")
