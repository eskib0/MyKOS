"""Sub-paquete de servicios del núcleo del backend de MyKOS.

Aloja la gestión de actividades, el motor de benchmarks, la integración de
protocolos y los adaptadores de proveedores de modelos de lenguaje.
"""
from __future__ import annotations

from core.activity import (
    activity_public_view,
    finish_activity,
    start_activity,
    stop_llama_cpp_server,
    update_activity,
)
from core.benchmark import (
    BENCHMARK_OUTPUT_TOKENS,
    BENCHMARK_PROFILES,
    BENCHMARK_PROMPT,
    benchmark_profile_catalog,
    execute_benchmark_suite,
    run_model_benchmark,
)
from core.claude import (
    claude_auth_status,
    claude_executable_path,
    claude_model_summary,
    claude_prompt_from_messages,
    claude_tool_protocol_prompt,
    claude_unverified_tool_claim_reason,
    logout_claude,
    parse_claude_response,
    run_claude_cli,
    start_claude_login,
    verified_tool_ledger_for_prompt,
)
from core.providers import (
    _logout_anthropic,
    _logout_antigravity,
    _logout_gemini,
    _logout_grok,
    _logout_kimi,
    _logout_mistral,
    _logout_nvidia,
    gemini_model_catalog,
    grok_model_catalog,
    kimi_model_catalog,
    logout_meta_ai,
    logout_openrouter,
    meta_ai_model_catalog,
    mistral_model_catalog,
    nvidia_model_catalog,
    openrouter_model_catalog,
    refresh_anthropic_models,
    refresh_antigravity_models,
    refresh_gemini_models,
    refresh_grok_models,
    refresh_kimi_models,
    refresh_meta_ai_models,
    refresh_mistral_models,
    refresh_nvidia_models,
    refresh_openrouter_models,
    start_grok_login,
    start_meta_ai_login,
    start_openrouter_login,
)
from core.integrity import (
    INTEGRITY_GUARD_MESSAGE,
    INTEGRITY_UNVERIFIED_NOTE,
    MAX_INTEGRITY_GUARD_RETRIES,
    MAX_VERIFIED_TOOL_TRACE,
    current_turn_tool_trace,
    inline_verified_ledger,
    integrity_check_answer,
    unverified_action_claim_reason,
)
from core.uploads import (
    ALLOWED_UPLOAD_EXTENSIONS,
    MAX_UPLOAD_FILES,
    MAX_UPLOAD_REQUEST_BYTES,
    UPLOAD_RETENTION_SECONDS,
    cleanup_uploads,
    process_multipart_uploads,
)
from core.ollama_catalog import (
    OLLAMA_CATALOG_MAX_BYTES,
    OLLAMA_CATALOG_TIMEOUT_SECONDS,
    OLLAMA_LIBRARY_URL,
    fetch_ollama_catalog,
    get_ollama_job,
    job_public,
    run_ollama_pull_job,
    set_ollama_job,
)
from core.runners import (
    GEMINI_RESPONSE_SCHEMA,
    execute_openai_json_tool_loop,
    has_message_images,
    parse_gemini_response,
)
