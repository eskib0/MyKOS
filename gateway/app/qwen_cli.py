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
        "permissions": {
            "deny": ["shell", "run_shell_command", "bash", "execute", "write_file", "edit_file", "listDirectory", "webSearch", "todoWrite", "*"],
        },
        "tools": {
            "disabled": ["shell", "run_shell_command", "bash", "execute", "write_file", "edit_file", "listDirectory", "webSearch", "todoWrite"],
            **{tool: {"enabled": False} for tool in DENIED_TOOLS},
        },
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

    # Aseguramos que DENIED_TOOLS y permisos restrictivos se apliquen siempre
    tools_block = safe_data.setdefault("tools", {})
    if isinstance(tools_block, dict):
        for tool in DENIED_TOOLS:
            tools_block[tool] = {"enabled": False}
        tools_block["disabled"] = ["shell", "run_shell_command", "bash", "execute", "write_file", "edit_file", "listDirectory", "webSearch", "todoWrite"]
    perms_block = safe_data.setdefault("permissions", {})
    if isinstance(perms_block, dict):
        perms_block["deny"] = ["shell", "run_shell_command", "bash", "execute", "write_file", "edit_file", "listDirectory", "webSearch", "todoWrite", "*"]

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
        perms = settings.get("permissions", {})
        if not isinstance(perms, dict) or not set(DENIED_TOOLS).issubset(set(perms.get("deny", []))):
            setup_safe_environment()
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


ALLOWED_QWEN_ENV_VARS = {
    "DASHSCOPE_API_KEY",
    "BAILIAN_CODING_PLAN_API_KEY",
    "QWEN_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OLLAMA_API_KEY",
    "OLLAMA_HOST",
}


