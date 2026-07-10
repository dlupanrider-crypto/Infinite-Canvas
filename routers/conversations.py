"""Conversation storage routes."""

from __future__ import annotations

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel

from repositories.conversations import (
    delete_conversation,
    list_conversations,
    load_conversation,
    new_conversation,
    safe_user_id,
)


router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreateRequest(BaseModel):
    title: str = "\u65b0\u5bf9\u8bdd"


@router.get("")
async def conversations(request: Request, x_user_id: str = Header(default="")):
    user_id = safe_user_id(x_user_id, request)
    return {"user_id": user_id, "conversations": list_conversations(user_id)}


@router.post("")
async def create_conversation(
    payload: ConversationCreateRequest,
    request: Request,
    x_user_id: str = Header(default=""),
):
    user_id = safe_user_id(x_user_id, request)
    return {"conversation": new_conversation(user_id, payload.title)}


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    request: Request,
    x_user_id: str = Header(default=""),
):
    user_id = safe_user_id(x_user_id, request)
    return {"conversation": load_conversation(user_id, conversation_id)}


@router.delete("/{conversation_id}")
async def remove_conversation(
    conversation_id: str,
    request: Request,
    x_user_id: str = Header(default=""),
):
    user_id = safe_user_id(x_user_id, request)
    delete_conversation(user_id, conversation_id)
    return {"ok": True}
