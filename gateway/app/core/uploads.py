"""Sub-módulo de gestión de cargas de archivos y temporales de MyKOS.

Maneja la recepción de formularios multipart (PDFs, imágenes), almacenamiento temporal,
validación de extensiones y tamaños, y purga periódica.
"""

from __future__ import annotations

import mimetypes
import os
import threading
import time
import uuid
from email.parser import BytesParser
from email.policy import default as email_default_policy
from pathlib import Path
from typing import Any, Callable

ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_UPLOAD_FILES = 8
MAX_UPLOAD_REQUEST_BYTES = 32 * 1024 * 1024
UPLOAD_RETENTION_SECONDS = 3600


def cleanup_uploads(
    upload_dir: Path,
    uploads: dict[str, dict[str, Any]],
    uploads_lock: threading.Lock,
    retention_seconds: int = UPLOAD_RETENTION_SECONDS,
    allowed_extensions: set[str] = ALLOWED_UPLOAD_EXTENSIONS,
) -> None:
    """Elimina adjuntos temporales expirados tanto de memoria como de disco."""
    cutoff = time.time() - retention_seconds
    upload_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        upload_dir.chmod(0o700)
    except OSError:
        pass
    with uploads_lock:
        for attachment_id, metadata in list(uploads.items()):
            path = Path(str(metadata.get("path", "")))
            try:
                old = path.stat().st_mtime < cutoff
            except OSError:
                old = True
            if old:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                uploads.pop(attachment_id, None)
        # Limpia temporales que sobrevivieron a un reinicio y aún no están registrados en memoria
        for path in upload_dir.iterdir():
            if not path.is_file() or path.suffix.casefold() not in allowed_extensions:
                continue
            try:
                old = path.stat().st_mtime < cutoff
            except OSError:
                continue
            if old:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def process_multipart_uploads(
    content_type: str,
    body: bytes,
    upload_dir: Path,
    uploads: dict[str, dict[str, Any]],
    uploads_lock: threading.Lock,
    utc_now_fn: Callable[[], str],
    api_error_cls: type[Exception],
    retention_seconds: int = UPLOAD_RETENTION_SECONDS,
    max_request_bytes: int = MAX_UPLOAD_REQUEST_BYTES,
    max_upload_files: int = MAX_UPLOAD_FILES,
    allowed_extensions: set[str] = ALLOWED_UPLOAD_EXTENSIONS,
) -> list[dict[str, Any]]:
    """Valida, almacena y registra archivos multipart adjuntos."""
    if len(body) > max_request_bytes:
        raise api_error_cls("La carga supera el límite de 32 MB.")
    try:
        raw_message = (
            b"Content-Type: " + content_type.encode("latin-1", errors="replace")
            + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        )
        message = BytesParser(policy=email_default_policy).parsebytes(raw_message)
    except Exception as error:
        raise api_error_cls(f"No se pudo leer la carga de archivos: {error}") from error
    if not message.is_multipart():
        raise api_error_cls("La carga no tiene un formulario multipart válido.")
    parts = [part for part in message.iter_parts() if part.get_filename()]
    if not parts or len(parts) > max_upload_files:
        raise api_error_cls(f"Adjunta entre 1 y {max_upload_files} archivos.")

    cleanup_uploads(upload_dir, uploads, uploads_lock, retention_seconds, allowed_extensions)
    created: list[dict[str, Any]] = []
    try:
        for part in parts:
            original_name = Path(str(part.get_filename())).name
            suffix = Path(original_name).suffix.casefold()
            if suffix not in allowed_extensions:
                raise api_error_cls("Solo se admiten PDF e imágenes.")
            data = part.get_payload(decode=True) or b""
            limit = 30 * 1024 * 1024 if suffix == ".pdf" else 12 * 1024 * 1024
            if not data or len(data) > limit:
                raise api_error_cls(f"El archivo {original_name} está vacío o supera su límite de tamaño.")
            attachment_id = uuid.uuid4().hex
            stored_path = upload_dir / f"{attachment_id}{suffix}"
            # Creación atómica con permisos 0600 desde open() para eliminar ventanas de acceso (TOCTOU)
            fd = os.open(str(stored_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            kind = "pdf" if suffix == ".pdf" else "image"
            metadata = {
                "id": attachment_id,
                "name": original_name,
                "size": len(data),
                "mime_type": mimetypes.guess_type(original_name)[0] or ("application/pdf" if kind == "pdf" else "image/*"),
                "kind": kind,
                "created_at": utc_now_fn(),
                "path": stored_path,
                "relative_path": f"data/uploads/{stored_path.name}",
            }
            with uploads_lock:
                uploads[attachment_id] = metadata
            created.append({key: value for key, value in metadata.items() if key not in {"path", "relative_path"}})
    except Exception:
        for item in created:
            attachment_id = str(item.get("id", ""))
            with uploads_lock:
                metadata = uploads.pop(attachment_id, None)
            if metadata:
                try:
                    Path(metadata["path"]).unlink(missing_ok=True)
                except OSError:
                    pass
        raise
    return created
