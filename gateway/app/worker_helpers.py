"""Funciones auxiliares del trabajador Python de MyKOS (vistas de aprobación, catálogo Ollama y biblioteca)."""
from __future__ import annotations

import html
import re
import urllib.parse
from pathlib import Path
from typing import Any

from tools import execute_tool


class ApiError(Exception):
    """An expected client-facing API error."""


OLLAMA_CATALOG_MAX_RESULTS = 30

LIBRARY_TEXT_EXTENSIONS = {
    ".bat", ".c", ".cc", ".cfg", ".cmake", ".conf", ".cpp", ".css",
    ".csv", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".html", ".ini", ".js",
    ".json", ".md", ".ps1", ".py", ".sh", ".sql", ".toml", ".txt",
    ".xml", ".yaml", ".yml",
}
LIBRARY_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
LIBRARY_PREVIEW_EXTENSIONS = LIBRARY_TEXT_EXTENSIONS | LIBRARY_IMAGE_EXTENSIONS | {
    ".pdf", ".docx", ".xlsx",
}


def _approval_public_view(record: dict[str, Any]) -> dict[str, Any]:
    action = record.get("action") or {}
    kind = str(action.get("kind", ""))
    if kind in {"write_file", "edit_file"}:
        if kind == "edit_file":
            if "old_text" in action or "new_text" in action:
                content = (
                    "--- Fragmento actual ---\n"
                    + str(action.get("old_text", ""))
                    + "\n--- Se sustituirá por ---\n"
                    + str(action.get("new_text", ""))
                )
            else:
                content = str(action.get("summary") or action.get("preview_row") or "Edición estructurada del archivo.")
        else:
            content = str(action.get("content", ""))
        preview_limit = 8_000
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Editar archivo" if kind == "edit_file" else "Crear archivo",
            "root": action.get("root", ""),
            "path": action.get("path", ""),
            "overwrite": kind == "edit_file",
            "content_preview": content[:preview_limit],
            "content_truncated": len(content) > preview_limit,
            "content_bytes": len(content.encode("utf-8")),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "research_note":
        content = str(action.get("content", ""))
        preview_limit = 12_000
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Guardar ficha de investigación",
            "research_title": action.get("title", ""),
            "root": action.get("root", ""),
            "path": action.get("path", ""),
            "query": action.get("query", ""),
            "sources_count": action.get("sources_count", 0),
            "content_preview": content[:preview_limit],
            "content_truncated": len(content) > preview_limit,
            "content_bytes": len(content.encode("utf-8")),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "run_powershell":
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Ejecutar PowerShell",
            "command": action.get("command", ""),
            "cwd_root": action.get("cwd_root", ""),
            "cwd_path": action.get("cwd_path", "."),
            "timeout_seconds": action.get("timeout_seconds", 30),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "save_memory":
        content = str(action.get("content", ""))
        preview_limit = 8_000
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Actualizar memoria" if action.get("memory_id") else "Guardar memoria",
            "memory_id": action.get("memory_id", ""),
            "memory_title": action.get("title", ""),
            "category": action.get("category", "fact"),
            "tags": action.get("tags", []),
            "content_preview": content[:preview_limit],
            "content_truncated": len(content) > preview_limit,
            "content_bytes": len(content.encode("utf-8")),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "delete_memory":
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Eliminar memoria",
            "memory_id": action.get("memory_id", ""),
            "memory_title": action.get("title", ""),
            "category": action.get("category", "fact"),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "git_commit":
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Crear commit Git",
            "root": action.get("root", ""),
            "message": action.get("message", ""),
            "paths": action.get("paths", []),
            "stage_all": bool(action.get("stage_all", False)),
            "stage_mode": action.get("stage_mode", ""),
            "status_preview": action.get("status_preview", ""),
            "status_truncated": bool(action.get("status_truncated", False)),
            "staged_stat": action.get("staged_stat", ""),
            "unstaged_stat": action.get("unstaged_stat", ""),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "stop_process":
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Detener proceso",
            "pid": action.get("pid", 0),
            "process_name": action.get("name", ""),
            "username": action.get("username", ""),
            "status": action.get("status", ""),
            "memory_bytes": action.get("memory_bytes", 0),
            "created_at_process": action.get("created_at", ""),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind in {"start_service", "stop_service"}:
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Iniciar servicio" if kind == "start_service" else "Detener servicio",
            "service": action.get("service", ""),
            "display_name": action.get("display_name", ""),
            "status": action.get("status", ""),
            "start_type": action.get("start_type", ""),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "pull_ollama_model":
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Descargar o actualizar modelo",
            "model": action.get("model", ""),
            "ollama_url": action.get("ollama_url", ""),
            "already_installed": bool(action.get("already_installed", False)),
            "current_size": action.get("current_size", 0),
            "panel_job_id": action.get("panel_job_id", ""),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "delete_ollama_model":
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Eliminar modelo Ollama",
            "model": action.get("model", ""),
            "ollama_url": action.get("ollama_url", ""),
            "size": action.get("size", 0),
            "capabilities": action.get("capabilities", []),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "git_branch":
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Cambiar de rama Git" if action.get("operation") == "switch" else "Crear rama Git",
            "root": action.get("root", ""),
            "operation": action.get("operation", ""),
            "branch": action.get("branch", ""),
            "start_point": action.get("start_point", ""),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind in {"git_remote_fetch", "git_remote_pull", "git_remote_push"}:
        titles = {
            "git_remote_fetch": "Consultar remoto Git (fetch)",
            "git_remote_pull": "Actualizar desde remoto Git (pull --ff-only)",
            "git_remote_push": "Enviar cambios al remoto Git (push)",
        }
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": titles.get(kind, "Operación Git remota"),
            "root": action.get("root", ""),
            "remote": action.get("remote", "origin"),
            "remote_url": action.get("remote_url", ""),
            "branch": action.get("branch", ""),
            "set_upstream": bool(action.get("set_upstream", False)),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "create_reminder":
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Crear recordatorio",
            "reminder_title": action.get("title", ""),
            "message": action.get("message", ""),
            "run_at": action.get("run_at", ""),
            "repeat_minutes": action.get("repeat_minutes", 0),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "delete_reminder":
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Eliminar recordatorio",
            "target_id": action.get("target_id", ""),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "spawn_subagent":
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Lanzar subagente local",
            "subagent_title": action.get("title", ""),
            "model": action.get("model", ""),
            "prompt": action.get("prompt", ""),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "text_to_speech":
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Generar audio por voz",
            "text": action.get("text", ""),
            "voice": action.get("voice", ""),
            "filename": action.get("filename", ""),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "pair_node":
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Emparejar nodo",
            "name": action.get("name", ""),
            "node_kind": action.get("node_kind", ""),
            "capabilities": action.get("capabilities", []),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    if kind == "revoke_node":
        return {
            "id": record.get("id", ""),
            "kind": kind,
            "title": "Revocar nodo",
            "node_id": action.get("node_id", ""),
            "created_at": record.get("created_at", ""),
            "expires_at": record.get("expires_at", ""),
        }
    return {
        "id": record.get("id", ""),
        "kind": kind,
        "title": "Acción desconocida",
        "created_at": record.get("created_at", ""),
        "expires_at": record.get("expires_at", ""),
    }


