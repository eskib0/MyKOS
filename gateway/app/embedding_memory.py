from __future__ import annotations

import atexit
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

import gateway_store


PROJECT_ROOT = Path(__file__).resolve().parent
INDEX_FILE = PROJECT_ROOT / "data" / "memory_embeddings.json"
EMBEDDING_URL = os.environ.get("MYKOS_LLAMA_CPP_EMBED_URL", "http://127.0.0.1:8092").rstrip("/")
EMBEDDING_EXE = os.environ.get(
    "MYKOS_LLAMA_CPP_EMBED_EXE",
    shutil.which("llama-server") or str(Path.home() / "llama.cpp" / "build" / "bin" / "llama-server"),
).strip()
EMBEDDING_MODEL_NAME = os.environ.get("MYKOS_LLAMA_CPP_EMBED_NAME", "nomic-embed-text:latest").strip()
EMBEDDING_MODEL_PATH = os.environ.get("MYKOS_LLAMA_CPP_EMBED_MODEL", "").strip()
EMBEDDING_CONTEXT = int(os.environ.get("MYKOS_LLAMA_CPP_EMBED_CONTEXT", "2048"))
EMBEDDING_BATCH = int(os.environ.get("MYKOS_LLAMA_CPP_EMBED_BATCH", "2048"))
EMBEDDING_START_TIMEOUT = 90

_LOCK = threading.RLock()
_PROCESS: subprocess.Popen[Any] | None = None
_LAST_ERROR = ""


