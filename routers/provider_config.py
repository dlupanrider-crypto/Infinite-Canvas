"""Provider registry configuration routes."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app_services.env_config import (
    provider_key_env,
    runninghub_wallet_key_env,
    update_env_values,
    volcengine_access_key_env,
    volcengine_secret_key_env,
)
from app_services.provider_normalization import normalize_provider
from repositories.provider_registry import (
    public_api_providers,
    public_provider,
    save_api_providers,
)


router = APIRouter(prefix="/api/providers", tags=["providers"])
_preserve_runninghub_overrides: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None
_reload_env: Optional[Callable[[], None]] = None


def configure_provider_config_routes(
    *,
    preserve_runninghub_overrides_fn: Callable[[dict[str, Any]], dict[str, Any]],
    reload_env_fn: Callable[[], None],
) -> None:
    global _preserve_runninghub_overrides, _reload_env
    _preserve_runninghub_overrides = preserve_runninghub_overrides_fn
    _reload_env = reload_env_fn


def _require_configured() -> None:
    if _preserve_runninghub_overrides is None or _reload_env is None:
        raise RuntimeError("Provider config routes are not configured")


class ApiProviderPayload(BaseModel):
    id: str = ""
    name: str = ""
    base_url: str = ""
    protocol: str = "openai"
    image_request_mode: str = "openai"
    image_generation_endpoint: str = ""
    image_edit_endpoint: str = ""
    enabled: bool = True
    primary: bool = False
    image_models: List[str] = Field(default_factory=list)
    chat_models: List[str] = Field(default_factory=list)
    video_models: List[str] = Field(default_factory=list)
    model_protocols: Dict[str, str] = Field(default_factory=dict)
    ms_loras: List[Dict[str, Any]] = Field(default_factory=list)
    ms_defaults_version: int = 0
    rh_apps: List[Dict[str, Any]] = Field(default_factory=list)
    rh_workflows: List[Dict[str, Any]] = Field(default_factory=list)
    volcengine_project_name: str = "default"
    volcengine_region: str = "cn-beijing"
    volcengine_access_key_id: Optional[str] = None
    volcengine_secret_access_key: Optional[str] = None
    api_key: Optional[str] = None
    wallet_api_key: Optional[str] = None
    clear_key: bool = False
    clear_wallet_key: bool = False
    clear_volcengine_access_key_id: bool = False
    clear_volcengine_secret_access_key: bool = False


@router.get("")
async def api_providers():
    return {"providers": public_api_providers()}


@router.put("")
async def save_providers(payload: List[ApiProviderPayload]):
    _require_configured()
    providers: list[dict[str, Any]] = []
    env_updates: dict[str, str] = {}
    primary_flags = [bool(item.primary) for item in payload]
    for item in payload:
        provider = normalize_provider(item.dict(exclude={"api_key"}))
        if provider["id"] == "runninghub":
            provider = _preserve_runninghub_overrides(provider)
        if any(existing["id"] == provider["id"] for existing in providers):
            raise HTTPException(
                status_code=400,
                detail=f"API \u5e73\u53f0 ID \u91cd\u590d\uff1a{provider['id']}",
            )
        providers.append(provider)
        key_env = provider_key_env(provider["id"])
        if item.clear_key:
            env_updates[key_env] = ""
        elif item.api_key is not None and item.api_key.strip():
            env_updates[key_env] = item.api_key.strip()

        if provider["id"] == "runninghub":
            wallet_env = runninghub_wallet_key_env()
            if item.clear_wallet_key:
                env_updates[wallet_env] = ""
            elif item.wallet_api_key is not None and item.wallet_api_key.strip():
                env_updates[wallet_env] = item.wallet_api_key.strip()
            provider["protocol"] = "runninghub"

        if provider["id"] == "volcengine":
            access_env = volcengine_access_key_env()
            secret_env = volcengine_secret_key_env()
            if item.clear_volcengine_access_key_id:
                env_updates[access_env] = ""
            elif item.volcengine_access_key_id is not None and item.volcengine_access_key_id.strip():
                env_updates[access_env] = item.volcengine_access_key_id.strip()
            if item.clear_volcengine_secret_access_key:
                env_updates[secret_env] = ""
            elif item.volcengine_secret_access_key is not None and item.volcengine_secret_access_key.strip():
                env_updates[secret_env] = item.volcengine_secret_access_key.strip()
            provider["protocol"] = "volcengine"

        if provider["id"] == "comfly":
            env_updates.update({
                "COMFLY_BASE_URL": provider["base_url"],
                "IMAGE_MODELS": ",".join(provider["image_models"]),
                "CHAT_MODELS": ",".join(provider["chat_models"]),
                "VIDEO_MODELS": ",".join(provider.get("video_models") or []),
            })
        if provider["id"] == "modelscope":
            env_updates["MODELSCOPE_CHAT_MODELS"] = ",".join(provider["chat_models"])

    if not providers:
        raise HTTPException(
            status_code=400,
            detail="\u81f3\u5c11\u4fdd\u7559\u4e00\u4e2a API \u5e73\u53f0",
        )
    primary_indices = [index for index, enabled in enumerate(primary_flags) if enabled]
    if primary_indices:
        winner = primary_indices[-1]
        for index, provider in enumerate(providers):
            provider["primary"] = index == winner
    save_api_providers(providers)
    if env_updates:
        update_env_values(env_updates)
        _reload_env()
    return {"providers": [public_provider(provider) for provider in providers]}
