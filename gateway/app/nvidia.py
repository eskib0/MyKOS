from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_GATEWAY_CREDS = Path.home() / ".mykos" / "gateway-state" / "mykos" / "credentials"
_CREDS_BASE = os.environ.get("MYKOS_CREDENTIALS_DIR")
if _CREDS_BASE:
    CREDENTIALS_ROOT = Path(_CREDS_BASE).expanduser()
elif _GATEWAY_CREDS.exists():
    CREDENTIALS_ROOT = _GATEWAY_CREDS
else:
    CREDENTIALS_ROOT = ROOT / "data" / "oauth"
NVIDIA_HOME = CREDENTIALS_ROOT / "nvidia"
NVIDIA_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
try:
    os.chmod(NVIDIA_HOME, 0o700)
except OSError:
    pass
CREDENTIALS_FILE = NVIDIA_HOME / "credentials.json"
MASTER_KEY_FILE = CREDENTIALS_ROOT / ".master_key"
NVIDIA_API_BASE = os.environ.get("MYKOS_NVIDIA_API_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")


def _master_key() -> bytes:
    CREDENTIALS_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        if MASTER_KEY_FILE.is_file():
            raw = base64.b64decode(MASTER_KEY_FILE.read_text(encoding="utf-8").strip(), validate=True)
            if len(raw) == 32:
                return raw
    except (OSError, ValueError):
        pass
    key = secrets.token_bytes(32)
    tmp = MASTER_KEY_FILE.with_suffix(".tmp")
    tmp.write_text(base64.b64encode(key).decode("ascii"), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(MASTER_KEY_FILE)
    return key


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _seal_bytes(plaintext: bytes) -> bytes:
    key = _master_key()
    nonce = secrets.token_bytes(16)
    stream = _keystream(key, nonce, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
    tag = hmac.new(key, b"mykos-cred-v1|" + nonce + ciphertext, hashlib.sha256).digest()
    return nonce + tag + ciphertext


def _open_bytes(blob: bytes) -> bytes:
    if len(blob) < 48:
        raise ValueError("Credencial cifrada truncada.")
    key = _master_key()
    nonce = blob[:16]
    tag = blob[16:48]
    ciphertext = blob[48:]
    expected = hmac.new(key, b"mykos-cred-v1|" + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("Firma de credencial inválida.")
    stream = _keystream(key, nonce, len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, stream))


def _encode_key(key: str) -> dict[str, str]:
    protected = _seal_bytes(key.encode("utf-8"))
    return {
        "encoding": "mykos-sealed-v1",
        "value": base64.b64encode(protected).decode("ascii"),
    }


def _decode_key(data: dict[str, Any]) -> str:
    try:
        raw = base64.b64decode(str(data.get("value", "")), validate=True)
        encoding = str(data.get("encoding", ""))
        if encoding == "mykos-sealed-v1":
            raw = _open_bytes(raw)
        elif encoding not in {"plain-local", ""}:
            return ""
        return raw.decode("utf-8").strip()
    except (ValueError, TypeError, OSError, UnicodeDecodeError):
        return ""


def get_nvidia_api_key() -> str:
    try:
        data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return _decode_key(data) if isinstance(data, dict) else ""


def save_nvidia_api_key(key: str) -> None:
    value = str(key).strip()
    if not value:
        raise RuntimeError("Introduce una clave personal de NVIDIA.")
    NVIDIA_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = CREDENTIALS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(_encode_key(value), ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(CREDENTIALS_FILE)


def clear_nvidia_api_key() -> None:
    try:
        CREDENTIALS_FILE.unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeError(f"No se pudo eliminar la credencial NVIDIA: {exc}") from exc


def nvidia_auth_status() -> dict[str, Any]:
    authenticated = bool(get_nvidia_api_key())
    return {
        "authenticated": authenticated,
        "auth_method": "NVIDIA Personal API Key" if authenticated else "",
        "error": "" if authenticated else "MyKOS todavía no tiene una clave personal de NVIDIA.",
    }


def _request_json(path: str, *, key: str | None = None, method: str = "GET", payload: dict[str, Any] | None = None, timeout: int = 45) -> dict[str, Any]:
    token = str(key or get_nvidia_api_key()).strip()
    if not token:
        raise RuntimeError("MyKOS todavía no tiene una clave personal de NVIDIA.")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{NVIDIA_API_BASE}/{path.lstrip('/')}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code == 404 and "Function" in detail and "account" in detail:
            raise RuntimeError(
                "NVIDIA ha aceptado la clave, pero esta cuenta no tiene habilitados los Public API Endpoints "
                "para ese modelo. Actívalos en la cuenta de NVIDIA o elige un modelo habilitado."
            ) from exc
        if exc.code == 410 and "end of life" in detail.casefold():
            raise RuntimeError("El modelo NVIDIA seleccionado ha llegado al final de su vida útil. Actualiza el catálogo y elige otro modelo.") from exc
        raise RuntimeError(f"NVIDIA rechazó la solicitud (HTTP {exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No se pudo consultar NVIDIA: {exc}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("NVIDIA devolvió un formato inesperado.")
    return result


_NON_CHAT_NVIDIA_MARKERS = (
    "embed",
    "rerank",
    "guard",
    "shield",
    "parse",
    "vila",
    "cosmos",
    "sdxl",
    "flux",
)


def is_nvidia_chat_model(row: dict[str, Any]) -> bool:
    """Devuelve True si el modelo NVIDIA NIM es apto para conversación de chat."""
    if not isinstance(row, dict):
        return False
    model_id = str(row.get("id", "")).strip()
    if not model_id:
        return False
    lowered = model_id.casefold()
    return not any(marker in lowered for marker in _NON_CHAT_NVIDIA_MARKERS)


def validate_nvidia_api_key(key: str) -> list[dict[str, Any]]:
    result = _request_json("models", key=str(key).strip())
    rows = result.get("data") if isinstance(result.get("data"), list) else []
    if not rows:
        raise RuntimeError("NVIDIA aceptó la conexión, pero no devolvió modelos disponibles.")
    return [row for row in rows if isinstance(row, dict) and str(row.get("id", "")).strip()]


def nvidia_models() -> list[dict[str, Any]]:
    return [row for row in validate_nvidia_api_key(get_nvidia_api_key()) if is_nvidia_chat_model(row)]


def nvidia_chat_completion(model: str, messages: list[dict[str, Any]], *, max_tokens: int = 1536, temperature: float = 0.2) -> str:
    model_id = str(model).strip()
    if model_id.startswith("nvidia/"):
        model_id = model_id.removeprefix("nvidia/")
    result = _request_json(
        "chat/completions",
        method="POST",
        payload={
            "model": model_id,
            "messages": messages,
            "max_tokens": max(1, min(8192, int(max_tokens))),
            "temperature": max(0.0, min(2.0, float(temperature))),
            "stream": False,
        },
        timeout=180,
    )
    choices = result.get("choices") if isinstance(result.get("choices"), list) else []
    first = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = str(message.get("content") or message.get("reasoning_content") or "").strip()
    if not content:
        raise RuntimeError("NVIDIA no devolvió texto de respuesta.")
    return content
