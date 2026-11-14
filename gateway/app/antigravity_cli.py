"""Adaptador mínimo para el CLI autenticado de Antigravity.

Usa la sesión OAuth propia de agy. No lee ni gestiona tokens.
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

AGY_PATH = os.environ.get(
    "MYKOS_AGY_PATH",
    shutil.which("agy") or str(Path.home() / ".local" / "bin" / "agy"),
)
MAX_PROMPT_CHARS = 12000
SAFE_HOME = Path(
    os.environ.get(
        "MYKOS_AGY_HOME",
        str(Path(__file__).resolve().parent.parent / "runtime" / "antigravity-home"),
    )
).expanduser()
SAFE_SETTINGS = SAFE_HOME / ".gemini" / "antigravity-cli" / "settings.json"
DENIED_TOOLS = {"read_file(*)", "write_file(*)", "command(*)", "read_url(*)", "execute_url(*)", "mcp(*)"}

CONFIG_DIR = Path(os.environ.get("MYKOS_CREDENTIALS_DIR", str(Path(__file__).resolve().parent / "data" / "oauth"))).expanduser() / "antigravity"
CONFIG_FILE = CONFIG_DIR / "config.json"


def is_antigravity_enabled() -> bool:
    try:
        if CONFIG_FILE.is_file():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return bool(data.get("enabled", False))
    except (OSError, ValueError, TypeError):
        pass
    return False


def ensure_safe_settings() -> None:
    """Garantiza que SAFE_SETTINGS exista y deniegue todas las herramientas del CLI."""
    SAFE_SETTINGS.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        existing = json.loads(SAFE_SETTINGS.read_text(encoding="utf-8")) if SAFE_SETTINGS.is_file() else {}
    except (OSError, ValueError, TypeError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    perms = existing.get("permissions")
    if not isinstance(perms, dict):
        perms = {}
    deny_list = perms.get("deny")
    if not isinstance(deny_list, list):
        deny_list = []
    merged = sorted({str(x) for x in deny_list if x} | DENIED_TOOLS)
    if set(merged) != {str(x) for x in deny_list if x} or not SAFE_SETTINGS.is_file():
        perms["deny"] = merged
        existing["permissions"] = perms
        tmp = SAFE_SETTINGS.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(SAFE_SETTINGS)


def enable_antigravity() -> dict[str, Any]:
    if not (shutil.which(AGY_PATH) or Path(AGY_PATH).is_file()):
        raise RuntimeError(f"No se encuentra el ejecutable {AGY_PATH}.")
    ensure_safe_settings()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps({"enabled": True}, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(CONFIG_FILE)
    return {"ok": True, "provider": "antigravity_cli", "authenticated": True, "enabled": True}


DEFAULT_ANTIGRAVITY_MODELS: list[tuple[str, str, str]] = [
    ("gemini-4-argon-high", "Gemini 4 Argon (High)", "Gemini Argon"),
    ("gemini-4-argon-medium", "Gemini 4 Argon (Medium)", "Gemini Argon"),
    ("gemini-4-argon-low", "Gemini 4 Argon (Low)", "Gemini Argon"),
    ("gemini-3.8-flash-high", "Gemini 3.8 Flash (High)", "Gemini"),
    ("gemini-3.8-flash-medium", "Gemini 3.8 Flash (Medium)", "Gemini"),
    ("gemini-3.8-flash-low", "Gemini 3.8 Flash (Low)", "Gemini"),
    ("claude-opus-5-5-high", "Claude Opus 5.5 (High)", "Claude Opus"),
    ("claude-opus-5-5-medium", "Claude Opus 5.5 (Medium)", "Claude Opus"),
    ("claude-opus-5-5-low", "Claude Opus 5.5 (Low)", "Claude Opus"),
    ("claude-sonnet-5-5-high", "Claude Sonnet 5.5 (High)", "Claude Sonnet"),
    ("claude-sonnet-5-5-medium", "Claude Sonnet 5.5 (Medium)", "Claude Sonnet"),
    ("claude-sonnet-5-5-low", "Claude Sonnet 5.5 (Low)", "Claude Sonnet"),
    ("gpt-oss-120b-medium", "GPT-OSS 120B (Medium)", "GPT-OSS"),
]

ANTIGRAVITY_LOCK = threading.RLock()
ANTIGRAVITY_CACHE: dict[str, Any] = {"checked_at": 0.0, "models": []}
CACHE_TTL_SECONDS = 300.0
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _fetch_agy_models() -> list[tuple[str, str, str]]:
    has_binary = bool(shutil.which(AGY_PATH) or Path(AGY_PATH).is_file())
    if not has_binary:
        return []
    try:
        ensure_safe_settings()
    except OSError:
        return []
    try:
        env = {
            "HOME": str(SAFE_HOME),
            "XDG_CONFIG_HOME": str(SAFE_HOME / ".config"),
            "XDG_CACHE_HOME": str(SAFE_HOME / ".cache"),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        }
        res = subprocess.run(
            [AGY_PATH, "models"],
            capture_output=True,
            text=True,
            timeout=8,
            env=env,
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            discovered: list[tuple[str, str, str]] = []
            for raw_line in res.stdout.replace("\r", "\n").splitlines():
                line = _ANSI_RE.sub("", raw_line).strip()
                if not line or "Fetching available models" in line or line.startswith(("Fetching", "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")):
                    continue
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    m_id, m_label = parts[0].strip(), parts[1].strip()
                else:
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        m_id, m_label = parts[0].strip(), parts[1].strip()
                    else:
                        m_id, m_label = line, line
                if not m_id:
                    continue
                name_lower = m_id.lower()
                if "argon" in name_lower:
                    family = "Gemini Argon"
                elif "gemini" in name_lower:
                    family = "Gemini"
                elif "opus" in name_lower:
                    family = "Claude Opus"
                elif "sonnet" in name_lower:
                    family = "Claude Sonnet"
                elif "claude" in name_lower:
                    family = "Claude"
                elif "gpt" in name_lower:
                    family = "GPT-OSS"
                else:
                    family = "Antigravity"
                discovered.append((m_id, m_label, family))
            return discovered
    except Exception:
        pass
    return []


def disable_antigravity() -> dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps({"enabled": False}, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(CONFIG_FILE)
    with ANTIGRAVITY_LOCK:
        ANTIGRAVITY_CACHE["models"] = []
        ANTIGRAVITY_CACHE["checked_at"] = 0.0
    return {"ok": True, "provider": "antigravity_cli", "authenticated": False, "enabled": False}


def antigravity_auth_status() -> dict[str, Any]:
    try:
        ensure_safe_settings()
    except OSError:
        pass
    has_binary = bool(shutil.which(AGY_PATH) or Path(AGY_PATH).is_file())
    enabled = is_antigravity_enabled()
    error = ""
    if not has_binary:
        error = "No se encuentra el ejecutable agy en este equipo."
    elif not enabled:
        error = "Antigravity CLI está desactivado en MyKOS."
    return {
        "available": has_binary,
        "authenticated": enabled and has_binary,
        "enabled": enabled,
        "provider": "antigravity_cli",
        "error": error,
    }


def antigravity_model_catalog(force: bool = False) -> tuple[list[dict[str, Any]], bool, str]:
    if not is_antigravity_enabled():
        return [], False, ""
    has_binary = bool(shutil.which(AGY_PATH) or Path(AGY_PATH).is_file())
    if not has_binary:
        return [], False, "No se encuentra el ejecutable agy."

    now = time.monotonic()
    with ANTIGRAVITY_LOCK:
        cached = ANTIGRAVITY_CACHE.get("models")
        checked_at = float(ANTIGRAVITY_CACHE.get("checked_at", 0.0))
        if not force and cached and (now - checked_at < CACHE_TTL_SECONDS):
            return list(cached), True, ""

    raw_models = _fetch_agy_models()
    if not raw_models:
        return [], False, "No se pudieron obtener modelos de Antigravity CLI (agy)."
    models: list[dict[str, Any]] = []
    for model_name, model_label, family in raw_models:
        models.append({
            "name": f"antigravity/{model_name}",
            "label": model_label,
            "provider": "antigravity_cli",
            "provider_label": "Antigravity CLI · sesión Google",
            "size": 0,
            "parameter_size": "",
            "family": family,
            "quantization": "",
            "modified_at": "",
            "capabilities": ["chat", "completion"],
            "chat_capable": True,
            "vision_capable": False,
            "thinking_capable": True,
            "tools_capable": False,
            "context_length": 0,
            "remote": True,
            "remote_host": "agy en perfil aislado sin herramientas",
            "benchmark_capable": False,
            "auth_method": "sesión Google gestionada por agy",
            "auth_status": "autenticado",
            "auth_error": "",
        })

    with ANTIGRAVITY_LOCK:
        ANTIGRAVITY_CACHE["models"] = list(models)
        ANTIGRAVITY_CACHE["checked_at"] = now

    return models, True, ""


def ensure_chat_safe() -> None:
    """Fail closed unless the dedicated CLI profile blocks every tool namespace."""
    try:
        settings = json.loads(SAFE_SETTINGS.read_text(encoding="utf-8"))
        denied = set(settings.get("permissions", {}).get("deny", []))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("No se puede verificar el perfil aislado de Antigravity.") from exc
    if not DENIED_TOOLS.issubset(denied):
        raise RuntimeError("El perfil aislado de Antigravity no deniega todas las herramientas; no se ha enviado el mensaje.")


def ask(prompt: str, timeout_seconds: int = 60, model: str = "") -> dict[str, Any]:
    """Ejecuta un turno sin streaming y devuelve texto, uso y duración.

    El uso se conoce al terminar: este adaptador no impone un límite previo
    de tokens. No debe exponerse como herramienta autónoma del modelo.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("El prompt debe contener texto.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"El prompt supera {MAX_PROMPT_CHARS} caracteres.")
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 300:
        raise ValueError("timeout_seconds debe estar entre 1 y 300.")

    ensure_chat_safe()

    command = [
        AGY_PATH,
        "--mode", "plan",
        "--sandbox",
        "--disable-slash-commands",
        "--output-format", "json",
        "--print-timeout", f"{timeout_seconds}s",
        "-p", prompt,
    ]
    if model:
        command.extend(["--model", model])
    child_environment = {
        "HOME": str(SAFE_HOME),
        "XDG_CONFIG_HOME": str(SAFE_HOME / ".config"),
        "XDG_CACHE_HOME": str(SAFE_HOME / ".cache"),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    }
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 10,
            check=False,
            cwd=str(SAFE_HOME),
            env=child_environment,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("No se encuentra el ejecutable agy.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Antigravity excedió el tiempo máximo.") from exc

    if result.returncode != 0:
        raise RuntimeError(f"agy terminó con código {result.returncode}.")
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("agy no devolvió un JSON válido.") from exc
    if not isinstance(payload, dict) or payload.get("status") != "SUCCESS":
        raise RuntimeError("agy no completó la petición correctamente.")
    response = payload.get("response")
    if not isinstance(response, str):
        raise RuntimeError("agy no devolvió texto de respuesta.")
    usage = payload.get("usage")
    return {
        "response": response,
        "conversation_id": payload.get("conversation_id"),
        "usage": usage if isinstance(usage, dict) else {},
        "duration_seconds": payload.get("duration_seconds"),
    }
