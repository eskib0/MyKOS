"""Persistencia de MyKOS en el almacén de documentos del Gateway (fase 2 de la hoja de ruta).

El Gateway es el dueño de los datos: guarda cada documento (conversaciones, memoria e índice de memoria) y este módulo
se los pide y se los envía por HTTP interno, con un token que el Gateway pone en el entorno al lanzar el backend.

Modos (variable MYKOS_STORE_MODE, que fija el Gateway al arrancar este proceso):

  gateway  Los documentos viven en el almacén del Gateway. Si no responde se falla en voz alta: nunca se devuelve un
           documento vacío «de mentira» que luego se guardaría encima de los datos reales.
  file     Los ficheros de data/ de siempre (uso manual sin Gateway y vuelta atrás). Mismo comportamiento que antes.

Los documentos que se guardan: conversaciones, memoria, índice, permisos/auditoría y aprobaciones.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MODE = os.environ.get("MYKOS_STORE_MODE", "").strip().lower()
BASE_URL = os.environ.get("MYKOS_STORE_URL", "").strip().rstrip("/")
TOKEN = os.environ.get("MYKOS_STORE_TOKEN", "").strip()
ENABLED = MODE == "gateway" and bool(BASE_URL) and bool(TOKEN)

# El Gateway de esta máquina se queda a veces sin responder decenas de segundos: hay que tener paciencia.
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("MYKOS_STORE_TIMEOUT", "") or 90)
# Esperas entre reintentos ante conexión rechazada o 502/503/504 (arranque o reinicio del Gateway): ~35 s en total.
# MYKOS_STORE_RETRY_SCALE las multiplica (las pruebas la ponen a 0,01 para no esperar).
_RETRY_SCALE = float(os.environ.get("MYKOS_STORE_RETRY_SCALE", "") or 1)
RETRY_DELAYS = tuple(delay * _RETRY_SCALE for delay in (0.3, 0.6, 1.2, 2.5, 5.0, 10.0, 15.0))

_REVISIONS: dict[str, int] = {}


class StoreError(RuntimeError):
    """Error del almacén. Es un RuntimeError: la API lo devuelve como un 502 con el mensaje."""


class StoreUnavailable(StoreError):
    """El almacén del Gateway no responde."""


class StoreRejected(StoreError):
    """El almacén rechazó la petición (documento no válido, borrado masivo, token...)."""


def mode() -> str:
    return "gateway" if ENABLED else "file"


# --------------------------------------------------------------------------- HTTP

def _error_message(error: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8", errors="replace"))
        if isinstance(payload, dict):
            return str(payload.get("message") or payload.get("error") or error.reason)
    except (OSError, ValueError):
        pass
    return str(error.reason)


def _request(method: str, name: str = "", body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    url = f"{BASE_URL}/mykos-store/{name}" if name else f"{BASE_URL}/mykos-store/"
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"X-MyKOS-Store-Token": TOKEN, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    last: Exception | str = "sin respuesta"
    for delay in (0.0, *RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return response.status, payload if isinstance(payload, dict) else {}
        except urllib.error.HTTPError as error:
            if error.code == 404 and method == "GET":
                return 404, {}
            if error.code in {502, 503, 504}:
                last = f"HTTP {error.code}: {_error_message(error)}"
                continue
            raise StoreRejected(f"El almacén del Gateway rechazó la petición (HTTP {error.code}): {_error_message(error)}") from error
        except (urllib.error.URLError, OSError, ValueError) as error:  # incluye rechazos de conexión y tiempos de espera
            last = error
    raise StoreUnavailable(f"El almacén del Gateway no responde ({BASE_URL}): {last}")


# --------------------------------------------------------------------------- ficheros (modo file)

def _file_load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _file_save(path: Path, data: Any, indent: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=indent)
    temporary.replace(path)


# --------------------------------------------------------------------------- API

def load_document(name: str, *, legacy_file: Path, default: Any = None) -> Any:
    """Devuelve el contenido del documento, o `default` si todavía no existe.

    En modo file lanza las mismas excepciones que antes (OSError, UnicodeDecodeError, JSONDecodeError) para que cada
    llamador conserve su manejo. En modo gateway lanza StoreError si el almacén no responde.
    """
    if not ENABLED:
        return _file_load(legacy_file, default)
    status, payload = _request("GET", name)
    if status == 404:
        return default
    revision = payload.get("revision")
    if isinstance(revision, int):
        _REVISIONS[name] = revision
    return payload.get("data", default)


def save_document(name: str, data: Any, *, legacy_file: Path, indent: int | None = 2, source: str = "backend") -> int:
    """Guarda el documento completo y devuelve su revisión (0 en modo file)."""
    if not ENABLED:
        _file_save(legacy_file, data, indent)
        return 0
    body: dict[str, Any] = {"data": data, "source": source}
    known = _REVISIONS.get(name)
    if known is not None:
        body["expectedRevision"] = known
    _status, payload = _request("PUT", name, body)
    revision = payload.get("revision")
    if isinstance(revision, int):
        _REVISIONS[name] = revision
    if payload.get("conflict"):
        print(f"Aviso: el documento «{name}» había cambiado desde la última lectura (revisión {known} → {payload.get('previousRevision')}); se guardó igualmente.")
    return revision if isinstance(revision, int) else 0


def store_info() -> dict[str, dict[str, Any]] | None:
    """Estado de los documentos del almacén (revisión, tamaño, recuento), o None en modo file o si no responde."""
    if not ENABLED:
        return None
    try:
        _status, payload = _request("GET")
    except StoreError:
        return None
    docs = payload.get("docs")
    if not isinstance(docs, list):
        return None
    return {str(item.get("name")): item for item in docs if isinstance(item, dict)}
