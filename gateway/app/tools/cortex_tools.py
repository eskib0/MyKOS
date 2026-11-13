"""Herramientas de agente para MyKOS Cortex (cerebro y base de conocimiento local).
"""
from __future__ import annotations

from typing import Any
from .base import ToolError
from cortex import get_cortex


def _search_cortex(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    if not query:
        raise ToolError("Escribe un término o palabra clave para buscar en Cortex.")
    try:
        limit = int(arguments.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))

    engine = get_cortex()
    results = engine.search_notes(query, limit=limit)
    return {
        "ok": True,
        "query": query,
        "count": len(results),
        "results": [
            {
                "path": r["path"],
                "title": r["title"],
                "tags": r.get("tags", []),
                "aliases": r.get("aliases", []),
                "snippet": r.get("snippet", ""),
                "score": r.get("score", 0),
            }
            for r in results
        ],
    }


def _read_cortex_note(arguments: dict[str, Any]) -> dict[str, Any]:
    path = str(arguments.get("path", "")).strip()
    if not path:
        raise ToolError("Indica la ruta o título de la nota de Cortex que quieres leer.")

    engine = get_cortex()
    try:
        note = engine.get_note(path)
    except FileNotFoundError:
        # Si no se encuentra como ruta exacta, busca por título/nombre en la bóveda
        results = engine.search_notes(path, limit=1)
        if results:
            note = engine.get_note(results[0]["path"])
        else:
            raise ToolError(f"No se encontró la nota '{path}' en la bóveda de Cortex.")
    except Exception as error:
        raise ToolError(f"Error al leer la nota en Cortex: {error}")

    backlinks = [b["source"] for b in note.get("backlinks", [])]
    return {
        "ok": True,
        "path": note["path"],
        "title": note.get("title", ""),
        "tags": note.get("tags", []),
        "aliases": note.get("aliases", []),
        "frontmatter": note.get("frontmatter", {}),
        "content": note.get("content", ""),
        "backlinks": backlinks,
    }


def _save_cortex_note(arguments: dict[str, Any]) -> dict[str, Any]:
    path = str(arguments.get("path", "")).strip()
    content = str(arguments.get("content", ""))
    if not path:
        raise ToolError("Indica la ruta de la nota a guardar en Cortex (ej: '04 - Bitácora y Diario/Resumen-2026-11-13.md').")
    if not content:
        raise ToolError("El contenido de la nota no puede estar vacío.")

    if not path.lower().endswith(".md"):
        path = f"{path}.md"

    engine = get_cortex()
    try:
        res = engine.save_note(path, content)
    except Exception as error:
        raise ToolError(f"Error al guardar la nota en Cortex: {error}")

    return {
        "ok": True,
        "saved": True,
        "path": res.get("path", path),
        "message": f"Nota '{path}' guardada en Cortex correctamente y sincronizada en el grafo.",
    }
