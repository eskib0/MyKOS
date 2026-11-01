"""Comprobador del cliente Python del almacén (gateway_store) con los cargadores REALES de MyKOS.

Uso (desde la carpeta del proyecto de prueba, con MYKOS_STORE_MODE / MYKOS_STORE_URL / MYKOS_STORE_TOKEN del Gateway de prueba):

    python store_client_check.py memory-roundtrip     escribe una entrada de memoria y una del índice, y lee todo de vuelta
    python store_client_check.py unavailable          con el Gateway inaccesible los cargadores fallan EN VOZ ALTA
    python store_client_check.py shrink                un borrado masivo por error lo rechaza el almacén

Imprime una única línea JSON con los resultados; el llamador (probe-store-gateway.cjs) decide si son correctos.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.getcwd())

import embedding_memory  # noqa: E402
import gateway_store  # noqa: E402
import server  # noqa: E402
import tools  # noqa: E402


def memory_roundtrip() -> dict:
    out: dict = {"mode": gateway_store.mode()}
    store = tools._load_memory_store()
    out["memory_before"] = len(store["entries"])
    now = tools._memory_now()
    store["entries"].append(
        {"id": "prueba-almacen", "title": "Prueba del almacén", "content": "Contenido con ñ, acentos y 🍄", "category": "fact", "tags": ["prueba"], "created_at": now, "updated_at": now}
    )
    tools._save_memory_store(store)
    reread = tools._load_memory_store()
    out["memory_after"] = len(reread["entries"])
    out["memory_text_ok"] = any(e.get("id") == "prueba-almacen" and e.get("content") == "Contenido con ñ, acentos y 🍄" for e in reread["entries"])

    index = embedding_memory._load_index()
    out["index_before"] = len(index["entries"])
    index["entries"]["prueba-almacen"] = {"updated_at": now, "vector": [0.25, -0.5, 0.125]}
    embedding_memory._save_index(index)
    index2 = embedding_memory._load_index()
    out["index_after"] = len(index2["entries"])
    out["index_vector_ok"] = index2["entries"].get("prueba-almacen", {}).get("vector") == [0.25, -0.5, 0.125]

    conv = server.load_store()
    out["conversations"] = len(conv["conversations"])
    out["catalog_count"] = tools.memory_catalog().get("count")
    return out


def unavailable() -> dict:
    out: dict = {"mode": gateway_store.mode()}
    for label, call in (
        ("conversations", server.load_store),
        ("memory", tools._load_memory_store),
        ("index", embedding_memory._load_index),
    ):
        try:
            result = call()
            out[label] = {"raised": False, "returned_empty": not result.get("conversations", result.get("entries", True))}
        except tools.ToolError as error:
            out[label] = {"raised": "ToolError", "message": str(error)[:120]}
        except gateway_store.StoreError as error:
            out[label] = {"raised": type(error).__name__, "message": str(error)[:120]}
    try:
        server.save_store({"conversations": []})
        out["save"] = {"raised": False}
    except gateway_store.StoreError as error:
        out["save"] = {"raised": type(error).__name__}
    return out


def shrink() -> dict:
    out: dict = {"mode": gateway_store.mode()}
    store = server.load_store()
    out["before"] = len(store["conversations"])
    try:
        server.save_store({"conversations": store["conversations"][:1]})
        out["raised"] = False
    except gateway_store.StoreRejected as error:
        out["raised"] = "StoreRejected"
        out["message"] = str(error)[:160]
    out["after"] = len(server.load_store()["conversations"])
    return out


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    handlers = {"memory-roundtrip": memory_roundtrip, "unavailable": unavailable, "shrink": shrink}
    if action not in handlers:
        print(json.dumps({"error": f"acción desconocida: {action!r}"}))
        sys.exit(2)
    print(json.dumps(handlers[action](), ensure_ascii=False))
