"""Adaptador para el CLI oficial de Qwen Code (qwen).

Usa la sesión y configuración propia del CLI de Qwen Code de forma aislada.
Garantiza un perfil seguro sin herramientas autónomas ni búsqueda web no configurada.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

MAX_PROMPT_CHARS = 12000

SAFE_HOME = Path(
    os.environ.get(
        "MYKOS_QWEN_HOME",
        str(Path(__file__).resolve().parent.parent / "runtime" / "qwen-home"),
    )
).expanduser()
SAFE_SETTINGS = SAFE_HOME / ".qwen" / "settings.json"
DENIED_TOOLS = {"webSearch", "shell", "listDirectory", "todoWrite"}

CONFIG_DIR = Path(
    os.environ.get(
        "MYKOS_CREDENTIALS_DIR",
        str(Path(__file__).resolve().parent / "data" / "oauth"),
    )
).expanduser() / "qwen"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_QWEN_MODELS: list[tuple[str, str, str]] = [
    ("qwen-code-default", "Qwen Code · CLI (Predeterminado)", "Qwen"),
]

CLOUD_QWEN_MODELS: list[tuple[str, str, str]] = [
    ("qwen-turbo", "Qwen Turbo · Nube (DashScope)", "Qwen"),
    ("qwen-plus", "Qwen Plus · Nube (DashScope)", "Qwen"),
    ("qwen-max", "Qwen Max · Nube (DashScope)", "Qwen"),
    ("qwen3-coder-plus", "Qwen 3 Coder Plus · Nube (DashScope)", "Qwen Coder"),
]

QWEN_LOCK = threading.Lock()
QWEN_CACHE: dict[str, Any] = {"checked_at": 0.0, "models": []}
CACHE_TTL_SECONDS = 300.0


def qwen_executable_path() -> str:
    configured = os.environ.get("MYKOS_QWEN_PATH", "").strip()
    candidates = [configured] if configured else []
    candidates.extend(
        [
            shutil.which("qwen") or "",
            str(Path.home() / ".local" / "bin" / "qwen"),
            str(Path.home() / ".local" / "lib" / "qwen-code" / "bin" / "qwen"),
            "/usr/local/bin/qwen",
            "/usr/bin/qwen",
        ]
    )
    for candidate in candidates:
        if candidate and (shutil.which(candidate) or Path(candidate).is_file()):
            return str(Path(candidate))
    return ""


def setup_safe_environment() -> None:
    """Crea o sincroniza el perfil seguro de Qwen desactivando herramientas peligrosas."""
    SAFE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    user_settings_file = Path.home() / ".qwen" / "settings.json"
    safe_data: dict[str, Any] = {
        "$version": 4,
        "tools": {tool: {"enabled": False} for tool in DENIED_TOOLS},
    }
    if user_settings_file.is_file():
        try:
            user_data = json.loads(user_settings_file.read_text(encoding="utf-8"))
            if isinstance(user_data, dict):
                for key in ("model", "modelProviders", "security", "env", "fastModel"):
                    if key in user_data:
                        safe_data[key] = user_data[key]
        except (OSError, ValueError, TypeError):
            pass

    # Aseguramos que DENIED_TOOLS estén explícitamente desactivadas
    tools_block = safe_data.setdefault("tools", {})
    if isinstance(tools_block, dict):
        for tool in DENIED_TOOLS:
            tools_block[tool] = {"enabled": False}

    temp_file = SAFE_SETTINGS.with_suffix(".tmp")
    temp_file.write_text(json.dumps(safe_data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temp_file, 0o600)
    except OSError:
        pass
    temp_file.replace(SAFE_SETTINGS)


def ensure_chat_safe() -> None:
    """Falla cerrado si el perfil de Qwen no desactiva todas las herramientas autónomas."""
    if not SAFE_SETTINGS.is_file():
        setup_safe_environment()
    try:
        settings = json.loads(SAFE_SETTINGS.read_text(encoding="utf-8"))
        tools_cfg = settings.get("tools", {})
        if not isinstance(tools_cfg, dict):
            raise RuntimeError("Configuración de herramientas de Qwen no es válida.")
        for tool in DENIED_TOOLS:
            tool_data = tools_cfg.get(tool)
            if not isinstance(tool_data, dict) or tool_data.get("enabled", True):
                raise RuntimeError(f"La herramienta {tool} está activa en el perfil de Qwen.")
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("No se puede verificar el perfil aislado de Qwen.") from exc


def is_qwen_enabled() -> bool:
    try:
        if CONFIG_FILE.is_file():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return bool(data.get("enabled", False))
    except (OSError, ValueError, TypeError):
        pass
    return False


def enable_qwen() -> dict[str, Any]:
    executable = qwen_executable_path()
    if not executable:
        raise RuntimeError("No se encuentra el ejecutable qwen en este equipo.")
    setup_safe_environment()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps({"enabled": True}, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(CONFIG_FILE)
    return {"ok": True, "provider": "qwen_cli", "authenticated": True, "enabled": True}


def disable_qwen() -> dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps({"enabled": False}, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(CONFIG_FILE)
    with QWEN_LOCK:
        QWEN_CACHE["models"] = []
        QWEN_CACHE["checked_at"] = 0.0
    return {"ok": True, "provider": "qwen_cli", "authenticated": False, "enabled": False}


def qwen_auth_status() -> dict[str, Any]:
    has_binary = bool(qwen_executable_path())
    enabled = is_qwen_enabled()
    error = ""
    if not has_binary:
        error = "No se encuentra el ejecutable qwen en este equipo."
    elif not enabled:
        error = "Qwen Code CLI está desactivado en MyKOS."
    return {
        "available": has_binary,
        "authenticated": enabled and has_binary,
        "enabled": enabled,
        "provider": "qwen_cli",
        "error": error,
    }


def _discover_qwen_models() -> list[tuple[str, str, str]]:
    discovered = list(DEFAULT_QWEN_MODELS)
    seen: set[str] = {"qwen-code-default"}

    # 1. Modelo activo en ~/.qwen/settings.json
    try:
        user_cfg = Path.home() / ".qwen" / "settings.json"
        if user_cfg.is_file():
            data = json.loads(user_cfg.read_text(encoding="utf-8"))
            active_model = str(data.get("model", {}).get("name", "")).strip()
            if active_model and active_model not in seen:
                family = "Qwen Coder" if "coder" in active_model.lower() else "Qwen"
                discovered.append((active_model, f"Qwen Code · {active_model}", family))
                seen.add(active_model)
    except Exception:
        pass

    # 2. Modelos locales instalados en Ollama
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for m in data.get("models", []):
                name = str(m.get("name", "")).strip()
                if "qwen" in name.lower() and name not in seen:
                    family = "Qwen Coder" if "coder" in name.lower() else "Qwen"
                    discovered.append((name, f"Qwen · {name} (Ollama)", family))
                    seen.add(name)
    except Exception:
        pass

    # 3. Modelos de nube solo si se dispone de clave de DashScope / Alibaba
    has_dashscope = bool(
        os.environ.get("DASHSCOPE_API_KEY", "").strip()
        or os.environ.get("BAILIAN_CODING_PLAN_API_KEY", "").strip()
    )
    if has_dashscope:
        for c_id, c_label, c_fam in CLOUD_QWEN_MODELS:
            if c_id not in seen:
                discovered.append((c_id, c_label, c_fam))
                seen.add(c_id)

    return discovered


def qwen_model_catalog(force: bool = False) -> tuple[list[dict[str, Any]], bool, str]:
    if not is_qwen_enabled():
        return [], False, ""
    executable = qwen_executable_path()
    if not executable:
        return [], False, "No se encuentra el ejecutable qwen."

    now = time.monotonic()
    with QWEN_LOCK:
        cached = QWEN_CACHE.get("models")
        checked_at = float(QWEN_CACHE.get("checked_at", 0.0))
        if not force and cached and (now - checked_at < CACHE_TTL_SECONDS):
            return list(cached), True, ""

    raw_models = _discover_qwen_models()
    cloud_ids = {m[0] for m in CLOUD_QWEN_MODELS}
    models: list[dict[str, Any]] = []
    for model_name, model_label, family in raw_models:
        is_cloud = model_name in cloud_ids
        models.append(
            {
                "name": f"qwen-cli/{model_name}",
                "label": model_label,
                "provider": "qwen_cli",
                "provider_label": "Qwen · Nube (DashScope API)" if is_cloud else "Qwen Code · Local (Ollama)",
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
                "context_length": 32768,
                "remote": is_cloud,
                "remote_host": "Alibaba Cloud DashScope" if is_cloud else "local (Ollama / GPU)",
                "benchmark_capable": not is_cloud,
                "auth_method": "DashScope API Key" if is_cloud else "CLI Qwen Code local",
                "auth_status": "autenticado",
                "auth_error": "",
            }
        )

    with QWEN_LOCK:
        QWEN_CACHE["models"] = list(models)
        QWEN_CACHE["checked_at"] = now

    return models, True, ""


def extract_qwen_response(payload: Any) -> tuple[str, dict[str, Any], float]:
    """Extrae el texto de respuesta, uso de tokens y duración del JSON de Qwen Code."""
    if isinstance(payload, dict):
        payload = [payload]
    if isinstance(payload, list):
        result_item = None
        assistant_text = ""
        for item in reversed(payload):
            if isinstance(item, dict):
                if item.get("type") == "result" and result_item is None:
                    result_item = item
                if not assistant_text and item.get("type") == "assistant":
                    msg = item.get("message", {})
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                assistant_text = part.get("text", "")
                                if assistant_text:
                                    break
        if result_item:
            if result_item.get("is_error"):
                err = result_item.get("error", {})
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(msg or "Qwen devolvió un error de ejecución.")
            text = str(result_item.get("result") or assistant_text).strip()
            usage = result_item.get("usage") or {}
            duration = float(result_item.get("duration_ms", 0.0)) / 1000.0
            return text, usage, duration
        if assistant_text:
            return assistant_text.strip(), {}, 0.0
    raise RuntimeError("Qwen no devolvió una respuesta válida.")


def ask_qwen(prompt: str, timeout_seconds: int = 120, model: str = "") -> dict[str, Any]:
    """Ejecuta un turno en Qwen Code en modo no interactivo y devuelve respuesta, uso y duración."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("El prompt debe contener texto.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"El prompt supera {MAX_PROMPT_CHARS} caracteres.")
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 300:
        raise ValueError("timeout_seconds debe estar entre 1 y 300.")

    ensure_chat_safe()
    executable = qwen_executable_path()
    if not executable:
        raise RuntimeError("No se encuentra el ejecutable qwen en este equipo.")

    command = [
        executable,
        "--output-format",
        "json",
    ]
    if model and model != "qwen-code-default":
        command.extend(["-m", model])
    command.extend(["-p", prompt])

    child_environment = {
        "HOME": str(SAFE_HOME),
        "XDG_CONFIG_HOME": str(SAFE_HOME / ".config"),
        "XDG_CACHE_HOME": str(SAFE_HOME / ".cache"),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    }
    for key, val in os.environ.items():
        if any(token in key for token in ("KEY", "TOKEN", "QWEN", "DASHSCOPE", "OPENAI", "OLLAMA")):
            child_environment[key] = val

    options: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout_seconds + 10,
        "check": False,
        "cwd": str(SAFE_HOME),
        "env": child_environment,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        options["start_new_session"] = True

    try:
        result = subprocess.run(command, **options)
    except FileNotFoundError as exc:
        raise RuntimeError("No se encuentra el ejecutable qwen.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Qwen Code excedió el tiempo máximo de respuesta.") from exc

    if result.returncode != 0 and not result.stdout:
        err_msg = (result.stderr or "").strip()
        raise RuntimeError(f"qwen terminó con código {result.returncode}. {err_msg}".strip())

    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("qwen no devolvió un JSON válido.") from exc

    response_text, usage, duration_seconds = extract_qwen_response(payload)
    if not response_text:
        raise RuntimeError("qwen no devolvió texto de respuesta.")

    return {
        "response": response_text,
        "usage": usage,
        "duration_seconds": duration_seconds,
    }
