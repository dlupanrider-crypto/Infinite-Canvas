"""Application service and router dependency wiring."""

from __future__ import annotations

from typing import Any


def configure_application(namespace: dict[str, Any]) -> None:
    globals().update(namespace)
    configure_provider_runtime(globals())
    configure_attachments(globals())
    configure_cloud_media(globals())
    configure_api_orchestration(globals())
    configure_runtime_registry(globals())
    configure_prompt_catalog(globals())
    configure_update_transport(globals())
    configure_canvas_index(globals())
    configure_runtime_state(globals())
    app.add_exception_handler(JimengPendingError, jimeng_pending_exception_handler)

    configure_conversation_storage(
        conversation_dir=CONVERSATION_DIR,
        lock=CONVERSATION_LOCK,
    )
    configure_history_storage(
        history_path=HISTORY_FILE,
        lock=HISTORY_LOCK,
        resolve_output_file_fn=lambda url: output_file_from_url(url),
    )
    configure_history_routes(queue_status_fn=queue_status_for_client)
    configure_canvas_storage(
        canvas_dir=CANVAS_DIR,
        projects_path=PROJECTS_PATH,
        lock=CANVAS_LOCK,
        trash_retention_ms=CANVAS_TRASH_RETENTION_MS,
    )
    configure_canvas_routes(
        broadcast_canvas_updated_fn=lambda canvas_id, updated_at, client_id: manager.broadcast_canvas_updated(
            canvas_id,
            updated_at,
            client_id,
        ),
        now_ms_fn=lambda: now_ms(),
    )
    configure_runninghub_workflow_storage(
        workflow_store_path=RUNNINGHUB_WORKFLOW_STORE_FILE,
        data_dir=DATA_DIR,
    )
    configure_prompt_library_storage(
        prompt_library_path=PROMPT_LIBRARY_PATH,
        data_dir=DATA_DIR,
        now_ms_fn=lambda: now_ms(),
        name_sanitizer=lambda name, fallback="asset": sanitize_asset_name(name, fallback),
        builtin_templates_fn=lambda: builtin_prompt_templates(),
    )
    configure_prompt_library_routes(
        sanitize_name_fn=lambda name, fallback="asset": sanitize_asset_name(name, fallback),
        now_ms_fn=lambda: now_ms(),
    )
    configure_asset_library_storage(
        asset_library_path=ASSET_LIBRARY_PATH,
        data_dir=DATA_DIR,
        now_ms_fn=lambda: now_ms(),
        name_sanitizer=lambda name, fallback="asset": sanitize_asset_name(name, fallback),
        updated_callback=lambda updated_at: (
            asyncio.run_coroutine_threadsafe(
                manager.broadcast_asset_library_updated(int(updated_at)),
                GLOBAL_LOOP,
            )
            if GLOBAL_LOOP
            else None
        ),
    )
    configure_asset_library_routes(
        asset_root=ASSET_LIBRARY_DIR,
        sanitize_name_fn=lambda name, fallback="asset": sanitize_asset_name(name, fallback),
        unique_category_dir_fn=lambda library, name: unique_asset_category_dir(library, name),
        remove_item_file_fn=lambda item: remove_asset_library_file(item),
    )
    configure_asset_item_routes(
        add_item=lambda payload: add_asset_library_item(payload),
        batch_add=lambda payload: batch_add_asset_library_items(payload),
        rename=lambda item_id, payload: rename_asset_library_item(item_id, payload),
        classify=lambda payload: classify_asset_library_items(payload),
        register_avatar=lambda item_id, payload: register_asset_library_avatar(item_id, payload),
        avatar_status=lambda item_id, payload: check_asset_library_avatar(item_id, payload),
        delete=lambda item_id, library_id="": delete_asset_library_item(item_id, library_id),
        batch_delete=lambda payload: batch_delete_asset_library_items(payload),
        move=lambda payload: batch_move_asset_library_items(payload),
        crop=lambda payload: batch_crop_asset_library_items(payload),
    )
    configure_local_asset_routes(
        upload=lambda files, folder="": upload_local_assets(files, folder),
        import_urls=lambda payload: import_local_assets_from_urls(payload),
        list=lambda: list_local_assets(),
        create_folder=lambda payload, request: create_local_asset_folder(payload, request),
        rename_folder=lambda payload, request: rename_local_asset_folder(payload, request),
        rename_item=lambda payload, request: rename_local_asset_item(payload, request),
        delete=lambda payload, request: delete_local_assets(payload, request),
        move=lambda payload, request: move_local_assets(payload, request),
        caption=lambda payload: caption_local_assets(payload),
        classify=lambda payload: classify_local_assets(payload),
        save_caption=lambda payload: save_local_asset_caption(payload),
    )
    configure_shared_folder_storage(
        registry_path=SHARED_FOLDERS_FILE,
        data_dir=DATA_DIR,
        base_dir=BASE_DIR,
        lock=SHARED_FOLDERS_LOCK,
        media_kind_fn=lambda path: asset_library_media_kind(path),
        now_ms_fn=lambda: now_ms(),
    )
    configure_shared_folder_routes(
        sanitize_name_fn=lambda name, fallback="asset": sanitize_asset_name(name, fallback),
        content_type_fn=lambda path: content_type_for_path(path),
        make_asset_item_fn=lambda path, name, subdir: make_asset_library_item(
            path,
            name,
            subdir=subdir,
        ),
        classify_image_fn=lambda path: classify_asset_image_best_effort(path),
        resolve_local_file_fn=lambda url: output_file_from_url(url),
    )
    configure_provider_normalization(
        model_list_normalizer=lambda values: model_list_from_values(values),
        runninghub_entries_normalizer=lambda values, kind: normalize_runninghub_entries(values, kind),
        bad_request_factory=lambda detail: HTTPException(status_code=400, detail=detail),
        volcengine_base_url=VOLCENGINE_DEFAULT_BASE_URL,
        volcengine_project_name=VOLCENGINE_DEFAULT_PROJECT_NAME,
        volcengine_region=VOLCENGINE_DEFAULT_REGION,
        runninghub_base_url=RUNNINGHUB_DEFAULT_BASE_URL,
    )
    configure_provider_routing(
        default_ai_base_url_fn=lambda: AI_BASE_URL,
        runninghub_base_url=RUNNINGHUB_DEFAULT_BASE_URL,
    )
    configure_provider_registry(
        providers_path=API_PROVIDERS_FILE,
        data_dir=DATA_DIR,
        lock=GLOBAL_CONFIG_LOCK,
        default_providers_fn=lambda: default_api_providers(),
        normalize_provider_fn=lambda item: normalize_provider(item),
        merge_defaults_fn=lambda providers, **kwargs: merge_default_api_providers(providers, **kwargs),
        provider_key_value_fn=lambda provider_id: provider_env_key_value(provider_id),
        provider_key_env_fn=lambda provider_id: provider_key_env(provider_id),
        mask_secret_fn=lambda value: mask_secret(value),
        runninghub_overlay_fn=lambda provider: runninghub_provider_with_workflow_store(provider),
        runninghub_wallet_value_fn=lambda: runninghub_wallet_key_value(),
        runninghub_wallet_env_fn=lambda: runninghub_wallet_key_env(),
        volcengine_access_value_fn=lambda: volcengine_access_key_value(),
        volcengine_access_env_fn=lambda: volcengine_access_key_env(),
        volcengine_secret_value_fn=lambda: volcengine_secret_key_value(),
        volcengine_secret_env_fn=lambda: volcengine_secret_key_env(),
        default_volcengine_project_name=VOLCENGINE_DEFAULT_PROJECT_NAME,
        default_volcengine_region=VOLCENGINE_DEFAULT_REGION,
    )
    configure_provider_config_routes(
        preserve_runninghub_overrides_fn=lambda provider: preserve_runninghub_hidden_overrides(provider),
        reload_env_fn=lambda: reload_env_globals(),
    )
    configure_provider_probe_routes(
        test_connection_fn=lambda payload: test_provider_connection(payload),
        probe_async_fn=lambda payload: probe_async_endpoint(payload),
        fetch_from_payload_fn=lambda payload: fetch_upstream_models_from_payload(payload),
        fetch_saved_fn=lambda provider_id: fetch_upstream_models(provider_id),
    )
    configure_provider_probe_adapter(
        AGNES_DEFAULT_VIDEO_MODELS=AGNES_DEFAULT_VIDEO_MODELS,
        JIMENG_DEFAULT_IMAGE_MODELS=JIMENG_DEFAULT_IMAGE_MODELS,
        JIMENG_DEFAULT_VIDEO_MODELS=JIMENG_DEFAULT_VIDEO_MODELS,
        RUNNINGHUB_DEFAULT_BASE_URL=RUNNINGHUB_DEFAULT_BASE_URL,
        codex_models_payload=codex_models_payload,
        codex_status=codex_status,
        gemini_cli_models_payload=gemini_cli_models_payload,
        gemini_cli_status=gemini_cli_status,
        get_api_provider_exact=get_api_provider_exact,
        jimeng_status=jimeng_status,
        looks_like_html_response=looks_like_html_response,
        provider_env_key_value=provider_env_key_value,
        runninghub_models_payload=runninghub_models_payload,
        volcengine_provider_api_key=volcengine_provider_api_key,
    )
    configure_cli_adapters(
        BASE_DIR=BASE_DIR,
        CHAT_RATIO_SIZE_OPTIONS=CHAT_RATIO_SIZE_OPTIONS,
        CODEX_DEFAULT_CHAT_MODELS=CODEX_DEFAULT_CHAT_MODELS,
        CODEX_DEFAULT_IMAGE_MODELS=CODEX_DEFAULT_IMAGE_MODELS,
        GEMINI_CLI_DEFAULT_CHAT_MODELS=GEMINI_CLI_DEFAULT_CHAT_MODELS,
        GEMINI_CLI_DEFAULT_IMAGE_MODELS=GEMINI_CLI_DEFAULT_IMAGE_MODELS,
        MAX_HISTORY_MESSAGES=MAX_HISTORY_MESSAGES,
        ONLINE_IMAGE_REFERENCE_MAX=ONLINE_IMAGE_REFERENCE_MAX,
        OUTPUT_OUTPUT_DIR=OUTPUT_OUTPUT_DIR,
        jimeng_extract_json=jimeng_extract_json,
        model_list_from_values=model_list_from_values,
        normalize_gpt_image_2_size=normalize_gpt_image_2_size,
        output_file_from_url=output_file_from_url,
        output_url_for=output_url_for,
        parse_size_pair=parse_size_pair,
        read_api_env_value=read_api_env_value,
    )
    configure_jimeng_adapter(
        BASE_DIR=BASE_DIR,
        JIMENG_LOGIN_SESSION=JIMENG_LOGIN_SESSION,
        OUTPUT_OUTPUT_DIR=OUTPUT_OUTPUT_DIR,
        content_type_for_path=content_type_for_path,
        output_file_from_url=output_file_from_url,
        output_path_for=output_path_for,
        output_url_for=output_url_for,
        parse_size_pair=parse_size_pair,
        read_api_env_value=read_api_env_value,
        save_ai_image_to_output=save_ai_image_to_output,
        save_remote_video_to_output=save_remote_video_to_output,
    )
    configure_runninghub_adapter(
        ONLINE_IMAGE_REFERENCE_MAX=ONLINE_IMAGE_REFERENCE_MAX,
        OUTPUT_INPUT_DIR=OUTPUT_INPUT_DIR,
        OUTPUT_OUTPUT_DIR=OUTPUT_OUTPUT_DIR,
        RUNNINGHUB_DEFAULT_IMAGE_MODELS=RUNNINGHUB_DEFAULT_IMAGE_MODELS,
        RUNNINGHUB_DEFAULT_VIDEO_MODELS=RUNNINGHUB_DEFAULT_VIDEO_MODELS,
        RUNNINGHUB_FALLBACK_CHAT_MODELS=RUNNINGHUB_FALLBACK_CHAT_MODELS,
        RUNNINGHUB_FILE_HOST_REWRITES=RUNNINGHUB_FILE_HOST_REWRITES,
        RUNNINGHUB_LLM_MODELS_URLS=RUNNINGHUB_LLM_MODELS_URLS,
        RUNNINGHUB_MODEL_ENDPOINT_ALIASES=RUNNINGHUB_MODEL_ENDPOINT_ALIASES,
        RUNNINGHUB_MODEL_REGISTRY_URL=RUNNINGHUB_MODEL_REGISTRY_URL,
        RUNNINGHUB_WORKFLOW_LOCK=RUNNINGHUB_WORKFLOW_LOCK,
        STATIC_RUNNINGHUB_MODEL_REGISTRY_FILE=STATIC_RUNNINGHUB_MODEL_REGISTRY_FILE,
        VIDEO_POLL_TIMEOUT=VIDEO_POLL_TIMEOUT,
        content_type_for_path=content_type_for_path,
        extract_image=extract_image,
        get_api_provider_exact=get_api_provider_exact,
        looks_like_html_response=looks_like_html_response,
        output_file_from_url=output_file_from_url,
        output_path_for=output_path_for,
        output_url_for=output_url_for,
        parse_size_pair=parse_size_pair,
        save_remote_video_to_output=save_remote_video_to_output,
        video_output_urls=video_output_urls,
    )
    configure_image_adapter(
        AI_BASE_URL=AI_BASE_URL,
        AI_REQUEST_TIMEOUT=AI_REQUEST_TIMEOUT,
        GPT_IMAGE2_MAX_EDGE=GPT_IMAGE2_MAX_EDGE,
        GPT_IMAGE2_MAX_PIXELS=GPT_IMAGE2_MAX_PIXELS,
        GPT_IMAGE2_MIN_PIXELS=GPT_IMAGE2_MIN_PIXELS,
        IMAGE_POLL_INTERVAL=IMAGE_POLL_INTERVAL,
        ONLINE_IMAGE_REFERENCE_MAX=ONLINE_IMAGE_REFERENCE_MAX,
        api_headers=api_headers,
        content_type_for_path=content_type_for_path,
        extract_image=extract_image,
        extract_task_id=extract_task_id,
        get_api_provider=get_api_provider,
        httpx_request_with_transient_retries=httpx_request_with_transient_retries,
        images_api_unsupported=images_api_unsupported,
        modelscope_api_key=modelscope_api_key,
        modelscope_image_api_root=modelscope_image_api_root,
        modelscope_image_url=modelscope_image_url,
        openai_video_proxy_public_reference_url=openai_video_proxy_public_reference_url,
        parse_size_pair=parse_size_pair,
        post_openai_responses=post_openai_responses,
        reference_to_data_url=reference_to_data_url,
        responses_image_size_instruction=responses_image_size_instruction,
        responses_input_image_url=responses_input_image_url,
        responses_no_image_detail=responses_no_image_detail,
        responses_output_text_image=responses_output_text_image,
        responses_proxy_tool_size=responses_proxy_tool_size,
        selected_model=selected_model,
        wait_for_image_task=wait_for_image_task,
    )
    configure_video_adapter(
        AI_BASE_URL=AI_BASE_URL,
        IMAGE_POLL_INTERVAL=IMAGE_POLL_INTERVAL,
        VIDEO_POLL_TIMEOUT=VIDEO_POLL_TIMEOUT,
        VIDEO_URL_KEYS=VIDEO_URL_KEYS,
        api_headers=api_headers,
        apimart_veo31_aspect=apimart_veo31_aspect,
        apimart_veo31_duration=apimart_veo31_duration,
        apimart_veo31_model=apimart_veo31_model,
        apimart_veo31_resolution=apimart_veo31_resolution,
        apimart_video_duration=apimart_video_duration,
        apimart_video_reference_error=apimart_video_reference_error,
        apply_trusted_asset_prompt_index=apply_trusted_asset_prompt_index,
        content_type_for_path=content_type_for_path,
        extract_task_id=extract_task_id,
        get_api_provider=get_api_provider,
        invalid_video_image_preview=invalid_video_image_preview,
        is_agnes_provider=is_agnes_provider,
        is_apimart_veo31_model=is_apimart_veo31_model,
        is_yuli_provider=is_yuli_provider,
        log_net_error=log_net_error,
        looks_like_image_media_url=looks_like_image_media_url,
        probe_local_audio_duration_seconds=probe_local_audio_duration_seconds,
        provider_env_key_value=provider_env_key_value,
        reference_to_data_url=reference_to_data_url,
        save_remote_video_to_output=save_remote_video_to_output,
        selected_model=selected_model,
        upload_audio_for_apimart=upload_audio_for_apimart,
        upload_image_for_apimart=upload_image_for_apimart,
        upload_local_video_to_cloud=upload_local_video_to_cloud,
        upload_video_for_apimart=upload_video_for_apimart,
        valid_apimart_video_image_input=valid_apimart_video_image_input,
        volcengine_content_role=volcengine_content_role,
        volcengine_media_reference_url=volcengine_media_reference_url,
        volcengine_video_duration=volcengine_video_duration,
        volcengine_video_reference_content_items=volcengine_video_reference_content_items,
        volcengine_video_resolution=volcengine_video_resolution,
    )
    configure_media_files(
        ASSETS_DIR=ASSETS_DIR,
        ASSET_LIBRARY_DIR=ASSET_LIBRARY_DIR,
        LOCAL_IMAGE_IMPORT_EXTS=LOCAL_IMAGE_IMPORT_EXTS,
        LOCAL_IMAGE_IMPORT_MAX_BYTES=LOCAL_IMAGE_IMPORT_MAX_BYTES,
        MEDIA_PREVIEW_DIR=MEDIA_PREVIEW_DIR,
        OUTPUT_DIR=OUTPUT_DIR,
        OUTPUT_INPUT_DIR=OUTPUT_INPUT_DIR,
        OUTPUT_OUTPUT_DIR=OUTPUT_OUTPUT_DIR,
        now_ms=now_ms,
        rewrite_runninghub_file_url=rewrite_runninghub_file_url,
        sanitize_asset_name=sanitize_asset_name,
        sanitize_export_filename=sanitize_export_filename,
    )
    configure_local_asset_service(
        LOCAL_UPLOAD_DIR=LOCAL_UPLOAD_DIR,
        _local_upload_classification_path=_local_upload_classification_path,
        _read_local_upload_classification=_read_local_upload_classification,
        _write_local_upload_classification=_write_local_upload_classification,
        caption_image_with_provider=caption_image_with_provider,
        classify_asset_image_best_effort=classify_asset_image_best_effort,
        classify_image_with_provider=classify_image_with_provider,
        sanitize_asset_name=sanitize_asset_name,
        upload_local_video_to_cloud=upload_local_video_to_cloud,
    )
    configure_chat_service(
        AI_REQUEST_TIMEOUT=AI_REQUEST_TIMEOUT,
        CHAT_ATTACHMENT_MAX=CHAT_ATTACHMENT_MAX,
        CODEX_DEFAULT_CHAT_MODELS=CODEX_DEFAULT_CHAT_MODELS,
        GEMINI_CLI_DEFAULT_CHAT_MODELS=GEMINI_CLI_DEFAULT_CHAT_MODELS,
        IMAGE_MODEL=IMAGE_MODEL,
        MAX_HISTORY_MESSAGES=MAX_HISTORY_MESSAGES,
        attachment_embedded_image_data_urls=attachment_embedded_image_data_urls,
        attachment_text_blocks=attachment_text_blocks,
        chat_prompt_size_override=chat_prompt_size_override,
        chat_system_prompt=chat_system_prompt,
        display_title=display_title,
        image_references=image_references,
        log_net_error=log_net_error,
        now_ms=now_ms,
        reference_to_data_url=reference_to_data_url,
        resolve_chat_provider=resolve_chat_provider,
        save_ai_image_to_output=save_ai_image_to_output,
        selected_model=selected_model,
        text_from_chat_response=text_from_chat_response,
        unwrap_apimart_response=unwrap_apimart_response,
    )
    configure_canvas_tool_service(
        ASSETS_DIR=ASSETS_DIR,
        BASE_DIR=BASE_DIR,
        OUTPUT_DIR=OUTPUT_DIR,
        OUTPUT_INPUT_DIR=OUTPUT_INPUT_DIR,
        asset_library_workflow_category=asset_library_workflow_category,
        builtin_prompt_templates=builtin_prompt_templates,
        canvas_assets_index=canvas_assets_index,
        fetch_remote_media_bytes=fetch_remote_media_bytes,
        filename_from_media_url=filename_from_media_url,
        local_media_file_by_basename=local_media_file_by_basename,
        make_workflow_library_item_from_bytes=make_workflow_library_item_from_bytes,
        now_ms=now_ms,
        output_file_from_url=output_file_from_url,
        prompt_template_markdown_path=prompt_template_markdown_path,
    )
    configure_asset_item_service(
        AI_REQUEST_TIMEOUT=AI_REQUEST_TIMEOUT,
        AVATAR_SUPPORTED_PLATFORMS=AVATAR_SUPPORTED_PLATFORMS,
        CODEX_DEFAULT_CHAT_MODELS=CODEX_DEFAULT_CHAT_MODELS,
        GEMINI_CLI_DEFAULT_CHAT_MODELS=GEMINI_CLI_DEFAULT_CHAT_MODELS,
        VIDEO_POLL_TIMEOUT=VIDEO_POLL_TIMEOUT,
        VOLCENGINE_DEFAULT_PROJECT_NAME=VOLCENGINE_DEFAULT_PROJECT_NAME,
        avatar_platform_for_provider=avatar_platform_for_provider,
        check_apimart_avatar_task=check_apimart_avatar_task,
        check_volcengine_avatar_task=check_volcengine_avatar_task,
        classify_asset_image_best_effort=classify_asset_image_best_effort,
        classify_image_with_provider=classify_image_with_provider,
        get_api_provider=get_api_provider,
        image_path_to_data_url=image_path_to_data_url,
        log_net_error=log_net_error,
        now_ms=now_ms,
        resolve_chat_provider=resolve_chat_provider,
        sanitize_asset_name=sanitize_asset_name,
        selected_model=selected_model,
        submit_apimart_avatar_asset=submit_apimart_avatar_asset,
        submit_volcengine_avatar_asset=submit_volcengine_avatar_asset,
        text_from_chat_response=text_from_chat_response,
        upload_media_for_apimart=upload_media_for_apimart,
        valid_apimart_video_image_input=valid_apimart_video_image_input,
        volcengine_public_asset_url=volcengine_public_asset_url,
    )
    configure_comfy_runtime(
        BACKEND_LOCAL_LOAD=BACKEND_LOCAL_LOAD,
        COMFYUI_DOWNLOAD_TIMEOUT=COMFYUI_DOWNLOAD_TIMEOUT,
        COMFYUI_INSTANCES=COMFYUI_INSTANCES,
        COMFY_DEBUG_TEXT_CLASS_HINTS=COMFY_DEBUG_TEXT_CLASS_HINTS,
        COMFY_PREVIEW_CLASS_HINTS=COMFY_PREVIEW_CLASS_HINTS,
        HISTORY_FILE=HISTORY_FILE,
        HISTORY_LOCK=HISTORY_LOCK,
        LOAD_LOCK=LOAD_LOCK,
        MEDIA_INPUT_EXT_RE=MEDIA_INPUT_EXT_RE,
        MEDIA_INPUT_KEYS=MEDIA_INPUT_KEYS,
        SYSTEM_PROMPT=SYSTEM_PROMPT,
        output_path_for=output_path_for,
        output_url_for=output_url_for,
        sanitize_export_filename=sanitize_export_filename,
    )
    configure_generation_service(
        BACKEND_LOCAL_LOAD=BACKEND_LOCAL_LOAD,
        CLIENT_ID=CLIENT_ID,
        COMFYUI_HISTORY_TIMEOUT=COMFYUI_HISTORY_TIMEOUT,
        COMFYUI_INSTANCES=COMFYUI_INSTANCES,
        GLOBAL_LOOP=GLOBAL_LOOP,
        LOAD_LOCK=LOAD_LOCK,
        NEXT_TASK_ID=NEXT_TASK_ID,
        QUEUE=QUEUE,
        QUEUE_LOCK=QUEUE_LOCK,
        WORKFLOW_DIR=WORKFLOW_DIR,
        WORKFLOW_PATH=WORKFLOW_PATH,
        collect_comfy_file_items=collect_comfy_file_items,
        collect_required_comfy_media=collect_required_comfy_media,
        comfy_class_is_debug_text=comfy_class_is_debug_text,
        comfy_class_is_preview=comfy_class_is_preview,
        comfy_output_kind=comfy_output_kind,
        comfy_text_values_from_output=comfy_text_values_from_output,
        convert_output_to_jpg=convert_output_to_jpg,
        download_comfy_output=download_comfy_output,
        get_comfy_history=get_comfy_history,
        manager=manager,
        modelscope_api_key=modelscope_api_key,
        modelscope_image_api_root=modelscope_image_api_root,
        modelscope_image_url=modelscope_image_url,
        modelscope_size=modelscope_size,
        output_path_for=output_path_for,
        output_url_for=output_url_for,
        reserve_best_backend=reserve_best_backend,
        save_comfy_text_output=save_comfy_text_output,
        save_to_history=save_to_history,
        selected_model=selected_model,
    )
    configure_runninghub_workflow_service(
        providers_path=API_PROVIDERS_FILE,
        default_base_url=RUNNINGHUB_DEFAULT_BASE_URL,
        default_apps=RUNNINGHUB_DEFAULT_APPS,
        load_static_provider_fn=lambda: load_static_runninghub_provider(),
        normalize_entry_fn=lambda entry, kind: normalize_runninghub_entry(entry, kind),
        normalize_entries_fn=lambda entries, kind: normalize_runninghub_entries(entries, kind),
        is_link_value_fn=lambda value: runninghub_is_workflow_link_value(value),
        infer_field_type_fn=lambda name, value: runninghub_infer_workflow_field_type(name, value),
        load_providers_fn=lambda: load_api_providers(),
        save_providers_fn=lambda providers: save_api_providers(providers),
        normalize_provider_fn=lambda provider: normalize_provider(provider),
        now_ms_fn=lambda: now_ms(),
    )
    configure_runninghub_routes(
        app_info=lambda webapp_id="": runninghub_app_info(webapp_id),
        submit=lambda payload: runninghub_submit(payload),
        workflow_submit=lambda payload: runninghub_workflow_submit(payload),
        workflow_info=lambda workflow_id="": runninghub_workflow_info(workflow_id),
        list_workflows=lambda: list_runninghub_workflows(),
        get_workflow=lambda workflow_id: get_runninghub_workflow(workflow_id),
        fetch_workflow=lambda payload: fetch_runninghub_workflow(payload),
        save_workflow=lambda workflow_id, payload: save_runninghub_workflow(workflow_id, payload),
        delete_workflow=lambda workflow_id: delete_runninghub_workflow(workflow_id),
        query=lambda task_id="": runninghub_query(task_id),
        upload_asset=lambda payload: runninghub_upload_asset(payload),
    )
    configure_cli_tool_routes(
        codex_status=lambda: codex_status(),
        codex_help=lambda payload: codex_help(payload),
        gemini_status=lambda: gemini_cli_status(),
        gemini_help=lambda payload: gemini_cli_help(payload),
        jimeng_status=lambda: jimeng_status(),
        jimeng_credit=lambda: jimeng_credit(),
        jimeng_logout=lambda: jimeng_logout(),
        jimeng_login_start=lambda: jimeng_login_start(),
        jimeng_login_status=lambda: jimeng_login_status(),
        jimeng_help=lambda payload: jimeng_help(payload),
        jimeng_query_media=lambda payload: jimeng_query_media(payload),
    )
    configure_media_routes(
        media_preview=lambda url, width=512: media_preview(url, width),
        image_jpeg=lambda url, width=0: image_jpeg(url, width),
        index=lambda: index(),
        view_image=lambda filename, media_type="input", subfolder="": view_image(
            filename,
            media_type,
            subfolder,
        ),
        download_output=lambda request, url, name="", inline=False: download_output(
            request,
            url,
            name,
            inline,
        ),
        upload_image=lambda files: upload_image(files),
        upload_ai_reference=lambda files: upload_ai_reference(files),
        upload_ai_base64=lambda payload: upload_ai_base64(payload),
        upload_comfyui_base64=lambda payload: upload_comfyui_base64(payload),
        temp_sh_upload=lambda payload, request: temp_sh_upload(payload, request),
        cloud_video_upload=lambda payload, request: cloud_video_upload(payload, request),
        import_local_ai_reference=lambda payload, request: import_local_ai_reference(
            payload,
            request,
        ),
    )
    configure_runtime_info_routes(
        config=lambda: ai_config(),
        models=lambda: ai_models(),
        token=lambda: get_global_token(),
    )
    configure_chat_routes(
        chat=lambda payload, request, user_id="": chat(payload, request, user_id),
        agent=lambda payload, request, user_id="": chat_agent(payload, request, user_id),
        stream=lambda payload, request, user_id="": chat_stream(payload, request, user_id),
    )
    configure_canvas_tool_routes(
        list_assets=lambda: list_canvas_assets(),
        prompt_templates=lambda: smart_canvas_prompt_templates(),
        check_assets=lambda payload: check_canvas_assets(payload),
        download_assets=lambda payload: download_canvas_assets(payload),
        export_workflow=lambda payload: export_canvas_workflow(payload),
        export_to_library=lambda payload: export_canvas_workflow_to_library(payload),
        upload_workflows=lambda files, library_id="", category_id="": upload_asset_library_workflows(
            files,
            library_id,
            category_id,
        ),
        import_workflow=lambda file: import_canvas_workflow(file),
        export_group=lambda payload: export_smart_canvas_group(payload),
    )
    configure_generation_routes(
        online_image=lambda payload: online_image(payload),
        query_image_task=lambda payload: query_image_task(payload),
        create_image_task=lambda payload: create_canvas_image_task(payload),
        get_image_task=lambda task_id: get_canvas_image_task(task_id),
        create_comfy_task=lambda payload: create_canvas_comfy_task(payload),
        get_comfy_task=lambda task_id: get_canvas_comfy_task(task_id),
        image_params=lambda provider_id="", model="": image_params(provider_id, model),
        canvas_video=lambda payload: canvas_video(payload),
        canvas_llm=lambda payload: canvas_llm(payload),
        poll_angle=lambda request: poll_angle_cloud(request),
        generate_angle=lambda request: generate_angle_cloud(request),
        generate_cloud=lambda request: generate_cloud(request),
        ms_generate=lambda request: ms_generate(request),
        generate=lambda request: generate(request),
    )
    configure_workflow_routes(
        workflow_dir=WORKFLOW_DIR,
        generate_request_factory=lambda **kwargs: GenerateRequest(**kwargs),
        generate_fn=lambda request: generate(request),
    )
    configure_comfyui_config_routes(
        get_instances_fn=lambda: list(COMFYUI_INSTANCES),
        set_instances_fn=apply_comfyui_instances,
        update_env_fn=lambda values: update_env_values(values),
    )
    configure_update_routes(
        current_version=lambda: current_app_version(),
        read_update_notes=read_local_update_notes,
        fetch_update_notes=fetch_update_notes_with_fallback,
        github_repo_url=GITHUB_REPO_URL,
        github_version_url=GITHUB_VERSION_URL,
        github_tree_url=GITHUB_TREE_URL,
        github_update_notes_url=GITHUB_UPDATE_NOTES_URL,
        modelscope_repo_url=MODELSCOPE_REPO_URL,
        modelscope_version_url=MODELSCOPE_VERSION_URL,
        modelscope_tree_url=MODELSCOPE_TREE_URL,
        modelscope_update_notes_url=MODELSCOPE_UPDATE_NOTES_URL,
        update_lock=UPDATE_LOCK,
        data_dir=DATA_DIR,
        stage_update_from_source=lambda source, staging_root: stage_update_from_source(source, staging_root),
        safe_update_target=lambda relative_path: safe_update_target(relative_path),
        safe_static_dir=lambda: safe_static_dir(),
        schedule_self_restart=lambda delay: schedule_self_restart(delay),
        safe_update_notes=lambda notes: safe_update_notes(notes),
    )
