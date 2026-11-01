from __future__ import annotations

import hashlib
import os
import platform
import secrets
import socket
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gateway_store


ROOT = Path(__file__).resolve().parent
NODES_FILE = ROOT / "data" / "nodes.json"
NODES_LOCK = threading.RLock()
MAX_NODES = 50
MAX_NAME_CHARS = 80
MAX_CAPABILITIES = 20
MAX_CAPABILITY_CHARS = 40


class NodeError(RuntimeError):
    """Error seguro producido por la capa de nodos local."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict[str, Any]:
    raw = gateway_store.load_document(
        "nodes",
        legacy_file=NODES_FILE,
        default={"nodes": []},
    )
    nodes = raw.get("nodes", []) if isinstance(raw, dict) else []
    return {"nodes": [item for item in nodes if isinstance(item, dict)]}


def _save(state: dict[str, Any]) -> None:
    gateway_store.save_document(
        "nodes",
        state,
        legacy_file=NODES_FILE,
        indent=2,
        source="nodes.registry",
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _local_node() -> dict[str, Any]:
    return {
        "id": "local-desktop",
        "name": socket.gethostname(),
        "kind": "desktop",
        "local": True,
        "enabled": True,
        "status": "online",
        "capabilities": ["chat", "files", "microphone", "tts"],
        "platform": platform.platform(),
        "pid": os.getpid(),
        "last_seen": _now(),
    }


def list_nodes() -> dict[str, Any]:
    with NODES_LOCK:
        state = _load()
        remote = []
        for item in state["nodes"]:
            public = {key: value for key, value in item.items() if key != "token_hash"}
            public["local"] = False
            if not public.get("enabled", True):
                public["status"] = "revoked"
            elif not public.get("last_seen"):
                public["status"] = "pending"
            remote.append(public)
    return {"ok": True, "nodes": [_local_node(), *remote], "local_only": True}


def prepare_pair_node(arguments: dict[str, Any]) -> dict[str, Any]:
    name = str(arguments.get("name", "")).strip()
    kind = str(arguments.get("kind", "node")).strip().lower() or "node"
    raw_capabilities = arguments.get("capabilities", [])
    if not name or len(name) > MAX_NAME_CHARS:
        raise NodeError(f"El nombre debe tener entre 1 y {MAX_NAME_CHARS} caracteres.")
    if kind not in {"mobile", "desktop", "node"}:
        raise NodeError("kind debe ser mobile, desktop o node.")
    if not isinstance(raw_capabilities, list) or len(raw_capabilities) > MAX_CAPABILITIES:
        raise NodeError("La lista de capacidades no es válida.")
    capabilities: list[str] = []
    for value in raw_capabilities:
        item = str(value).strip().lower()
        if item and len(item) <= MAX_CAPABILITY_CHARS and item not in capabilities:
            capabilities.append(item)
    with NODES_LOCK:
        if len(_load()["nodes"]) >= MAX_NODES:
            raise NodeError("Se ha alcanzado el límite de nodos emparejados.")
    return {
        "kind": "pair_node",
        "name": name,
        "node_kind": kind,
        "capabilities": capabilities,
    }


def pair_node_approved(action: dict[str, Any], *, endpoint: str) -> dict[str, Any]:
    token = secrets.token_urlsafe(32)
    node = {
        "id": uuid.uuid4().hex,
        "name": str(action.get("name", "")).strip(),
        "kind": str(action.get("node_kind", "node")).strip(),
        "capabilities": list(action.get("capabilities", [])) if isinstance(action.get("capabilities"), list) else [],
        "enabled": True,
        "status": "pending",
        "created_at": _now(),
        "last_seen": "",
        "token_hash": _token_hash(token),
    }
    with NODES_LOCK:
        state = _load()
        state["nodes"].append(node)
        _save(state)
    return {
        "ok": True,
        "node_id": node["id"],
        "name": node["name"],
        "kind": node["kind"],
        "capabilities": node["capabilities"],
        "endpoint": endpoint.rstrip("/") + "/api/nodes/heartbeat",
        "node_token": token,
        "token_notice": "Guarda este token: MyKOS no lo vuelve a mostrar y solo se acepta por HTTPS o una red local de confianza.",
    }


def prepare_revoke_node(arguments: dict[str, Any]) -> dict[str, Any]:
    node_id = str(arguments.get("node_id", "")).strip()
    if not node_id or node_id == "local-desktop":
        raise NodeError("El nodo local no se puede revocar desde esta acción.")
    if len(node_id) > 80:
        raise NodeError("El identificador del nodo no es válido.")
    return {"kind": "revoke_node", "node_id": node_id}


def revoke_node_approved(action: dict[str, Any]) -> dict[str, Any]:
    node_id = str(action.get("node_id", "")).strip()
    with NODES_LOCK:
        state = _load()
        target = next((item for item in state["nodes"] if item.get("id") == node_id), None)
        if target is None:
            raise NodeError("El nodo no existe.")
        target["enabled"] = False
        target["status"] = "revoked"
        target["revoked_at"] = _now()
        _save(state)
    return {"ok": True, "node_id": node_id, "status": "revoked"}


def heartbeat_node(payload: dict[str, Any], token: str) -> dict[str, Any]:
    node_id = str(payload.get("node_id", "")).strip()
    if not node_id or len(token) < 20:
        raise NodeError("Faltan credenciales de nodo.")
    with NODES_LOCK:
        state = _load()
        target = next((item for item in state["nodes"] if item.get("id") == node_id), None)
        if target is None or not target.get("enabled", True) or not secrets.compare_digest(str(target.get("token_hash", "")), _token_hash(token)):
            raise NodeError("El nodo o el token no son válidos.")
        capabilities = payload.get("capabilities")
        if isinstance(capabilities, list):
            target["reported_capabilities"] = [str(item)[:MAX_CAPABILITY_CHARS] for item in capabilities[:MAX_CAPABILITIES]]
        target["status"] = "online"
        target["last_seen"] = _now()
        _save(state)
    return {"ok": True, "node_id": node_id, "status": "online", "server_time": _now()}
