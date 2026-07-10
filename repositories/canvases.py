import json
import os
import re
import time
import uuid

from fastapi import HTTPException


DEFAULT_PROJECT_ID = "default"
CANVAS_COLORS = {"", "red", "orange", "amber", "green", "teal", "blue", "violet", "pink", "slate"}

_CANVAS_DIR = ""
_PROJECTS_PATH = ""
_CANVAS_LOCK = None
_CANVAS_TRASH_RETENTION_MS = 0


def configure_canvas_storage(canvas_dir, projects_path, lock, trash_retention_ms):
    global _CANVAS_DIR, _PROJECTS_PATH, _CANVAS_LOCK, _CANVAS_TRASH_RETENTION_MS
    _CANVAS_DIR = canvas_dir
    _PROJECTS_PATH = projects_path
    _CANVAS_LOCK = lock
    _CANVAS_TRASH_RETENTION_MS = trash_retention_ms


def _now_ms():
    return int(time.time() * 1000)


def canvas_path(canvas_id):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", canvas_id or "")
    if not cleaned:
        raise HTTPException(status_code=400, detail="无效的画布 ID")
    return os.path.join(_CANVAS_DIR, f"{cleaned}.json")


def save_canvas(canvas):
    canvas["updated_at"] = _now_ms()
    with _CANVAS_LOCK:
        with open(canvas_path(canvas["id"]), "w", encoding="utf-8") as f:
            json.dump(canvas, f, ensure_ascii=False, indent=2)


def normalize_canvas_kind(kind="classic"):
    return "smart" if str(kind or "").strip().lower() == "smart" else "classic"