def _is_local_endpoint(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()
        return hostname in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
    except Exception:
        return False


def _get_qwen_configured_endpoint(model_name: str = "") -> tuple[str, bool]:
    """Lee ~/.qwen/settings.json y determina el baseUrl configurado (revisando model, security y modelProviders)."""
    try:
        user_cfg = Path.home() / ".qwen" / "settings.json"
        if user_cfg.is_file():
            data = json.loads(user_cfg.read_text(encoding="utf-8"))
            lookup_model = (model_name or "").strip().removeprefix("qwen-cli/")
            if not lookup_model or lookup_model == "qwen-code-default":
                lookup_model = str(data.get("model", {}).get("name") or "").strip().removeprefix("qwen-cli/")
            # 1. Comprobar modelProviders (proveedores personalizados como openai, ollama, gemini)
            providers = data.get("modelProviders", {})
            if isinstance(providers, dict):
                for prov_list in providers.values():
                    if isinstance(prov_list, list):
                        for entry in prov_list:
                            if isinstance(entry, dict):
                                e_id = str(entry.get("id") or "").strip().removeprefix("qwen-cli/")
                                e_name = str(entry.get("name") or "").strip().removeprefix("qwen-cli/")
                                if not lookup_model or e_id == lookup_model or e_name == lookup_model:
                                    b_url = str(entry.get("baseUrl") or "").strip()
                                    if b_url:
                                        return b_url, _is_local_endpoint(b_url)
            # 2. Comprobar model.baseUrl o security.auth.baseUrl
            base_url = str(
                data.get("model", {}).get("baseUrl")
                or data.get("security", {}).get("auth", {}).get("baseUrl")
                or ""
            ).strip()
            if base_url:
                return base_url, _is_local_endpoint(base_url)
    except Exception:
        pass
    return "", False


def _is_known_ollama_model(name: str) -> bool:
    if not name or name == "qwen-code-default":
        return False
    clean = name.removeprefix("qwen-cli/").strip()
    with QWEN_LOCK:
        for m in QWEN_CACHE.get("models", []):
            m_id = m.get("name", "").removeprefix("qwen-cli/").strip()
            if m_id == clean or m.get("name") == name:
                return not m.get("remote", True) or bool(m.get("benchmark_capable", False))
    if ":" in clean and not any(clean.startswith(p) for p in ("http:", "https:", "file:")):
        return True
    return False


def _get_ollama_model_names() -> set[str]:
    """Obtiene los nombres de modelos realmente instalados en Ollama local."""
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {str(m.get("name", "")).strip() for m in data.get("models", []) if m.get("name")}
    except Exception:
        return set()


def _discover_qwen_models() -> list[dict[str, Any]]:
    endpoint_url, is_endpoint_local = _get_qwen_configured_endpoint()
    discovered: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1. Modelo predeterminado de Qwen Code
    default_host = "local (Ollama / endpoint local)" if is_endpoint_local else (endpoint_url or "Alibaba Cloud / Remoto")
    default_label_prov = "Qwen Code · Local" if is_endpoint_local else "Qwen Code · Remoto"
    default_auth = "CLI Qwen Code local" if is_endpoint_local else "DashScope / Configuración CLI"
    discovered.append({
        "id": "qwen-code-default",
        "label": "Qwen Code · CLI (Predeterminado)",
        "family": "Qwen",
        "remote": not is_endpoint_local,
        "remote_host": default_host,
        "provider_label": default_label_prov,
        "auth_method": default_auth,
        "is_ollama": False,
    })
    seen.add("qwen-code-default")

    # 2. Modelo activo en ~/.qwen/settings.json
    try:
        user_cfg = Path.home() / ".qwen" / "settings.json"
        if user_cfg.is_file():
            data = json.loads(user_cfg.read_text(encoding="utf-8"))
            active_model = str(data.get("model", {}).get("name", "")).strip()
            if active_model and active_model not in seen:
                family = "Qwen Coder" if "coder" in active_model.lower() else "Qwen"
                active_endpoint, is_active_local = _get_qwen_configured_endpoint(active_model)
                discovered.append({
                    "id": active_model,
                    "label": f"Qwen Code · {active_model}",
                    "family": family,
                    "remote": not is_active_local,
                    "remote_host": "local (Ollama / endpoint local)" if is_active_local else (active_endpoint or default_host),
                    "provider_label": "Qwen Code · Local" if is_active_local else "Qwen Code · Remoto",
                    "auth_method": "CLI Qwen Code local" if is_active_local else default_auth,
                    "is_ollama": False,
                })
                seen.add(active_model)
    except Exception:
        pass

    # 3. Modelos locales instalados en Ollama
    ollama_models = _get_ollama_model_names()
    for name in ollama_models:
        if "qwen" in name.lower() and name not in seen:
            family = "Qwen Coder" if "coder" in name.lower() else "Qwen"
            discovered.append({
                "id": name,
                "label": f"Qwen · {name} (Ollama)",
                "family": family,
                "remote": False,
                "remote_host": "local (Ollama / 127.0.0.1:11434)",
                "provider_label": "Qwen Code · Local (Ollama)",
                "auth_method": "Ollama local",
                "is_ollama": True,
            })
            seen.add(name)

    # 4. Modelos de nube solo si se dispone de clave de DashScope / Alibaba
    has_dashscope = bool(
        os.environ.get("DASHSCOPE_API_KEY", "").strip()
        or os.environ.get("BAILIAN_CODING_PLAN_API_KEY", "").strip()
    )
    if has_dashscope:
        for c_id, c_label, c_fam in CLOUD_QWEN_MODELS:
            if c_id not in seen:
                discovered.append({
                    "id": c_id,
                    "label": c_label,
                    "family": c_fam,
                    "remote": True,
                    "remote_host": "Alibaba Cloud DashScope",
                    "provider_label": "Qwen · Nube (DashScope API)",
                    "auth_method": "DashScope API Key",
                    "is_ollama": False,
                })
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
    models: list[dict[str, Any]] = []
    for m in raw_models:
        is_cloud = bool(m["remote"])
        models.append(
            {
                "name": f"qwen-cli/{m['id']}",
                "label": m["label"],
                "provider": "qwen_cli",
                "provider_label": m["provider_label"],
                "size": 0,
                "parameter_size": "",
                "family": m["family"],
                "quantization": "",
                "modified_at": "",
                "capabilities": ["chat", "completion"],
                "chat_capable": True,
                "vision_capable": False,
                "thinking_capable": True,
                "tools_capable": False,
                "context_length": 32768,
                "remote": is_cloud,
                "remote_host": m["remote_host"],
                "benchmark_capable": bool(m.get("is_ollama", False)),
                "auth_method": m["auth_method"],
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

    clean_model = (model or "").strip()
    raw_name = clean_model.removeprefix("qwen-cli/")
    ollama_models = _get_ollama_model_names()
    is_ollama = bool(raw_name and (clean_model in ollama_models or raw_name in ollama_models))
    endpoint_url, is_local = _get_qwen_configured_endpoint(clean_model or raw_name)

    # Fail closed si el modelo era local de Ollama pero Ollama no responde
    if _is_known_ollama_model(clean_model or raw_name) and not is_ollama:
        raise RuntimeError("El modelo local de Ollama no está accesible. No se enviará a la nube por seguridad.")

    command = [
        executable,
        "--output-format",
        "json",
        "--max-tool-calls",
        "0",
    ]
    if raw_name and raw_name != "qwen-code-default":
        command.extend(["-m", raw_name])

    child_environment = {
        "HOME": str(SAFE_HOME),
        "XDG_CONFIG_HOME": str(SAFE_HOME / ".config"),
        "XDG_CACHE_HOME": str(SAFE_HOME / ".cache"),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    }
    for key, val in os.environ.items():
        if key in ALLOWED_QWEN_ENV_VARS or (key.startswith("QWEN_") and not key.startswith("QWEN_SECRET")):
            child_environment[key] = val

    # Enrutamiento explícito a endpoint local si el modelo reside en Ollama o tiene baseUrl local
    if is_ollama:
        command.extend(["--openai-base-url", "http://127.0.0.1:11434/v1", "--auth-type", "openai"])
        child_environment["OPENAI_BASE_URL"] = "http://127.0.0.1:11434/v1"
        child_environment["OPENAI_API_KEY"] = "ollama"
        child_environment["OLLAMA_HOST"] = "http://127.0.0.1:11434"
    elif is_local and endpoint_url:
        command.extend(["--openai-base-url", endpoint_url, "--auth-type", "openai"])
        child_environment["OPENAI_BASE_URL"] = endpoint_url
        child_environment.setdefault("OPENAI_API_KEY", "local")

    command.extend(["-p", prompt])

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
