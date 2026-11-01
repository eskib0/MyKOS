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
        is_ok = data.get("status") in {"ok", "loading model"}
        if is_ok:
            try:
                models_data = strata_request("/v1/models", timeout=2)
                models_list = models_data.get("data", [])
                loaded_id = models_list[0].get("id", "") if models_list else ""
            except Exception:
                loaded_id = ""
            return {"online": True, "loaded_model": loaded_id}
    except Exception:
        pass
    return {"online": False, "loaded_model": ""}


def strata_model_catalog() -> list[dict[str, Any]]:
    """Devuelve los modelos de Strata para el catálogo /api/models de MyKOS."""
    status = strata_status()
    online = status["online"]
    if not online:
        return []

    loaded = status.get("loaded_model", "")
    catalog = []
    # Modelo 1: Qwen3.8 Flash-Next 125B MoE
    m1_key = "qwen3.8-flash-next-iq2_xs-32k"
    m1_info = KNOWN_STRATA_MODELS[m1_key]
    m1_active = online and (loaded == m1_key or not loaded)
    catalog.append({
        "name": f"strata/{m1_key}",
        "label": m1_info["label"],
        "provider": "strata",
        "provider_label": "Strata · GPU CUDA",
        "size": 0,
        "parameter_size": m1_info["parameter_size"],
        "family": m1_info["family"],
        "quantization": m1_info["quantization"],
        "modified_at": "",
        "capabilities": m1_info["capabilities"],
        "chat_capable": True,
        "vision_capable": m1_info["vision_capable"],
        "thinking_capable": m1_info["thinking_capable"],
        "tools_capable": m1_info["tools_capable"],
        "context_length": m1_info["context_length"],
        "remote": False,
        "remote_host": "",
        "benchmark_capable": True,
        "engine": "Strata 125B (En línea)" if m1_active else "Strata 125B (Local en reposo)",
        "status": "online" if m1_active else "standby",
    })

    # Modelo 2: Qwen3.6-35B-A3B Visión + MTP
    m2_key = "qwen3.6-35b-a3b"
    m2_info = KNOWN_STRATA_MODELS[m2_key]
    m2_active = online and loaded == m2_key
    catalog.append({
        "name": f"strata/{m2_key}",
        "label": m2_info["label"],
        "provider": "strata",
        "provider_label": "Strata · GPU CUDA",
        "size": 0,
        "parameter_size": m2_info["parameter_size"],
        "family": m2_info["family"],
        "quantization": m2_info["quantization"],
        "modified_at": "",
        "capabilities": m2_info["capabilities"],
        "chat_capable": True,
        "vision_capable": m2_info["vision_capable"],
        "thinking_capable": m2_info["thinking_capable"],
        "tools_capable": m2_info["tools_capable"],
        "context_length": m2_info["context_length"],
        "remote": False,
        "remote_host": "",
        "benchmark_capable": True,
        "engine": "Strata 35B (En línea)" if m2_active else "Strata 35B (Local en reposo)",
        "status": "online" if m2_active else "standby",
    })

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
        "temperature": float(options.get("temperature", 0.5) or 0.5),
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
