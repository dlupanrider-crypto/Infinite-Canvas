"""Provider registry persistence and public serialization."""

from __future__ import annotations

import json
import os
from threading import Lock
from typing import Any, Callable, Optional


_providers_path = ""
_data_dir = ""
_lock: Optional[Lock] = None
_default_providers: Optional[Callable[[], list[dict[str, Any]]]] = None
_normalize_provider: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None
_merge_defaults: Optional[Callable[..., list[dict[str, Any]]]] = None
_provider_key_value: Optional[Callable[[str], str]] = None
_provider_key_env: Optional[Callable[[str], str]] = None
_mask_secret: Optional[Callable[[str], str]] = None
_runninghub_overlay: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None
_runninghub_wallet_value: Optional[Callable[[], str]] = None
_runninghub_wallet_env: Optional[Callable[[], str]] = None
_volcengine_access_value: Optional[Callable[[], str]] = None
_volcengine_access_env: Optional[Callable[[], str]] = None
_volcengine_secret_value: Optional[Callable[[], str]] = None
_volcengine_secret_env: Optional[Callable[[], str]] = None
_volcengine_project_name = "default"
_volcengine_region = "cn-beijing"


def configure_provider_registry(
    *,
    providers_path: str,
    data_dir: str,
    lock: Lock,
    default_providers_fn: Callable[[], list[dict[str, Any]]],
    normalize_provider_fn: Callable[[dict[str, Any]], dict[str, Any]],
    merge_defaults_fn: Callable[..., list[dict[str, Any]]],
    provider_key_value_fn: Callable[[str], str],
    provider_key_env_fn: Callable[[str], str],
    mask_secret_fn: Callable[[str], str],
    runninghub_overlay_fn: Callable[[dict[str, Any]], dict[str, Any]],
    runninghub_wallet_value_fn: Callable[[], str],
    runninghub_wallet_env_fn: Callable[[], str],
    volcengine_access_value_fn: Callable[[], str],
    volcengine_access_env_fn: Callable[[], str],
    volcengine_secret_value_fn: Callable[[], str],
    volcengine_secret_env_fn: Callable[[], str],
    default_volcengine_project_name: str,
    default_volcengine_region: str,
) -> None:
    global _providers_path, _data_dir, _lock
    global _default_providers, _normalize_provider, _merge_defaults
    global _provider_key_value, _provider_key_env, _mask_secret
    global _runninghub_overlay, _runninghub_wallet_value, _runninghub_wallet_env
    global _volcengine_access_value, _volcengine_access_env
    global _volcengine_secret_value, _volcengine_secret_env
    global _volcengine_project_name, _volcengine_region

    _providers_path = providers_path
    _data_dir = data_dir
    _lock = lock
    _default_providers = default_providers_fn
    _normalize_provider = normalize_provider_fn
    _merge_defaults = merge_defaults_fn
    _provider_key_value = provider_key_value_fn
    _provider_key_env = provider_key_env_fn
    _mask_secret = mask_secret_fn
    _runninghub_overlay = runninghub_overlay_fn
    _runninghub_wallet_value = runninghub_wallet_value_fn
    _runninghub_wallet_env = runninghub_wallet_env_fn
    _volcengine_access_value = volcengine_access_value_fn
    _volcengine_access_env = volcengine_access_env_fn
    _volcengine_secret_value = volcengine_secret_value_fn
    _volcengine_secret_env = volcengine_secret_env_fn
    _volcengine_project_name = default_volcengine_project_name
    _volcengine_region = default_volcengine_region


def _require_configured() -> None:
    callbacks = (
        _default_providers,
        _normalize_provider,
        _merge_defaults,
        _provider_key_value,
        _provider_key_env,
        _mask_secret,
        _runninghub_overlay,
        _runninghub_wallet_value,
        _runninghub_wallet_env,
        _volcengine_access_value,
        _volcengine_access_env,
        _volcengine_secret_value,
        _volcengine_secret_env,
    )
    if not _providers_path or not _data_dir or _lock is None or not all(callbacks):
        raise RuntimeError("Provider registry is not configured")


def load_api_providers() -> list[dict[str, Any]]:
    _require_configured()
    defaults = _default_providers()
    if not os.path.exists(_providers_path):
        return _merge_defaults(defaults)
    try:
        with open(_providers_path, "r", encoding="utf-8") as providers_file:
            raw = json.load(providers_file)
        if not isinstance(raw, list):
            raise ValueError("Provider registry root must be a list")
        providers = [_normalize_provider(item) for item in raw if isinstance(item, dict)]
        return _merge_defaults(providers or defaults, inject_missing=not bool(providers))
    except Exception as exc:
        print(f"Failed to load API provider registry: {exc}")
        return defaults


def save_api_providers(providers: list[dict[str, Any]]) -> None:
    _require_configured()
    os.makedirs(_data_dir, exist_ok=True)
    with _lock:
        with open(_providers_path, "w", encoding="utf-8") as providers_file:
            json.dump(providers, providers_file, ensure_ascii=False, indent=2)


def public_provider(provider: dict[str, Any]) -> dict[str, Any]:
    _require_configured()
    provider = dict(provider)
    if provider.get("id") == "runninghub":
        try:
            provider = _runninghub_overlay(provider)
        except Exception:
            pass

    provider_id = str(provider.get("id") or "")
    key = _provider_key_value(provider_id)
    item = {
        **provider,
        "has_key": bool(key),
        "key_preview": _mask_secret(key),
        "key_env": _provider_key_env(provider_id),
    }
    if provider_id == "runninghub":
        wallet_key = _runninghub_wallet_value()
        item.update({
            "has_wallet_key": bool(wallet_key),
            "wallet_key_preview": _mask_secret(wallet_key),
            "wallet_key_env": _runninghub_wallet_env(),
        })
    if provider_id == "volcengine":
        access_key = _volcengine_access_value()
        secret_key = _volcengine_secret_value()
        item.update({
            "has_volcengine_access_key": bool(access_key),
            "volcengine_access_key_preview": _mask_secret(access_key),
            "volcengine_access_key_env": _volcengine_access_env(),
            "has_volcengine_secret_key": bool(secret_key),
            "volcengine_secret_key_preview": _mask_secret(secret_key),
            "volcengine_secret_key_env": _volcengine_secret_env(),
            "volcengine_project_name": provider.get("volcengine_project_name") or _volcengine_project_name,
            "volcengine_region": provider.get("volcengine_region") or _volcengine_region,
        })
    return item


def public_api_providers() -> list[dict[str, Any]]:
    return [public_provider(provider) for provider in load_api_providers()]
