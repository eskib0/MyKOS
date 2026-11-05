"""Lectura de documentos complejos (PDF, Office, imágenes con OCR) en MyKOS.
"""
from __future__ import annotations

import base64
import io
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .base import (
    ALLOWED_IMAGE_EXTENSIONS,
    MAX_DOCUMENT_TEXT_CHARS,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_OCR_CHARS,
    MAX_OFFICE_BYTES,
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    MAX_SPREADSHEET_ROWS,
    ToolError,
    _relative_label,
    _resolve_project_path,
)

def _resolve_read_file(
    arguments: dict[str, Any],
    allowed_extensions: set[str],
    description: str,
) -> tuple[str, Path, Path]:
    root_name, root_path, file_path = _resolve_project_path(
        arguments.get("root", "mykos"), arguments.get("path"), allow_root=False
    )
    raw_path = arguments.get("path")
    if isinstance(raw_path, str) and (root_path / Path(raw_path)).is_symlink():
        raise ToolError("No se leerán enlaces simbólicos.")
    if file_path.suffix.lower() not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise ToolError(f"{description} requiere una extensión permitida: {allowed}.")
    if not file_path.is_file():
        raise ToolError(f"No existe un archivo normal en '{_relative_label(file_path, root_path)}'.")
    return root_name, root_path, file_path


