"""Sub-módulo de verificación de integridad y prevención de afirmaciones no demostradas.

Comprueba que las respuestas del asistente no afirmen haber realizado acciones (crear archivos,
ejecutar comandos, modificar configuración) sin que existan registros verificados de ejecución
de herramientas en el turno actual.
"""

from __future__ import annotations

import json
import re
from typing import Any

from tools.schemas import SENSITIVE_TOOL_NAMES
from .claude import verified_tool_ledger_for_prompt

INTEGRITY_GUARD_MESSAGE = (
    "AVISO DEL SISTEMA: en tu respuesta dices que hiciste algo ({claims}), pero en este turno "
    "{evidence}. Haz UNA de estas dos cosas: "
    "1) Llama ahora a la herramienta que hace falta (p. ej. find_project_paths, list_project_files o read_project_file). "
    "2) Responde diciendo claramente que NO lo has hecho todavía. "
    "No repitas que lo hiciste ni inventes el contenido de ningún archivo."
)

MAX_INTEGRITY_GUARD_RETRIES = 1
MAX_VERIFIED_TOOL_TRACE = 12

_WRITE_CLAIM_VERBS = (
    "guardado|guardada|creado|creada|escrito|escrita|editado|editada|modificado|modificada|"
    "actualizado|actualizada|borrado|borrada|eliminado|eliminada|instalado|instalada|"
    "enviado|enviada|movido|movida|renombrado|renombrada|aplicado|aplicada|reiniciado|reiniciada|"
    "detenido|detenida|lanzado|lanzada|añadido|añadida|registrado|registrada|commiteado"
)
_CHECK_CLAIM_VERBS = (
    "ejecutado|ejecutada|comprobado|comprobada|verificado|verificada|probado|probada|reproducido|"
    "revisado|revisada|leído|leida|leido|buscado|localizado|localizada|abierto|abierta|"
    "consultado|consultada|analizado|analizada|inspeccionado|inspeccionada|listado|listada"
)
_ACTION_CLAIM_RE = re.compile(
    r"(?<![\wáéíóúñ])(?P<neg>no\s+)?(?:ya\s+)?(?:(?:te|le|lo|la|los|las|me)\s+)?"
    r"(?:he|hemos|acabo\s+de|se\s+ha|se\s+han|ya\s+est[aá]|queda|qued[oó])\s+"
    rf"(?:(?:ya|todo|correctamente)\s+)?(?P<verb>{_WRITE_CLAIM_VERBS}|{_CHECK_CLAIM_VERBS})\b",
    re.IGNORECASE,
)

INTEGRITY_UNVERIFIED_NOTE = (
    "\n\n⚠️ Aviso del sistema: esta respuesta dice que se hizo algo, pero MyKOS no registró ninguna "
    "herramienta que lo confirme. No lo des por hecho."
)


def _decode_tool_message(message: dict[str, Any]) -> dict[str, Any] | None:
    try:
        decoded = json.loads(str(message.get("content", "")))
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def current_turn_tool_trace(
    messages: list[dict[str, Any]],
    max_trace: int = MAX_VERIFIED_TOOL_TRACE,
) -> list[dict[str, Any]]:
    """Evidence of tools really executed by the host since Usuario's last message.

    Valid for every provider because it is derived from the role=tool messages
    the host itself appended, never from what the model said.
    """
    start = 0
    for index in range(len(messages) - 1, -1, -1):
        item = messages[index]
        if isinstance(item, dict) and item.get("role") == "user" and not item.get("integrity_guard"):
            start = index + 1
            break
    trace: list[dict[str, Any]] = []
    for item in messages[start:]:
        if not isinstance(item, dict) or item.get("role") != "tool":
            continue
        decoded = _decode_tool_message(item)
        if decoded is None:
            trace.append({"tool": "", "ok": False})
            continue
        name = str(decoded.get("action") or decoded.get("tool") or "").strip()
        entry: dict[str, Any] = {"tool": name, "ok": bool(decoded.get("ok"))}
        error = str(decoded.get("error", "")).strip()
        if error:
            entry["error"] = error[:500]
        trace.append(entry)
    return trace[-max_trace:]


