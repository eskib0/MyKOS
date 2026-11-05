from __future__ import annotations

import base64
import ipaddress
import io
import json
import hashlib
from html.parser import HTMLParser
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import gateway_store
from embedding_memory import (
    remove as remove_memory_embedding,
    search as semantic_memory_search,
    status as memory_embedding_status,
    upsert as upsert_memory_embedding,
)
from browser import BrowserError, browser_close, browser_open, browser_snapshot
from automations import (
    AutomationError,
    create_approved,
    delete_approved,
    list_automations,
    list_events,
    prepare_create,
    prepare_delete,
)
from subagents import SubagentError, list_jobs, prepare_spawn, spawn_approved
from management import local_status
from media import (
    MediaError,
    generate_image_approved,
    generate_video_approved,
    list_media,
    media_status,
    prepare_generate_image,
    prepare_generate_video,
    prepare_text_to_speech,
    text_to_speech_approved,
)
from nodes import NodeError, list_nodes, pair_node_approved, prepare_pair_node, prepare_revoke_node, revoke_node_approved
from rea import ReaError, rea_analyze_javascript, rea_call_tool, rea_inspect_binary, rea_list_tools, rea_status, resolve_rea_target


PROJECT_ROOT = Path(__file__).resolve().parent
ALLOWED_ROOTS_FILE = PROJECT_ROOT / "config" / "allowed_roots.json"
MEMORY_FILE = PROJECT_ROOT / "data" / "memory.json"
MAX_LIST_ENTRIES = 200
MAX_READ_BYTES = 400_000
MAX_SEARCH_RESULTS = 30
MAX_SEARCH_FILES = 1_500
MAX_SEARCH_FILE_BYTES = 500_000
MAX_PATH_SEARCH_ENTRIES = 10_000
MAX_WRITE_BYTES = 120_000
MAX_RESEARCH_TITLE_CHARS = 180
MAX_RESEARCH_QUERY_CHARS = 500
MAX_RESEARCH_SUMMARY_CHARS = 20_000
MAX_RESEARCH_KEY_POINTS = 20
MAX_RESEARCH_SOURCES = 12
MAX_COMMAND_CHARS = 4_000
MAX_COMMAND_TIMEOUT = 60
MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_DOCUMENT_TEXT_CHARS = 120_000
MAX_OFFICE_BYTES = 30 * 1024 * 1024
MAX_SPREADSHEET_ROWS = 10_000
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
MAX_OCR_CHARS = 30_000
WEB_REQUEST_TIMEOUT_SECONDS = 20
WEB_MAX_BYTES = 2 * 1024 * 1024
WEB_MAX_TEXT_CHARS = 30_000
WEB_MAX_RESULTS = 10
WEB_USER_AGENT = "MyKOS/1.0 (local research assistant)"
MAX_PROCESS_RESULTS = 100
MAX_SERVICE_RESULTS = 100
MAX_PROCESS_QUERY_CHARS = 120
MAX_SERVICE_NAME_CHARS = 256
OLLAMA_REQUEST_TIMEOUT_SECONDS = 30
OLLAMA_PULL_TIMEOUT_SECONDS = 30 * 60
OLLAMA_MODEL_NAME_CHARS = 200
MEMORY_MAX_ENTRIES = 1_000
MEMORY_MAX_TITLE_CHARS = 160
MEMORY_MAX_CONTENT_BYTES = 50_000
MEMORY_MAX_TAGS = 12
MEMORY_MAX_TAG_CHARS = 40
MEMORY_CATEGORIES = {"fact", "preference", "project", "decision", "task", "reference"}
GIT_MAX_OUTPUT_CHARS = 60_000
GIT_MAX_LOG_ENTRIES = 50
GIT_MAX_PATHS = 100
GIT_MAX_COMMIT_MESSAGE_CHARS = 200
GIT_REMOTE_TIMEOUT_SECONDS = 120
# These paths are never exposed through project/file tools.  MyKOS keeps OAuth
# credentials, conversation data, uploads and local databases below `data/`;
# blocking the directory at path resolution also covers direct file requests.
IGNORED_PARTS = {
    # Almacenes de sesiones y credenciales del usuario en Linux (navegadores, CLIs con OAuth, llaveros).
    ".config",
    ".local",
    ".claude",
    ".codex",
    ".mozilla",
    ".pki",
    ".git",
    ".mykos",
    ".gnupg",
    ".ssh",
    "__pycache__",
    "appdata",
    "cache",
    "credentials",
    "data",
    "logs",
    "oauth",
    "programdata",
    "secrets",
    "state",
    "tmp",
    "temp",
}
PRIVATE_PATH_ROOTS = tuple(path.resolve() for path in (
    PROJECT_ROOT / "data",
    Path.home() / ".mykos" / "gateway-state",
    Path.home() / "mykos-gateway-state",
))
ALLOWED_TEXT_EXTENSIONS = {
    ".bat", ".c", ".cc", ".cfg", ".cmake", ".conf", ".cpp", ".css",
    ".csv", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".html", ".ini", ".js",
    ".json", ".md", ".ps1", ".py", ".sh", ".sql", ".toml", ".txt",
    ".xml", ".yaml", ".yml",
}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
SENSITIVE_TOOL_NAMES = {
    "write_project_file",
    "edit_project_file",
    "save_research_note",
    "run_powershell",
    "save_memory",
    "delete_memory",
    "git_commit",
    "pull_ollama_model",
    "delete_ollama_model",
    "stop_process",
    "start_service",
    "stop_service",
    "create_reminder",
    "delete_reminder",
    "spawn_subagent",
    "git_remote_fetch",
    "git_remote_pull",
    "git_remote_push",
    "git_branch",
    "text_to_speech",
    "generate_image",
    "generate_video",
    "pair_node",
    "revoke_node",
    "rea_call_tool",
}
MEMORY_LOCK = threading.RLock()
GIT_LOCK = threading.RLock()
OLLAMA_LOCK = threading.RLock()

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "write_project_file",
            "description": "Prepara una solicitud para crear o modificar un archivo de texto dentro de una raíz autorizada. Nunca escribe directamente: siempre requiere aprobación explícita de Usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Nombre de la raíz autorizada, por ejemplo mykos, mykos o linux.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa del archivo dentro de la raíz.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Contenido UTF-8 que se propone guardar.",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Debe ser true para reemplazar un archivo existente.",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_project_file",
            "description": "Prepara una edición acotada de un archivo de texto existente. old_text debe ser un fragmento exacto y único leído previamente; solo ese fragmento se sustituye por new_text. Conserva todo lo demás y requiere aprobación explícita de Usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Nombre de la raíz autorizada, por ejemplo mykos, mykos o linux.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa del archivo existente dentro de la raíz.",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Fragmento exacto, no vacío y único que se va a sustituir.",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Texto que sustituye exactamente a old_text; puede estar vacío solo para borrar ese fragmento.",
                    },
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_research_note",
            "description": "Prepara una ficha de investigación en Markdown con resumen y fuentes. Nunca la guarda directamente: requiere aprobación explícita de Usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Raíz autorizada; usa workspace salvo que Usuario indique otra.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa opcional dentro de la raíz (por defecto research/<tema>.md).",
                    },
                    "title": {
                        "type": "string",
                        "description": "Título de la investigación.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Pregunta o consulta investigada.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Resumen en español basado únicamente en las fuentes consultadas.",
                    },
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Puntos principales encontrados.",
                    },
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "url": {"type": "string"},
                                "note": {"type": "string"},
                            },
                            "required": ["title", "url"],
                            "additionalProperties": False,
                        },
                        "description": "Fuentes públicas consultadas, con título, URL y nota opcional.",
                    },
                },
                "required": ["title", "query", "summary", "sources"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_powershell",
            "description": "Prepara una solicitud para ejecutar un comando de shell en el equipo de Usuario (bash en Linux; PowerShell solo en Windows). Es la vía para abrir una carpeta, archivo o programa en su pantalla (en Linux: xdg-open \"/ruta\"). Nunca lo ejecuta directamente: siempre requiere aprobación explícita de Usuario y muestra el comando completo antes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Comando exacto que se propone ejecutar, en la sintaxis del shell del equipo (bash en Linux).",
                    },
                    "cwd_root": {
                        "type": "string",
                        "description": "Raíz autorizada que se usará como directorio de trabajo.",
                    },
                    "cwd_path": {
                        "type": "string",
                        "description": "Subcarpeta relativa opcional dentro de cwd_root.",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Tiempo máximo de ejecución, entre 1 y 60 segundos.",
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Busca recuerdos persistentes guardados por MyKOS. Solo lectura y búsqueda local por palabras clave.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Palabras o frase que se quieren buscar en la memoria.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Categoría opcional: fact, preference, project, decision, task o reference.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Número máximo de resultados, entre 1 y 20.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_memory",
            "description": "Lee el contenido completo de un recuerdo persistente mediante su identificador.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "Identificador devuelto por search_memory o list_memory.",
                    },
                },
                "required": ["memory_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_memory",
            "description": "Lista recuerdos persistentes sin mostrar todo su contenido.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Categoría opcional del recuerdo.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Número máximo de recuerdos, entre 1 y 50.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Prepara un recuerdo persistente nuevo o una actualización. Nunca guarda directamente: requiere aprobación explícita de Usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "Identificador existente para actualizar; vacío para crear un recuerdo nuevo.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Título breve y descriptivo.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Contenido duradero que se quiere recordar.",
                    },
                    "category": {
                        "type": "string",
                        "description": "fact, preference, project, decision, task o reference.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Etiquetas breves para facilitar búsquedas.",
                    },
                },
                "required": ["title", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_memory",
            "description": "Prepara la eliminación de un recuerdo persistente. Nunca borra directamente: requiere aprobación explícita de Usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "Identificador del recuerdo que se quiere eliminar.",
                    },
                },
                "required": ["memory_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_project_paths",
            "description": "Localiza por nombre archivos y carpetas dentro de una raíz autorizada, sin leer su contenido. Úsala cuando Usuario recuerde el nombre pero no la ruta. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {"type": "string", "description": "Nombre de la raíz autorizada, por ejemplo mykos o linux."},
                    "query": {"type": "string", "description": "Parte distintiva del nombre del archivo o carpeta que se busca."},
                    "path": {"type": "string", "description": "Subcarpeta relativa desde la que buscar dentro de la raíz autorizada."},
                    "max_results": {"type": "integer", "description": "Número máximo de coincidencias, entre 1 y 30."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_project_files",
            "description": "Busca texto dentro de archivos de texto de una raíz autorizada. Solo lectura, con límite de resultados y sin salir de la raíz.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Nombre de la raíz autorizada, por ejemplo mykos, mykos o linux.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Texto que se quiere localizar.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Subcarpeta relativa opcional donde buscar.",
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Si es true, distingue mayúsculas y minúsculas.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Número máximo de coincidencias, entre 1 y 30.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_local_status",
            "description": "Consulta información básica de solo lectura del equipo y de las GPU NVIDIA disponibles. No ejecuta comandos proporcionados por el usuario.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_processes",
            "description": "Lista procesos activos del equipo en modo solo lectura. No muestra comandos completos ni modifica procesos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Texto opcional para filtrar por nombre del proceso.",
                    },
                    "pid": {
                        "type": "integer",
                        "description": "PID opcional para consultar un proceso concreto.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Número máximo de procesos, entre 1 y 100.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_services",
            "description": "Lista servicios del sistema en modo solo lectura. No inicia, detiene ni reconfigura servicios.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Texto opcional para filtrar por nombre o nombre visible.",
                    },
                    "state": {
                        "type": "string",
                        "enum": ["all", "running", "stopped"],
                        "description": "Filtra por estado; por defecto devuelve todos.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Número máximo de servicios, entre 1 y 100.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_process",
            "description": "Prepara detener un proceso concreto por PID. Nunca lo detiene directamente: requiere aprobación explícita de Usuario y verifica que el PID siga siendo el mismo proceso.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {
                        "type": "integer",
                        "description": "PID exacto del proceso que se quiere detener.",
                    },
                },
                "required": ["pid"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_service",
            "description": "Prepara iniciar un servicio del sistema por nombre exacto. Nunca lo inicia directamente: requiere aprobación explícita.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Nombre exacto del servicio, no el nombre visible.",
                    },
                },
                "required": ["service"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_service",
            "description": "Prepara detener un servicio del sistema por nombre exacto. Nunca lo detiene directamente: requiere aprobación explícita.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Nombre exacto del servicio, no el nombre visible.",
                    },
                },
                "required": ["service"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Consulta el estado local de un repositorio Git dentro de una raíz autorizada. Solo lectura: no prepara ni modifica nada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Nombre de la raíz autorizada que contiene el repositorio, por ejemplo mykos.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Consulta las diferencias Git de una raíz autorizada. Solo lectura y con salida limitada; no cambia el índice ni los archivos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Nombre de la raíz autorizada que contiene el repositorio.",
                    },
                    "staged": {
                        "type": "boolean",
                        "description": "Si es true, muestra las diferencias ya preparadas en el índice; si es false, las no preparadas.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa opcional para limitar la diferencia a un archivo o carpeta.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Consulta el historial reciente de commits de una raíz autorizada. Solo lectura y sin acceso a remotos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Nombre de la raíz autorizada que contiene el repositorio.",
                    },
                    "max_entries": {
                        "type": "integer",
                        "description": "Número de commits a devolver, entre 1 y 50.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa opcional para limitar el historial a un archivo o carpeta.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Prepara un commit Git local. Nunca hace add ni commit directamente: siempre requiere aprobación explícita de Usuario y no puede usar remotos, reset, checkout ni borrar ramas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Nombre de la raíz autorizada que contiene el repositorio.",
                    },
                    "message": {
                        "type": "string",
                        "description": "Mensaje del commit, breve y descriptivo.",
                    },
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Rutas relativas concretas que se incluirán. Si se omite, se usarán solo cambios ya preparados; no se incluirán cambios sin preparar.",
                    },
                    "stage_all": {
                        "type": "boolean",
                        "description": "Si es true, prepara todos los cambios actuales de esta raíz antes del commit. Debe revisarse con cuidado.",
                    },
                },
                "required": ["message"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_remote_status",
            "description": "Consulta remotos, ramas y seguimiento de un repositorio Git autorizado. No contacta con la red.",
            "parameters": {
                "type": "object",
                "properties": {"root": {"type": "string", "description": "Raíz autorizada del repositorio."}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_branch",
            "description": "Prepara crear o cambiar a una rama local. Requiere aprobación; no borra ramas ni fuerza cambios.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {"type": "string", "description": "Raíz autorizada del repositorio."},
                    "operation": {"type": "string", "description": "create o switch."},
                    "branch": {"type": "string", "description": "Nombre de la rama."},
                    "start_point": {"type": "string", "description": "Punto de partida para crear la rama; por defecto HEAD."},
                },
                "required": ["branch"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_remote_fetch",
            "description": "Prepara actualizar referencias desde un remoto Git. Requiere aprobación y no modifica archivos de trabajo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {"type": "string", "description": "Raíz autorizada del repositorio."},
                    "remote": {"type": "string", "description": "Remoto; por defecto origin."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_remote_pull",
            "description": "Prepara un pull Git con --ff-only para no crear merges automáticos. Requiere aprobación.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {"type": "string", "description": "Raíz autorizada del repositorio."},
                    "remote": {"type": "string", "description": "Remoto; por defecto origin."},
                    "branch": {"type": "string", "description": "Rama a traer; por defecto la rama actual."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_remote_push",
            "description": "Prepara publicar una rama en un remoto Git. Requiere aprobación; force push está bloqueado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {"type": "string", "description": "Raíz autorizada del repositorio."},
                    "remote": {"type": "string", "description": "Remoto; por defecto origin."},
                    "branch": {"type": "string", "description": "Rama a publicar; por defecto la rama actual."},
                    "set_upstream": {"type": "boolean", "description": "Si es true, establece el seguimiento upstream."},
                    "force": {"type": "boolean", "description": "No permitido; force push se bloquea siempre."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_pdf",
            "description": "Extrae texto de un PDF dentro de una raíz autorizada. Solo lectura, con límites de tamaño y páginas; no modifica el archivo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Nombre de la raíz autorizada, por ejemplo mykos, mykos o linux.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa del PDF dentro de la raíz.",
                    },
                    "start_page": {
                        "type": "integer",
                        "description": "Primera página que se quiere extraer, empezando en 1.",
                    },
                    "max_pages": {
                        "type": "integer",
                        "description": "Máximo de páginas a extraer, entre 1 y 100.",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_image",
            "description": "Lee una imagen dentro de una raíz autorizada. Devuelve metadatos y OCR opcional; si el modelo admite visión, el servidor le adjunta la imagen directamente. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Nombre de la raíz autorizada, por ejemplo mykos, mykos o linux.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa de la imagen dentro de la raíz.",
                    },
                    "ocr": {
                        "type": "boolean",
                        "description": "Si es true, intenta extraer texto visible con Tesseract.",
                    },
                    "max_ocr_chars": {
                        "type": "integer",
                        "description": "Máximo de caracteres OCR que se devuelven, entre 500 y 30.000.",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": "Extrae texto de documentos DOCX o XLSX dentro de una raíz autorizada. Solo lectura, con límites de tamaño y contenido.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Nombre de la raíz autorizada, por ejemplo mykos, mykos o linux.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa del documento dentro de la raíz.",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_ollama_models",
            "description": "Consulta los modelos disponibles en la instancia configurada de Ollama. Solo lectura; no descarga ni elimina nada.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pull_ollama_model",
            "description": "Prepara la descarga o actualización de un modelo de Ollama. Nunca inicia la descarga directamente: requiere aprobación explícita de Usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Nombre exacto del modelo de Ollama, por ejemplo qwen3.6:latest.",
                    },
                },
                "required": ["model"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_ollama_model",
            "description": "Prepara la eliminación de un modelo instalado en Ollama. Nunca borra directamente: requiere aprobación explícita de Usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Nombre exacto del modelo instalado que se quiere eliminar.",
                    },
                },
                "required": ["model"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_project_files",
            "description": "Lista archivos y carpetas de una raíz autorizada. Solo lectura y limitada a las rutas declaradas en la configuración.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Nombre de la raíz autorizada, por ejemplo mykos, mykos o linux.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa dentro de esa raíz. Vacía para la raíz.",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Si es true, recorre subcarpetas. Usa false salvo que sea necesario.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_project_file",
            "description": "Lee un archivo de texto pequeño dentro de una raíz autorizada. Nunca lee binarios ni rutas fuera de las raíces declaradas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Nombre de la raíz autorizada, por ejemplo mykos, mykos o linux.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa del archivo dentro de la raíz.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Primera linea a leer, empezando en 1. Opcional.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Ultima linea a leer (maximo 400 lineas o 30.000 caracteres por llamada). Opcional; la respuesta indica has_more y next_start_line.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_allowed_roots",
            "description": "Muestra las carpetas autorizadas para las herramientas de solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Busca información pública en la web y devuelve resultados con título, URL y resumen. Solo lectura; no inicia sesión, no envía datos privados y no modifica nada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Consulta concreta que se quiere investigar, preferiblemente con términos y contexto suficientes.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Número máximo de resultados, entre 1 y 10.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Captura el texto legible de una página pública concreta y conserva título, URL final y fecha para poder citar la fuente. Solo lectura; rechaza URLs locales, privadas o con credenciales.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL pública http o https de la fuente que se quiere leer.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Máximo de texto devuelto, entre 1.000 y 30.000 caracteres.",
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_open",
            "description": "Abre una URL pública en un navegador local aislado de MyKOS y devuelve el texto renderizado y los enlaces principales. No reutiliza sesiones ni credenciales de MyKOS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL pública http o https que se quiere abrir.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Máximo de texto devuelto, entre 1.000 y 30.000 caracteres.",
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_snapshot",
            "description": "Lee el estado renderizado de la página abierta en el navegador local aislado. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_chars": {
                        "type": "integer",
                        "description": "Máximo de texto devuelto, entre 1.000 y 30.000 caracteres.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_close",
            "description": "Cierra el navegador local aislado y elimina su perfil temporal. Solo afecta al navegador de MyKOS.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_automations",
            "description": "Lista los recordatorios locales de MyKOS. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_automation_events",
            "description": "Lista los avisos de recordatorios locales que ya se han activado. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Número máximo de eventos, entre 1 y 100.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Prepara un recordatorio local persistente. Requiere aprobación explícita y no envía mensajes externos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título breve del recordatorio."},
                    "message": {"type": "string", "description": "Texto que se mostrará cuando se active."},
                    "run_at": {"type": "string", "description": "Fecha ISO futura, por ejemplo 2026-09-24T10:30:00+02:00."},
                    "repeat_minutes": {"type": "integer", "description": "0 para una vez o minutos de repetición, hasta 10080."},
                },
                "required": ["title", "run_at"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "Prepara borrar un recordatorio local por identificador. Requiere aprobación explícita.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string", "description": "Identificador del recordatorio."}},
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_subagents",
            "description": "Lista los trabajos de subagentes locales de MyKOS. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "Número máximo de trabajos, entre 1 y 100."}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": "Prepara un subagente local de Ollama para resolver una tarea de texto aislada. No tiene herramientas ni acceso a archivos; requiere aprobación explícita.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título breve del trabajo."},
                    "prompt": {"type": "string", "description": "Tarea detallada del subagente."},
                    "model": {"type": "string", "description": "Modelo Ollama opcional; por defecto el modelo local configurado."},
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "media_status",
            "description": "Consulta qué motores multimedia locales están disponibles en MyKOS. No conecta servicios externos.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_media",
            "description": "Lista archivos multimedia generados por MyKOS dentro de su almacenamiento local. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Número máximo de archivos, entre 1 y 100."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "text_to_speech",
            "description": "Prepara generar un archivo WAV con síntesis de voz local. Siempre requiere aprobación explícita; no usa APIs externas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Texto que se convertirá a voz, máximo 12.000 caracteres."},
                    "voice": {"type": "string", "description": "Nombre opcional de una voz local disponible (por ejemplo, alvaro o elvira)."},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Prepara la generación de una imagen digital en alta definición mediante difusión fotorrealista (FLUX) a partir de una descripción detallada en texto (prompt). Requiere aprobación explícita; guarda el resultado en el almacén multimedia local de MyKOS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Descripción detallada de la imagen a generar (sujeto, entorno, iluminación, encuadre, estilo fotográfico o artístico)."},
                    "aspect_ratio": {
                        "type": "string",
                        "enum": ["1:1", "16:9", "9:16", "4:3", "3:4"],
                        "description": "Relación de aspecto deseada para la imagen (por defecto 1:1).",
                    },
                    "model": {
                        "type": "string",
                        "enum": ["flux", "flux-realism", "turbo"],
                        "description": "Modelo de difusión a utilizar: 'flux' (fotorrealismo de máxima fidelidad y detalle, por defecto), 'flux-realism' o 'turbo'.",
                    },
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_video",
            "description": "Prepara la generación de un vídeo cinemático digital en formato MP4 a partir de una descripción en texto (prompt) o de una imagen generada previamente. Requiere aprobación explícita; guarda el resultado en el almacén multimedia local de MyKOS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Descripción de la escena o animación a generar en vídeo."},
                    "image_url": {"type": "string", "description": "URL o ruta opcional de una imagen generada previamente para animarla (por ejemplo '/static/media/gen-xxxx.jpg')."},
                    "motion": {
                        "type": "string",
                        "enum": ["cinematic", "zoom_in", "zoom_out", "pan_left", "pan_right"],
                        "description": "Tipo de movimiento de cámara: 'cinematic' (zoom suave y deriva tridimensional, por defecto), 'zoom_in', 'zoom_out', 'pan_left' o 'pan_right'.",
                    },
                    "duration_seconds": {
                        "type": "integer",
                        "description": "Duración del clip de vídeo en segundos (de 2 a 10, por defecto 4).",
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": ["1:1", "16:9", "9:16", "4:3", "3:4"],
                        "description": "Relación de aspecto del vídeo (por defecto 1:1).",
                    },
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_nodes",
            "description": "Lista el nodo de escritorio local y los nodos propios emparejados con MyKOS. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pair_node",
            "description": "Prepara emparejar un nodo móvil, de escritorio u otro nodo propio. Requiere aprobación explícita y entrega el token una sola vez.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre visible del nodo."},
                    "kind": {"type": "string", "description": "mobile, desktop o node."},
                    "capabilities": {"type": "array", "items": {"type": "string"}, "description": "Capacidades declaradas por el nodo."},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "revoke_node",
            "description": "Prepara revocar un nodo propio emparejado. Requiere aprobación explícita.",
            "parameters": {
                "type": "object",
                "properties": {"node_id": {"type": "string", "description": "Identificador del nodo que se quiere revocar."}},
                "required": ["node_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "local_management_status",
            "description": "Consulta el estado de la instalación local de MyKOS, sus rutas propias, almacenamiento, permisos básicos y motor Ollama. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rea_status",
            "description": "Consulta el estado del motor integrado REA (Reverse Engineer Anything), su versión y el número de herramientas MCP disponibles (207 herramientas de ingeniería inversa). Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rea_list_tools",
            "description": "Busca o lista herramientas disponibles en el motor REA (decompilación, binarios ELF/PE/Mach-O, Android APK, Rust, Go, WASM, Electron/JS, SQLite, PCAP, firmware).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Filtro opcional por nombre o descripción (ej. decompile, android, swift, electron, rust, macho, elf).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Máximo de herramientas a devolver (por defecto 35, máximo 100).",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rea_inspect_binary",
            "description": "Abre e inspecciona un binario o artefacto local con REA (open_binary + inspect_artifact + binary_overview), devolviendo evidencia SHA-256, formato, arquitectura, secciones y funciones.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Ruta al archivo binario o artefacto local a analizar.",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rea_analyze_javascript",
            "description": "Ejecuta análisis estático e ingeniería inversa de REA sobre una aplicación o bundle JavaScript, TypeScript, Web o Electron.",
            "parameters": {
                "type": "object",
                "properties": {
                    "input_path": {
                        "type": "string",
                        "description": "Ruta al archivo o directorio de la aplicación JS/Web/Electron.",
                    },
                    "detail": {
                        "type": "string",
                        "enum": ["summary", "standard", "full"],
                        "description": "Nivel de detalle del análisis (por defecto summary).",
                    },
                },
                "required": ["input_path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rea_call_tool",
            "description": "Invoca cualquiera de las 207 herramientas estáticas del motor REA (ej. list_procedures, procedure_pseudo_code, list_strings, inspect_android_package, inspect_go_binary, inspect_rust_binary).",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Nombre exacto de la herramienta de REA a ejecutar.",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Diccionario JSON con los parámetros de la herramienta de REA.",
                    },
                },
                "required": ["tool_name"],
                "additionalProperties": False,
            },
        },
    },
]


