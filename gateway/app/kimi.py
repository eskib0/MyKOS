"""Proveedor directo Kimi API; la clave se cifra con DPAPI mediante MyKOS."""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from nvidia import _decode_key, _encode_key

ROOT = Path(__file__).resolve().parent
HOME = Path(os.environ.get("MYKOS_CREDENTIALS_DIR", str(ROOT / "data" / "oauth"))).expanduser() / "kimi"
HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
try:
    os.chmod(HOME, 0o700)
except OSError:
    pass
FILE = HOME / "credentials.json"
# Endpoint OpenAI-compatible documentado por Kimi Open Platform.
BASE = os.environ.get("MYKOS_KIMI_API_URL", "https://api.moonshot.ai/v1").rstrip("/")

def _key() -> str:
    try: data = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return ""
    return _decode_key(data) if isinstance(data, dict) else ""

def save_kimi_api_key(key: str) -> None:
    key = str(key).strip()
    if not key: raise RuntimeError("Introduce una clave personal de Kimi.")
    temp = FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(_encode_key(key), ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(FILE)

def clear_kimi_api_key() -> None: FILE.unlink(missing_ok=True)

def kimi_auth_status() -> dict[str, Any]:
    ok = bool(_key())
    return {"authenticated": ok, "auth_method": "Kimi API Key" if ok else "", "error": "" if ok else "MyKOS todavía no tiene una clave de Kimi."}

def _request(path: str, *, key: str = "", payload: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
    token = key or _key()
    if not token: raise RuntimeError("MyKOS todavía no tiene una clave de Kimi.")
    req = urllib.request.Request(f"{BASE}/{path.lstrip('/')}", data=json.dumps(payload).encode("utf-8") if payload is not None else None, method="POST" if payload is not None else "GET", headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response: result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc: raise RuntimeError(f"Kimi rechazó la solicitud (HTTP {exc.code}): {exc.read().decode('utf-8', errors='replace')[:400]}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc: raise RuntimeError(f"No se pudo consultar Kimi: {exc}") from exc
    if not isinstance(result, dict): raise RuntimeError("Kimi devolvió un formato inesperado.")
    return result

def kimi_models(key: str = "") -> list[dict[str, Any]]:
    rows = _request("models", key=key).get("data", [])
    rows = [row for row in rows if isinstance(row, dict) and str(row.get("id", "")).strip()]
    if not rows: raise RuntimeError("Kimi aceptó la conexión, pero no devolvió modelos disponibles.")
    return rows

def kimi_chat_completion(model: str, messages: list[dict[str, Any]], *, max_tokens: int = 1536, temperature: float = .2) -> str:
    # Kimi K2.6 exige temperature=1; usar el valor compatible para todo el
    # proveedor evita que el selector de creatividad de MyKOS rompa la llamada.
    data = _request("chat/completions", payload={"model": model.removeprefix("kimi/"), "messages": messages, "max_tokens": max(1, min(8192, int(max_tokens))), "temperature": 1, "stream": False}, timeout=180)
    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
    msg = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
    text = msg.get("content", "") if isinstance(msg, dict) else ""
    if isinstance(text, list):
        text = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in text)
    if not str(text).strip(): raise RuntimeError(str(data.get("error") or "Kimi no devolvió texto."))
    return str(text).strip()
