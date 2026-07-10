"""Provider connectivity and model-discovery routes."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter(prefix="/api/providers", tags=["provider-probe"])
_test_connection: Optional[Callable[[Any], Awaitable[Any]]] = None
_probe_async: Optional[Callable[[Any], Awaitable[Any]]] = None
_fetch_from_payload: Optional[Callable[[Any], Awaitable[Any]]] = None
_fetch_saved: Optional[Callable[[str], Awaitable[Any]]] = None


def configure_provider_probe_routes(
    *,
    test_connection_fn: Callable[[Any], Awaitable[Any]],
    probe_async_fn: Callable[[Any], Awaitable[Any]],
    fetch_from_payload_fn: Callable[[Any], Awaitable[Any]],
    fetch_saved_fn: Callable[[str], Awaitable[Any]],
) -> None:
    global _test_connection, _probe_async, _fetch_from_payload, _fetch_saved
    _test_connection = test_connection_fn
    _probe_async = probe_async_fn
    _fetch_from_payload = fetch_from_payload_fn
    _fetch_saved = fetch_saved_fn


def _require_configured() -> None:
    if not all((_test_connection, _probe_async, _fetch_from_payload, _fetch_saved)):
        raise RuntimeError("Provider probe routes are not configured")


class TestConnectionPayload(BaseModel):
    base_url: str = ""
    api_key: str = ""
    provider_id: str = ""
    protocol: str = "openai"
    image_request_mode: str = "openai"


@router.post("/test-connection")
async def test_provider_connection(payload: TestConnectionPayload):
    _require_configured()
    return await _test_connection(payload)


@router.post("/probe-async")
async def probe_async_endpoint(payload: TestConnectionPayload):
    _require_configured()
    return await _probe_async(payload)


@router.post("/fetch-models")
async def fetch_upstream_models_from_payload(payload: TestConnectionPayload):
    _require_configured()
    return await _fetch_from_payload(payload)


@router.get("/{provider_id}/fetch-models")
async def fetch_upstream_models(provider_id: str):
    _require_configured()
    return await _fetch_saved(provider_id)
