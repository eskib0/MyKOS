"""Subagentes locales mínimos para MyKOS.

Cada trabajo usa Ollama directamente con un prompt aislado. No recibe las
herramientas de MyKOS, no accede a archivos y no se conecta a MyKOS.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gateway_store


ROOT = Path(__file__).resolve().parent
SUBAGENTS_FILE = ROOT / "data" / "subagents.json"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.6:latest").strip() or "qwen3.6:latest"
MAX_PROMPT_CHARS = 12_000
MAX_JOBS = 100
MAX_ACTIVE = 3
DEFAULT_TIMEOUT_SECONDS = 15 * 60


class SubagentError(RuntimeError):
    """Error controlado de subagentes."""


_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict[str, Any]:
    data = gateway_store.load_document(
        "subagents",
        legacy_file=SUBAGENTS_FILE,
        default={"jobs": []},
    )
    jobs = data.get("jobs") if isinstance(data, dict) and isinstance(data.get("jobs"), list) else []
    return {"jobs": jobs[-MAX_JOBS:]}


def _save(data: dict[str, Any]) -> None:
    gateway_store.save_document(
        "subagents",
        data,
        legacy_file=SUBAGENTS_FILE,
        indent=2,
        source="subagents.worker",
    )


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(job.get("id", "")),
        "title": str(job.get("title", "")),
        "model": str(job.get("model", "")),
        "status": str(job.get("status", "unknown")),
        "prompt": str(job.get("prompt", ""))[:800],
        "result": str(job.get("result", "")),
        "error": str(job.get("error", "")),
        "created_at": str(job.get("created_at", "")),
        "updated_at": str(job.get("updated_at", "")),
    }


def list_jobs(limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    with _LOCK:
        data = _load()
    jobs = [job for job in data["jobs"] if isinstance(job, dict)]
    return {"ok": True, "action": "list_subagents", "jobs": [_public(job) for job in jobs[-limit:]]}


def prepare_spawn(arguments: dict[str, Any]) -> dict[str, Any]:
    prompt = arguments.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise SubagentError("Debes indicar la tarea del subagente.")
    prompt = prompt.strip()
    if len(prompt) > MAX_PROMPT_CHARS:
        raise SubagentError("La tarea del subagente supera el límite de 12.000 caracteres.")
    title = str(arguments.get("title", "Subagente local")).strip() or "Subagente local"
    if len(title) > 160:
        raise SubagentError("El título del subagente es demasiado largo.")
    model = str(arguments.get("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
    if len(model) > 200 or any(char.isspace() for char in model):
        raise SubagentError("El nombre del modelo no es válido.")
    return {"kind": "spawn_subagent", "title": title, "prompt": prompt, "model": model}


def _set_job(job_id: str, **updates: Any) -> None:
    with _LOCK:
        data = _load()
        job = next((item for item in data["jobs"] if isinstance(item, dict) and item.get("id") == job_id), None)
        if job is None:
            return
        job.update(updates)
        job["updated_at"] = _now()
        _save(data)


def _ollama_chat(model: str, prompt: str) -> str:
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": "Eres un subagente local aislado de MyKOS. Responde a la tarea, no uses herramientas, no ejecutes comandos y no afirmes haber cambiado archivos.",
            },
            {"role": "user", "content": prompt},
        ],
        "options": {"num_ctx": 8192, "num_predict": 2048, "temperature": 0.2},
    }
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            raw = response.read(2 * 1024 * 1024)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SubagentError(f"Ollama devolvió HTTP {error.code}: {detail[:400]}") from error
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise SubagentError(f"No se pudo completar el subagente local: {error}") from error
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SubagentError("Ollama devolvió una respuesta no válida.") from error
    message = data.get("message") if isinstance(data, dict) else None
    result = message.get("content") if isinstance(message, dict) else data.get("response") if isinstance(data, dict) else ""
    if not isinstance(result, str) or not result.strip():
        raise SubagentError("El subagente no devolvió texto.")
    return result.strip()


def _run(job_id: str, model: str, prompt: str) -> None:
    _set_job(job_id, status="running")
    try:
        result = _ollama_chat(model, prompt)
    except SubagentError as error:
        _set_job(job_id, status="failed", error=str(error))
        return
    _set_job(job_id, status="completed", result=result)


def spawn_approved(action: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        data = _load()
        active = [job for job in data["jobs"] if isinstance(job, dict) and job.get("status") in {"queued", "running"}]
        if len(active) >= MAX_ACTIVE:
            raise SubagentError("Ya hay demasiados subagentes activos; espera a que termine uno.")
        job = {
            "id": uuid.uuid4().hex,
            "title": str(action["title"]),
            "model": str(action["model"]),
            "prompt": str(action["prompt"]),
            "status": "queued",
            "result": "",
            "error": "",
            "created_at": _now(),
            "updated_at": _now(),
        }
        data["jobs"].append(job)
        _save(data)
    thread = threading.Thread(target=_run, args=(job["id"], job["model"], job["prompt"]), daemon=True, name=f"mykos-subagent-{job['id'][:8]}")
    thread.start()
    return {"ok": True, "action": "spawn_subagent", "job": _public(job)}
