"""Sub-módulo de integración con el catálogo oficial de Ollama y descargas en segundo plano."""

from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from tools import execute_ollama_pull_with_progress
from worker_helpers import ApiError, _catalog_cards

OLLAMA_LIBRARY_URL = "https://ollama.com/library"
OLLAMA_CATALOG_TIMEOUT_SECONDS = 15
OLLAMA_CATALOG_MAX_BYTES = 2 * 1024 * 1024

_OLLAMA_JOBS: dict[str, dict[str, Any]] = {}
_OLLAMA_JOBS_LOCK = threading.Lock()


def job_public(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job.get("id", ""),
        "model": job.get("model", ""),
        "status": job.get("status", "unknown"),
        "message": job.get("message", ""),
        "completed": job.get("completed", 0),
        "total": job.get("total", 0),
        "percent": job.get("percent", 0),
        "updated_at": job.get("updated_at", ""),
        "result": job.get("result") if job.get("status") == "completed" else None,
    }


def set_ollama_job(job_id: str, utc_now_fn: Callable[[], str], **updates: Any) -> dict[str, Any]:
    with _OLLAMA_JOBS_LOCK:
        job = _OLLAMA_JOBS.setdefault(job_id, {"id": job_id})
        job.update(updates)
        job["updated_at"] = utc_now_fn()
        return job_public(job)


def get_ollama_job(job_id: str) -> dict[str, Any] | None:
    with _OLLAMA_JOBS_LOCK:
        job = _OLLAMA_JOBS.get(job_id)
        return job_public(job) if job else None


def run_ollama_pull_job(job_id: str, action: dict[str, Any], utc_now_fn: Callable[[], str]) -> None:
    set_ollama_job(job_id, utc_now_fn, status="running", message="Descargando desde Ollama…")

    def on_progress(event: dict[str, Any]) -> None:
        total = int(event.get("total", 0) or 0)
        completed = int(event.get("completed", 0) or 0)
        percent = round(completed * 100 / total, 1) if total else 0
        set_ollama_job(
            job_id,
            utc_now_fn,
            message=str(event.get("status", "Descargando…")),
            completed=completed,
            total=total,
            percent=percent,
        )

    try:
        result = execute_ollama_pull_with_progress(action, on_progress)
    except Exception as error:
        set_ollama_job(job_id, utc_now_fn, status="failed", message=str(error), error=str(error))
        return
    set_ollama_job(job_id, utc_now_fn, status="completed", message="Modelo descargado correctamente.", percent=100, result=result)


def fetch_ollama_catalog(query: str = "", get_models_fn: Callable[[], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    query = str(query or "").strip()
    if len(query) > 80:
        raise ApiError("La búsqueda del catálogo no puede superar 80 caracteres.")
    params = {"q": query} if query else {"sort": "newest"}
    url = f"{OLLAMA_LIBRARY_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "text/html", "User-Agent": "MyKOS/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=OLLAMA_CATALOG_TIMEOUT_SECONDS) as response:
            raw = response.read(OLLAMA_CATALOG_MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"El catálogo de Ollama devolvió HTTP {error.code}.") from error
    except urllib.error.URLError as error:
        raise RuntimeError("No se pudo conectar con el catálogo público de Ollama.") from error
    except (OSError, TimeoutError) as error:
        raise RuntimeError(f"No se pudo consultar el catálogo de Ollama: {error}") from error
    if len(raw) > OLLAMA_CATALOG_MAX_BYTES:
        raise RuntimeError("La respuesta del catálogo de Ollama es demasiado grande.")
    document = raw.decode("utf-8", errors="replace")
    cards = _catalog_cards(document)
    installed: list[dict[str, Any]] = []
    if get_models_fn is not None:
        try:
            installed = get_models_fn()
        except RuntimeError:
            installed = []
    installed_names = {
        str(model.get("name", "")).split(":", 1)[0].casefold()
        for model in installed
        if model.get("name") and model.get("provider", "ollama") == "ollama"
    }
    for card in cards:
        card["installed"] = str(card["name"]).casefold() in installed_names
    return {
        "ok": True,
        "query": query,
        "source": OLLAMA_LIBRARY_URL,
        "count": len(cards),
        "models": cards,
    }