class ToolError(Exception):
    """Error seguro y legible producido por una herramienta."""


def _load_allowed_roots() -> list[dict[str, Any]]:
    workspace_env = os.environ.get("MYKOS_WORKSPACE_DIR") or os.environ.get("MYKOS_GATEWAY_WORKSPACE_DIR")
    default_ws = Path(workspace_env).expanduser() if workspace_env else (Path.home() / ".mykos" / "workspace")
    try:
        default_ws.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        pass
    roots: list[dict[str, Any]] = [
        {"name": "workspace", "path": default_ws.resolve()},
        {"name": "mykos", "path": PROJECT_ROOT},
    ]
    try:
        data = json.loads(ALLOWED_ROOTS_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        data = {}
    configured = data.get("roots", []) if isinstance(data, dict) else []
    if not isinstance(configured, list):
        configured = []
    names = {root["name"] for root in roots}
    for entry in configured:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        raw_path = entry.get("path")
        if not name or not isinstance(raw_path, str):
            continue
        if not name.replace("_", "").replace("-", "").replace(".", "").isalnum() or len(name) > 40:
            continue
        configured_path = Path(os.path.expandvars(raw_path)).expanduser()
        if not configured_path.is_absolute():
            configured_path = (PROJECT_ROOT / configured_path).resolve()
        try:
            if not configured_path.exists() and name == "workspace":
                configured_path.mkdir(parents=True, exist_ok=True, mode=0o700)
            resolved = configured_path.resolve()
        except OSError:
            continue
        if resolved == Path("/"):
            continue
        if resolved.is_dir() and not resolved.is_symlink():
            if name in names:
                for r in roots:
                    if r["name"] == name:
                        r["path"] = resolved
                        break
            else:
                roots.append({"name": name, "path": resolved})
                names.add(name)
    return roots


def allowed_root_catalog() -> list[dict[str, str]]:
    return [{"name": root["name"], "path": str(root["path"])} for root in _load_allowed_roots()]


def tool_catalog() -> list[dict[str, str]]:
    return [
        {
            "name": "write_project_file",
            "description": "Prepara una escritura de archivo para aprobación explícita.",
            "scope": "Cambio real · requiere aprobación",
        },
        {
            "name": "edit_project_file",
            "description": "Prepara una sustitución acotada y verificable dentro de un archivo existente.",
            "scope": "Cambio real � requiere aprobación",
        },
        {
            "name": "save_research_note",
            "description": "Prepara una ficha de investigación con resumen y fuentes.",
            "scope": "Cambio real · requiere aprobación",
        },
        {
            "name": "run_powershell",
            "description": "Prepara un comando de shell (bash en Linux) para aprobación explícita.",
            "scope": "Ejecución real · requiere aprobación",
        },
        {
            "name": "search_memory",
            "description": "Busca recuerdos persistentes por palabras clave.",
            "scope": "Solo lectura · memoria local",
        },
        {
            "name": "read_memory",
            "description": "Lee un recuerdo persistente completo.",
            "scope": "Solo lectura · memoria local",
        },
        {
            "name": "list_memory",
            "description": "Lista recuerdos persistentes.",
            "scope": "Solo lectura · memoria local",
        },
        {
            "name": "save_memory",
            "description": "Prepara un recuerdo nuevo o una actualización.",
            "scope": "Cambio real · requiere aprobación",
        },
        {
            "name": "delete_memory",
            "description": "Prepara la eliminación de un recuerdo.",
            "scope": "Borrado real · requiere aprobación",
        },
        {
            "name": "search_project_files",
            "description": "Busca texto dentro de archivos de una raíz autorizada.",
            "scope": "Solo lectura · texto permitido · máximo 30 resultados",
        },
        {
            "name": "find_project_paths",
            "description": "Localiza archivos y carpetas por nombre dentro de una raíz autorizada.",
            "scope": "Solo lectura · máximo 30 coincidencias",
        },
        {
            "name": "get_local_status",
            "description": "Consulta el estado básico del equipo y de las GPU NVIDIA.",
            "scope": "Solo lectura · sin comandos arbitrarios",
        },
        {
            "name": "list_processes",
            "description": "Lista procesos activos y sus recursos básicos.",
            "scope": "Solo lectura · máximo 100 resultados",
        },
        {
            "name": "list_services",
            "description": "Lista servicios de Windows y su estado.",
            "scope": "Solo lectura · máximo 100 resultados",
        },
        {
            "name": "stop_process",
            "description": "Prepara detener un proceso por PID.",
            "scope": "Cambio real · requiere aprobación",
        },
        {
            "name": "start_service",
            "description": "Prepara iniciar un servicio de Windows.",
            "scope": "Cambio real · requiere aprobación",
        },
        {
            "name": "stop_service",
            "description": "Prepara detener un servicio de Windows.",
            "scope": "Cambio real · requiere aprobación",
        },
        {
            "name": "git_status",
            "description": "Consulta el estado local de un repositorio Git.",
            "scope": "Solo lectura · sin remotos",
        },
        {
            "name": "git_diff",
            "description": "Consulta diferencias Git preparadas o no preparadas.",
            "scope": "Solo lectura · salida limitada",
        },
        {
            "name": "git_log",
            "description": "Consulta el historial reciente de commits.",
            "scope": "Solo lectura · sin remotos",
        },
        {
            "name": "git_commit",
            "description": "Prepara un commit Git local para aprobación explícita.",
            "scope": "Cambio real · add/commit · requiere aprobación",
        },
        {
            "name": "git_remote_status",
            "description": "Consulta remotos y ramas sin contactar con la red.",
            "scope": "Solo lectura · metadatos locales",
        },
        {
            "name": "git_branch",
            "description": "Prepara crear o cambiar de rama local.",
            "scope": "Cambio local · requiere aprobación",
        },
        {
            "name": "git_remote_fetch",
            "description": "Prepara actualizar referencias desde un remoto.",
            "scope": "Red y referencias Git · requiere aprobación",
        },
        {
            "name": "git_remote_pull",
            "description": "Prepara pull con fast-forward only.",
            "scope": "Cambio local y red · requiere aprobación",
        },
        {
            "name": "git_remote_push",
            "description": "Prepara publicar una rama sin force push.",
            "scope": "Publicación externa · requiere aprobación",
        },
        {
            "name": "read_pdf",
            "description": "Extrae texto de documentos PDF.",
            "scope": "Solo lectura · máximo 30 MB y 100 páginas",
        },
        {
            "name": "read_image",
            "description": "Lee metadatos, OCR y visión directa de imágenes.",
            "scope": "Solo lectura · Pillow/Tesseract · máximo 12 MB",
        },
        {
            "name": "read_document",
            "description": "Extrae texto de documentos DOCX y XLSX.",
            "scope": "Solo lectura · máximo 30 MB",
        },
        {
            "name": "list_ollama_models",
            "description": "Consulta los modelos disponibles en Ollama.",
            "scope": "Solo lectura · instancia Ollama configurada",
        },
        {
            "name": "pull_ollama_model",
            "description": "Prepara descargar o actualizar un modelo de Ollama.",
            "scope": "Descarga externa · requiere aprobación",
        },
        {
            "name": "delete_ollama_model",
            "description": "Prepara eliminar un modelo de Ollama.",
            "scope": "Borrado real · requiere aprobación",
        },
        {
            "name": "list_project_files",
            "description": "Lista archivos y carpetas de una raíz autorizada.",
            "scope": "Solo lectura · rutas declaradas",
        },
        {
            "name": "read_project_file",
            "description": "Lee archivos de texto pequeños de una raíz autorizada.",
            "scope": "Solo lectura · extensiones de texto permitidas",
        },
        {
            "name": "list_allowed_roots",
            "description": "Muestra las carpetas autorizadas.",
            "scope": "Solo lectura · configuración del proyecto",
        },
        {
            "name": "web_search",
            "description": "Busca fuentes públicas y devuelve títulos, URLs y resúmenes.",
            "scope": "Solo lectura · búsqueda web · máximo 10 resultados",
        },
        {
            "name": "web_fetch",
            "description": "Captura texto legible y metadatos de una fuente web pública.",
            "scope": "Solo lectura · URLs públicas · máximo 2 MB",
        },
        {
            "name": "browser_open",
            "description": "Abre y renderiza una URL pública con un navegador local aislado.",
            "scope": "Solo lectura · perfil temporal · sin credenciales de MyKOS",
        },
        {
            "name": "browser_snapshot",
            "description": "Lee la página renderizada abierta en el navegador aislado.",
            "scope": "Solo lectura · navegador local",
        },
        {
            "name": "browser_close",
            "description": "Cierra el navegador aislado y su perfil temporal.",
            "scope": "Control local · solo MyKOS",
        },
        {
            "name": "list_automations",
            "description": "Lista los recordatorios locales configurados.",
            "scope": "Solo lectura · almacenamiento local",
        },
        {
            "name": "list_automation_events",
            "description": "Lista avisos de recordatorios ya activados.",
            "scope": "Solo lectura · eventos locales",
        },
        {
            "name": "create_reminder",
            "description": "Prepara crear un recordatorio local persistente.",
            "scope": "Cambio local · requiere aprobación",
        },
        {
            "name": "delete_reminder",
            "description": "Prepara borrar un recordatorio local.",
            "scope": "Borrado local · requiere aprobación",
        },
        {
            "name": "list_subagents",
            "description": "Lista trabajos de subagentes locales.",
            "scope": "Solo lectura · trabajos persistentes",
        },
        {
            "name": "spawn_subagent",
            "description": "Prepara iniciar un subagente local aislado.",
            "scope": "Ejecución local · requiere aprobación",
        },
        {
            "name": "local_management_status",
            "description": "Consulta el estado de la instalación local de MyKOS.",
            "scope": "Solo lectura · diagnóstico local",
        },
        {
            "name": "media_status",
            "description": "Consulta motores multimedia locales disponibles.",
            "scope": "Solo lectura · sin servicios externos",
        },
        {
            "name": "list_media",
            "description": "Lista archivos multimedia generados por MyKOS.",
            "scope": "Solo lectura · almacenamiento local",
        },
        {
            "name": "text_to_speech",
            "description": "Prepara síntesis de voz local en WAV.",
            "scope": "Escritura local · requiere aprobación",
        },
        {
            "name": "generate_image",
            "description": "Prepara la generación de una imagen digital en alta definición a partir de un prompt.",
            "scope": "Generación multimedia · requiere aprobación",
        },
        {
            "name": "generate_video",
            "description": "Prepara la generación de un vídeo cinemático en MP4 a partir de un prompt o imagen.",
            "scope": "Generación multimedia · requiere aprobación",
        },
        {
            "name": "list_nodes",
            "description": "Lista el escritorio local y nodos propios emparejados.",
            "scope": "Solo lectura · nodos locales",
        },
        {
            "name": "pair_node",
            "description": "Prepara emparejar un nodo móvil o externo.",
            "scope": "Credencial nueva · requiere aprobación",
        },
        {
            "name": "revoke_node",
            "description": "Prepara revocar un nodo emparejado.",
            "scope": "Cambio local · requiere aprobación",
        },
        {
            "name": "rea_status",
            "description": "Consulta el estado del motor de ingeniería inversa REA (207 herramientas).",
            "scope": "Solo lectura · motor REA local",
        },
        {
            "name": "rea_list_tools",
            "description": "Busca o lista herramientas del motor REA.",
            "scope": "Solo lectura · motor REA local",
        },
        {
            "name": "rea_inspect_binary",
            "description": "Inspecciona un binario o artefacto local con REA (SHA-256, formato, funciones).",
            "scope": "Solo lectura · análisis estático REA",
        },
        {
            "name": "rea_analyze_javascript",
            "description": "Analiza aplicaciones o bundles JS/TS/Electron con REA.",
            "scope": "Solo lectura · análisis estático REA",
        },
        {
            "name": "rea_call_tool",
            "description": "Ejecuta una herramienta estática del catálogo MCP de REA.",
            "scope": "Solo lectura · análisis estático REA",
        },
    ]


def _relative_label(path: Path, root_path: Path) -> str:
    relative = path.relative_to(root_path)
    return "." if str(relative) == "." else relative.as_posix()


def _resolve_root(root_name: Any) -> tuple[str, Path]:
    roots = _load_allowed_roots()
    default_root = roots[0]["name"] if roots else "workspace"
    requested = str(root_name or default_root).strip()
    for root in roots:
        if root["name"] == requested:
            return root["name"], root["path"]
    available = ", ".join(root["name"] for root in roots)
    raise ToolError(f"Raíz no autorizada: {requested}. Disponibles: {available}.")


def _resolve_project_path(root_name: Any, raw_path: Any, *, allow_root: bool = True) -> tuple[str, Path, Path]:
    roots = _load_allowed_roots()
    roots_by_name = {item["name"]: item["path"] for item in roots}
    workspace_root = roots_by_name.get("workspace")
    selected_name, root_path = _resolve_root(root_name)
    if raw_path is None:
        raw_path = ""
    if not isinstance(raw_path, str):
        raise ToolError("La ruta debe ser texto.")
    raw_path = raw_path.strip()
    if len(raw_path) > 500:
        raise ToolError("La ruta es demasiado larga.")

    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ToolError("Solo se aceptan rutas relativas a una raíz autorizada.")

    # Si se incluye "workspace" como prefijo de ruta (p. ej. "workspace/research/tema.md"):
    if candidate.parts and candidate.parts[0].lower() == "workspace":
        remainder = Path(*candidate.parts[1:]) if len(candidate.parts) > 1 else Path(".")
        if selected_name == "workspace":
            candidate = remainder
        elif selected_name == "mykos" and workspace_root is not None:
            selected_name = "workspace"
            root_path = workspace_root
            candidate = remainder

    resolved = (root_path / candidate).resolve()
    try:
        resolved.relative_to(root_path)
    except ValueError as error:
        raise ToolError("La ruta queda fuera de la raíz autorizada.") from error
    if not resolved.exists() and raw_path and ".." not in candidate.parts:
        fallback_attempts: list[tuple[str, Path, Path]] = []
        other_name = "workspace" if selected_name == "mykos" else "mykos"
        other_root = roots_by_name.get(other_name)
        if other_root is not None:
            fallback_attempts.append((other_name, other_root, (other_root / candidate).resolve()))
        for alt_name, alt_root, alt_path in fallback_attempts:
            try:
                alt_path.relative_to(alt_root)
            except ValueError:
                continue
            if _is_ignored(alt_path, alt_root):
                continue
            if alt_path.exists() or (not resolved.parent.exists() and alt_path.parent != alt_root and alt_path.parent.exists()):
                selected_name, root_path, resolved = alt_name, alt_root, alt_path
                break
    if _is_ignored(resolved, root_path):
        raise ToolError("La ruta pertenece a almacenamiento privado o interno y no está disponible para las herramientas de proyecto.")
    if not allow_root and resolved == root_path:
        raise ToolError("Debes indicar un archivo, no la raíz completa.")
    return selected_name, root_path, resolved


def _is_ignored(path: Path, root_path: Path) -> bool:
    try:
        resolved = path.resolve()
        parts = resolved.relative_to(root_path.resolve()).parts
    except (OSError, ValueError):
        return True
    if any(resolved == private_root or private_root in resolved.parents for private_root in PRIVATE_PATH_ROOTS):
        return True
    return bool(
        IGNORED_PARTS.intersection(part.casefold() for part in parts)
        or any(part.casefold().startswith(".env") for part in parts)
        or any(part.casefold() in {"auth.json", "credentials.json", "token.json"} for part in parts)
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
    return {"ok": True, "root": root_name, "path": _relative_label(directory, root_path), "query": query,
            "matches": matches, "entries_scanned": entries_scanned, "truncated": truncated}


def _get_local_status() -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_logical": os.cpu_count(),
    }

    try:
        import psutil  # type: ignore

        memory = psutil.virtual_memory()
        result["memory"] = {
            "total_bytes": memory.total,
            "available_bytes": memory.available,
            "used_percent": memory.percent,
        }
        result["cpu_used_percent"] = psutil.cpu_percent(interval=0.1)
    except (ImportError, AttributeError, OSError):
        result["memory"] = {"available": False}

    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        result["gpu"] = {"available": False, "reason": "nvidia-smi no está disponible."}
        return result

    try:
        completed = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        result["gpu"] = {"available": False, "reason": f"No se pudo consultar NVIDIA: {error}"}
        return result

    devices: list[dict[str, str]] = []
    for line in completed.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 5:
            continue
        devices.append(
            {
                "name": fields[0],
                "memory_total_mib": fields[1],
                "memory_used_mib": fields[2],
                "utilization_percent": fields[3],
                "temperature_c": fields[4],
            }
        )
    result["gpu"] = {
        "available": completed.returncode == 0 and bool(devices),
        "devices": devices,
    }
    if completed.returncode != 0:
        result["gpu"]["reason"] = completed.stderr.strip()[:300] or "nvidia-smi devolvió un error."
    return result


PROTECTED_PROCESS_NAMES = {
    "system",
    "registry",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "winlogon.exe",
    "svchost.exe",
}

SERVICE_STATUS_NAMES = {
    1: "stopped",
    2: "start_pending",
    3: "stop_pending",
    4: "running",
    5: "continue_pending",
    6: "pause_pending",
    7: "paused",
}

SERVICE_START_TYPE_NAMES = {
    0: "boot",
    1: "system",
    2: "automatic",
    3: "manual",
    4: "disabled",
}


def _get_psutil() -> Any:
    try:
        import psutil  # type: ignore
    except ImportError as error:
        raise ToolError("La gestión de procesos requiere la dependencia psutil.") from error
    return psutil


def _process_record(process: Any) -> dict[str, Any] | None:
    psutil = _get_psutil()
    try:
        info = process.as_dict(
            attrs=["pid", "name", "username", "status", "create_time"],
            ad_value=None,
        )
        memory_bytes = int(process.memory_info().rss)
    except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied, OSError):
        return None

    pid = int(info.get("pid") or 0)
    name = str(info.get("name") or "")
    created_epoch = info.get("create_time")
    created_at = ""
    if isinstance(created_epoch, (int, float)) and created_epoch > 0:
        created_at = datetime.fromtimestamp(created_epoch, timezone.utc).isoformat(timespec="seconds")
    return {
        "pid": pid,
        "name": name,
        "username": str(info.get("username") or ""),
        "status": str(info.get("status") or "unknown"),
        "memory_bytes": memory_bytes,
        "created_at": created_at,
        "create_time_epoch": float(created_epoch) if isinstance(created_epoch, (int, float)) else 0,
    }


