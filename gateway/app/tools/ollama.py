"""Integración y gestión del motor local Ollama para MyKOS.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable

from .base import (
    OLLAMA_LOCK,
    OLLAMA_MODEL_NAME_CHARS,
    OLLAMA_PULL_TIMEOUT_SECONDS,
    OLLAMA_REQUEST_TIMEOUT_SECONDS,
    OLLAMA_URL,
    ToolError,
)

def _ollama_request_json(
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    method: str | None = None,
    timeout: int = OLLAMA_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    request_method = method or ("POST" if payload is not None else "GET")
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{OLLAMA_URL}{path}",
        data=body,
        headers=headers,
        method=request_method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ToolError(f"Ollama devolvió HTTP {error.code}: {detail[:500]}") from error
    except urllib.error.URLError as error:
        raise ToolError(
            f"No se puede conectar con Ollama en {OLLAMA_URL}. Comprueba que Ollama esté iniciado."
        ) from error
    except (OSError, TimeoutError) as error:
        raise ToolError(f"La petición a Ollama no pudo completarse: {error}") from error

    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
        for line in reversed(raw.decode("utf-8", errors="replace").splitlines()):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        if parsed is None:
            raise ToolError("Ollama devolvió una respuesta que no es JSON válido.")
    if not isinstance(parsed, dict):
        raise ToolError("Ollama devolvió un formato de respuesta inesperado.")
    return parsed


def _normalise_ollama_model_name(raw_model: Any) -> str:
    if not isinstance(raw_model, str) or not raw_model.strip():
        raise ToolError("Debes indicar el nombre del modelo de Ollama.")
    model = raw_model.strip()
    if len(model) > OLLAMA_MODEL_NAME_CHARS or "\x00" in model:
        raise ToolError("El nombre del modelo de Ollama es demasiado largo o contiene caracteres no válidos.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", model):
        raise ToolError("El nombre del modelo solo puede contener letras, números, punto, dos puntos, barra, guion y guion bajo.")
    return model


def _ollama_model_summary(raw_model: dict[str, Any]) -> dict[str, Any]:
    details = raw_model.get("details") or {}
    capabilities = [str(item) for item in (raw_model.get("capabilities") or [])]
    name = str(raw_model.get("name", ""))
    remote = bool(
        raw_model.get("remote_model")
        or raw_model.get("remote_host")
        or name.endswith(":cloud")
    )
    return {
        "name": name,
        "size": raw_model.get("size", 0),
        "parameter_size": details.get("parameter_size", ""),
        "family": details.get("family", ""),
        "quantization": details.get("quantization_level", ""),
        "modified_at": raw_model.get("modified_at", ""),
        "capabilities": capabilities,
        "chat_capable": not capabilities or bool({"chat", "completion"}.intersection(capabilities)),
        "vision_capable": "vision" in capabilities,
        "remote": remote,
        "remote_host": raw_model.get("remote_host", ""),
    }


def _list_ollama_models() -> dict[str, Any]:
    result = _ollama_request_json("/api/tags")
    raw_models = result.get("models", [])
    if not isinstance(raw_models, list):
        raw_models = []
    models = [
        _ollama_model_summary(model)
        for model in raw_models
        if isinstance(model, dict) and str(model.get("name", "")).strip()
    ]
    return {
        "ok": True,
        "action": "list_ollama_models",
        "ollama_url": OLLAMA_URL,
        "count": len(models),
        "models": models,
    }


def _find_ollama_model(model_name: str, models_result: dict[str, Any]) -> dict[str, Any] | None:
    for model in models_result.get("models", []):
        if isinstance(model, dict) and str(model.get("name", "")) == model_name:
            return model
    return None


def _prepare_pull_ollama_model(arguments: dict[str, Any]) -> dict[str, Any]:
    model_name = _normalise_ollama_model_name(arguments.get("model"))
    current = _list_ollama_models()
    existing = _find_ollama_model(model_name, current)
    return {
        "kind": "pull_ollama_model",
        "model": model_name,
        "ollama_url": OLLAMA_URL,
        "already_installed": existing is not None,
        "current_size": existing.get("size", 0) if existing else 0,
    }


def _prepare_delete_ollama_model(arguments: dict[str, Any]) -> dict[str, Any]:
    model_name = _normalise_ollama_model_name(arguments.get("model"))
    current = _list_ollama_models()
    existing = _find_ollama_model(model_name, current)
    if existing is None:
        raise ToolError(f"El modelo '{model_name}' no está instalado en Ollama.")
    return {
        "kind": "delete_ollama_model",
        "model": model_name,
        "ollama_url": OLLAMA_URL,
        "size": existing.get("size", 0),
        "capabilities": existing.get("capabilities", []),
    }


def execute_ollama_pull_with_progress(
    action: dict[str, Any],
    progress_callback: Any = None,
) -> dict[str, Any]:
    model_name = _normalise_ollama_model_name(action.get("model"))
    payload = json.dumps({"name": model_name, "stream": True}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/pull",
        data=payload,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    last_event: dict[str, Any] = {}
    with OLLAMA_LOCK:
        try:
            with urllib.request.urlopen(request, timeout=OLLAMA_PULL_TIMEOUT_SECONDS) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as error:
                        raise ToolError("Ollama devolvió un progreso de descarga no válido.") from error
                    if not isinstance(event, dict):
                        continue
                    last_event = event
                    if progress_callback is not None:
                        progress_callback(event)
                    if event.get("error"):
                        raise ToolError(f"Ollama no pudo descargar el modelo: {event['error']}")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise ToolError(f"Ollama devolvió HTTP {error.code}: {detail[:500]}") from error
        except urllib.error.URLError as error:
            raise ToolError(
                f"No se puede conectar con Ollama en {OLLAMA_URL}. Comprueba que Ollama esté iniciado."
            ) from error
        except (OSError, TimeoutError) as error:
            raise ToolError(f"La descarga de Ollama no pudo completarse: {error}") from error
        current = _list_ollama_models()
        installed = _find_ollama_model(model_name, current)
    if installed is None:
        raise ToolError("Ollama terminó la descarga, pero el modelo no aparece en el listado posterior.")
    return {
        "ok": True,
        "action": "pull_ollama_model",
        "model": model_name,
        "status": last_event.get("status", "success"),
        "model_info": installed,
    }


def _execute_pull_ollama_model(action: dict[str, Any]) -> dict[str, Any]:
    return execute_ollama_pull_with_progress(action)


def _execute_delete_ollama_model(action: dict[str, Any]) -> dict[str, Any]:
    model_name = _normalise_ollama_model_name(action.get("model"))
    with OLLAMA_LOCK:
        current = _list_ollama_models()
        if _find_ollama_model(model_name, current) is None:
            raise ToolError(f"El modelo '{model_name}' ya no está instalado; no se borrará nada.")
        response = _ollama_request_json(
            "/api/delete",
            {"name": model_name},
            method="DELETE",
            timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS,
        )
        remaining = _list_ollama_models()
    if _find_ollama_model(model_name, remaining) is not None:
        raise ToolError("Ollama respondió correctamente, pero el modelo sigue apareciendo en el listado.")
    return {
        "ok": True,
        "action": "delete_ollama_model",
        "model": model_name,
        "status": response.get("status", "success"),
        "remaining_models": remaining.get("models", []),
    }


