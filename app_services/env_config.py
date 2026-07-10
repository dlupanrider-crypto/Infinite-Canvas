import os
import re
from typing import Dict


_API_ENV_FILE = ""
_DATA_DIR = ""


def configure_env_config(*, api_env_file: str, data_dir: str = "") -> None:
    global _API_ENV_FILE, _DATA_DIR
    _API_ENV_FILE = api_env_file
    _DATA_DIR = data_dir


def ensure_runtime_config_files() -> None:
    try:
        os.makedirs(os.path.dirname(_API_ENV_FILE), exist_ok=True)
        if _DATA_DIR:
            os.makedirs(_DATA_DIR, exist_ok=True)
        if not os.path.exists(_API_ENV_FILE):
            with open(_API_ENV_FILE, "a", encoding="utf-8"):
                pass
    except Exception as exc:
        print(f"Failed to initialize API config files: {exc}")


def load_env_file() -> None:
    if not os.path.exists(_API_ENV_FILE):
        return
    try:
        with open(_API_ENV_FILE, "r", encoding="utf-8-sig") as f:
            for raw_line in f.read().splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except Exception as exc:
        print(f"Failed to load API/.env: {exc}")


def provider_key_env(provider_id):
    provider_id = str(provider_id or "").strip()
    if provider_id == "comfly":
        return "COMFLY_API_KEY"
    if provider_id == "modelscope":
        return "MODELSCOPE_API_KEY"
    if provider_id == "runninghub":
        return "RUNNINGHUB_API_KEY"
    if provider_id == "volcengine":
        return "ARK_API_KEY"
    return f"API_PROVIDER_{re.sub(r'[^A-Za-z0-9]', '_', provider_id).upper()}_KEY"


def runninghub_wallet_key_env():
    return "RUNNINGHUB_WALLET_API_KEY"


def volcengine_access_key_env():
    return "VOLCENGINE_ACCESS_KEY_ID"


def volcengine_secret_key_env():
    return "VOLCENGINE_SECRET_ACCESS_KEY"


def read_api_env_value(key: str) -> str:
    key = str(key or "").strip()
    if not key or not os.path.exists(_API_ENV_FILE):
        return ""
    try:
        with open(_API_ENV_FILE, "r", encoding="utf-8-sig") as f:
            for raw_line in f.read().splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                env_key, value = line.split("=", 1)
                if env_key.strip() == key:
                    return value.strip().strip('"').strip("'")
    except Exception:
        return ""
    return ""


def mask_secret(value):
    if not value:
        return ""
    tail = value[-4:] if len(value) > 4 else value
    return f"*******{tail}"


def strip_auth_scheme(value, scheme="Bearer"):
    text = str(value or "").strip()
    if not text:
        return ""
    pattern = rf"^{re.escape(scheme)}\s+"
    return re.sub(pattern, "", text, flags=re.I).strip()


def bearer_auth_value(value):
    token = strip_auth_scheme(value, "Bearer")
    return f"Bearer {token}" if token else ""


def env_quote(value):
    text = str(value or "")
    if not text or re.search(r"\s|#|['\"]", text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def update_env_values(updates: Dict[str, str]) -> None:
    os.makedirs(os.path.dirname(_API_ENV_FILE), exist_ok=True)
    lines = []
    if os.path.exists(_API_ENV_FILE):
        with open(_API_ENV_FILE, "r", encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    seen = set()
    next_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            next_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            next_lines.append(f"{key}={env_quote(updates[key])}")
            os.environ[key] = str(updates[key] or "")
            seen.add(key)
        else:
            next_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            next_lines.append(f"{key}={env_quote(value)}")
            os.environ[key] = str(value or "")
    with open(_API_ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(next_lines).rstrip() + "\n")
