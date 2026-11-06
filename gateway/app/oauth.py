from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from meta_ai import meta_ai_auth_status, meta_ai_login_state
from nvidia import _decode_key, _encode_key

ROOT = Path(__file__).resolve().parent
# En servicio, MyKOS Gateway inyecta MYKOS_CREDENTIALS_DIR dentro de su propio
# estado privado.
OAUTH_ROOT = Path(os.environ.get("MYKOS_CREDENTIALS_DIR", str(ROOT / "data" / "oauth"))).expanduser()
OPENAI_HOME = OAUTH_ROOT / "openai-codex"
OPENAI_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
OPENROUTER_HOME = OAUTH_ROOT / "openrouter"
OPENROUTER_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
OPENROUTER_CREDENTIALS_FILE = OPENROUTER_HOME / "credentials.json"
OPENROUTER_AUTH_URL = "https://openrouter.ai/auth"
OPENROUTER_KEY_EXCHANGE_URL = "https://openrouter.ai/api/v1/auth/keys"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

_CODEX_NODE = os.environ.get("MYKOS_CODEX_NODE", shutil.which("node") or "/usr/bin/node").strip()
_CODEX_CLI = os.environ.get(
    "MYKOS_CODEX_CLI",
    str(ROOT.parent / "optional" / "codex" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"),
).strip()
LOGIN_TIMEOUT_SECONDS = 15 * 60
STATUS_CACHE_SECONDS = 15
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
URL_RE = re.compile(r"https?://[^\s\"'<>\x1b]+", re.IGNORECASE)

_LOCK = threading.RLock()
_LOGIN: dict[str, Any] = {"status": "idle", "started_at": 0.0, "url": "", "code": "", "error": ""}
_STATUS_CACHE: dict[str, Any] = {"checked_at": 0.0, "authenticated": False, "error": ""}
_OPENROUTER_LOCK = threading.RLock()
_OPENROUTER_LOGIN: dict[str, Any] = {
    "status": "idle",
    "started_at": 0.0,
    "login_url": "",
    "code_verifier": "",
    "error": "",
}


def _encode_openrouter_key(key: str) -> dict[str, str]:
    return _encode_key(key)


def _decode_openrouter_key(data: dict[str, Any]) -> str:
    return _decode_key(data)


def _paths() -> tuple[str, str]:
    node = _CODEX_NODE if Path(_CODEX_NODE).is_file() else (shutil.which("node") or "")
    cli = _CODEX_CLI
    return node, cli


def _chrome_path() -> str:
    candidates = [
        os.environ.get("MYKOS_CHROME_PATH", ""),
        shutil.which("google-chrome") or "",
        shutil.which("google-chrome-stable") or "",
        shutil.which("chromium") or "",
        shutil.which("chromium-browser") or "",
        shutil.which("xdg-open") or "",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return ""


def _open_chrome(url: str) -> None:
    chrome = _chrome_path()
    if not chrome:
        return
    try:
        cmd = [chrome, url] if chrome.endswith("xdg-open") else [chrome, "--new-tab", url]
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(OPENAI_HOME)
    for name in ("OPENAI_API_KEY", "CODEX_ACCESS_TOKEN"):
        env.pop(name, None)
    return env


def _public_login_state() -> dict[str, Any]:
    with _LOCK:
        state = dict(_LOGIN)
    if state.get("started_at") and time.time() - float(state["started_at"]) > LOGIN_TIMEOUT_SECONDS and state.get("status") == "running":
        state["status"] = "expired"
    return {
        "provider": "openai_codex_oauth",
        "status": state.get("status", "idle"),
        "login_url": state.get("url", ""),
        "user_code": state.get("code", ""),
        "error": state.get("error", ""),
    }


def _extract_code(line: str) -> str:
    # El CLI puede imprimir el código en una línea propia o dividirlo con
    # espacios/guiones. Se buscan únicamente formatos de nueve caracteres;
    # así no se confunden palabras normales con el código de dispositivo.
    patterns = (
        r"\b([A-Z0-9]{9})\b",
        r"\b([A-Z0-9]{3}[- ]+[A-Z0-9]{3}[- ]+[A-Z0-9]{3})\b",
        r"\b([A-Z0-9]{4}[- ][A-Z0-9]{5})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            return re.sub(r"[- ]", "", match.group(1))
    return ""


def _run_login() -> None:
    node, cli = _paths()
    if not node or not Path(cli).is_file():
        with _LOCK:
            _LOGIN.update(status="error", error="No se encuentra el ejecutable aislado de Codex.")
        return
    command = [node, cli, "login", "--device-auth"]
    try:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            env=_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        with _LOCK:
            _LOGIN["pid"] = process.pid
        deadline = time.time() + LOGIN_TIMEOUT_SECONDS
        waiting_for_code = False
        for raw_line in process.stdout or []:
            # El CLI usa colores ANSI; si se dejan en la URL, Chrome la recibe
            # como «%1B[0m» y la página de dispositivo no termina bien.
            line = ANSI_RE.sub("", raw_line).strip()
            if not line:
                continue
            url_match = URL_RE.search(line)
            if url_match:
                login_url = url_match.group(0).rstrip(".,)")
                should_open = False
                with _LOCK:
                    if not _LOGIN.get("url"):
                        _LOGIN["url"] = login_url
                        should_open = True
                if should_open:
                    _open_chrome(login_url)
            code = _extract_code(line)
            if not code and re.search(r"\b(?:code|código|verification|verificación|device)\b", line, re.IGNORECASE):
                waiting_for_code = True
            elif not code and waiting_for_code:
                bare_code = re.fullmatch(r"[A-Z0-9]{9}", line, re.IGNORECASE)
                if bare_code:
                    code = bare_code.group(0)
                    waiting_for_code = False
            with _LOCK:
                if code and not _LOGIN.get("code"):
                    _LOGIN["code"] = code
            if time.time() > deadline:
                process.kill()
                break
        return_code = process.wait(timeout=10)
        with _LOCK:
            if return_code == 0:
                _LOGIN["status"] = "completed"
                _LOGIN["error"] = ""
            elif _LOGIN.get("status") == "running":
                _LOGIN["status"] = "cancelled"
                _LOGIN["error"] = "El inicio de sesión OAuth no terminó correctamente."
    except Exception as error:
        with _LOCK:
            _LOGIN.update(status="error", error=f"No se pudo iniciar OAuth: {error}")


def start_openai_login() -> dict[str, Any]:
    with _LOCK:
        if _LOGIN.get("status") == "running":
            return _public_login_state()
        _LOGIN.clear()
        _LOGIN.update(status="running", started_at=time.time(), url="", code="", error="")
    thread = threading.Thread(target=_run_login, name="mykos-openai-oauth", daemon=True)
    thread.start()
    return _public_login_state()


def logout_openai() -> dict[str, Any]:
    """Remove MyKOS's isolated Codex OAuth session without touching MyKOS."""
    node, cli = _paths()
    if not node or not Path(cli).is_file():
        raise RuntimeError("No se encuentra el ejecutable aislado de Codex.")
    try:
        completed = subprocess.run(
            [node, cli, "logout"],
            cwd=str(ROOT),
            env=_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"No se pudo cerrar OpenAI OAuth en MyKOS: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Codex no pudo cerrar la sesión OAuth.").strip()
        raise RuntimeError(detail[-500:])
    with _LOCK:
        _LOGIN.clear()
        _LOGIN.update(status="idle", started_at=0.0, url="", code="", error="")
        _STATUS_CACHE.clear()
        _STATUS_CACHE.update(checked_at=0.0, authenticated=False, error="")
    return {"ok": True, "provider": "openai_codex_oauth", "status": "logged_out"}


def openai_auth_status(*, force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    with _LOCK:
        if not force and now - float(_STATUS_CACHE.get("checked_at", 0.0)) < STATUS_CACHE_SECONDS:
            return dict(_STATUS_CACHE)
    node, cli = _paths()
    authenticated = False
    error = ""
    if not node or not Path(cli).is_file():
        error = "No se encuentra Codex para OpenAI OAuth."
    else:
        try:
            completed = subprocess.run(
                [node, cli, "login", "status"],
                cwd=str(ROOT),
                env=_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            output = f"{completed.stdout}\n{completed.stderr}".lower()
            authenticated = completed.returncode == 0 and "not logged" not in output and "no estás conectado" not in output
            if not authenticated:
                error = "MyKOS no tiene una sesión OpenAI OAuth activa."
        except Exception as exc:
            error = f"No se pudo comprobar OpenAI OAuth: {exc}"
    result = {"authenticated": authenticated, "auth_method": "OpenAI Codex OAuth" if authenticated else "", "error": error}
    with _LOCK:
        _STATUS_CACHE.clear()
        _STATUS_CACHE.update(checked_at=now, **result)
    return dict(result)


def openai_model_summaries() -> list[dict[str, Any]]:
    auth = openai_auth_status()
    model_rows: list[dict[str, Any]] = []
    cache_file = OPENAI_HOME / "models_cache.json"
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        model_rows = cached.get("models", []) if isinstance(cached, dict) else []
    except (OSError, json.JSONDecodeError):
        model_rows = []
    if not model_rows:
        model_rows = [
            {"slug": "gpt-5.6-luna", "display_name": "GPT-5.6-Luna"},
            {"slug": "gpt-5.6-sol", "display_name": "GPT-5.6-Sol"},
            {"slug": "gpt-5.6-terra", "display_name": "GPT-5.6-Terra"},
            {"slug": "gpt-5.5", "display_name": "GPT-5.5"},
        ]
    result: list[dict[str, Any]] = []
    for row in model_rows:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug", "")).strip()
        if not slug or slug == "codex-auto-review":
            continue
        result.append({
            "name": f"openai-codex-oauth/{slug}",
            "label": str(row.get("display_name") or slug),
            "provider": "openai_codex_oauth",
            "provider_label": "OpenAI Codex · OAuth propio de MyKOS",
            "size": 0, "parameter_size": "", "family": "OpenAI",
            "quantization": "", "modified_at": "",
            "capabilities": ["chat", "completion", "thinking"],
            "chat_capable": bool(auth.get("authenticated")),
            "vision_capable": False, "thinking_capable": True, "tools_capable": True,
            "context_length": 258_400, "remote": True, "remote_host": "OpenAI mediante Codex OAuth",
            "benchmark_capable": False, "auth_method": "OpenAI Codex OAuth",
            "auth_status": "autenticado" if auth.get("authenticated") else "no autenticado",
            "auth_error": str(auth.get("error", "")),
        })
    priority = {"gpt-5.6-luna": 0, "gpt-5.6-sol": 1, "gpt-5.5": 2, "gpt-5.6-terra": 3}
    result.sort(key=lambda item: (priority.get(item["name"].rsplit("/", 1)[-1], 20), item["label"]))
    return result


def openai_model_summary() -> dict[str, Any]:
    return openai_model_summaries()[0]


def _openrouter_key() -> str:
    try:
        data = json.loads(OPENROUTER_CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    # Decodificar con el gestor común (_decode_openrouter_key soporta mykos-sealed-v1, plain-local y dpapi)
    decoded = _decode_openrouter_key(data)
    if decoded:
        return decoded

    # Migración de credenciales antiguas en texto plano con propiedad "key"
    legacy_key = str(data.get("key", "")).strip()
    if legacy_key:
        _save_openrouter_key(legacy_key)
    return legacy_key


def _save_openrouter_key(key: str) -> None:
    value = str(key).strip()
    if not value:
        raise RuntimeError("OpenRouter no devolvió una credencial válida.")
    temporary = OPENROUTER_CREDENTIALS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(_encode_openrouter_key(value), ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(OPENROUTER_CREDENTIALS_FILE)


def _openrouter_public_login_state() -> dict[str, Any]:
    with _OPENROUTER_LOCK:
        state = dict(_OPENROUTER_LOGIN)
    if (
        state.get("status") == "running"
        and state.get("started_at")
        and time.time() - float(state["started_at"]) > LOGIN_TIMEOUT_SECONDS
    ):
        state["status"] = "expired"
        state["error"] = "El inicio de sesión de OpenRouter ha caducado."
    return {
        "provider": "openrouter",
        "status": state.get("status", "idle"),
        "login_url": state.get("login_url", ""),
        "error": state.get("error", ""),
    }


def openrouter_auth_status() -> dict[str, Any]:
    authenticated = bool(_openrouter_key())
    return {
        "authenticated": authenticated,
        "auth_method": "OpenRouter OAuth (PKCE)" if authenticated else "",
        "error": "" if authenticated else "MyKOS todavía no tiene una sesión OpenRouter OAuth.",
    }


def start_openrouter_oauth(callback_url: str) -> dict[str, Any]:
    if not str(callback_url).strip():
        raise RuntimeError("MyKOS no tiene una URL de callback para OpenRouter.")
    if _openrouter_key():
        return {"ok": True, **_openrouter_public_login_state(), "status": "completed", "authenticated": True}
    verifier = secrets.token_urlsafe(64)
    oauth_state = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    query = urllib.parse.urlencode(
        {
            "callback_url": callback_url,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": oauth_state,
            "key_label": "MyKOS",
        }
    )
    login_url = f"{OPENROUTER_AUTH_URL}?{query}"
    with _OPENROUTER_LOCK:
        _OPENROUTER_LOGIN.clear()
        _OPENROUTER_LOGIN.update(
            status="running",
            started_at=time.time(),
            login_url=login_url,
            code_verifier=verifier,
            oauth_state=oauth_state,
            error="",
        )
    return {"ok": True, **_openrouter_public_login_state()}


def complete_openrouter_oauth(code: str = "", error: str = "", state: str = "") -> dict[str, Any]:
    with _OPENROUTER_LOCK:
        verifier = str(_OPENROUTER_LOGIN.get("code_verifier", ""))
        expected_state = str(_OPENROUTER_LOGIN.get("oauth_state", ""))
        running = _OPENROUTER_LOGIN.get("status") == "running"

    if not running or not verifier or not expected_state:
        raise RuntimeError("No hay un inicio de sesión OpenRouter pendiente en MyKOS.")

    # El parámetro state es OBLIGATORIO y debe coincidir de forma estricta (prevención de CSRF / confusión)
    clean_state = str(state or "").strip()
    if not clean_state or not hmac.compare_digest(clean_state.encode("utf-8"), expected_state.encode("utf-8")):
        raise RuntimeError("El parámetro state de OAuth es inválido o no coincide; posible petición falsificada.")

    if error:
        with _OPENROUTER_LOCK:
            _OPENROUTER_LOGIN.update(status="error", error=str(error), code_verifier="", oauth_state="")
        return _openrouter_public_login_state()

    if not str(code).strip():
        raise RuntimeError("OpenRouter no devolvió el código de autorización.")
    body = json.dumps(
        {
            "code": str(code).strip(),
            "code_verifier": verifier,
            "code_challenge_method": "S256",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_KEY_EXCHANGE_URL,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(50_000).decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"OpenRouter rechazó la autorización ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No se pudo completar el OAuth de OpenRouter: {exc}") from exc
    key = payload.get("key") if isinstance(payload, dict) else ""
    _save_openrouter_key(str(key))
    with _OPENROUTER_LOCK:
        _OPENROUTER_LOGIN.update(status="completed", code_verifier="", error="")
    return _openrouter_public_login_state()


def logout_openrouter_oauth() -> dict[str, Any]:
    try:
        OPENROUTER_CREDENTIALS_FILE.unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeError(f"No se pudo eliminar la sesión OpenRouter de MyKOS: {exc}") from exc
    with _OPENROUTER_LOCK:
        _OPENROUTER_LOGIN.clear()
        _OPENROUTER_LOGIN.update(status="idle", started_at=0.0, login_url="", code_verifier="", error="")
    return {"ok": True, "provider": "openrouter", "status": "logged_out"}


def openrouter_api_json(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    key = _openrouter_key()
    if not key:
        raise RuntimeError("MyKOS todavía no tiene una sesión OpenRouter OAuth.")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"https://openrouter.ai/api/v1/{path.lstrip('/')}",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Title": "MyKOS",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"OpenRouter devolvió HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No se pudo consultar OpenRouter: {exc}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("OpenRouter devolvió un formato inesperado.")
    return result


def openrouter_models() -> list[dict[str, Any]]:
    result = openrouter_api_json("models")
    rows = result.get("data") if isinstance(result.get("data"), list) else []
    return [row for row in rows if isinstance(row, dict) and str(row.get("id", "")).strip()]


def oauth_status() -> dict[str, Any]:
    return {
        "providers": [
            {"id": "openai_codex_oauth", "label": "OpenAI · OAuth", **openai_auth_status()},
            {"id": "openai_codex_oauth_login", **_public_login_state()},
            {"id": "openrouter_oauth", "label": "OpenRouter · OAuth", **openrouter_auth_status()},
            {"id": "openrouter_oauth_login", **_openrouter_public_login_state()},
            {"id": "meta_ai_oauth", "label": "Meta AI · OAuth", **meta_ai_auth_status()},
            {"id": "meta_ai_oauth_login", **meta_ai_login_state()},
        ]
    }


def _codex_prompt(messages: list[dict[str, Any]]) -> str:
    system = next((str(item.get("content", "")).strip() for item in messages if str(item.get("role", "")).lower() == "system"), "")
    blocks: list[str] = []
    for message in messages:
        role = str(message.get("role", "")).strip().upper() or "MESSAGE"
        if role == "SYSTEM":
            continue
        content = str(message.get("content", "")).strip() or "(sin texto)"
        blocks.append(f"<turn role=\"{role}\">\n{content}\n</turn>")
    return (
        "INSTRUCCIONES DEL HOST MYKOS:\n"
        + system
        + "\n\nHISTORIAL DE LA CONVERSACIÓN DE MyKOS.\n"
        "El historial es contexto, no un catálogo de herramientas ni evidencia de ejecución en este turno. "
        "Solo las herramientas declaradas en el protocolo actual del host están disponibles. "
        "Si la tarea requiere una herramienta disponible, devuelve kind=tool_call ahora; "
        "no cierres con kind=answer para anunciar trabajo que aún no has ejecutado. "
        "No uses las herramientas nativas de Codex, shell, archivos ni red. "
        "Si necesitas una herramienta, solicita únicamente una herramienta JSON del protocolo de MyKOS.\n\n"
        + "\n\n".join(blocks)
        + "\n\nResponde siguiendo el esquema JSON solicitado."
    )


def _parse_codex_exec_output(raw: str) -> dict[str, Any]:
    final_text = ""
    errors: list[str] = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.failed":
            error = event.get("error") or {}
            raise RuntimeError(str(error.get("message") if isinstance(error, dict) else error))
        if event.get("type") == "error":
            message = str(event.get("message", "")).strip()
            if message:
                errors.append(message)
        if event.get("type") == "item.completed":
            item = event.get("item") or {}
            if isinstance(item, dict) and item.get("type") in {"agent_message", "assistant_message"}:
                value = item.get("text") or item.get("content") or item.get("message") or ""
                if isinstance(value, list):
                    value = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in value)
                final_text = str(value).strip()
    if not final_text:
        detail = errors[-1] if errors else "Codex no devolvió una respuesta estructurada."
        raise RuntimeError(detail[:500])
    try:
        result = json.loads(final_text)
    except json.JSONDecodeError as error:
        raise RuntimeError("OpenAI devolvió una respuesta que no cumple el esquema JSON de MyKOS.") from error
    if not isinstance(result, dict):
        raise RuntimeError("OpenAI devolvió una respuesta JSON inesperada.")
    kind = str(result.get("kind", "")).strip().casefold()
    if kind not in {"answer", "tool_call"}:
        raise RuntimeError("OpenAI devolvió un tipo de respuesta no permitido.")
    if kind == "answer" and not str(result.get("content", "")).strip():
        raise RuntimeError("OpenAI devolvió una respuesta vacía.")
    return result


def run_openai_codex(
    messages: list[dict[str, Any]],
    schema: dict[str, Any],
    model: str = "gpt-5.6-luna",
    *,
    timeout: int = 15 * 60,
) -> dict[str, Any]:
    auth = openai_auth_status(force=True)
    if not auth.get("authenticated"):
        raise RuntimeError(str(auth.get("error") or "MyKOS no tiene una sesión OpenAI OAuth activa."))
    node, cli = _paths()
    if not node or not Path(cli).is_file():
        raise RuntimeError("No se encuentra el ejecutable aislado de Codex.")
    schema_path = OPENAI_HOME / "mykos-response-schema.json"
    schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
    command = [
        node, cli, "exec", "--ephemeral", "--json", "--model", model, "--output-schema", str(schema_path),
        "--skip-git-repo-check", "--sandbox", "read-only", "--cd", str(OPENAI_HOME),
        "--ignore-user-config", "-",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            env=_environment(),
            input=_codex_prompt(messages),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("OpenAI tardó demasiado en responder y MyKOS canceló la petición.") from error
    except OSError as error:
        raise RuntimeError(f"No se pudo iniciar Codex aislado: {error}") from error
    if completed.returncode != 0 and not completed.stdout:
        detail = (completed.stderr or "").strip() or "Codex terminó con error."
        raise RuntimeError(detail[:500])
    return _parse_codex_exec_output(completed.stdout or "")