def load_projects():
    try:
        with open(_PROJECTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        projects = data.get("projects") if isinstance(data, dict) else data
        if isinstance(projects, list):
            return [p for p in projects if isinstance(p, dict) and p.get("id")]
    except Exception:
        pass
    return []


def save_projects(projects):
    with _CANVAS_LOCK:
        with open(_PROJECTS_PATH, "w", encoding="utf-8") as f:
            json.dump({"projects": projects}, f, ensure_ascii=False, indent=2)


def update_project(project_id, *, name=None, order=None):
    projects = ensure_default_project()
    target = next((project for project in projects if project.get("id") == project_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="\u9879\u76ee\u4e0d\u5b58\u5728")
    if name is not None:
        target["name"] = (str(name).strip() or target.get("name") or "\u672a\u547d\u540d\u9879\u76ee")[:60]
    if order is not None:
        target["order"] = int(order)
    target["updated_at"] = _now_ms()
    save_projects(projects)
    return project_record(target)


def delete_project_and_reassign(project_id):
    if project_id == DEFAULT_PROJECT_ID:
        raise HTTPException(status_code=400, detail="\u9ed8\u8ba4\u9879\u76ee\u4e0d\u53ef\u5220\u9664")
    projects = ensure_default_project()
    if not any(project.get("id") == project_id for project in projects):
        raise HTTPException(status_code=404, detail="\u9879\u76ee\u4e0d\u5b58\u5728")
    save_projects([project for project in projects if project.get("id") != project_id])
    moved = 0
    with _CANVAS_LOCK:
        for filename in os.listdir(_CANVAS_DIR):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(_CANVAS_DIR, filename)
            try:
                with open(path, "r", encoding="utf-8") as canvas_file:
                    data = json.load(canvas_file)
            except Exception:
                continue
            if str(data.get("project") or "") != project_id:
                continue
            data["project"] = DEFAULT_PROJECT_ID
            with open(path, "w", encoding="utf-8") as canvas_file:
                json.dump(data, canvas_file, ensure_ascii=False, indent=2)
            moved += 1
    return moved


def project_record(p):
    return {
        "id": p.get("id"),
        "name": (p.get("name") or "未命名项目")[:60],
        "order": int(p.get("order") or 0),
        "created_at": p.get("created_at", 0),
        "updated_at": p.get("updated_at", 0),
    }


def ensure_default_project():
    projects = load_projects()
    changed = False
    if not any(p.get("id") == DEFAULT_PROJECT_ID for p in projects):
        ts = _now_ms()
        projects.insert(0, {"id": DEFAULT_PROJECT_ID, "name": "默认项目", "order": 0, "created_at": ts, "updated_at": ts})
        changed = True
    if changed:
        save_projects(projects)
    return projects


def new_project(name="新项目"):
    projects = ensure_default_project()
    ts = _now_ms()
    clean = (str(name or "").strip() or "新项目")[:60]
    order = max([int(p.get("order") or 0) for p in projects], default=0) + 1
    proj = {"id": uuid.uuid4().hex, "name": clean, "order": order, "created_at": ts, "updated_at": ts}
    projects.append(proj)
    save_projects(projects)
    return proj


def list_projects():
    projects = ensure_default_project()
    counts = {}
    for rec in iter_canvas_records(include_deleted=False):
        pid = rec.get("project") or DEFAULT_PROJECT_ID
        counts[pid] = counts.get(pid, 0) + 1
    out = []
    for p in sorted(projects, key=lambda x: (int(x.get("order") or 0), x.get("created_at") or 0)):
        rec = project_record(p)
        rec["canvas_count"] = counts.get(rec["id"], 0)
        out.append(rec)
    return out


def new_canvas(title="未命名画布", icon="layers", kind="classic", project=None, board_x=None, board_y=None):
    timestamp = _now_ms()
    canvas_kind = normalize_canvas_kind(kind)
    canvas = {
        "id": uuid.uuid4().hex,
        "title": (title or ("智能画布" if canvas_kind == "smart" else "未命名画布"))[:80],
        "icon": (icon or ("sparkles" if canvas_kind == "smart" else "layers"))[:32],
        "kind": canvas_kind,
        "owner": "",
        "color": "",
        "pinned": False,
        "project": str(project or "").strip() or DEFAULT_PROJECT_ID,
        "created_at": timestamp,
        "updated_at": timestamp,
        "nodes": [],
        "connections": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }
    if board_x is not None:
        canvas["board_x"] = float(board_x)
    if board_y is not None:
        canvas["board_y"] = float(board_y)
    save_canvas(canvas)
    return canvas


def load_canvas(canvas_id):
    path = canvas_path(canvas_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="画布不存在")
    with open(path, "r", encoding="utf-8") as f:
        canvas = json.load(f)
    if canvas.get("deleted_at"):
        raise HTTPException(status_code=404, detail="画布已在回收站")
    return canvas


def load_canvas_any(canvas_id):
    path = canvas_path(canvas_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="画布不存在")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_canvas_color(value):
    color = str(value or "").strip().lower()
    return color if color in CANVAS_COLORS else ""


def canvas_record(data):
    return {
        "id": data.get("id"),
        "title": data.get("title", "未命名画布"),
        "icon": data.get("icon", "layers"),
        "kind": normalize_canvas_kind(data.get("kind")),
        "owner": str(data.get("owner") or "")[:40],
        "color": normalize_canvas_color(data.get("color")),
        "pinned": bool(data.get("pinned") or False),
        "project": str(data.get("project") or "").strip() or DEFAULT_PROJECT_ID,
        "board_x": data.get("board_x"),
        "board_y": data.get("board_y"),
        "created_at": data.get("created_at", 0),
        "updated_at": data.get("updated_at", 0),
        "deleted_at": data.get("deleted_at", 0),
        "node_count": len(data.get("nodes", [])),
    }


def update_canvas_metadata(canvas_id, **changes):
    canvas = load_canvas(canvas_id)
    if changes.get("title") is not None:
        canvas["title"] = (changes["title"] or canvas.get("title") or "\u672a\u547d\u540d\u753b\u5e03")[:80]
    if changes.get("icon") is not None:
        canvas["icon"] = (changes["icon"] or "layers")[:32]
    if changes.get("owner") is not None:
        canvas["owner"] = str(changes["owner"]).strip()[:40]
    if changes.get("color") is not None:
        canvas["color"] = normalize_canvas_color(changes["color"])
    if changes.get("pinned") is not None:
        canvas["pinned"] = bool(changes["pinned"])
    if changes.get("project") is not None:
        canvas["project"] = str(changes["project"]).strip() or DEFAULT_PROJECT_ID
    if changes.get("board_x") is not None:
        canvas["board_x"] = float(changes["board_x"])
    if changes.get("board_y") is not None:
        canvas["board_y"] = float(changes["board_y"])
    with _CANVAS_LOCK:
        with open(canvas_path(canvas["id"]), "w", encoding="utf-8") as canvas_file:
            json.dump(canvas, canvas_file, ensure_ascii=False, indent=2)
    return canvas_record(canvas)


def soft_delete_canvas(canvas_id):
    canvas = load_canvas_any(canvas_id)
    if not canvas.get("deleted_at"):
        canvas["deleted_at"] = _now_ms()
        save_canvas(canvas)


def restore_canvas(canvas_id):
    canvas = load_canvas_any(canvas_id)
    if canvas.get("deleted_at"):
        canvas.pop("deleted_at", None)
        save_canvas(canvas)
    return canvas


def purge_canvas(canvas_id):
    path = canvas_path(canvas_id)
    with _CANVAS_LOCK:
        if os.path.exists(path):
            os.remove(path)


def cleanup_expired_canvas_trash():
    cutoff = _now_ms() - _CANVAS_TRASH_RETENTION_MS
    with _CANVAS_LOCK:
        for filename in os.listdir(_CANVAS_DIR):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(_CANVAS_DIR, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                deleted_at = int(data.get("deleted_at") or 0)
                if deleted_at and deleted_at < cutoff:
                    os.remove(path)
            except Exception:
                continue


def iter_canvas_records(include_deleted=False):
    cleanup_expired_canvas_trash()
    records = []
    for filename in os.listdir(_CANVAS_DIR):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(_CANVAS_DIR, filename), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        is_deleted = bool(data.get("deleted_at"))
        if include_deleted != is_deleted:
            continue
        records.append(canvas_record(data))
    return records


def list_canvases():
    records = iter_canvas_records(include_deleted=False)
    return sorted(
        records,
        key=lambda item: (
            0 if item.get("pinned") else 1,
            -int(item.get("updated_at") or item.get("created_at") or 0),
        ),
    )


def list_deleted_canvases():
    records = iter_canvas_records(include_deleted=True)
    return sorted(records, key=lambda item: item["deleted_at"], reverse=True)
