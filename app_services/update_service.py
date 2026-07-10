import json
import os
import re
import shutil
import time
import traceback
import urllib.request
from threading import Thread
from typing import Any, Callable, Dict, List, Tuple

import requests


UPDATE_SOURCE_LABELS = {"github": "GitHub", "modelscope": "ModelScope"}


class UpdateDownloadError(RuntimeError):
    pass


class BackupValidationError(ValueError):
    pass


class BackupNotFoundError(FileNotFoundError):
    pass


def version_tuple(value: str) -> List[int]:
    return [int(x) for x in re.findall(r"\d+", str(value or ""))]


def version_gt(a: str, b: str) -> bool:
    ta, tb = version_tuple(a), version_tuple(b)
    n = max(len(ta), len(tb))
    ta += [0] * (n - len(ta))
    tb += [0] * (n - len(tb))
    return ta > tb


def update_allowed_file(path: str) -> bool:
    path = str(path or "").replace("\\", "/").lstrip("/")
    if not path or any(part in {"", ".", ".."} for part in path.split("/")):
        return False
    return path in {"main.py", "VERSION"} or path.startswith("static/")


def normalize_update_source(value: str) -> str:
    source = str(value or "github").strip().lower()
    if source == "ms":
        return "modelscope"
    if source not in {"github", "modelscope"}:
        return "github"
    return source


def connectivity_probe(name: str, url: str, timeout: float = 5.0) -> Dict[str, Any]:
    started = time.time()
    item = {
        "name": name,
        "url": url,
        "ok": False,
        "status": 0,
        "elapsed_ms": 0,
        "error": "",
        "timed_out": False,
    }
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Infinite-Canvas-Updater"},
            timeout=timeout,
            stream=True,
            proxies=urllib.request.getproxies() or None,
        )
        item["status"] = response.status_code
        item["ok"] = 200 <= response.status_code < 400
        if not item["ok"]:
            item["error"] = f"HTTP {response.status_code} {response.reason}"
        response.close()
    except requests.Timeout:
        item["timed_out"] = True
        item["error"] = f"connection timed out after {timeout:g}s"
    except requests.RequestException as exc:
        item["error"] = str(exc)
    finally:
        item["elapsed_ms"] = int((time.time() - started) * 1000)
    return item


def update_connectivity_targets(
    *,
    github_tree_url: str,
    github_version_url: str,
    modelscope_version_url: str,
    modelscope_repo_url: str,
) -> List[Tuple[str, str, str, bool]]:
    return [
        ("GitHub 更新列表", github_tree_url, "github", True),
        ("GitHub 版本文件", github_version_url, "github", True),
        ("GitHub 主页", "https://github.com/", "github", False),
        ("ModelScope 版本文件", modelscope_version_url, "modelscope", True),
        ("ModelScope 空间页面", modelscope_repo_url, "modelscope", False),
        ("ModelScope 主页", "https://modelscope.cn/", "modelscope", False),
        ("Google 连通性", "https://www.google.com/generate_204", "reference", False),
    ]


def build_update_connectivity(targets: List[Tuple[str, str, str, bool]]) -> Dict[str, Any]:
    results = []
    for name, url, source, required in targets:
        item = connectivity_probe(name, url)
        item["source"] = source
        item["required"] = required
        results.append(item)
    sources = {}
    for source in ("github", "modelscope"):
        source_required = [item for item in results if item.get("source") == source and item.get("required")]
        sources[source] = {
            "ok": all(item["ok"] for item in source_required),
            "required": [item["name"] for item in source_required],
        }
    return {
        "ok": sources["github"]["ok"],
        "results": results,
        "sources": sources,
        "required": sources["github"]["required"],
        "optional": ["GitHub 主页", "ModelScope 空间页面", "ModelScope 主页", "Google 连通性"],
    }


def probe_update_connectivity_target(
    target_name: str,
    targets: List[Tuple[str, str, str, bool]],
) -> Dict[str, Any]:
    for name, url, source, required in targets:
        if name == target_name:
            item = connectivity_probe(name, url)
            item["source"] = source
            item["required"] = required
            return item
    return {}


