"""Provider configuration normalization rules."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Callable, Optional


PROVIDER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{2,40}$")
SUPPORTED_PROVIDER_PROTOCOLS = {
    "openai",
    "apimart",
    "gemini",
    "gemini-cli",
    "volcengine",
    "runninghub",
    "jimeng",
    "codex",
}
SUPPORTED_IMAGE_REQUEST_MODES = {
    "openai",
    "openai-json",
    "openai-video-proxy",
    "openai-responses",
}
PER_MODEL_PROTOCOL_OPTIONS = {"openai", "gemini"}

LOCKED_RECOMMENDED_PROVIDER_RULES = {
    "exellome": {
        "names": {"exellome"},
        "base_urls": {"https://new.exellome.online"},
        "protocol": "apimart",
        "image_request_mode": "openai-video-proxy",
        "video_models": [],
    },
    "fhl": {
        "names": {"fhl"},
        "base_urls": {"https://www.fhl.mom"},
        "protocol": "openai",
        "image_request_mode": "openai-responses",
        "video_models": [],
    },
}

_model_list_normalizer: Optional[Callable[[Any], list[str]]] = None
_runninghub_entries_normalizer: Optional[Callable[[Any, str], list[dict[str, Any]]]] = None
_bad_request_factory: Optional[Callable[[str], Exception]] = None
_volcengine_base_url = ""
_volcengine_project_name = "default"
_volcengine_region = "cn-beijing"
_runninghub_base_url = "https://www.runninghub.cn"


def configure_provider_normalization(
    *,
    model_list_normalizer: Callable[[Any], list[str]],
    runninghub_entries_normalizer: Callable[[Any, str], list[dict[str, Any]]],
    bad_request_factory: Callable[[str], Exception],
    volcengine_base_url: str,
    volcengine_project_name: str,
    volcengine_region: str,
    runninghub_base_url: str,
) -> None:
    global _model_list_normalizer, _runninghub_entries_normalizer, _bad_request_factory
    global _volcengine_base_url, _volcengine_project_name, _volcengine_region
    global _runninghub_base_url
    _model_list_normalizer = model_list_normalizer
    _runninghub_entries_normalizer = runninghub_entries_normalizer
    _bad_request_factory = bad_request_factory
    _volcengine_base_url = volcengine_base_url
    _volcengine_project_name = volcengine_project_name
    _volcengine_region = volcengine_region
    _runninghub_base_url = runninghub_base_url


def _require_configured() -> None:
    if not all((_model_list_normalizer, _runninghub_entries_normalizer, _bad_request_factory)):
        raise RuntimeError("Provider normalization is not configured")


def _bad_request(detail: str) -> Exception:
    _require_configured()
    return _bad_request_factory(detail)


def normalize_endpoint_override(value: Any, label: str) -> str:
    endpoint = str(value or "").strip()
    if not endpoint:
        return ""
    if len(endpoint) > 300 or re.search(r"\s", endpoint):
        raise _bad_request(
            f"{label} \u4e0d\u5408\u6cd5\uff0c\u8bf7\u586b\u5199\u7c7b\u4f3c /v1/images/edits \u7684\u8def\u5f84"
        )
    if re.match(r"^https?://", endpoint, re.I):
        return endpoint.rstrip("/")
    if not endpoint.startswith("/"):
        raise _bad_request(
            f"{label} \u9700\u8981\u4ee5 /v1/... \u5f00\u5934\uff0c\u6216\u586b\u5199\u5b8c\u6574 http(s) \u5730\u5740"
        )
    return endpoint


def normalize_image_request_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in SUPPORTED_IMAGE_REQUEST_MODES else "openai"


def locked_recommended_provider_rule(
    provider_id: str = "",
    name: str = "",
    base_url: str = "",
) -> Optional[dict[str, Any]]:
    provider_id = str(provider_id or "").strip().lower()
    provider_name = str(name or "").strip().lower()
    normalized_base_url = str(base_url or "").strip().rstrip("/").lower()
    try:
        host = urllib.parse.urlsplit(normalized_base_url).netloc.lower()
    except Exception:
        host = ""
    for key, rule in LOCKED_RECOMMENDED_PROVIDER_RULES.items():
        hosts = {urllib.parse.urlsplit(url).netloc.lower() for url in rule["base_urls"]}
        if (
            provider_id == key
            or provider_name in rule["names"]
            or normalized_base_url in rule["base_urls"]
            or (host and host in hosts)
        ):
            return rule
    return None


def apply_locked_recommended_model_rules(
    base_url: str = "",
    grouped: Optional[dict[str, list[str]]] = None,
) -> Optional[dict[str, list[str]]]:
    rule = locked_recommended_provider_rule("", "", base_url)
    if not rule or "video_models" not in rule:
        return grouped
    normalized = {key: list(value or []) for key, value in (grouped or {}).items()}
    normalized.setdefault("image", [])
    normalized.setdefault("chat", [])
    normalized["video"] = list(rule.get("video_models") or [])
    return normalized


def normalize_model_protocols(value: Any) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if isinstance(value, dict):
        for raw_name, raw_protocol in value.items():
            name = str(raw_name or "").strip()
            protocol = str(raw_protocol or "").strip().lower()
            if name and protocol in PER_MODEL_PROTOCOL_OPTIONS:
                normalized[name] = protocol
    return normalized


def detect_image_request_mode(base_url: str = "", models: Any = None) -> str:
    normalized_base_url = str(base_url or "").strip().lower()
    if "apihub.agnes-ai.com" in normalized_base_url:
        return "openai-json"
    for model in models or []:
        if str(model or "").strip().lower().startswith("agnes-image-"):
            return "openai-json"
    return ""


def normalize_ms_loras(values: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in values or []:
        if not isinstance(raw, dict):
            continue
        lora_id = str(raw.get("id") or "").strip()
        target_model = str(raw.get("target_model") or raw.get("model") or "").strip()
        if not lora_id or not target_model:
            continue
        key = (target_model, lora_id)
        if key in seen:
            continue
        seen.add(key)
        try:
            strength = float(raw.get("strength", raw.get("default_strength", 0.8)))
        except Exception:
            strength = 0.8
        normalized.append({
            "id": lora_id[:180],
            "name": re.sub(r"\s+", " ", str(raw.get("name") or "").strip())[:80] or lora_id,
            "target_model": target_model[:180],
            "strength": max(0.0, min(2.0, strength)),
            "enabled": bool(raw.get("enabled", True)),
            "note": str(raw.get("note") or "").strip()[:300],
        })
    return normalized


def normalize_provider(item: dict[str, Any]) -> dict[str, Any]:
    _require_configured()
    provider_id = str(item.get("id") or "").strip().lower()
    if not PROVIDER_ID_RE.fullmatch(provider_id):
        raise _bad_request(
            f"API \u5e73\u53f0 ID \u4e0d\u5408\u6cd5\uff1a{provider_id or '(empty)'}"
        )
    name = re.sub(r"\s+", " ", str(item.get("name") or provider_id).strip())[:60] or provider_id
    base_url = str(item.get("base_url") or "").strip().rstrip("/")
    if base_url and not re.match(r"^https?://", base_url):
        raise _bad_request(
            f"{name} \u7684 Base URL \u9700\u8981\u4ee5 http:// \u6216 https:// \u5f00\u5934"
        )

    protocol = str(item.get("protocol") or "openai").strip().lower()
    if protocol not in SUPPORTED_PROVIDER_PROTOCOLS:
        protocol = "openai"
    image_request_mode = (
        detect_image_request_mode(base_url, item.get("image_models") or [])
        or normalize_image_request_mode(item.get("image_request_mode"))
    )
    image_generation_endpoint = normalize_endpoint_override(
        item.get("image_generation_endpoint"),
        "\u6587\u751f\u56fe\u7aef\u53e3",
    )
    image_edit_endpoint = normalize_endpoint_override(
        item.get("image_edit_endpoint"),
        "\u56fe\u751f\u56fe/\u7f16\u8f91\u7aef\u53e3",
    )
    volcengine_project = re.sub(
        r"\s+", " ", str(item.get("volcengine_project_name") or "").strip()
    )[:80]
    volcengine_region = re.sub(
        r"\s+", " ", str(item.get("volcengine_region") or "").strip()
    )[:40]

    if provider_id == "volcengine":
        protocol = "volcengine"
        base_url = base_url or _volcengine_base_url
        volcengine_project = volcengine_project or _volcengine_project_name
        volcengine_region = volcengine_region or _volcengine_region
    if provider_id == "jimeng" or protocol == "jimeng":
        protocol = "jimeng"
        base_url = ""
    if protocol in {"codex", "gemini-cli"}:
        base_url = ""
    if provider_id == "runninghub":
        protocol = "runninghub"
        base_url = base_url or _runninghub_base_url

    locked_rule = locked_recommended_provider_rule(provider_id, name, base_url)
    if locked_rule:
        protocol = locked_rule["protocol"]
        image_request_mode = locked_rule["image_request_mode"]
    video_models = _model_list_normalizer(item.get("video_models") or [])
    if locked_rule and "video_models" in locked_rule:
        video_models = _model_list_normalizer(locked_rule.get("video_models") or [])

    return {
        "id": provider_id,
        "name": name,
        "base_url": base_url,
        "protocol": protocol,
        "image_request_mode": image_request_mode,
        "image_generation_endpoint": image_generation_endpoint,
        "image_edit_endpoint": image_edit_endpoint,
        "enabled": bool(item.get("enabled", True)),
        "primary": bool(item.get("primary", False)),
        "image_models": _model_list_normalizer(item.get("image_models") or []),
        "chat_models": _model_list_normalizer(item.get("chat_models") or []),
        "video_models": video_models,
        "model_protocols": normalize_model_protocols(item.get("model_protocols")),
        "ms_loras": normalize_ms_loras(item.get("ms_loras") or []),
        "ms_defaults_version": int(item.get("ms_defaults_version") or 0),
        "rh_apps": _runninghub_entries_normalizer(item.get("rh_apps") or [], "app"),
        "rh_workflows": _runninghub_entries_normalizer(item.get("rh_workflows") or [], "workflow"),
        "volcengine_project_name": volcengine_project,
        "volcengine_region": volcengine_region,
    }
