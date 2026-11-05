"""Adaptador de integración para Claude Code CLI mediante suscripción claude.ai OAuth.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from anthropic_api import get_anthropic_api_key
from tools import TOOL_SCHEMAS, _desktop_session_environment
from worker_helpers import ApiError

CLAUDE_MODEL_NAME = "claude-sonnet-oauth"
CLAUDE_MODEL_LABEL = "Claude Sonnet · OAuth"
CLAUDE_CLI_MODEL = os.environ.get("MYKOS_CLAUDE_MODEL", "sonnet").strip() or "sonnet"
CLAUDE_CONTEXT_LENGTH = 131_072
CLAUDE_STATUS_CACHE_SECONDS = 30.0
CLAUDE_STATUS_LOCK = threading.Lock()
CLAUDE_STATUS_CACHE: dict[str, Any] = {"checked_at": 0.0, "status": None}
CLAUDE_LOGIN_PROCESS: subprocess.Popen[Any] | None = None

MAX_VERIFIED_TOOL_TRACE = 10
MAX_TOOL_ROUNDS = 6
MAX_REQUEST_TIMEOUT_SECONDS = 300
MAX_INTEGRITY_RETRIES = 2

CLAUDE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["answer", "tool_call"]},
        "content": {"type": "string"},
        "tool_name": {"type": "string"},
        "arguments": {
            "type": "string",
            "description": "Objeto JSON serializado como texto con los argumentos de la herramienta.",
        },
    },
    "required": ["kind", "content", "tool_name", "arguments"],
    "additionalProperties": False,
}


def claude_executable_path() -> str:
    configured = os.environ.get("MYKOS_CLAUDE_EXECUTABLE", "").strip()
    candidates = [configured] if configured else []
    candidates.extend(
        [
            str(Path.home() / ".npm-global" / "bin" / "claude"),
            str(Path.home() / ".local" / "bin" / "claude"),
            "/usr/local/bin/claude",
            "/usr/bin/claude",
            shutil.which("claude") or "",
        ]
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return ""


def run_claude_cli(arguments: list[str], *, input_text: str = "", timeout: int = 30, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    executable = claude_executable_path()
    if not executable:
        raise RuntimeError(
            "No se encuentra Claude Code en este equipo. Instala Claude Code o configura MYKOS_CLAUDE_EXECUTABLE."
        )
    command = [executable, *arguments]
    options: dict[str, Any] = {
        "cwd": str(cwd or Path(__file__).resolve().parent.parent),
        "input": input_text,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "check": False,
    }
    child_environment = os.environ.copy()
    for secret_name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        child_environment.pop(secret_name, None)
    options["env"] = child_environment
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.run(command, **options)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Claude tardó demasiado en responder y MyKOS canceló la petición.") from error
    except OSError as error:
        raise RuntimeError(f"No se pudo iniciar Claude Code: {error}") from error


def start_claude_login(root_dir: Path | None = None) -> dict[str, Any]:
    global CLAUDE_LOGIN_PROCESS
    executable = claude_executable_path()
    if not executable:
        raise RuntimeError("Claude Code no está instalado en este equipo.")
    with CLAUDE_STATUS_LOCK:
        if CLAUDE_LOGIN_PROCESS is not None and CLAUDE_LOGIN_PROCESS.poll() is None:
            return {"ok": True, "provider": "anthropic_oauth", "status": "running"}
        child_environment = os.environ.copy()
        child_environment.pop("ANTHROPIC_API_KEY", None)
        child_environment.pop("ANTHROPIC_AUTH_TOKEN", None)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        if os.name != "nt":
            desktop = _desktop_session_environment()
            real_home = desktop.pop("HOME", "")
            child_environment.update(desktop)
            opener = shutil.which("xdg-open")
            if opener and real_home:
                launcher = Path(tempfile.gettempdir()) / f"mykos-open-desktop-{os.getuid()}.sh"
                launcher.write_text(f"#!/bin/sh\nHOME={shlex.quote(real_home)} exec {shlex.quote(opener)} \"$@\"\n", encoding="utf-8")
                launcher.chmod(0o700)
                child_environment["BROWSER"] = str(launcher)
        try:
            CLAUDE_LOGIN_PROCESS = subprocess.Popen(
                [executable, "auth", "login"],
                cwd=str(root_dir or Path(__file__).resolve().parent.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=child_environment,
                creationflags=creationflags,
            )
        except OSError as error:
            raise RuntimeError(f"No se pudo iniciar el inicio de sesión de Claude: {error}") from error
        CLAUDE_STATUS_CACHE["checked_at"] = 0.0
        CLAUDE_STATUS_CACHE["status"] = None
    return {"ok": True, "provider": "anthropic_oauth", "status": "running"}


def claude_auth_status() -> dict[str, Any]:
    now = time.monotonic()
    with CLAUDE_STATUS_LOCK:
        cached = CLAUDE_STATUS_CACHE.get("status")
        if cached is not None and now - float(CLAUDE_STATUS_CACHE.get("checked_at", 0.0)) < CLAUDE_STATUS_CACHE_SECONDS:
            return dict(cached)

        direct_key = get_anthropic_api_key()
        if direct_key:
            status = {
                "available": True,
                "authenticated": True,
                "auth_method": "clave_directa",
                "email": "",
                "subscription_tier": "API directa",
                "provider": "anthropic_oauth",
                "label": "Anthropic · API directa",
                "error": "",
            }
            CLAUDE_STATUS_CACHE["checked_at"] = now
            CLAUDE_STATUS_CACHE["status"] = status
            return dict(status)

        executable = claude_executable_path()
        if not executable:
            status = {
                "available": False,
                "authenticated": False,
                "auth_method": "no_instalado",
                "email": "",
                "subscription_tier": "",
                "provider": "anthropic_oauth",
                "label": "Claude Code no instalado",
                "error": "Claude Code no está instalado en este equipo.",
            }
            CLAUDE_STATUS_CACHE["checked_at"] = now
            CLAUDE_STATUS_CACHE["status"] = status
            return dict(status)

        try:
            completed = run_claude_cli(["auth", "status"], timeout=15)
        except RuntimeError as error:
            status = {
                "available": True,
                "authenticated": False,
                "auth_method": "error",
                "email": "",
                "subscription_tier": "",
                "provider": "anthropic_oauth",
                "label": "Claude Code · Error",
                "error": str(error),
            }
            CLAUDE_STATUS_CACHE["checked_at"] = now
            CLAUDE_STATUS_CACHE["status"] = status
            return dict(status)

        output = f"{completed.stdout}\n{completed.stderr}".strip()
        authenticated = completed.returncode == 0 and "Logged in as" in output
        email = ""
        match = re.search(r"Logged in as ([^\s\r\n]+)", output)
        if match:
            email = match.group(1).strip()
        status = {
            "available": True,
            "authenticated": authenticated,
            "auth_method": "claude_ai_oauth",
            "email": email,
            "subscription_tier": "Suscripción claude.ai" if authenticated else "",
            "provider": "anthropic_oauth",
            "label": f"Claude Code ({email})" if email else "Claude Code · claude.ai",
            "error": "" if authenticated else "Sesión no iniciada en Claude Code.",
        }
        CLAUDE_STATUS_CACHE["checked_at"] = now
        CLAUDE_STATUS_CACHE["status"] = status
        return dict(status)


def logout_claude() -> dict[str, Any]:
    with CLAUDE_STATUS_LOCK:
        try:
            run_claude_cli(["auth", "logout"], timeout=15)
        except RuntimeError:
            pass
        CLAUDE_STATUS_CACHE["checked_at"] = 0.0
        CLAUDE_STATUS_CACHE["status"] = None
    return {"ok": True, "provider": "anthropic_oauth", "authenticated": False}


def claude_model_summary() -> dict[str, Any]:
    auth = claude_auth_status()
    available = bool(auth.get("available"))
    authenticated = bool(auth.get("authenticated"))
    return {
        "name": CLAUDE_MODEL_NAME,
        "label": CLAUDE_MODEL_LABEL,
        "provider": "anthropic_oauth",
        "provider_label": "Claude Code · claude.ai OAuth",
        "size": 0,
        "parameter_size": "",
        "family": "Claude Sonnet",
        "quantization": "",
        "modified_at": "",
        "capabilities": ["chat", "completion", "thinking", "tools"],
        "chat_capable": authenticated,
        "vision_capable": False,
        "thinking_capable": True,
        "tools_capable": True,
        "context_length": CLAUDE_CONTEXT_LENGTH,
        "remote": True,
        "remote_host": "Anthropic mediante Claude Code",
        "benchmark_capable": False,
        "auth_method": auth.get("auth_method", "claude.ai OAuth"),
        "auth_status": "autenticado" if authenticated else ("disponible" if available else "no_instalado"),
        "subscription_type": str(auth.get("subscription_tier") or auth.get("subscription_type", "")),
        "auth_error": str(auth.get("error", "")),
    }


def claude_tool_protocol_prompt(*, arguments_as_string: bool = False) -> str:
    arguments_example = (
        '{"kind":"tool_call","content":"","tool_name":"...","arguments":"{\\"clave\\":\\"valor\\"}"}'
        if arguments_as_string
        else '{"kind":"tool_call","content":"","tool_name":"...","arguments":{...}}'
    )
    lines = [
        "PROTOCOLO DE HERRAMIENTAS DE MYKOS:",
        "La respuesta debe ajustarse al esquema JSON que recibe el host.",
        "INTEGRIDAD: el texto previo de MyKOS no demuestra que una herramienta se haya llamado ni que haya fallado. Solo los bloques RESULTADO-DE-HERRAMIENTA y REGISTRO-VERIFICADO-DEL-HOST son evidencia. No afirmes haber probado, reproducido o recibido un error de herramienta si el host no te ha dado ese resultado en este turno.",
        'Para responder normalmente usa: {"kind":"answer","content":"...","tool_name":"","arguments":""}.',
        f"Para usar una herramienta usa: {arguments_example}.",
        "Solicita una sola herramienta por turno. No inventes nombres ni argumentos.",
        "Tras recibir un resultado de herramienta, si queda trabajo pendiente, llama directamente a la siguiente herramienta en lugar de anunciar lo que vas a hacer. Usa kind=answer solo cuando la tarea esté terminada o necesites una decisión de Usuario.",
        "NUNCA uses etiquetas XML como <invoke> dentro del contenido. Si necesitas usar una herramienta, DEBES usar estrictamente kind='tool_call' en el JSON. No mezcles texto para el usuario y llamadas a herramientas en el mismo turno.",
        "Las herramientas sensibles crean una aprobación: nunca digas que se ha escrito, ejecutado o cambiado algo hasta que el host devuelva el resultado aprobado.",
        "Herramientas disponibles:",
    ]
    for schema in TOOL_SCHEMAS:
        function = schema.get("function") if isinstance(schema, dict) else {}
        if not isinstance(function, dict):
            continue
        name = str(function.get("name", "")).strip()
        description = str(function.get("description", "")).strip()
        parameters = function.get("parameters") or {}
        lines.append(f"- {name}: {description}")
        lines.append(f"  Parámetros: {json.dumps(parameters, ensure_ascii=False, separators=(',', ':'))}")
    return "\n".join(lines)


def verified_tool_ledger_for_prompt(message: dict[str, Any]) -> str:
    raw_trace = message.get("verified_tool_trace")
    if not isinstance(raw_trace, list):
        return ""
    entries: list[dict[str, Any]] = []
    for raw_entry in raw_trace[-MAX_VERIFIED_TOOL_TRACE:]:
        if not isinstance(raw_entry, dict):
            continue
        name = str(raw_entry.get("tool", "")).strip()
        if not name:
            continue
        item: dict[str, Any] = {"tool": name, "ok": bool(raw_entry.get("ok"))}
        error = str(raw_entry.get("error", "")).strip()
        if error:
            item["error"] = error[:500]
        entries.append(item)
    if not entries:
        return ""
    return "<registro-verificado-del-host>\n" + json.dumps(entries, ensure_ascii=False, separators=(",", ":")) + "\n</registro-verificado-del-host>"


def claude_unverified_tool_claim_reason(content: str, trace: list[dict[str, Any]]) -> str:
    normalized = re.sub(r"\s+", " ", str(content or "")).casefold()
    if not normalized:
        return ""
    error_terms = (
        "error de esquema",
        "must have required property",
        "no such tool",
        "herramienta no responde",
        "herramientas no responden",
        "fallo de herramientas",
        "falla de herramientas",
    )
    first_person_attempt = re.search(
        r"\b(?:he|hemos|acabo de|lo estoy)\s+(?:probado|comprobado|verificado|reproducido|intentado|ejecutado|reintentado)\b"
        r"|\b(?:me devuelve|me devuelven|me ha devuelto|me han devuelto)\b",
        normalized,
    )
    if not first_person_attempt or not any(term in normalized for term in error_terms):
        return ""
    successful = [entry for entry in trace if isinstance(entry, dict) and entry.get("ok")]
    if successful:
        tools = ", ".join(str(entry.get("tool", "")).strip() for entry in successful if str(entry.get("tool", "")).strip())
        return f"El host registró resultados correctos para: {tools}. No afirmes que devolvieron un error. Usa esos resultados o solicita otra herramienta."
    return "No se ha ejecutado ninguna herramienta en este turno. No afirmes haber probado, reproducido o recibido un error de herramienta; llama primero a la herramienta necesaria o responde sin atribuirte esa comprobación."


def claude_prompt_from_messages(messages: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for item in messages:
        role = item.get("role")
        if role == "system":
            continue
        if role == "user":
            content = str(item.get("content", ""))
            sections.append(f"USUARIO:\n{content.strip()}")
            continue
        if role == "assistant":
            content = str(item.get("content", ""))
            sections.append(f"ASISTENTE:\n{content.strip()}")
            continue
        if role == "tool":
            tool_content = str(item.get("content", ""))
            sections.append(f"RESULTADO-DE-HERRAMIENTA:\n{tool_content.strip()}")
    sections.append("Devuelve exclusivamente la respuesta JSON solicitada.")
    return "\n\n".join(sections)


def parse_claude_response(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    stdout = completed.stdout.strip()
    if not stdout:
        stderr = completed.stderr.strip()
        raise RuntimeError(stderr or "Claude no devolvió ningún texto.")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("Claude devolvió una respuesta que no es JSON válido.") from error
    if not isinstance(data, dict):
        raise RuntimeError("Claude no devolvió una estructura JSON esperada.")
    is_error = bool(data.get("is_error"))
    structured = data.get("structured_output")
    if structured is not None:
        if not isinstance(structured, dict):
            raise RuntimeError("La salida estructurada de Claude no tiene formato de objeto.")
        parsed = dict(structured)
        parsed["is_error"] = is_error
        parsed["raw_json"] = data
        return parsed
    result_text = str(data.get("result", "")).strip()
    if not result_text:
        raise RuntimeError("Claude terminó sin resultado textual utilizable.")
    try:
        extracted = json.loads(result_text)
        if isinstance(extracted, dict):
            extracted["is_error"] = is_error
            extracted["raw_json"] = data
            return extracted
    except json.JSONDecodeError:
        pass
    return {
        "kind": "answer",
        "content": result_text,
        "tool_name": "",
        "arguments": "",
        "is_error": is_error,
        "raw_json": data,
    }
