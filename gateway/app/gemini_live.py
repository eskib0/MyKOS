"""Sesiones Gemini Live: MyKOS crea tokens efímeros sin revelar la API key."""
from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from typing import Any

from gemini import _key

AUTH_TOKENS_URL = "https://generativelanguage.googleapis.com/v1alpha/auth_tokens"
DEFAULT_MODEL = "gemini-3.8-live"
DEFAULT_VOICE = "Puck"


def _error_detail(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")[:800]
    try:
        data = json.loads(text)
        return str(data.get("error", {}).get("message") or text)
    except (TypeError, ValueError):
        return text


def create_ephemeral_token(model: str = DEFAULT_MODEL, voice: str = DEFAULT_VOICE) -> dict[str, Any]:
    """Crea un token Live de un solo uso y con vida corta.

    El token no es una API key: queda restringido a una sesión WebSocket de
    Gemini Live. La key permanente nunca sale de este proceso.
    """
    api_key = _key()
    if not api_key:
        raise RuntimeError("MyKOS no tiene una API key de Gemini para la llamada Live.")
    model = str(model or DEFAULT_MODEL).strip()
    voice = str(voice or DEFAULT_VOICE).strip()
    if not model or len(model) > 120 or not voice or len(voice) > 80:
        raise RuntimeError("La configuración de Gemini Live no es válida.")
    now = dt.datetime.now(dt.timezone.utc)
    expires = now + dt.timedelta(minutes=10)
    new_session_expires = now + dt.timedelta(minutes=1)
    payload = {
        "uses": 1,
        "expireTime": expires.isoformat().replace("+00:00", "Z"),
        "newSessionExpireTime": new_session_expires.isoformat().replace("+00:00", "Z"),
    }
    req = urllib.request.Request(
        AUTH_TOKENS_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Gemini Live rechazó el token (HTTP {exc.code}): {_error_detail(exc.read())}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("No se pudo preparar la llamada Gemini Live.") from exc
    token = str(data.get("name") or "").strip()
    if not token.startswith("auth_tokens/"):
        raise RuntimeError("Gemini Live devolvió un token no válido.")
    return {"token": token, "expires_at": payload["expireTime"], "model": model, "voice": voice}
