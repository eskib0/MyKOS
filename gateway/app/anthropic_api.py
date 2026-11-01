"""Proveedor directo Anthropic Messages API (Claude 3.5 / 3.7 Sonnet y Haiku).
La clave se cifra mediante el gestor de credenciales de MyKOS.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from nvidia import _decode_key, _encode_key

ROOT = Path(__file__).resolve().parent
_GATEWAY_CREDS = ROOT.parent / "state" / "mykos" / "credentials"
_CREDS_BASE = os.environ.get("MYKOS_CREDENTIALS_DIR")
if _CREDS_BASE:
    HOME = Path(_CREDS_BASE).expanduser() / "anthropic"
elif _GATEWAY_CREDS.exists():
    HOME = _GATEWAY_CREDS / "anthropic"
else:
    HOME = ROOT / "data" / "oauth" / "anthropic"
HOME.mkdir(parents=True, exist_ok=True)
FILE = HOME / "credentials.json"
BASE = os.environ.get("MYKOS_ANTHROPIC_API_URL", "https://api.anthropic.com/v1").rstrip("/")
ANTHROPIC_VERSION = "2023-06-01"

ANTHROPIC_MODELS: list[dict[str, Any]] = [
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


def clear_anthropic_api_key() -> dict[str, Any]:
    try:
        if FILE.exists():
            FILE.unlink()
    except OSError:
        pass
    return {"ok": True, "provider": "anthropic_api", "status": "logged_out"}


def validate_anthropic_api_key(key: str) -> list[str]:
    key = str(key).strip()
    if not key or not key.startswith("sk-ant-"):
        raise RuntimeError("La clave debe comenzar con sk-ant-.")
    url = f"{BASE}/models"
    req = urllib.request.Request(
        url,
        headers={
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
            "User-Agent": "MyKOS-Gateway/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            data_list = data.get("data", [])
            return [str(m.get("id")) for m in data_list if isinstance(m, dict)]
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            body = json.loads(error.read().decode("utf-8"))
            detail = body.get("error", {}).get("message", "")
        except Exception:
            pass
        raise RuntimeError(f"Anthropic API rechazó la clave ({error.code}): {detail or error.reason}")
    except Exception as error:
        raise RuntimeError(f"No se pudo conectar con Anthropic API: {error}")


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
    return {
        "available": True,
        "authenticated": True,
        "provider": "anthropic_api",
        "models": len(ANTHROPIC_MODELS),
        "error": "",
    }


def anthropic_model_catalog() -> tuple[list[dict[str, Any]], bool, str]:
    key = _key()
    if not key:
        return [], False, ""
    models = []
    for m in ANTHROPIC_MODELS:
        models.append({
            "name": m["name"],
            "label": m["label"],
            "provider": "anthropic_api",
            "provider_label": "Anthropic · Direct API",
            "size": 0,
            "parameter_size": "",
            "family": m["family"],
            "quantization": "",
            "modified_at": "",
            "capabilities": ["chat", "completion", "thinking" if m["thinking_capable"] else "", "tools"],
            "chat_capable": True,
            "vision_capable": m["vision_capable"],
            "thinking_capable": m["thinking_capable"],
            "tools_capable": True,
            "context_length": m["context_length"],
            "remote": True,
            "remote_host": "api.anthropic.com",
            "benchmark_capable": False,
            "auth_method": "API Key (sk-ant-...)",
            "auth_status": "autenticado",
            "auth_error": "",
        })
    return models, True, ""


def _format_tools(tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    formatted = []
    for schema in tool_schemas:
        if not isinstance(schema, dict) or not schema.get("name"):
            continue
        params = schema.get("parameters") or {"type": "object", "properties": {}}
        formatted.append({
            "name": schema["name"],
            "description": schema.get("description", ""),
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

    # Extraer ID del modelo real
    target_id = "claude-3-5-sonnet-20241022"
    clean_name = model_name.removeprefix("anthropic/")
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

    payload: dict[str, Any] = {
        "model": target_id,
        "max_tokens": 4096,
        "messages": anthropic_messages,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)

    if tool_schemas:
        payload["tools"] = _format_tools(tool_schemas)

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
