"""Diagnóstico y gestión de solo lectura de la instalación local de MyKOS."""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gateway_store


ROOT = Path(__file__).resolve().parent
WORKSPACE_ENV = os.environ.get("MYKOS_WORKSPACE_DIR") or os.environ.get("MYKOS_GATEWAY_WORKSPACE_DIR")
WORKSPACE = Path(WORKSPACE_ENV).expanduser().resolve() if WORKSPACE_ENV else (Path.home() / ".mykos" / "workspace").resolve()
_DATA_ENV = os.environ.get("MYKOS_DATA_DIR", "").strip()
DATA = Path(_DATA_ENV).expanduser().resolve() if _DATA_ENV else (ROOT / "data" if os.access(ROOT / "data" if (ROOT / "data").exists() else ROOT, os.W_OK) else (Path.home() / ".mykos" / "data").resolve())
CONFIG = ROOT / "config"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def _store_doc(name: str) -> dict[str, Any] | None:
    """Datos de un documento que guarda el Gateway (revisión, tamaño, recuento), o None si no aplica."""
    docs = gateway_store.store_info()
    doc = docs.get(name) if docs else None
    return doc if isinstance(doc, dict) and doc.get("exists") else None


def _file_info(path: Path, store_doc: str | None = None) -> dict[str, Any]:
    if store_doc and gateway_store.ENABLED:
        doc = _store_doc(store_doc)
        if doc is None:
            return {"exists": False, "path": f"gateway:{store_doc}", "storage": "gateway"}
        return {"exists": True, "path": f"gateway:{store_doc}", "bytes": doc.get("bytes", 0), "revision": doc.get("revision"), "storage": "gateway"}
    try:
        stat = path.stat()
    except OSError:
        return {"exists": False, "path": str(path)}
    return {"exists": True, "path": str(path), "bytes": stat.st_size}


def _count_json_items(path: Path, key: str, store_doc: str | None = None) -> int:
    if store_doc and gateway_store.ENABLED:
        doc = _store_doc(store_doc)
        return int(doc.get("count", 0)) if doc else 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 0
    value = data.get(key) if isinstance(data, dict) else None
    return len(value) if isinstance(value, list) else 0


def _ollama_check() -> dict[str, Any]:
    request = urllib.request.Request(f"{OLLAMA_URL}/api/tags", headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            data = json.loads(response.read(512_000).decode("utf-8"))
        models = data.get("models", []) if isinstance(data, dict) else []
        return {"status": "ok", "detail": f"Ollama operativo · {len(models)} modelos", "models": len(models)}
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "warning", "detail": "Ollama no responde ahora mismo", "models": 0}


def local_status() -> dict[str, Any]:
    disk = shutil.disk_usage(ROOT)
    workspace_files = 0
    if WORKSPACE.is_dir():
        for _path in WORKSPACE.rglob("*"):
            if _path.is_file():
                workspace_files += 1
                if workspace_files >= 10_000:
                    break
    checks = [
        {"id": "mykos_root", "label": "Raíz de MyKOS", "status": "ok", "detail": str(ROOT)},
        {"id": "workspace", "label": "Workspace independiente", "status": "ok" if WORKSPACE.is_dir() else "error", "detail": f"{workspace_files} archivos" if WORKSPACE.is_dir() else "No encontrado"},
        {"id": "config", "label": "Configuración local", "status": "ok" if (CONFIG / "system_prompt.txt").is_file() else "warning", "detail": "Prompt y raíces locales disponibles" if (CONFIG / "system_prompt.txt").is_file() else "Falta system_prompt.txt"},
        {"id": "data", "label": "Almacenamiento local", "status": "ok" if DATA.is_dir() else "error", "detail": str(DATA)},
        {"id": "ollama", "label": "Motor Ollama", **_ollama_check()},
    ]
    return {
        "ok": True,
        "action": "local_management_status",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "application": "MyKOS",
        "process": {"pid": os.getpid(), "host": socket.gethostname(), "python": sys.version.split()[0], "platform": platform.platform()},
        "paths": {"root": str(ROOT), "workspace": str(WORKSPACE), "data": str(DATA), "config": str(CONFIG)},
        "files": {
            "conversations": _file_info(DATA / "conversations.json", store_doc="conversations"),
            "permissions": _file_info(DATA / "permissions.json", store_doc="permissions"),
            "automations": _file_info(DATA / "automations.json", store_doc="automations"),
            "subagents": _file_info(DATA / "subagents.json", store_doc="subagents"),
            "nodes": _file_info(DATA / "nodes.json", store_doc="nodes"),
        },
        "counts": {
            "conversations": _count_json_items(DATA / "conversations.json", "conversations", store_doc="conversations"),
            "automations": _count_json_items(DATA / "automations.json", "automations", store_doc="automations"),
            "automation_events": _count_json_items(DATA / "automations.json", "events", store_doc="automations"),
            "subagent_jobs": _count_json_items(DATA / "subagents.json", "jobs", store_doc="subagents"),
            "nodes": _count_json_items(DATA / "nodes.json", "nodes", store_doc="nodes"),
        },
        "disk": {"free_bytes": disk.free, "total_bytes": disk.total, "used_bytes": disk.used},
        "checks": checks,
    }