def _list_processes(arguments: dict[str, Any]) -> dict[str, Any]:
    psutil = _get_psutil()
    query = str(arguments.get("query", "") or "").strip()
    if len(query) > MAX_PROCESS_QUERY_CHARS:
        raise ToolError(f"El filtro de procesos no puede superar {MAX_PROCESS_QUERY_CHARS} caracteres.")
    raw_pid = arguments.get("pid")
    pid: int | None = None
    if raw_pid is not None and raw_pid != "":
        try:
            pid = int(raw_pid)
        except (TypeError, ValueError) as error:
            raise ToolError("El PID debe ser un número entero.") from error
        if pid < 0:
            raise ToolError("El PID no puede ser negativo.")
    try:
        max_results = int(arguments.get("max_results", 50))
    except (TypeError, ValueError) as error:
        raise ToolError("max_results debe ser un número entero.") from error
    if not 1 <= max_results <= MAX_PROCESS_RESULTS:
        raise ToolError(f"max_results debe estar entre 1 y {MAX_PROCESS_RESULTS}.")

    if pid is not None:
        try:
            candidates = [psutil.Process(pid)]
        except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
            raise ToolError(f"No se puede consultar el proceso {pid}: {error}.") from error
    else:
        candidates = psutil.process_iter()

    query_folded = query.casefold()
    processes: list[dict[str, Any]] = []
    for process in candidates:
        record = _process_record(process)
        if record is None:
            continue
        if query_folded and query_folded not in record["name"].casefold():
            continue
        processes.append(record)

    processes.sort(key=lambda item: (-int(item["memory_bytes"]), str(item["name"]).casefold(), int(item["pid"])))
    truncated = len(processes) > max_results
    return {
        "ok": True,
        "action": "list_processes",
        "query": query,
        "pid": pid,
        "count": len(processes),
        "truncated": truncated,
        "processes": processes[:max_results],
    }


