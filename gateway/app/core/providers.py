"""Catálogo y autenticación de proveedores de modelos remotos para MyKOS.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from anthropic_api import anthropic_auth_status, anthropic_model_catalog, clear_anthropic_api_key
from antigravity_cli import antigravity_auth_status, antigravity_model_catalog, disable_antigravity
from qwen_cli import disable_qwen, qwen_auth_status, qwen_model_catalog
from gemini import clear_gemini_api_key, gemini_auth_status, gemini_models
from grok import clear_grok_credentials, grok_auth_status, grok_models, start_grok_oauth
from kimi import clear_kimi_api_key, kimi_auth_status, kimi_models
from meta_ai import (
    logout_meta_ai_oauth,
    meta_ai_auth_status,
    meta_ai_models,
    start_meta_ai_oauth,
)
from mistral import clear_mistral_api_key, clear_mistral_auth_cache, is_mistral_chat_model, mistral_auth_status, mistral_models
from nvidia import clear_nvidia_api_key, is_nvidia_chat_model, nvidia_auth_status, nvidia_models
from oauth import logout_openrouter_oauth, openrouter_auth_status, openrouter_models, start_openrouter_oauth

import os
PUBLIC_PORT = int(os.environ.get("MYKOS_PUBLIC_PORT", "0") or 0) or int(os.environ.get("MYKOS_PORT", "3210") or 3210)

OPENROUTER_LOCK = threading.RLock()
OPENROUTER_MODEL_CACHE: dict[str, Any] = {'checked_at': 0.0, 'models': [], 'authenticated': False, 'error': ''}
OPENROUTER_MODEL_CACHE_SECONDS = 60

NVIDIA_LOCK = threading.RLock()
NVIDIA_MODEL_CACHE: dict[str, Any] = {'checked_at': 0.0, 'models': [], 'authenticated': False, 'error': ''}
NVIDIA_MODEL_CACHE_SECONDS = 60

KIMI_LOCK = threading.RLock()
KIMI_MODEL_CACHE: dict[str, Any] = {'checked_at': 0.0, 'models': [], 'authenticated': False, 'error': ''}
KIMI_MODEL_CACHE_SECONDS = 60

GEMINI_LOCK = threading.RLock()
GEMINI_MODEL_CACHE: dict[str, Any] = {'checked_at': 0.0, 'models': [], 'authenticated': False, 'error': ''}
GEMINI_MODEL_CACHE_SECONDS = 60

MISTRAL_LOCK = threading.RLock()
MISTRAL_MODEL_CACHE: dict[str, Any] = {'checked_at': 0.0, 'models': [], 'authenticated': False, 'error': ''}
MISTRAL_MODEL_CACHE_SECONDS = 300.0

META_AI_LOCK = threading.RLock()
META_AI_MODEL_CACHE: dict[str, Any] = {'checked_at': 0.0, 'models': [], 'authenticated': False, 'error': ''}
META_AI_MODEL_CACHE_SECONDS = 60.0

GROK_LOCK = threading.RLock()
GROK_MODEL_CACHE: dict[str, Any] = {'checked_at': 0.0, 'models': [], 'authenticated': False, 'error': ''}
GROK_MODEL_CACHE_SECONDS = 60.0

ANTHROPIC_LOCK = threading.RLock()
ANTHROPIC_MODEL_CACHE: dict[str, Any] = {'checked_at': 0.0, 'models': [], 'authenticated': False, 'error': ''}
ANTHROPIC_MODEL_CACHE_SECONDS = 60

ANTIGRAVITY_LOCK = threading.RLock()

def _is_openrouter_chat_model(row: dict[str, Any]) -> bool:
    model_id = str(row.get("id", "")).strip()
    if not model_id:
        return False
    lowered = model_id.casefold()
    if any(marker in lowered for marker in ("embedding", "/embed", "whisper", "tts", "dall-e", "stable-diffusion")):
        return False
    arch = row.get("architecture") if isinstance(row.get("architecture"), dict) else {}
    output_mods = arch.get("output_modalities")
    if isinstance(output_mods, list) and output_mods:
        if "text" not in {str(item).casefold() for item in output_mods}:
            return False
    else:
        modality = str(arch.get("modality") or "").casefold()
        if "->" in modality:
            out_side = modality.split("->", 1)[1]
            if "text" not in out_side:
                return False
    return True


def openrouter_model_catalog(force: bool = False) -> tuple[list[dict[str, Any]], bool, str]:
    now = time.monotonic()
    with OPENROUTER_LOCK:
        cached_models = OPENROUTER_MODEL_CACHE.get("models") or []
        if (
            not force
            and cached_models
            and now - float(OPENROUTER_MODEL_CACHE.get("checked_at", 0.0)) < OPENROUTER_MODEL_CACHE_SECONDS
        ):
            return list(cached_models), bool(OPENROUTER_MODEL_CACHE.get("authenticated")), str(OPENROUTER_MODEL_CACHE.get("error", ""))

        try:
            auth = openrouter_auth_status()
            authenticated = bool(auth.get("authenticated"))
            if not authenticated:
                error_text = str(auth.get("error", ""))
                OPENROUTER_MODEL_CACHE.update({"checked_at": now, "models": [], "authenticated": False, "error": error_text})
                return [], False, error_text
            auth_method_raw = str(auth.get("auth_method") or "")
            is_api = "api" in auth_method_raw.casefold()
            provider_label = "OpenRouter · API" if is_api else "OpenRouter · OAuth"
            auth_method = "OpenRouter API Key" if is_api else "OpenRouter OAuth (PKCE)"
            remote_host = (
                "OpenRouter mediante tu clave API personal"
                if is_api
                else "OpenRouter mediante OAuth propio de MyKOS"
            )
            rows = openrouter_models()
            models: list[dict[str, Any]] = []
            for row in rows:
                if not _is_openrouter_chat_model(row):
                    continue
                model_id = str(row.get("id", "")).strip()
                reference = model_id if model_id.startswith("openrouter/") else f"openrouter/{model_id}"
                architecture = row.get("architecture") if isinstance(row.get("architecture"), dict) else {}
                modalities = architecture.get("input_modalities") if isinstance(architecture.get("input_modalities"), list) else []
                vision = "image" in {str(item).casefold() for item in modalities}
                models.append(
                    {
                        "name": reference,
                        "label": str(row.get("name") or model_id),
                        "provider": "openrouter",
                        "provider_label": provider_label,
                        "size": 0,
                        "parameter_size": "",
                        "family": "OpenRouter",
                        "quantization": "",
                        "modified_at": "",
                        "capabilities": ["chat", "completion", "tools"] + (["vision"] if vision else []),
                        "chat_capable": True,
                        "vision_capable": vision,
                        "thinking_capable": False,
                        "tools_capable": True,
                        "context_length": int(row.get("context_length", 0) or 0),
                        "remote": True,
                        "remote_host": remote_host,
                        "benchmark_capable": False,
                        "auth_method": auth_method,
                        "auth_status": "autenticado",
                        "auth_error": "",
                    }
                )
            OPENROUTER_MODEL_CACHE.update(
                {"checked_at": now, "models": models, "authenticated": True, "error": ""}
            )
            return models, True, ""
        except (RuntimeError, ValueError, TypeError) as error:
            cached_models = list(OPENROUTER_MODEL_CACHE.get("models") or [])
            error_text = str(error)
            OPENROUTER_MODEL_CACHE.update({"checked_at": now, "error": error_text})
            return cached_models, bool(OPENROUTER_MODEL_CACHE.get("authenticated")), error_text


def nvidia_model_catalog(force: bool = False) -> tuple[list[dict[str, Any]], bool, str]:
    now = time.monotonic()
    with NVIDIA_LOCK:
        cached_models = NVIDIA_MODEL_CACHE.get("models") or []
        if (
            not force
            and cached_models
            and now - float(NVIDIA_MODEL_CACHE.get("checked_at", 0.0)) < NVIDIA_MODEL_CACHE_SECONDS
        ):
            return list(cached_models), bool(NVIDIA_MODEL_CACHE.get("authenticated")), str(NVIDIA_MODEL_CACHE.get("error", ""))

        try:
            auth = nvidia_auth_status()
            authenticated = bool(auth.get("authenticated"))
            if not authenticated:
                error_text = str(auth.get("error", ""))
                NVIDIA_MODEL_CACHE.update({"checked_at": now, "models": [], "authenticated": False, "error": error_text})
                return [], False, error_text
            rows = nvidia_models()
            models: list[dict[str, Any]] = []
            for row in rows:
                if not is_nvidia_chat_model(row):
                    continue
                model_id = str(row.get("id", "")).strip()
                # Keep the MyKOS provider namespace separate from NVIDIA's own
                # namespace. For example, API id nvidia/nemotron-... becomes
                # MyKOS name nvidia/nvidia/nemotron-..., so the request keeps
                # the full upstream id instead of stripping it accidentally.
                reference = f"nvidia/{model_id}"
                architecture = row.get("architecture") if isinstance(row.get("architecture"), dict) else {}
                modalities = architecture.get("input_modalities") if isinstance(architecture.get("input_modalities"), list) else []
                vision = "image" in {str(item).casefold() for item in modalities}
                models.append(
                    {
                        "name": reference,
                        "label": str(row.get("name") or model_id),
                        "provider": "nvidia_api",
                        "provider_label": "NVIDIA NIM · API",
                        "size": 0,
                        "parameter_size": "",
                        "family": "NVIDIA NIM",
                        "quantization": "",
                        "modified_at": "",
                        "capabilities": ["chat", "completion", "tools"] + (["vision"] if vision else []),
                        "chat_capable": True,
                        "vision_capable": vision,
                        "thinking_capable": False,
                        "tools_capable": True,
                        "context_length": int(row.get("context_length", row.get("contextWindow", 0)) or 0),
                        "remote": True,
                        "remote_host": "NVIDIA NIM mediante la credencial protegida de MyKOS",
                        "benchmark_capable": False,
                        "auth_method": "NVIDIA Personal API Key",
                        "auth_status": "autenticado",
                        "auth_error": "",
                    }
                )
            NVIDIA_MODEL_CACHE.update({"checked_at": now, "models": models, "authenticated": True, "error": ""})
            return models, True, ""
        except (RuntimeError, ValueError, TypeError) as error:
            cached_models = list(NVIDIA_MODEL_CACHE.get("models") or [])
            error_text = str(error)
            NVIDIA_MODEL_CACHE.update({"checked_at": now, "error": error_text})
            return cached_models, bool(NVIDIA_MODEL_CACHE.get("authenticated")), error_text
def refresh_nvidia_models() -> dict[str, Any]:
    models, authenticated, error = nvidia_model_catalog(force=True)
    if error and not models:
        raise RuntimeError(error)
    return {"ok": True, "provider": "nvidia_api", "authenticated": authenticated, "models": len(models), "error": error}


def _logout_nvidia() -> dict[str, Any]:
    clear_nvidia_api_key()
    with NVIDIA_LOCK:
        NVIDIA_MODEL_CACHE.clear()
        NVIDIA_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
    return {"ok": True, "provider": "nvidia_api", "status": "logged_out"}

def kimi_model_catalog(force: bool = False) -> tuple[list[dict[str, Any]], bool, str]:
    now = time.monotonic()
    with KIMI_LOCK:
        cached = KIMI_MODEL_CACHE.get("models") or []
        if not force and cached and now - float(KIMI_MODEL_CACHE.get("checked_at", 0)) < KIMI_MODEL_CACHE_SECONDS:
            return list(cached), bool(KIMI_MODEL_CACHE.get("authenticated")), str(KIMI_MODEL_CACHE.get("error", ""))
        try:
            auth = kimi_auth_status()
            if not auth.get("authenticated"):
                error = str(auth.get("error", "")); KIMI_MODEL_CACHE.update(checked_at=now, models=[], authenticated=False, error=error); return [], False, error
            models = [{"name": f"kimi/{str(row.get('id')).strip()}", "label": str(row.get("id")).strip(), "provider": "kimi_api", "provider_label": "Kimi · API", "size": 0, "parameter_size": "", "family": "Kimi", "quantization": "", "modified_at": "", "capabilities": ["chat", "completion", "tools"], "chat_capable": True, "vision_capable": False, "thinking_capable": False, "tools_capable": True, "context_length": 0, "remote": True, "remote_host": "Kimi API mediante la credencial protegida de MyKOS", "benchmark_capable": False, "auth_method": "Kimi API Key", "auth_status": "autenticado", "auth_error": ""} for row in kimi_models()]
            KIMI_MODEL_CACHE.update(checked_at=now, models=models, authenticated=True, error=""); return models, True, ""
        except RuntimeError as exc:
            KIMI_MODEL_CACHE.update(checked_at=now, error=str(exc)); return list(cached), bool(KIMI_MODEL_CACHE.get("authenticated")), str(exc)

def refresh_kimi_models() -> dict[str, Any]:
    models, authenticated, error = kimi_model_catalog(True)
    if error and not models: raise RuntimeError(error)
    return {"ok": True, "provider": "kimi_api", "authenticated": authenticated, "models": len(models), "error": error}


def _logout_kimi() -> dict[str, Any]:
    clear_kimi_api_key()
    with KIMI_LOCK:
        KIMI_MODEL_CACHE.clear()
        KIMI_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
    return {"ok": True, "provider": "kimi_api", "status": "logged_out"}


def gemini_model_catalog(force: bool = False) -> tuple[list[dict[str, Any]], bool, str]:
    now = time.monotonic()
    with GEMINI_LOCK:
        cached = GEMINI_MODEL_CACHE.get("models") or []
        if not force and cached and now - float(GEMINI_MODEL_CACHE.get("checked_at", 0)) < GEMINI_MODEL_CACHE_SECONDS:
            return list(cached), bool(GEMINI_MODEL_CACHE.get("authenticated")), str(GEMINI_MODEL_CACHE.get("error", ""))
        try:
            auth = gemini_auth_status()
            if not auth.get("authenticated"):
                error = str(auth.get("error", ""))
                GEMINI_MODEL_CACHE.update(checked_at=now, models=[], authenticated=False, error=error)
                return [], False, error
            raw_rows = gemini_models()
            models = []
            for row in raw_rows:
                model_id = str(row.get("id")).strip()
                lower_id = model_id.lower()
                thinking_capable = (
                    "thinking" in lower_id
                    or "gemini-2.5" in lower_id
                    or "gemini-3" in lower_id
                    or "gemini-4" in lower_id
                )
                caps_list = ["chat", "completion", "vision", "tools"]
                if thinking_capable:
                    caps_list.append("thinking")
                models.append(
                    {
                        "name": f"gemini/{model_id}",
                        "label": str(row.get("name") or row.get("id")).strip(),
                        "provider": "gemini_api",
                        "provider_label": "Gemini · API",
                        "size": 0,
                        "parameter_size": "",
                        "family": "Gemini",
                        "quantization": "",
                        "modified_at": "",
                        "capabilities": caps_list,
                        "chat_capable": True,
                        "vision_capable": True,
                        "thinking_capable": thinking_capable,
                        "tools_capable": True,
                        "context_length": int(row.get("context_length", 0)),
                        "remote": True,
                        "remote_host": "Google AI Studio mediante la credencial protegida de MyKOS",
                        "benchmark_capable": False,
                        "auth_method": "Google AI Studio API Key",
                        "auth_status": "autenticado",
                        "auth_error": "",
                    }
                )
            GEMINI_MODEL_CACHE.update(checked_at=now, models=models, authenticated=True, error="")
            return models, True, ""
        except (RuntimeError, ValueError, TypeError) as exc:
            GEMINI_MODEL_CACHE.update(checked_at=now, error=str(exc))
            return list(cached), bool(GEMINI_MODEL_CACHE.get("authenticated")), str(exc)


def refresh_gemini_models() -> dict[str, Any]:
    models, authenticated, error = gemini_model_catalog(True)
    if error and not models:
        raise RuntimeError(error)
    return {"ok": True, "provider": "gemini_api", "authenticated": authenticated, "models": len(models), "error": error}


def _logout_gemini() -> dict[str, Any]:
    clear_gemini_api_key()
    with GEMINI_LOCK:
        GEMINI_MODEL_CACHE.clear()
        GEMINI_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
    return {"ok": True, "provider": "gemini_api", "status": "logged_out"}


def mistral_model_catalog(force: bool = False) -> tuple[list[dict[str, Any]], bool, str]:
    now = time.monotonic()
    with MISTRAL_LOCK:
        cached = MISTRAL_MODEL_CACHE.get("models") or []
        if not force and cached and now - float(MISTRAL_MODEL_CACHE.get("checked_at", 0)) < MISTRAL_MODEL_CACHE_SECONDS:
            return list(cached), bool(MISTRAL_MODEL_CACHE.get("authenticated")), str(MISTRAL_MODEL_CACHE.get("error", ""))
        try:
            auth = mistral_auth_status()
            if not auth.get("authenticated"):
                error = str(auth.get("error", ""))
                MISTRAL_MODEL_CACHE.update(checked_at=now, models=[], authenticated=False, error=error)
                return [], False, error
            raw_rows = mistral_models()
            models = []
            for row in raw_rows:
                if not is_mistral_chat_model(row):
                    continue
                model_id = str(row.get("id", "")).strip()
                caps = row.get("capabilities") or {}
                has_vision = bool(caps.get("vision"))
                has_reasoning = bool(caps.get("reasoning"))
                has_tools = bool(caps.get("function_calling", True))
                caps_list = ["chat", "completion"]
                if has_vision:
                    caps_list.append("vision")
                if has_reasoning:
                    caps_list.append("thinking")
                if has_tools:
                    caps_list.append("tools")
                context_len = int(row.get("max_context_length") or 128000)
                models.append({
                    "name": f"mistral/{model_id}",
                    "label": f"{model_id} (Mistral · Vibe)",
                    "provider": "mistral_api",
                    "provider_label": "Mistral · Vibe",
                    "size": 0,
                    "parameter_size": "",
                    "family": "Mistral",
                    "quantization": "",
                    "modified_at": "",
                    "capabilities": caps_list,
                    "chat_capable": True,
                    "vision_capable": has_vision,
                    "thinking_capable": has_reasoning,
                    "tools_capable": has_tools,
                    "context_length": context_len,
                    "remote": True,
                    "remote_host": "Mistral AI / Vibe mediante sesión OAuth o clave protegida",
                    "benchmark_capable": False,
                    "auth_method": str(auth.get("auth_method", "Mistral Vibe")),
                    "auth_status": "autenticado",
                    "auth_error": "",
                })
            MISTRAL_MODEL_CACHE.update(checked_at=now, models=models, authenticated=True, error="")
            return models, True, ""
        except (RuntimeError, ValueError, TypeError) as exc:
            MISTRAL_MODEL_CACHE.update(checked_at=now, error=str(exc))
            return list(cached), bool(MISTRAL_MODEL_CACHE.get("authenticated")), str(exc)


def refresh_mistral_models() -> dict[str, Any]:
    clear_mistral_auth_cache()
    models, authenticated, error = mistral_model_catalog(True)
    if error and not models:
        raise RuntimeError(error)
    return {"ok": True, "provider": "mistral_api", "authenticated": authenticated, "models": len(models), "error": error}


def _logout_mistral() -> dict[str, Any]:
    clear_mistral_api_key()
    with MISTRAL_LOCK:
        MISTRAL_MODEL_CACHE.clear()
        MISTRAL_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
    return {"ok": True, "provider": "mistral_api", "status": "logged_out"}


def refresh_anthropic_models() -> dict[str, Any]:
    models, authenticated, error = anthropic_model_catalog(force=True)
    with ANTHROPIC_LOCK:
        ANTHROPIC_MODEL_CACHE.update(checked_at=time.monotonic(), models=models, authenticated=authenticated, error=error)
    return {"ok": True, "provider": "anthropic_api", "authenticated": authenticated, "models": len(models), "error": error}


def _logout_anthropic() -> dict[str, Any]:
    res = clear_anthropic_api_key()
    with ANTHROPIC_LOCK:
        ANTHROPIC_MODEL_CACHE.clear()
        ANTHROPIC_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
    return res


def refresh_antigravity_models() -> dict[str, Any]:
    models, authenticated, error = antigravity_model_catalog(force=True)
    return {"ok": True, "provider": "antigravity_cli", "authenticated": authenticated, "models": len(models), "error": error}


def _logout_antigravity() -> dict[str, Any]:
    return disable_antigravity()


def refresh_qwen_models() -> dict[str, Any]:
    models, authenticated, error = qwen_model_catalog(force=True)
    return {"ok": True, "provider": "qwen_cli", "authenticated": authenticated, "models": len(models), "error": error}


def _logout_qwen() -> dict[str, Any]:
    return disable_qwen()


def start_openrouter_login() -> dict[str, Any]:
    callback_url = f"http://127.0.0.1:{PUBLIC_PORT}/api/oauth/openrouter/callback"
    return start_openrouter_oauth(callback_url)


def refresh_openrouter_models() -> dict[str, Any]:
    models, authenticated, error = openrouter_model_catalog(force=True)
    if error and not models:
        raise RuntimeError(error)
    return {"ok": True, "provider": "openrouter", "authenticated": authenticated, "models": len(models), "error": error}


def meta_ai_model_catalog(force: bool = False) -> tuple[list[dict[str, Any]], bool, str]:
    now = time.monotonic()
    with META_AI_LOCK:
        cached = META_AI_MODEL_CACHE.get("models") or []
        if not force and cached and now - float(META_AI_MODEL_CACHE.get("checked_at", 0.0)) < META_AI_MODEL_CACHE_SECONDS:
            return list(cached), bool(META_AI_MODEL_CACHE.get("authenticated")), str(META_AI_MODEL_CACHE.get("error", ""))
        auth = meta_ai_auth_status()
        has_oauth = bool(auth.get("has_oauth"))
        has_api_key = bool(auth.get("has_api_key")) or "API Key" in str(auth.get("auth_method", ""))
        if not auth.get("has_oauth") and not auth.get("has_api_key") and auth.get("authenticated"):
            has_oauth = "OAuth" in str(auth.get("auth_method", "")) or not has_api_key
        rows = meta_ai_models(force=force)
        models = []
        for row in rows:
            model_name = str(row.get("name", "")).strip()
            if model_name in {"meta-ai/muse-image", "meta-ai/sam-3.1", "meta-ai/muse-voice-transcribe"}:
                continue
            provider = str(row.get("provider", "meta_ai_oauth")).strip()
            is_api = provider == "meta_ai_api"
            is_authed = has_api_key if is_api else has_oauth
            family = "Muse (Meta AI)" if is_api else "Llama 4 (Meta AI)"
            remote_host = (
                "Meta Model API (compatible OpenAI SDK)"
                if is_api
                else "Meta AI (gateway.meta.ai DGW) mediante sesión OAuth de MyKOS"
            )
            auth_method = "Meta Model API Key" if is_api else "Meta AI OAuth (ecto1 / OIDC)"
            auth_status = "autenticado" if is_authed else ("requiere clave API" if is_api else "no autenticado")
            caps = ["chat", "completion", "tools"]
            if row.get("enable_thinking"):
                caps.append("thinking")
            models.append({
                "name": model_name,
                "label": str(row.get("label") or model_name).strip(),
                "provider": provider,
                "provider_label": "Meta AI · API" if is_api else "Meta AI · OAuth",
                "size": 0,
                "parameter_size": "",
                "family": family,
                "quantization": "",
                "modified_at": "",
                "capabilities": caps,
                "chat_capable": bool(is_authed),
                "vision_capable": False,
                "thinking_capable": bool(row.get("enable_thinking")),
                "tools_capable": True,
                "context_length": int(row.get("context_length", 128000)),
                "remote": True,
                "remote_host": remote_host,
                "benchmark_capable": False,
                "auth_method": auth_method,
                "auth_status": auth_status,
                "auth_error": "",
                "free": bool(row.get("free", False)),
                "recommended": bool(row.get("recommended", False)),
                "description": str(row.get("description", "")).strip() or "",
            })
        any_authed = bool(has_oauth or has_api_key)
        META_AI_MODEL_CACHE.update(checked_at=now, models=models, authenticated=any_authed, error="")
        return models, any_authed, ""


def start_meta_ai_login() -> dict[str, Any]:
    return start_meta_ai_oauth(open_browser=True)


def refresh_meta_ai_models() -> dict[str, Any]:
    models, authenticated, error = meta_ai_model_catalog(force=True)
    return {"ok": True, "provider": "meta_ai_oauth", "authenticated": authenticated, "models": len(models), "error": error}


def logout_meta_ai() -> dict[str, Any]:
    result = logout_meta_ai_oauth()
    with META_AI_LOCK:
        META_AI_MODEL_CACHE.clear()
        META_AI_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
    return result


def grok_model_catalog(force: bool = False) -> tuple[list[dict[str, Any]], bool, str]:
    now = time.monotonic()
    with GROK_LOCK:
        cached = GROK_MODEL_CACHE.get("models") or []
        if not force and cached and now - float(GROK_MODEL_CACHE.get("checked_at", 0)) < GROK_MODEL_CACHE_SECONDS:
            return list(cached), bool(GROK_MODEL_CACHE.get("authenticated")), str(GROK_MODEL_CACHE.get("error", ""))
        try:
            auth = grok_auth_status()
            if not auth.get("authenticated"):
                error = str(auth.get("error", ""))
                GROK_MODEL_CACHE.update(checked_at=now, models=[], authenticated=False, error=error)
                return [], False, error
            rows = grok_models()
            is_oauth = auth.get("mode") == "oauth"
            models = [
                {
                    "name": str(row.get("name", f"grok/{row.get('id', '')}")).strip(),
                    "label": str(row.get("label", row.get("id", ""))).strip(),
                    "provider": "grok_oauth" if is_oauth else "grok_api",
                    "provider_label": "Grok · xAI (OAuth)" if is_oauth else "Grok · xAI (API)",
                    "size": 0,
                    "parameter_size": "",
                    "family": "Grok",
                    "quantization": "",
                    "modified_at": "",
                    "capabilities": ["chat", "completion", "tools"] + (["vision"] if row.get("vision") else []),
                    "chat_capable": True,
                    "vision_capable": bool(row.get("vision")),
                    "thinking_capable": False,
                    "tools_capable": True,
                    "context_length": int(row.get("context_length", 131072)),
                    "remote": True,
                    "remote_host": "xAI API mediante la credencial protegida de MyKOS",
                    "benchmark_capable": False,
                    "auth_method": str(auth.get("auth_method", "Grok")),
                    "auth_status": "autenticado",
                    "auth_error": "",
                }
                for row in rows
            ]
            GROK_MODEL_CACHE.update(checked_at=now, models=models, authenticated=True, error="")
            return models, True, ""
        except RuntimeError as exc:
            err = str(exc)
            if "401" in err or "403" in err:
                GROK_MODEL_CACHE.update(checked_at=now, models=[], authenticated=False, error=err)
                return [], False, err
            GROK_MODEL_CACHE.update(checked_at=now, error=err)
            return list(cached), bool(GROK_MODEL_CACHE.get("authenticated")), err


def start_grok_login() -> dict[str, Any]:
    return start_grok_oauth(open_browser=True)


def refresh_grok_models() -> dict[str, Any]:
    models, authenticated, error = grok_model_catalog(force=True)
    return {"ok": True, "provider": "grok", "authenticated": authenticated, "models": len(models), "error": error}


def _logout_grok() -> dict[str, Any]:
    clear_grok_credentials()
    with GROK_LOCK:
        GROK_MODEL_CACHE.clear()
        GROK_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
    return {"ok": True, "provider": "grok", "status": "logged_out"}


def logout_openrouter() -> dict[str, Any]:
    result = logout_openrouter_oauth()
    with OPENROUTER_LOCK:
        OPENROUTER_MODEL_CACHE.clear()
        OPENROUTER_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
    return result



