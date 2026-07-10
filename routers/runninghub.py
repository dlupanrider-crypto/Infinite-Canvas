"""RunningHub task, workflow, and upload routes."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/runninghub", tags=["runninghub"])
_handlers: dict[str, Callable[..., Awaitable[Any]]] = {}


def configure_runninghub_routes(**handlers: Callable[..., Awaitable[Any]]) -> None:
    global _handlers
    _handlers = handlers


def _handler(name: str) -> Callable[..., Awaitable[Any]]:
    handler = _handlers.get(name)
    if handler is None:
        raise RuntimeError(f"RunningHub route handler is not configured: {name}")
    return handler


class RunningHubSubmitRequest(BaseModel):
    webappId: str = ""
    nodeInfoList: List[Dict[str, Any]] = Field(default_factory=list)
    instanceType: str = ""
    useWallet: bool = False


class RunningHubWorkflowSubmitRequest(BaseModel):
    workflowId: str = ""
    nodeInfoList: List[Dict[str, Any]] = Field(default_factory=list)
    workflow: Any = None
    useWallet: bool = False


class RunningHubUploadAssetRequest(BaseModel):
    url: str = ""
    useWallet: bool = False


class RunningHubWorkflowConfigField(BaseModel):
    id: str = ""
    nodeId: str = ""
    fieldName: str = ""
    fieldValue: str = ""
    fieldType: str = "TEXT"
    label: str = ""
    enabled: bool = True
    sourceFromUpstream: bool = True
    group: str = ""
    note: str = ""
    options: List[str] = Field(default_factory=list)
    random_enabled: bool = False
    min: Any = ""
    max: Any = ""
    step: Any = ""
    imageOrder: int = 0
    required: bool = False


class RunningHubWorkflowConfig(BaseModel):
    workflowId: str = ""
    title: str = ""
    description: str = ""
    fields: List[RunningHubWorkflowConfigField] = Field(default_factory=list)
    workflowJson: Dict[str, Any] = Field(default_factory=dict)
    optionalImageMode: str = "prune-workflow"
    raw: Dict[str, Any] = Field(default_factory=dict)


@router.get("/app-info")
async def runninghub_app_info(webappId: str = ""):
    return await _handler("app_info")(webappId)


@router.post("/submit")
async def runninghub_submit(payload: RunningHubSubmitRequest):
    return await _handler("submit")(payload)


@router.post("/workflow-submit")
async def runninghub_workflow_submit(payload: RunningHubWorkflowSubmitRequest):
    return await _handler("workflow_submit")(payload)


@router.get("/workflow-info")
async def runninghub_workflow_info(workflowId: str = ""):
    return await _handler("workflow_info")(workflowId)


@router.get("/workflows")
async def list_runninghub_workflows():
    return await _handler("list_workflows")()


@router.get("/workflows/{workflow_id:path}")
async def get_runninghub_workflow(workflow_id: str):
    return await _handler("get_workflow")(workflow_id)


@router.post("/workflows/fetch")
async def fetch_runninghub_workflow(payload: RunningHubWorkflowConfig):
    return await _handler("fetch_workflow")(payload)


@router.put("/workflows/{workflow_id:path}")
async def save_runninghub_workflow(
    workflow_id: str,
    payload: RunningHubWorkflowConfig,
):
    return await _handler("save_workflow")(workflow_id, payload)


@router.delete("/workflows/{workflow_id:path}")
async def delete_runninghub_workflow(workflow_id: str):
    return await _handler("delete_workflow")(workflow_id)


@router.get("/query")
async def runninghub_query(taskId: str = ""):
    return await _handler("query")(taskId)


@router.post("/upload-asset")
async def runninghub_upload_asset(payload: RunningHubUploadAssetRequest):
    return await _handler("upload_asset")(payload)