def unverified_action_claim_reason(
    content: str,
    trace: list[dict[str, Any]],
    sensitive_tool_names: set[str] | None = None,
) -> str:
    """Return a correction when the answer claims an action the host did not see.

    Conservative on purpose: only first-person/past-tense claims of writing or
    running something are checked, and negated ones ("no he guardado") pass.
    """
    if sensitive_tool_names is None:
        sensitive_tool_names = SENSITIVE_TOOL_NAMES
    text = re.sub(r"\s+", " ", str(content or ""))
    if not text:
        return ""
    claimed: list[str] = []
    for match in _ACTION_CLAIM_RE.finditer(text):
        if match.group("neg"):
            continue
        verb = match.group("verb").casefold()
        if verb not in claimed:
            claimed.append(verb)
    if not claimed:
        return ""
    ok_entries = [entry for entry in trace if entry.get("ok")]
    claims_text = ", ".join(claimed[:4])
    if not ok_entries:
        return INTEGRITY_GUARD_MESSAGE.format(
            claims=claims_text,
            evidence="no hay ningún RESULTADO-DE-HERRAMIENTA correcto que lo confirme",
        )
    writes = {verb for verb in claimed if re.fullmatch(_WRITE_CLAIM_VERBS, verb)}
    if writes and not any(str(entry.get("tool", "")) in sensitive_tool_names for entry in ok_entries):
        used = ", ".join(sorted({str(entry.get("tool", "")) for entry in ok_entries if entry.get("tool")})) or "ninguna"
        return INTEGRITY_GUARD_MESSAGE.format(
            claims=claims_text,
            evidence=f"solo se usaron herramientas de lectura ({used}); ninguna escribió ni cambió nada",
        )
    return ""


def inline_verified_ledger(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy the history adding the host-verified ledger to past assistant turns.

    Claude's flattener already does this; the other providers (Ollama, llama.cpp,
    Gemini...) only see role/content, so the evidence must travel inside content.
    Assistant turns without a ledger are marked as unverified so the model does
    not treat its own old claims as facts.
    """
    prepared: list[dict[str, Any]] = []
    for item in messages:
        if not isinstance(item, dict) or item.get("role") != "assistant" or item.get("tool_calls"):
            prepared.append(item)
            continue
        content = str(item.get("content", ""))
        if content.lstrip().startswith('{"kind"') or "<registro-verificado-del-host>" in content:
            prepared.append(item)
            continue
        ledger = verified_tool_ledger_for_prompt(item)
        suffix = ledger or "<registro-verificado-del-host>sin registro de herramientas para este mensaje</registro-verificado-del-host>"
        copy = dict(item)
        copy["content"] = f"{content}\n{suffix}"
        prepared.append(copy)
    return prepared


def integrity_check_answer(
    messages: list[dict[str, Any]],
    content: str,
    retries: int,
    max_retries: int = MAX_INTEGRITY_GUARD_RETRIES,
    sensitive_tool_names: set[str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Common final-answer check for every provider loop.

    Returns (action, trace): action is "ok", "retry" (a guard message was
    appended to `messages`) or "warn" (retries exhausted; caller must append a
    visible warning instead of presenting the claim as a fact).
    """
    trace = current_turn_tool_trace(messages)
    reason = unverified_action_claim_reason(content, trace, sensitive_tool_names=sensitive_tool_names)
    if not reason:
        return "ok", trace
    if retries >= max_retries:
        return "warn", trace
    messages.append({"role": "assistant", "content": content, "integrity_guard": True})
    messages.append({"role": "user", "content": reason, "integrity_guard": True})
    return "retry", trace
