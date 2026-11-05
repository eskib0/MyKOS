"""Módulo base y primitivas comunes para las herramientas de MyKOS.

Define constantes, límites de seguridad, excepciones, resolución de rutas
autorizadas y detección de rutas privadas e ignoradas.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# PROJECT_ROOT apunta a gateway/app; REPO_ROOT apunta a la raíz del repositorio de MyKOS
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT.parent.parent if (PROJECT_ROOT.parent.parent / ".git").exists() else PROJECT_ROOT
ALLOWED_ROOTS_FILE = PROJECT_ROOT / "config" / "allowed_roots.json"
MEMORY_FILE = PROJECT_ROOT / "data" / "memory.json"

# Límites de seguridad y cuotas
MAX_LIST_ENTRIES = 200
MAX_READ_BYTES = 400_000
MAX_SEARCH_RESULTS = 30
MAX_SEARCH_FILES = 1_500
MAX_SEARCH_FILE_BYTES = 500_000
MAX_PATH_SEARCH_ENTRIES = 10_000
MAX_WRITE_BYTES = 120_000
MAX_RESEARCH_TITLE_CHARS = 180
MAX_RESEARCH_QUERY_CHARS = 500
MAX_RESEARCH_SUMMARY_CHARS = 20_000
MAX_RESEARCH_KEY_POINTS = 20
MAX_RESEARCH_SOURCES = 12
MAX_COMMAND_CHARS = 4_000
MAX_COMMAND_TIMEOUT = 60
MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_DOCUMENT_TEXT_CHARS = 120_000
MAX_OFFICE_BYTES = 30 * 1024 * 1024
MAX_SPREADSHEET_ROWS = 10_000
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
MAX_OCR_CHARS = 30_000
WEB_REQUEST_TIMEOUT_SECONDS = 20
WEB_MAX_BYTES = 2 * 1024 * 1024
WEB_MAX_TEXT_CHARS = 30_000
WEB_MAX_RESULTS = 10
WEB_USER_AGENT = "MyKOS/1.0 (local research assistant)"
MAX_PROCESS_RESULTS = 100
MAX_SERVICE_RESULTS = 100
MAX_PROCESS_QUERY_CHARS = 120
MAX_SERVICE_NAME_CHARS = 256
OLLAMA_REQUEST_TIMEOUT_SECONDS = 30
OLLAMA_PULL_TIMEOUT_SECONDS = 30 * 60
OLLAMA_MODEL_NAME_CHARS = 200
MEMORY_MAX_ENTRIES = 1_000
MEMORY_MAX_TITLE_CHARS = 160
MEMORY_MAX_CONTENT_BYTES = 50_000
MEMORY_MAX_TAGS = 12
MEMORY_MAX_TAG_CHARS = 40
MEMORY_CATEGORIES = {"fact", "preference", "project", "decision", "task", "reference"}
GIT_MAX_OUTPUT_CHARS = 60_000
GIT_MAX_LOG_ENTRIES = 50
GIT_MAX_PATHS = 100
GIT_MAX_COMMIT_MESSAGE_CHARS = 200
GIT_REMOTE_TIMEOUT_SECONDS = 120

# Rutas y extensiones ignoradas o restringidas por seguridad
IGNORED_PARTS = {
    ".config",
    ".local",
    ".claude",
    ".codex",
    ".mozilla",
    ".pki",
    ".git",
    ".mykos",
    ".gnupg",
    ".ssh",
    "__pycache__",
    "appdata",
    "cache",
    "credentials",
    "data",
    "logs",
    "oauth",
    "programdata",
    "secrets",
    "state",
    "tmp",
    "temp",
}

PRIVATE_PATH_ROOTS = tuple(path.resolve() for path in (
    PROJECT_ROOT / "data",
    Path.home() / ".mykos" / "gateway-state",
    Path.home() / "mykos-gateway-state",
))

ALLOWED_TEXT_EXTENSIONS = {
    ".bat", ".c", ".cc", ".cfg", ".cmake", ".conf", ".cpp", ".css",
    ".csv", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".html", ".ini", ".js",
    ".json", ".md", ".ps1", ".py", ".sh", ".sql", ".toml", ".txt",
    ".xml", ".yaml", ".yml",
}

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")

# Bloqueos de concurrencia
MEMORY_LOCK = threading.RLock()
GIT_LOCK = threading.RLock()
OLLAMA_LOCK = threading.RLock()


class ToolError(Exception):
    """Error seguro y legible producido por una herramienta."""


def _load_allowed_roots() -> list[dict[str, Any]]:
    workspace_env = os.environ.get("MYKOS_WORKSPACE_DIR") or os.environ.get("MYKOS_GATEWAY_WORKSPACE_DIR")
    default_ws = Path(workspace_env).expanduser() if workspace_env else (Path.home() / ".mykos" / "workspace")
    try:
        default_ws.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        pass
    roots: list[dict[str, Any]] = [
        {"name": "workspace", "path": default_ws.resolve()},
        {"name": "mykos", "path": REPO_ROOT},
    ]
    try:
        data = json.loads(ALLOWED_ROOTS_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        data = {}
    configured = data.get("roots", []) if isinstance(data, dict) else []
    if not isinstance(configured, list):
        configured = []
    names = {root["name"] for root in roots}
    for entry in configured:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        raw_path = entry.get("path")
        if not name or not isinstance(raw_path, str):
            continue
        if not name.replace("_", "").replace("-", "").replace(".", "").isalnum() or len(name) > 40:
            continue
        configured_path = Path(os.path.expandvars(raw_path)).expanduser()
        if not configured_path.is_absolute():
            configured_path = (PROJECT_ROOT / configured_path).resolve()
        try:
            if not configured_path.exists() and name == "workspace":
                configured_path.mkdir(parents=True, exist_ok=True, mode=0o700)
            resolved = configured_path.resolve()
        except OSError:
            continue
        if resolved == Path("/"):
            continue
        if resolved.is_dir() and not resolved.is_symlink():
            if name in names:
                for r in roots:
                    if r["name"] == name:
                        r["path"] = resolved
                        break
            else:
                roots.append({"name": name, "path": resolved})
                names.add(name)
    return roots


def allowed_root_catalog() -> list[dict[str, str]]:
    return [{"name": root["name"], "path": str(root["path"])} for root in _load_allowed_roots()]


def _relative_label(path: Path, root_path: Path) -> str:
    relative = path.relative_to(root_path)
    return "." if str(relative) == "." else relative.as_posix()


def _resolve_root(root_name: Any) -> tuple[str, Path]:
    roots = _load_allowed_roots()
    default_root = roots[0]["name"] if roots else "workspace"
    requested = str(root_name or default_root).strip()
    for root in roots:
        if root["name"] == requested:
            return root["name"], root["path"]
    available = ", ".join(root["name"] for root in roots)
    raise ToolError(f"Raíz no autorizada: {requested}. Disponibles: {available}.")


def _resolve_project_path(root_name: Any, raw_path: Any, *, allow_root: bool = True) -> tuple[str, Path, Path]:
    roots = _load_allowed_roots()
    roots_by_name = {item["name"]: item["path"] for item in roots}
    workspace_root = roots_by_name.get("workspace")
    selected_name, root_path = _resolve_root(root_name)
    if raw_path is None:
        raw_path = ""
    if not isinstance(raw_path, str):
        raise ToolError("La ruta debe ser texto.")
    raw_path = raw_path.strip()
    if len(raw_path) > 500:
        raise ToolError("La ruta es demasiado larga.")

    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ToolError("Solo se aceptan rutas relativas a una raíz autorizada.")

    # Si se incluye "workspace" como prefijo de ruta (p. ej. "workspace/research/tema.md"):
    if candidate.parts and candidate.parts[0].lower() == "workspace":
        remainder = Path(*candidate.parts[1:]) if len(candidate.parts) > 1 else Path(".")
        if selected_name == "workspace":
            candidate = remainder
        elif selected_name == "mykos" and workspace_root is not None:
            selected_name = "workspace"
            root_path = workspace_root
            candidate = remainder

    resolved = (root_path / candidate).resolve()
    try:
        resolved.relative_to(root_path)
    except ValueError as error:
        raise ToolError("La ruta queda fuera de la raíz autorizada.") from error
    if not resolved.exists() and raw_path and ".." not in candidate.parts:
        fallback_attempts: list[tuple[str, Path, Path]] = []
        other_name = "workspace" if selected_name == "mykos" else "mykos"
        other_root = roots_by_name.get(other_name)
        if other_root is not None:
            fallback_attempts.append((other_name, other_root, (other_root / candidate).resolve()))
        for alt_name, alt_root, alt_path in fallback_attempts:
            try:
                alt_path.relative_to(alt_root)
            except ValueError:
                continue
            if _is_ignored(alt_path, alt_root):
                continue
            if alt_path.exists() or (not resolved.parent.exists() and alt_path.parent != alt_root and alt_path.parent.exists()):
                selected_name, root_path, resolved = alt_name, alt_root, alt_path
                break
    if _is_ignored(resolved, root_path):
        raise ToolError("La ruta pertenece a almacenamiento privado o interno y no está disponible para las herramientas de proyecto.")
    if not allow_root and resolved == root_path:
        raise ToolError("Debes indicar un archivo, no la raíz completa.")
    return selected_name, root_path, resolved


def _is_ignored(path: Path, root_path: Path) -> bool:
    try:
        resolved = path.resolve()
        parts = resolved.relative_to(root_path.resolve()).parts
    except (OSError, ValueError):
        return True
    if any(resolved == private_root or private_root in resolved.parents for private_root in PRIVATE_PATH_ROOTS):
        return True
    return bool(
        IGNORED_PARTS.intersection(part.casefold() for part in parts)
        or any(part.casefold().startswith(".env") for part in parts)
        or any(part.casefold() in {"auth.json", "credentials.json", "token.json"} for part in parts)
    )


def _is_private_path(path: Path) -> bool:
    """Verifica si una ruta apunta a datos privados o credenciales del sistema."""
    try:
        resolved = path.resolve()
        return any(resolved == private_root or private_root in resolved.parents for private_root in PRIVATE_PATH_ROOTS)
    except OSError:
        return True


def encode_tool_result(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
