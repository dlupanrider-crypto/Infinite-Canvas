"""Central imports and legacy export installation for application assembly."""

from __future__ import annotations

from typing import Any

from api_models import (
    AIReference,
    CanvasLLMRequest,
    CanvasVideoRequest,
    CloudGenRequest,
    CloudPollRequest,
    GenerateRequest,
    ImageTaskQueryRequest,
    MsGenerateRequest,
    OnlineImageRequest,
    TokenRequest,
)
from provider_adapters.probe import (
    classify_upstream_model,
    configure_provider_probe_adapter,
    fetch_models_from_upstream,
    fetch_upstream_models,
    fetch_upstream_models_from_payload,
    parse_upstream_models,
    probe_async_endpoint,
    test_provider_connection,
)
from provider_adapters.cli import (
    configure_cli_adapters,
    export_cli_adapter,
)
from provider_adapters.jimeng import (
    configure_jimeng_adapter,
    export_jimeng_adapter,
)
from provider_adapters.runninghub import (
    configure_runninghub_adapter,
    export_runninghub_adapter,
)
from provider_adapters.image import (
    configure_image_adapter,
    export_image_adapter,
)
from provider_adapters.video import (
    configure_video_adapter,
    export_video_adapter,
)
from app_services.media_files import (
    configure_media_files,
    export_media_files,
)
from app_services.local_assets import (
    configure_local_asset_service,
    export_local_asset_service,
)
from app_services.chat_service import (
    configure_chat_service,
    export_chat_service,
)
from app_services.canvas_tools import (
    configure_canvas_tool_service,
    export_canvas_tool_service,
)
from app_services.asset_items import (
    configure_asset_item_service,
    export_asset_item_service,
)
from app_services.generation_service import (
    configure_generation_service,
    export_generation_service,
)
from app_services.comfy_runtime import (
    configure_comfy_runtime,
    export_comfy_runtime,
)
from app_services.provider_runtime import (
    configure_provider_runtime,
    export_provider_runtime,
)
from app_services.attachments import (
    configure_attachments,
    export_attachments,
)
from app_services.cloud_media import (
    configure_cloud_media,
    export_cloud_media,
)
from app_services.api_orchestration import (
    configure_api_orchestration,
    export_api_orchestration,
)
from app_services.runtime_registry import (
    configure_runtime_registry,
    export_runtime_registry,
)
from app_services.prompt_catalog import (
    configure_prompt_catalog,
    export_prompt_catalog,
)
from app_services.update_transport import (
    configure_update_transport,
    export_update_transport,
)
from app_services.canvas_index import (
    configure_canvas_index,
    export_canvas_index,
)
from app_services.runtime_state import (
    configure_runtime_state,
    export_runtime_state,
)
from app_services.app_metadata import build_app_info
from app_services.env_config import (
    bearer_auth_value,
    configure_env_config,
    ensure_runtime_config_files,
    env_quote,
    load_env_file,
    mask_secret,
    provider_key_env,
    read_api_env_value,
    runninghub_wallet_key_env,
    strip_auth_scheme,
    update_env_values,
    volcengine_access_key_env,
    volcengine_secret_key_env,
)
from app_services.realtime import ConnectionManager, install_quiet_access_log_filter
from app_services.provider_normalization import (
    PER_MODEL_PROTOCOL_OPTIONS,
    SUPPORTED_PROVIDER_PROTOCOLS,
    apply_locked_recommended_model_rules,
    configure_provider_normalization,
    detect_image_request_mode,
    locked_recommended_provider_rule,
    normalize_endpoint_override,
    normalize_image_request_mode,
    normalize_model_protocols,
    normalize_ms_loras,
    normalize_provider,
)
from app_services.runninghub_workflows import (
    configure_runninghub_workflow_service,
    remove_runninghub_workflow_from_provider,
    runninghub_collect_workflow_fields,
    runninghub_is_saved_link_field,
    runninghub_normalize_field,
    runninghub_provider_with_workflow_store,
    runninghub_provider_workflow_config,
    runninghub_saved_hidden_workflow_ids,
    runninghub_select_workflow_config,
    runninghub_static_workflow_config,
    runninghub_workflow_config_has_payload,
    runninghub_workflow_entry_from_config,
    runninghub_workflow_store_key,
    sync_runninghub_workflow_to_provider,
)
from app_services.provider_routing import (
    configure_provider_routing,
    effective_image_request_mode,
    effective_protocol,
    is_apimart_provider,
    is_codex_provider,
    is_gemini_cli_provider,
    is_gemini_provider,
    is_jimeng_provider,
    is_runninghub_provider,
    is_volcengine_provider,
    provider_endpoint_url,
    provider_protocol,
    runninghub_endpoint_url,
    runninghub_openapi_base_url,
    runninghub_openapi_url,
)
from app_services.static_versioning import (
    configure_static_versioning,
    current_app_version,
    fetch_remote_update_notes,
    fetch_update_notes_with_fallback,
    read_local_update_notes,
    safe_update_notes,
    static_html_response,
    sync_static_html_versions,
    versioned_static_html,
)
from app_services.update_service import (
    UPDATE_SOURCE_LABELS,
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
    update_allowed_file,
    update_connectivity_targets,
)
from repositories.canvases import (
    DEFAULT_PROJECT_ID,
    canvas_path,
    canvas_record,
    cleanup_expired_canvas_trash,
    configure_canvas_storage,
    ensure_default_project,
    list_canvases,
    list_deleted_canvases,
    list_projects,
    load_canvas,
    load_canvas_any,
    load_projects,
    new_canvas,
    new_project,
    normalize_canvas_color,
    normalize_canvas_kind,
    project_record,
    save_canvas,
    save_projects,
)
from repositories.asset_library import (
    configure_asset_library_storage,
    default_asset_library,
    find_asset_category,
    find_asset_category_in_library,
    find_asset_category_with_library,
    find_asset_library,
    load_asset_library,
    normalize_asset_library,
    save_asset_library,
    sort_asset_library_items,
)
from repositories.prompt_libraries import (
    configure_prompt_library_storage,
    default_prompt_libraries,
    default_prompt_template_categories,
    find_prompt_library,
    load_prompt_libraries,
    normalize_prompt_category_id,
    normalize_prompt_libraries,
    normalize_prompt_library_item,
    normalize_prompt_template_categories,
    public_prompt_libraries,
    save_prompt_libraries,
    seed_system_prompt_library,
)
from repositories.provider_registry import (
    configure_provider_registry,
    load_api_providers,
    public_api_providers,
    public_provider,
    save_api_providers,
)
from repositories.runninghub_workflows import (
    configure_runninghub_workflow_storage,
    load_runninghub_workflow_store,
    runninghub_workflow_store_path,
    save_runninghub_workflow_store,
)
from repositories.shared_folders import configure_shared_folder_storage
from routers.workflows import (
    configure_workflow_routes,
    router as workflows_router,
)
from routers.comfyui_config import (
    configure_comfyui_config_routes,
    router as comfyui_config_router,
)
from routers.update import (
    configure_update_routes,
    router as update_router,
)
from routers.canvases import (
    configure_canvas_routes,
    router as canvases_router,
)
from routers.conversations import router as conversations_router
from routers.asset_library import (
    configure_asset_library_routes,
    router as asset_library_router,
)
from routers.prompt_libraries import (
    configure_prompt_library_routes,
    router as prompt_libraries_router,
)
from routers.provider_config import (
    configure_provider_config_routes,
    router as provider_config_router,
)
from routers.shared_folders import (
    configure_shared_folder_routes,
    router as shared_folders_router,
)
from routers.provider_probe import (
    TestConnectionPayload,
    configure_provider_probe_routes,
    router as provider_probe_router,
)
from routers.asset_items import (
    AssetAvatarRegisterRequest,
    AssetLibraryAddRequest,
    AssetLibraryBatchAddRequest,
    AssetLibraryBatchCropRequest,
    AssetLibraryBatchDeleteRequest,
    AssetLibraryBatchMoveRequest,
    AssetLibraryClassifyRequest,
    AssetLibraryRenameRequest,
    configure_asset_item_routes,
    router as asset_items_router,
)
from routers.local_assets import (
    LocalAssetCaptionRequest,
    LocalAssetCaptionSaveRequest,
    LocalAssetClassifyRequest,
    LocalAssetFolderRequest,
    LocalAssetRenameRequest,
    LocalAssetUrlImportItem,
    LocalAssetUrlImportRequest,
    configure_local_asset_routes,
    router as local_assets_router,
)
from routers.runninghub import (
    RunningHubSubmitRequest,
    RunningHubUploadAssetRequest,
    RunningHubWorkflowConfig,
    RunningHubWorkflowConfigField,
    RunningHubWorkflowSubmitRequest,
    configure_runninghub_routes,
    router as runninghub_router,
)
from routers.cli_tools import (
    CodexHelpRequest,
    GeminiCliHelpRequest,
    JimengHelpRequest,
    JimengQueryMediaRequest,
    configure_cli_tool_routes,
    router as cli_tools_router,
)
from routers.history import (
    configure_history_routes,
    router as history_router,
)
from routers.media import (
    Base64UploadRequest,
    CloudVideoUploadRequest,
    LocalImageImportRequest,
    TempShUploadRequest,
    configure_media_routes,
    router as media_router,
)
from routers.runtime_info import (
    configure_runtime_info_routes,
    router as runtime_info_router,
)
from routers.chat import (
    ChatRequest,
    configure_chat_routes,
    router as chat_router,
)
from routers.canvas_tools import (
    CanvasAssetCheckRequest,
    CanvasAssetDownloadRequest,
    CanvasWorkflowExportRequest,
    SmartCanvasGroupExportItem,
    SmartCanvasGroupExportRequest,
    configure_canvas_tool_routes,
    router as canvas_tools_router,
)
from routers.generation import (
    configure_generation_routes,
    router as generation_router,
)
from repositories.history import configure_history_storage
from repositories.conversations import (
    configure_conversation_storage,
    conversation_path,
    list_conversations,
    load_conversation,
    new_conversation,
    safe_user_id,
    save_conversation,
)

export_cli_adapter(globals())
export_jimeng_adapter(globals())
export_runninghub_adapter(globals())
export_image_adapter(globals())
export_video_adapter(globals())
export_media_files(globals())
export_local_asset_service(globals())
export_chat_service(globals())
export_canvas_tool_service(globals())
export_asset_item_service(globals())
export_generation_service(globals())
export_comfy_runtime(globals())
export_provider_runtime(globals())
export_attachments(globals())
export_cloud_media(globals())
export_api_orchestration(globals())
export_runtime_registry(globals())
export_prompt_catalog(globals())
export_update_transport(globals())
export_canvas_index(globals())
export_runtime_state(globals())

def install_dependencies(target: dict[str, Any]) -> None:
    for name, value in globals().items():
        if not name.startswith("__") and name not in {"Any", "install_dependencies"}:
            target[name] = value
