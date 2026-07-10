"""Chat, agent-chat, and streaming-chat routes."""

from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, Dict, List

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/chat", tags=["chat"])
_handlers: dict[str, Callable[..., Awaitable[Any]]] = {}
_message_max_length = int(os.getenv("LLM_MESSAGE_MAX_LENGTH", "20000"))


def configure_chat_routes(**handlers: Callable[..., Awaitable[Any]]) -> None:
    global _handlers
    _handlers = handlers


def _handler(name: str) -> Callable[..., Awaitable[Any]]:
    handler = _handlers.get(name)
    if handler is None:
        raise RuntimeError(f"Chat route handler is not configured: {name}")
    return handler


class AIReference(BaseModel):
    url: str = ""
    kind: str = "image"
    name: str = ""


class ChatRequest(BaseModel):
    conversation_id: str = ""
    message: str = Field(min_length=1, max_length=_message_max_length)
    system_prompt: str = ""
    model: str = ""
    image_model: str = ""
    image_provider: str = ""
    mode: str = "chat"
    size: str = "1024x1024"
    quality: str = "auto"
    reference_images: List[AIReference] = Field(default_factory=list)
    provider: str = "comfly"
    ms_model: str = ""


@router.post("")
async def chat(
    payload: ChatRequest,
    request: Request,
    x_user_id: str = Header(default=""),
):
    return await _handler("chat")(payload, request, x_user_id)


@router.post("/agent")
async def chat_agent(
    payload: ChatRequest,
    request: Request,
    x_user_id: str = Header(default=""),
):
    return await _handler("agent")(payload, request, x_user_id)


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    x_user_id: str = Header(default=""),
):
    return await _handler("stream")(payload, request, x_user_id)
