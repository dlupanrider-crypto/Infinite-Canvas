import json
import os
import re
import time
import uuid

from fastapi import HTTPException, Request


_CONVERSATION_DIR = ""
_CONVERSATION_LOCK = None


def configure_conversation_storage(conversation_dir, lock):
    global _CONVERSATION_DIR, _CONVERSATION_LOCK
    _CONVERSATION_DIR = conversation_dir
    _CONVERSATION_LOCK = lock


def safe_user_id(user_id, request: Request):
    candidate = (user_id or "").strip()
    if not candidate and request.client:
        candidate = f"ip-{request.client.host}"
    if not candidate:
        candidate = "anonymous"
    candidate = re.sub(r"[^a-zA-Z0-9_.-]", "-", candidate)[:80].strip(".-")
    return candidate or "anonymous"


def user_dir(user_id):
    path = os.path.join(_CONVERSATION_DIR, user_id)
    os.makedirs(path, exist_ok=True)
    return path


def conversation_path(user_id, conversation_id):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", conversation_id or "")
    if not cleaned:
        raise HTTPException(status_code=400, detail="无效的对话 ID")
    return os.path.join(user_dir(user_id), f"{cleaned}.json")


def _now_ms():
    return int(time.time() * 1000)


def save_conversation(user_id, conversation):
    with _CONVERSATION_LOCK:
        path = conversation_path(user_id, conversation["id"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(conversation, f, ensure_ascii=False, indent=2)


def new_conversation(user_id, title="新对话"):
    timestamp = _now_ms()
    conversation = {
        "id": uuid.uuid4().hex,
        "title": (title or "新对话")[:80],
        "created_at": timestamp,
        "updated_at": timestamp,
        "messages": [],
    }
    save_conversation(user_id, conversation)
    return conversation


def load_conversation(user_id, conversation_id):
    path = conversation_path(user_id, conversation_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="对话不存在")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_conversation(user_id, conversation_id):
    path = conversation_path(user_id, conversation_id)
    with _CONVERSATION_LOCK:
        if os.path.exists(path):
            os.remove(path)


def list_conversations(user_id):
    records = []
    for filename in os.listdir(user_dir(user_id)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(user_dir(user_id), filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        messages = data.get("messages", [])
        last_message = next((m for m in reversed(messages) if m.get("role") != "system"), None)
        records.append(
            {
                "id": data.get("id"),
                "title": data.get("title", "新对话"),
                "created_at": data.get("created_at", 0),
                "updated_at": data.get("updated_at", 0),
                "last_message": (last_message or {}).get("content", ""),
            }
        )
    return sorted(records, key=lambda item: item["updated_at"], reverse=True)
