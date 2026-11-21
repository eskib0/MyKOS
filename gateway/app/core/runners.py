"""Sub-módulo de ejecución de modelos remotos y bucles de herramientas de MyKOS.

Orquesta las peticiones a OpenRouter, NVIDIA NIM, Kimi, Grok, Gemini, Anthropic Claude,
Mistral y Meta AI, resolviendo sus llamadas a herramientas de forma segura y supervisada.
"""

from __future__ import annotations

import json
import os
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

MAX_TOOL_ROUNDS = 24
MAX_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("MYKOS_REQUEST_TIMEOUT_SECONDS", "300") or 300)
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

    def _try_load(s: str) -> Any:
        try:
            return json.loads(s, strict=False)
        except Exception:
            return None

    data: Any = _try_load(text)
    if data is None:
        fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()
            data = _try_load(text)

    if data is None:
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            candidate = text[first_brace : last_brace + 1]
            data = _try_load(candidate)
            if data is None:
                repaired = re.sub(r',\s*"\s*"\s*', ', "', candidate)
                repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
                data = _try_load(repaired)

    if data is None:
        repaired = re.sub(r',\s*"\s*"\s*', ', "', text)
        repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
        data = _try_load(repaired)

    if data is None:
        m_ans = re.search(r'"kind"\s*:\s*"answer"\s*,\s*"content"\s*:\s*"([\s\S]*?)"\s*,\s*"tool_name"', cleaned)
        if not m_ans:
            m_ans = re.search(r'"content"\s*:\s*"([\s\S]*?)"\s*,\s*"kind"\s*:\s*"answer"', cleaned)
        if m_ans:
            raw_c = m_ans.group(1)
            try:
                c_clean = json.loads(f'"{raw_c}"', strict=False)
            except Exception:
                c_clean = raw_c.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
            return {"kind": "answer", "content": c_clean.strip()}
        return {"kind": "answer", "content": cleaned}

    if not isinstance(data, dict):
        return {"kind": "answer", "content": cleaned}

    kind = str(data.get("kind", "")).strip().casefold()
    content = str(data.get("content", ""))
    if kind not in {"answer", "tool_call"}:
        return {"kind": "answer", "content": content or cleaned}

    if kind == "answer":
        return {"kind": "answer", "content": content.strip() if content is not None else cleaned}

    tool_name = str(data.get("tool_name", "")).strip()
    raw_arguments = data.get("arguments", {})
    if isinstance(raw_arguments, str):
        try:
            arguments = json.loads(raw_arguments, strict=False)
        except json.JSONDecodeError:
            repaired_args = re.sub(r',\s*"\s*"\s*', ', "', raw_arguments)
            repaired_args = re.sub(r',\s*([}\]])', r'\1', repaired_args)
            try:
                arguments = json.loads(repaired_args, strict=False)
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