def _systemd_service_records() -> list[dict[str, Any]]:
    executable = shutil.which("systemctl")
    if not executable:
        raise ToolError("systemctl no está disponible para consultar los servicios del sistema.")
    try:
        completed = subprocess.run(
            [executable, "list-units", "--type=service", "--all", "--no-pager", "--no-legend"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ToolError(f"No se pudieron consultar los servicios del sistema: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[:500]
        raise ToolError(f"systemctl no pudo consultar los servicios: {detail}")
    services: list[dict[str, Any]] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip().lstrip("●*").strip()
        if not line:
            continue
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit_name, _load, active_state, sub_state = parts[:4]
        description = parts[4] if len(parts) > 4 else unit_name
        name = unit_name[:-8] if unit_name.endswith(".service") else unit_name
        status = "running" if active_state == "active" and sub_state == "running" else "stopped"
        services.append(
            {
                "name": name,
                "display_name": description,
                "status": status,
                "status_code": 4 if status == "running" else 1,
                "start_type": "automatic" if active_state == "active" else "manual",
                "start_type_code": 2 if active_state == "active" else 3,
            }
        )
    return services


def _list_services(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    if len(query) > MAX_PROCESS_QUERY_CHARS:
        raise ToolError(f"El filtro de servicios no puede superar {MAX_PROCESS_QUERY_CHARS} caracteres.")
    state = str(arguments.get("state", "all") or "all").strip().casefold()
    if state not in {"all", "running", "stopped"}:
        raise ToolError("state debe ser all, running o stopped.")
    try:
        max_results = int(arguments.get("max_results", 50))
    except (TypeError, ValueError) as error:
        raise ToolError("max_results debe ser un número entero.") from error
    if not 1 <= max_results <= MAX_SERVICE_RESULTS:
        raise ToolError(f"max_results debe estar entre 1 y {MAX_SERVICE_RESULTS}.")

    query_folded = query.casefold()
    services = [
        service
        for service in _systemd_service_records()
        if (not query_folded or query_folded in service["name"].casefold() or query_folded in service["display_name"].casefold())
        and (state == "all" or service["status"] == state)
    ]
    services.sort(key=lambda item: (str(item["name"]).casefold(), str(item["display_name"]).casefold()))
    return {
        "ok": True,
        "action": "list_services",
        "query": query,
        "state": state,
        "count": len(services),
        "truncated": len(services) > max_results,
        "services": services[:max_results],
    }


def _normalise_service_name(raw_name: Any) -> str:
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise ToolError("Debes indicar el nombre exacto del servicio.")
    name = raw_name.strip()
    if name.endswith(".service"):
        name = name[:-8]
    if len(name) > MAX_SERVICE_NAME_CHARS or any(char.isspace() and char in "\r\n\t" for char in name):
        raise ToolError("El nombre del servicio es demasiado largo o contiene saltos de línea.")
    if any(ord(char) < 32 for char in name) or name.startswith("/") or name.startswith("-"):
        raise ToolError("El nombre del servicio contiene caracteres no válidos.")
    return name


def _find_service(service_name: str) -> dict[str, Any] | None:
    wanted = service_name.casefold()
    return next((service for service in _systemd_service_records() if service["name"].casefold() == wanted), None)


def _prepare_service_action(arguments: dict[str, Any], kind: str, expected_status: str) -> dict[str, Any]:
    service_name = _normalise_service_name(arguments.get("service"))
    service = _find_service(service_name)
    if service is None:
        raise ToolError(f"No existe un servicio con el nombre exacto '{service_name}'.")
    if service["status"] != expected_status:
        action_word = "iniciar" if kind == "start_service" else "detener"
        raise ToolError(f"No se puede {action_word} '{service['name']}' porque ahora está {service['status']}.")
    if kind == "start_service" and service["start_type"] == "disabled":
        raise ToolError(f"El servicio '{service['name']}' está deshabilitado; no se iniciará.")
    return {
        "kind": kind,
        "service": service["name"],
        "display_name": service["display_name"],
        "status": service["status"],
        "status_code": service["status_code"],
        "start_type": service["start_type"],
    }


def _execute_service_action(action: dict[str, Any], command: str, target_status: str) -> dict[str, Any]:
    service_name = _normalise_service_name(action.get("service"))
    current = _find_service(service_name)
    if current is None:
        raise ToolError(f"El servicio '{service_name}' ya no existe; no se modificará nada.")
    if current["status"] != action.get("status") or current["status_code"] != action.get("status_code"):
        raise ToolError("El estado del servicio cambió desde la aprobación; no se ejecutará la acción.")
    executable = shutil.which("systemctl")
    if not executable:
        raise ToolError("systemctl no está disponible para controlar servicios en Linux.")
    try:
        completed = subprocess.run(
            [executable, command, f"{service_name}.service"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ToolError(f"No se pudo ejecutar {command} sobre '{service_name}': {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[:500]
        raise ToolError(f"systemctl rechazó {command} sobre '{service_name}': {detail}")

    deadline = time.monotonic() + 15
    observed = current
    while time.monotonic() < deadline:
        observed = _find_service(service_name) or observed
        if observed.get("status") == target_status:
            return {
                "ok": True,
                "action": action.get("kind", ""),
                "service": service_name,
                "display_name": observed.get("display_name", ""),
                "status": observed.get("status", ""),
            }
        time.sleep(0.5)
    raise ToolError(
        f"systemctl aceptó la orden, pero el servicio '{service_name}' no llegó a {target_status}."
    )


def _prepare_stop_process(arguments: dict[str, Any]) -> dict[str, Any]:
    psutil = _get_psutil()
    try:
        pid = int(arguments.get("pid"))
    except (TypeError, ValueError) as error:
        raise ToolError("El PID debe ser un número entero.") from error
    if pid <= 4:
        raise ToolError("No se permite detener procesos del sistema con PID 0-4.")
    if pid == os.getpid():
        raise ToolError("No se permite detener el servidor de MyKOS desde esta herramienta.")
    try:
        process = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
        raise ToolError(f"No se puede consultar el proceso {pid}: {error}.") from error
    record = _process_record(process)
    if record is None:
        raise ToolError(f"No se puede obtener la identidad del proceso {pid}.")
    if record["name"].casefold() in PROTECTED_PROCESS_NAMES:
        raise ToolError(f"El proceso '{record['name']}' está protegido y no se detendrá.")
    if not record["create_time_epoch"]:
        raise ToolError("No se pudo fijar la identidad temporal del proceso; no se detendrá.")
    return {
        "kind": "stop_process",
        "pid": pid,
        "name": record["name"],
        "username": record["username"],
        "status": record["status"],
        "memory_bytes": record["memory_bytes"],
        "create_time_epoch": record["create_time_epoch"],
        "created_at": record["created_at"],
    }


def _execute_stop_process(action: dict[str, Any]) -> dict[str, Any]:
    psutil = _get_psutil()
    try:
        pid = int(action.get("pid"))
    except (TypeError, ValueError) as error:
        raise ToolError("La solicitud no contiene un PID válido.") from error
    try:
        process = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
        raise ToolError(f"El proceso {pid} ya no está disponible; no se detendrá.") from error
    current = _process_record(process)
    if current is None or current["name"].casefold() != str(action.get("name", "")).casefold():
        raise ToolError("El PID ya pertenece a otro proceso; no se ejecutará la solicitud.")
    expected_time = float(action.get("create_time_epoch", 0) or 0)
    if not expected_time or abs(float(current["create_time_epoch"]) - expected_time) > 0.05:
        raise ToolError("El proceso cambió desde la aprobación; no se ejecutará la solicitud.")
    if current["name"].casefold() in PROTECTED_PROCESS_NAMES or pid == os.getpid():
        raise ToolError("El proceso está protegido; no se detendrá.")
    try:
        process.terminate()
        process.wait(timeout=10)
    except psutil.TimeoutExpired as error:
        raise ToolError("El proceso no terminó en 10 segundos; no se forzará su cierre.") from error
    except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
        raise ToolError(f"No se pudo detener el proceso {pid}: {error}.") from error
    return {
        "ok": True,
        "action": "stop_process",
        "pid": pid,
        "name": current["name"],
        "stopped": True,
    }


def _run_git(root_path: Path, arguments: list[str], *, timeout: int = 20, env: dict[str, str] | None = None) -> Any:
    git = shutil.which("git.exe") or shutil.which("git")
    if not git:
        raise ToolError("Git no está instalado o no está disponible en PATH.")
    try:
        process_env = os.environ.copy()
        process_env["GIT_TERMINAL_PROMPT"] = "0"
        if env:
            process_env.update(env)
        return subprocess.run(
            [git, "--literal-pathspecs", *arguments],
            cwd=str(root_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=process_env,
        )
    except subprocess.TimeoutExpired as error:
        raise ToolError(f"Git superó el tiempo máximo de {timeout} segundos.") from error
    except (OSError, subprocess.SubprocessError) as error:
        raise ToolError(f"No se pudo iniciar Git: {error}") from error


def _git_repository(arguments: dict[str, Any]) -> tuple[str, Path]:
    root_name, root_path = _resolve_root(arguments.get("root", "mykos"))
    result = _run_git(root_path, ["rev-parse", "--show-toplevel"], timeout=10)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:300]
        raise ToolError(f"La raíz '{root_name}' no contiene un repositorio Git válido. {detail}".strip())
    output = result.stdout.strip().splitlines()
    if not output:
        raise ToolError(f"Git no pudo determinar la raíz del repositorio '{root_name}'.")
    git_root = Path(output[-1].strip()).resolve()
    if os.path.normcase(str(git_root)) != os.path.normcase(str(root_path.resolve())):
        raise ToolError(
            f"La raíz Git real ({git_root}) no coincide con la raíz autorizada ({root_path})."
        )
    return root_name, root_path


def _git_status_state(root_path: Path) -> dict[str, str]:
    result = _run_git(
        root_path,
        ["status", "--short", "--branch", "--untracked-files=all"],
        timeout=20,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise ToolError(f"No se pudo consultar el estado Git. {detail}".strip())
    raw = result.stdout.strip()
    head_result = _run_git(root_path, ["rev-parse", "HEAD"], timeout=10)
    head = head_result.stdout.strip() if head_result.returncode == 0 else ""
    fingerprint_parts = [raw]
    diff_targets = []
    if head:
        diff_targets.append(["diff", "--raw", "--no-ext-diff", "--no-color", head, "--"])
    else:
        diff_targets.append(["diff", "--raw", "--no-ext-diff", "--no-color", "--"])
    diff_targets.append(["diff", "--raw", "--cached", "--"])
    for diff_arguments in diff_targets:
        diff_result = _run_git(root_path, diff_arguments, timeout=30)
        if diff_result.returncode != 0:
            detail = (diff_result.stderr or diff_result.stdout).strip()[:500]
            raise ToolError(f"No se pudo verificar el contenido Git. {detail}".strip())
        fingerprint_parts.append(diff_result.stdout)

    untracked = _run_git(
        root_path,
        ["ls-files", "--others", "--exclude-standard", "-z"],
        timeout=20,
    )
    if untracked.returncode != 0:
        detail = (untracked.stderr or untracked.stdout).strip()[:500]
        raise ToolError(f"No se pudieron verificar los archivos sin seguimiento. {detail}".strip())
    for raw_path in untracked.stdout.split("\x00"):
        if not raw_path:
            continue
        raw_candidate = root_path / Path(raw_path)
        candidate = raw_candidate.resolve()
        try:
            candidate.relative_to(root_path)
        except ValueError as error:
            raise ToolError("Git devolvió un archivo sin seguimiento fuera de la raíz autorizada.") from error
        if raw_candidate.is_symlink():
            fingerprint_parts.append(f"untracked:{raw_path}:symlink")
            continue
        if raw_candidate.is_dir():
            # Git can report an untracked directory with a trailing slash
            # when it contains a large tree. The status line is the stable
            # fingerprint for that directory; do not try read_bytes() on it.
            fingerprint_parts.append(f"untracked-dir:{raw_path}")
            continue
        try:
            file_stat = candidate.stat()
            digest = hashlib.sha256()
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            fingerprint_parts.append(
                f"untracked:{raw_path}:{file_stat.st_size}:{file_stat.st_mtime_ns}:{digest.hexdigest()}"
            )
        except OSError as error:
            raise ToolError(f"No se pudo verificar el archivo sin seguimiento '{raw_path}'.") from error
    return {
        "raw": raw,
        "hash": hashlib.sha256("\x1f".join(fingerprint_parts).encode("utf-8")).hexdigest(),
        "head": head,
    }


def _git_status_changes(raw_status: str) -> list[str]:
    lines = raw_status.splitlines()
    if lines and lines[0].startswith("##"):
        return lines[1:]
    return lines


def _git_pathspecs(arguments: dict[str, Any], root_path: Path) -> list[str]:
    raw_paths = arguments.get("paths")
    if raw_paths is None:
        single_path = arguments.get("path")
        raw_paths = [] if single_path is None or single_path == "" else [single_path]
    if not isinstance(raw_paths, list):
        raise ToolError("Las rutas Git deben ser una lista de textos.")
    if len(raw_paths) > GIT_MAX_PATHS:
        raise ToolError(f"No se pueden indicar más de {GIT_MAX_PATHS} rutas Git.")

    paths: list[str] = []
    for raw_path in raw_paths:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ToolError("Cada ruta Git debe ser un texto no vacío.")
        raw_path = raw_path.strip()
        if len(raw_path) > 500 or "\x00" in raw_path:
            raise ToolError("Una ruta Git no es válida o es demasiado larga.")
        candidate = Path(raw_path)
        if candidate.is_absolute():
            raise ToolError("Git solo acepta rutas relativas a la raíz autorizada.")
        resolved = (root_path / candidate).resolve()
        try:
            resolved.relative_to(root_path)
        except ValueError as error:
            raise ToolError("Una ruta Git queda fuera de la raíz autorizada.") from error
        if resolved == root_path:
            raise ToolError("Una ruta Git debe apuntar a un archivo o carpeta, no a la raíz.")
        label = _relative_label(resolved, root_path)
        if label not in paths:
            paths.append(label)
    return paths


def _git_diff_stat(root_path: Path, *, staged: bool, paths: list[str]) -> str:
    arguments = ["diff", "--no-ext-diff", "--no-color", "--stat"]
    if staged:
        arguments.append("--cached")
    arguments.extend(["--", *paths])
    result = _run_git(root_path, arguments, timeout=20)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise ToolError(f"No se pudo calcular el resumen de diferencias. {detail}".strip())
    return result.stdout.strip()[:GIT_MAX_OUTPUT_CHARS]


def _git_status(arguments: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path = _git_repository(arguments)
    state = _git_status_state(root_path)
    raw = state["raw"]
    changes = _git_status_changes(raw)
    lines = raw.splitlines()
    return {
        "ok": True,
        "action": "git_status",
        "root": root_name,
        "branch": lines[0][2:].strip() if lines and lines[0].startswith("##") else "",
        "head": state["head"],
        "clean": not changes,
        "changes": changes[:500],
        "changes_truncated": len(changes) > 500,
        "status": raw[:GIT_MAX_OUTPUT_CHARS],
        "status_truncated": len(raw) > GIT_MAX_OUTPUT_CHARS,
    }


def _git_diff(arguments: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path = _git_repository(arguments)
    staged = bool(arguments.get("staged", False))
    paths = _git_pathspecs(arguments, root_path)
    git_arguments = ["diff", "--no-ext-diff", "--no-color", "--unified=3"]
    if staged:
        git_arguments.append("--cached")
    git_arguments.extend(["--", *paths])
    result = _run_git(root_path, git_arguments, timeout=30)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise ToolError(f"No se pudo consultar la diferencia Git. {detail}".strip())
    diff = result.stdout
    return {
        "ok": True,
        "action": "git_diff",
        "root": root_name,
        "staged": staged,
        "paths": paths,
        "diff": diff[:GIT_MAX_OUTPUT_CHARS],
        "truncated": len(diff) > GIT_MAX_OUTPUT_CHARS,
    }


def _git_log(arguments: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path = _git_repository(arguments)
    try:
        max_entries = int(arguments.get("max_entries", 10))
    except (TypeError, ValueError) as error:
        raise ToolError("max_entries debe ser un número entero.") from error
    max_entries = max(1, min(max_entries, GIT_MAX_LOG_ENTRIES))
    paths = _git_pathspecs(arguments, root_path)
    git_arguments = [
        "log",
        f"-n{max_entries}",
        "--date=iso-strict",
        "--pretty=format:%H%x09%ad%x09%an%x09%s",
        "--no-decorate",
        "--no-color",
        "--",
        *paths,
    ]
    result = _run_git(root_path, git_arguments, timeout=20)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise ToolError(f"No se pudo consultar el historial Git. {detail}".strip())

    commits: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        fields = line.split("\t", 3)
        if len(fields) != 4:
            continue
        commits.append(
            {
                "id": fields[0],
                "date": fields[1],
                "author": fields[2],
                "subject": fields[3],
            }
        )
    return {
        "ok": True,
        "action": "git_log",
        "root": root_name,
        "paths": paths,
        "commits": commits,
        "count": len(commits),
    }


def _redact_git_text(value: Any) -> str:
    text = str(value or "")
    for candidate in re.findall(r"https?://[^\s]+", text):
        try:
            parsed = urlsplit(candidate.rstrip(".,);]"))
            if parsed.username or parsed.password:
                safe = urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, parsed.query, parsed.fragment))
                text = text.replace(candidate, safe)
        except ValueError:
            continue
    text = re.sub(r"(https?://)([^\s/@:]+):([^\s/@]+)@", r"\1***:***@", text)
    return text


def _git_remote_name(value: Any) -> str:
    name = str(value or "origin").strip()
    if not name or len(name) > 80 or not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise ToolError("El nombre del remoto Git no es válido.")
    return name


def _git_ref_name(value: Any, *, label: str = "rama") -> str:
    name = str(value or "").strip()
    if not name or len(name) > 200 or "\x00" in name or name.startswith("-"):
        raise ToolError(f"El nombre de {label} no es válido.")
    checked = _run_git(Path.cwd(), ["check-ref-format", "--branch", name], timeout=10)
    if checked.returncode != 0:
        detail = _redact_git_text((checked.stderr or checked.stdout).strip()[:300])
        raise ToolError(f"El nombre de {label} no es válido en Git. {detail}".strip())
    return name


def _git_remote_url(root_path: Path, remote: str) -> str:
    result = _run_git(root_path, ["remote", "get-url", remote], timeout=10)
    if result.returncode != 0:
        raise ToolError(f"El remoto Git '{remote}' no existe en esta raíz.")
    return _redact_git_text(result.stdout.strip())


def _git_current_branch(root_path: Path) -> str:
    result = _run_git(root_path, ["symbolic-ref", "--quiet", "--short", "HEAD"], timeout=10)
    if result.returncode != 0 or not result.stdout.strip():
        raise ToolError("El repositorio está en detached HEAD; indica una rama explícita.")
    return result.stdout.strip()


def _git_remote_status(arguments: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path = _git_repository(arguments)
    remote_result = _run_git(root_path, ["remote", "-v"], timeout=10)
    if remote_result.returncode != 0:
        raise ToolError("No se pudieron consultar los remotos Git.")
    remotes: dict[str, dict[str, str]] = {}
    for line in remote_result.stdout.splitlines():
        fields = line.split("\t", 1)
        if len(fields) != 2:
            continue
        name, rest = fields
        url, _, kind = rest.rpartition(" (")
        remotes.setdefault(name, {})[kind.rstrip(")")] = _redact_git_text(url)
    branch_result = _run_git(
        root_path,
        ["for-each-ref", "refs/heads", "--format=%(HEAD)\t%(refname:short)\t%(upstream:short)\t%(objectname:short)"],
        timeout=10,
    )
    branches = []
    for line in branch_result.stdout.splitlines():
        head, name, upstream, commit = (line.split("\t") + ["", "", "", ""])[:4]
        branches.append({"current": head == "*", "name": name, "upstream": upstream, "commit": commit})
    return {
        "ok": True,
        "action": "git_remote_status",
        "root": root_name,
        "remotes": [{"name": name, **values} for name, values in sorted(remotes.items())],
        "branches": branches,
        "network_contacted": False,
    }


def _prepare_git_remote_action(arguments: dict[str, Any], operation: str) -> dict[str, Any]:
    root_name, root_path = _git_repository(arguments)
    state = _git_status_state(root_path)
    if operation == "git_branch":
        branch_operation = str(arguments.get("operation", "create")).strip().casefold()
        if branch_operation not in {"create", "switch"}:
            raise ToolError("La operación de rama debe ser create o switch.")
        branch = _git_ref_name(arguments.get("branch"), label="rama")
        action = {
            "kind": "git_branch",
            "root": root_name,
            "operation": branch_operation,
            "branch": branch,
            "head_before": state["head"],
            "status_hash": state["hash"],
        }
        if branch_operation == "create":
            start_point = str(arguments.get("start_point", "HEAD")).strip() or "HEAD"
            if len(start_point) > 200 or start_point.startswith("-"):
                raise ToolError("El punto de partida de la rama no es válido.")
            action["start_point"] = start_point
        return action
    remote = _git_remote_name(arguments.get("remote", "origin"))
    remote_url = _git_remote_url(root_path, remote)
    action: dict[str, Any] = {
        "kind": operation,
        "root": root_name,
        "remote": remote,
        "remote_url": remote_url,
        "head_before": state["head"],
        "status_hash": state["hash"],
    }
    if operation in {"git_remote_pull", "git_remote_push"}:
        branch = str(arguments.get("branch", "")).strip() or _git_current_branch(root_path)
        action["branch"] = _git_ref_name(branch)
    if operation == "git_remote_push":
        action["set_upstream"] = bool(arguments.get("set_upstream", False))
        if bool(arguments.get("force", False)):
            raise ToolError("force push está bloqueado en MyKOS.")
    return action


def _execute_git_remote_action(action: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path = _git_repository(action)
    operation = str(action.get("kind", ""))
    with GIT_LOCK:
        if operation in {"git_remote_pull", "git_remote_push", "git_branch"}:
            state = _git_status_state(root_path)
            if action.get("head_before", "") != state["head"] or action.get("status_hash", "") != state["hash"]:
                raise ToolError("El estado Git cambió desde la aprobación; revisa de nuevo antes de continuar.")
        remote = _git_remote_name(action.get("remote", "origin")) if operation != "git_branch" else ""
        if operation == "git_remote_fetch":
            command = ["fetch", "--no-tags", remote]
        elif operation == "git_remote_pull":
            command = ["pull", "--ff-only", remote, _git_ref_name(action.get("branch"))]
        elif operation == "git_remote_push":
            command = ["push"]
            if action.get("set_upstream"):
                command.append("--set-upstream")
            command.extend([remote, _git_ref_name(action.get("branch"))])
        elif operation == "git_branch":
            branch = _git_ref_name(action.get("branch"), label="rama")
            if action.get("operation") == "create":
                command = ["switch", "--create", branch, str(action.get("start_point", "HEAD"))]
            else:
                current = _git_current_branch(root_path)
                if current == branch:
                    return {"ok": True, "action": "git_branch", "root": root_name, "branch": branch, "unchanged": True}
                command = ["switch", branch]
        else:
            raise ToolError("Operación Git remota desconocida.")
        result = _run_git(root_path, command, timeout=GIT_REMOTE_TIMEOUT_SECONDS)
        if result.returncode != 0:
            detail = _redact_git_text((result.stderr or result.stdout).strip()[-1_200:])
            raise ToolError(f"Git no pudo completar la operación. {detail}".strip())
        after = _git_status_state(root_path)
        return {
            "ok": True,
            "action": operation,
            "root": root_name,
            "remote": remote or None,
            "branch": str(action.get("branch", "")),
            "head": after["head"],
            "output": _redact_git_text((result.stdout or result.stderr).strip())[-4_000:],
            "status": after["raw"][:GIT_MAX_OUTPUT_CHARS],
        }


def _normalise_git_commit_message(raw_message: Any) -> str:
    if not isinstance(raw_message, str) or not raw_message.strip():
        raise ToolError("El commit necesita un mensaje.")
    message = raw_message.strip()
    if len(message) > GIT_MAX_COMMIT_MESSAGE_CHARS:
        raise ToolError(
            f"El mensaje del commit supera el límite de {GIT_MAX_COMMIT_MESSAGE_CHARS} caracteres."
        )
    if "\x00" in message:
        raise ToolError("El mensaje del commit contiene un carácter no válido.")
    return message


def _prepare_git_commit(arguments: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path = _git_repository(arguments)
    message = _normalise_git_commit_message(arguments.get("message"))
    paths = _git_pathspecs(arguments, root_path)
    stage_all = bool(arguments.get("stage_all", False))
    if stage_all and paths:
        raise ToolError("Elige stage_all=true o una lista de paths, no ambas opciones.")

    state = _git_status_state(root_path)
    changes = _git_status_changes(state["raw"])
    if stage_all and not changes:
        raise ToolError("No hay cambios para preparar en el repositorio.")
    if paths:
        selected = _run_git(
            root_path,
            ["status", "--short", "--untracked-files=all", "--", *paths],
            timeout=20,
        )
        if selected.returncode != 0:
            detail = (selected.stderr or selected.stdout).strip()[:500]
            raise ToolError(f"No se pudo revisar el alcance del commit. {detail}".strip())
        if not selected.stdout.strip():
            raise ToolError("Las rutas indicadas no tienen cambios para incluir.")
    elif not stage_all:
        cached = _run_git(root_path, ["diff", "--cached", "--quiet", "--"], timeout=20)
        if cached.returncode == 0:
            raise ToolError("No hay cambios preparados. Indica paths o stage_all=true.")
        if cached.returncode != 1:
            detail = (cached.stderr or cached.stdout).strip()[:500]
            raise ToolError(f"No se pudo revisar el índice Git. {detail}".strip())

    stat_paths = paths
    return {
        "kind": "git_commit",
        "root": root_name,
        "message": message,
        "paths": paths,
        "stage_all": stage_all,
        "stage_mode": "todos los cambios actuales" if stage_all else (
            "rutas seleccionadas" if paths else "solo cambios ya preparados"
        ),
        "status_hash": state["hash"],
        "head_before": state["head"],
        "status_preview": state["raw"][:GIT_MAX_OUTPUT_CHARS],
        "status_truncated": len(state["raw"]) > GIT_MAX_OUTPUT_CHARS,
        "staged_stat": _git_diff_stat(root_path, staged=True, paths=stat_paths),
        "unstaged_stat": _git_diff_stat(root_path, staged=False, paths=stat_paths),
    }


def _execute_git_commit(action: dict[str, Any]) -> dict[str, Any]:
    root_name, root_path = _git_repository(action)
    message = _normalise_git_commit_message(action.get("message"))
    paths = _git_pathspecs(action, root_path)
    stage_all = bool(action.get("stage_all", False))
    if stage_all and paths:
        raise ToolError("La acción Git no puede combinar stage_all con paths.")

    with GIT_LOCK:
        state = _git_status_state(root_path)
        expected_hash = str(action.get("status_hash", ""))
        expected_head = str(action.get("head_before", ""))
        if expected_hash and state["hash"] != expected_hash:
            raise ToolError("El estado Git cambió desde la revisión; no se hará el commit.")
        if expected_head != state["head"]:
            raise ToolError("La rama cambió desde la revisión; no se hará el commit.")

        if stage_all:
            added = _run_git(root_path, ["add", "--all"], timeout=30)
        elif paths:
            added = _run_git(root_path, ["add", "--all", "--", *paths], timeout=30)
        else:
            added = None
        if added is not None and added.returncode != 0:
            detail = (added.stderr or added.stdout).strip()[:800]
            raise ToolError(f"Git no pudo preparar los cambios. {detail}".strip())

        cached = _run_git(root_path, ["diff", "--cached", "--quiet", "--"], timeout=20)
        if cached.returncode == 0:
            raise ToolError("No quedan cambios preparados para el commit.")
        if cached.returncode != 1:
            detail = (cached.stderr or cached.stdout).strip()[:500]
            raise ToolError(f"No se pudo comprobar el índice Git. {detail}".strip())

        commit_arguments = ["commit", "-m", message]
        if paths:
            commit_arguments.extend(["--", *paths])
        committed = _run_git(root_path, commit_arguments, timeout=60)
        if committed.returncode != 0:
            detail = (committed.stderr or committed.stdout).strip()[-1_200:]
            raise ToolError(f"Git no pudo crear el commit. {detail}".strip())

        after = _git_status_state(root_path)
        head_after = after["head"]
        files = _run_git(
            root_path,
            ["diff-tree", "--root", "--no-commit-id", "--name-status", "-r", head_after],
            timeout=20,
        )
        committed_files = [line for line in files.stdout.splitlines() if line.strip()]
        branch_lines = after["raw"].splitlines()
        branch = branch_lines[0][2:].strip() if branch_lines and branch_lines[0].startswith("##") else ""
        return {
            "ok": True,
            "action": "git_commit",
            "root": root_name,
            "commit": head_after,
            "message": message,
            "branch": branch,
            "paths": paths,
            "stage_all": stage_all,
            "committed_files": committed_files[:GIT_MAX_PATHS],
            "remaining_status": after["raw"],
            "clean": not _git_status_changes(after["raw"]),
        }


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


def _validate_web_url(raw_url: Any) -> str:
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise ToolError("Debes indicar una URL pública.")
    url = raw_url.strip()
    if len(url) > 2_000:
        raise ToolError("La URL es demasiado larga.")
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ToolError("Solo se permiten URLs http o https con un host público.")
    if parsed.username or parsed.password:
        raise ToolError("No se permiten URLs con usuario o contraseña incorporados.")
    try:
        port = parsed.port
    except ValueError as error:
        raise ToolError("La URL contiene un puerto no válido.") from error

    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
        raise ToolError("Por seguridad, no se permiten hosts locales o internos.")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            resolved = socket.getaddrinfo(host, port or (443 if parsed.scheme.lower() == "https" else 80), type=socket.SOCK_STREAM)
            addresses = {ipaddress.ip_address(item[4][0]) for item in resolved}
        except (OSError, ValueError) as error:
            raise ToolError("No se pudo resolver el host de la URL.") from error
    if not addresses or any(not address.is_global for address in addresses):
        raise ToolError("Por seguridad, la URL apunta a una red local, privada o no enrutable.")
    return parsed.geturl()


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        _validate_web_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _download_web_page(url: str) -> tuple[str, str, str, bytes]:
    validated_url = _validate_web_url(url)
    request = urllib.request.Request(
        validated_url,
        headers={
            "Accept": "text/html, application/xhtml+xml, text/plain;q=0.9, */*;q=0.1",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
            "User-Agent": WEB_USER_AGENT,
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    try:
        with opener.open(request, timeout=WEB_REQUEST_TIMEOUT_SECONDS) as response:
            final_url = _validate_web_url(response.geturl())
            content_type = response.headers.get_content_type().lower()
            if content_type not in {"text/html", "application/xhtml+xml", "text/plain", "text/xml", "application/xml"}:
                raise ToolError(f"La URL devuelve contenido no textual ({content_type}).")
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > WEB_MAX_BYTES:
                        raise ToolError(f"La página supera el límite de {WEB_MAX_BYTES // (1024 * 1024)} MB.")
                except ValueError:
                    pass
            raw = response.read(WEB_MAX_BYTES + 1)
            if len(raw) > WEB_MAX_BYTES:
                raise ToolError(f"La página supera el límite de {WEB_MAX_BYTES // (1024 * 1024)} MB.")
            charset = response.headers.get_content_charset() or "utf-8"
    except ToolError:
        raise
    except urllib.error.HTTPError as error:
        raise ToolError(f"La fuente web devolvió HTTP {error.code}.") from error
    except urllib.error.URLError as error:
        raise ToolError(f"No se pudo abrir la fuente web: {error.reason}.") from error
    except (OSError, TimeoutError) as error:
        raise ToolError(f"La petición web no pudo completarse: {error}.") from error
    return final_url, content_type, charset, raw


class _WebTextParser(HTMLParser):
    _skip_tags = {"script", "style", "noscript", "svg", "template", "nav", "footer", "header", "form"}
    _block_tags = {"article", "aside", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "main", "p", "section", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.skip_depth = 0
        self.title_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._skip_tags:
            self.skip_depth += 1
        if tag == "title":
            self.title_depth += 1
        if tag in self._block_tags and self.skip_depth == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self.title_depth:
            self.title_depth -= 1
        if tag in self._skip_tags and self.skip_depth:
            self.skip_depth -= 1
        if tag in self._block_tags and self.skip_depth == 0:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.title_depth:
            self.title_parts.append(data)
        elif self.skip_depth == 0:
            self.parts.append(data)


class _DuckDuckGoLiteParser(HTMLParser):
    """Extract result links and snippets from DuckDuckGo Lite HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._link_result: dict[str, str] | None = None
        self._in_link = False
        self._in_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set(str(attributes.get("class", "")).split())
        if tag.lower() == "a" and "result-link" in classes:
            self._link_result = {
                "url": _decode_search_url(str(attributes.get("href", ""))),
                "title": "",
                "snippet": "",
            }
            self._in_link = True
        elif "result-snippet" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._in_link:
            if self._link_result and self._link_result.get("url"):
                self.results.append(self._link_result)
            self._link_result = None
            self._in_link = False
        if self._in_snippet:
            self._in_snippet = False

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._in_link and self._link_result is not None:
            self._link_result["title"] += text
        elif self._in_snippet and self.results:
            current = self.results[-1]
            current["snippet"] = f"{current.get('snippet', '')} {text}".strip()


def _decode_search_url(raw_url: str) -> str:
    absolute = urljoin("https://html.duckduckgo.com", raw_url.strip())
    parsed = urlparse(absolute)
    encoded = parse_qs(parsed.query).get("uddg", [""])[0]
    candidate = unquote(encoded or absolute)
    candidate_parsed = urlparse(candidate)
    if candidate_parsed.scheme.lower() not in {"http", "https"} or not candidate_parsed.hostname:
        return ""
    return candidate_parsed.geturl()


def _web_search(arguments: dict[str, Any]) -> dict[str, Any]:
    raw_query = arguments.get("query")
    if not isinstance(raw_query, str) or not raw_query.strip():
        raise ToolError("Debes indicar qué quieres buscar en la web.")
    query = raw_query.strip()
    if len(query) > 200:
        raise ToolError("La búsqueda no puede superar 200 caracteres.")
    try:
        max_results = int(arguments.get("max_results", WEB_MAX_RESULTS))
    except (TypeError, ValueError) as error:
        raise ToolError("max_results debe ser un número entero.") from error
    max_results = max(1, min(max_results, WEB_MAX_RESULTS))
    search_url = f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}"
    final_url, _content_type, charset, raw = _download_web_page(search_url)
    try:
        parser = _DuckDuckGoLiteParser()
        parser.feed(raw.decode(charset, errors="replace"))
        parser.close()
    except (LookupError, UnicodeError) as error:
        raise ToolError("No se pudo interpretar la respuesta del buscador.") from error

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in parser.results:
        source_url = str(item.get("url", "")).strip()
        if not source_url or source_url in seen_urls:
            continue
        seen_urls.add(source_url)
        results.append({
            "title": (str(item.get("title", "")) or source_url).strip(),
            "url": source_url,
            "snippet": re.sub(r"\s+", " ", str(item.get("snippet", ""))).strip(),
        })
        if len(results) >= max_results:
            break
    return {
        "ok": True,
        "action": "web_search",
        "query": query,
        "provider": "DuckDuckGo Lite",
        "searched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": results,
        "result_count": len(results),
        "search_url": final_url,
    }


def _web_fetch(arguments: dict[str, Any]) -> dict[str, Any]:
    url = _validate_web_url(arguments.get("url"))
    try:
        max_chars = int(arguments.get("max_chars", WEB_MAX_TEXT_CHARS))
    except (TypeError, ValueError) as error:
        raise ToolError("max_chars debe ser un número entero.") from error
    max_chars = max(1_000, min(max_chars, WEB_MAX_TEXT_CHARS))
    final_url, content_type, charset, raw = _download_web_page(url)
    try:
        decoded = raw.decode(charset, errors="replace")
    except LookupError:
        decoded = raw.decode("utf-8", errors="replace")

    title = ""
    if content_type in {"text/html", "application/xhtml+xml", "text/xml", "application/xml"}:
        parser = _WebTextParser()
        parser.feed(decoded)
        parser.close()
        title = re.sub(r"\s+", " ", "".join(parser.title_parts)).strip()
        lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
        text = "\n".join(line for line in lines if line)
    else:
        text = re.sub(r"\s+", " ", decoded).strip()
    if not title:
        title = final_url
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars].rstrip() + "…"
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "ok": True,
        "action": "web_fetch",
        "source": {"title": title, "url": final_url, "fetched_at": fetched_at},
        "title": title,
        "url": final_url,
        "fetched_at": fetched_at,
        "content_type": content_type,
        "text": text,
        "text_chars": len(text),
        "truncated": truncated,
    }


def _ollama_request_json(
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    method: str | None = None,
    timeout: int = OLLAMA_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    request_method = method or ("POST" if payload is not None else "GET")
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{OLLAMA_URL}{path}",
        data=body,
        headers=headers,
        method=request_method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ToolError(f"Ollama devolvió HTTP {error.code}: {detail[:500]}") from error
    except urllib.error.URLError as error:
        raise ToolError(
            f"No se puede conectar con Ollama en {OLLAMA_URL}. Comprueba que Ollama esté iniciado."
        ) from error
    except (OSError, TimeoutError) as error:
        raise ToolError(f"La petición a Ollama no pudo completarse: {error}") from error

    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
        for line in reversed(raw.decode("utf-8", errors="replace").splitlines()):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        if parsed is None:
            raise ToolError("Ollama devolvió una respuesta que no es JSON válido.")
    if not isinstance(parsed, dict):
        raise ToolError("Ollama devolvió un formato de respuesta inesperado.")
    return parsed


def _normalise_ollama_model_name(raw_model: Any) -> str:
    if not isinstance(raw_model, str) or not raw_model.strip():
        raise ToolError("Debes indicar el nombre del modelo de Ollama.")
    model = raw_model.strip()
    if len(model) > OLLAMA_MODEL_NAME_CHARS or "\x00" in model:
        raise ToolError("El nombre del modelo de Ollama es demasiado largo o contiene caracteres no válidos.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", model):
        raise ToolError("El nombre del modelo solo puede contener letras, números, punto, dos puntos, barra, guion y guion bajo.")
    return model


def _ollama_model_summary(raw_model: dict[str, Any]) -> dict[str, Any]:
    details = raw_model.get("details") or {}
    capabilities = [str(item) for item in (raw_model.get("capabilities") or [])]
    name = str(raw_model.get("name", ""))
    remote = bool(
        raw_model.get("remote_model")
        or raw_model.get("remote_host")
        or name.endswith(":cloud")
    )
    return {
        "name": name,
        "size": raw_model.get("size", 0),
        "parameter_size": details.get("parameter_size", ""),
        "family": details.get("family", ""),
        "quantization": details.get("quantization_level", ""),
        "modified_at": raw_model.get("modified_at", ""),
        "capabilities": capabilities,
        "chat_capable": not capabilities or bool({"chat", "completion"}.intersection(capabilities)),
        "vision_capable": "vision" in capabilities,
        "remote": remote,
        "remote_host": raw_model.get("remote_host", ""),
    }


def _list_ollama_models() -> dict[str, Any]:
    result = _ollama_request_json("/api/tags")
    raw_models = result.get("models", [])
    if not isinstance(raw_models, list):
        raw_models = []
    models = [
        _ollama_model_summary(model)
        for model in raw_models
        if isinstance(model, dict) and str(model.get("name", "")).strip()
    ]
    return {
        "ok": True,
        "action": "list_ollama_models",
        "ollama_url": OLLAMA_URL,
        "count": len(models),
        "models": models,
    }


def _find_ollama_model(model_name: str, models_result: dict[str, Any]) -> dict[str, Any] | None:
    for model in models_result.get("models", []):
        if isinstance(model, dict) and str(model.get("name", "")) == model_name:
            return model
    return None


def _prepare_pull_ollama_model(arguments: dict[str, Any]) -> dict[str, Any]:
    model_name = _normalise_ollama_model_name(arguments.get("model"))
    current = _list_ollama_models()
    existing = _find_ollama_model(model_name, current)
    return {
        "kind": "pull_ollama_model",
        "model": model_name,
        "ollama_url": OLLAMA_URL,
        "already_installed": existing is not None,
        "current_size": existing.get("size", 0) if existing else 0,
    }


def _prepare_delete_ollama_model(arguments: dict[str, Any]) -> dict[str, Any]:
    model_name = _normalise_ollama_model_name(arguments.get("model"))
    current = _list_ollama_models()
    existing = _find_ollama_model(model_name, current)
    if existing is None:
        raise ToolError(f"El modelo '{model_name}' no está instalado en Ollama.")
    return {
        "kind": "delete_ollama_model",
        "model": model_name,
        "ollama_url": OLLAMA_URL,
        "size": existing.get("size", 0),
        "capabilities": existing.get("capabilities", []),
    }


def execute_ollama_pull_with_progress(
    action: dict[str, Any],
    progress_callback: Any = None,
) -> dict[str, Any]:
    model_name = _normalise_ollama_model_name(action.get("model"))
    payload = json.dumps({"name": model_name, "stream": True}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/pull",
        data=payload,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    last_event: dict[str, Any] = {}
    with OLLAMA_LOCK:
        try:
            with urllib.request.urlopen(request, timeout=OLLAMA_PULL_TIMEOUT_SECONDS) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as error:
                        raise ToolError("Ollama devolvió un progreso de descarga no válido.") from error
                    if not isinstance(event, dict):
                        continue
                    last_event = event
                    if progress_callback is not None:
                        progress_callback(event)
                    if event.get("error"):
                        raise ToolError(f"Ollama no pudo descargar el modelo: {event['error']}")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise ToolError(f"Ollama devolvió HTTP {error.code}: {detail[:500]}") from error
        except urllib.error.URLError as error:
            raise ToolError(
                f"No se puede conectar con Ollama en {OLLAMA_URL}. Comprueba que Ollama esté iniciado."
            ) from error
        except (OSError, TimeoutError) as error:
            raise ToolError(f"La descarga de Ollama no pudo completarse: {error}") from error
        current = _list_ollama_models()
        installed = _find_ollama_model(model_name, current)
    if installed is None:
        raise ToolError("Ollama terminó la descarga, pero el modelo no aparece en el listado posterior.")
    return {
        "ok": True,
        "action": "pull_ollama_model",
        "model": model_name,
        "status": last_event.get("status", "success"),
        "model_info": installed,
    }


def _execute_pull_ollama_model(action: dict[str, Any]) -> dict[str, Any]:
    return execute_ollama_pull_with_progress(action)


def _execute_delete_ollama_model(action: dict[str, Any]) -> dict[str, Any]:
    model_name = _normalise_ollama_model_name(action.get("model"))
    with OLLAMA_LOCK:
        current = _list_ollama_models()
        if _find_ollama_model(model_name, current) is None:
            raise ToolError(f"El modelo '{model_name}' ya no está instalado; no se borrará nada.")
        response = _ollama_request_json(
            "/api/delete",
            {"name": model_name},
            method="DELETE",
            timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS,
        )
        remaining = _list_ollama_models()
    if _find_ollama_model(model_name, remaining) is not None:
        raise ToolError("Ollama respondió correctamente, pero el modelo sigue apareciendo en el listado.")
    return {
        "ok": True,
        "action": "delete_ollama_model",
        "model": model_name,
        "status": response.get("status", "success"),
        "remaining_models": remaining.get("models", []),
    }


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


def _prepare_run_powershell(arguments: dict[str, Any]) -> dict[str, Any]:
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ToolError("Debes indicar un comando.")
    command = command.strip()
    if len(command) > MAX_COMMAND_CHARS:
        raise ToolError(f"El comando supera el límite de {MAX_COMMAND_CHARS} caracteres.")
    if "\x00" in command:
        raise ToolError("El comando contiene un carácter no válido.")

    cwd_root, cwd_root_path, cwd_path = _resolve_project_path(
        arguments.get("cwd_root", "mykos"), arguments.get("cwd_path", "")
    )
    if not cwd_path.is_dir():
        raise ToolError("El directorio de trabajo no existe.")
    try:
        timeout_seconds = int(arguments.get("timeout_seconds", 30))
    except (TypeError, ValueError) as error:
        raise ToolError("timeout_seconds debe ser un número entero.") from error
    timeout_seconds = max(1, min(timeout_seconds, MAX_COMMAND_TIMEOUT))

    return {
        "kind": "run_powershell",
        "command": command,
        "cwd_root": cwd_root,
        "cwd_path": _relative_label(cwd_path, cwd_root_path),
        "timeout_seconds": timeout_seconds,
    }


def _prepare_rea_call_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(arguments.get("tool_name", "")).strip()
    tool_args = arguments.get("arguments") if isinstance(arguments.get("arguments"), dict) else {}
    if not tool_name:
        raise ToolError("Debes indicar el nombre de la herramienta de REA (tool_name).")
    return {
        "kind": "rea_call_tool",
        "tool_name": tool_name,
        "arguments": tool_args,
        "summary": f"Ejecutar herramienta REA · {tool_name}",
    }


def analyze_action_risk(action: dict[str, Any]) -> tuple[str, str]:
    """Analiza heurísticamente el nivel de riesgo de una acción aprobable.

    Devuelve (risk_level, risk_warning):
    - 'critical': Acciones potencialmente destructivas, privilegios o modificación de núcleo.
    - 'warning': Modificaciones en mykos, eliminación de recuerdos/modelos o envío remoto.
    - 'normal': Operaciones estándar acotadas en workspace.
    """
    kind = str(action.get("kind", "")).strip()

    if kind == "run_powershell":
        cmd = str(action.get("command", "")).strip()
        cmd_lower = cmd.lower()
        if re.search(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|--recursive|--force)", cmd, re.IGNORECASE) or "rm -rf" in cmd_lower:
            return "critical", "Comando de borrado recursivo forzado (rm -rf)"
        if re.search(r"\b(mkfs|dd\s+if=|truncate\s+-s\s*0|shred\b)", cmd, re.IGNORECASE):
            return "critical", "Comando potencialmente destructivo para el almacenamiento o particiones"
        if re.search(r"\b(sudo\s+|su\s+-|chmod\s+(-R\s+)?777|chown\s+-R)", cmd, re.IGNORECASE):
            return "critical", "Ejecución con privilegios de superusuario o permisos inseguros (sudo / chmod 777)"
        if re.search(r"\b(curl|wget)\s+.*\|\s*(ba|z)?sh\b", cmd, re.IGNORECASE):
            return "critical", "Descarga e interpretación directa de script remoto por tubería (curl | sh)"
        if re.search(r"\b/(etc|boot|sys|proc|dev|root)\b", cmd):
            return "critical", "Comando que referencia directorios protegidos del sistema (/etc, /boot, /root)"
        if re.search(r"\b~/\.(bashrc|profile|zshrc|config/systemd)\b", cmd):
            return "warning", "Modificación de archivos de inicio del usuario (~/.bashrc, ~/.profile)"
        return "normal", ""

    if kind in {"write_file", "edit_file", "write_project_file", "edit_project_file"}:
        root = str(action.get("root", "")).strip()
        path = str(action.get("path", "")).strip().lower()
        if root == "mykos":
            core_files = {"server.py", "policy.js", "routes.js", "permissions.py", "index.js", "tools.py"}
            if any(path.endswith(cf) for cf in core_files):
                return "critical", f"Modificación directa de la infraestructura crítica de MyKOS ({path})"
            return "warning", f"Escritura en el repositorio de código fuente de MyKOS ({path})"
        return "normal", ""

    if kind in {"stop_process", "stop_service"}:
        name = str(action.get("process_name") or action.get("service") or "").lower()
        if any(crit in name for crit in ["systemd", "dbus", "sshd", "xorg", "gnome", "wayland"]):
            return "critical", f"Detención de un servicio crítico del sistema ({name})"
        return "warning", f"Detención de proceso o servicio ({name})"

    if kind in {"delete_ollama_model", "delete_memory"}:
        return "warning", f"Eliminación permanente solicitada ({kind})"

    if kind == "git_remote_push":
        if bool(action.get("force")):
            return "critical", "Empuje forzado a repositorio remoto (git push --force)"
        return "warning", "Envío de cambios a repositorio remoto (git push)"

    return "normal", ""


def prepare_approval_action(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    arguments = arguments if isinstance(arguments, dict) else {}
    try:
        res: dict[str, Any]
        if name == "save_memory":
            res = {"ok": True, "action": _prepare_save_memory(arguments)}
        elif name == "delete_memory":
            res = {"ok": True, "action": _prepare_delete_memory(arguments)}
        elif name == "write_project_file":
            res = {"ok": True, "action": _prepare_write_project_file(arguments)}
        elif name == "edit_project_file":
            res = {"ok": True, "action": _prepare_edit_project_file(arguments)}
        elif name == "save_research_note":
            res = {"ok": True, "action": _prepare_save_research_note(arguments)}
        elif name == "run_powershell":
            res = {"ok": True, "action": _prepare_run_powershell(arguments)}
        elif name == "git_commit":
            res = {"ok": True, "action": _prepare_git_commit(arguments)}
        elif name == "git_remote_fetch":
            res = {"ok": True, "action": _prepare_git_remote_action(arguments, "git_remote_fetch")}
        elif name == "git_remote_pull":
            res = {"ok": True, "action": _prepare_git_remote_action(arguments, "git_remote_pull")}
        elif name == "git_remote_push":
            res = {"ok": True, "action": _prepare_git_remote_action(arguments, "git_remote_push")}
        elif name == "git_branch":
            res = {"ok": True, "action": _prepare_git_remote_action(arguments, "git_branch")}
        elif name == "pull_ollama_model":
            res = {"ok": True, "action": _prepare_pull_ollama_model(arguments)}
        elif name == "delete_ollama_model":
            res = {"ok": True, "action": _prepare_delete_ollama_model(arguments)}
        elif name == "stop_process":
            res = {"ok": True, "action": _prepare_stop_process(arguments)}
        elif name == "start_service":
            res = {"ok": True, "action": _prepare_service_action(arguments, "start_service", "stopped")}
        elif name == "stop_service":
            res = {"ok": True, "action": _prepare_service_action(arguments, "stop_service", "running")}
        elif name == "create_reminder":
            res = {"ok": True, "action": prepare_create(arguments)}
        elif name == "delete_reminder":
            res = {"ok": True, "action": prepare_delete(arguments)}
        elif name == "spawn_subagent":
            res = {"ok": True, "action": prepare_spawn(arguments)}
        elif name == "text_to_speech":
            res = {"ok": True, "action": prepare_text_to_speech(arguments)}
        elif name == "generate_image":
            res = {"ok": True, "action": prepare_generate_image(arguments)}
        elif name == "generate_video":
            res = {"ok": True, "action": prepare_generate_video(arguments)}
        elif name == "pair_node":
            res = {"ok": True, "action": prepare_pair_node(arguments)}
        elif name == "revoke_node":
            res = {"ok": True, "action": prepare_revoke_node(arguments)}
        elif name == "rea_call_tool":
            res = {"ok": True, "action": _prepare_rea_call_tool(arguments)}
        else:
            return {"ok": False, "error": f"No existe una acción aprobable llamada: {name}"}

        if res.get("ok") and isinstance(res.get("action"), dict):
            risk_level, risk_warning = analyze_action_risk(res["action"])
            res["action"]["risk_level"] = risk_level
            res["action"]["risk_warning"] = risk_warning
        return res
    except ToolError as error:
        return {"ok": False, "error": str(error)}
    except (OSError, RuntimeError) as error:
        return {"ok": False, "error": f"No se pudo preparar la acción: {error}"}


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


def _desktop_session_environment() -> dict[str, str]:
    """Variables de la sesión gráfica de Usuario, para que un comando aprobado pueda abrir ventanas.

    El backend arranca con un HOME propio y sin DISPLAY; se toman de un proceso del escritorio del
    mismo usuario. Si no hay sesión gráfica, se devuelve solo lo que se pueda deducir.
    """
    import pwd

    uid = os.getuid()
    wanted = ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
              "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "XDG_DATA_DIRS", "LANG")
    found: dict[str, str] = {}
    for name in ("gnome-shell", "plasmashell", "xfce4-session", "cinnamon", "gnome-session-binary"):
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                if proc.stat().st_uid != uid or (proc / "comm").read_text().strip() != name[:15]:
                    continue
                raw = (proc / "environ").read_bytes().split(b"\0")
            except OSError:
                continue
            for item in raw:
                key, _, value = item.decode("utf-8", "replace").partition("=")
                if key in wanted and value:
                    found.setdefault(key, value)
            if "DISPLAY" in found or "WAYLAND_DISPLAY" in found:
                break
        if "DISPLAY" in found or "WAYLAND_DISPLAY" in found:
            break
    runtime_dir = Path(f"/run/user/{uid}")
    if runtime_dir.is_dir():
        found.setdefault("XDG_RUNTIME_DIR", str(runtime_dir))
        if (runtime_dir / "bus").exists():
            found.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir / 'bus'}")
    try:
        found["HOME"] = pwd.getpwuid(uid).pw_dir
    except KeyError:
        pass
    return found


def _execute_run_shell_posix(action: dict[str, Any], cwd_root: str, cwd_root_path: Path, cwd_path: Path, timeout_seconds: int) -> dict[str, Any]:
    """Ejecuta en Linux/macOS, con bash, el comando ya aprobado por el usuario."""
    shell = shutil.which("bash") or "/bin/sh"
    environment = {
        k: v
        for k, v in os.environ.items()
        if (not re.search(r"(TOKEN|KEY|SECRET|PASSWORD|AUTH)", k, re.IGNORECASE)) or k in {"SSH_AUTH_SOCK", "GPG_AGENT_INFO"}
    }
    environment.update(_desktop_session_environment())
    # La salida va a ficheros temporales, no a tuberías: un programa gráfico lanzado por el comando
    # (p. ej. el gestor de archivos tras xdg-open) hereda la salida y dejaría la llamada colgada.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        timed_out = False
        try:
            process = subprocess.Popen(
                [shell, "-c", action["command"]], cwd=str(cwd_path), stdin=subprocess.DEVNULL,
                stdout=out, stderr=err, env=environment, start_new_session=True,
            )
        except OSError as error:
            raise ToolError(f"No se pudo iniciar el comando: {error}") from error
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, 15)
            except OSError:
                pass
            returncode = None
        out.seek(0)
        err.seek(0)
        stdout = out.read().decode("utf-8", "replace")[-12_000:]
        stderr = err.read().decode("utf-8", "replace")[-12_000:]
    if timed_out:
        return {
            "ok": False, "action": "run_powershell", "shell": "bash", "timed_out": True,
            "timeout_seconds": timeout_seconds, "stdout": stdout,
            "stderr": "El comando superó el tiempo máximo de ejecución.",
        }
    return {
        "ok": returncode == 0, "action": "run_powershell", "shell": "bash",
        "cwd_root": cwd_root, "cwd_path": _relative_label(cwd_path, cwd_root_path),
        "returncode": returncode, "stdout": stdout, "stderr": stderr,
    }


def _execute_run_powershell(action: dict[str, Any]) -> dict[str, Any]:
    prepared = _prepare_run_powershell(action)
    action = prepared
    cwd_root, cwd_root_path, cwd_path = _resolve_project_path(
        action.get("cwd_root", "mykos"), action.get("cwd_path", "")
    )
    timeout_seconds = int(action.get("timeout_seconds", 30))
    return _execute_run_shell_posix(action, cwd_root, cwd_root_path, cwd_path, timeout_seconds)


def execute_approved_action(action: dict[str, Any]) -> dict[str, Any]:
    try:
        kind = str(action.get("kind", ""))
        if kind == "save_memory":
            return _execute_save_memory(action)
        if kind == "delete_memory":
            return _execute_delete_memory(action)
        if kind == "write_file":
            return _execute_write_file(action)
        if kind == "edit_file":
            return _execute_edit_file(action)
        if kind == "research_note":
            return _execute_research_note(action)
        if kind == "run_powershell":
            return _execute_run_powershell(action)
        if kind == "git_commit":
            return _execute_git_commit(action)
        if kind in {"git_remote_fetch", "git_remote_pull", "git_remote_push", "git_branch"}:
            return _execute_git_remote_action(action)
        if kind == "pull_ollama_model":
            return _execute_pull_ollama_model(action)
        if kind == "delete_ollama_model":
            return _execute_delete_ollama_model(action)
        if kind == "stop_process":
            return _execute_stop_process(action)
        if kind == "start_service":
            return _execute_service_action(action, "start", "running")
        if kind == "stop_service":
            return _execute_service_action(action, "stop", "stopped")
        if kind == "create_reminder":
            return create_approved(action)
        if kind == "delete_reminder":
            return delete_approved(action)
        if kind == "spawn_subagent":
            return spawn_approved(action)
        if kind == "text_to_speech":
            return text_to_speech_approved(action)
        if kind == "generate_image":
            return generate_image_approved(action)
        if kind == "generate_video":
            return generate_video_approved(action)
        if kind == "pair_node":
            return pair_node_approved(action, endpoint="http://127.0.0.1:3210")
        if kind == "revoke_node":
            return revoke_node_approved(action)
        if kind == "rea_call_tool":
            t_name = str(action.get("tool_name", "")).strip()
            t_args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
            return rea_call_tool(t_name, t_args, allow_dynamic=True)
        return {"ok": False, "error": f"Tipo de acción desconocido: {kind}"}
    except ToolError as error:
        return {"ok": False, "error": str(error)}
    except (OSError, RuntimeError) as error:
        return {"ok": False, "error": f"No se pudo completar la acción: {error}"}


def _list_allowed_roots() -> dict[str, Any]:
    return {"ok": True, "roots": allowed_root_catalog()}


def execute_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    arguments = arguments if isinstance(arguments, dict) else {}
    try:
        if name in SENSITIVE_TOOL_NAMES:
            return {"ok": False, "requires_approval": True, "error": "Esta acción requiere aprobación explícita de Usuario."}
        if name == "search_project_files":
            return _search_project_files(arguments)
        if name == "find_project_paths":
            return _find_project_paths(arguments)
        if name == "get_local_status":
            return _get_local_status()
        if name == "list_processes":
            return _list_processes(arguments)
        if name == "list_services":
            return _list_services(arguments)
        if name == "git_status":
            return _git_status(arguments)
        if name == "git_diff":
            return _git_diff(arguments)
        if name == "git_log":
            return _git_log(arguments)
        if name == "git_remote_status":
            return _git_remote_status(arguments)
        if name == "read_pdf":
            return _read_pdf(arguments)
        if name == "read_image":
            return _read_image(arguments)
        if name == "read_document":
            return _read_document(arguments)
        if name == "list_ollama_models":
            return _list_ollama_models()
        if name == "search_memory":
            return _search_memory(arguments)
        if name == "read_memory":
            return _read_memory(arguments)
        if name == "list_memory":
            return _list_memory(arguments)
        if name == "list_project_files":
            return _list_project_files(arguments)
        if name == "read_project_file":
            return _read_project_file(arguments)
        if name == "list_allowed_roots":
            return _list_allowed_roots()
        if name == "web_search":
            return _web_search(arguments)
        if name == "web_fetch":
            return _web_fetch(arguments)
        if name == "browser_open":
            return browser_open(arguments)
        if name == "browser_snapshot":
            return browser_snapshot(arguments)
        if name == "browser_close":
            return browser_close()
        if name == "list_automations":
            return list_automations()
        if name == "list_automation_events":
            try:
                limit = int(arguments.get("limit", 50) or 50)
            except (TypeError, ValueError) as error:
                raise AutomationError("limit debe ser un número entero.") from error
            return list_events(limit)
        if name == "list_subagents":
            try:
                limit = int(arguments.get("limit", 50) or 50)
            except (TypeError, ValueError) as error:
                raise SubagentError("limit debe ser un número entero.") from error
            return list_jobs(limit)
        if name == "local_management_status":
            return local_status()
        if name == "media_status":
            return media_status()
        if name == "list_media":
            return list_media(arguments.get("limit", 100))
        if name == "list_nodes":
            return list_nodes()
        if name == "rea_status":
            return rea_status()
        if name == "rea_list_tools":
            return rea_list_tools(
                str(arguments.get("query", "") or ""),
                int(arguments.get("limit", 35) or 35),
            )
        if name == "rea_inspect_binary":
            raw_target = str(arguments.get("path", "") or "").strip()
            if not raw_target:
                raise ToolError("Debes indicar «path» (nombre del programa o ruta al binario).")
            target_p = Path(resolve_rea_target(raw_target))
            if _is_private_path(target_p):
                raise ToolError("No se permite inspeccionar directorios privados o credenciales de MyKOS.")
            return rea_inspect_binary(str(target_p))
        if name == "rea_analyze_javascript":
            raw_target = str(arguments.get("input_path", "") or "").strip()
            if not raw_target:
                raise ToolError("Debes indicar «input_path».")
            target_p = Path(resolve_rea_target(raw_target))
            if _is_private_path(target_p):
                raise ToolError("No se permite analizar directorios privados o credenciales de MyKOS.")
            return rea_analyze_javascript(str(target_p), str(arguments.get("detail", "summary") or "summary"))
        if name == "rea_call_tool":
            t_name = str(arguments.get("tool_name", "") or "").strip()
            t_args = arguments.get("arguments")
            if not isinstance(t_args, dict):
                t_args = {}
            for val in t_args.values():
                if isinstance(val, str) and ("/" in val or "\\" in val):
                    try:
                        cand = Path(val).expanduser().resolve()
                        if _is_private_path(cand):
                            raise ToolError("No se permite usar REA sobre rutas de credenciales de MyKOS.")
                    except OSError:
                        pass
            return rea_call_tool(t_name, t_args)
        return {"ok": False, "error": f"Herramienta desconocida: {name}"}
    except ToolError as error:
        return {"ok": False, "error": str(error)}
    except ReaError as error:
        return {"ok": False, "error": str(error)}
    except BrowserError as error:
        return {"ok": False, "error": str(error)}
    except AutomationError as error:
        return {"ok": False, "error": str(error)}
    except SubagentError as error:
        return {"ok": False, "error": str(error)}
    except (OSError, RuntimeError) as error:
        return {"ok": False, "error": f"No se pudo completar la herramienta: {error}"}


def encode_tool_result(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