def approval_public_view(record: dict[str, Any]) -> dict[str, Any]:
    public = _approval_public_view(record)
    public["permission"] = record.get("permission") or {}
    return public


def _catalog_text(fragment: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", fragment)
    return html.unescape(re.sub(r"\s+", " ", without_tags)).strip()


def _catalog_cards(document: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    pattern = re.compile(
        r'<li\b[^>]*>\s*<a\b[^>]*href="/library/([^"?#]+)"[^>]*>(.*?)</a>\s*</li>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(document):
        name = html.unescape(match.group(1)).strip().strip("/")
        block = match.group(2)
        if not name:
            continue
        description_match = re.search(r"<p\b[^>]*>(.*?)</p>", block, re.IGNORECASE | re.DOTALL)
        description = _catalog_text(description_match.group(1)) if description_match else ""
        raw_badges = re.findall(
            r'<span\b[^>]*class="[^"]*bg-[^"]*"[^>]*>(.*?)</span>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        badges: list[str] = []
        for raw_badge in raw_badges:
            badge = _catalog_text(raw_badge)
            if badge and badge not in badges:
                badges.append(badge)
        cards.append(
            {
                "name": name,
                "url": f"https://ollama.com/library/{urllib.parse.quote(name)}",
                "description": description[:500],
                "badges": badges[:30],
            }
        )
        if len(cards) >= OLLAMA_CATALOG_MAX_RESULTS:
            break
    return cards


def _library_file_kind(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in LIBRARY_IMAGE_EXTENSIONS:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".docx", ".xlsx"}:
        return "document"
    if suffix in LIBRARY_TEXT_EXTENSIONS:
        return "text"
    return "other"


def library_list(root: str, path: str) -> dict[str, Any]:
    result = execute_tool(
        "list_project_files",
        {"root": root or "mykos", "path": path or "", "recursive": False},
    )
    if not result.get("ok"):
        raise ApiError(str(result.get("error", "No se pudo listar la carpeta.")))
    items = []
    for item in result.get("items", []):
        if not isinstance(item, dict):
            continue
        item = dict(item)
        if item.get("type") == "file":
            item["kind"] = _library_file_kind(str(item.get("path", "")))
            item["previewable"] = item["kind"] in {"text", "pdf", "image", "document"}
        else:
            item["kind"] = "directory"
            item["previewable"] = False
        items.append(item)
    return {
        "ok": True,
        "root": result.get("root", root),
        "path": result.get("path", path or "."),
        "items": items,
        "truncated": bool(result.get("truncated", False)),
    }


def library_search(root: str, path: str, query: str) -> dict[str, Any]:
    result = execute_tool(
        "search_project_files",
        {
            "root": root or "mykos",
            "path": path or "",
            "query": query,
            "max_results": 30,
        },
    )
    if not result.get("ok"):
        raise ApiError(str(result.get("error", "No se pudo buscar en la biblioteca.")))
    return result


def library_preview(root: str, path: str) -> dict[str, Any]:
    clean_path = str(path or "").strip()
    kind = _library_file_kind(clean_path)
    if kind == "text":
        result = execute_tool("read_project_file", {"root": root or "mykos", "path": clean_path})
    elif kind == "pdf":
        result = execute_tool("read_pdf", {"root": root or "mykos", "path": clean_path, "max_pages": 20})
    elif kind == "image":
        result = execute_tool(
            "read_image",
            {"root": root or "mykos", "path": clean_path, "ocr": True},
        )
    elif kind == "document":
        result = execute_tool("read_document", {"root": root or "mykos", "path": clean_path})
    else:
        raise ApiError("Este tipo de archivo no tiene vista previa segura.")
    if not result.get("ok"):
        raise ApiError(str(result.get("error", "No se pudo abrir el archivo.")))

    image_base64 = result.pop("_image_base64", None)
    image_mime_type = result.pop("_image_mime_type", None)
    public = dict(result)
    if kind == "text" and "text" not in public:
        public["text"] = public.pop("content", "")
    public.update({"kind": kind, "root": root or "mykos", "path": clean_path})
    if image_base64:
        public["image"] = {"data": image_base64, "mime_type": image_mime_type or "image/png"}
    return public
