"""Herramientas de orquestación del motor nativo multi-agente MyKOS Swarm."""

from __future__ import annotations

from typing import Any

from .base import ToolError


def _engine() -> Any:
    import swarm_engine

    return swarm_engine


def _swarm_status(arguments: dict[str, Any]) -> dict[str, Any]:
    raw_since = arguments.get("since_seq", 0)
    raw_limit = arguments.get("limit", 30)
    try:
        since_seq = max(0, int(raw_since or 0))
    except (TypeError, ValueError) as error:
        raise ToolError("since_seq debe ser un número entero.") from error
    try:
        limit = max(1, min(100, int(raw_limit or 30)))
    except (TypeError, ValueError) as error:
        raise ToolError("limit debe ser un entero entre 1 y 100.") from error
    return _engine().get_swarm_status(since_seq=since_seq, limit=limit)


def _swarm_add_worker(arguments: dict[str, Any]) -> dict[str, Any]:
    name = str(arguments.get("name", "") or "").strip()
    role = str(arguments.get("role", "Especialista") or "Especialista").strip()
    brief = str(arguments.get("brief", "") or "").strip()
    model = str(arguments.get("model", "inherit") or "inherit").strip()
    raw_title = arguments.get("title")
    title = str(raw_title).strip() if isinstance(raw_title, str) and raw_title.strip() else None
    if not name:
        raise ToolError("Debes indicar «name» para crear el trabajador en el Swarm.")
    if not brief:
        raise ToolError("Debes indicar «brief» con la misión del trabajador.")
    return _engine().add_worker(name=name, role=role, brief=brief, model=model, title=title)


def _swarm_post(arguments: dict[str, Any]) -> dict[str, Any]:
    text = str(arguments.get("text", "") or "").strip()
    if not text:
        raise ToolError("Debes indicar «text» para publicar en el tablón del Swarm.")
    raw_wait = arguments.get("wait_seconds", 0)
    try:
        wait_seconds = max(0.0, min(45.0, float(raw_wait or 0.0)))
    except (TypeError, ValueError) as error:
        raise ToolError("wait_seconds debe ser un número entre 0 y 45.") from error

    engine = _engine()
    res = engine.post_board_message("coordinator", text, trigger_wake=True)
    if not res.get("ok"):
        return res
    posted = res.get("message") if isinstance(res.get("message"), dict) else {}
    posted_seq = int(posted.get("seq") or 0)
    woken = res.get("woken") if isinstance(res.get("woken"), list) else []
    if wait_seconds > 0.0 and woken:
        settled = engine.wait_for_swarm_settlement(woken, after_seq=max(0, posted_seq - 1), wait_seconds=wait_seconds)
        settled["posted_message"] = posted
        settled["woken"] = woken
        settled["waited_seconds"] = wait_seconds
        return settled
    return res


def _swarm_read_board(arguments: dict[str, Any]) -> dict[str, Any]:
    raw_since = arguments.get("since_seq", 0)
    raw_limit = arguments.get("limit", 40)
    try:
        since_seq = max(0, int(raw_since or 0))
    except (TypeError, ValueError) as error:
        raise ToolError("since_seq debe ser un número entero.") from error
    try:
        limit = max(1, min(150, int(raw_limit or 40)))
    except (TypeError, ValueError) as error:
        raise ToolError("limit debe ser un entero entre 1 y 150.") from error
    return _engine().get_swarm_status(since_seq=since_seq, limit=limit)


def _swarm_kill(arguments: dict[str, Any]) -> dict[str, Any]:
    reset = bool(arguments.get("reset", False))
    name = str(arguments.get("name", "") or "").strip()
    title = str(arguments.get("title", "") or "").strip()
    engine = _engine()
    if reset:
        return engine.reset_swarm(title=title or "Nuevo Swarm MyKOS")
    if not name:
        raise ToolError("Debes indicar «name» (o 'all') o activar «reset: true».")
    return engine.kill_worker(name)


def _swarm_save_cortex(arguments: dict[str, Any]) -> dict[str, Any]:
    title = str(arguments.get("title", "") or "").strip()
    raw_seq = arguments.get("seq")
    seq: int | None = None
    if raw_seq is not None and str(raw_seq).strip() != "":
        try:
            seq = int(raw_seq)
        except (TypeError, ValueError) as error:
            raise ToolError("seq debe ser un número entero.") from error
    return _engine().save_swarm_report_to_cortex(custom_title=title, seq=seq)
