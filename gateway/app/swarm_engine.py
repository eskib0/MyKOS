"""Motor nativo multi-agente MyKOS Swarm con persistencia ACID y ejecución real de herramientas."""

from __future__ import annotations

import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gateway_store import load_document, save_document

APP_ROOT = Path(__file__).resolve().parent
_DATA_ENV = os.environ.get("MYKOS_DATA_DIR", "").strip()
DATA_DIR = (
    Path(_DATA_ENV).expanduser().resolve()
    if _DATA_ENV
    else (APP_ROOT / "data" if os.access(APP_ROOT / "data" if (APP_ROOT / "data").exists() else APP_ROOT, os.W_OK) else (Path.home() / ".mykos" / "data").resolve())
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SWARM_DOC_NAME = "swarm"
SWARM_FILE = DATA_DIR / "swarm.json"
MAX_AUTO_HOPS = 6
MAX_BOARD_MESSAGES = 400
LOCAL_PROVIDERS = {"ollama", "llama_cpp", "llamacpp", "strata"}
VALID_PERMISSION_MODES = {"supervisado", "acceso_total"}
VALID_STATES = {"waiting", "working", "stopped", "killed"}
REMOTE_MODEL_PREFIXES = (
    "antigravity/",
    "qwen-cli/",
    "meta-ai/",
    "nvidia/",
    "kimi/",
    "gemini/",
    "mistral/",
    "anthropic/",
    "openrouter/",
    "grok/",
    "openai-codex-oauth/",
    "openai/",
    "claude-",
)

_MENTION_RE = re.compile(r"(?<![A-Za-z0-9_.-])@([a-zA-Z0-9][a-zA-Z0-9_-]{0,39})\b")

_STATE_LOCK = threading.RLock()
_RUNTIME_LOCK = threading.RLock()
_WAIT_COND = threading.Condition(_RUNTIME_LOCK)
_LOCAL_GPU_LOCK = threading.Lock()

_ACTIVE_THREADS: dict[str, threading.Thread] = {}
_ACTIVE_THREAD_KEYS: dict[str, tuple[int, int]] = {}
_PENDING_WAKE: set[str] = set()
_SWARM_EPOCH = 0
_WORKER_GEN: dict[str, int] = {}
_RUNTIME_HOOKS: dict[str, Any] = {}


def configure_runtime(**hooks: Any) -> None:
    """Registra los ejecutores y utilidades de server.py sin crear ciclos de importación."""
    for key, value in hooks.items():
        if value is not None:
            _RUNTIME_HOOKS[key] = value


def _get_server_module() -> Any:
    for mod_name in ("server", "__main__"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "run_model_until_result"):
            return mod
    import server  # type: ignore[import-not-found]
    return server


def _resolve_hook(name: str) -> Any:
    hook = _RUNTIME_HOOKS.get(name)
    if hook is not None:
        return hook
    server_mod = _get_server_module()
    return getattr(server_mod, name)


def _default_coordinator() -> dict[str, Any]:
    return {
        "name": "coordinator",
        "role": "Coordinador Principal (Chat MyKOS)",
        "model": "inherit",
        "state": "waiting",
        "last_read_seq": 0,
        "last_post_seq": 0,
        "last_post_time": "",
        "tools_used_count": 0,
        "last_error": "",
    }


def default_swarm_state(title: str = "Swarm MyKOS", permission_mode: str = "supervisado") -> dict[str, Any]:
    now = utc_now()
    mode = permission_mode if permission_mode in VALID_PERMISSION_MODES else "supervisado"
    return {
        "title": str(title or "Swarm MyKOS").strip() or "Swarm MyKOS",
        "created_at": now,
        "updated_at": now,
        "head": 0,
        "permission_mode": mode,
        "auto_hops": 0,
        "members": {
            "coordinator": _default_coordinator(),
        },
        "messages": [],
    }


def _normalise_loaded_state(raw: Any) -> dict[str, Any]:
    base = default_swarm_state()
    if not isinstance(raw, dict):
        return base
    now = utc_now()
    title = str(raw.get("title") or base["title"]).strip() or base["title"]
    mode = str(raw.get("permission_mode") or "supervisado").strip().casefold()
    if mode not in VALID_PERMISSION_MODES:
        mode = "supervisado"
    raw_members = raw.get("members")
    members: dict[str, dict[str, Any]] = {}
    if isinstance(raw_members, dict):
        for key, value in raw_members.items():
            if not isinstance(value, dict):
                continue
            cname = str(value.get("name") or key).strip().casefold()
            if not cname:
                continue
            state_val = str(value.get("state") or "waiting").strip().casefold()
            if state_val not in VALID_STATES:
                state_val = "waiting"
            members[cname] = {
                "name": cname,
                "role": str(value.get("role") or ("Coordinador Principal (Chat MyKOS)" if cname == "coordinator" else "Especialista")).strip(),
                "model": str(value.get("model") or "inherit").strip() or "inherit",
                "state": state_val,
                "last_read_seq": int(value.get("last_read_seq") or 0),
                "last_post_seq": int(value.get("last_post_seq") or 0),
                "last_post_time": str(value.get("last_post_time") or ""),
                "tools_used_count": int(value.get("tools_used_count") or 0),
                "last_error": str(value.get("last_error") or ""),
            }
    if "coordinator" not in members:
        members["coordinator"] = _default_coordinator()
    raw_messages = raw.get("messages")
    messages = [dict(item) for item in raw_messages if isinstance(item, dict)] if isinstance(raw_messages, list) else []
    max_seq = max((int(msg.get("seq") or 0) for msg in messages), default=0)
    head = max(int(raw.get("head") or 0), max_seq)
    try:
        auto_hops = max(0, int(raw.get("auto_hops") or 0))
    except (TypeError, ValueError):
        auto_hops = 0
    return {
        "title": title,
        "created_at": str(raw.get("created_at") or now),
        "updated_at": str(raw.get("updated_at") or now),
        "head": head,
        "permission_mode": mode,
        "auto_hops": auto_hops,
        "members": members,
        "messages": messages,
    }


def _load_state() -> dict[str, Any]:
    with _STATE_LOCK:
        raw = load_document(SWARM_DOC_NAME, legacy_file=SWARM_FILE, default=default_swarm_state())
        return _normalise_loaded_state(raw)


def _save_state(state: dict[str, Any]) -> None:
    with _STATE_LOCK:
        state["updated_at"] = utc_now()
        if len(state.get("messages", [])) > MAX_BOARD_MESSAGES:
            state["messages"] = state["messages"][-MAX_BOARD_MESSAGES:]
        save_document(SWARM_DOC_NAME, state, legacy_file=SWARM_FILE, indent=2, source="backend.swarm")


def normalize_agent_name(raw_name: str) -> str:
    """Normaliza nombres de trabajador: minúsculas, sin espacios y caracteres seguros."""
    stripped = str(raw_name or "").strip().lstrip("@").casefold()
    stripped = re.sub(r"\s+", "", stripped)
    return re.sub(r"[^a-z0-9_-]", "", stripped)[:40]


def extract_mentions(text: str) -> list[str]:
    """Extrae menciones @nombre (o @all) sin duplicados y conservando el orden."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _MENTION_RE.finditer(str(text or "")):
        token = match.group(1).strip().casefold()
        if token and token not in seen:
            seen.add(token)
            found.append(token)
    return found


def _compute_edges(messages: list[dict[str, Any]], members: dict[str, Any]) -> list[dict[str, Any]]:
    edge_map: dict[tuple[str, str], dict[str, Any]] = {}
    member_names = list(members.keys())
    for msg in messages:
        sender = str(msg.get("agent") or "").strip().casefold()
        if not sender:
            continue
        seq = int(msg.get("seq") or 0)
        mentions = msg.get("mentions") if isinstance(msg.get("mentions"), list) else extract_mentions(str(msg.get("text") or ""))
        targets: list[str] = []
        for mention in mentions:
            m = str(mention).strip().casefold()
            if m == "all":
                for cand in member_names:
                    if cand != sender and cand not in targets:
                        targets.append(cand)
            elif m in members and m != sender and m not in targets:
                targets.append(m)
        for target in targets:
            key = (sender, target)
            entry = edge_map.get(key)
            if entry is None:
                edge_map[key] = {"from": sender, "to": target, "count": 1, "last_seq": seq}
            else:
                entry["count"] += 1
                if seq > entry["last_seq"]:
                    entry["last_seq"] = seq
    return sorted(edge_map.values(), key=lambda item: (-item["count"], -item["last_seq"], item["from"], item["to"]))


def _sorted_member_list(members: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items = [dict(v) for v in members.values()]
    items.sort(key=lambda m: (0 if m["name"] == "coordinator" else 1, m["name"]))
    return items


def _build_status_payload(state: dict[str, Any], *, since_seq: int = 0, limit: int = 60) -> dict[str, Any]:
    all_messages = state.get("messages", [])
    filtered = [dict(msg) for msg in all_messages if int(msg.get("seq") or 0) > since_seq]
    if limit > 0 and len(filtered) > limit:
        filtered = filtered[-limit:]
    members = state.get("members", {})
    member_list = _sorted_member_list(members)
    workers = [m for m in member_list if m["name"] != "coordinator"]
    active_count = sum(1 for m in workers if m["state"] == "working")
    waiting_count = sum(1 for m in workers if m["state"] == "waiting")
    killed_count = sum(1 for m in workers if m["state"] == "killed")
    return {
        "ok": True,
        "title": state["title"],
        "created_at": state["created_at"],
        "updated_at": state["updated_at"],
        "head": state["head"],
        "permission_mode": state["permission_mode"],
        "auto_hops": state.get("auto_hops", 0),
        "members": members,
        "member_list": member_list,
        "messages": filtered,
        "edges": _compute_edges(all_messages, members),
        "counts": {
            "members": len(member_list),
            "workers": len(workers),
            "working": active_count,
            "waiting": waiting_count,
            "killed": killed_count,
            "messages": len(all_messages),
        },
    }


def get_swarm_status(since_seq: int = 0, limit: int = 60) -> dict[str, Any]:
    try:
        since = max(0, int(since_seq))
    except (TypeError, ValueError):
        since = 0
    try:
        lim = max(1, min(400, int(limit)))
    except (TypeError, ValueError):
        lim = 60
    state = _load_state()
    return _build_status_payload(state, since_seq=since, limit=lim)


def set_swarm_title(title: str = "", permission_mode: str | None = None) -> dict[str, Any]:
    clean_title = str(title or "").strip()
    clean_mode = str(permission_mode or "").strip().casefold() if permission_mode is not None else None
    if not clean_title and not clean_mode:
        return {"ok": False, "error": "Indica un título o un modo de permisos para actualizar el Swarm."}
    if clean_mode is not None and clean_mode not in VALID_PERMISSION_MODES:
        return {"ok": False, "error": "El modo de permisos debe ser 'supervisado' o 'acceso_total'."}
    with _STATE_LOCK:
        state = _load_state()
        if clean_title:
            state["title"] = clean_title[:120]
        if clean_mode is not None:
            state["permission_mode"] = clean_mode
        _save_state(state)
        return _build_status_payload(state)


def _get_cortex_engine() -> Any:
    try:
        server_mod = _get_server_module()
        if hasattr(server_mod, "_cortex_engine_and_root"):
            engine, _ = server_mod._cortex_engine_and_root()
            if engine is not None:
                return engine
    except Exception:
        pass
    from cortex import get_cortex  # type: ignore[import-not-found]
    return get_cortex()


def _slug_cortex_title(raw_title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|#\[\]]+', "-", str(raw_title or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
    return (cleaned[:64].strip(" .-_")) or "Informe Swarm"


def save_swarm_report_to_cortex(
    custom_title: str = "",
    seq: int | None = None,
    auto_archive: bool = False,
) -> dict[str, Any]:
    """Compila el informe del Swarm (o un mensaje concreto #seq) en Markdown y lo guarda en MyKOS Cortex."""
    with _STATE_LOCK:
        state = _load_state()
    messages = list(state.get("messages") or [])
    if not messages:
        return {"ok": False, "error": "El tablón del Swarm está vacío; no hay contenido que guardar en Cortex."}

    target_seq: int | None = None
    if seq is not None and str(seq).strip() != "":
        try:
            parsed_seq = int(seq)
        except (TypeError, ValueError):
            return {"ok": False, "error": "El número de mensaje #seq no es válido."}
        if parsed_seq > 0:
            target_seq = parsed_seq

    selected_msgs = (
        [m for m in messages if int(m.get("seq") or 0) == target_seq]
        if target_seq is not None
        else messages
    )
    if target_seq is not None and not selected_msgs:
        return {"ok": False, "error": f"No se encontró el mensaje #{target_seq} en el tablón del Swarm."}

    mission_title = str(custom_title or state.get("title") or "Swarm MyKOS").strip() or "Swarm MyKOS"
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hora_utc = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    slug_titulo = _slug_cortex_title(mission_title)
    suffix = f" - msg-{target_seq}" if target_seq is not None else ""
    rel_path = f"01 - Proyectos MyKOS/Informes Swarm/{fecha} - {slug_titulo}{suffix}.md"

    try:
        cortex_engine = _get_cortex_engine()
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo abrir MyKOS Cortex: {exc}"}

    if auto_archive:
        try:
            cortex_engine.get_note(rel_path)
            stamp = datetime.now(timezone.utc).strftime("%H%M%S")
            rel_path = f"01 - Proyectos MyKOS/Informes Swarm/{fecha} - {slug_titulo}{suffix}-{stamp}.md"
        except FileNotFoundError:
            pass
        except Exception:
            pass

    members = _sorted_member_list(state.get("members") or {})
    yaml_title = mission_title.replace('"', '\\"')
    if target_seq is not None:
        yaml_title = f"{yaml_title} (#{target_seq})".replace('"', '\\"')
    lines: list[str] = [
        "---",
        f'title: "{yaml_title}"',
        f"fecha: {fecha}",
        f'mision: "{mission_title.replace(chr(34), chr(92) + chr(34))}"',
        "tags: [swarm, informe, mykos]",
        f'aliases: ["{yaml_title}"]',
        "---",
        "",
        f"# 🐝 Informe Swarm: {mission_title}" + (f" (Mensaje #{target_seq})" if target_seq is not None else ""),
        "",
        "> Centro de mando: [[00 - Dashboard MyKOS]]",
        "",
        f"- **Fecha**: {fecha} ({hora_utc})",
        f"- **Modo de permisos**: `{state.get('permission_mode', 'supervisado')}`",
        f"- **Mensajes incluidos**: {len(selected_msgs)} (head actual: #{state.get('head', 0)})",
        f"- **Origen**: {'Auto-archivo al reiniciar Swarm' if auto_archive else 'Guardado manual desde MyKOS Swarm'}",
        "",
        "## 👥 Roster de Agentes",
        "",
        "| Agente | Rol | Modelo | Estado | Herramientas |",
        "| --- | --- | --- | --- | --- |",
    ]
    for member in members:
        m_name = str(member.get("name") or "")
        m_role = str(member.get("role") or "").replace("|", "\\|")
        m_model = str(member.get("model") or "inherit").replace("|", "\\|")
        m_state = str(member.get("state") or "waiting")
        m_tools = int(member.get("tools_used_count") or 0)
        lines.append(f"| `@{m_name}` | {m_role} | `{m_model}` | `{m_state}` | {m_tools} |")

    lines.extend(["", "## 📋 Tablón de Mensajes", ""])
    for msg in selected_msgs:
        m_seq = int(msg.get("seq") or 0)
        m_agent = str(msg.get("agent") or "unknown")
        m_role = str(msg.get("role") or "")
        m_model = str(msg.get("model") or "")
        m_dur = float(msg.get("duration_seconds") or 0.0)
        m_tools = [str(t) for t in (msg.get("tools_used") or []) if t]
        m_time = str(msg.get("created_at") or "")
        meta_parts = [p for p in [m_role, f"`{m_model}`" if m_model else "", f"{m_dur:.1f}s" if m_dur > 0 else "", m_time] if p]
        lines.append(f"### #{m_seq} · `@{m_agent}`")
        if meta_parts:
            lines.append(f"_{' · '.join(meta_parts)}_")
        if m_tools:
            lines.append(f"**Herramientas**: {', '.join(f'`{t}`' for t in m_tools)}")
        lines.append("")
        lines.append(str(msg.get("text") or "").strip())
        lines.append("")

    markdown = "\n".join(lines).rstrip() + "\n"
    try:
        saved = cortex_engine.save_note(rel_path, markdown)
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo guardar el informe en Cortex: {exc}"}

    saved_path = str((saved or {}).get("path") or rel_path) if isinstance(saved, dict) else rel_path
    return {
        "ok": True,
        "path": saved_path,
        "title": mission_title,
        "messages_count": len(selected_msgs),
        "auto_archived": bool(auto_archive),
    }


def reset_swarm(title: str = "Nuevo Swarm MyKOS", permission_mode: str | None = None) -> dict[str, Any]:
    global _SWARM_EPOCH
    clean_title = str(title or "").strip() or "Nuevo Swarm MyKOS"
    archived_path = ""
    with _RUNTIME_LOCK:
        _SWARM_EPOCH += 1
        _PENDING_WAKE.clear()
        _WORKER_GEN.clear()
        with _STATE_LOCK:
            current = _load_state()
            has_worker_reply = any(
                str(m.get("agent") or "").strip().casefold() != "coordinator"
                for m in (current.get("messages") or [])
            )
            if has_worker_reply:
                try:
                    archive_res = save_swarm_report_to_cortex(auto_archive=True)
                    if archive_res.get("ok"):
                        archived_path = str(archive_res.get("path") or "")
                except Exception:
                    archived_path = ""
            next_mode = str(permission_mode or current.get("permission_mode") or "supervisado").strip().casefold()
            if next_mode not in VALID_PERMISSION_MODES:
                next_mode = "supervisado"
            fresh = default_swarm_state(title=clean_title[:120], permission_mode=next_mode)
            _save_state(fresh)
        _WAIT_COND.notify_all()
        payload = _build_status_payload(fresh)
        if archived_path:
            payload["archived_path"] = archived_path
        return payload


def _is_local_model(model_name: str, model_entry: dict[str, Any] | None = None) -> bool:
    if isinstance(model_entry, dict):
        provider = str(model_entry.get("provider") or "").strip().casefold()
        if provider in LOCAL_PROVIDERS:
            return True
        if "remote" in model_entry:
            return not bool(model_entry.get("remote"))
    lower = str(model_name or "").strip().casefold()
    return not lower.startswith(REMOTE_MODEL_PREFIXES)


def _match_catalog_model(pool: list[dict[str, Any]], req: str) -> dict[str, Any] | None:
    if not pool or not req:
        return None
    req_cf = req.casefold()
    # 1. Exacta y exacta sin distinguir mayúsculas
    exact = next((m for m in pool if str(m.get("name", "")) == req), None)
    if exact is not None:
        return exact
    exact_ci = next((m for m in pool if str(m.get("name", "")).casefold() == req_cf), None)
    if exact_ci is not None:
        return exact_ci

    # Normalizar posibles prefijos explícitos de llama.cpp
    bare_req_cf = req_cf
    for prefix in ("llama_cpp/", "llamacpp/", "llama-cpp/"):
        if bare_req_cf.startswith(prefix):
            bare_req_cf = bare_req_cf[len(prefix):]
            break

    # 2. Alias de llama.cpp local ("mykos-cuda")
    if bare_req_cf in {"mykos-cuda", "llama-cuda", "gguf"}:
        llama_models = [m for m in pool if str(m.get("provider") or "").casefold() == "llama_cpp"]
        if llama_models:
            online_llama = next((m for m in llama_models if str(m.get("status") or "").casefold() == "online"), None)
            return online_llama or llama_models[0]

    # 3. Coincidencia quitando el prefijo de proveedor (<provider>/<id>)
    targets = {req_cf, bare_req_cf}
    stripped_match = next(
        (
            m for m in pool
            if str(m.get("name", "")).split("/", 1)[-1].casefold() in targets
            or str(m.get("id", "")).casefold() in targets
        ),
        None,
    )
    if stripped_match is not None:
        return stripped_match

    # 4. Coincidencia por sufijo o subcadena (priorizando modelos online y nombres más específicos)
    suffix_matches = [
        m for m in pool
        if str(m.get("name", "")).casefold().endswith("/" + bare_req_cf)
        or (bare_req_cf in str(m.get("name", "")).casefold())
    ]
    if suffix_matches:
        suffix_matches.sort(
            key=lambda m: (
                0 if str(m.get("status") or "").casefold() == "online" else 1,
                0 if str(m.get("name", "")).casefold().endswith("/" + bare_req_cf) else 1,
                len(str(m.get("name", ""))),
            )
        )
        return suffix_matches[0]
    return None


def _resolve_model_and_locality(requested_model: str) -> tuple[str, dict[str, Any], bool]:
    req = str(requested_model or "").strip()
    models: list[dict[str, Any]] = []
    try:
        get_models_fn = _resolve_hook("get_models")
        models = get_models_fn() or []
    except Exception:
        models = []

    chat_models = [m for m in models if isinstance(m, dict) and m.get("chat_capable", True)]
    if not req or req == "inherit":
        default_name = ""
        try:
            getter = _RUNTIME_HOOKS.get("default_model_getter")
            if callable(getter):
                default_name = str(getter() or "").strip()
            else:
                server_mod = _get_server_module()
                default_name = str(getattr(server_mod, "DEFAULT_MODEL", "") or "").strip()
        except Exception:
            default_name = ""
        if not default_name:
            try:
                choose_fn = _resolve_hook("choose_default_model")
                default_name = str(choose_fn(models) or "").strip()
            except Exception:
                default_name = ""
        req = default_name or (str(chat_models[0].get("name", "")) if chat_models else "") or "inherit"

    selected = _match_catalog_model(chat_models, req)
    if selected is None:
        selected = _match_catalog_model(models, req)
    if selected is None:
        req_cf = req.casefold()
        if req_cf.startswith("llama-cpp/"):
            req = "llama_cpp/" + req[len("llama-cpp/"):]
            req_cf = req.casefold()
        looks_llama = (
            req_cf == "mykos-cuda"
            or req_cf.startswith(("llama_cpp/", "llamacpp/", "llama-cpp/"))
            or any(tag in req_cf for tag in (".gguf", "-gguf", "_gguf"))
        )
        is_local = True if looks_llama else _is_local_model(req, None)
        provider = "llama_cpp" if looks_llama else ("ollama" if is_local else "remote")
        selected = {"name": req, "provider": provider, "remote": not is_local, "thinking_capable": looks_llama}
    else:
        resolved_name = str(selected.get("name") or "").strip()
        if resolved_name:
            req = resolved_name
        is_local = _is_local_model(req, selected)
    return req, selected, is_local


def _wake_worker(name: str, epoch: int, worker_gen: int) -> None:
    with _RUNTIME_LOCK:
        if epoch != _SWARM_EPOCH or _WORKER_GEN.get(name, 0) != worker_gen:
            return
        _PENDING_WAKE.add(name)
        existing = _ACTIVE_THREADS.get(name)
        existing_key = _ACTIVE_THREAD_KEYS.get(name)
        if existing is not None and existing.is_alive() and existing_key == (epoch, worker_gen):
            _WAIT_COND.notify_all()
            return
        thread = threading.Thread(
            target=_worker_loop,
            args=(name, epoch, worker_gen),
            daemon=True,
            name=f"mykos-swarm-{name}",
        )
        _ACTIVE_THREADS[name] = thread
        _ACTIVE_THREAD_KEYS[name] = (epoch, worker_gen)
        thread.start()
        _WAIT_COND.notify_all()


def _resolve_targets(mentions: list[str], sender: str, members: dict[str, dict[str, Any]]) -> list[str]:
    targets: list[str] = []
    has_all = "all" in mentions
    if has_all:
        for mname, member in members.items():
            if mname != "coordinator" and mname != sender and member.get("state") != "killed":
                if mname not in targets:
                    targets.append(mname)
    for mention in mentions:
        if mention == "all":
            continue
        member = members.get(mention)
        if member and mention != "coordinator" and mention != sender and member.get("state") != "killed":
            if mention not in targets:
                targets.append(mention)
    return targets


def _format_worker_context(state: dict[str, Any], worker_name: str, up_to_seq: int) -> tuple[str, list[dict[str, str]]]:
    members = state.get("members", {})
    member = members.get(worker_name, {})
    role = str(member.get("role") or "Especialista")
    last_read = int(member.get("last_read_seq") or 0)

    user_profile = ""
    core_memory = ""
    try:
        user_profile = str(_resolve_hook("load_user_profile")() or "").strip()
    except Exception:
        user_profile = ""
    try:
        core_memory = str(_resolve_hook("load_core_memory")() or "").strip()
    except Exception:
        core_memory = ""

    roster_lines = [
        f"- @{m['name']} | rol: {m['role']} | modelo: {m['model']} | estado: {m['state']}"
        for m in _sorted_member_list(members)
    ]
    memory_blocks: list[str] = []
    if user_profile:
        memory_blocks.append(f"## Perfil del Usuario\n{user_profile}")
    if core_memory:
        memory_blocks.append(f"## Memoria Persistente MyKOS Cortex\n{core_memory}")
    memory_text = ("\n\n" + "\n\n".join(memory_blocks)) if memory_blocks else ""

    system_prompt = (
        f"Eres @{worker_name}, un agente especialista trabajando dentro del motor nativo multi-agente MyKOS Swarm.\n"
        f"Tu rol asignado es: {role}.\n"
        f"Misión activa del Swarm: {state.get('title', 'Swarm MyKOS')}.\n"
        f"Modo de permisos del Swarm: {state.get('permission_mode', 'supervisado')}.\n\n"
        "REGLAS DE OPERACIÓN EN EL SWARM:\n"
        "1. Dispones de todas las herramientas reales de MyKOS (sistema de archivos, shell, git, cortex, web, documentos, REA, multimedia y sistema). Úsalas para verificar hechos antes de afirmar resultados.\n"
        "2. Tu respuesta final se publicará automáticamente en el tablón compartido del Swarm con tu firma; NO ejecutes './bin/mykos swarm post' ni herramientas swarm_* manualmente salvo que tu misión lo ordene explícitamente.\n"
        "3. Referencia mensajes anteriores del tablón usando #seq (por ejemplo #1, #3).\n"
        "4. Si necesitas que otro compañero actúe a continuación, menciónalo explícitamente con @nombre (o @coordinator cuando reportes resultados finales o necesites decisión).\n"
        "5. Responde en español, de forma técnica, concisa y accionable.\n\n"
        "ROSTER ACTUAL DEL SWARM:\n"
        + "\n".join(roster_lines)
        + memory_text
    )

    relevant_msgs = [msg for msg in state.get("messages", []) if int(msg.get("seq") or 0) <= up_to_seq][-40:]
    board_lines: list[str] = []
    for msg in relevant_msgs:
        seq = int(msg.get("seq") or 0)
        author = str(msg.get("agent") or "unknown")
        marker = " [NUEVO]" if seq > last_read else ""
        tools_tag = f" [tools: {', '.join(msg['tools_used'])}]" if msg.get("tools_used") else ""
        board_lines.append(f"#{seq}{marker} @{author} ({msg.get('role', '')}){tools_tag}:\n{msg.get('text', '')}")

    user_prompt = (
        f"TABLÓN COMPARTIDO (#1..#{up_to_seq}):\n\n"
        + ("\n\n---\n\n".join(board_lines) if board_lines else "(El tablón está vacío)")
        + f"\n\n---\nActúa ahora como @{worker_name}. Atiende las peticiones dirigidas a ti o a @all (especialmente desde #{last_read + 1} en adelante), usa las herramientas necesarias y entrega tu respuesta."
    )
    return system_prompt, [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _worker_turn(worker_name: str, target_seq: int, epoch: int, worker_gen: int) -> None:
    with _STATE_LOCK:
        if epoch != _SWARM_EPOCH or _WORKER_GEN.get(worker_name, 0) != worker_gen:
            return
        state = _load_state()
        member = state["members"].get(worker_name)
        if not member or member.get("state") == "killed":
            return
        system_prompt, worker_messages = _format_worker_context(state, worker_name, target_seq)
        _ = system_prompt
        requested_model = str(member.get("model") or "inherit")
        permission_mode = str(state.get("permission_mode") or "supervisado")

    effective_model, selected_model, is_local = _resolve_model_and_locality(requested_model)
    started = time.monotonic()
    tools_used: list[str] = []
    response_text = ""
    error_text = ""

    try:
        run_model_fn = _resolve_hook("run_model_until_result")
        norm_fn = _resolve_hook("normalise_generation_settings")
        generation = norm_fn({}, selected_model)
        activity_id = f"swarm_{worker_name}_{target_seq}_{uuid.uuid4().hex[:6]}"
        conversation_id = f"swarm:{worker_name}"

        def _invoke() -> dict[str, Any]:
            return run_model_fn(
                effective_model,
                worker_messages,
                conversation_id,
                supports_vision=False,
                generation=generation,
                activity_id=activity_id,
                permission_mode=permission_mode,
                remote_worker=True,
            )

        if is_local:
            with _LOCAL_GPU_LOCK:
                result = _invoke()
        else:
            result = _invoke()

        if isinstance(result, dict):
            tools_used = [str(t) for t in (result.get("tools_used") or []) if str(t).strip()]
            msg_obj = result.get("message")
            if isinstance(msg_obj, dict):
                response_text = str(msg_obj.get("content") or "").strip()
            elif isinstance(result.get("pending_action"), dict):
                pending = result["pending_action"]
                tool_name = str(pending.get("tool_name") or "")
                approval_id = str(pending.get("id") or "")
                proposal = str(result.get("proposal") or "").strip()
                response_text = (
                    f"{proposal}\n\n" if proposal else ""
                ) + f"@coordinator Acción sensible pendiente de aprobación: `{tool_name}` (id: `{approval_id}`)."
            elif isinstance(result.get("content"), str):
                response_text = str(result["content"]).strip()
        if not response_text:
            response_text = "He revisado la tarea asignada y completado el turno sin salida textual adicional."
    except Exception as exc:
        error_text = str(exc)

    duration = round(max(0.0, time.monotonic() - started), 2)

    with _RUNTIME_LOCK:
        if epoch != _SWARM_EPOCH or _WORKER_GEN.get(worker_name, 0) != worker_gen:
            return

    with _STATE_LOCK:
        state = _load_state()
        member = state["members"].get(worker_name)
        if not member or member.get("state") == "killed":
            return
        member["last_read_seq"] = max(int(member.get("last_read_seq") or 0), target_seq)
        member["tools_used_count"] = int(member.get("tools_used_count") or 0) + len(tools_used)
        if error_text:
            member["last_error"] = error_text
        else:
            member["last_error"] = ""
        _save_state(state)

    if error_text:
        post_board_message(
            worker_name,
            f"⚠️ Error al ejecutar el turno ({effective_model}): {error_text}",
            model=effective_model,
            tools_used=tools_used,
            duration_seconds=duration,
            trigger_wake=False,
        )
    else:
        post_board_message(
            worker_name,
            response_text,
            model=effective_model,
            tools_used=tools_used,
            duration_seconds=duration,
            trigger_wake=True,
        )


def _worker_loop(worker_name: str, epoch: int, worker_gen: int) -> None:
    try:
        while True:
            with _RUNTIME_LOCK:
                if epoch != _SWARM_EPOCH or _WORKER_GEN.get(worker_name, 0) != worker_gen:
                    return
                if worker_name not in _PENDING_WAKE:
                    with _STATE_LOCK:
                        state = _load_state()
                        member = state["members"].get(worker_name)
                        if member and member.get("state") == "working":
                            member["state"] = "waiting"
                            _save_state(state)
                    return
                _PENDING_WAKE.discard(worker_name)
                with _STATE_LOCK:
                    state = _load_state()
                    member = state["members"].get(worker_name)
                    if not member or member.get("state") == "killed":
                        return
                    member["state"] = "working"
                    member["last_error"] = ""
                    target_seq = int(state.get("head") or 0)
                    _save_state(state)
                _WAIT_COND.notify_all()

            _worker_turn(worker_name, target_seq, epoch, worker_gen)
    finally:
        with _RUNTIME_LOCK:
            current_thread = threading.current_thread()
            if _ACTIVE_THREADS.get(worker_name) is current_thread:
                _ACTIVE_THREADS.pop(worker_name, None)
                _ACTIVE_THREAD_KEYS.pop(worker_name, None)
            if epoch == _SWARM_EPOCH and _WORKER_GEN.get(worker_name, 0) == worker_gen:
                with _STATE_LOCK:
                    state = _load_state()
                    member = state["members"].get(worker_name)
                    if member and member.get("state") == "working":
                        member["state"] = "waiting"
                        _save_state(state)
            _WAIT_COND.notify_all()


def add_worker(
    name: str,
    role: str = "Especialista",
    brief: str = "",
    model: str = "inherit",
    permission_mode: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    clean_name = normalize_agent_name(name)
    if not clean_name:
        return {"ok": False, "error": "Nombre de trabajador no válido (usa letras minúsculas, números o guiones)."}
    if clean_name in {"coordinator", "all", "system"}:
        return {"ok": False, "error": f"El nombre '@{clean_name}' está reservado en el Swarm."}

    clean_role = str(role or "Especialista").strip()[:100] or "Especialista"
    clean_model = str(model or "inherit").strip() or "inherit"
    if clean_model != "inherit":
        clean_model, _, _ = _resolve_model_and_locality(clean_model)
    clean_brief = str(brief or "").strip()

    with _RUNTIME_LOCK:
        epoch = _SWARM_EPOCH
        worker_gen = _WORKER_GEN.get(clean_name, 0) + 1
        _WORKER_GEN[clean_name] = worker_gen

        with _STATE_LOCK:
            state = _load_state()
            if title and str(title).strip():
                state["title"] = str(title).strip()[:120]
            if permission_mode is not None:
                pm = str(permission_mode).strip().casefold()
                if pm in VALID_PERMISSION_MODES:
                    state["permission_mode"] = pm

            existing = state["members"].get(clean_name) or {}
            state["members"][clean_name] = {
                "name": clean_name,
                "role": clean_role,
                "model": clean_model,
                "state": "waiting",
                "last_read_seq": int(existing.get("last_read_seq") or 0),
                "last_post_seq": int(existing.get("last_post_seq") or 0),
                "last_post_time": str(existing.get("last_post_time") or ""),
                "tools_used_count": int(existing.get("tools_used_count") or 0),
                "last_error": "",
            }
            _save_state(state)

    if clean_brief:
        posted = post_board_message("coordinator", f"@{clean_name} {clean_brief}", trigger_wake=True)
        return posted
    return get_swarm_status()


def post_board_message(
    agent: str,
    text: str,
    model: str = "",
    tools_used: list[str] | None = None,
    duration_seconds: float = 0.0,
    trigger_wake: bool = True,
) -> dict[str, Any]:
    sender = normalize_agent_name(agent) or "coordinator"
    if str(agent or "").strip().casefold().lstrip("@") == "coordinator":
        sender = "coordinator"
    body = str(text or "").strip()
    if not body:
        return {"ok": False, "error": "El mensaje para el tablón no puede estar vacío."}

    clean_tools = [str(item).strip() for item in (tools_used or []) if str(item).strip()]
    try:
        dur = round(max(0.0, float(duration_seconds or 0.0)), 2)
    except (TypeError, ValueError):
        dur = 0.0

    with _RUNTIME_LOCK:
        epoch = _SWARM_EPOCH
        woken_targets: list[str] = []
        loop_guarded = False

        with _STATE_LOCK:
            state = _load_state()
            if sender not in state["members"]:
                if sender == "coordinator":
                    state["members"]["coordinator"] = _default_coordinator()
                else:
                    return {"ok": False, "error": f"El agente '@{sender}' no pertenece al Swarm actual."}

            sender_member = state["members"][sender]
            next_seq = int(state.get("head") or 0) + 1
            created = utc_now()
            mentions = extract_mentions(body)
            resolved_model = str(model or sender_member.get("model") or "inherit")
            msg_record = {
                "seq": next_seq,
                "agent": sender,
                "role": str(sender_member.get("role") or ""),
                "model": resolved_model,
                "text": body,
                "mentions": mentions,
                "tools_used": clean_tools,
                "duration_seconds": dur,
                "created_at": created,
            }
            state["head"] = next_seq
            state["messages"].append(msg_record)
            sender_member["last_post_seq"] = next_seq
            sender_member["last_post_time"] = created
            sender_member["last_read_seq"] = max(int(sender_member.get("last_read_seq") or 0), next_seq)

            if sender == "coordinator":
                state["auto_hops"] = 0

            targets = _resolve_targets(mentions, sender, state["members"]) if trigger_wake else []
            if targets:
                if sender != "coordinator" and int(state.get("auto_hops") or 0) >= MAX_AUTO_HOPS:
                    loop_guarded = True
                    msg_record["text"] = (
                        f"{body}\n\n[Protección anti-bucle: se alcanzó MAX_AUTO_HOPS={MAX_AUTO_HOPS} "
                        "sin intervención de @coordinator; no se despertarán más turnos automáticos.]"
                    )
                else:
                    if sender != "coordinator":
                        state["auto_hops"] = int(state.get("auto_hops") or 0) + 1
                    woken_targets = list(targets)
            _save_state(state)

        for target in woken_targets:
            worker_gen = _WORKER_GEN.get(target, 0)
            _wake_worker(target, epoch, worker_gen)

        _WAIT_COND.notify_all()
        payload = _build_status_payload(state)
        payload["message"] = msg_record
        payload["woken"] = woken_targets
        payload["loop_guarded"] = loop_guarded
        return payload


def wait_for_swarm_settlement(targets: list[str], after_seq: int, wait_seconds: float = 0.0) -> dict[str, Any]:
    """Espera hasta que los trabajadores despertados completen su turno o venza el timeout."""
    timeout = max(0.0, min(120.0, float(wait_seconds or 0.0)))
    if timeout <= 0.0 or not targets:
        return get_swarm_status(since_seq=after_seq, limit=60)

    deadline = time.monotonic() + timeout
    with _RUNTIME_LOCK:
        while True:
            state = _load_state()
            members = state.get("members", {})
            tracked = set(targets)
            for msg in state.get("messages", []):
                if int(msg.get("seq") or 0) > after_seq:
                    for m in (msg.get("mentions") or []):
                        if m == "all":
                            tracked.update(k for k in members if k != "coordinator")
                        elif m in members and m != "coordinator":
                            tracked.add(m)
            busy = False
            for name in tracked:
                if name in _PENDING_WAKE:
                    busy = True
                    break
                thread = _ACTIVE_THREADS.get(name)
                member = members.get(name) or {}
                if member.get("state") == "killed":
                    continue
                if (thread is not None and thread.is_alive()) or member.get("state") == "working":
                    busy = True
                    break
            if not busy:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _WAIT_COND.wait(timeout=min(remaining, 0.5))

    return get_swarm_status(since_seq=after_seq, limit=100)


def kill_worker(name: str) -> dict[str, Any]:
    raw = str(name or "").strip().lstrip("@").casefold()
    if not raw:
        return {"ok": False, "error": "Indica el nombre del agente a detener (o 'all')."}
    if raw == "coordinator":
        return {"ok": False, "error": "No se puede detener al coordinador principal."}

    with _RUNTIME_LOCK:
        with _STATE_LOCK:
            state = _load_state()
            if raw == "all":
                for mname, member in state["members"].items():
                    if mname == "coordinator":
                        continue
                    member["state"] = "killed"
                    _PENDING_WAKE.discard(mname)
                    _WORKER_GEN[mname] = _WORKER_GEN.get(mname, 0) + 1
            else:
                norm = normalize_agent_name(raw)
                if norm not in state["members"]:
                    return {"ok": False, "error": f"No existe el agente '@{norm}' en el Swarm."}
                state["members"][norm]["state"] = "killed"
                _PENDING_WAKE.discard(norm)
                _WORKER_GEN[norm] = _WORKER_GEN.get(norm, 0) + 1
            _save_state(state)
        _WAIT_COND.notify_all()
        return _build_status_payload(state)
