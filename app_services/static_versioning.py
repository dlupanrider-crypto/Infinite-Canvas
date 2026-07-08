import json
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, Tuple

import requests
from fastapi.responses import Response


_BASE_DIR = ""
_STATIC_DIR = ""
_GITHUB_UPDATE_NOTES_URL = ""
_MODELSCOPE_UPDATE_NOTES_URL = ""


def configure_static_versioning(
    *,
    base_dir: str,
    static_dir: str,
    github_update_notes_url: str,
    modelscope_update_notes_url: str,
) -> None:
    global _BASE_DIR, _STATIC_DIR, _GITHUB_UPDATE_NOTES_URL, _MODELSCOPE_UPDATE_NOTES_URL
    _BASE_DIR = base_dir
    _STATIC_DIR = static_dir
    _GITHUB_UPDATE_NOTES_URL = github_update_notes_url
    _MODELSCOPE_UPDATE_NOTES_URL = modelscope_update_notes_url


def current_app_version() -> str:
    version_file = os.path.join(_BASE_DIR, "VERSION")
    try:
        if os.path.exists(version_file):
            with open(version_file, "r", encoding="utf-8") as f:
                version = (f.read().strip().splitlines() or [""])[0].strip()
                if version:
                    return version
    except Exception:
        pass
    try:
        return time.strftime("%Y.%m.%d", time.localtime())
    except Exception:
        return ""


def update_notes_path() -> str:
    return os.path.join(_STATIC_DIR, "update-notes.json")


def safe_update_notes(payload: Any, version: str = "") -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    clean_items = []
    for item in items[:30]:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("title") or "").strip()
            if not text:
                continue
            clean_items.append({
                "type": str(item.get("type") or "update").strip()[:32],
                "text": text[:500],
            })
        else:
            text = str(item or "").strip()
            if text:
                clean_items.append({"type": "update", "text": text[:500]})
    notes_version = str(payload.get("version") or version or "").strip()
    history = payload.get("history")
    selected_history = {}
    if version and isinstance(history, list):
        for entry in history:
            if isinstance(entry, dict) and str(entry.get("version") or "").strip() == version:
                selected_history = safe_update_notes(entry, version)
                break
    if selected_history:
        return selected_history
    return {
        "version": notes_version,
        "updated_at": str(payload.get("updated_at") or payload.get("date") or "").strip(),
        "items": clean_items,
    }


def read_local_update_notes(version: str = "") -> Dict[str, Any]:
    try:
        path = update_notes_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return safe_update_notes(json.load(f), version)
    except Exception:
        pass
    return {"version": version or current_app_version(), "updated_at": "", "items": []}


def fetch_remote_update_notes(url: str, version: str = "", timeout: float = 5.0) -> Dict[str, Any]:
    info: Dict[str, Any] = {"ok": False, "error": "", "url": url, "version": version, "items": []}
    if not url:
        info["error"] = "missing url"
        return info
    try:
        resp = requests.get(
            f"{url}{'&' if '?' in url else '?'}t={int(time.time())}",
            headers={"User-Agent": "Infinite-Canvas-Updater"},
            timeout=timeout,
            proxies=urllib.request.getproxies() or None,
        )
        if 200 <= resp.status_code < 400:
            payload = json.loads(resp.content.decode("utf-8", errors="replace"))
            notes = safe_update_notes(payload, version)
            info.update(notes)
            info["ok"] = True
        else:
            info["error"] = f"HTTP {resp.status_code}"
    except Exception as exc:
        info["error"] = str(exc)
    return info


def fetch_update_notes_with_fallback(
    preferred_source: str,
    version: str,
    timeout: float = 3.0,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    urls = {
        "github": _GITHUB_UPDATE_NOTES_URL,
        "modelscope": _MODELSCOPE_UPDATE_NOTES_URL,
    }
    preferred = preferred_source if preferred_source in urls else "github"
    order = [preferred, "modelscope" if preferred == "github" else "github"]
    notes_by_source: Dict[str, Any] = {}
    best_notes: Dict[str, Any] = {"version": version, "items": []}
    for source in order:
        notes = fetch_remote_update_notes(urls[source], version, timeout=timeout)
        notes["source"] = source
        notes_by_source[source] = notes
        if notes.get("ok") and (notes.get("items") or []):
            best_notes = notes
            break
    for source, url in urls.items():
        if source not in notes_by_source:
            notes_by_source[source] = {
                "ok": False,
                "error": "not attempted: update notes already available" if best_notes.get("items") else "not attempted",
                "url": url,
                "source": source,
                "version": version,
                "items": [],
            }
    return best_notes, notes_by_source


def versioned_static_html(html: str) -> str:
    version = current_app_version()
    if not version:
        return html
    safe_version = urllib.parse.quote(version, safe="._-")
    pattern = re.compile(
        r'(?P<prefix>(?:src|href)=["\']|@import\s+url\(["\'])(?P<url>/static/[^"\')?#]+(?:\.(?:js|css|html)))(?:\?v=[^"\')#]*)?',
        re.I,
    )

    def replace(match):
        url = match.group("url")
        cache_version = safe_version
        try:
            rel = urllib.parse.unquote(url[len("/static/"):]).replace("/", os.sep)
            path = os.path.abspath(os.path.join(_STATIC_DIR, rel))
            static_root = os.path.abspath(_STATIC_DIR)
            if path.startswith(static_root + os.sep) and os.path.isfile(path):
                cache_version = f"{safe_version}.{int(os.path.getmtime(path))}"
        except Exception:
            pass
        return f"{match.group('prefix')}{url}?v={cache_version}"

    return pattern.sub(replace, html)


def sync_static_html_versions() -> None:
    version = current_app_version()
    if not version:
        return
    safe_version = urllib.parse.quote(version, safe="._-")
    try:
        for name in os.listdir(_STATIC_DIR):
            if name.startswith("._") or not name.lower().endswith(".html"):
                continue
            path = os.path.join(_STATIC_DIR, name)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = f.read()
                new = versioned_static_html(re.sub(r'([?&]v=)[^"\'`\s<>)]*', rf'\g<1>{safe_version}', old))
                if new != old:
                    with open(path, "w", encoding="utf-8", newline="") as f:
                        f.write(new)
            except Exception as exc:
                print(f"Failed to sync static page version ({name}): {exc}")
    except Exception as exc:
        print(f"Failed to sync static page versions: {exc}")


def static_html_response(filename: str):
    path = os.path.join(_STATIC_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    return Response(
        versioned_static_html(html),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )

