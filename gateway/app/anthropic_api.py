"""Proveedor directo Anthropic Messages API (Claude 4 / 3.7 / 3.5 Sonnet, Opus y Haiku).
La clave se cifra mediante el gestor de credenciales de MyKOS.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from nvidia import _decode_key, _encode_key

ROOT = Path(__file__).resolve().parent
_GATEWAY_CREDS = Path.home() / ".mykos" / "gateway-state" / "mykos" / "credentials"
_CREDS_BASE = os.environ.get("MYKOS_CREDENTIALS_DIR")
if _CREDS_BASE:
    HOME = Path(_CREDS_BASE).expanduser() / "anthropic"
elif _GATEWAY_CREDS.exists():
    HOME = _GATEWAY_CREDS / "anthropic"
else:
    HOME = ROOT / "data" / "oauth" / "anthropic"
HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
try:
    os.chmod(HOME, 0o700)
except OSError:
    pass
FILE = HOME / "credentials.json"
BASE = os.environ.get("MYKOS_ANTHROPIC_API_URL", "https://api.anthropic.com/v1").rstrip("/")
ANTHROPIC_VERSION = "2023-06-01"
_CACHE_LOCK = threading.RLock()
_MODEL_CACHE: dict[str, Any] = {"checked_at": 0.0, "models": [], "error": ""}
_CACHE_TTL_SECONDS = 120.0

ANTHROPIC_MODELS: list[dict[str, Any]] = [
    {
        "id": "claude-sonnet-4-5-20250929",
        "alias": "claude-sonnet-4-5",
        "name": "anthropic/claude-sonnet-4-5",
        "label": "Claude Sonnet 4.5",
        "family": "Claude Sonnet",
        "context_length": 200_000,
        "thinking_capable": True,
        "vision_capable": True,
    },
    {
        "id": "claude-sonnet-4-20250514",
        "alias": "claude-sonnet-4-0",
        "name": "anthropic/claude-sonnet-4-0",
        "label": "Claude Sonnet 4",
        "family": "Claude Sonnet",
        "context_length": 200_000,
        "thinking_capable": True,
        "vision_capable": True,
    },
    {
        "id": "claude-3-7-sonnet-20250219",
        "alias": "claude-3-7-sonnet-latest",
        "name": "anthropic/claude-3-7-sonnet-latest",
        "label": "Claude 3.7 Sonnet",
        "family": "Claude Sonnet",
        "context_length": 200_000,
        "thinking_capable": True,
        "vision_capable": True,
    },
    {
        "id": "claude-3-5-sonnet-20241022",
        "alias": "claude-3-5-sonnet-latest",
        "name": "anthropic/claude-3-5-sonnet-latest",
        "label": "Claude 3.5 Sonnet",
        "family": "Claude Sonnet",
        "context_length": 200_000,
        "thinking_capable": True,
        "vision_capable": True,
    },
    {
        "id": "claude-3-5-haiku-20241022",
        "alias": "claude-3-5-haiku-latest",
        "name": "anthropic/claude-3-5-haiku-latest",
        "label": "Claude 3.5 Haiku",
        "family": "Claude Haiku",
        "context_length": 200_000,
        "thinking_capable": False,
        "vision_capable": True,
    },
]


def _key() -> str:
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    stored = _decode_key(data) if isinstance(data, dict) else ""
    if stored:
        return stored
    env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return env_key


def get_anthropic_api_key() -> str:
    return _key()


def save_anthropic_api_key(key: str) -> None:
    key = str(key).strip()
    if not key:
        raise RuntimeError("Introduce una clave personal de Anthropic (sk-ant-…).")
    temp = FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(_encode_key(key), ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(FILE)
    with _CACHE_LOCK:
        _MODEL_CACHE.update(checked_at=0.0, models=[], error="")


def clear_anthropic_api_key() -> dict[str, Any]:
    try:
        if FILE.exists():
            FILE.unlink()
    except OSError:
        pass
    with _CACHE_LOCK:
        _MODEL_CACHE.update(checked_at=0.0, models=[], error="")
    return {"ok": True, "provider": "anthropic_api", "status": "logged_out"}


def _fetch_anthropic_models(key: str) -> list[dict[str, Any]]:
    req = urllib.request.Request(
        f"{BASE}/models",
        headers={
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
            "User-Agent": "MyKOS-Gateway/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            body = json.loads(error.read().decode("utf-8"))
            detail = body.get("error", {}).get("message", "")
        except Exception:
            pass
        raise RuntimeError(f"Anthropic API rechazó la clave ({error.code}): {detail or error.reason}") from error
    except Exception as error:
        raise RuntimeError(f"No se pudo conectar con Anthropic API: {error}") from error

    raw_rows = data.get("data", []) if isinstance(data, dict) else []
    fallback_by_id = {m["id"]: m for m in ANTHROPIC_MODELS}
    discovered: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("id") or "").strip()
        if not mid or mid in seen_ids:
            continue
        seen_ids.add(mid)
        base_meta = fallback_by_id.get(mid)
        lower = mid.casefold()
        if base_meta:
            discovered.append(dict(base_meta))
            continue
        family = "Claude Opus" if "opus" in lower else ("Claude Haiku" if "haiku" in lower else "Claude Sonnet")
        label = str(row.get("display_name") or mid).strip()
        thinking = "haiku" not in lower or "4" in lower
        discovered.append({
            "id": mid,
            "alias": mid,
            "name": f"anthropic/{mid}",
            "label": label,
            "family": family,
            "context_length": 200_000,
            "thinking_capable": thinking,
            "vision_capable": True,
        })
    return discovered


def validate_anthropic_api_key(key: str) -> list[str]:
    key = str(key).strip()
    if not key or not key.startswith("sk-ant-"):
        raise RuntimeError("La clave debe comenzar con sk-ant-.")
    rows = _fetch_anthropic_models(key)
    with _CACHE_LOCK:
        if rows:
            _MODEL_CACHE.update(checked_at=time.monotonic(), models=rows, error="")
    return [m["id"] for m in rows]


def _model_entry(m: dict[str, Any]) -> dict[str, Any]:
    caps = ["chat", "completion"]
    if m.get("thinking_capable"):
        caps.append("thinking")
    caps.append("tools")
    return {
        "name": m["name"],
        "label": m["label"],
        "provider": "anthropic_api",
        "provider_label": "Anthropic · Direct API",
        "size": 0,
        "parameter_size": "",
        "family": m["family"],
        "quantization": "",
        "modified_at": "",
        "capabilities": caps,
        "chat_capable": True,
        "vision_capable": bool(m.get("vision_capable", True)),
        "thinking_capable": bool(m.get("thinking_capable", False)),
        "tools_capable": True,
        "context_length": int(m.get("context_length") or 200_000),
        "remote": True,
        "remote_host": "api.anthropic.com",
        "benchmark_capable": False,
        "auth_method": "API Key (sk-ant-...)",
        "auth_status": "autenticado",
        "auth_error": "",
    }


def anthropic_auth_status() -> dict[str, Any]:
    key = _key()
    if not key:
        return {
            "available": True,
            "authenticated": False,
            "provider": "anthropic_api",
            "models": 0,
            "error": "No hay clave personal de Anthropic configurada.",
        }
    with _CACHE_LOCK:
        cached = list(_MODEL_CACHE.get("models") or [])
        last_err = str(_MODEL_CACHE.get("error") or "")
    count = len(cached) if cached else len(ANTHROPIC_MODELS)
    return {
        "available": True,
        "authenticated": not ("rechazó" in last_err or "(401)" in last_err or "(403)" in last_err),
        "provider": "anthropic_api",
        "models": count,
        "error": last_err if ("rechazó" in last_err or "(401)" in last_err or "(403)" in last_err) else "",
    }


def anthropic_model_catalog(force: bool = False) -> tuple[list[dict[str, Any]], bool, str]:
    key = _key()
    if not key:
        return [], False, ""
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = list(_MODEL_CACHE.get("models") or [])
        checked_at = float(_MODEL_CACHE.get("checked_at", 0.0))
        if not force and cached and (now - checked_at < _CACHE_TTL_SECONDS):
            return [_model_entry(m) for m in cached], True, ""
    try:
        rows = _fetch_anthropic_models(key)
        selected = rows if rows else list(ANTHROPIC_MODELS)
        with _CACHE_LOCK:
            _MODEL_CACHE.update(checked_at=now, models=selected, error="")
        return [_model_entry(m) for m in selected], True, ""
    except RuntimeError as exc:
        err_msg = str(exc)
        if "rechazó la clave" in err_msg or "(401)" in err_msg or "(403)" in err_msg:
            with _CACHE_LOCK:
                _MODEL_CACHE.update(checked_at=now, models=[], error=err_msg)
            return [], False, err_msg
        fallback = cached if cached else list(ANTHROPIC_MODELS)
        with _CACHE_LOCK:
            _MODEL_CACHE.update(checked_at=now, models=fallback, error="")
        return [_model_entry(m) for m in fallback], True, ""


def _format_tools(tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    formatted = []
    for schema in tool_schemas:
        if not isinstance(schema, dict):
            continue
        fn = schema.get("function") if isinstance(schema.get("function"), dict) else schema
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        params = fn.get("parameters") or fn.get("input_schema") or {"type": "object", "properties": {}}
        formatted.append({
            "name": name,
            "description": str(fn.get("description") or ""),
            "input_schema": params,
        })
    return formatted


def anthropic_chat_completion(
    model_name: str,
    messages: list[dict[str, Any]],
    *,
    tool_schemas: list[dict[str, Any]] | None = None,
    generation: dict[str, Any] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    key = _key()
    if not key:
        raise RuntimeError("No hay clave de Anthropic guardada en MyKOS.")

    clean_name = str(model_name or "").strip().removeprefix("anthropic/")
    target_id = clean_name or "claude-sonnet-4-5-20250929"
    for item in ANTHROPIC_MODELS:
        if clean_name in {item["id"], item["alias"], item["name"]}:
            target_id = item["id"]
            break

    # Separar system prompt y formatear mensajes
    system_parts: list[str] = []
    anthropic_messages: list[dict[str, Any]] = []

    for msg in messages:
        role = str(msg.get("role", "user")).casefold()
        content = msg.get("content", "")

        if role == "system":
            if isinstance(content, str) and content.strip():
                system_parts.append(content.strip())
            continue

        if role == "tool":
            # Mensaje de resultado de herramienta en Anthropic va bajo rol 'user'
            tool_call_id = msg.get("tool_call_id") or "call_0"
            tool_content = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            tool_result_block = {
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": tool_content,
            }
            if anthropic_messages and anthropic_messages[-1]["role"] == "user":
                if isinstance(anthropic_messages[-1]["content"], list):
                    anthropic_messages[-1]["content"].append(tool_result_block)
                else:
                    anthropic_messages[-1]["content"] = [
                        {"type": "text", "text": str(anthropic_messages[-1]["content"])},
                        tool_result_block,
                    ]
            else:
                anthropic_messages.append({"role": "user", "content": [tool_result_block]})
            continue

        # Mensajes de user o assistant
        msg_role = "assistant" if role == "assistant" else "user"
        content_blocks = []
        if isinstance(content, str) and content:
            content_blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    content_blocks.append(part)
                elif isinstance(part, str):
                    content_blocks.append({"type": "text", "text": part})

        # Comprobar tool_calls nativos de assistant
        if role == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_fn = tc.get("function", {})
                tc_args = tc_fn.get("arguments", {})
                if isinstance(tc_args, str):
                    try:
                        tc_args = json.loads(tc_args)
                    except Exception:
                        tc_args = {}
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id") or f"call_{int(time.time()*1000)}",
                    "name": tc_fn.get("name", ""),
                    "input": tc_args,
                })

        if not content_blocks:
            content_blocks.append({"type": "text", "text": "(sin texto)"})

        # Anthropic exige alternancia estricta user/assistant
        if anthropic_messages and anthropic_messages[-1]["role"] == msg_role:
            prev_content = anthropic_messages[-1]["content"]
            if isinstance(prev_content, list):
                prev_content.extend(content_blocks)
            else:
                anthropic_messages[-1]["content"] = [{"type": "text", "text": str(prev_content)}, *content_blocks]
        else:
            anthropic_messages.append({"role": msg_role, "content": content_blocks})

    # Asegurarse de que el primer mensaje es user
    if anthropic_messages and anthropic_messages[0]["role"] == "assistant":
        anthropic_messages.insert(0, {"role": "user", "content": [{"type": "text", "text": "Continúa."}]})

    # Si la lista quedó vacía, enviar saludo
    if not anthropic_messages:
        anthropic_messages = [{"role": "user", "content": [{"type": "text", "text": "Hola"}]}]

    gen_options = generation.get("options") if isinstance(generation, dict) and isinstance(generation.get("options"), dict) else {}
    raw_max_tokens = gen_options.get("num_predict")
    try:
        max_tokens = max(512, min(8192, int(raw_max_tokens))) if raw_max_tokens is not None else 4096
    except (TypeError, ValueError):
        max_tokens = 4096

    payload: dict[str, Any] = {
        "model": target_id,
        "max_tokens": max_tokens,
        "messages": anthropic_messages,
    }
    raw_temp = gen_options.get("temperature")
    if isinstance(raw_temp, (int, float)) and 0.0 <= float(raw_temp) <= 1.0:
        payload["temperature"] = float(raw_temp)
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)

    formatted_tools = _format_tools(tool_schemas) if tool_schemas else []
    if formatted_tools:
        payload["tools"] = formatted_tools

    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/messages",
        data=body_bytes,
        headers={
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
            "User-Agent": "MyKOS-Gateway/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            err_body = json.loads(error.read().decode("utf-8"))
            detail = err_body.get("error", {}).get("message", "")
        except Exception:
            pass
        raise RuntimeError(f"Anthropic error ({error.code}): {detail or error.reason}")
    except Exception as error:
        raise RuntimeError(f"Fallo de conexión con Anthropic: {error}")

    # Procesar respuesta
    content_list = data.get("content", [])
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for block in content_list:
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_calls.append({
                "id": block.get("id"),
                "name": block.get("name"),
                "arguments": block.get("input", {}),
            })

    full_text = "".join(text_parts).strip()
    usage = data.get("usage", {})

    if tool_calls:
        first_call = tool_calls[0]
        return json.dumps({
            "kind": "tool_call",
            "tool_name": first_call["name"],
            "arguments": first_call["arguments"],
        }, ensure_ascii=False)

    return full_text
