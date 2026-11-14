"""
Módulo de integración con Strata para MyKOS.
Conecta con el motor local Strata en http://127.0.0.1:18080 (API OpenAI /v1/chat/completions y /v1/models).
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("mykos.strata")

STRATA_URL = os.environ.get("MYKOS_STRATA_URL", "http://127.0.0.1:18080").rstrip("/")
STRATA_TIMEOUT_SECONDS = int(os.environ.get("MYKOS_STRATA_TIMEOUT", "600"))

# Metadatos de los modelos oficiales soportados por Strata
KNOWN_STRATA_MODELS: dict[str, dict[str, Any]] = {
    "qwen3.8-flash-next-iq2_xs-32k": {
        "label": "Strata · Qwen3.8 Flash-Next (125B IQ2_XS)",
        "parameter_size": "125B",
        "family": "Qwen3.8 · qwen4exp",
        "quantization": "IQ2_XS",
        "context_length": 32768,
        "capabilities": ["chat", "completion", "thinking", "tools"],
        "vision_capable": False,
        "thinking_capable": True,
        "tools_capable": True,
    },
    "qwen3.8-flash-next-iq2_xs-64k": {
        "label": "Strata · Qwen3.8 Flash-Next (125B IQ2_XS 64K)",
        "parameter_size": "125B",
        "family": "Qwen3.8 · qwen4exp",
        "quantization": "IQ2_XS",
        "context_length": 65536,
        "capabilities": ["chat", "completion", "thinking", "tools"],
        "vision_capable": False,
        "thinking_capable": True,
        "tools_capable": True,
    },
    "qwen3.6-35b-a3b": {
        "label": "Strata · Qwen3.6 (35B-A3B Visión + MTP)",
        "parameter_size": "35B (3B activos)",
        "family": "Qwen3.6 · qwen35moe",
        "quantization": "UD-Q4_K_XL",
        "context_length": 32768,
        "capabilities": ["chat", "completion", "thinking", "tools", "vision"],
        "vision_capable": True,
        "thinking_capable": True,
        "tools_capable": True,
    },
}

STRATA_MODELS = KNOWN_STRATA_MODELS


def strata_request(path: str, payload: dict[str, Any] | None = None, timeout: int = 5) -> dict[str, Any]:
    """Realiza una petición HTTP al servidor local de Strata."""
    url = f"{STRATA_URL}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise RuntimeError(f"Strata no responde en {STRATA_URL}: {err}") from err


def strata_status() -> dict[str, Any]:
    """Comprueba si el servidor local de Strata está en línea y qué modelo tiene cargado."""
    try:
        data = strata_request("/health", timeout=1)
        health_status = str(data.get("status") or "").strip()
        if health_status in {"ok", "loading model"}:
            models_list: list[dict[str, Any]] = []
            loaded_id = ""
            try:
                models_data = strata_request("/v1/models", timeout=2)
                raw_list = models_data.get("data", [])
                if isinstance(raw_list, list):
                    models_list = [m for m in raw_list if isinstance(m, dict)]
                    for item in models_list:
                        st = item.get("status") if isinstance(item.get("status"), dict) else {}
                        if st.get("value") == "loaded":
                            loaded_id = str(item.get("id") or "")
                            break
                    if not loaded_id and models_list:
                        first_st = models_list[0].get("status") if isinstance(models_list[0].get("status"), dict) else {}
                        if not first_st or (first_st.get("value") not in {"unloaded", "failed"} and not first_st.get("failed")):
                            loaded_id = str(models_list[0].get("id") or "")
            except Exception:
                pass
            return {"online": True, "loaded_model": loaded_id, "status": health_status, "models": models_list}
    except Exception:
        pass
    return {"online": False, "loaded_model": "", "status": "offline", "models": []}


def _strata_catalog_entry(model_key: str, info: dict[str, Any], active: bool) -> dict[str, Any]:
    """Construye una entrada homogénea del catálogo de Strata."""
    param_size = str(info.get("parameter_size") or "")
    short_tag = param_size.split(" ", 1)[0] if param_size else model_key
    return {
        "name": f"strata/{model_key}",
        "label": str(info.get("label") or f"Strata · {model_key}"),
        "provider": "strata",
        "provider_label": "Strata · GPU CUDA",
        "size": int(info.get("size") or 0),
        "parameter_size": param_size,
        "family": str(info.get("family") or "Strata CUDA"),
        "quantization": str(info.get("quantization") or ""),
        "modified_at": "",
        "capabilities": list(info.get("capabilities") or ["chat", "completion", "thinking", "tools"]),
        "chat_capable": True,
        "vision_capable": bool(info.get("vision_capable", False)),
        "thinking_capable": bool(info.get("thinking_capable", True)),
        "tools_capable": bool(info.get("tools_capable", True)),
        "context_length": int(info.get("context_length") or 32768),
        "remote": False,
        "remote_host": "",
        "benchmark_capable": True,
        "engine": f"Strata {short_tag} (En línea)" if active else f"Strata {short_tag} (Local en reposo)",
        "status": "online" if active else "standby",
    }


def strata_model_catalog() -> list[dict[str, Any]]:
    """Devuelve los modelos de Strata para el catálogo /api/models de MyKOS."""
    status = strata_status()
    if not status["online"]:
        return []

    loaded = str(status.get("loaded_model") or "").strip()
    if loaded.startswith("strata/"):
        loaded = loaded[len("strata/"):]

    catalog: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for m_key, m_info in STRATA_MODELS.items():
        active = bool(loaded and loaded == m_key)
        catalog.append(_strata_catalog_entry(m_key, m_info, active))
        seen_keys.add(m_key)

    for item in status.get("models") or []:
        st = item.get("status") if isinstance(item.get("status"), dict) else {}
        if st.get("failed") or str(st.get("value") or "").lower() == "failed":
            continue
        raw_id = str(item.get("id") or "").strip()
        clean_id = raw_id[len("strata/"):] if raw_id.startswith("strata/") else raw_id
        if not clean_id or clean_id in seen_keys:
            continue
        arch = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
        input_mods = [str(x).lower() for x in (arch.get("input_modalities") or [])]
        vision = "image" in input_mods or "vision" in clean_id.lower()
        caps = ["chat", "completion", "thinking", "tools"] + (["vision"] if vision else [])
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        ctx = int(meta.get("n_ctx") or item.get("context_length") or 32768)
        active = bool(loaded and loaded == clean_id)
        catalog.append(
            _strata_catalog_entry(
                clean_id,
                {
                    "label": f"Strata · {clean_id}",
                    "parameter_size": "",
                    "family": "Strata CUDA",
                    "quantization": str(meta.get("ftype") or ""),
                    "context_length": ctx,
                    "capabilities": caps,
                    "vision_capable": vision,
                    "thinking_capable": True,
                    "tools_capable": True,
                    "size": int(meta.get("size") or 0),
                },
                active,
            )
        )
        seen_keys.add(clean_id)

    return catalog


def strata_chat_request(
    messages: list[dict[str, Any]],
    generation: dict[str, Any],
    tool_schemas: list[dict[str, Any]] | None = None,
    model_name: str = "qwen3.8-flash-next-iq2_xs-32k",
    gateway_requester: Any = None,
) -> dict[str, Any]:
    """Envía la petición de chat a Strata y extrae el texto, herramientas y telemetría."""
    options = generation.get("options") if isinstance(generation, dict) else {}
    options = options if isinstance(options, dict) else {}

    clean_model = model_name
    if clean_model.startswith("strata/"):
        clean_model = clean_model[len("strata/"):]

    raw_temp = options.get("temperature")

    payload: dict[str, Any] = {
        "model": clean_model,
        "messages": [
            {
                key: value
                for key, value in item.items()
                if key in {"role", "content", "images", "tool_calls", "tool_call_id"}
            }
            for item in messages
        ],
        "stream": False,
        "max_tokens": int(options.get("num_predict", 2048) or 2048),
        "temperature": float(raw_temp) if raw_temp is not None else 0.5,
    }

    effort = str(generation.get("effort", "")).strip().casefold()
    if effort == "off":
        payload["reasoning_effort"] = "none"
    elif effort in {"low", "medium", "high"}:
        payload["reasoning_effort"] = effort

    if tool_schemas:
        payload["tools"] = tool_schemas
        payload["tool_choice"] = "auto"

    if gateway_requester is not None:
        return gateway_requester("strata", payload)

    return strata_request("/v1/chat/completions", payload, timeout=STRATA_TIMEOUT_SECONDS)
