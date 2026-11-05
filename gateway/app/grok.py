"""Proveedor oficial e integraciones para Grok (xAI) en MyKOS.
Soporta autenticación dual:
1. OAuth 2.0 (OIDC / Device Code & PKCE) con cuenta de xAI / SuperGrok.
2. Clave de API personal de xAI (xai-...).
Ambas opciones se cifran en reposo con la clave maestra de MyKOS.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from nvidia import _decode_key, _encode_key

ROOT = Path(__file__).resolve().parent
CREDENTIALS_ROOT = Path(os.environ.get("MYKOS_CREDENTIALS_DIR", str(ROOT / "data" / "oauth"))).expanduser()
GROK_HOME = CREDENTIALS_ROOT / "grok"
GROK_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
try:
    os.chmod(GROK_HOME, 0o700)
except OSError:
    pass
CREDENTIALS_FILE = GROK_HOME / "credentials.json"

AUTH_ISSUER = "https://auth.x.ai"
AUTHORIZE_URL = "https://auth.x.ai/oauth2/authorize"
DEVICE_CODE_URL = "https://auth.x.ai/oauth2/device/code"
TOKEN_URL = "https://auth.x.ai/oauth2/token"
PUBLIC_CLIENT_ID = os.environ.get("MYKOS_GROK_CLIENT_ID", "b1a00492-073a-47ea-816f-4c329264a828").strip()
DEFAULT_SCOPES = "openid profile email offline_access grok-cli:access api:access"
API_BASE = os.environ.get("MYKOS_GROK_API_URL", "https://api.x.ai/v1").rstrip("/")

_LOCK = threading.RLock()
_LOGIN_STATE: dict[str, Any] = {
    "status": "idle",  # idle, running, completed, error
    "started_at": 0.0,
    "user_code": "",
    "verification_uri": "",
    "verification_uri_complete": "",
    "code_verifier": "",
    "error": "",
}
_DEVICE_POLL_THREAD: threading.Thread | None = None

DEFAULT_GROK_MODELS: list[dict[str, Any]] = [
    {
        "id": "grok-2-latest",
        "name": "grok/grok-2-latest",
        "label": "Grok 2 (xAI)",
        "context_length": 131072,
        "vision": False,
    },
    {
        "id": "grok-2-vision-1212",
        "name": "grok/grok-2-vision-1212",
        "label": "Grok 2 Vision (xAI)",
        "context_length": 32768,
        "vision": True,
    },
    {
        "id": "grok-beta",
        "name": "grok/grok-beta",
        "label": "Grok Beta (xAI)",
        "context_length": 131072,
        "vision": False,
    },
    {
        "id": "grok-3",
        "name": "grok/grok-3",
        "label": "Grok 3 (xAI)",
        "context_length": 131072,
        "vision": False,
    },
]


def _open_browser(url: str) -> None:
    for candidate in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "firefox", "xdg-open"):
        binary = shutil.which(candidate)
        if not binary:
            continue
        try:
            subprocess.Popen(
                [binary, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
        except Exception:
            continue


def _load_grok_session() -> dict[str, Any] | None:
    if not CREDENTIALS_FILE.is_file():
        return None
    try:
        raw_json = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw_json, dict):
            return None
        decrypted = _decode_key(raw_json)
        if not decrypted:
            return None
        session = json.loads(decrypted)
        if isinstance(session, dict):
            return session
    except Exception:
        return None
    return None


def _save_grok_session(session: dict[str, Any]) -> None:
    GROK_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = json.dumps(session, ensure_ascii=False)
    sealed = _encode_key(raw)
    tmp = CREDENTIALS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(sealed, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(CREDENTIALS_FILE)


def clear_grok_credentials() -> None:
    with _LOCK:
        CREDENTIALS_FILE.unlink(missing_ok=True)
        _LOGIN_STATE.clear()
        _LOGIN_STATE.update(
            status="idle",
            started_at=0.0,
            user_code="",
            verification_uri="",
            verification_uri_complete="",
            code_verifier="",
            error="",
        )


def grok_auth_status() -> dict[str, Any]:
    session = _load_grok_session()
    with _LOCK:
        login_copy = dict(_LOGIN_STATE)

    if session:
        mode = session.get("mode", "oauth")
        if mode == "api_key":
            return {
                "authenticated": True,
                "auth_method": "Grok API Key",
                "mode": "api_key",
                "error": "",
                "login": login_copy,
            }
        access_token = session.get("access_token", "")
        if access_token:
            return {
                "authenticated": True,
                "auth_method": "Grok OAuth (xAI)",
                "mode": "oauth",
                "error": "",
                "login": login_copy,
            }

    return {
        "authenticated": False,
        "auth_method": "",
        "mode": "",
        "error": "MyKOS todavía no tiene una sesión de Grok.",
        "login": login_copy,
    }


def save_grok_api_key(key: str) -> None:
    clean_key = str(key).strip()
    if not clean_key:
        raise RuntimeError("Introduce una clave válida de xAI (Grok).")
    session = {
        "mode": "api_key",
        "api_key": clean_key,
        "saved_at": int(time.time()),
    }
    _save_grok_session(session)
    with _LOCK:
        _LOGIN_STATE.update(status="completed", error="")


def refresh_grok_oauth_token() -> str:
    session = _load_grok_session()
    if not session or session.get("mode") != "oauth":
        return ""
    refresh_token = session.get("refresh_token", "")
    if not refresh_token:
        raise RuntimeError("No hay token de refresco para renovar la sesión de Grok.")

    body = urllib.parse.urlencode(
        {
            "client_id": PUBLIC_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Error al refrescar token de Grok: {exc}") from exc

    new_access = data.get("access_token")
    if not new_access:
        raise RuntimeError("xAI no devolvió access_token en el refresco.")

    expires_in = int(data.get("expires_in", 3600))
    session["access_token"] = str(new_access)
    if data.get("refresh_token"):
        session["refresh_token"] = str(data["refresh_token"])
    session["expires_at"] = int(time.time()) + expires_in
    _save_grok_session(session)
    return str(new_access)


def _get_active_token() -> str:
    session = _load_grok_session()
    if not session:
        raise RuntimeError("MyKOS todavía no tiene una sesión de Grok configurada.")
    if session.get("mode") == "api_key":
        token = str(session.get("api_key", "")).strip()
        if not token:
            raise RuntimeError("Clave de API de Grok vacía.")
        return token

    # Modo OAuth
    expires_at = int(session.get("expires_at", 0))
    if expires_at and time.time() > (expires_at - 120):
        try:
            return refresh_grok_oauth_token()
        except Exception:
            pass
    return str(session.get("access_token", ""))


def _poll_device_code(device_code: str, interval: int, expires_in: int) -> None:
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(max(3, interval))
        with _LOCK:
            if _LOGIN_STATE.get("status") != "running":
                break

        body = urllib.parse.urlencode(
            {
                "client_id": PUBLIC_CLIENT_ID,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                access_token = data.get("access_token")
                refresh_token = data.get("refresh_token", "")
                exp_in = int(data.get("expires_in", 3600))
                if access_token:
                    session = {
                        "mode": "oauth",
                        "access_token": str(access_token),
                        "refresh_token": str(refresh_token),
                        "expires_at": int(time.time()) + exp_in,
                        "token_type": data.get("token_type", "Bearer"),
                        "scope": data.get("scope", DEFAULT_SCOPES),
                    }
                    _save_grok_session(session)
                    with _LOCK:
                        _LOGIN_STATE.update(
                            status="completed",
                            error="",
                        )
                    return
        except urllib.error.HTTPError as exc:
            try:
                err_payload = json.loads(exc.read().decode("utf-8"))
                err_code = err_payload.get("error", "")
                if err_code in ("authorization_pending", "slow_down"):
                    if err_code == "slow_down":
                        interval += 5
                    continue
                # Error fatal
                with _LOCK:
                    _LOGIN_STATE.update(
                        status="error",
                        error=f"Autorización rechazada: {err_code}",
                    )
                return
            except Exception:
                continue
        except Exception:
            continue

    with _LOCK:
        if _LOGIN_STATE.get("status") == "running":
            _LOGIN_STATE.update(status="error", error="El tiempo de autorización ha expirado.")


def start_grok_oauth(*, open_browser: bool = True) -> dict[str, Any]:
    global _DEVICE_POLL_THREAD
    auth = grok_auth_status()
    if auth.get("authenticated"):
        return {"ok": True, "already_authenticated": True, **auth}

    body = urllib.parse.urlencode(
        {
            "client_id": PUBLIC_CLIENT_ID,
            "scope": DEFAULT_SCOPES,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        DEVICE_CODE_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"No se pudo iniciar OAuth con xAI: {exc}") from exc

    device_code = data.get("device_code")
    user_code = data.get("user_code", "")
    verification_uri = data.get("verification_uri", "https://accounts.x.ai/oauth2/device")
    verification_uri_complete = data.get("verification_uri_complete", f"{verification_uri}?user_code={user_code}")
    expires_in = int(data.get("expires_in", 1800))
    interval = int(data.get("interval", 5))

    with _LOCK:
        _LOGIN_STATE.update(
            status="running",
            started_at=time.time(),
            user_code=user_code,
            verification_uri=verification_uri,
            verification_uri_complete=verification_uri_complete,
            error="",
        )

    # Iniciar polling en background
    _DEVICE_POLL_THREAD = threading.Thread(
        target=_poll_device_code,
        args=(device_code, interval, expires_in),
        daemon=True,
    )
    _DEVICE_POLL_THREAD.start()

    if open_browser:
        _open_browser(verification_uri_complete)

    return {
        "ok": True,
        "status": "running",
        "user_code": user_code,
        "verification_uri": verification_uri,
        "verification_uri_complete": verification_uri_complete,
        "login": dict(_LOGIN_STATE),
    }


def logout_grok() -> dict[str, Any]:
    clear_grok_credentials()
    return {"ok": True, "provider": "grok", "status": "logged_out"}


def grok_models(key: str = "") -> list[dict[str, Any]]:
    # Intentar obtener modelos dinámicos si la API responde
    token = key
    if not token:
        try:
            token = _get_active_token()
        except Exception:
            token = ""

    if token:
        req = urllib.request.Request(
            f"{API_BASE}/models",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                rows = data.get("data", [])
                if isinstance(rows, list) and rows:
                    out = []
                    for row in rows:
                        mid = str(row.get("id", "")).strip()
                        if not mid:
                            continue
                        out.append(
                            {
                                "id": mid,
                                "name": f"grok/{mid}",
                                "label": f"{mid} (xAI)",
                                "context_length": 131072,
                                "vision": "vision" in mid.lower(),
                            }
                        )
                    if out:
                        return out
        except Exception:
            pass

    return list(DEFAULT_GROK_MODELS)


def grok_chat_completion(
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    stream: bool = False,
) -> str:
    token = _get_active_token()
    clean_model = model.removeprefix("grok/")

    payload: dict[str, Any] = {
        "model": clean_model,
        "messages": messages,
        "max_tokens": max(1, min(16384, int(max_tokens))),
        "temperature": max(0.0, min(2.0, float(temperature))),
        "stream": stream,
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_msg = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"xAI Grok rechazó la llamada ({exc.code}): {err_msg}") from exc
    except Exception as exc:
        raise RuntimeError(f"Error conectando con Grok (xAI): {exc}") from exc

    choices = data.get("choices", [])
    if not choices or not isinstance(choices, list):
        raise RuntimeError("xAI Grok no devolvió choices válidas.")
    msg = choices[0].get("message", {})
    content = msg.get("content", "")
    if isinstance(content, list):
        content = "".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in content)
    return str(content).strip()