def _read_pdf(arguments: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path, file_path = _resolve_read_file(arguments, {".pdf"}, "El lector PDF")
    size = file_path.stat().st_size
    if size > MAX_PDF_BYTES:
        raise ToolError(f"El PDF supera el límite de {MAX_PDF_BYTES // (1024 * 1024)} MB.")
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as error:
        raise ToolError("Falta la dependencia pypdf para leer PDF.") from error

    try:
        reader = PdfReader(str(file_path), strict=False)
        if reader.is_encrypted:
            try:
                decrypted = reader.decrypt("")
            except Exception as error:  # pypdf exposes different encryption errors by version
                raise ToolError("El PDF está cifrado y no se puede abrir sin contraseña.") from error
            if not decrypted:
                raise ToolError("El PDF está cifrado y no se puede abrir sin contraseña.")
        total_pages = len(reader.pages)
    except ToolError:
        raise
    except Exception as error:
        raise ToolError(f"No se pudo abrir el PDF: {error}") from error

    if total_pages == 0:
        return {
            "ok": True,
            "action": "read_pdf",
            "root": root_name,
            "path": _relative_label(file_path, root_path),
            "size": size,
            "pages": 0,
            "start_page": 1,
            "page_count": 0,
            "text": "",
            "truncated": False,
        }

    try:
        start_page = int(arguments.get("start_page", 1))
        max_pages = int(arguments.get("max_pages", min(20, MAX_PDF_PAGES)))
    except (TypeError, ValueError) as error:
        raise ToolError("start_page y max_pages deben ser números enteros.") from error
    if start_page < 1 or start_page > total_pages:
        raise ToolError(f"start_page debe estar entre 1 y {total_pages}.")
    max_pages = max(1, min(max_pages, MAX_PDF_PAGES))
    end_page = min(total_pages, start_page - 1 + max_pages)

    sections: list[str] = []
    for page_index in range(start_page - 1, end_page):
        try:
            page_text = reader.pages[page_index].extract_text() or ""
        except Exception as error:
            page_text = f"[No se pudo extraer el texto de esta página: {error}]"
        sections.append(f"--- Página {page_index + 1} ---\n{page_text.strip()}".strip())
    text = "\n\n".join(sections)
    return {
        "ok": True,
        "action": "read_pdf",
        "root": root_name,
        "path": _relative_label(file_path, root_path),
        "size": size,
        "pages": total_pages,
        "start_page": start_page,
        "page_count": end_page - start_page + 1,
        "text": text[:MAX_DOCUMENT_TEXT_CHARS],
        "truncated": len(text) > MAX_DOCUMENT_TEXT_CHARS or end_page < total_pages,
    }


def _image_mime_type(image_format: str, suffix: str) -> str:
    formats = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
        "GIF": "image/gif",
        "BMP": "image/bmp",
        "TIFF": "image/tiff",
    }
    return formats.get(image_format.upper(), {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(suffix.lower(), "application/octet-stream"))


def _run_image_ocr(file_path: Path, max_chars: int) -> dict[str, Any]:
    tesseract = shutil.which("tesseract.exe") or shutil.which("tesseract")
    if not tesseract:
        return {"available": False, "performed": False, "text": "", "reason": "Tesseract no está disponible."}
    try:
        languages_result = subprocess.run(
            [tesseract, "--list-langs"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        languages = {
            line.strip()
            for line in languages_result.stdout.splitlines()
            if line.strip() and not line.lower().startswith("list of available")
        }
        language = "spa+eng" if {"spa", "eng"}.issubset(languages) else (
            "spa" if "spa" in languages else "eng" if "eng" in languages else ""
        )
        command = [tesseract, str(file_path), "stdout", "--psm", "6"]
        if language:
            command.extend(["-l", language])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {"available": True, "performed": False, "text": "", "reason": "El OCR superó 30 segundos."}
    except (OSError, subprocess.SubprocessError) as error:
        return {"available": True, "performed": False, "text": "", "reason": f"No se pudo iniciar Tesseract: {error}"}

    if completed.returncode != 0:
        return {
            "available": True,
            "performed": False,
            "text": "",
            "reason": completed.stderr.strip()[:300] or "Tesseract devolvió un error.",
        }
    text = completed.stdout.strip()
    return {
        "available": True,
        "performed": True,
        "text": text[:max_chars],
        "truncated": len(text) > max_chars,
    }


def _read_image(arguments: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path, file_path = _resolve_read_file(
        arguments, ALLOWED_IMAGE_EXTENSIONS, "El lector de imágenes"
    )
    size = file_path.stat().st_size
    if size > MAX_IMAGE_BYTES:
        raise ToolError(f"La imagen supera el límite de {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
    try:
        from PIL import Image  # type: ignore
    except ImportError as error:
        raise ToolError("Falta Pillow para leer imágenes.") from error

    try:
        with Image.open(file_path) as image:
            image.verify()
        with Image.open(file_path) as image:
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ToolError(f"La imagen supera el límite de {MAX_IMAGE_PIXELS:,} píxeles.")
            image_format = str(image.format or file_path.suffix.lstrip(".")).upper()
            mode = str(image.mode)
            frames = int(getattr(image, "n_frames", 1))
            if file_path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                image_bytes = file_path.read_bytes()
                mime_type = _image_mime_type(image_format, file_path.suffix)
            else:
                buffer = io.BytesIO()
                image.convert("RGBA" if "A" in image.getbands() else "RGB").save(buffer, format="PNG")
                image_bytes = buffer.getvalue()
                mime_type = "image/png"
    except ToolError:
        raise
    except Exception as error:
        raise ToolError(f"No se pudo abrir la imagen: {error}") from error

    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ToolError("La imagen convertida supera el límite permitido.")
    try:
        max_ocr_chars = int(arguments.get("max_ocr_chars", MAX_OCR_CHARS))
    except (TypeError, ValueError) as error:
        raise ToolError("max_ocr_chars debe ser un número entero.") from error
    max_ocr_chars = max(500, min(max_ocr_chars, MAX_OCR_CHARS))
    ocr = _run_image_ocr(file_path, max_ocr_chars) if arguments.get("ocr", True) else {
        "available": False,
        "performed": False,
        "text": "",
        "reason": "OCR desactivado para esta lectura.",
    }
    return {
        "ok": True,
        "action": "read_image",
        "root": root_name,
        "path": _relative_label(file_path, root_path),
        "size": size,
        "format": image_format,
        "mime_type": mime_type,
        "width": width,
        "height": height,
        "mode": mode,
        "frames": frames,
        "ocr": ocr,
        "vision_ready": True,
        "_image_base64": base64.b64encode(image_bytes).decode("ascii"),
        "_image_mime_type": mime_type,
    }


def _read_document(arguments: dict[str, Any]) -> dict[str, Any]:
    allowed_extensions = {".docx", ".xlsx"}
    root_name, root_path, file_path = _resolve_read_file(
        arguments, allowed_extensions, "El lector de documentos"
    )
    size = file_path.stat().st_size
    if size > MAX_OFFICE_BYTES:
        raise ToolError(f"El documento supera el límite de {MAX_OFFICE_BYTES // (1024 * 1024)} MB.")

    suffix = file_path.suffix.lower()
    truncated = False
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(file_path) as archive:
                raw_xml = archive.read("word/document.xml")
            document = ET.fromstring(raw_xml)
        except (KeyError, OSError, zipfile.BadZipFile, ET.ParseError) as error:
            raise ToolError(f"No se pudo abrir el documento DOCX: {error}") from error

        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs: list[str] = []
        for paragraph in document.iter(f"{namespace}p"):
            value = "".join((node.text or "") for node in paragraph.iter(f"{namespace}t"))
            if value.strip():
                paragraphs.append(value.strip())
        text = "\n".join(paragraphs)
    else:
        try:
            from openpyxl import load_workbook  # type: ignore
        except ImportError as error:
            raise ToolError("Falta openpyxl para leer archivos XLSX.") from error

        lines: list[str] = []
        rows_read = 0
        workbook = None
        try:
            workbook = load_workbook(file_path, read_only=True, data_only=True)
            for worksheet in workbook.worksheets:
                lines.append(f"--- Hoja: {worksheet.title} ---")
                for row in worksheet.iter_rows(values_only=True):
                    values = ["" if value is None else str(value) for value in row]
                    if not any(value.strip() for value in values):
                        continue
                    lines.append("\t".join(values).rstrip())
                    rows_read += 1
                    if rows_read >= MAX_SPREADSHEET_ROWS:
                        truncated = True
                        break
                if truncated:
                    break
            text = "\n".join(lines)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            raise ToolError(f"No se pudo abrir el documento XLSX: {error}") from error
        finally:
            if workbook is not None:
                workbook.close()

    if len(text) > MAX_DOCUMENT_TEXT_CHARS:
        text = text[:MAX_DOCUMENT_TEXT_CHARS]
        truncated = True
    return {
        "ok": True,
        "action": "read_document",
        "root": root_name,
        "path": _relative_label(file_path, root_path),
        "size": size,
        "format": suffix.lstrip("."),
        "text": text,
        "truncated": truncated,
    }