def fetch_remote_version(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    info: Dict[str, Any] = {"version": "", "ok": False, "error": "", "url": url}
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
            text = resp.content.decode("utf-8", errors="replace").strip()
            version = text.splitlines()[0].strip() if text else ""
            if version and "<" not in version and "{" not in version and re.search(r"\d", version):
                info["version"] = version
                info["ok"] = True
            elif not version:
                info["error"] = "empty version file"
            else:
                info["error"] = "invalid version file format"
        else:
            info["error"] = f"HTTP {resp.status_code}"
    except requests.RequestException as exc:
        info["error"] = str(exc)
    return info


def build_check_update_info(
    *,
    current: str,
    github_version_url: str,
    modelscope_version_url: str,
    fetch_update_notes: Callable[[str, str, float], Tuple[Dict[str, Any], Dict[str, Any]]],
    probe_timeout: float = 5.0,
    join_timeout: float = 5.5,
) -> Dict[str, Any]:
    holder: Dict[str, Dict[str, Any]] = {}

    def _probe(key: str, url: str):
        item = fetch_remote_version(url, timeout=probe_timeout)
        item["source"] = key
        holder[key] = item

    threads = [
        Thread(target=_probe, args=("github", github_version_url), daemon=True),
        Thread(target=_probe, args=("modelscope", modelscope_version_url), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=join_timeout)

    github = holder.get("github") or {
        "version": "",
        "ok": False,
        "error": f"check timed out after {probe_timeout:g}s",
        "url": github_version_url,
        "source": "github",
    }
    modelscope = holder.get("modelscope") or {
        "version": "",
        "ok": False,
        "error": f"check timed out after {probe_timeout:g}s",
        "url": modelscope_version_url,
        "source": "modelscope",
    }
    best: Dict[str, Any] = {}
    for item in (github, modelscope):
        if item["ok"] and item["version"]:
            if not best or version_gt(item["version"], best["version"]):
                best = {"source": item["source"], "version": item["version"]}
    update_available = bool(best and version_gt(best["version"], current))
    notes_by_source: Dict[str, Any] = {}
    if best and best.get("version"):
        best_notes, notes_by_source = fetch_update_notes(str(best.get("source") or "github"), best["version"], 3.0)
        best["update_notes"] = best_notes if best_notes.get("ok") else {"version": best["version"], "items": []}
    return {
        "current": current,
        "github": github,
        "modelscope": modelscope,
        "latest": best,
        "update_notes": best.get("update_notes") if best else {},
        "update_notes_sources": notes_by_source,
        "update_available": update_available,
        "reachable": bool(github["ok"] or modelscope["ok"]),
    }


def apply_update_from_source(
    *,
    data_dir: str,
    requested_source: str,
    fallback: bool,
    auto_restart: bool,
    restart_delay: int,
    stage_update_from_source,
    safe_update_target,
    safe_static_dir,
    schedule_self_restart,
    safe_update_notes,
) -> Dict[str, Any]:
    staging_root = ""
    source_order = [requested_source]
    if fallback:
        other = "modelscope" if requested_source == "github" else "github"
        source_order.append(other)
    try:
        backup_root = os.path.join(data_dir, "update_backups", time.strftime("%Y%m%d-%H%M%S"))
        source = requested_source
        root_files = static_files = files = None
        download_errors: List[str] = []
        fallback_used = False

        for idx, candidate in enumerate(source_order):
            attempt_staging = os.path.join(
                data_dir,
                "update_staging",
                f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{candidate}",
            )
            if os.path.isdir(attempt_staging):
                shutil.rmtree(attempt_staging, ignore_errors=True)
            label = UPDATE_SOURCE_LABELS.get(candidate, candidate)
            print(f"[update] trying source [{idx + 1}/{len(source_order)}] {label} ({candidate}) -> {attempt_staging}")
            try:
                root_files, static_files, files = stage_update_from_source(candidate, attempt_staging)
                source = candidate
                staging_root = attempt_staging
                fallback_used = idx > 0
                print(f"[update] source {label} succeeded, {len(files or [])} files")
                break
            except Exception as exc:
                if os.path.isdir(attempt_staging):
                    shutil.rmtree(attempt_staging, ignore_errors=True)
                print(f"[update] source {label} failed: {exc}")
                traceback.print_exc()
                download_errors.append(f"{label}: {exc}")
        if not staging_root:
            detail = "; ".join(download_errors) or "unknown error"
            print(f"[update] all sources failed -> {detail}")
            raise UpdateDownloadError(f"all download sources failed -> {detail}")

        updated = []
        for rel in root_files:
            target = safe_update_target(rel)
            if os.path.exists(target):
                backup_path = os.path.join(backup_root, *rel.split("/"))
                os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                shutil.copy2(target, backup_path)

        staged_static_dir = os.path.join(staging_root, "static")
        if not os.path.isdir(staged_static_dir):
            raise RuntimeError("staged static directory missing; update canceled")
        static_dir = safe_static_dir()
        backup_static_dir = os.path.join(backup_root, "static")
        if os.path.isdir(static_dir):
            os.makedirs(os.path.dirname(backup_static_dir), exist_ok=True)
            shutil.copytree(static_dir, backup_static_dir)
            shutil.rmtree(static_dir)
        try:
            shutil.copytree(staged_static_dir, static_dir)
        except Exception:
            if os.path.isdir(static_dir):
                shutil.rmtree(static_dir, ignore_errors=True)
            if os.path.isdir(backup_static_dir):
                shutil.copytree(backup_static_dir, static_dir)
            raise
        updated.extend(static_files)

        replaced_root_files = []
        try:
            for rel in root_files:
                target = safe_update_target(rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                temp_path = f"{target}.update_tmp"
                shutil.copy2(os.path.join(staging_root, *rel.split("/")), temp_path)
                os.replace(temp_path, target)
                replaced_root_files.append(rel)
                updated.append(rel)
        except Exception:
            for rel in reversed(replaced_root_files):
                backup_path = os.path.join(backup_root, *rel.split("/"))
                target = safe_update_target(rel)
                if os.path.exists(backup_path):
                    temp_path = f"{target}.rollback_tmp"
                    shutil.copy2(backup_path, temp_path)
                    os.replace(temp_path, target)
            if os.path.isdir(static_dir):
                shutil.rmtree(static_dir, ignore_errors=True)
            if os.path.isdir(backup_static_dir):
                shutil.copytree(backup_static_dir, static_dir)
            raise

        restart_scheduled = False
        if auto_restart and updated:
            restart_scheduled = schedule_self_restart(restart_delay)
        new_version = ""
        try:
            staged_version = os.path.join(staging_root, "VERSION")
            if os.path.exists(staged_version):
                with open(staged_version, "r", encoding="utf-8") as f:
                    new_version = (f.read().strip().splitlines() or [""])[0].strip()
        except Exception:
            new_version = ""
        notes_file = os.path.join(staging_root, "static", "update-notes.json")
        update_notes = {}
        try:
            if os.path.exists(notes_file):
                with open(notes_file, "r", encoding="utf-8") as f:
                    update_notes = safe_update_notes(json.load(f), new_version)
        except Exception:
            update_notes = {}
        return {
            "ok": True,
            "source": source,
            "source_label": UPDATE_SOURCE_LABELS.get(source, source),
            "requested_source": requested_source,
            "fallback_used": fallback_used,
            "download_errors": download_errors,
            "updated": updated,
            "count": len(updated),
            "version": new_version,
            "update_notes": update_notes,
            "backup_dir": backup_root if os.path.exists(backup_root) else "",
            "restart_required": True,
            "restart_scheduled": restart_scheduled,
        }
    finally:
        if staging_root and os.path.isdir(staging_root):
            shutil.rmtree(staging_root, ignore_errors=True)


def list_update_backups(data_dir: str) -> List[Dict[str, Any]]:
    root = os.path.join(data_dir, "update_backups")
    if not os.path.isdir(root):
        return []
    items = []
    for name in sorted(os.listdir(root), reverse=True):
        backup_path = os.path.join(root, name)
        if not os.path.isdir(backup_path):
            continue
        file_count = 0
        for _, _, filenames in os.walk(backup_path):
            file_count += len(filenames)
        try:
            created_at = os.path.getmtime(backup_path)
        except OSError:
            created_at = 0.0
        items.append({
            "name": name,
            "file_count": file_count,
            "created_at": created_at,
        })
    return items


def rollback_update_backup(
    *,
    data_dir: str,
    backup_name: str,
    auto_restart: bool,
    restart_delay: int,
    safe_static_dir,
    safe_update_target,
    schedule_self_restart,
) -> Dict[str, Any]:
    backup_root_abs = os.path.abspath(os.path.join(data_dir, "update_backups"))
    backup_dir = os.path.abspath(os.path.join(backup_root_abs, backup_name))
    if os.path.commonpath([backup_root_abs, backup_dir]) != backup_root_abs:
        raise BackupValidationError("unsafe backup path")
    if not os.path.isdir(backup_dir):
        raise BackupNotFoundError("backup not found")

    restored = []
    skipped = []
    backup_static_dir = os.path.join(backup_dir, "static")
    if os.path.isdir(backup_static_dir):
        static_dir = safe_static_dir()
        if os.path.isdir(static_dir):
            shutil.rmtree(static_dir)
        try:
            shutil.copytree(backup_static_dir, static_dir)
        except Exception:
            if os.path.isdir(static_dir):
                shutil.rmtree(static_dir, ignore_errors=True)
            raise
        for dirpath, _, filenames in os.walk(backup_static_dir):
            for filename in filenames:
                src = os.path.join(dirpath, filename)
                restored.append(os.path.relpath(src, backup_dir).replace("\\", "/"))

    for dirpath, _, filenames in os.walk(backup_dir):
        for filename in filenames:
            src = os.path.join(dirpath, filename)
            rel = os.path.relpath(src, backup_dir).replace("\\", "/")
            if rel.startswith("static/"):
                continue
            if not update_allowed_file(rel):
                skipped.append(rel)
                continue
            try:
                target = safe_update_target(rel)
            except ValueError:
                skipped.append(rel)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            temp_path = f"{target}.rollback_tmp"
            with open(src, "rb") as fin, open(temp_path, "wb") as fout:
                shutil.copyfileobj(fin, fout)
            os.replace(temp_path, target)
            restored.append(rel)

    restart_scheduled = False
    if auto_restart and restored:
        restart_scheduled = schedule_self_restart(restart_delay)
    return {
        "ok": True,
        "restored": restored,
        "skipped": skipped,
        "count": len(restored),
        "restart_required": True,
        "restart_scheduled": restart_scheduled,
    }
