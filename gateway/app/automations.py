"""Recordatorios locales persistentes de MyKOS.

El programador solo crea eventos locales. No envía correo, mensajería externa
ni accede al workspace real de MyKOS.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import gateway_store


ROOT = Path(__file__).resolve().parent
AUTOMATIONS_FILE = ROOT / "data" / "automations.json"
MAX_AUTOMATIONS = 200
MAX_EVENTS = 200
MAX_TITLE_CHARS = 180
MAX_MESSAGE_CHARS = 4_000
MAX_REPEAT_MINUTES = 7 * 24 * 60


class AutomationError(RuntimeError):
    """Error controlado de automatizaciones."""


_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_run_at(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AutomationError("Debes indicar cuándo debe ejecutarse el recordatorio.")
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise AutomationError("run_at debe ser una fecha ISO, por ejemplo 2026-09-24T10:30:00+02:00.") from error
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    parsed = parsed.astimezone(timezone.utc)
    if parsed <= _now():
        raise AutomationError("El recordatorio debe programarse en el futuro.")
    if parsed > _now() + timedelta(days=365):
        raise AutomationError("El recordatorio no puede programarse a más de un año.")
    return parsed


def _load() -> dict[str, Any]:
    data = gateway_store.load_document(
        "automations",
        legacy_file=AUTOMATIONS_FILE,
        default={"automations": [], "events": []},
    )
    if not isinstance(data, dict):
        return {"automations": [], "events": []}
    try:
        json.dumps(data)
    except (TypeError, ValueError):
        return {"automations": [], "events": []}
    automations = data.get("automations") if isinstance(data.get("automations"), list) else []
    events = data.get("events") if isinstance(data.get("events"), list) else []
    return {"automations": automations[-MAX_AUTOMATIONS:], "events": events[-MAX_EVENTS:]}


def _save(data: dict[str, Any]) -> None:
    gateway_store.save_document(
        "automations",
        data,
        legacy_file=AUTOMATIONS_FILE,
        indent=2,
        source="automations.scheduler",
    )


def _public_automation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id", "")),
        "type": "reminder",
        "title": str(item.get("title", "")),
        "message": str(item.get("message", "")),
        "run_at": str(item.get("run_at", "")),
        "repeat_minutes": int(item.get("repeat_minutes", 0) or 0),
        "enabled": bool(item.get("enabled", False)),
        "created_at": str(item.get("created_at", "")),
        "last_run_at": str(item.get("last_run_at", "")),
    }


def _public_event(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id", "")),
        "automation_id": str(item.get("automation_id", "")),
        "title": str(item.get("title", "")),
        "message": str(item.get("message", "")),
        "fired_at": str(item.get("fired_at", "")),
    }


def list_automations() -> dict[str, Any]:
    with _LOCK:
        data = _load()
    return {"ok": True, "action": "list_automations", "automations": [_public_automation(item) for item in data["automations"] if isinstance(item, dict)]}


def list_events(limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    with _LOCK:
        data = _load()
    events = [item for item in data["events"] if isinstance(item, dict)]
    return {"ok": True, "action": "list_automation_events", "events": [_public_event(item) for item in events[-limit:]]}


def prepare_create(arguments: dict[str, Any]) -> dict[str, Any]:
    title = arguments.get("title")
    message = arguments.get("message", "")
    if not isinstance(title, str) or not title.strip():
        raise AutomationError("El recordatorio necesita un título.")
    if not isinstance(message, str):
        raise AutomationError("El mensaje del recordatorio debe ser texto.")
    title = title.strip()
    message = message.strip()
    if len(title) > MAX_TITLE_CHARS or len(message) > MAX_MESSAGE_CHARS:
        raise AutomationError("El título o mensaje supera el límite permitido.")
    run_at = _parse_run_at(arguments.get("run_at"))
    try:
        repeat_minutes = int(arguments.get("repeat_minutes", 0) or 0)
    except (TypeError, ValueError) as error:
        raise AutomationError("repeat_minutes debe ser un número entero.") from error
    if repeat_minutes < 0 or repeat_minutes > MAX_REPEAT_MINUTES:
        raise AutomationError("repeat_minutes debe estar entre 0 y 10080 minutos.")
    return {
        "kind": "create_reminder",
        "title": title,
        "message": message,
        "run_at": _iso(run_at),
        "repeat_minutes": repeat_minutes,
    }


def prepare_delete(arguments: dict[str, Any]) -> dict[str, Any]:
    automation_id = str(arguments.get("id", "")).strip()
    if not automation_id or len(automation_id) > 80:
        raise AutomationError("Debes indicar un identificador de recordatorio válido.")
    return {"kind": "delete_reminder", "id": automation_id}


def create_approved(action: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        data = _load()
        active = [item for item in data["automations"] if isinstance(item, dict) and item.get("enabled")]
        if len(active) >= MAX_AUTOMATIONS:
            raise AutomationError("Se ha alcanzado el límite de recordatorios activos.")
        item = {
            "id": uuid.uuid4().hex,
            "title": str(action["title"]),
            "message": str(action.get("message", "")),
            "run_at": str(action["run_at"]),
            "repeat_minutes": int(action.get("repeat_minutes", 0) or 0),
            "enabled": True,
            "created_at": _iso(_now()),
            "last_run_at": "",
        }
        data["automations"].append(item)
        _save(data)
    return {"ok": True, "action": "create_reminder", "automation": _public_automation(item)}


def delete_approved(action: dict[str, Any]) -> dict[str, Any]:
    automation_id = str(action.get("id", ""))
    with _LOCK:
        data = _load()
        found = next((item for item in data["automations"] if isinstance(item, dict) and item.get("id") == automation_id), None)
        if found is None:
            raise AutomationError("El recordatorio no existe o ya fue eliminado.")
        data["automations"] = [item for item in data["automations"] if item is not found]
        _save(data)
    return {"ok": True, "action": "delete_reminder", "id": automation_id, "title": str(found.get("title", ""))}


def tick() -> int:
    now = _now()
    fired = 0
    with _LOCK:
        data = _load()
        changed = False
        for item in data["automations"]:
            if not isinstance(item, dict) or not item.get("enabled"):
                continue
            try:
                due = datetime.fromisoformat(str(item.get("run_at", "")).replace("Z", "+00:00")).astimezone(timezone.utc)
            except (ValueError, TypeError):
                item["enabled"] = False
                changed = True
                continue
            if due > now:
                continue
            event = {
                "id": uuid.uuid4().hex,
                "automation_id": str(item.get("id", "")),
                "title": str(item.get("title", "")),
                "message": str(item.get("message", "")),
                "fired_at": _iso(now),
            }
            data["events"].append(event)
            fired += 1
            repeat = int(item.get("repeat_minutes", 0) or 0)
            if repeat > 0:
                next_run = due
                while next_run <= now:
                    next_run += timedelta(minutes=repeat)
                item["run_at"] = _iso(next_run)
                item["last_run_at"] = _iso(now)
            else:
                item["enabled"] = False
                item["last_run_at"] = _iso(now)
            changed = True
        if len(data["events"]) > MAX_EVENTS:
            data["events"] = data["events"][-MAX_EVENTS:]
        if changed:
            _save(data)
    return fired


def _worker() -> None:
    while not _STOP.wait(1.0):
        try:
            tick()
        except (OSError, RuntimeError, AutomationError):
            pass


def start_scheduler() -> None:
    global _THREAD
    if _THREAD is not None and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=_worker, daemon=True, name="mykos-automations")
    _THREAD.start()


def stop_scheduler() -> None:
    global _THREAD
    _STOP.set()
    thread = _THREAD
    _THREAD = None
    if thread is not None and thread.is_alive():
        thread.join(timeout=2)
