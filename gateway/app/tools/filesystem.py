"""Operaciones de sistema de archivos, fichas de investigación y edición segura de MyKOS.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .base import (
    ALLOWED_TEXT_EXTENSIONS,
    MAX_LIST_ENTRIES,
    MAX_PATH_SEARCH_ENTRIES,
    MAX_READ_BYTES,
    MAX_RESEARCH_KEY_POINTS,
    MAX_RESEARCH_QUERY_CHARS,
    MAX_RESEARCH_SOURCES,
    MAX_RESEARCH_SUMMARY_CHARS,
    MAX_RESEARCH_TITLE_CHARS,
    MAX_SEARCH_FILE_BYTES,
    MAX_SEARCH_FILES,
    MAX_SEARCH_RESULTS,
    MAX_WRITE_BYTES,
    ToolError,
    _is_ignored,
    _relative_label,
    _resolve_project_path,
)


def _list_project_files(arguments: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path, directory = _resolve_project_path(
        arguments.get("root", "mykos"), arguments.get("path", "")
    )
    if not directory.is_dir():
        raise ToolError(f"No existe una carpeta en '{arguments.get('path', '')}'.")

    recursive = bool(arguments.get("recursive", False))
    iterator = directory.rglob("*") if recursive else directory.iterdir()
    items: list[dict[str, Any]] = []
    truncated = False
    for item in sorted(iterator, key=lambda value: (not value.is_dir(), value.name.lower())):
        if item.is_symlink() or _is_ignored(item, root_path):
            continue
        if len(items) >= MAX_LIST_ENTRIES:
            truncated = True
            break
        entry: dict[str, Any] = {
            "path": _relative_label(item, root_path),
            "type": "directory" if item.is_dir() else "file",
        }
        if item.is_file():
            try:
                entry["size"] = item.stat().st_size
            except OSError:
                entry["size"] = None
        items.append(entry)

    return {
        "ok": True,
        "root": root_name,
        "path": _relative_label(directory, root_path),
        "recursive": recursive,
        "items": items,
        "truncated": truncated,
    }


def _read_project_file(arguments: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path, file_path = _resolve_project_path(
        arguments.get("root", "mykos"), arguments.get("path"), allow_root=False
    )
    if not file_path.is_file():
        raise ToolError(f"No existe el archivo '{arguments.get('path', '')}'.")
    if file_path.suffix.lower() not in ALLOWED_TEXT_EXTENSIONS:
        raise ToolError("Por seguridad, esta herramienta solo lee archivos de texto permitidos.")

    max_range_bytes = 5_000_000
    max_range_lines = 400
    max_range_chars = 30_000

    try:
        size = file_path.stat().st_size
    except OSError as error:
        raise ToolError("No se puede consultar el archivo.") from error
    if size > max_range_bytes:
        raise ToolError(f"El archivo supera el limite de {max_range_bytes} bytes.")

    try:
        raw = file_path.read_bytes()
        if b"\x00" in raw:
            raise ToolError("El archivo parece binario y no se leera como texto.")
        content = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ToolError("El archivo no esta codificado como UTF-8.") from error
    except OSError as error:
        raise ToolError("No se puede leer el archivo.") from error

    all_lines = content.splitlines()
    total_lines = len(all_lines)

    def _line_arg(name: str) -> int | None:
        value = arguments.get(name)
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as error:
            raise ToolError(f"{name} debe ser un numero entero.") from error

    start_arg = _line_arg("start_line")
    end_arg = _line_arg("end_line")
    ranged = start_arg is not None or end_arg is not None or size > MAX_READ_BYTES
    label = _relative_label(file_path, root_path)
    if not ranged:
        return {
            "ok": True,
            "root": root_name,
            "path": label,
            "size": size,
            "total_lines": total_lines,
            "content": content,
        }

    start = max(1, start_arg or 1)
    end = end_arg if end_arg is not None else start + max_range_lines - 1
    end = min(end, total_lines, start + max_range_lines - 1)
    chunk: list[str] = []
    used = 0
    last = start - 1
    for number in range(start, end + 1):
        line = all_lines[number - 1]
        if chunk and used + len(line) + 1 > max_range_chars:
            break
        chunk.append(line)
        used += len(line) + 1
        last = number
    return {
        "ok": True,
        "root": root_name,
        "path": label,
        "size": size,
        "total_lines": total_lines,
        "start_line": start,
        "end_line": last,
        "has_more": last < total_lines,
        "next_start_line": last + 1 if last < total_lines else None,
        "content": "\n".join(chunk),
    }


def _search_project_files(arguments: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path, directory = _resolve_project_path(
        arguments.get("root", "mykos"), arguments.get("path", "")
    )
    if not directory.is_dir():
        raise ToolError(f"No existe una carpeta en '{arguments.get('path', '')}'.")

    raw_query = arguments.get("query")
    if not isinstance(raw_query, str) or not raw_query.strip():
        raise ToolError("Debes indicar un texto que buscar.")
    query = raw_query.strip()
    if len(query) > 200:
        raise ToolError("La búsqueda no puede superar 200 caracteres.")

    try:
        max_results = int(arguments.get("max_results", MAX_SEARCH_RESULTS))
    except (TypeError, ValueError) as error:
        raise ToolError("max_results debe ser un número entero.") from error
    max_results = max(1, min(max_results, MAX_SEARCH_RESULTS))
    case_sensitive = bool(arguments.get("case_sensitive", False))
    needle = query if case_sensitive else query.casefold()
    matches: list[dict[str, Any]] = []
    files_scanned = 0
    truncated = False

    for current, dirnames, filenames in os.walk(directory, followlinks=False):
        current_path = Path(current)
        dirnames[:] = sorted(
            (
                name for name in dirnames
                if not (current_path / name).is_symlink()
                and not _is_ignored(current_path / name, root_path)
            ),
            key=str.casefold,
        )
        for filename in sorted(filenames, key=str.casefold):
            if len(matches) >= max_results or files_scanned >= MAX_SEARCH_FILES:
                truncated = True
                break
            file_path = current_path / filename
            if file_path.is_symlink() or file_path.suffix.lower() not in ALLOWED_TEXT_EXTENSIONS:
                continue
            if _is_ignored(file_path, root_path):
                continue
            try:
                if file_path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                    continue
                raw = file_path.read_bytes()
                if b"\x00" in raw:
                    continue
                content = raw.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            files_scanned += 1
            for line_number, line in enumerate(content.splitlines(), start=1):
                haystack = line if case_sensitive else line.casefold()
                if needle not in haystack:
                    continue
                matches.append(
                    {
                        "path": _relative_label(file_path, root_path),
                        "line": line_number,
                        "snippet": line.strip()[:240],
                    }
                )
                if len(matches) >= max_results:
                    truncated = True
                    break
        if truncated:
            break

    return {
        "ok": True,
        "root": root_name,
        "path": _relative_label(directory, root_path),
        "query": query,
        "case_sensitive": case_sensitive,
        "files_scanned": files_scanned,
        "matches": matches,
        "truncated": truncated,
    }


def _find_project_paths(arguments: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path, directory = _resolve_project_path(
        arguments.get("root", "mykos"), arguments.get("path", "")
    )
    if not directory.is_dir():
        raise ToolError(f"No existe una carpeta en '{arguments.get('path', '')}'.")
    raw_query = arguments.get("query")
    if not isinstance(raw_query, str) or not raw_query.strip():
        raise ToolError("Debes indicar parte del nombre que buscas.")
    query = raw_query.strip()
    if len(query) > 200:
        raise ToolError("La búsqueda no puede superar 200 caracteres.")
    try:
        max_results = int(arguments.get("max_results", MAX_SEARCH_RESULTS))
    except (TypeError, ValueError) as error:
        raise ToolError("max_results debe ser un número entero.") from error
    max_results = max(1, min(max_results, MAX_SEARCH_RESULTS))
    needle = query.casefold()
    matches: list[dict[str, str]] = []
    entries_scanned = 0
    truncated = False
    for current, dirnames, filenames in os.walk(directory, followlinks=False):
        current_path = Path(current)
        clean_dirs: list[str] = []
        for name in sorted(dirnames, key=str.casefold):
            candidate = current_path / name
            if candidate.is_symlink() or _is_ignored(candidate, root_path):
                continue
            entries_scanned += 1
            if needle in name.casefold():
                matches.append({"path": _relative_label(candidate, root_path), "type": "directory"})
                if len(matches) >= max_results:
                    truncated = True
                    break
            if entries_scanned >= MAX_PATH_SEARCH_ENTRIES:
                truncated = True
                break
            clean_dirs.append(name)
        dirnames[:] = clean_dirs
        if truncated:
            break
        for name in sorted(filenames, key=str.casefold):
            candidate = current_path / name
            if candidate.is_symlink() or _is_ignored(candidate, root_path):
                continue
            entries_scanned += 1
            if needle in name.casefold():
                matches.append({"path": _relative_label(candidate, root_path), "type": "file"})
                if len(matches) >= max_results:
                    truncated = True
                    break
            if entries_scanned >= MAX_PATH_SEARCH_ENTRIES:
                truncated = True
                break
        if truncated:
            break
    return {
        "ok": True,
        "root": root_name,
        "path": _relative_label(directory, root_path),
        "query": query,
        "matches": matches,
        "entries_scanned": entries_scanned,
        "truncated": truncated,
    }


def _prepare_write_project_file(arguments: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path, file_path = _resolve_project_path(
        arguments.get("root", "mykos"), arguments.get("path"), allow_root=False
    )
    if file_path.suffix.lower() not in ALLOWED_TEXT_EXTENSIONS:
        raise ToolError("Por seguridad, solo se pueden escribir extensiones de texto permitidas.")
    if file_path.is_dir():
        raise ToolError("La ruta indicada es una carpeta, no un archivo.")
    if file_path.is_symlink():
        raise ToolError("No se escribirá sobre enlaces simbólicos.")
    if not file_path.parent.is_dir():
        raise ToolError("La carpeta de destino no existe; no se crearán carpetas automáticamente.")

    content = arguments.get("content")
    if not isinstance(content, str):
        raise ToolError("El contenido debe ser texto.")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        raise ToolError(f"El contenido supera el límite de {MAX_WRITE_BYTES} bytes.")
    if b"\x00" in encoded:
        raise ToolError("El contenido contiene un byte nulo y no se escribirá.")

    overwrite = bool(arguments.get("overwrite", False))
    exists = file_path.exists()
    if exists:
        try:
            old_content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ToolError("No se pudo leer el archivo existente para sobrescribirlo.") from error
        if old_content == content:
            raise ToolError("El contenido propuesto es idéntico al archivo actual.")
        return {
            "kind": "edit_file",
            "root": root_name,
            "path": _relative_label(file_path, root_path),
            "content": content,
            "old_text": old_content,
            "new_text": content,
            "expected_sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
            "summary": f"Reescribir archivo existente ({len(old_content)} -> {len(content)} caracteres).",
        }

    return {
        "kind": "write_file",
        "root": root_name,
        "path": _relative_label(file_path, root_path),
        "content": content,
        "overwrite": overwrite,
        "existed_at_request": exists,
    }


def _prepare_edit_project_file(arguments: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path, file_path = _resolve_project_path(
        arguments.get("root", "mykos"), arguments.get("path"), allow_root=False
    )
    if file_path.suffix.lower() not in ALLOWED_TEXT_EXTENSIONS:
        raise ToolError("Por seguridad, solo se pueden editar extensiones de texto permitidas.")
    if not file_path.exists() or file_path.is_dir():
        raise ToolError("La edición requiere un archivo existente.")
    if file_path.is_symlink():
        raise ToolError("No se editarán enlaces simbólicos.")

    old_text = arguments.get("old_text")
    new_text = arguments.get("new_text")
    if not isinstance(old_text, str) or not old_text:
        raise ToolError("old_text debe ser un fragmento exacto y no vacío del archivo leído.")
    if not isinstance(new_text, str):
        raise ToolError("new_text debe ser texto; puede estar vacío solo para borrar el fragmento indicado.")
    if old_text == new_text:
        raise ToolError("La edición no cambia nada.")
    if len(old_text.encode("utf-8")) > MAX_WRITE_BYTES or len(new_text.encode("utf-8")) > MAX_WRITE_BYTES:
        raise ToolError(f"El fragmento de edición supera el límite de {MAX_WRITE_BYTES} bytes.")
    if "\x00" in old_text or "\x00" in new_text:
        raise ToolError("La edición contiene un byte nulo y no se realizará.")

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ToolError("No se pudo leer el archivo de texto que se quiere editar.") from error
    occurrences = content.count(old_text)
    if occurrences != 1:
        raise ToolError(
            "El fragmento a sustituir debe aparecer exactamente una vez en el archivo "
            f"actual (ahora aparece {occurrences}). Léelo de nuevo y usa más contexto."
        )
    updated = content.replace(old_text, new_text, 1)
    encoded = updated.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        raise ToolError(f"El archivo resultante supera el límite de {MAX_WRITE_BYTES} bytes.")

    return {
        "kind": "edit_file",
        "root": root_name,
        "path": _relative_label(file_path, root_path),
        "content": updated,
        "old_text": old_text,
        "new_text": new_text,
        "expected_sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
        "summary": f"Sustituir un fragmento único de {len(old_text)} caracteres por otro de {len(new_text)} caracteres.",
    }


def _research_slug(title: str) -> str:
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", plain).strip("-").lower()
    return slug[:90] or "investigacion"


def _prepare_save_research_note(arguments: dict[str, Any]) -> dict[str, Any]:
    title = arguments.get("title")
    query = arguments.get("query")
    summary = arguments.get("summary")
    if not isinstance(title, str) or not title.strip():
        raise ToolError("La ficha necesita un título.")
    if len(title.strip()) > MAX_RESEARCH_TITLE_CHARS:
        raise ToolError(f"El título supera el límite de {MAX_RESEARCH_TITLE_CHARS} caracteres.")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("La ficha necesita indicar qué se investigó.")
    if len(query.strip()) > MAX_RESEARCH_QUERY_CHARS:
        raise ToolError(f"La consulta supera el límite de {MAX_RESEARCH_QUERY_CHARS} caracteres.")
    if not isinstance(summary, str) or not summary.strip():
        raise ToolError("La ficha necesita un resumen.")
    if len(summary.encode("utf-8")) > MAX_RESEARCH_SUMMARY_CHARS:
        raise ToolError(f"El resumen supera el límite de {MAX_RESEARCH_SUMMARY_CHARS} bytes.")

    raw_points = arguments.get("key_points", [])
    if not isinstance(raw_points, list):
        raise ToolError("Los puntos principales deben ser una lista.")
    points = [str(point).strip() for point in raw_points if isinstance(point, str) and point.strip()]
    points = points[:MAX_RESEARCH_KEY_POINTS]

    raw_sources = arguments.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ToolError("La ficha necesita al menos una fuente.")
    sources: list[dict[str, str]] = []
    for raw_source in raw_sources[:MAX_RESEARCH_SOURCES]:
        if not isinstance(raw_source, dict):
            continue
        source_title = str(raw_source.get("title", "")).strip()
        source_url = str(raw_source.get("url", "")).strip()
        source_note = str(raw_source.get("note", "")).strip()
        parsed = urlparse(source_url)
        if not source_title or parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            continue
        if parsed.username or parsed.password:
            continue
        sources.append({"title": source_title[:240], "url": source_url[:2_000], "note": source_note[:500]})
    if not sources:
        raise ToolError("No hay fuentes públicas válidas para guardar en la ficha.")

    captured = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        f"# {title.strip()}",
        "",
        f"- **Consulta:** {query.strip()}",
        f"- **Fecha de consulta:** {captured}",
        "",
        "## Resumen",
        "",
        summary.strip(),
    ]
    if points:
        lines.extend(["", "## Puntos principales", ""])
        lines.extend(f"- {point}" for point in points)
    lines.extend(["", "## Fuentes", ""])
    for source in sources:
        line = f"- [{source['title']}]({source['url']})"
        if source["note"]:
            line += f" — {source['note']}"
        lines.append(line)
    content = "\n".join(lines).strip() + "\n"
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        raise ToolError(f"La ficha supera el límite de {MAX_WRITE_BYTES} bytes.")

    root = arguments.get("root", "workspace")
    raw_path = arguments.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raw_path = f"research/{_research_slug(title)}.md"
    else:
        raw_path = raw_path.strip()
        if raw_path.lower().startswith("workspace/"):
            raw_path = raw_path[len("workspace/"):]
    if not raw_path.lower().endswith(".md"):
        raw_path = f"{raw_path}.md"
    root_name, root_path, file_path = _resolve_project_path(root, raw_path, allow_root=False)
    if file_path.is_symlink() or file_path.is_dir():
        raise ToolError("La ruta de la ficha no es un archivo válido.")
    if file_path.exists():
        raise ToolError("Ya existe una ficha con esa ruta; indica otra ruta para no sobrescribirla.")
    return {
        "kind": "research_note",
        "root": root_name,
        "path": _relative_label(file_path, root_path),
        "content": content,
        "title": title.strip(),
        "query": query.strip(),
        "sources_count": len(sources),
        "overwrite": False,
    }


def _execute_write_file(action: dict[str, Any], *, allow_existing_edit: bool = False) -> dict[str, Any]:
    root_name, root_path, file_path = _resolve_project_path(
        action.get("root"), action.get("path"), allow_root=False
    )
    if file_path.suffix.lower() not in ALLOWED_TEXT_EXTENSIONS:
        raise ToolError("La extensión ya no está permitida.")
    if file_path.is_symlink() or file_path.is_dir() or not file_path.parent.is_dir():
        raise ToolError("El destino ya no es un archivo normal dentro de una carpeta válida.")
    content = action.get("content")
    if not isinstance(content, str):
        raise ToolError("La acción no contiene contenido de texto válido.")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES or b"\x00" in encoded:
        raise ToolError("El contenido ya no cumple los límites de seguridad.")
    overwrite = bool(action.get("overwrite", False))
    existed = file_path.exists()
    if existed and not allow_existing_edit:
        raise ToolError("Las escrituras genéricas no pueden reemplazar archivos existentes; prepara una edición acotada.")
    if existed and not overwrite and not allow_existing_edit:
        raise ToolError("El archivo apareció después de la aprobación y no se permite sobrescribirlo.")
    expected_sha256 = action.get("expected_sha256")
    if existed and allow_existing_edit and (not isinstance(expected_sha256, str) or not expected_sha256):
        raise ToolError("La edición no incluye la versión original verificada del archivo.")
    if isinstance(expected_sha256, str) and expected_sha256:
        if not existed:
            raise ToolError("El archivo ya no existe desde que se preparó la aprobación.")
        actual_sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ToolError("El archivo cambió desde que se preparó la aprobación; léelo de nuevo antes de sobrescribirlo.")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{file_path.name}.",
            suffix=".mykos.tmp",
            dir=file_path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, file_path)
        temporary_path = None
        written = file_path.read_bytes()
        if written != encoded:
            raise ToolError("La verificación posterior a la escritura no coincide.")
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    return {
        "ok": True,
        "action": "write_file",
        "root": root_name,
        "path": _relative_label(file_path, root_path),
        "bytes": len(encoded),
        "overwritten": existed,
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _execute_edit_file(action: dict[str, Any]) -> dict[str, Any]:
    result = _execute_write_file(action, allow_existing_edit=True)
    result["action"] = "edit_file"
    return result


def _execute_research_note(action: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path, file_path = _resolve_project_path(
        action.get("root"), action.get("path"), allow_root=False
    )
    parent = file_path.parent
    current = parent
    while current != root_path:
        if current.exists() and current.is_symlink():
            raise ToolError("La carpeta de destino contiene un enlace simbólico.")
        if current == current.parent:
            raise ToolError("La carpeta de destino queda fuera de la raíz autorizada.")
        current = current.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ToolError(f"No se pudo crear la carpeta de investigación: {error}") from error
    write_action = dict(action)
    write_action["kind"] = "write_file"
    result = _execute_write_file(write_action)
    return {
        "ok": bool(result.get("ok")),
        "action": "research_note",
        "root": root_name,
        "path": _relative_label(file_path, root_path),
        "title": action.get("title", ""),
        "sources_count": action.get("sources_count", 0),
        "bytes": result.get("bytes", 0),
        "sha256": result.get("sha256", ""),
    }
