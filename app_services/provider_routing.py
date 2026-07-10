"""Provider protocol detection and endpoint routing helpers."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Callable, Optional

from app_services.provider_normalization import (
    PER_MODEL_PROTOCOL_OPTIONS,
    detect_image_request_mode,
    normalize_image_request_mode,
)


FIXED_PROTOCOL_PROVIDER_IDS = {"modelscope", "volcengine", "jimeng", "runninghub"}
_default_ai_base_url: Optional[Callable[[], str]] = None
_runninghub_base_url = "https://www.runninghub.cn"


def configure_provider_routing(
    *,
    default_ai_base_url_fn: Callable[[], str],
    runninghub_base_url: str,
) -> None:
    global _default_ai_base_url, _runninghub_base_url
    _default_ai_base_url = default_ai_base_url_fn
    _runninghub_base_url = runninghub_base_url


def provider_endpoint_url(provider: Any, key: str, default_path: str) -> str:
    default_base_url = _default_ai_base_url() if _default_ai_base_url else ""
    base_url = str((provider or {}).get("base_url") or default_base_url).strip().rstrip("/")
    override = str((provider or {}).get(key) or "").strip()
    if override:
        if re.match(r"^https?://", override, re.I):
            return override.rstrip("/")
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}{override}"
        return override
    for prefix in ("/api/v3", "/v1beta", "/v1", "/v2"):
        if base_url.endswith(prefix) and default_path.startswith(f"{prefix}/"):
            return f"{base_url}{default_path[len(prefix):]}"
    return f"{base_url}{default_path}"


def runninghub_endpoint_url(provider: Any, path: str) -> str:
    base_url = str((provider or {}).get("base_url") or _runninghub_base_url).strip().rstrip("/")
    return f"{base_url}{path}"


def runninghub_openapi_base_url(provider: Any = None) -> str:
    base_url = str((provider or {}).get("base_url") or _runninghub_base_url).strip().rstrip("/")
    return base_url if base_url.endswith("/openapi/v2") else f"{base_url}/openapi/v2"


def runninghub_openapi_url(provider: Any, path: str = "") -> str:
    path = str(path or "").strip()
    if path.startswith(("http://", "https://")):
        return path
    path = path.lstrip("/")
    base_url = runninghub_openapi_base_url(provider)
    return f"{base_url}/{path}" if path else base_url


def provider_protocol(provider: Any) -> str:
    return str((provider or {}).get("protocol") or "openai").strip().lower()


def effective_protocol(provider: Any, model: str = "") -> str:
    base_protocol = provider_protocol(provider)
    provider_id = str((provider or {}).get("id") or "").strip().lower()
    if provider_id in FIXED_PROTOCOL_PROVIDER_IDS:
        return base_protocol
    overrides = (provider or {}).get("model_protocols")
    if isinstance(overrides, dict):
        protocol = str(overrides.get(str(model or "").strip()) or "").strip().lower()
        if protocol in PER_MODEL_PROTOCOL_OPTIONS:
            return protocol
    return base_protocol


def is_apimart_provider(provider: Any) -> bool:
    base_url = str((provider or {}).get("base_url") or "").lower()
    return provider_protocol(provider) == "apimart" or "apimart.ai" in base_url


def effective_image_request_mode(provider: Any, model: str = "") -> str:
    detected = detect_image_request_mode((provider or {}).get("base_url"), [model])
    return detected or normalize_image_request_mode((provider or {}).get("image_request_mode"))


def is_gemini_provider(provider: Any) -> bool:
    return provider_protocol(provider) == "gemini"


def is_volcengine_provider(provider: Any) -> bool:
    return provider_protocol(provider) == "volcengine"


def is_runninghub_provider(provider: Any) -> bool:
    return (
        provider_protocol(provider) == "runninghub"
        or str((provider or {}).get("id") or "").strip().lower() == "runninghub"
    )


def is_jimeng_provider(provider: Any) -> bool:
    return (
        provider_protocol(provider) == "jimeng"
        or str((provider or {}).get("id") or "").strip().lower() == "jimeng"
    )


def is_codex_provider(provider: Any) -> bool:
    return provider_protocol(provider) == "codex"


def is_gemini_cli_provider(provider: Any) -> bool:
    return provider_protocol(provider) == "gemini-cli"