def _request(path: str, payload: dict[str, Any] | None = None, timeout: int = 20) -> dict[str, Any]:
    body = None
    method = "GET"
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(
        f"{EMBEDDING_URL}{path}", data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(f"No se puede conectar con llama.cpp embeddings en {EMBEDDING_URL}.") from error
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("llama.cpp embeddings devolvió JSON no válido.") from error
    if not isinstance(result, dict):
        raise RuntimeError("llama.cpp embeddings devolvió un formato inesperado.")
    return result


def _resolve_model_path() -> str:
    if EMBEDDING_MODEL_PATH and Path(EMBEDDING_MODEL_PATH).is_file():
        return EMBEDDING_MODEL_PATH
    ollama = shutil.which("ollama")
    if ollama:
        try:
            completed = subprocess.run(
                [ollama, "show", EMBEDDING_MODEL_NAME, "--modelfile"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            match = re.search(r"^FROM\s+(.+?)\s*$", completed.stdout or "", re.MULTILINE)
            if match and Path(match.group(1).strip()).is_file():
                return match.group(1).strip()
        except (OSError, subprocess.SubprocessError):
            pass
    raise RuntimeError(
        "No se encontró el GGUF de nomic-embed-text. "
        "Configura MYKOS_LLAMA_CPP_EMBED_MODEL o instala el modelo en Ollama."
    )


def _health_ok() -> bool:
    try:
        result = _request("/health", timeout=2)
        return result.get("status") == "ok"
    except RuntimeError:
        return False


def _start_server() -> None:
    global _PROCESS, _LAST_ERROR
    with _LOCK:
        if _health_ok():
            return
        if not Path(EMBEDDING_EXE).is_file():
            raise RuntimeError(f"No se encuentra llama-server para embeddings: {EMBEDDING_EXE}")
        model_path = _resolve_model_path()
        parsed = urlparse(EMBEDDING_URL)
        command = [
            EMBEDDING_EXE,
            "-m", model_path,
            "--embedding",
            "--pooling", "mean",
            "-c", str(EMBEDDING_CONTEXT),
            "-b", str(EMBEDDING_BATCH),
            "-ub", str(EMBEDDING_BATCH),
            "-ngl", "99",
            "-fa", "auto",
            "--no-webui",
            "--host", parsed.hostname or "127.0.0.1",
            "--port", str(parsed.port or 8092),
        ]
        if _PROCESS is not None and _PROCESS.poll() is not None:
            _PROCESS = None
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        _PROCESS = subprocess.Popen(
            command,
            cwd=str(Path(EMBEDDING_EXE).parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        deadline = time.monotonic() + EMBEDDING_START_TIMEOUT
        while time.monotonic() < deadline:
            if _PROCESS.poll() is not None:
                code = _PROCESS.returncode
                _PROCESS = None
                _LAST_ERROR = f"llama.cpp embeddings terminó al arrancar (código {code})."
                raise RuntimeError(_LAST_ERROR)
            if _health_ok():
                _LAST_ERROR = ""
                return
            time.sleep(0.5)
        _LAST_ERROR = "llama.cpp embeddings tardó demasiado en cargar nomic-embed-text."
        raise RuntimeError(_LAST_ERROR)


def _normalise_vector(raw: Any) -> list[float]:
    if not isinstance(raw, list) or not raw:
        raise RuntimeError("llama.cpp embeddings no devolvió un vector.")
    vector = [float(value) for value in raw]
    if not all(math.isfinite(value) for value in vector):
        raise RuntimeError("llama.cpp embeddings devolvió valores no finitos.")
    return vector


def embed(text: str) -> list[float]:
    text = str(text).strip()
    if not text:
        raise RuntimeError("No se puede generar un embedding vacío.")
    try:
        base = os.environ.get("MYKOS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        payload = json.dumps({"model": EMBEDDING_MODEL_NAME, "prompt": text}).encode("utf-8")
        req = urllib.request.Request(base + "/api/embeddings", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            vec = json.loads(resp.read().decode("utf-8")).get("embedding")
        if vec:
            return _normalise_vector(vec)
    except (OSError, ValueError, RuntimeError):
        pass
    _start_server()
    result = _request(
        "/v1/embeddings",
        {"model": EMBEDDING_MODEL_NAME, "input": text},
        timeout=120,
    )
    data = result.get("data") if isinstance(result.get("data"), list) else []
    first = data[0] if data and isinstance(data[0], dict) else {}
    return _normalise_vector(first.get("embedding"))


def _load_index() -> dict[str, Any]:
    # El índice lo guarda el Gateway junto a la memoria (gateway_store); sin Gateway, data/memory_embeddings.json.
    empty = {"version": 1, "model": EMBEDDING_MODEL_NAME, "entries": {}}
    try:
        data = gateway_store.load_document("memory-index", legacy_file=INDEX_FILE)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return empty
    return data


def _save_index(index: dict[str, Any]) -> None:
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    gateway_store.save_document("memory-index", index, legacy_file=INDEX_FILE, indent=None, source="embedding_memory")


def _memory_text(entry: dict[str, Any]) -> str:
    return "\n".join(
        [
            str(entry.get("title", "")),
            str(entry.get("content", "")),
            " ".join(str(tag) for tag in (entry.get("tags") or [])),
        ]
    ).strip()


def upsert(entry: dict[str, Any]) -> bool:
    try:
        vector = embed(_memory_text(entry))
        with _LOCK:
            index = _load_index()
            index["model"] = EMBEDDING_MODEL_NAME
            index["entries"][str(entry.get("id", ""))] = {
                "updated_at": str(entry.get("updated_at", "")),
                "vector": vector,
            }
            _save_index(index)
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def remove(memory_id: str) -> None:
    with _LOCK:
        index = _load_index()
        index.get("entries", {}).pop(str(memory_id), None)
        _save_index(index)


def search(query: str, entries: list[dict[str, Any]], max_results: int) -> tuple[list[dict[str, Any]], bool]:
    try:
        query_vector = embed(query)
    except (OSError, RuntimeError, ValueError):
        return [], False
    with _LOCK:
        index = _load_index()
        index_entries = index.setdefault("entries", {})
        changed = False
        for entry in entries:
            memory_id = str(entry.get("id", ""))
            cached = index_entries.get(memory_id)
            if not isinstance(cached, dict) or cached.get("updated_at") != str(entry.get("updated_at", "")):
                try:
                    index_entries[memory_id] = {
                        "updated_at": str(entry.get("updated_at", "")),
                        "vector": embed(_memory_text(entry)),
                    }
                    changed = True
                except (OSError, RuntimeError, ValueError):
                    continue
        if changed:
            index["model"] = EMBEDDING_MODEL_NAME
            _save_index(index)
        scored: list[tuple[float, str]] = []
        query_norm = math.sqrt(sum(value * value for value in query_vector)) or 1.0
        for memory_id, cached in index_entries.items():
            vector = cached.get("vector") if isinstance(cached, dict) else None
            if not isinstance(vector, list) or len(vector) != len(query_vector):
                continue
            vector_norm = math.sqrt(sum(float(value) * float(value) for value in vector)) or 1.0
            score = sum(float(a) * float(b) for a, b in zip(query_vector, vector)) / (query_norm * vector_norm)
            scored.append((score, str(memory_id)))
        scored.sort(reverse=True)
        by_id = {str(entry.get("id", "")): entry for entry in entries}
        matches = [
            {"id": memory_id, "score": score}
            for score, memory_id in scored[:max_results]
            if memory_id in by_id
        ]
        return matches, True


def _ollama_ok() -> bool:
    try:
        base = os.environ.get("MYKOS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        with urllib.request.urlopen(base + "/api/tags", timeout=2) as resp:
            models = json.loads(resp.read().decode("utf-8")).get("models", [])
        wanted = EMBEDDING_MODEL_NAME.split(":")[0]
        return any(str(m.get("name", "")).split(":")[0] == wanted for m in models)
    except (OSError, ValueError):
        return False


def status() -> dict[str, Any]:
    with _LOCK:
        ollama_url = os.environ.get("MYKOS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        ollama_available = _ollama_ok()
        return {
            "available": ollama_available or Path(EMBEDDING_EXE).is_file(),
            "provider": "ollama" if ollama_available else "llama.cpp-fallback",
            "url": ollama_url if ollama_available else EMBEDDING_URL,
            "model": EMBEDDING_MODEL_NAME,
            "model_path": EMBEDDING_MODEL_PATH,
            "running": _health_ok(),
            "last_error": _LAST_ERROR,
            "index": str(INDEX_FILE),
        }


def shutdown() -> None:
    global _PROCESS
    with _LOCK:
        process = _PROCESS
        _PROCESS = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=8)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass


atexit.register(shutdown)
