"""Local CLI provider status, authentication, and help routes."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter(tags=["cli-tools"])
_handlers: dict[str, Callable[..., Awaitable[Any]]] = {}


def configure_cli_tool_routes(**handlers: Callable[..., Awaitable[Any]]) -> None:
    global _handlers
    _handlers = handlers


def _handler(name: str) -> Callable[..., Awaitable[Any]]:
    handler = _handlers.get(name)
    if handler is None:
        raise RuntimeError(f"CLI tool route handler is not configured: {name}")
    return handler


class JimengHelpRequest(BaseModel):
    command: str = ""


class CodexHelpRequest(BaseModel):
    command: str = ""


class GeminiCliHelpRequest(BaseModel):
    command: str = ""


class JimengQueryMediaRequest(BaseModel):
    submit_id: str = ""
    kind: str = "image"


@router.get("/api/codex/status")
async def codex_status():
    return await _handler("codex_status")()


@router.post("/api/codex/help")
async def codex_help(payload: CodexHelpRequest):
    return await _handler("codex_help")(payload)


@router.get("/api/gemini-cli/status")
async def gemini_cli_status():
    return await _handler("gemini_status")()


@router.post("/api/gemini-cli/help")
async def gemini_cli_help(payload: GeminiCliHelpRequest):
    return await _handler("gemini_help")(payload)


@router.get("/api/jimeng/status")
async def jimeng_status():
    return await _handler("jimeng_status")()


@router.get("/api/jimeng/credit")
async def jimeng_credit():
    return await _handler("jimeng_credit")()


@router.post("/api/jimeng/logout")
async def jimeng_logout():
    return await _handler("jimeng_logout")()


@router.post("/api/jimeng/login/start")
async def jimeng_login_start():
    return await _handler("jimeng_login_start")()


@router.get("/api/jimeng/login/status")
async def jimeng_login_status():
    return await _handler("jimeng_login_status")()


@router.post("/api/jimeng/help")
async def jimeng_help(payload: JimengHelpRequest):
    return await _handler("jimeng_help")(payload)


@router.post("/api/jimeng/query-media")
async def jimeng_query_media(payload: JimengQueryMediaRequest):
    return await _handler("jimeng_query_media")(payload)
