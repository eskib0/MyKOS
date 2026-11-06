"""Proveedor directo Gemini API (Google AI Studio); la clave se cifra con DPAPI mediante MyKOS."""
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
    HOME = Path(_CREDS_BASE).expanduser() / "gemini"
elif _GATEWAY_CREDS.exists():
    HOME = _GATEWAY_CREDS / "gemini"
else:
    HOME = ROOT / "data" / "oauth" / "gemini"
HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
try:
    os.chmod(HOME, 0o700)
except OSError:
    pass
FILE = HOME / "credentials.json"
BASE = os.environ.get("MYKOS_GEMINI_API_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")


def _key() -> str:
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    stored = _decode_key(data) if isinstance(data, dict) else ""
    if stored:
        return stored
    env_key = os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()
    return env_key


def save_gemini_api_key(key: str) -> None:
    key = str(key).strip()
    if not key:
        raise RuntimeError("Introduce una clave personal de Google AI Studio (Gemini).")
    temp = FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(_encode_key(key), ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(FILE)


def clear_gemini_api_key() -> None:
    FILE.unlink(missing_ok=True)


def gemini_auth_status() -> dict[str, Any]:
    ok = bool(_key())
    return {
        "authenticated": ok,
        "auth_method": "Google AI Studio API Key" if ok else "",
        "error": "" if ok else "MyKOS todavía no tiene una clave de Google AI Studio (Gemini).",
    }


def _request(
    path: str,
    *,
    key: str = "",
    payload: dict[str, Any] | None = None,
    method: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    token = key or _key()
    if not token:
        raise RuntimeError("MyKOS todavía no tiene una clave de Google AI Studio (Gemini).")
    http_method = method or ("POST" if payload is not None else "GET")
    data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
    url = f"{BASE}/{path.lstrip('/')}"
    req = urllib.request.Request(
        url,
        data=data_bytes,
        method=http_method,
        headers={
            "x-goog-api-key": token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    max_retries = 3
    result = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 503 and attempt < max_retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            err_msg = exc.read().decode("utf-8", errors="replace")[:500]
            try:
                err_json = json.loads(err_msg)
                if isinstance(err_json, dict) and "error" in err_json:
                    detail = err_json["error"].get("message") or err_msg
                else:
                    detail = err_msg
            except Exception:
                detail = err_msg
            raise RuntimeError(f"Gemini rechazó la solicitud (HTTP {exc.code}): {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt < max_retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RuntimeError(f"No se pudo consultar Gemini API: {exc}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Gemini devolvió un formato inesperado.")
    return result


def gemini_models(key: str = "") -> list[dict[str, Any]]:
    result = _request("models", key=key)
    raw_models = result.get("models", [])
    if not isinstance(raw_models, list):
        raise RuntimeError("Gemini devolvió un catálogo de modelos no válido.")
    
    rows: list[dict[str, Any]] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name", "")).strip()
        clean_id = raw_name.removeprefix("models/").strip()
        if not clean_id:
            continue
        methods = item.get("supportedGenerationMethods", [])
        # ``generateContent`` también se anuncia en modelos especializados
        # (TTS, transcripción, imagen y música). El adaptador de MyKOS sólo
        # implementa conversación de texto/visión y devuelve exclusivamente
        # partes de texto, así que no debemos ofrecer esos modelos como chat.
        specialized_markers = ("live", "-tts", "transcribe", "image", "lyria")
        if any(marker in clean_id.lower() for marker in specialized_markers):
            continue
        if isinstance(methods, list) and "generateContent" in methods:
            rows.append({
                "id": clean_id,
                "name": str(item.get("displayName") or clean_id),
                "description": str(item.get("description", "")),
                "context_length": int(item.get("inputTokenLimit") or 0),
                "output_token_limit": int(item.get("outputTokenLimit") or 0),
            })
    if not rows:
        raise RuntimeError("Google AI Studio aceptó la conexión, pero no devolvió modelos compatibles con texto.")
    
    # Ordenar priorizando modelos más modernos (3.8, 3.5, 3.x, 2.5)
    def _rank(m: dict[str, Any]) -> tuple[int, int, str]:
        mid = m["id"].lower()
        if "3.8" in mid:
            priority = 0
        elif "3.5" in mid:
            priority = 1
        elif "3." in mid:
            priority = 2
        elif "2.5" in mid:
            priority = 3
        else:
            priority = 4
        # Dentro de la misma versión, flash antes que pro para rapidez en chat
        sub = 0 if "flash" in mid else (1 if "pro" in mid else 2)
        return (priority, sub, m["id"])

    rows.sort(key=_rank)
    return rows


def gemini_chat_completion(
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 2048,
    temperature: float = 0.2,
    system_prompt: str = "",
    response_schema: dict[str, Any] | None = None,
) -> str:
    clean_model = model.removeprefix("gemini/").removeprefix("models/").strip()
    if "live" in clean_model.lower():
        clean_model = "gemini-3.8-flash"
    if not clean_model:
        raise RuntimeError(f"Nombre de modelo Gemini no válido: {model}")

    # Separar instrucciones de sistema de las del usuario/asistente
    system_parts: list[dict[str, str]] = []
    if system_prompt.strip():
        system_parts.append({"text": system_prompt.strip()})

    contents: list[dict[str, Any]] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip().lower()
        raw_content = msg.get("content", "")

        # Si viene contenido en formato lista o texto
        text = ""
        parts: list[dict[str, Any]] = []
        if isinstance(raw_content, str):
            text = raw_content.strip()
            if text:
                parts.append({"text": text})
        elif isinstance(raw_content, list):
            for part in raw_content:
                if isinstance(part, str):
                    if part.strip():
                        parts.append({"text": part.strip()})
                elif isinstance(part, dict):
                    if part.get("type") == "text" and part.get("text"):
                        parts.append({"text": str(part["text"]).strip()})
                    elif part.get("type") == "image_url":
                        image_url = part.get("image_url", {})
                        url_str = str(image_url.get("url", "") if isinstance(image_url, dict) else image_url)
                        if url_str.startswith("data:") and ";base64," in url_str:
                            header, b64_data = url_str.split(";base64,", 1)
                            mime_type = header.replace("data:", "").strip()
                            parts.append({"inlineData": {"mimeType": mime_type, "data": b64_data}})

        if not parts:
            continue

        if role == "system":
            system_parts.extend(parts)
            continue

        gemini_role = "user" if role in {"user", "human", "tool"} else "model"

        # Gemini requiere alternar roles user y model. Si dos consecutivos son iguales, fusionamos parts.
        if contents and contents[-1]["role"] == gemini_role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": gemini_role, "parts": parts})

    if not contents:
        raise RuntimeError("No hay mensajes válidos para enviar a Gemini.")

    gen_config: dict[str, Any] = {
        "temperature": max(0.0, min(2.0, float(temperature))),
        "maxOutputTokens": max(1, min(65536, int(max_tokens))),
    }
    if response_schema and isinstance(response_schema, dict):
        gen_config["responseMimeType"] = "application/json"
        gen_config["responseSchema"] = response_schema

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": gen_config,
    }
    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}

    endpoint = f"models/{clean_model}:generateContent"
    data = _request(endpoint, payload=payload, timeout=180)

    candidates = data.get("candidates") if isinstance(data.get("candidates"), list) else []
    if not candidates or not isinstance(candidates[0], dict):
        feedback = data.get("promptFeedback", {})
        block_reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
        if block_reason:
            raise RuntimeError(f"Gemini bloqueó la solicitud por política de seguridad ({block_reason}).")
        raise RuntimeError(str(data.get("error") or "Gemini no devolvió ninguna respuesta."))

    candidate = candidates[0]
    candidate_content = candidate.get("content", {})
    candidate_parts = candidate_content.get("parts", []) if isinstance(candidate_content, dict) else []

    text_parts = [
        str(part.get("text", ""))
        for part in candidate_parts
        if isinstance(part, dict) and "text" in part
    ]
    result_text = "".join(text_parts).strip()

    if not result_text:
        finish_reason = candidate.get("finishReason", "UNKNOWN")
        if finish_reason != "STOP":
            raise RuntimeError(f"Gemini finalizó sin texto (motivo: {finish_reason}).")
        raise RuntimeError("Gemini devolvió una respuesta vacía.")

    return result_text
