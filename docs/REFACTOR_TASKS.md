# Infinite Canvas Refactor Tasks

This document keeps the refactor staged and behavior-preserving. Each stage should compile and pass the lightweight regression check before the next stage starts.

## Completed

- Extract static versioning and update-notes helpers into `app_services/static_versioning.py`.
- Extract WebSocket connection management and quiet access-log filtering into `app_services/realtime.py`.
- Align `APP_VERSION` with `VERSION`.
- Add empty runtime data directories with `.gitkeep` files for `data/canvases/` and `data/conversations/`.
- Remove legacy static-versioning helper implementations from `main.py`.
- Extract app-info response construction into `app_services/app_metadata.py`.
- Extract pure update helpers into `app_services/update_service.py`.
- Extract update connectivity and check-update service logic into `app_services/update_service.py`.
- Extract update apply, backup listing, and rollback service logic into `app_services/update_service.py`.
- Extract env file, provider key, and auth-header helpers into `app_services/env_config.py`.
- Extract conversation JSON storage helpers into `repositories/conversations.py`.
- Extract canvas/project JSON storage helpers into `repositories/canvases.py`.
- Extract asset-library normalization, load/save, and lookup helpers into `repositories/asset_library.py`.
- Extract prompt-library normalization, load/save, and lookup helpers into `repositories/prompt_libraries.py`.
- Extract provider-registry persistence and public serialization into `repositories/provider_registry.py`.
- Extract provider normalization rules into `app_services/provider_normalization.py`.
- Extract RunningHub workflow JSON persistence into `repositories/runninghub_workflows.py`.
- Extract RunningHub workflow merge, sync, tombstone, and field rules into `app_services/runninghub_workflows.py`.
- Extract provider protocol detection and endpoint routing into `app_services/provider_routing.py`.
- Move local workflow CRUD/run endpoints into `routers/workflows.py`.
- Move ComfyUI instance configuration endpoints into `routers/comfyui_config.py`.
- Move app metadata, update check/apply/backup/rollback endpoints into `routers/update.py`.
- Move conversation endpoints into `routers/conversations.py`.
- Move canvas/project endpoints into `routers/canvases.py`.
- Move asset-library and category CRUD endpoints into `routers/asset_library.py`.
- Move prompt-library CRUD endpoints into `routers/prompt_libraries.py`.
- Move provider registry read/write endpoints into `routers/provider_config.py`.
- Extract shared-folder storage/path scanning into `repositories/shared_folders.py`.
- Move shared-folder registration, browsing, file, and import endpoints into `routers/shared_folders.py`.
- Move provider connectivity/model-discovery HTTP endpoints into `routers/provider_probe.py`.
- Move asset item operation HTTP endpoints and request models into `routers/asset_items.py`.
- Move local asset management HTTP endpoints and request models into `routers/local_assets.py`.
- Move RunningHub task/workflow/upload HTTP endpoints and request models into `routers/runninghub.py`.
- Move Codex, Gemini CLI, and Jimeng status/auth/help endpoints into `routers/cli_tools.py`.
- Extract generation history persistence into `repositories/history.py`.
- Move history and queue-status endpoints into `routers/history.py`.
- Move media preview/download/upload/import endpoints into `routers/media.py`.
- Move runtime config, model-list, and token endpoints into `routers/runtime_info.py`.
- Move chat, agent-chat, and streaming-chat endpoints into `routers/chat.py`.
- Move canvas asset and workflow import/export endpoints into `routers/canvas_tools.py`.
- Extract shared generation/canvas request models into `api_models.py`.
- Move all image/video/LLM/cloud generation HTTP endpoints into `routers/generation.py`.
- Extract provider connectivity probes and upstream model discovery into `provider_adapters/probe.py`.
- Extract Codex and Gemini CLI execution/image/chat adapters into `provider_adapters/cli.py`.
- Extract Jimeng CLI execution, media preparation, and result parsing into `provider_adapters/jimeng.py`.
- Extract RunningHub OpenAPI/model/schema/upload/generation logic into `provider_adapters/runninghub.py`.
- Extract media storage, previews, local import, and asset file operations into `app_services/media_files.py`.
- Extract common image-provider dispatch, size rules, and requests into `provider_adapters/image.py`.
- Extract video-provider polling, upload, and dispatch into `provider_adapters/video.py`.
- Extract local upload/import/tree/caption/classify operations into `app_services/local_assets.py`.
- Extract chat history, agent decisions, image generation, and streaming replies into `app_services/chat_service.py`.
- Extract canvas asset/archive/workflow/group-export operations into `app_services/canvas_tools.py`.
- Extract asset item add/classify/avatar/move/crop/delete operations into `app_services/asset_items.py`.

## Execution Plan

### Stage 1: Low-Risk Service Extraction

- Extract filesystem path/bootstrap helpers into a small runtime module.
- Keep `reload_env_globals` local until provider registry extraction.
- Keep all public API routes unchanged.

Exit criteria:

- `main.py` no longer owns cross-cutting helpers.
- New modules stay framework-light unless they are route modules.
- Regression check passes after every extraction.

### Stage 2: Storage Boundaries

- Extract conversation JSON storage helpers. Done.
- Extract canvas/project JSON storage helpers. Done.
- Extract asset-library JSON storage helpers. Core load/save/normalize/lookups done; file-copy and media import helpers remain local for now.
- Extract prompt-library JSON storage helpers. Done.
- Add small focused tests around load/save/list behavior before changing storage internals.

Exit criteria:

- JSON file paths and locks are centralized.
- Route handlers call repository-style functions.
- Storage internals can later move to SQLite without changing route payloads.

### Stage 3: Provider Boundaries

- Extract provider normalization and public-provider serialization. Done.
- Extract RunningHub app/workflow helpers. Workflow persistence, merge, sync, tombstones, and field rules done.
- Extract ModelScope and OpenAI-compatible request helpers.
- Extract ModelScope cloud generation and local ComfyUI task orchestration. Done.
- Extract shared provider protocol, attachment parsing, cloud media, and API orchestration. Done.
- Extract runtime registry, prompt catalog, update transport, canvas indexing, and queue state. Done.
- Keep provider payload shapes backwards compatible.

Exit criteria:

- Each provider family has a focused module.
- Shared request helpers and error normalization are reused.
- Existing configured providers continue to load without migration.

### Stage 4: Route Modules

- Introduce FastAPI routers after service boundaries are stable.
- Start with low-risk routers: app/update/config.
- Move business-heavy routers later: canvas/assets/chat/workflows.

Exit criteria:

- `main.py` only creates the app, mounts static folders, registers middleware, includes routers, and starts uvicorn. Done.
- Target `main.py` size: 300-800 lines. Done (783 lines).

### Stage 5: Performance Improvements

- Add short-lived cache for update checks.
- Parallelize WebSocket broadcasts safely.
- Add metadata index/cache for canvas lists.
- Add cache or database migration path for large asset libraries.

## Verification Checklist

- `python -m py_compile main.py app_services/*.py`
- `python scripts/regression_check.py --startup --data --frontend`
- Manual smoke test for the touched page/API path.
