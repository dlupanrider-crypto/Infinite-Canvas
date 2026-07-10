"""Shared request models for generation and canvas services."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


ONLINE_IMAGE_PROMPT_MAX_LENGTH = int(os.getenv("ONLINE_IMAGE_PROMPT_MAX_LENGTH", "12000"))
VIDEO_PROMPT_MAX_LENGTH = int(os.getenv("VIDEO_PROMPT_MAX_LENGTH", "12000"))
LLM_MESSAGE_MAX_LENGTH = int(os.getenv("LLM_MESSAGE_MAX_LENGTH", "20000"))


class GenerateRequest(BaseModel):
    prompt: str = ""
    width: int = 1024
    height: int = 1024
    workflow_json: str = "Z-Image.json"
    params: Dict[str, Any] = Field(default_factory=dict)
    type: str = "zimage"
    client_id: str = ""
    convert_to_jpg: bool = False


class TokenRequest(BaseModel):
    token: str


class CloudGenRequest(BaseModel):
    prompt: str
    api_key: str = ""
    model: str = ""
    resolution: str = "1024x1024"
    type: str = "zimage"
    image_urls: List[str] = Field(default_factory=list)
    loras: Optional[Any] = None
    client_id: Optional[str] = None


class CloudPollRequest(BaseModel):
    task_id: str
    api_key: str = ""
    client_id: Optional[str] = None


class AIReference(BaseModel):
    url: str = ""
    name: str = ""
    role: str = ""
    kind: str = ""
    mime: str = ""


class OnlineImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=ONLINE_IMAGE_PROMPT_MAX_LENGTH)
    provider_id: str = "comfly"
    model: str = ""
    size: str = "1024x1024"
    quality: str = "auto"
    n: int = 1
    reference_images: List[AIReference] = Field(default_factory=list)


class ImageTaskQueryRequest(BaseModel):
    provider_id: str = "comfly"
    task_id: str = Field(min_length=1, max_length=240)


class CanvasVideoRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=VIDEO_PROMPT_MAX_LENGTH)
    provider_id: str = "comfly"
    model: str = "veo3-fast"
    duration: int = 5
    aspect_ratio: str = "16:9"
    resolution: str = ""
    size: str = ""
    images: List[AIReference] = Field(default_factory=list)
    videos: List[str] = Field(default_factory=list)
    audios: List[str] = Field(default_factory=list)
    enhance_prompt: bool = False
    enable_upsample: bool = False
    watermark: bool = False
    seed: Optional[int] = None
    camerafixed: bool = False
    return_last_frame: bool = False
    generate_audio: bool = False
    multimodal: bool = False
    trusted_asset: bool = False


class MsGenerateRequest(BaseModel):
    prompt: str
    api_key: str = ""
    model: str = "black-forest-labs/FLUX.2-klein-9B"
    image_urls: List[str] = Field(default_factory=list)
    width: int = 0
    height: int = 0
    size: str = ""
    loras: Optional[Any] = None
    client_id: Optional[str] = None


class CanvasLLMRequest(BaseModel):
    message: str = Field(min_length=1, max_length=LLM_MESSAGE_MAX_LENGTH)
    system_prompt: str = ""
    model: str = ""
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    provider: str = "comfly"
    ms_model: str = ""
    images: List[str] = Field(default_factory=list)
    videos: List[str] = Field(default_factory=list)