def _usage_int(usage: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        val = usage.get(key)
        if val is not None:
            try:
                parsed = int(float(val))
                if parsed > 0:
                    return parsed
            except (TypeError, ValueError):
                pass
    return 0


def build_turn_telemetry(
    content: str,
    duration_seconds: float,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construye métricas homogéneas de telemetría (duración, tokens, t/s) para cualquier motor."""
    usage_dict = usage if isinstance(usage, dict) else {}
    try:
        raw_dur = float(duration_seconds or 0.0)
    except (TypeError, ValueError):
        raw_dur = 0.0
    dur_sec = max(0.001, raw_dur) if raw_dur > 0 else 0.0
    duration_ms = max(1, int(round(dur_sec * 1000))) if dur_sec > 0 else 0

    tokens_out = _usage_int(
        usage_dict,
        ("completion_tokens", "output_tokens", "candidatesTokenCount", "eval_count"),
    )
    stripped = str(content or "").strip()
    if tokens_out <= 0 and stripped:
        tokens_out = max(1, round(len(stripped) / 4))

    tokens_in = _usage_int(
        usage_dict,
        ("prompt_tokens", "input_tokens", "promptTokenCount", "prompt_eval_count"),
    )
    tokens_per_second = (
        round(tokens_out / (duration_ms / 1000.0), 1)
        if duration_ms > 0 and tokens_out > 0
        else 0.0
    )
    return {
        "duration_ms": duration_ms,
        "tokens_out": int(tokens_out),
        "tokens_in": int(tokens_in),
        "tokens_per_second": tokens_per_second,
    }


def _extract_turn_tool_exchange(
    messages: list[dict[str, Any]],
    max_chars_per_tool: int = 12000,
    max_total_chars: int = 48000,
) -> list[dict[str, Any]]:
    """Extrae los pares tool_call/tool del turno actual para preservar contexto entre turnos."""
    start = 0
    for idx in range(len(messages) - 1, -1, -1):
        item = messages[idx]
        if isinstance(item, dict) and item.get("role") == "user" and not item.get("integrity_guard"):
            start = idx + 1
            break
    raw_items: list[dict[str, Any]] = []
    for item in messages[start:]:
        if not isinstance(item, dict) or item.get("integrity_guard"):
            continue
        role = str(item.get("role", "")).strip()
        if role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": str(item.get("content", ""))}
            if isinstance(item.get("tool_calls"), list) and item["tool_calls"]:
                entry["tool_calls"] = item["tool_calls"]
            raw_items.append(entry)
        elif role == "tool":
            content = str(item.get("content", ""))
            if len(content) > max_chars_per_tool:
                try:
                    decoded = json.loads(content)
                    if isinstance(decoded, dict):
                        for key in ("content", "stdout", "stderr", "text", "output"):
                            val = decoded.get(key)
                            if isinstance(val, str) and len(val) > max_chars_per_tool - 1000:
                                decoded[key] = (
                                    val[: max_chars_per_tool - 1000]
                                    + "\n[... contenido recortado en historial ...]"
                                )
                        content = json.dumps(decoded, ensure_ascii=False)
                except (TypeError, ValueError):
                    pass
                if len(content) > max_chars_per_tool:
                    content = content[:max_chars_per_tool]
            tool_entry: dict[str, Any] = {"role": "tool", "content": content}
            if item.get("tool_call_id"):
                tool_entry["tool_call_id"] = item["tool_call_id"]
            if item.get("tool_name"):
                tool_entry["tool_name"] = item["tool_name"]
            raw_items.append(tool_entry)

    kept: list[dict[str, Any]] = []
    total_chars = 0
    for item in reversed(raw_items):
        item_len = len(str(item.get("content", "")))
        if kept and total_chars + item_len > max_total_chars:
            break
        kept.append(item)
        total_chars += item_len
    kept.reverse()
    while len(kept) > 1 and kept[0].get("role") == "tool":
        kept.pop(0)
    return kept


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
    total_model_seconds = 0.0
    accumulated_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}

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
        call_started = time.monotonic()
        if raw_completion_fn is not None:
            raw_res = raw_completion_fn(working_messages, sys_prompt)
        else:
            req_messages = openai_compatible_messages_fn(
                working_messages,
                system_prompt=sys_prompt,
                supports_vision=supports_vision,
            )
            raw_res = completion_fn(req_messages)
        elapsed_call = max(0.001, time.monotonic() - call_started)
        if isinstance(raw_res, dict):
            content_raw = str(raw_res.get("content") or raw_res.get("response") or "")
            raw_dur = raw_res.get("duration_seconds")
            try:
                parsed_dur = float(raw_dur) if raw_dur is not None else 0.0
            except (TypeError, ValueError):
                parsed_dur = 0.0
            total_model_seconds += parsed_dur if parsed_dur > 0 else elapsed_call
            usage_part = raw_res.get("usage")
            if isinstance(usage_part, dict):
                accumulated_usage["prompt_tokens"] += _usage_int(
                    usage_part,
                    ("prompt_tokens", "input_tokens", "promptTokenCount", "prompt_eval_count"),
                )
                accumulated_usage["completion_tokens"] += _usage_int(
                    usage_part,
                    ("completion_tokens", "output_tokens", "candidatesTokenCount", "eval_count"),
                )
        else:
            content_raw = str(raw_res or "")
            total_model_seconds += elapsed_call
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
            telemetry = build_turn_telemetry(content, total_model_seconds, accumulated_usage)
            turn_exchange = _extract_turn_tool_exchange(working_messages)
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "model": model,
                "content": content,
                "created_at": utc_now_fn(),
                "telemetry": telemetry,
            }
            if turn_exchange:
                assistant_message["tool_exchange"] = turn_exchange
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
                "telemetry": telemetry,
                "duration_seconds": round(total_model_seconds, 3),
                "usage": {
                    "prompt_tokens": telemetry["tokens_in"],
                    "completion_tokens": telemetry["tokens_out"],
                    "total_tokens": telemetry["tokens_in"] + telemetry["tokens_out"],
                },
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
        if isinstance(tool_result, dict) and not tool_result.get("tool") and not tool_result.get("action"):
            tool_result = {**tool_result, "tool": tool_name}
        merge_source_cards_fn(source_cards, tool_result)
        working_messages.append(tool_message_fn(tool_result, supports_vision))

    raise RuntimeError(f"{provider_label} no terminó dentro del límite de rondas.")
