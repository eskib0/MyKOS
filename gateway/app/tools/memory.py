"""Gestión de memoria persistente (local y semántica) de MyKOS.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import gateway_store
from embedding_memory import (
    remove as remove_memory_embedding,
    search as semantic_memory_search,
    status as memory_embedding_status,
    upsert as upsert_memory_embedding,
)
from .base import (
    MEMORY_CATEGORIES,
    MEMORY_FILE,
    MEMORY_LOCK,
    MEMORY_MAX_CONTENT_BYTES,
    MEMORY_MAX_ENTRIES,
    MEMORY_MAX_TAGS,
    MEMORY_MAX_TAG_CHARS,
    MEMORY_MAX_TITLE_CHARS,
    ToolError,
)


def _memory_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_memory_store() -> dict[str, Any]:
    # La memoria la guarda el Gateway (gateway_store); sin Gateway, el fichero data/memory.json de siempre.
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = gateway_store.load_document("memory", legacy_file=MEMORY_FILE, default={"entries": []})
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ToolError("La memoria persistente no se puede leer; no se modificará.") from error
    except gateway_store.StoreError as error:
        raise ToolError(f"La memoria persistente no está disponible ahora mismo: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise ToolError("El formato de la memoria persistente no es válido; no se modificará.")
    return data


def _save_memory_store(store: dict[str, Any]) -> None:
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        gateway_store.save_document("memory", store, legacy_file=MEMORY_FILE, indent=2, source="tools.memory")
    except gateway_store.StoreError as error:
        raise ToolError(f"No se pudo guardar la memoria persistente: {error}") from error


def _memory_summary(entry: dict[str, Any]) -> dict[str, Any]:
    content = str(entry.get("content", ""))
    return {
        "id": str(entry.get("id", "")),
        "title": str(entry.get("title", "")),
        "category": str(entry.get("category", "fact")),
        "tags": [str(tag) for tag in (entry.get("tags") or [])],
        "preview": content.replace("\n", " ").strip()[:240],
        "created_at": str(entry.get("created_at", "")),
        "updated_at": str(entry.get("updated_at", "")),
    }


def memory_catalog() -> dict[str, Any]:
    try:
        with MEMORY_LOCK:
            store = _load_memory_store()
            entries = sorted(
                (entry for entry in store["entries"] if isinstance(entry, dict)),
                key=lambda item: str(item.get("updated_at", "")),
                reverse=True,
            )
        return {
            "ok": True,
            "count": len(entries),
            "entries": [_memory_summary(entry) for entry in entries[:50]],
            "embedding": memory_embedding_status(),
        }
    except ToolError as error:
        return {"ok": False, "count": 0, "entries": [], "error": str(error)}


def _find_memory_entry(entries: list[Any], memory_id: str) -> dict[str, Any] | None:
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("id", "")) == memory_id:
            return entry
    return None


def _normalise_memory_tags(raw_tags: Any) -> list[str]:
    if raw_tags is None:
        return []
    if isinstance(raw_tags, str):
        raw_tags = raw_tags.split(",")
    if not isinstance(raw_tags, list):
        raise ToolError("Las etiquetas deben ser una lista de textos.")
    tags: list[str] = []
    for raw_tag in raw_tags[:MEMORY_MAX_TAGS]:
        if not isinstance(raw_tag, str):
            raise ToolError("Cada etiqueta debe ser texto.")
        tag = raw_tag.strip().casefold()
        if not tag:
            continue
        if len(tag) > MEMORY_MAX_TAG_CHARS:
            raise ToolError(f"Cada etiqueta puede tener como máximo {MEMORY_MAX_TAG_CHARS} caracteres.")
        if tag not in tags:
            tags.append(tag)
    return tags


def _normalise_memory_category(raw_category: Any) -> str:
    category = str(raw_category or "fact").strip().casefold()
    if category not in MEMORY_CATEGORIES:
        available = ", ".join(sorted(MEMORY_CATEGORIES))
        raise ToolError(f"Categoría no válida: {category}. Usa una de: {available}.")
    return category


def _list_memory(arguments: dict[str, Any]) -> dict[str, Any]:
    category = str(arguments.get("category", "")).strip().casefold()
    if category:
        category = _normalise_memory_category(category)
    try:
        max_results = int(arguments.get("max_results", 50))
    except (TypeError, ValueError) as error:
        raise ToolError("max_results debe ser un número entero.") from error
    max_results = max(1, min(max_results, 50))
    with MEMORY_LOCK:
        store = _load_memory_store()
        entries = [entry for entry in store["entries"] if isinstance(entry, dict)]
        if category:
            entries = [entry for entry in entries if entry.get("category") == category]
        entries.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
    return {
        "ok": True,
        "count": len(entries),
        "entries": [_memory_summary(entry) for entry in entries[:max_results]],
    }


def _search_memory(arguments: dict[str, Any]) -> dict[str, Any]:
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("Debes indicar qué quieres buscar en la memoria.")
    query = query.strip()
    if len(query) > 300:
        raise ToolError("La búsqueda no puede superar 300 caracteres.")
    terms = [term for term in query.casefold().split() if term]
    category = str(arguments.get("category", "")).strip().casefold()
    if category:
        category = _normalise_memory_category(category)
    try:
        max_results = int(arguments.get("max_results", 10))
    except (TypeError, ValueError) as error:
        raise ToolError("max_results debe ser un número entero.") from error
    max_results = max(1, min(max_results, 20))

    with MEMORY_LOCK:
        store = _load_memory_store()
        entries = [
            entry for entry in store["entries"]
            if isinstance(entry, dict) and (not category or entry.get("category") == category)
        ]

    semantic_matches, semantic_available = semantic_memory_search(query, entries, max_results)
    if semantic_available and semantic_matches:
        by_id = {str(entry.get("id", "")): entry for entry in entries}
        matches: list[dict[str, Any]] = []
        for semantic_match in semantic_matches:
            entry = by_id.get(str(semantic_match.get("id", "")))
            if entry is None:
                continue
            matches.append(
                {
                    "id": str(entry.get("id", "")),
                    "title": str(entry.get("title", "")),
                    "category": str(entry.get("category", "fact")),
                    "tags": [str(tag) for tag in (entry.get("tags") or [])],
                    "score": round(float(semantic_match.get("score", 0.0)), 4),
                    "match_type": "semantic",
                    "preview": str(entry.get("content", "")).replace("\n", " ").strip()[:300],
                    "updated_at": str(entry.get("updated_at", "")),
                }
            )
        return {
            "ok": True,
            "query": query,
            "count": len(matches),
            "matches": matches,
            "semantic": True,
            "embedding": memory_embedding_status(),
        }

    # Fallback seguro: búsqueda textual si llama.cpp embeddings no está disponible.
    matches = []
    for entry in entries:
        content = str(entry.get("content", ""))
        haystack = " ".join(
            [
                str(entry.get("title", "")),
                content,
                " ".join(str(tag) for tag in (entry.get("tags") or [])),
            ]
        ).casefold()
        active_terms = [term for term in terms if len(term) >= 3] or list(terms)
        hits = [term for term in active_terms if term in haystack]
        if not hits:
            continue
        score = len(hits) * 1000 + sum(haystack.count(term) for term in hits)
        preview = content.replace("\n", " ").strip()
        position = preview.casefold().find(hits[0])
        if position >= 0:
            preview = preview[max(0, position - 80):position + 220]
        matches.append(
            {
                "id": str(entry.get("id", "")),
                "title": str(entry.get("title", "")),
                "category": str(entry.get("category", "fact")),
                "tags": [str(tag) for tag in (entry.get("tags") or [])],
                "score": score,
                "match_type": "text",
                "preview": preview,
                "updated_at": str(entry.get("updated_at", "")),
            }
        )
    matches.sort(key=lambda item: (item["score"], item["updated_at"]), reverse=True)
    return {
        "ok": True,
        "query": query,
        "count": len(matches),
        "matches": matches[:max_results],
        "semantic": False,
        "embedding": memory_embedding_status(),
    }


def _read_memory(arguments: dict[str, Any]) -> dict[str, Any]:
    memory_id = str(arguments.get("memory_id", "")).strip()
    if not memory_id:
        raise ToolError("Debes indicar el identificador del recuerdo.")
    with MEMORY_LOCK:
        store = _load_memory_store()
        entry = _find_memory_entry(store["entries"], memory_id)
        if entry is None:
            raise ToolError("No existe ese recuerdo.")
        return {"ok": True, "memory": dict(entry)}


def _prepare_save_memory(arguments: dict[str, Any]) -> dict[str, Any]:
    memory_id = str(arguments.get("memory_id", "")).strip()
    title = arguments.get("title")
    content = arguments.get("content")
    if not isinstance(title, str) or not title.strip():
        raise ToolError("El recuerdo necesita un título.")
    if len(title.strip()) > MEMORY_MAX_TITLE_CHARS:
        raise ToolError(f"El título supera el límite de {MEMORY_MAX_TITLE_CHARS} caracteres.")
    if not isinstance(content, str) or not content.strip():
        raise ToolError("El recuerdo necesita contenido.")
    encoded = content.encode("utf-8")
    if len(encoded) > MEMORY_MAX_CONTENT_BYTES:
        raise ToolError(f"El contenido supera el límite de {MEMORY_MAX_CONTENT_BYTES} bytes.")
    if b"\x00" in encoded:
        raise ToolError("El contenido contiene un byte nulo y no se guardará.")
    category = _normalise_memory_category(arguments.get("category", "fact"))
    tags = _normalise_memory_tags(arguments.get("tags", []))
    with MEMORY_LOCK:
        store = _load_memory_store()
        existing = _find_memory_entry(store["entries"], memory_id) if memory_id else None
    if memory_id and existing is None:
        raise ToolError("No existe el recuerdo que se quiere actualizar.")
    if not memory_id and len(store["entries"]) >= MEMORY_MAX_ENTRIES:
        raise ToolError("La memoria ha alcanzado su límite de entradas.")
    return {
        "kind": "save_memory",
        "memory_id": memory_id,
        "title": title.strip(),
        "content": content,
        "category": category,
        "tags": tags,
        "mode": "update" if memory_id else "create",
    }


def _prepare_delete_memory(arguments: dict[str, Any]) -> dict[str, Any]:
    memory_id = str(arguments.get("memory_id", "")).strip()
    if not memory_id:
        raise ToolError("Debes indicar el identificador del recuerdo.")
    with MEMORY_LOCK:
        store = _load_memory_store()
        existing = _find_memory_entry(store["entries"], memory_id)
    if existing is None:
        raise ToolError("No existe ese recuerdo.")
    return {
        "kind": "delete_memory",
        "memory_id": memory_id,
        "title": str(existing.get("title", "")),
        "category": str(existing.get("category", "fact")),
    }


def _execute_save_memory(action: dict[str, Any]) -> dict[str, Any]:
    memory_id = str(action.get("memory_id", "")).strip()
    title = action.get("title")
    content = action.get("content")
    if not isinstance(title, str) or not isinstance(content, str):
        raise ToolError("La acción de memoria no contiene título y contenido válidos.")
    encoded = content.encode("utf-8")
    if len(encoded) > MEMORY_MAX_CONTENT_BYTES or b"\x00" in encoded:
        raise ToolError("El contenido ya no cumple los límites de memoria.")
    category = _normalise_memory_category(action.get("category", "fact"))
    tags = _normalise_memory_tags(action.get("tags", []))
    now = _memory_now()
    with MEMORY_LOCK:
        store = _load_memory_store()
        entries = store["entries"]
        existing = _find_memory_entry(entries, memory_id) if memory_id else None
        if memory_id and existing is None:
            raise ToolError("El recuerdo ya no existe; no se actualizará.")
        if existing is None:
            if len(entries) >= MEMORY_MAX_ENTRIES:
                raise ToolError("La memoria ha alcanzado su límite de entradas.")
            memory_id = memory_id or os.urandom(12).hex()
            entry = {
                "id": memory_id,
                "title": title.strip(),
                "content": content,
                "category": category,
                "tags": tags,
                "created_at": now,
                "updated_at": now,
            }
            entries.append(entry)
            mode = "created"
        else:
            existing["title"] = title.strip()
            existing["content"] = content
            existing["category"] = category
            existing["tags"] = tags
            existing["updated_at"] = now
            entry = existing
            mode = "updated"
        _save_memory_store(store)
    semantic_indexed = upsert_memory_embedding(entry)
    return {
        "ok": True,
        "action": "save_memory",
        "mode": mode,
        "memory": _memory_summary(entry),
        "semantic_indexed": semantic_indexed,
    }


def _execute_delete_memory(action: dict[str, Any]) -> dict[str, Any]:
    memory_id = str(action.get("memory_id", "")).strip()
    if not memory_id:
        raise ToolError("La acción no contiene un identificador de memoria.")
    with MEMORY_LOCK:
        store = _load_memory_store()
        before = len(store["entries"])
        deleted = _find_memory_entry(store["entries"], memory_id)
        if deleted is None:
            raise ToolError("El recuerdo ya no existe.")
        store["entries"] = [entry for entry in store["entries"] if entry.get("id") != memory_id]
        _save_memory_store(store)
    try:
        remove_memory_embedding(memory_id)
    except OSError:
        pass
    return {
        "ok": True,
        "action": "delete_memory",
        "memory_id": memory_id,
        "title": str(deleted.get("title", "")),
        "remaining": before - 1,
    }
