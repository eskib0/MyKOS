from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gateway_store

ROOT = Path(__file__).resolve().parent
PERMISSIONS_FILE = ROOT / "data" / "permissions.json"
PERMISSION_MODES = {"once", "permanent"}
MAX_AUDIT_ENTRIES = 2000
MAX_GRANTS = 200
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict[str, Any]:
    data = gateway_store.load_document(
        "permissions",
        legacy_file=PERMISSIONS_FILE,
        default={"grants": [], "audit": []},
    )
    if not isinstance(data, dict):
        return {"grants": [], "audit": []}
    return {
        "grants": data.get("grants") if isinstance(data.get("grants"), list) else [],
        "audit": data.get("audit") if isinstance(data.get("audit"), list) else [],
    }


def _save(state: dict[str, Any]) -> None:
    gateway_store.save_document(
        "permissions",
        state,
        legacy_file=PERMISSIONS_FILE,
        indent=2,
        source="permissions",
    )


def _key(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def permission_descriptor(tool_name: str, action: dict[str, Any]) -> dict[str, Any]:
    """Build a narrow reusable scope from an already validated action."""
    kind = str(action.get("kind") or tool_name).strip()
    category = "action"
    resource = kind
    match: dict[str, Any] = {"kind": kind}
    summary = kind

    if kind in {"write_file", "edit_file", "research_note"}:
        category = "filesystem"
        root = str(action.get("root", "")).strip()
        path = str(action.get("path", "")).strip()
        resource = f"{root}/{path}".strip("/")
        match.update({"root": root, "path": path, "overwrite": bool(action.get("overwrite", False))})
        summary = f"{kind} · {resource}"
    elif kind == "run_powershell":
        category = "shell"
        root = str(action.get("cwd_root", "")).strip()
        path = str(action.get("cwd_path", ".")).strip() or "."
        command = str(action.get("command", "")).strip()
        resource = f"{root}/{path}".strip("/")
        # A reusable shell grant is exact-command only, never arbitrary shell access.
        match.update({"cwd_root": root, "cwd_path": path, "command": command})
        summary = f"PowerShell · {resource} · {command[:180]}"
    elif kind in {"start_service", "stop_service"}:
        category = "service"
        resource = str(action.get("service", "")).strip()
        match.update({"service": resource})
        summary = f"{kind} · servicio {resource}"
    elif kind == "stop_process":
        category = "process"
        pid = int(action.get("pid", 0) or 0)
        name = str(action.get("name", "")).strip()
        resource = f"{name} · PID {pid}"
        match.update({"pid": pid, "name": name, "create_time_epoch": action.get("create_time_epoch", 0)})
        summary = f"Detener proceso · {resource}"
    elif kind in {"pull_ollama_model", "delete_ollama_model"}:
        category = "model"
        resource = str(action.get("model", "")).strip()
        match.update({"model": resource})
        summary = f"{kind} · modelo {resource}"
    elif kind in {"save_memory", "delete_memory"}:
        category = "memory"
        memory_id = str(action.get("memory_id", "")).strip()
        resource = str(action.get("category", "memory")) if kind == "save_memory" else memory_id
        match.update({"memory_id": memory_id, "category": str(action.get("category", "fact"))})
        summary = f"{kind} · {resource}"
    elif kind == "git_commit":
        category = "git"
        resource = str(action.get("root", "")).strip()
        match.update({
            "root": resource,
            "message": str(action.get("message", "")),
            "paths": list(action.get("paths", [])) if isinstance(action.get("paths"), list) else [],
            "stage_all": bool(action.get("stage_all", False)),
        })
        summary = f"Commit Git · {resource}"
    elif kind == "rea_call_tool":
        category = "rea"
        tool_name = str(action.get("tool_name", "")).strip()
        resource = tool_name
        match.update({"tool_name": tool_name, "arguments": action.get("arguments", {})})
        summary = f"REA · {tool_name}"
    else:
        match = {key: value for key, value in action.items() if key != "content"}
        summary = f"{kind} · acción exacta"

    return {
        "category": category,
        "resource": resource,
        "operation": kind,
        "summary": summary,
        "scope_key": _key(match),
        "match": match,
    }


def allowed_modes(descriptor: dict[str, Any]) -> list[str]:
    operation = str(descriptor.get("operation", ""))
    match = descriptor.get("match") if isinstance(descriptor.get("match"), dict) else {}
    resource = str(descriptor.get("resource", ""))
    parts = resource.split("/", 1)
    root = str(match.get("root", "") or (parts[0] if len(parts) > 0 else ""))
    path = str(match.get("path", "") or (parts[1] if len(parts) > 1 else ""))
    category = str(descriptor.get("category", ""))
    if operation in {
        "run_powershell",
        "delete_memory",
        "delete_ollama_model",
        "git_commit",
        "stop_process",
        "start_service",
        "stop_service",
        "create_reminder",
        "delete_reminder",
        "spawn_subagent",
        "git_branch",
        "git_remote_fetch",
        "git_remote_pull",
        "git_remote_push",
        "text_to_speech",
        "generate_image",
        "generate_video",
        "pair_node",
        "revoke_node",
        "rea_call_tool",
    }:
        return ["once"]
    # Los archivos de código e infraestructura del propio Gateway nunca se auto-conceden de forma permanente
    if category == "filesystem" or operation in {"write_file", "edit_file"}:
        if root == "mykos" or resource.startswith("mykos/") or path.startswith(("gateway/", "static/", "apps/")) or re.search(r"\.(html|js|mjs|py|sh)$", path or resource, re.IGNORECASE):
            return ["once"]
    return ["once", "permanent"]


def permission_request_view(tool_name: str, action: dict[str, Any]) -> dict[str, Any]:
    descriptor = permission_descriptor(tool_name, action)
    modes = allowed_modes(descriptor)
    labels = {
        "once": ("Supervisado", "Pide tu aprobación cada vez."),
        "permanent": ("Acceso total", "No vuelve a preguntar; queda registrado como permiso concedido."),
    }
    return {
        **descriptor,
        "modes": [
            {"id": mode, "label": labels[mode][0], "description": labels[mode][1]}
            for mode in modes
        ],
    }


def _active(grant: dict[str, Any], session_id: str) -> bool:
    if grant.get("status", "active") != "active":
        return False
    mode = str(grant.get("mode", ""))
    if mode == "permanent":
        return True
    return mode == "session" and bool(session_id) and grant.get("session_id") == session_id


def find_grant(descriptor: dict[str, Any], session_id: str = "") -> dict[str, Any] | None:
    with _LOCK:
        state = _load()
        for grant in reversed(state["grants"]):
            if not isinstance(grant, dict) or grant.get("scope_key") != descriptor.get("scope_key"):
                continue
            if _active(grant, session_id):
                return dict(grant)
    return None


def grant_permission(descriptor: dict[str, Any], mode: str, session_id: str, *, approval_id: str = "") -> dict[str, Any] | None:
    mode = str(mode or "once").strip().casefold()
    if mode not in PERMISSION_MODES:
        raise ValueError("Modo de permiso no válido.")
    if mode not in allowed_modes(descriptor):
        raise ValueError("Este tipo de acción solo admite un permiso de una vez.")
    if mode == "once":
        return None
    now = _now()
    with _LOCK:
        state = _load()
        for grant in reversed(state["grants"]):
            if not isinstance(grant, dict) or grant.get("status") != "active":
                continue
            if grant.get("scope_key") != descriptor.get("scope_key") or grant.get("mode") != mode:
                continue
            if mode == "session" and grant.get("session_id") != session_id:
                continue
            grant["last_used_at"] = now
            _save(state)
            return dict(grant)
        grant = {
            "id": uuid.uuid4().hex,
            "status": "active",
            "mode": mode,
            "session_id": session_id if mode == "session" else "",
            "category": descriptor.get("category", "action"),
            "resource": descriptor.get("resource", ""),
            "operation": descriptor.get("operation", ""),
            "summary": descriptor.get("summary", ""),
            "scope_key": descriptor.get("scope_key", ""),
            "created_at": now,
            "last_used_at": now,
            "approval_id": approval_id,
        }
        state["grants"].append(grant)
        state["grants"] = state["grants"][-MAX_GRANTS:]
        _save(state)
        return dict(grant)


def record_audit(
    event: str,
    descriptor: dict[str, Any],
    *,
    mode: str = "once",
    status: str = "ok",
    permission_id: str = "",
    approval_id: str = "",
    session_id: str = "",
    detail: str = "",
) -> dict[str, Any]:
    entry = {
        "id": uuid.uuid4().hex,
        "at": _now(),
        "event": event,
        "status": status,
        "mode": mode,
        "permission_id": permission_id,
        "approval_id": approval_id,
        "session_id": session_id,
        "category": descriptor.get("category", "action"),
        "resource": descriptor.get("resource", ""),
        "operation": descriptor.get("operation", ""),
        "summary": descriptor.get("summary", ""),
        "detail": str(detail or "")[:500],
    }
    with _LOCK:
        state = _load()
        state["audit"].append(entry)
        state["audit"] = state["audit"][-MAX_AUDIT_ENTRIES:]
        _save(state)
    return entry
