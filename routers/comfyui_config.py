"""ComfyUI backend instance configuration routes."""

from __future__ import annotations

import re
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/comfyui/instances", tags=["comfyui-config"])

_get_instances: Optional[Callable[[], list[str]]] = None
_set_instances: Optional[Callable[[list[str]], None]] = None
_update_env: Optional[Callable[[dict[str, str]], None]] = None


def configure_comfyui_config_routes(
    *,
    get_instances_fn: Callable[[], list[str]],
    set_instances_fn: Callable[[list[str]], None],
    update_env_fn: Callable[[dict[str, str]], None],
) -> None:
    global _get_instances, _set_instances, _update_env
    _get_instances = get_instances_fn
    _set_instances = set_instances_fn
    _update_env = update_env_fn


def _require_configured() -> None:
    if _get_instances is None or _set_instances is None or _update_env is None:
        raise RuntimeError("ComfyUI config routes are not configured")


class ComfyInstancesPayload(BaseModel):
    instances: List[str] = Field(default_factory=list)


def normalize_comfyui_instances(instances: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in instances:
        value = str(item or "").strip()
        if not value:
            continue
        value = re.sub(r"^https?://", "", value).rstrip("/")
        if ":" not in value:
            raise HTTPException(
                status_code=400,
                detail=f"\u5730\u5740\u7f3a\u5c11\u7aef\u53e3\u53f7\uff1a{item}\uff08\u5e94\u4e3a host:port\uff0c\u4f8b\u5982 127.0.0.1:8188\uff09",
            )
        host, _, port = value.rpartition(":")
        if not host or not port.isdigit():
            raise HTTPException(
                status_code=400,
                detail=f"\u5730\u5740\u4e0d\u5408\u6cd5\uff1a{item}\uff08\u5e94\u4e3a host:port\uff0c\u4f8b\u5982 127.0.0.1:8188\uff09",
            )
        if value not in cleaned:
            cleaned.append(value)
    if not cleaned:
        raise HTTPException(
            status_code=400,
            detail="\u81f3\u5c11\u4fdd\u7559\u4e00\u4e2a ComfyUI \u540e\u7aef\u5730\u5740",
        )
    return cleaned


@router.get("")
def get_comfyui_instances():
    _require_configured()
    return {"instances": _get_instances()}


@router.put("")
def save_comfyui_instances(payload: ComfyInstancesPayload):
    _require_configured()
    cleaned = normalize_comfyui_instances(payload.instances)
    try:
        _update_env({"COMFYUI_INSTANCES": ",".join(cleaned)})
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"\u5199\u5165 env \u5931\u8d25\uff1a{exc}",
        ) from exc
    _set_instances(cleaned)
    return {"instances": _get_instances()}
