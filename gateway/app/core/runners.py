"""Sub-módulo de ejecución de modelos remotos y bucles de herramientas de MyKOS.

Orquesta las peticiones a OpenRouter, NVIDIA NIM, Kimi, Grok, Gemini, Anthropic Claude,
Mistral y Meta AI, resolviendo sus llamadas a herramientas de forma segura y supervisada.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from anthropic_api import anthropic_chat_completion
from gemini import gemini_chat_completion
from grok import grok_auth_status, grok_chat_completion
from kimi import kimi_chat_completion
from meta_ai import meta_ai_chat_completion
from mistral import mistral_chat_completion
from nvidia import nvidia_chat_completion
from oauth import openrouter_api_json
from tools.schemas import TOOL_SCHEMAS, SENSITIVE_TOOL_NAMES
from worker_helpers import ApiError
from .activity import update_activity
from .integrity import inline_verified_ledger, integrity_check_answer, INTEGRITY_UNVERIFIED_NOTE

MAX_TOOL_ROUNDS = 12
MAX_REQUEST_TIMEOUT_SECONDS = 180
OPENROUTER_REQUEST_TIMEOUT_SECONDS = 90

GEMINI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["answer", "tool_call"]},
        "content": {"type": "string"},
        "tool_name": {"type": "string"},
        "arguments": {"type": "object"},
    },
    "required": ["kind", "content"],
}


def has_message_images(messages: list[dict[str, Any]]) -> bool:
    return any(isinstance(message.get("images"), list) and message.get("images") for message in messages)


def parse_gemini_response(result_text: str) -> dict[str, Any]:
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", result_text, flags=re.IGNORECASE).strip()
    if not cleaned:
        cleaned = result_text.strip()
    text = cleaned
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    data: Any = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            candidate = text[first_brace : last_brace + 1]
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                repaired = re.sub(r',\s*"\s*"\s*', ', "', candidate)
                repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
                try:
                    data = json.loads(repaired)
                except json.JSONDecodeError:
                    data = None
        if data is None:
            repaired = re.sub(r',\s*"\s*"\s*', ', "', text)
            repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
            try:
                data = json.loads(repaired)
            except Exception:
                data = None
        if data is None:
            return {"kind": "answer", "content": cleaned}

    if not isinstance(data, dict):
        return {"kind": "answer", "content": cleaned}

    kind = str(data.get("kind", "")).strip().casefold()
    content = str(data.get("content", ""))
    if kind not in {"answer", "tool_call"}:
        return {"kind": "answer", "content": content or cleaned}

    if kind == "answer":
        return {"kind": "answer", "content": content.strip() or cleaned}

    tool_name = str(data.get("tool_name", "")).strip()
    raw_arguments = data.get("arguments", {})
    if isinstance(raw_arguments, str):
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            repaired_args = re.sub(r',\s*"\s*"\s*', ', "', raw_arguments)
            repaired_args = re.sub(r',\s*([}\]])', r'\1', repaired_args)
            try:
                arguments = json.loads(repaired_args)
            except Exception:
                arguments = {}
    elif isinstance(raw_arguments, dict):
        arguments = raw_arguments
    else:
        arguments = {}

    allowed_tools = {
        str((schema.get("function") or {}).get("name", ""))
        for schema in TOOL_SCHEMAS
        if isinstance(schema, dict) and isinstance(schema.get("function"), dict)
    }
    if not tool_name or tool_name not in allowed_tools:
        return {"kind": "answer", "content": content.strip() or f"Herramienta no reconocida: {tool_name}"}

    return {
        "kind": "tool_call",
        "content": content.strip(),
        "tool_name": tool_name,
        "arguments": arguments,
    }


def extract_generated_media_markdowns(messages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Extract (url, markdown) pairs for generated media executed in the current user turn."""
    last_user_idx = -1
    for idx, item in enumerate(messages):
        if isinstance(item, dict) and str(item.get("role", "")).strip().casefold() == "user" and not item.get("integrity_guard"):
            last_user_idx = idx
    found: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for item in messages[last_user_idx + 1 :]:
        if not isinstance(item, dict) or str(item.get("role", "")).strip().casefold() != "tool":
            continue
        raw = item.get("content")
        data: Any = raw
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except Exception:
                continue
        if not isinstance(data, dict) or not data.get("ok"):
            continue
        url = str(data.get("url") or "").strip()
        md = str(data.get("markdown") or "").strip()
        if url.startswith("/static/media/gen-") and md and url not in seen_urls:
            seen_urls.add(url)
            found.append((url, md))
    return found


def ensure_generated_media_markdown(content: str, messages: list[dict[str, Any]]) -> str:
    """Guarantee that generated image/video Markdown links from this turn appear in the assistant reply."""
    text = str(content or "").strip()
    media_items = extract_generated_media_markdowns(messages)
    if not media_items:
        return text
    missing = [md for url, md in media_items if url not in text]
    if not missing:
        return text
    suffix = "\n\n".join(missing)
    return f"{text}\n\n{suffix}" if text else suffix


