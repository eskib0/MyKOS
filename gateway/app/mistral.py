"""Proveedor directo Mistral AI / Vibe API.
La clave se resuelve automáticamente desde el keyring del sistema de Vibe (ai.mistral.vibe -> MISTRAL_API_KEY)
o desde las credenciales protegidas de MyKOS.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from nvidia import _decode_key, _encode_key

ROOT = Path(__file__).resolve().parent
MISTRAL_CREDENTIALS_DIR = Path(os.environ.get("MYKOS_CREDENTIALS_DIR", str(ROOT / "data" / "oauth"))).expanduser() / "mistral"
MISTRAL_CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
FILE = MISTRAL_CREDENTIALS_DIR / "credentials.json"
BASE = os.environ.get("MYKOS_MISTRAL_API_URL", "https://api.mistral.ai/v1").rstrip("/")


def _ensure_dbus_session_bus() -> None:
    if "DBUS_SESSION_BUS_ADDRESS" not in os.environ:
        try:
            uid = os.getuid()
            bus_path = Path(f"/run/user/{uid}/bus")
            if bus_path.exists():
                os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"
        except Exception:
            pass


def _saved_key() -> str:
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return _decode_key(data) if isinstance(data, dict) else ""


def _vibe_keyring_key() -> str:
    _ensure_dbus_session_bus()
    try:
        import keyring
        key = keyring.get_password("ai.mistral.vibe", "MISTRAL_API_KEY")
        if key:
            return str(key).strip()
    except Exception:
        pass
    # Fallback con el python del entorno uv de vibe
    real_user_home = Path.home()
    candidate_pythons = [
        real_user_home / ".local/share/uv/tools/mistral-vibe/bin/python",
    ]
    for vibe_python in candidate_pythons:
        if vibe_python.exists():
            try:
                env = dict(os.environ)
                env["HOME"] = str(real_user_home)
                if "DBUS_SESSION_BUS_ADDRESS" not in env:
                    uid = os.getuid()
                    bus_path = Path(f"/run/user/{uid}/bus")
                    if bus_path.exists():
                        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"
                res = subprocess.run(
                    [
                        str(vibe_python),
                        "-c",
                        "import keyring; print(keyring.get_password('ai.mistral.vibe', 'MISTRAL_API_KEY') or '')",
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                val = res.stdout.strip()
                if val:
                    return val
            except Exception:
                pass
    return ""


def get_mistral_api_key() -> str:
    key = _saved_key() or os.environ.get("MISTRAL_API_KEY", "").strip()
    return key


def save_mistral_api_key(key: str) -> None:
    key = str(key).strip()
    if not key:
        raise RuntimeError("Introduce una clave válida de Mistral.")
    temp = FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(_encode_key(key), ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(FILE)


def link_vibe_keyring() -> str:
    key = _vibe_keyring_key()
    if not key:
        raise RuntimeError("No se encontró ninguna clave de Mistral en la sesión de Vibe del sistema.")
    save_mistral_api_key(key)
    return key


def clear_mistral_api_key() -> None:
    try:
        if FILE.exists():
            FILE.unlink()
    except OSError:
        pass


def mistral_auth_status() -> dict[str, Any]:
    key = get_mistral_api_key()
    ok = bool(key)
    return {
        "available": True,
        "authenticated": ok,
        "auth_method": "Mistral API / Vibe" if ok else "",
        "error": "" if ok else "Mistral todavía no está conectado en MyKOS.",
    }


def _request(path: str, *, key: str = "", payload: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
    token = key or get_mistral_api_key()
    if not token:
        raise RuntimeError("MyKOS todavía no tiene una clave de Mistral.")
    req = urllib.request.Request(
        f"{BASE}/{path.lstrip('/')}",
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        method="POST" if payload is not None else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Mistral rechazó la solicitud (HTTP {exc.code}): {exc.read().decode('utf-8', errors='replace')[:400]}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No se pudo consultar Mistral: {exc}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Mistral devolvió un formato inesperado.")
    return result


def mistral_models(key: str = "") -> list[dict[str, Any]]:
    rows = _request("models", key=key).get("data", [])
    valid = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id", "")).strip()
        if not model_id:
            continue
        caps = row.get("capabilities") or {}
        # Filtrar solo modelos que soporten chat / completions
        if isinstance(caps, dict) and caps.get("completion_chat") is False:
            continue
        valid.append(row)
    if not valid:
        raise RuntimeError("Mistral aceptó la conexión, pero no devolvió modelos disponibles.")
    return valid


def mistral_chat_completion(
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> str:
    model_id = model.removeprefix("mistral/")
    valid_messages = list(messages)
    while valid_messages and valid_messages[-1].get("role") == "assistant":
        valid_messages.pop()
    if not valid_messages:
        valid_messages = [{"role": "user", "content": "Hola"}]

    data = _request(
        "chat/completions",
        payload={
            "model": model_id,
            "messages": valid_messages,
            "max_tokens": max(1, min(8192, int(max_tokens))),
            "temperature": max(0.0, min(1.5, float(temperature))),
            "stream": False,
        },
        timeout=180,
    )
    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
    msg = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}

    # 1. Si Mistral devolvió una llamada nativa a herramienta (tool_calls),
    # transformarla al formato JSON esperado por el bucle de herramientas de MyKOS.
    tool_calls = msg.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        first = tool_calls[0] if isinstance(tool_calls[0], dict) else {}
        fn = first.get("function") if isinstance(first.get("function"), dict) else {}
        tool_name = str(fn.get("name", "")).strip()
        raw_args = fn.get("arguments", "{}")
        args = {}
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except Exception:
                args = {}
        elif isinstance(raw_args, dict):
            args = raw_args
        if isinstance(args, dict) and "arguments" in args and len(args) == 1 and isinstance(args["arguments"], dict):
            args = args["arguments"]
        if tool_name:
            return json.dumps({
                "kind": "tool_call",
                "tool_name": tool_name,
                "arguments": args,
            }, ensure_ascii=False)

    # 2. Extraer texto y razonamiento del contenido
    raw_content = msg.get("content", "")
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    if isinstance(raw_content, str):
        text_parts.append(raw_content)
    elif isinstance(raw_content, list):
        for part in raw_content:
            if isinstance(part, dict):
                ptype = part.get("type")
                if ptype == "text":
                    text_parts.append(str(part.get("text", "")))
                elif ptype == "thinking":
                    th = part.get("thinking")
                    if isinstance(th, list):
                        for sub in th:
                            if isinstance(sub, dict) and sub.get("type") == "text":
                                thinking_parts.append(str(sub.get("text", "")))
                    elif isinstance(th, str):
                        thinking_parts.append(th)
                elif "text" in part:
                    text_parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                text_parts.append(part)

    text = "".join(text_parts).strip()
    if not text and thinking_parts:
        text = "".join(thinking_parts).strip()

    if not text:
        raise RuntimeError(str(data.get("error") or "Mistral no devolvió texto."))
    return text
