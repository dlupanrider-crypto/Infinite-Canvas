"""Application metadata and self-update routes."""

from __future__ import annotations

from threading import Lock
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app_services.app_metadata import build_app_info
from app_services.update_service import (
    BackupNotFoundError,
    BackupValidationError,
    UpdateDownloadError,
    apply_update_from_source,
    build_check_update_info,
    build_update_connectivity,
    list_update_backups,
    normalize_update_source,
    probe_update_connectivity_target,
    rollback_update_backup,
    update_connectivity_targets,
)


router = APIRouter(tags=["app-update"])
_config: dict[str, Any] = {}


def configure_update_routes(**config: Any) -> None:
    global _config
    _config = config


def _value(name: str) -> Any:
    if name not in _config:
        raise RuntimeError(f"Update routes missing configuration: {name}")
    return _config[name]


def _targets() -> list[dict[str, Any]]:
    return update_connectivity_targets(
        github_tree_url=_value("github_tree_url"),
        github_version_url=_value("github_version_url"),
        modelscope_version_url=_value("modelscope_version_url"),
        modelscope_repo_url=_value("modelscope_repo_url"),
    )


class UpdateRequest(BaseModel):
    auto_restart: bool = False
    restart_delay: int = 3
    source: str = "github"
    fallback: bool = True


class RollbackRequest(BaseModel):
    name: str = ""
    auto_restart: bool = False
    restart_delay: int = 3


@router.get("/api/app-info")
def app_info():
    return build_app_info(
        current_version=_value("current_version")(),
        read_update_notes=_value("read_update_notes"),
        github_repo_url=_value("github_repo_url"),
        github_version_url=_value("github_version_url"),
        github_tree_url=_value("github_tree_url"),
        github_update_notes_url=_value("github_update_notes_url"),
        modelscope_repo_url=_value("modelscope_repo_url"),
        modelscope_version_url=_value("modelscope_version_url"),
        modelscope_tree_url=_value("modelscope_tree_url"),
        modelscope_update_notes_url=_value("modelscope_update_notes_url"),
    )


@router.get("/api/update-connectivity/probe")
def update_connectivity_probe(name: str):
    item = probe_update_connectivity_target(name, _targets())
    if item:
        return item
    raise HTTPException(
        status_code=404,
        detail="\u672a\u77e5\u7684\u8fde\u901a\u6027\u68c0\u6d4b\u76ee\u6807",
    )


@router.get("/api/update-connectivity")
def update_connectivity():
    return build_update_connectivity(_targets())


@router.get("/api/check-update")
def check_update():
    return build_check_update_info(
        current=_value("current_version")(),
        github_version_url=_value("github_version_url"),
        modelscope_version_url=_value("modelscope_version_url"),
        fetch_update_notes=_value("fetch_update_notes"),
    )


@router.post("/api/update-from-github")
def update_from_github(request: UpdateRequest = UpdateRequest()):
    update_lock: Lock = _value("update_lock")
    if not update_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="\u6b63\u5728\u66f4\u65b0\u4e2d\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5",
        )
    try:
        return apply_update_from_source(
            data_dir=_value("data_dir"),
            requested_source=normalize_update_source(request.source),
            fallback=request.fallback,
            auto_restart=request.auto_restart,
            restart_delay=request.restart_delay,
            stage_update_from_source=_value("stage_update_from_source"),
            safe_update_target=_value("safe_update_target"),
            safe_static_dir=_value("safe_static_dir"),
            schedule_self_restart=_value("schedule_self_restart"),
            safe_update_notes=_value("safe_update_notes"),
        )
    except UpdateDownloadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"\u66f4\u65b0\u5931\u8d25\uff1a{exc}",
        ) from exc
    finally:
        update_lock.release()


@router.get("/api/update-backups")
def get_update_backups():
    return {"backups": list_update_backups(_value("data_dir"))}


@router.post("/api/update-rollback")
def rollback_update(request: RollbackRequest):
    if not request.name:
        raise HTTPException(status_code=400, detail="\u7f3a\u5c11\u5907\u4efd\u540d\u79f0")
    update_lock: Lock = _value("update_lock")
    if not update_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="\u6b63\u5728\u66f4\u65b0\u4e2d\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5",
        )
    try:
        return rollback_update_backup(
            data_dir=_value("data_dir"),
            backup_name=request.name,
            auto_restart=request.auto_restart,
            restart_delay=request.restart_delay,
            safe_static_dir=_value("safe_static_dir"),
            safe_update_target=_value("safe_update_target"),
            schedule_self_restart=_value("schedule_self_restart"),
        )
    except BackupValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BackupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"\u56de\u6eda\u5931\u8d25\uff1a{exc}",
        ) from exc
    finally:
        update_lock.release()
