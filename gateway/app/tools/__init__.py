"""Sub-paquete de herramientas y acciones de MyKOS.

Proporciona despacho centralizado de herramientas, acciones aprobables,
inspección del sistema, sistema de archivos, git, ollama, memoria y utilidades web.
Mantiene compatibilidad 100% hacia atrás reexportando todos los símbolos públicos.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from automations import (
    AutomationError,
    create_approved,
    delete_approved,
    list_automations,
    list_events,
    prepare_create,
    prepare_delete,
)
from browser import BrowserError, browser_close, browser_open, browser_snapshot
from management import local_status
from media import (
    MediaError,
    generate_image_approved,
    generate_video_approved,
    list_media,
    media_status,
    prepare_generate_image,
    prepare_generate_video,
    prepare_text_to_speech,
    text_to_speech_approved,
)
from nodes import NodeError, list_nodes, pair_node_approved, prepare_pair_node, prepare_revoke_node, revoke_node_approved
from embedding_memory import (
    remove as remove_memory_embedding,
    search as semantic_memory_search,
    status as memory_embedding_status,
    upsert as upsert_memory_embedding,
)
import gateway_store
from rea import (
    ReaError,
    rea_analyze_javascript,
    rea_call_tool,
    rea_inspect_binary,
    rea_list_tools,
    rea_status,
    resolve_rea_target,
)
from subagents import SubagentError, list_jobs, prepare_spawn, spawn_approved

# Primitivas base, constantes y rutas
from .base import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_ROOTS_FILE,
    ALLOWED_TEXT_EXTENSIONS,
    GIT_LOCK,
    GIT_MAX_COMMIT_MESSAGE_CHARS,
    GIT_MAX_LOG_ENTRIES,
    GIT_MAX_OUTPUT_CHARS,
    GIT_MAX_PATHS,
    GIT_REMOTE_TIMEOUT_SECONDS,
    IGNORED_PARTS,
    MAX_COMMAND_CHARS,
    MAX_COMMAND_TIMEOUT,
    MAX_DOCUMENT_TEXT_CHARS,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_LIST_ENTRIES,
    MAX_OCR_CHARS,
    MAX_OFFICE_BYTES,
    MAX_PATH_SEARCH_ENTRIES,
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    MAX_PROCESS_QUERY_CHARS,
    MAX_PROCESS_RESULTS,
    MAX_READ_BYTES,
    MAX_RESEARCH_KEY_POINTS,
    MAX_RESEARCH_QUERY_CHARS,
    MAX_RESEARCH_SOURCES,
    MAX_RESEARCH_SUMMARY_CHARS,
    MAX_RESEARCH_TITLE_CHARS,
    MAX_SEARCH_FILE_BYTES,
    MAX_SEARCH_FILES,
    MAX_SEARCH_RESULTS,
    MAX_SERVICE_NAME_CHARS,
    MAX_SERVICE_RESULTS,
    MAX_SPREADSHEET_ROWS,
    MAX_WRITE_BYTES,
    WEB_MAX_BYTES,
    WEB_MAX_RESULTS,
    WEB_MAX_TEXT_CHARS,
    WEB_REQUEST_TIMEOUT_SECONDS,
    WEB_USER_AGENT,
    MEMORY_CATEGORIES,
    MEMORY_FILE,
    MEMORY_LOCK,
    MEMORY_MAX_CONTENT_BYTES,
    MEMORY_MAX_ENTRIES,
    MEMORY_MAX_TAGS,
    MEMORY_MAX_TAG_CHARS,
    MEMORY_MAX_TITLE_CHARS,
    OLLAMA_LOCK,
    OLLAMA_MODEL_NAME_CHARS,
    OLLAMA_PULL_TIMEOUT_SECONDS,
    OLLAMA_REQUEST_TIMEOUT_SECONDS,
    OLLAMA_URL,
    PRIVATE_PATH_ROOTS,
    PROJECT_ROOT,
    ToolError,
    _is_ignored,
    _is_private_path,
    _load_allowed_roots,
    _relative_label,
    _resolve_project_path,
    _resolve_root,
    allowed_root_catalog,
    encode_tool_result,
)
from .documents import (
    _image_mime_type,
    _read_document,
    _read_image,
    _read_pdf,
    _resolve_read_file,
    _run_image_ocr,
)
from .filesystem import (
    _execute_edit_file,
    _execute_research_note,
    _execute_write_file,
    _find_project_paths,
    _list_project_files,
    _prepare_edit_project_file,
    _prepare_save_research_note,
    _prepare_write_project_file,
    _read_project_file,
    _research_slug,
    _search_project_files,
)
from .git_tools import (
    _execute_git_commit,
    _execute_git_remote_action,
    _git_current_branch,
    _git_diff,
    _git_diff_stat,
    _git_log,
    _git_pathspecs,
    _git_ref_name,
    _git_remote_name,
    _git_remote_status,
    _git_remote_url,
    _git_repository,
    _git_status,
    _git_status_changes,
    _git_status_state,
    _normalise_git_commit_message,
    _prepare_git_commit,
    _prepare_git_remote_action,
    _redact_git_text,
    _run_git,
)
from .memory import (
    _execute_delete_memory,
    _execute_save_memory,
    _find_memory_entry,
    _list_memory,
    _load_memory_store,
    _memory_now,
    _memory_summary,
    _normalise_memory_category,
    _normalise_memory_tags,
    _prepare_delete_memory,
    _prepare_save_memory,
    _read_memory,
    _save_memory_store,
    _search_memory,
    memory_catalog,
)
from .ollama import (
    _execute_delete_ollama_model,
    _execute_pull_ollama_model,
    _find_ollama_model,
    _list_ollama_models,
    _normalise_ollama_model_name,
    _ollama_model_summary,
    _ollama_request_json,
    _prepare_delete_ollama_model,
    _prepare_pull_ollama_model,
    execute_ollama_pull_with_progress,
)
from .schemas import (
    SENSITIVE_TOOL_NAMES,
    TOOL_SCHEMAS,
    tool_catalog,
)
from .shell import (
    _desktop_session_environment,
    _execute_run_powershell,
    _execute_run_shell_posix,
    _prepare_run_powershell,
    analyze_action_risk,
)
from .system import (
    PROTECTED_PROCESS_NAMES,
    SERVICE_START_TYPE_NAMES,
    SERVICE_STATUS_NAMES,
    _execute_service_action,
    _execute_stop_process,
    _find_service,
    _get_local_status,
    _get_psutil,
    _list_processes,
    _list_services,
    _normalise_service_name,
    _prepare_service_action,
    _prepare_stop_process,
    _process_record,
    _systemd_service_records,
)
from .web import (
    _DuckDuckGoLiteParser,
    _SafeRedirectHandler,
    _WebTextParser,
    _decode_search_url,
    _download_web_page,
    _validate_web_url,
    _web_fetch,
    _web_search,
)


def _prepare_rea_call_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(arguments.get("tool_name", "")).strip()
    tool_args = arguments.get("arguments") if isinstance(arguments.get("arguments"), dict) else {}
    if not tool_name:
        raise ToolError("Debes indicar el nombre de la herramienta de REA (tool_name).")
    return {
        "kind": "rea_call_tool",
        "tool_name": tool_name,
        "arguments": tool_args,
        "summary": f"Ejecutar herramienta REA · {tool_name}",
    }


def _list_allowed_roots() -> dict[str, Any]:
    return {"ok": True, "roots": allowed_root_catalog()}


def prepare_approval_action(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    arguments = arguments if isinstance(arguments, dict) else {}
    try:
        res: dict[str, Any]
        if name == "save_memory":
            res = {"ok": True, "action": _prepare_save_memory(arguments)}
        elif name == "delete_memory":
            res = {"ok": True, "action": _prepare_delete_memory(arguments)}
        elif name == "write_project_file":
            res = {"ok": True, "action": _prepare_write_project_file(arguments)}
        elif name == "edit_project_file":
            res = {"ok": True, "action": _prepare_edit_project_file(arguments)}
        elif name == "save_research_note":
            res = {"ok": True, "action": _prepare_save_research_note(arguments)}
        elif name == "run_powershell":
            res = {"ok": True, "action": _prepare_run_powershell(arguments)}
        elif name == "git_commit":
            res = {"ok": True, "action": _prepare_git_commit(arguments)}
        elif name == "git_remote_fetch":
            res = {"ok": True, "action": _prepare_git_remote_action(arguments, "git_remote_fetch")}
        elif name == "git_remote_pull":
            res = {"ok": True, "action": _prepare_git_remote_action(arguments, "git_remote_pull")}
        elif name == "git_remote_push":
            res = {"ok": True, "action": _prepare_git_remote_action(arguments, "git_remote_push")}
        elif name == "git_branch":
            res = {"ok": True, "action": _prepare_git_remote_action(arguments, "git_branch")}
        elif name == "pull_ollama_model":
            res = {"ok": True, "action": _prepare_pull_ollama_model(arguments)}
        elif name == "delete_ollama_model":
            res = {"ok": True, "action": _prepare_delete_ollama_model(arguments)}
        elif name == "stop_process":
            res = {"ok": True, "action": _prepare_stop_process(arguments)}
        elif name == "start_service":
            res = {"ok": True, "action": _prepare_service_action(arguments, "start_service", "stopped")}
        elif name == "stop_service":
            res = {"ok": True, "action": _prepare_service_action(arguments, "stop_service", "running")}
        elif name == "create_reminder":
            res = {"ok": True, "action": prepare_create(arguments)}
        elif name == "delete_reminder":
            res = {"ok": True, "action": prepare_delete(arguments)}
        elif name == "spawn_subagent":
            res = {"ok": True, "action": prepare_spawn(arguments)}
        elif name == "text_to_speech":
            res = {"ok": True, "action": prepare_text_to_speech(arguments)}
        elif name == "generate_image":
            res = {"ok": True, "action": prepare_generate_image(arguments)}
        elif name == "generate_video":
            res = {"ok": True, "action": prepare_generate_video(arguments)}
        elif name == "pair_node":
            res = {"ok": True, "action": prepare_pair_node(arguments)}
        elif name == "revoke_node":
            res = {"ok": True, "action": prepare_revoke_node(arguments)}
        elif name == "rea_call_tool":
            res = {"ok": True, "action": _prepare_rea_call_tool(arguments)}
        else:
            return {"ok": False, "error": f"No existe una acción aprobable llamada: {name}"}

        if res.get("ok") and isinstance(res.get("action"), dict):
            risk_level, risk_warning = analyze_action_risk(res["action"])
            res["action"]["risk_level"] = risk_level
            res["action"]["risk_warning"] = risk_warning
        return res
    except ToolError as error:
        return {"ok": False, "error": str(error)}
    except (OSError, RuntimeError) as error:
        return {"ok": False, "error": f"No se pudo preparar la acción: {error}"}


def execute_approved_action(action: dict[str, Any]) -> dict[str, Any]:
    try:
        kind = str(action.get("kind", ""))
        if kind == "save_memory":
            return _execute_save_memory(action)
        if kind == "delete_memory":
            return _execute_delete_memory(action)
        if kind == "write_file":
            return _execute_write_file(action)
        if kind == "edit_file":
            return _execute_edit_file(action)
        if kind == "research_note":
            return _execute_research_note(action)
        if kind == "run_powershell":
            return _execute_run_powershell(action)
        if kind == "git_commit":
            return _execute_git_commit(action)
        if kind in {"git_remote_fetch", "git_remote_pull", "git_remote_push", "git_branch"}:
            return _execute_git_remote_action(action)
        if kind == "pull_ollama_model":
            return _execute_pull_ollama_model(action)
        if kind == "delete_ollama_model":
            return _execute_delete_ollama_model(action)
        if kind == "stop_process":
            return _execute_stop_process(action)
        if kind == "start_service":
            return _execute_service_action(action, "start", "running")
        if kind == "stop_service":
            return _execute_service_action(action, "stop", "stopped")
        if kind == "create_reminder":
            return create_approved(action)
        if kind == "delete_reminder":
            return delete_approved(action)
        if kind == "spawn_subagent":
            return spawn_approved(action)
        if kind == "text_to_speech":
            return text_to_speech_approved(action)
        if kind == "generate_image":
            return generate_image_approved(action)
        if kind == "generate_video":
            return generate_video_approved(action)
        if kind == "pair_node":
            return pair_node_approved(action, endpoint="http://127.0.0.1:3210")
        if kind == "revoke_node":
            return revoke_node_approved(action)
        if kind == "rea_call_tool":
            t_name = str(action.get("tool_name", "")).strip()
            t_args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
            return rea_call_tool(t_name, t_args, allow_dynamic=True)
        return {"ok": False, "error": f"Tipo de acción desconocido: {kind}"}
    except ToolError as error:
        return {"ok": False, "error": str(error)}
    except (OSError, RuntimeError) as error:
        return {"ok": False, "error": f"No se pudo completar la acción: {error}"}


def execute_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    arguments = arguments if isinstance(arguments, dict) else {}
    try:
        if name in SENSITIVE_TOOL_NAMES:
            return {"ok": False, "requires_approval": True, "error": "Esta acción requiere aprobación explícita de Usuario."}
        if name == "search_project_files":
            return _search_project_files(arguments)
        if name == "find_project_paths":
            return _find_project_paths(arguments)
        if name == "get_local_status":
            return _get_local_status()
        if name == "list_processes":
            return _list_processes(arguments)
        if name == "list_services":
            return _list_services(arguments)
        if name == "git_status":
            return _git_status(arguments)
        if name == "git_diff":
            return _git_diff(arguments)
        if name == "git_log":
            return _git_log(arguments)
        if name == "git_remote_status":
            return _git_remote_status(arguments)
        if name == "read_pdf":
            return _read_pdf(arguments)
        if name == "read_image":
            return _read_image(arguments)
        if name == "read_document":
            return _read_document(arguments)
        if name == "list_ollama_models":
            return _list_ollama_models()
        if name == "search_memory":
            return _search_memory(arguments)
        if name == "read_memory":
            return _read_memory(arguments)
        if name == "list_memory":
            return _list_memory(arguments)
        if name == "list_project_files":
            return _list_project_files(arguments)
        if name == "read_project_file":
            return _read_project_file(arguments)
        if name == "list_allowed_roots":
            return _list_allowed_roots()
        if name == "web_search":
            return _web_search(arguments)
        if name == "web_fetch":
            return _web_fetch(arguments)
        if name == "browser_open":
            return browser_open(arguments)
        if name == "browser_snapshot":
            return browser_snapshot(arguments)
        if name == "browser_close":
            return browser_close()
        if name == "list_automations":
            return list_automations()
        if name == "list_automation_events":
            try:
                limit = int(arguments.get("limit", 50) or 50)
            except (TypeError, ValueError) as error:
                raise AutomationError("limit debe ser un número entero.") from error
            return list_events(limit)
        if name == "list_subagents":
            try:
                limit = int(arguments.get("limit", 50) or 50)
            except (TypeError, ValueError) as error:
                raise SubagentError("limit debe ser un número entero.") from error
            return list_jobs(limit)
        if name == "local_management_status":
            return local_status()
        if name == "media_status":
            return media_status()
        if name == "list_media":
            return list_media(arguments.get("limit", 100))
        if name == "list_nodes":
            return list_nodes()
        if name == "rea_status":
            return rea_status()
        if name == "rea_list_tools":
            return rea_list_tools(
                str(arguments.get("query", "") or ""),
                int(arguments.get("limit", 35) or 35),
            )
        if name == "rea_inspect_binary":
            raw_target = str(arguments.get("path", "") or "").strip()
            if not raw_target:
                raise ToolError("Debes indicar «path» (nombre del programa o ruta al binario).")
            target_p = Path(resolve_rea_target(raw_target))
            if _is_private_path(target_p):
                raise ToolError("No se permite inspeccionar directorios privados o credenciales de MyKOS.")
            return rea_inspect_binary(str(target_p))
        if name == "rea_analyze_javascript":
            raw_target = str(arguments.get("input_path", "") or "").strip()
            if not raw_target:
                raise ToolError("Debes indicar «input_path».")
            target_p = Path(resolve_rea_target(raw_target))
            if _is_private_path(target_p):
                raise ToolError("No se permite analizar directorios privados o credenciales de MyKOS.")
            return rea_analyze_javascript(str(target_p), str(arguments.get("detail", "summary") or "summary"))
        if name == "rea_call_tool":
            t_name = str(arguments.get("tool_name", "") or "").strip()
            t_args = arguments.get("arguments")
            if not isinstance(t_args, dict):
                t_args = {}
            for val in t_args.values():
                if isinstance(val, str) and ("/" in val or "\\" in val):
                    try:
                        cand = Path(val).expanduser().resolve()
                        if _is_private_path(cand):
                            raise ToolError("No se permite usar REA sobre rutas de credenciales de MyKOS.")
                    except OSError:
                        pass
            return rea_call_tool(t_name, t_args)
        return {"ok": False, "error": f"Herramienta desconocida: {name}"}
    except ToolError as error:
        return {"ok": False, "error": str(error)}
    except ReaError as error:
        return {"ok": False, "error": str(error)}
    except BrowserError as error:
        return {"ok": False, "error": str(error)}
    except AutomationError as error:
        return {"ok": False, "error": str(error)}
    except SubagentError as error:
        return {"ok": False, "error": str(error)}
    except (OSError, RuntimeError) as error:
        return {"ok": False, "error": f"No se pudo completar la herramienta: {error}"}
