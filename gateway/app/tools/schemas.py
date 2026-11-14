"""Definiciones de esquemas de herramientas y catálogo de capacidades de MyKOS.
"""
from __future__ import annotations

from typing import Any

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
            "name": "search_cortex",
            "description": "Busca en la memoria y cerebro Cortex por palabras clave, proyectos o tags. Devuelve notas coincidentes con su título, ruta, fragmento relevante y tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Texto o palabras clave a buscar en las notas de Cortex.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Número máximo de resultados (por defecto 10).",
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
            "name": "read_cortex_note",
            "description": "Lee el contenido completo de una nota en Cortex mediante su ruta o título (por ejemplo '00 - Dashboard MyKOS.md' o 'Dashboard'). Devuelve el texto Markdown completo, tags y backlinks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa o nombre de la nota a leer (ej: '00 - Centro de Mando/00 - Dashboard MyKOS.md' o '04 - Bitácora y Diario/2026-11-11.md').",
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
            "name": "save_cortex_note",
            "description": "Crea o actualiza una nota Markdown en Cortex (tu cerebro y base de conocimiento local). Actualiza el grafo y los enlaces automáticamente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa del archivo .md en la bóveda (ej: '04 - Bitácora y Diario/Resumen-Chat.md' o 'Notas/Idea.md').",
                    },
                    "content": {
                        "type": "string",
                        "description": "Contenido completo de la nota en formato Markdown con enlaces [[wikilinks]] o tags si aplica.",
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
            "description": "Prepara la generación de una imagen digital en alta definición mediante difusión FLUX (servicio en la nube Pollinations.ai) a partir de una descripción en texto (prompt). Requiere aprobación explícita; la descripción se transmite a dicho servicio y el resultado se guarda en el almacén multimedia local de MyKOS.",
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
            "description": "Prepara la generación de un vídeo cinemático digital en formato MP4 mediante FLUX Motion (servicio en la nube Pollinations.ai) a partir de una descripción en texto (prompt) o imagen. Requiere aprobación explícita; la descripción se transmite a dicho servicio y el resultado se guarda en el almacén multimedia local de MyKOS.",
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
    {
        "type": "function",
        "function": {
            "name": "swarm_status",
            "description": "Consulta el estado actual del motor multi-agente MyKOS Swarm, el roster de agentes activos y los últimos mensajes del tablón.",
            "parameters": {
                "type": "object",
                "properties": {
                    "since_seq": {"type": "integer", "description": "Devolver solo mensajes posteriores a este #seq (0 por defecto)."},
                    "limit": {"type": "integer", "description": "Número máximo de mensajes recientes a devolver (por defecto 30)."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "swarm_add_worker",
            "description": "Crea o asigna un trabajador especialista en MyKOS Swarm, publica su misión (@nombre brief) en el tablón y lo despierta en paralelo con todas las herramientas de MyKOS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Identificador corto en minúsculas sin espacios (ej. investigador, implementador, verificador)."},
                    "role": {"type": "string", "description": "Rol o especialidad del trabajador (ej. Especialista en Seguridad)."},
                    "brief": {"type": "string", "description": "Misión clara: qué debe resolver, qué herramientas o archivos revisar y qué debe reportar."},
                    "model": {"type": "string", "description": "Modelo opcional (ej. openai/gpt-4o, claude-sonnet-oauth, qwen3:8b, o 'inherit')."},
                    "title": {"type": "string", "description": "Título opcional para la misión del Swarm."},
                },
                "required": ["name", "brief"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "swarm_post",
            "description": "Publica un mensaje en el tablón compartido del Swarm como coordinador (@nombre o @all despierta a los trabajadores) y opcionalmente espera hasta 45 s a que respondan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Mensaje con menciones (@nombre o @all) y referencias #seq."},
                    "wait_seconds": {"type": "number", "description": "Segundos opcionales a esperar (0 a 45) para recoger respuestas del equipo directamente."},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "swarm_read_board",
            "description": "Lee los mensajes publicados en el tablón del Swarm a partir de un #seq dado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "since_seq": {"type": "integer", "description": "Leer mensajes posteriores a #seq (0 para leer desde el principio)."},
                    "limit": {"type": "integer", "description": "Máximo de mensajes a devolver (por defecto 40)."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "swarm_kill",
            "description": "Detiene un trabajador específico del Swarm (o todos con name='all') y opcionalmente reinicia el tablón con reset=true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre del trabajador a detener o 'all' para detener a todos."},
                    "reset": {"type": "boolean", "description": "Si es true, detiene el Swarm activo y limpia el tablón para una nueva misión."},
                    "title": {"type": "string", "description": "Nuevo título opcional al reiniciar el Swarm."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "swarm_save_cortex",
            "description": "Compila el informe del Swarm actual (o un mensaje concreto #seq) en Markdown y lo guarda en MyKOS Cortex.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título opcional para el informe en Cortex."},
                    "seq": {"type": "integer", "description": "Número de mensaje #seq opcional si solo deseas guardar ese mensaje concreto."},
                },
                "additionalProperties": False,
            },
        },
    },
]




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
            "name": "search_cortex",
            "description": "Busca notas, proyectos e ideas en el cerebro local Cortex.",
            "scope": "Solo lectura · memoria local Cortex",
        },
        {
            "name": "read_cortex_note",
            "description": "Lee una nota completa de Cortex con sus enlaces y backlinks.",
            "scope": "Solo lectura · memoria local Cortex",
        },
        {
            "name": "save_cortex_note",
            "description": "Guarda o actualiza una nota en Cortex y sincroniza el grafo.",
            "scope": "Memoria local · guardado directo en bóveda",
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
            "description": "Prepara la generación de una imagen digital en alta definición a partir de un prompt (Pollinations.ai).",
            "scope": "Servicio externo (Pollinations.ai) · requiere aprobación",
        },
        {
            "name": "generate_video",
            "description": "Prepara la generación de un vídeo cinemático en MP4 a partir de un prompt o imagen (Pollinations.ai).",
            "scope": "Servicio externo (Pollinations.ai) · requiere aprobación",
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
        {
            "name": "swarm_status",
            "description": "Consulta el estado del Swarm, roster de agentes y tablón.",
            "scope": "Solo lectura · motor multi-agente Swarm",
        },
        {
            "name": "swarm_add_worker",
            "description": "Añade un trabajador al Swarm y lanza su misión en paralelo.",
            "scope": "Orquestación local · motor MyKOS Swarm",
        },
        {
            "name": "swarm_post",
            "description": "Publica un mensaje (@agente/@all) en el tablón Swarm y opcionalmente espera respuestas.",
            "scope": "Orquestación local · motor MyKOS Swarm",
        },
        {
            "name": "swarm_read_board",
            "description": "Lee mensajes del tablón compartido del Swarm desde since_seq.",
            "scope": "Solo lectura · motor multi-agente Swarm",
        },
        {
            "name": "swarm_kill",
            "description": "Detiene uno o todos los trabajadores del Swarm o lo reinicia.",
            "scope": "Control local · motor MyKOS Swarm",
        },
        {
            "name": "swarm_save_cortex",
            "description": "Guarda el informe completo del Swarm (o un mensaje #seq) en MyKOS Cortex.",
            "scope": "Escritura local · MyKOS Cortex + Swarm",
        },
    ]


