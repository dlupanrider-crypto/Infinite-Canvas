"""Extracted runtime state services."""

from __future__ import annotations

import asyncio
import base64
import datetime
import functools
import glob
import hashlib
import hmac
import html
import json
import math
import mimetypes
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import httpx
import requests
from fastapi import HTTPException
from PIL import Image, ImageOps


RUNTIME_STATE_EXPORTS = (
    'apply_comfyui_instances',
    'queue_status_for_client',
)


def configure_runtime_state(namespace: dict[str, Any]) -> None:
    required = {
        'BACKEND_LOCAL_LOAD',
        'COMFYUI_INSTANCES',
        'QUEUE',
        'QUEUE_LOCK',
    }
    missing = sorted(required - namespace.keys())
    if missing:
        raise RuntimeError(f"Runtime State missing dependencies: {', '.join(missing)}")
    globals().update({name: namespace[name] for name in required})


def export_runtime_state(target: dict[str, Any]) -> None:
    for name in RUNTIME_STATE_EXPORTS:
        target[name] = globals()[name]


def apply_comfyui_instances(instances):
    global COMFYUI_INSTANCES, COMFYUI_ADDRESS, BACKEND_LOCAL_LOAD
    COMFYUI_INSTANCES = list(instances)
    COMFYUI_ADDRESS = COMFYUI_INSTANCES[0]
    previous_load = BACKEND_LOCAL_LOAD or {}
    BACKEND_LOCAL_LOAD = {
        address: previous_load.get(address, 0)
        for address in COMFYUI_INSTANCES
    }

def queue_status_for_client(client_id):
    with QUEUE_LOCK:
        total = len(QUEUE)
        positions = [
            index + 1
            for index, task in enumerate(QUEUE)
            if task["client_id"] == client_id
        ]
    return {"total": total, "position": positions[0] if positions else 0}
