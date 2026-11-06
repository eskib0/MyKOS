"""Gestión de estado de actividad en tiempo real y supervisor del servidor local llama.cpp.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

ACTIVE_ACTIVITIES: dict[str, Any] = {}
ACTIVITY_LOCK = threading.Lock()
ACTIVITY_STALE_SECONDS = 300

LLAMA_CPP_PROCESS_LOCK = threading.Lock()
LLAMA_CPP_PROCESS: subprocess.Popen[Any] | None = None


LLAMA_PID_FILE = Path(
    os.environ.get(
        "MYKOS_GATEWAY_STATE_DIR",
        str(Path.home() / ".mykos" / "gateway-state")
    )
) / "llama-server.pid"


def _process_starttime(pid: int) -> str:
    """Obtiene el identificador temporal único (starttime ticks) del proceso en Linux para evitar colisiones por reciclaje de PID."""
    try:
        stat_path = f"/proc/{pid}/stat"
        if os.path.isfile(stat_path):
            with open(stat_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            rparen = content.rfind(")")
            if rparen != -1:
                remainder = content[rparen + 1:].split()
                if len(remainder) > 19:
                    return remainder[19]
    except (OSError, IndexError):
        pass
    return ""


def stop_llama_cpp_server(model_path: str = "") -> None:
    """Libera el modelo CUDA configurado terminando únicamente la instancia lanzada por MyKOS."""
    global LLAMA_CPP_PROCESS
    with LLAMA_CPP_PROCESS_LOCK:
        tracked = LLAMA_CPP_PROCESS
        LLAMA_CPP_PROCESS = None
        target_pids: dict[int, str] = {}  # pid -> expected_starttime

        if tracked is not None and tracked.poll() is None:
            t_pid = int(tracked.pid)
            target_pids[t_pid] = _process_starttime(t_pid)

        # Recuperar PID del archivo de estado propio de MyKOS con su starttime
        if LLAMA_PID_FILE.is_file():
            try:
                raw_text = LLAMA_PID_FILE.read_text(encoding="utf-8").strip()
                saved_pid = 0
                saved_starttime = ""
                if raw_text.startswith("{"):
                    data = json.loads(raw_text)
                    if isinstance(data, dict):
                        saved_pid = int(data.get("pid", 0))
                        saved_starttime = str(data.get("starttime", "")).strip()
                elif raw_text:
                    saved_pid = int(raw_text)
                if saved_pid and saved_pid != os.getpid():
                    target_pids[saved_pid] = saved_starttime
                LLAMA_PID_FILE.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass

        current_uid = os.getuid() if hasattr(os, "getuid") else None
        for pid, expected_st in target_pids.items():
            if tracked is not None and pid == int(tracked.pid):
                try:
                    tracked.terminate()
                    tracked.wait(timeout=8)
                    continue
                except (OSError, subprocess.TimeoutExpired):
                    pass
            # Comprobaciones estrictas de seguridad de proceso:
            # 1. Verificación de PID reciclado mediante starttime
            if expected_st:
                current_st = _process_starttime(pid)
                if current_st and current_st != expected_st:
                    # El PID ha sido reasignado por el kernel a otro proceso completamente distinto
                    continue
            # 2. Mismo UID de usuario
            # 3. El binario debe ser efectivamente llama-server / llama.cpp
            try:
                if current_uid is not None:
                    proc_path = f"/proc/{pid}"
                    if os.path.exists(proc_path):
                        if os.stat(proc_path).st_uid != current_uid:
                            continue
                        cmdline_file = f"/proc/{pid}/cmdline"
                        if os.path.isfile(cmdline_file):
                            with open(cmdline_file, "rb") as f:
                                raw_cmd = f.read().replace(b"\x00", b" ").decode("utf-8", errors="replace").lower()
                            if "llama-server" not in raw_cmd and "llama.cpp" not in raw_cmd:
                                continue
                os.kill(pid, 15)
            except OSError:
                continue


def _activity_model_info(
    model_name: str,
    selected_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = selected_model if isinstance(selected_model, dict) else {}
    provider = selected.get("provider", "")
    remote = bool(selected.get("remote", "anthropic" in model_name or provider in {"openrouter", "nvidia_api", "kimi_api", "gemini_api", "mistral_api", "grok_api", "meta_ai_api"}))
    if "claude" in model_name.lower() or provider == "anthropic_oauth":
        return {
            "model": model_name,
            "model_label": str(selected.get("label") or "Claude Sonnet · claude.ai"),
            "provider_label": str(selected.get("provider_label") or "Claude Code · claude.ai OAuth"),
            "remote": True,
            "location": "remoto",
        }
    if provider == "openrouter":
        return {
            "model": model_name,
            "model_label": str(selected.get("label") or model_name),
            "provider_label": str(selected.get("provider_label") or "OpenRouter · OAuth"),
            "remote": True,
            "location": "remoto",
        }
    if provider == "nvidia_api":
        return {
            "model": model_name,
            "model_label": str(selected.get("label") or model_name),
            "provider_label": str(selected.get("provider_label") or "NVIDIA NIM · API"),
            "remote": True,
            "location": "remoto",
        }
    if provider == "kimi_api":
        return {
            "model": model_name,
            "model_label": str(selected.get("label") or model_name),
            "provider_label": str(selected.get("provider_label") or "Kimi · API"),
            "remote": True,
            "location": "remoto",
        }
    if provider == "gemini_api":
        return {
            "model": model_name,
            "model_label": str(selected.get("label") or model_name),
            "provider_label": str(selected.get("provider_label") or "Gemini · API"),
            "remote": True,
            "location": "remoto",
        }
    if provider == "mistral_api":
        return {
            "model": model_name,
            "model_label": str(selected.get("label") or model_name),
            "provider_label": str(selected.get("provider_label") or "Mistral · Vibe"),
            "remote": True,
            "location": "remoto",
        }
    return {
        "model": model_name,
        "model_label": str(selected.get("label") or model_name or "Modelo"),
        "provider_label": str(selected.get("provider_label") or "Ollama local"),
        "remote": remote,
        "location": "remoto" if remote else "local",
    }


def _purge_activity_locked(now: float | None = None) -> None:
    current = time.time() if now is None else now
    stale = [
        activity_id
        for activity_id, item in ACTIVE_ACTIVITIES.items()
        if current - float(item.get("updated_at_epoch", item.get("started_at_epoch", 0))) > ACTIVITY_STALE_SECONDS
    ]
    for activity_id in stale:
        ACTIVE_ACTIVITIES.pop(activity_id, None)


from datetime import datetime, timezone

_SYNC_GATEWAY_FN: Callable[..., None] | None = None


def set_sync_gateway_fn(fn: Callable[..., None]) -> None:
    global _SYNC_GATEWAY_FN
    _SYNC_GATEWAY_FN = fn


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def start_activity(
    activity_id: str,
    conversation_id: str,
    model_name: str,
    selected_model: dict[str, Any] | None = None,
) -> str:
    activity_id = activity_id.strip() or uuid.uuid4().hex
    now = time.time()
    info = _activity_model_info(model_name, selected_model)
    timestamp = _utc_now()
    with ACTIVITY_LOCK:
        _purge_activity_locked(now)
        ACTIVE_ACTIVITIES[activity_id] = {
            "id": activity_id,
            "conversation_id": conversation_id,
            **info,
            "status": "working",
            "phase": "preparing",
            "label": "Preparando petición…",
            "detail": f"{info['model_label']} · {info['location']}",
            "started_at": timestamp,
            "started_at_epoch": now,
            "updated_at": timestamp,
            "updated_at_epoch": now,
        }
        gateway_item = dict(ACTIVE_ACTIVITIES[activity_id])
    if _SYNC_GATEWAY_FN is not None:
        try:
            _SYNC_GATEWAY_FN("start", activity_id, gateway_item)
        except Exception:
            pass
    return activity_id


def update_activity(
    activity_id: str | None,
    *,
    selected_model: dict[str, Any] | None = None,
    status: str | None = None,
    phase: str | None = None,
    label: str | None = None,
    detail: str | None = None,
) -> None:
    if not activity_id:
        return
    with ACTIVITY_LOCK:
        item = ACTIVE_ACTIVITIES.get(activity_id)
        if item is None:
            return
        if selected_model is not None:
            item.update(_activity_model_info(str(item.get("model", "")), selected_model))
        if status is not None:
            item["status"] = status
        if phase is not None:
            item["phase"] = phase
        if label is not None:
            item["label"] = label
        if detail is not None:
            item["detail"] = detail
        item["updated_at"] = _utc_now()
        item["updated_at_epoch"] = time.time()
        gateway_item = dict(item)
    if _SYNC_GATEWAY_FN is not None:
        try:
            _SYNC_GATEWAY_FN("update", activity_id, gateway_item)
        except Exception:
            pass


def activity_public_view(
    activity_id: str = "",
    conversation_id: str = "",
) -> dict[str, Any]:
    with ACTIVITY_LOCK:
        _purge_activity_locked()
        item = ACTIVE_ACTIVITIES.get(activity_id) if activity_id else None
        if item is None and conversation_id:
            item = next(
                (
                    candidate
                    for candidate in ACTIVE_ACTIVITIES.values()
                    if candidate.get("conversation_id") == conversation_id
                ),
                None,
            )
        if item is None:
            return {"ok": True, "active": False, "status": "idle"}
        public = {
            key: value
            for key, value in item.items()
            if not key.endswith("_epoch")
        }
        public["active"] = True
        public["elapsed_seconds"] = max(0.0, time.time() - float(item.get("started_at_epoch", time.time())))
        public["heartbeat_age_seconds"] = max(0.0, time.time() - float(item.get("updated_at_epoch", time.time())))
        return {"ok": True, **public}


def finish_activity(activity_id: str | None) -> None:
    if not activity_id:
        return
    with ACTIVITY_LOCK:
        ACTIVE_ACTIVITIES.pop(activity_id, None)
    if _SYNC_GATEWAY_FN is not None:
        try:
            _SYNC_GATEWAY_FN("finish", activity_id, None)
        except Exception:
            pass