def execute_openai_json_tool_loop(
    *,
    model: str,
    provider: str,
    provider_label: str,
    activity_detail: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    completion_fn: Any,
    system_prompt_fn: Callable[[dict[str, Any]], str],
    source_cards_fn: Callable[..., list[dict[str, str]]],
    merge_source_cards_fn: Callable[[list[dict[str, str]], dict[str, Any]], None],
    tool_message_fn: Callable[[dict[str, Any], bool], dict[str, Any]],
    openai_compatible_messages_fn: Callable[..., list[dict[str, Any]]],
    controller_execute_tool_fn: Callable[[str, dict[str, Any]], dict[str, Any]],
    save_assistant_message_fn: Callable[[str, dict[str, Any]], None],
    handle_sensitive_tool_fn: Callable[..., dict[str, Any] | None],
    utc_now_fn: Callable[[], str],
    raw_completion_fn: Any = None,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
    permission_mode: str = "supervisado",
) -> dict[str, Any]:
    sys_prompt = system_prompt_fn({"name": model, "provider": provider, "remote": True})
    working_messages = [dict(item) for item in messages if str(item.get("role", "")).strip().casefold() != "system"]
    source_cards = source_cards_fn(working_messages, current_turn_only=True)
    tool_names: list[str] = []
    working_messages = inline_verified_ledger(working_messages)
    integrity_retries = 0
    generation = generation if isinstance(generation, dict) else {}
    request_deadline = time.monotonic() + MAX_REQUEST_TIMEOUT_SECONDS

    for tool_round in range(MAX_TOOL_ROUNDS + 1):
        if time.monotonic() > request_deadline:
            raise ApiError(408, f"Se superó el tiempo límite de la petición ({MAX_REQUEST_TIMEOUT_SECONDS}s). Abortando.")
        update_activity(
            activity_id,
            status="working",
            phase="model",
            label="Trabajando…",
            detail=activity_detail,
        )
        if raw_completion_fn is not None:
            content_raw = raw_completion_fn(working_messages, sys_prompt)
        else:
            req_messages = openai_compatible_messages_fn(
                working_messages,
                system_prompt=sys_prompt,
                supports_vision=supports_vision,
            )
            content_raw = completion_fn(req_messages)
        parsed = parse_gemini_response(content_raw)
        kind = parsed.get("kind")
        if kind == "answer":
            content = str(parsed.get("content", "")).strip()
            integrity_action, integrity_trace = integrity_check_answer(working_messages, content, integrity_retries)
            if integrity_action == "retry":
                integrity_retries += 1
                continue
            if integrity_action == "warn":
                content += INTEGRITY_UNVERIFIED_NOTE
            content = ensure_generated_media_markdown(content, working_messages)
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "model": model,
                "content": content,
                "created_at": utc_now_fn(),
            }
            if integrity_trace:
                assistant_message["verified_tool_trace"] = integrity_trace
            if source_cards:
                assistant_message["sources"] = source_cards
            save_assistant_message_fn(conversation_id, assistant_message)
            return {
                "message": assistant_message,
                "tools_used": sorted(set(tool_names)),
                "sources": source_cards,
                "done": True,
            }

        if tool_round >= MAX_TOOL_ROUNDS:
            raise RuntimeError(f"{provider_label} solicitó demasiadas rondas de herramientas.")

        tool_name = str(parsed.get("tool_name", "")).strip()
        tool_arguments = parsed.get("arguments", {})
        tool_names.append(tool_name)
        working_messages.append({
            "role": "assistant",
            "model": model,
            "content": json.dumps(parsed, ensure_ascii=False, separators=(",", ":")),
        })

        if tool_name in SENSITIVE_TOOL_NAMES:
            pending_response = handle_sensitive_tool_fn(
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                provider_label=provider_label,
                conversation_id=conversation_id,
                model=model,
                working_messages=working_messages,
                source_cards=source_cards,
                tool_names=tool_names,
                supports_vision=supports_vision,
                generation=generation,
                permission_mode=permission_mode,
                activity_id=activity_id,
                proposal=str(parsed.get("content", "")),
            )
            if pending_response is not None:
                return pending_response
            continue

        update_activity(
            activity_id,
            status="working",
            phase="tool",
            label="Consultando una herramienta…",
            detail=f"{provider_label} ha solicitado «{tool_name}»; MyKOS la está consultando.",
        )
        tool_result = controller_execute_tool_fn(tool_name, tool_arguments)
        merge_source_cards_fn(source_cards, tool_result)
        working_messages.append(tool_message_fn(tool_result, supports_vision))

    raise RuntimeError(f"{provider_label} no terminó dentro del límite de rondas.")
