from __future__ import annotations

import html
import hashlib
import hmac
import json
import mimetypes
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from email.parser import BytesParser
from email.policy import default as email_default_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import gateway_store
from nvidia import (
    clear_nvidia_api_key,
    nvidia_auth_status,
    nvidia_chat_completion,
    nvidia_models,
    save_nvidia_api_key,
    validate_nvidia_api_key,
)
from kimi import clear_kimi_api_key, kimi_auth_status, kimi_chat_completion, kimi_models, save_kimi_api_key
from gemini import clear_gemini_api_key, gemini_auth_status, gemini_chat_completion, gemini_models, save_gemini_api_key
from mistral import (
    clear_mistral_api_key,
    link_vibe_keyring,
    mistral_auth_status,
    mistral_chat_completion,
    mistral_models,
    save_mistral_api_key,
)
from anthropic_api import (
    anthropic_auth_status,
    anthropic_chat_completion,
    anthropic_model_catalog,
    clear_anthropic_api_key,
    get_anthropic_api_key,
    save_anthropic_api_key,
    validate_anthropic_api_key,
    ANTHROPIC_MODELS,
)
from antigravity_cli import (
    antigravity_auth_status,
    antigravity_model_catalog,
    disable_antigravity,
    enable_antigravity,
    is_antigravity_enabled,
)
from qwen_cli import (
    disable_qwen,
    enable_qwen,
    is_qwen_enabled,
    qwen_auth_status,
    qwen_model_catalog,
)
from meta_ai import (
    logout_meta_ai_oauth,
    meta_ai_auth_status,
    meta_ai_chat_completion,
    meta_ai_models,
    start_meta_ai_oauth,
)
from grok import (
    clear_grok_credentials,
    grok_auth_status,
    grok_chat_completion,
    grok_models,
    logout_grok,
    save_grok_api_key,
    start_grok_oauth,
)
from gemini_live import create_ephemeral_token
from automations import start_scheduler, stop_scheduler
from media import MediaError, kokoro_audio, list_media, media_status, transcribe_audio_file
from management import local_status
from nodes import NodeError, heartbeat_node, list_nodes
from strata import (
    strata_chat_request,
    strata_model_catalog,
    strata_status,
)
from oauth import (
    complete_openrouter_oauth,
    logout_openai,
    logout_openrouter_oauth,
    openai_auth_status,
    openai_model_summaries,
    openrouter_api_json,
    openrouter_auth_status,
    openrouter_models,
    oauth_status,
    run_openai_codex,
    start_openai_login,
    start_openrouter_oauth,
)
from permissions import (
    allowed_modes,
    find_grant,
    grant_permission,
    permission_descriptor,
    permission_request_view,
    record_audit,
)
from tools import (
    SENSITIVE_TOOL_NAMES,
    TOOL_SCHEMAS,
    allowed_root_catalog,
    encode_tool_result,
    execute_approved_action,
    execute_tool,
    execute_ollama_pull_with_progress,
    memory_catalog,
    prepare_approval_action,
    tool_catalog,
)
from worker_helpers import (
    ApiError,
    _catalog_cards,
    approval_public_view,
    library_list,
    library_preview,
    library_search,
)
from core.claude import (
    CLAUDE_CLI_MODEL,
    CLAUDE_MODEL_LABEL,
    CLAUDE_MODEL_NAME,
    CLAUDE_RESPONSE_SCHEMA,
    claude_auth_status,
    claude_executable_path,
    claude_model_summary,
    claude_prompt_from_messages,
    claude_tool_protocol_prompt,
    claude_unverified_tool_claim_reason,
    logout_claude,
    parse_claude_response,
    run_claude_cli,
    start_claude_login,
    verified_tool_ledger_for_prompt,
)
from core.benchmark import (
    benchmark_profile_catalog,
    execute_benchmark_suite,
)
from core.integrity import (
    INTEGRITY_GUARD_MESSAGE,
    INTEGRITY_UNVERIFIED_NOTE,
    MAX_INTEGRITY_GUARD_RETRIES,
    current_turn_tool_trace,
    inline_verified_ledger,
    integrity_check_answer,
    unverified_action_claim_reason,
)
from core.uploads import (
    ALLOWED_UPLOAD_EXTENSIONS,
    MAX_UPLOAD_FILES,
    MAX_UPLOAD_REQUEST_BYTES,
    UPLOAD_RETENTION_SECONDS,
    cleanup_uploads,
    process_multipart_uploads,
)
from core.ollama_catalog import (
    OLLAMA_CATALOG_MAX_BYTES,
    OLLAMA_CATALOG_TIMEOUT_SECONDS,
    OLLAMA_LIBRARY_URL,
    fetch_ollama_catalog as core_fetch_ollama_catalog,
    get_ollama_job,
    run_ollama_pull_job as core_run_ollama_pull_job,
    set_ollama_job as core_set_ollama_job,
)
from core.runners import (
    GEMINI_RESPONSE_SCHEMA,
    execute_openai_json_tool_loop,
    has_message_images,
    parse_gemini_response as core_parse_gemini_response,
)


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"
CONVERSATIONS_FILE = DATA_DIR / "conversations.json"
APPROVALS_FILE = DATA_DIR / "approvals.json"
SYSTEM_PROMPT_FILE = CONFIG_DIR / "system_prompt.txt"
UPLOAD_DIR = DATA_DIR / "uploads"
WORKSPACE_ENV = os.environ.get("MYKOS_WORKSPACE_DIR") or os.environ.get("MYKOS_GATEWAY_WORKSPACE_DIR")
WORKSPACE_DIR = Path(WORKSPACE_ENV).expanduser().resolve() if WORKSPACE_ENV else (Path.home() / ".mykos" / "workspace").resolve()
MEMORY_CORE_DIR = WORKSPACE_DIR / "memory" / "core"
MAX_UPLOAD_REQUEST_BYTES = 32 * 1024 * 1024
MAX_UPLOAD_FILES = 4
MAX_TRANSCRIPTION_REQUEST_BYTES = 26 * 1024 * 1024
ALLOWED_AUDIO_EXTENSIONS = {".webm", ".wav", ".mp3", ".m4a", ".ogg", ".mp4"}
MAX_ATTACHMENT_CONTEXT_CHARS = 10_000
COMPACTION_KEEP_MESSAGES = 10
# Vision models can account for several thousand tokens per image even when
# the visible OCR/text is short. Reserve enough room before calling Ollama.
IMAGE_CONTEXT_RESERVE_TOKENS = 8_192
ATTACHMENT_NUM_CTX = 16_384
UPLOAD_RETENTION_SECONDS = 24 * 60 * 60
ALLOWED_UPLOAD_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
}
OLLAMA_LIBRARY_URL = "https://ollama.com/library"
OLLAMA_CATALOG_TIMEOUT_SECONDS = 15
OLLAMA_CATALOG_MAX_BYTES = 2 * 1024 * 1024
OLLAMA_CATALOG_MAX_RESULTS = 30
CLAUDE_MODEL_NAME = "claude-sonnet-oauth"
CLAUDE_MODEL_LABEL = "Claude Sonnet · OAuth"
CLAUDE_CLI_MODEL = os.environ.get("MYKOS_CLAUDE_MODEL", "sonnet").strip() or "sonnet"
CLAUDE_CONTEXT_LENGTH = 131_072
CLAUDE_STATUS_CACHE_SECONDS = 30
CLAUDE_REQUEST_TIMEOUT_SECONDS = 15 * 60
OPENROUTER_MODEL_CACHE_SECONDS = 60
OPENROUTER_REQUEST_TIMEOUT_SECONDS = 15 * 60
NVIDIA_MODEL_CACHE_SECONDS = 60
KIMI_MODEL_CACHE_SECONDS = 60
GEMINI_MODEL_CACHE_SECONDS = 60
# NVIDIA NIM has occasionally left a transport request open; keep MyKOS responsive.
NVIDIA_REQUEST_TIMEOUT_SECONDS = 120
LLAMA_CPP_MODEL_NAME = "mykos-cuda"
LLAMA_CPP_MODEL_LABEL = "MyKOS · llama.cpp CUDA · Qwen3.6 35.5B"
LLAMA_CPP_URL = os.environ.get("MYKOS_LLAMA_CPP_URL", "http://127.0.0.1:8091").rstrip("/")
MYKOS_GATEWAY_URL = os.environ.get("MYKOS_GATEWAY_URL", "http://127.0.0.1:3210").rstrip("/")
MYKOS_CONTROL_URL = os.environ.get("MYKOS_CONTROL_URL", MYKOS_GATEWAY_URL).rstrip("/")
MYKOS_CONTROL_TOKEN = os.environ.get("MYKOS_CONTROL_TOKEN", "").strip()
MYKOS_GATEWAY_BACKEND_MODEL = os.environ.get("MYKOS_GATEWAY_BACKEND_MODEL", "mykos-llamacpp/mykos-cuda").strip()
MYKOS_GATEWAY_ENABLED = os.environ.get("MYKOS_USE_GATEWAY", "1").strip().casefold() not in {"0", "false", "no", "off"}
# Fase 3, tramo 5: con «1» el bucle de chat con herramientas del modelo local lo ejecuta el Gateway (chat-loop.js) y este
# proceso solo ejecuta las herramientas y acciones que el Gateway le pide. Lo pone el Gateway al lanzar el trabajador
# (chatLoop.enabled); sin la variable, o con «0», el bucle sigue siendo el de aquí.
MYKOS_GATEWAY_CHAT_LOOP = os.environ.get("MYKOS_GATEWAY_CHAT_LOOP", "0").strip().casefold() in {"1", "true", "yes", "on"}
LLAMA_CPP_EXE = os.environ.get(
    "MYKOS_LLAMA_CPP_EXE",
    str(Path.home() / "llama.cpp" / "build" / "bin" / "llama-server"),
).strip()
LLAMA_CPP_MODEL = os.environ.get(
    "MYKOS_LLAMA_CPP_MODEL",
    str(Path.home() / ".ollama" / "models" / "blobs" / "sha256-d372de8e934898a59e6ccfabc3368474711384d8f1fd4d22d87a3f0a45400cdc"),
).strip()
LLAMA_CPP_CONTEXT_LENGTH = int(os.environ.get("MYKOS_LLAMA_CPP_CONTEXT", "32768"))
LLAMA_CPP_START_TIMEOUT_SECONDS = 120

HOST = os.environ.get("MYKOS_HOST", "127.0.0.1")
# Backend interno de MyKOS. El puerto público (3210) lo sirve MyKOS Gateway, que reenvía /api/* aquí.
PORT = int(os.environ.get("MYKOS_PORT", "3211"))
# Puerto que ve el usuario; solo sirve para construir URLs de retorno (callback de OAuth).
PUBLIC_PORT = int(os.environ.get("MYKOS_PUBLIC_PORT", "0") or 0) or PORT
# Lo activa el Gateway al arrancar este proceso: sin interfaz propia y sin dejar motores cargados al cerrarse.
BACKEND_ONLY = os.environ.get("MYKOS_BACKEND_ONLY", "").strip().casefold() in {"1", "true", "yes", "on"}
# Puerta del trabajador: la activa el plugin del Gateway (MYKOS_WORKER_GUARD=1). Con ella, TODAS las rutas /api/* salvo
# /api/health exigen la cabecera X-MyKOS-Control-Token con el token del Gateway. Así una página web ajena o un programa
# local no pueden saltarse las comprobaciones del Gateway (Host, Origin, tabla de rutas y auditoría) hablando
# directamente con este puerto. Con la puerta activa y sin token, se rechaza todo: falla cerrado. Sin la variable
# (arranque manual antiguo, o un Gateway anterior al plugin 0.6.0 que aún no envía el token) no cambia nada.
WORKER_GUARD = os.environ.get("MYKOS_WORKER_GUARD", "").strip().casefold() in {"1", "true", "yes", "on"}
# Servicios auxiliares (fase 3, cuarto corte): estas rutas no las decide este proceso. El Gateway valida la forma
# exacta de la petición, aplica sus límites de carga y firma la decisión (cabecera X-MyKOS-Gateway-Decision, ligada al
# método, a la ruta y al cuerpo exacto cuando el Gateway lo ha leído). Con la puerta activa, sin esa firma se rechaza:
# falla cerrado. Esta lista debe coincidir con POLICY_TABLE de gateway-plugin/mykos-ui/policy.js (probe-routes.cjs
# lo comprueba). Sin MYKOS_WORKER_GUARD (arranque manual antiguo) no se exige nada, como antes.
GATEWAY_DECISION_ROUTES = {
    ("POST", "/api/benchmark"),
    ("POST", "/api/ollama/pull-request"),
    ("POST", "/api/ollama/delete-request"),
    ("POST", "/api/automations/create-request"),
    ("POST", "/api/automations/delete-request"),
    ("POST", "/api/oauth/openai/start"),
    ("POST", "/api/oauth/openai/logout"),
    ("POST", "/api/oauth/claude/start"),
    ("POST", "/api/oauth/claude/logout"),
    ("POST", "/api/oauth/openrouter/start"),
    ("POST", "/api/oauth/openrouter/refresh"),
    ("POST", "/api/oauth/openrouter/logout"),
    ("GET", "/api/oauth/openrouter/callback"),
    ("POST", "/api/oauth/meta/start"),
    ("POST", "/api/oauth/meta/refresh"),
    ("POST", "/api/oauth/meta/logout"),
    ("POST", "/api/oauth/grok/start"),
    ("POST", "/api/oauth/grok/refresh"),
    ("POST", "/api/oauth/grok/logout"),
    ("POST", "/api/providers/nvidia/connect"),
    ("POST", "/api/providers/nvidia/logout"),
    ("POST", "/api/providers/nvidia/refresh"),
    ("POST", "/api/providers/kimi/connect"),
    ("POST", "/api/providers/kimi/logout"),
    ("POST", "/api/providers/kimi/refresh"),
    ("POST", "/api/providers/gemini/connect"),
    ("POST", "/api/providers/gemini/logout"),
    ("POST", "/api/providers/gemini/refresh"),
    ("POST", "/api/providers/mistral/connect"),
    ("POST", "/api/providers/mistral/logout"),
    ("POST", "/api/providers/mistral/refresh"),
    ("POST", "/api/providers/anthropic/connect"),
    ("POST", "/api/providers/anthropic/logout"),
    ("POST", "/api/providers/anthropic/refresh"),
    ("POST", "/api/providers/antigravity/connect"),
    ("POST", "/api/providers/antigravity/logout"),
    ("POST", "/api/providers/antigravity/refresh"),
    ("POST", "/api/providers/qwen/connect"),
    ("POST", "/api/providers/qwen/logout"),
    ("POST", "/api/providers/qwen/refresh"),
    ("POST", "/api/providers/grok/connect"),
    ("POST", "/api/providers/grok/logout"),
    ("POST", "/api/providers/grok/refresh"),
    ("POST", "/api/uploads"),
    ("POST", "/api/nodes/heartbeat"),
}
# En estas dos rutas el Gateway no lee el cuerpo (una subida llega a 32 MB) o no hay cuerpo (retorno de OAuth), así que
# su decisión viaja sin hash («-»). En TODAS las demás la decisión tiene que venir ligada al cuerpo exacto: una
# decisión sin ligar en una ruta JSON se rechaza.
GATEWAY_DECISION_UNBOUND_BODY = {
    ("POST", "/api/uploads"),
    ("GET", "/api/oauth/openrouter/callback"),
}
GATEWAY_DECISION_HEADER = "X-MyKOS-Gateway-Decision"
GATEWAY_DECISION_MAX_AGE = 300  # margen sobre la caducidad que firma el Gateway (120 s), por si el reloj va justo
# PID del Gateway que supervisa este proceso: si desaparece, el backend se apaga solo.
PARENT_PID = int(os.environ.get("MYKOS_PARENT_PID", "0") or 0)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "").strip()
MAX_MESSAGE_CHARS = 12_000
# Las tareas complejas pueden necesitar muchas lecturas, comprobaciones y
# acciones aprobadas. El límite sigue siendo estricto para evitar bucles del
# modelo, pero 8 rondas cortaban demasiado pronto el trabajo de todos los
# proveedores.
MAX_TOOL_ROUNDS = 32
TOOL_CONTEXT_NUM_CTX = 16_384
MAX_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("MYKOS_REQUEST_TIMEOUT_SECONDS", "300") or 300)
MAX_WEB_SEARCH_CALLS_PER_REQUEST = 2
MAX_WEB_FETCH_CALLS_PER_REQUEST = 6
APPROVAL_TTL_SECONDS = 15 * 60
CHAT_CAPABILITIES = {"chat", "completion"}
CONTEXT_ESTIMATE_CHARS_PER_TOKEN = 4
CONTEXT_SAFETY_TOKENS = 512
CONTEXT_COMPACT_RATIO = 0.82
CONTEXT_WARNING_RATIO = 0.70
CONTEXT_CRITICAL_RATIO = 0.92
MAX_CONTEXT_SUMMARY_CHARS = 2_400
GENERATION_EFFORTS = {"off", "low", "medium", "high"}
GENERATION_SPEEDS = {"fast", "balanced", "quality", "full"}
GENERATION_CREATIVITY = {"precise", "balanced", "creative"}
GENERATION_PRESETS = {
    # Remote providers often expose large windows (and NVIDIA may report 0),
    # so the local presets must not reduce every chat to an 8K window.
    "fast": {"num_ctx": 16384, "num_predict": 2048},
    "balanced": {"num_ctx": 32768, "num_predict": 4096},
    "quality": {"num_ctx": 65536, "num_predict": 6144},
    "full": {"num_ctx": 131072, "num_predict": 8192},
}
CREATIVITY_TEMPERATURE = {"precise": 0.2, "balanced": 0.5, "creative": 0.8}
BENCHMARK_OUTPUT_TOKENS = 192
BENCHMARK_PROFILES = {
    "fast": {
        "label": "Rápido",
        "description": "Contexto corto y respuesta ágil.",
        "generation": {"effort": "off", "speed": "fast", "creativity": "precise"},
    },
    "balanced": {
        "label": "Equilibrado",
        "description": "Punto de referencia para el uso diario.",
        "generation": {"effort": "off", "speed": "balanced", "creativity": "balanced"},
    },
    "deep": {
        "label": "Profundo",
        "description": "Más contexto y razonamiento cuando el modelo lo admite.",
        "generation": {"effort": "high", "speed": "quality", "creativity": "precise"},
    },
    "full": {
        "label": "Full Session · 131K",
        "description": "Contexto máximo configurado; puede consumir bastante memoria.",
        "generation": {"effort": "high", "speed": "full", "creativity": "precise"},
    },
}
BENCHMARK_PROMPT = (
    "Responde en español con una sola frase breve (máximo 20 palabras) confirmando "
    "que esta prueba de rendimiento ha terminado."
)

OPENAI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["answer", "tool_call"]},
        "content": {"type": "string"},
        "tool_name": {"type": "string"},
        "arguments": {
            "type": "string",
            "description": "Objeto JSON serializado con los argumentos de la herramienta.",
        },
    },
    "required": ["kind", "content", "tool_name", "arguments"],
    "additionalProperties": False,
}

CLAUDE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["answer", "tool_call"]},
        "content": {"type": "string"},
        "tool_name": {"type": "string"},
        "arguments": {"type": "object"},
    },
    "required": ["kind", "content"],
    "additionalProperties": False,
}

# Claude Code is invoked without its native tools.  MyKOS therefore asks it to
# emit a small JSON protocol and executes that protocol itself.  Keep a
# host-owned trace of those executions: prose generated by the model is not
# evidence that a tool was called or that it failed.
MAX_VERIFIED_TOOL_TRACE = 12
MAX_CLAUDE_RESPONSE_GUARD_RETRIES = 1

GEMINI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["answer", "tool_call"]},
        "content": {"type": "string"},
        "tool_name": {"type": "string"},
        "arguments": {"type": "object"},
    },
    "required": ["kind", "content"],
}

STORE_LOCK = threading.RLock()
UPLOADS_LOCK = threading.RLock()
OLLAMA_JOBS_LOCK = threading.RLock()
BENCHMARK_LOCK = threading.Lock()
CLAUDE_STATUS_LOCK = threading.RLock()
OPENROUTER_LOCK = threading.RLock()
NVIDIA_LOCK = threading.RLock()
ACTIVITY_LOCK = threading.RLock()
UPLOADS: dict[str, dict[str, Any]] = {}
OLLAMA_JOBS: dict[str, dict[str, Any]] = {}
CLAUDE_STATUS_CACHE: dict[str, Any] = {"checked_at": 0.0, "status": None}
CLAUDE_LOGIN_PROCESS: subprocess.Popen[Any] | None = None
OPENROUTER_MODEL_CACHE: dict[str, Any] = {"checked_at": 0.0, "models": [], "authenticated": False, "error": ""}
NVIDIA_MODEL_CACHE: dict[str, Any] = {"checked_at": 0.0, "models": [], "authenticated": False, "error": ""}
KIMI_LOCK = threading.RLock()
KIMI_MODEL_CACHE: dict[str, Any] = {"checked_at": 0.0, "models": [], "authenticated": False, "error": ""}
GEMINI_LOCK = threading.RLock()
GEMINI_MODEL_CACHE: dict[str, Any] = {"checked_at": 0.0, "models": [], "authenticated": False, "error": ""}
MISTRAL_LOCK = threading.RLock()
MISTRAL_MODEL_CACHE: dict[str, Any] = {"checked_at": 0.0, "models": [], "authenticated": False, "error": ""}
MISTRAL_MODEL_CACHE_SECONDS = 300.0
GROK_LOCK = threading.RLock()
GROK_MODEL_CACHE: dict[str, Any] = {"checked_at": 0.0, "models": [], "authenticated": False, "error": ""}
GROK_MODEL_CACHE_SECONDS = 60.0
from core.activity import (
    activity_public_view,
    finish_activity,
    set_sync_gateway_fn,
    start_activity,
    stop_llama_cpp_server as _core_stop_llama_cpp_server,
    update_activity,
)


def stop_llama_cpp_server() -> None:
    _core_stop_llama_cpp_server(LLAMA_CPP_MODEL)


DEFAULT_SYSTEM_PROMPT = """Eres MyKOS, el asistente personal local integrado en MyKOS.

Hablas con el usuario en español de España, de manera natural, clara, breve y práctica. Eres un ayudante competente de taller, no un chatbot corporativo. Si preguntan quién eres, responde MyKOS (el asistente de MyKOS).

Entorno y herramientas:
- Este servidor se ejecuta en Linux.
- Solo tienes acceso al equipo mediante las herramientas declaradas. Si necesitas una herramienta, llámala en este turno. Las herramientas sensibles crean una solicitud pendiente que requiere aprobación explícita del usuario.
- `run_powershell` ejecuta **bash** en Linux. Para abrir visualmente una carpeta, archivo o web en pantalla usa `run_powershell` con `xdg-open "/ruta/absoluta"`.
- Para modificar un archivo existente, léelo primero con `read_project_file` y usa `edit_project_file` con el fragmento exacto que cambia. Usa `write_project_file` solo para crear archivos nuevos.
- Tienes dos sistemas de memoria separados:
  (A) Memoria interna rápida (`search_memory`, `read_memory`, `list_memory`, `save_memory`, `delete_memory`) para datos puntuales y hechos cortos.
  (B) Memoria estructural y documentos (`root: "workspace"`): guarda notas, fichas de investigación (`research/`), diario (`memory/`) y proyectos del usuario en la raíz `workspace` (~/.mykos/workspace). Nunca guardes documentos en la raíz `mykos` para no ensuciar el repositorio de código.
- Git: `git_status`, `git_diff`, `git_log` y `git_remote_status` son de solo lectura. `git_commit`, `git_branch`, `git_remote_fetch`, `git_remote_pull` (`--ff-only`) y `git_remote_push` (sin force push) requieren aprobación explícita.
- Investigación web: haz una búsqueda principal con `web_search`, lee hasta 3 fuentes con `web_fetch` y usa `save_research_note` solo con URLs verificadas por esas herramientas (se guardan por defecto en `root: "workspace"`).
- Multimedia: para generar imágenes usa `generate_image` con motor FLUX; para crear vídeos cinemáticos en MP4 usa `generate_video`. Ambas herramientas están completamente disponibles y requieren aprobación explícita.
- Raíces autorizadas: `workspace` (espacio de trabajo independiente para archivos y notas del usuario, por defecto) y `mykos` (código fuente del sistema). Usa siempre `root` y una ruta relativa (`path`)."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


try:
    LOCAL_TIMEZONE = ZoneInfo("Europe/Madrid")
except Exception:
    LOCAL_TIMEZONE = timezone.utc
_SPANISH_WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_SPANISH_MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def current_time_context() -> str:
    """Fecha y hora actuales en español, hora de Madrid, para que MyKOS no responda a ciegas."""
    now = datetime.now(LOCAL_TIMEZONE)
    weekday = _SPANISH_WEEKDAYS[now.weekday()]
    month = _SPANISH_MONTHS[now.month - 1]
    return (
        f"Fecha y hora actuales: {weekday} {now.day} de {month} de {now.year}, "
        f"{now.strftime('%H:%M')} (hora de Madrid, España)."
    )


def load_system_prompt() -> str:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        prompt = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        prompt = ""
    return prompt or DEFAULT_SYSTEM_PROMPT


def load_user_profile() -> str:
    """Lee el perfil del usuario (USER.md) desde el espacio de trabajo o configuración."""
    candidates = [
        WORKSPACE_DIR / "USER.md",
        Path.home() / ".mykos" / "USER.md",
        CONFIG_DIR / "USER.md",
    ]
    for path in candidates:
        try:
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return content
        except OSError:
            pass
    return ""


def load_base_system_prompt() -> str:
    prompt = load_system_prompt()
    user_profile = load_user_profile()
    if user_profile:
        header = "" if user_profile.startswith("#") else "# Perfil del Usuario\n\n"
        prompt += f"\n\n{header}{user_profile}"
    return prompt


_CORE_MEMORY_FILES = [
    ("identity.md",            "## Identidad del asistente"),
    ("operational-lessons.md", "## Lecciones operativas"),
    ("preferences.md",         "## Preferencias de Usuario"),
]


def load_core_memory() -> str:
    """Lee los archivos de memoria persistente de MyKOS (core/) e inyecta su
    contenido directamente en el System Prompt para que el modelo los tenga
    disponibles desde el primer token, sin necesidad de usar herramientas."""
    sections: list[str] = []
    for filename, header in _CORE_MEMORY_FILES:
        path = MEMORY_CORE_DIR / filename
        try:
            content = path.read_text(encoding="utf-8").strip()
            if content:
                sections.append(f"{header}\n\n{content}")
        except OSError:
            pass  # Si el archivo no existe todavía, se omite sin error.
    # El diario y el corpus completo son histórico: no se inyectan como
    # instrucciones de sistema. El modelo debe consultarlos de forma acotada
    # cuando el asunto lo requiera, igual que cualquier otra fuente documental.
    if not sections:
        return ""
    joined = "\n\n---\n\n".join(sections)
    return (
        "# Memoria persistente de MyKOS (cargada automáticamente al inicio)\n\n"
        + joined
    )





def load_store() -> dict[str, Any]:
    # Las conversaciones las guarda el Gateway (gateway_store); sin Gateway, el fichero data/conversations.json de siempre.
    # Si el Gateway no responde, gateway_store lanza StoreError (no se devuelve un almacén vacío que luego se guardaría).
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data = gateway_store.load_document("conversations", legacy_file=CONVERSATIONS_FILE)
        if isinstance(data, dict) and isinstance(data.get("conversations"), list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"conversations": []}


def save_store(store: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    gateway_store.save_document("conversations", store, legacy_file=CONVERSATIONS_FILE, indent=2, source="server.save_store")


def load_approval_store() -> dict[str, Any]:
    data = gateway_store.load_document(
        "approvals",
        legacy_file=APPROVALS_FILE,
        default={"approvals": []},
    )
    if isinstance(data, dict) and isinstance(data.get("approvals"), list):
        return data
    return {"approvals": []}


def save_approval_store(store: dict[str, Any]) -> None:
    gateway_store.save_document(
        "approvals",
        store,
        legacy_file=APPROVALS_FILE,
        indent=2,
        source="server.approvals",
    )


def purge_approvals(store: dict[str, Any]) -> bool:
    now = time.time()
    changed = False
    active: list[dict[str, Any]] = []
    for item in store.get("approvals", []):
        if not isinstance(item, dict):
            changed = True
            continue
        if item.get("status") != "pending":
            changed = True
            continue
        try:
            expires_at = float(item.get("expires_at_epoch", 0))
        except (TypeError, ValueError):
            expires_at = 0
        if expires_at <= now:
            changed = True
            continue
        active.append(item)
    if len(active) != len(store.get("approvals", [])):
        changed = True
    store["approvals"] = active
    return changed


def tool_message_for_result(result: dict[str, Any], supports_vision: bool) -> dict[str, Any]:
    public_result = dict(result)
    image_base64 = public_result.pop("_image_base64", None)
    image_mime_type = public_result.pop("_image_mime_type", None)
    if image_base64:
        if supports_vision:
            public_result["image_attached"] = True
        else:
            public_result["image_attached"] = False
            public_result["image_note"] = "El modelo actual no admite visión; se devuelve únicamente el OCR y los metadatos."
    message: dict[str, Any] = {
        "role": "tool",
        "content": encode_tool_result(public_result),
    }
    if image_base64 and supports_vision:
        message["images"] = [image_base64]
        if image_mime_type:
            message["image_mime_type"] = image_mime_type
    return message


def verified_tool_trace_entry(name: str, result: dict[str, Any] | None) -> dict[str, Any]:
    """Return compact, host-verified evidence for a Claude tool round."""
    result = result if isinstance(result, dict) else {"ok": False, "error": "La herramienta devolvió un formato no válido."}
    entry = {
        "tool": str(name or "").strip(),
        "ok": bool(result.get("ok")),
    }
    error = str(result.get("error", "")).strip()
    if error:
        entry["error"] = error[:500]
    return entry


def append_verified_claude_tool_result(
    messages: list[dict[str, Any]],
    trace: list[dict[str, Any]],
    name: str,
    result: dict[str, Any] | None,
    supports_vision: bool,
) -> None:
    """Append an execution result and retain only a compact audited trace."""
    safe_result = result if isinstance(result, dict) else {"ok": False, "error": "La herramienta devolvió un formato no válido."}
    trace.append(verified_tool_trace_entry(name, safe_result))
    del trace[:-MAX_VERIFIED_TOOL_TRACE]
    messages.append(tool_message_for_result(safe_result, supports_vision))


def source_cards_from_tool_result(result: Any) -> list[dict[str, str]]:
    """Reduce web-tool output to safe, compact metadata for the chat UI."""
    if not isinstance(result, dict) or not result.get("ok"):
        return []
    action = str(result.get("action", ""))
    cards: list[dict[str, str]] = []
    if action == "web_search":
        consulted_at = str(result.get("searched_at", ""))
        for item in result.get("results", []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()
            if title and url:
                cards.append(
                    {
                        "title": title[:240],
                        "url": url[:2_000],
                        "snippet": str(item.get("snippet", "")).strip()[:360],
                        "consulted_at": consulted_at,
                        "kind": "search",
                    }
                )
    elif action == "web_fetch":
        source = result.get("source") if isinstance(result.get("source"), dict) else result
        title = str(source.get("title", "")).strip()
        url = str(source.get("url", "")).strip()
        if title and url:
            cards.append(
                {
                    "title": title[:240],
                    "url": url[:2_000],
                    "snippet": "Fuente leída por MyKOS.",
                    "consulted_at": str(source.get("fetched_at", result.get("fetched_at", ""))),
                    "kind": "page",
                }
            )
    return cards


def merge_source_cards(target: list[dict[str, str]], result: Any) -> None:
    seen = {item.get("url") for item in target}
    for card in source_cards_from_tool_result(result):
        if card.get("url") in seen:
            continue
        target.append(card)
        seen.add(card.get("url"))
        if len(target) >= 12:
            break


def research_sources_are_verified(arguments: dict[str, Any], source_cards: list[dict[str, str]]) -> bool:
    """Allow research notes only when every cited URL came from a real web tool result."""
    verified = {
        str(card.get("url", "")).strip().rstrip("/")
        for card in source_cards
        if isinstance(card, dict) and str(card.get("url", "")).strip()
    }
    raw_sources = arguments.get("sources") if isinstance(arguments, dict) else None
    if not verified or not isinstance(raw_sources, list) or not raw_sources:
        return False
    cited = {
        str(item.get("url", "")).strip().rstrip("/")
        for item in raw_sources
        if isinstance(item, dict) and str(item.get("url", "")).strip()
    }
    return bool(cited) and cited.issubset(verified)


def source_cards_from_messages(messages: list[dict[str, Any]], *, current_turn_only: bool = False) -> list[dict[str, str]]:
    """Keep historical verification separate from sources displayed for this turn."""
    if current_turn_only:
        start = next((i + 1 for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"), 0)
        messages = messages[start:]
    cards: list[dict[str, str]] = []
    for message in messages:
        if message.get("role") == "assistant" and isinstance(message.get("sources"), list):
            for source in message.get("sources", []):
                if not isinstance(source, dict):
                    continue
                url = str(source.get("url", "")).strip()
                title = str(source.get("title", "")).strip()
                if not url or not title:
                    continue
                merge_source_cards(
                    cards,
                    {
                        "ok": True,
                        "action": "web_search",
                        "searched_at": source.get("consulted_at", ""),
                        "results": [source],
                    },
                )
            continue
        if message.get("role") != "tool":
            continue
        try:
            result = json.loads(str(message.get("content", "")))
        except (TypeError, json.JSONDecodeError):
            continue
        merge_source_cards(cards, result)
    return cards


def _permission_candidate(tool_name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    prepared = prepare_approval_action(tool_name, arguments)
    if not prepared.get("ok"):
        return None, None
    action = prepared.get("action")
    if not isinstance(action, dict):
        return None, None
    return action, permission_descriptor(tool_name, action)


def _authorized_sensitive_action(
    tool_name: str,
    arguments: dict[str, Any],
    session_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    action, descriptor = _permission_candidate(tool_name, arguments)
    if action is None or descriptor is None:
        return None, None
    authorization = controller_authorize_action(tool_name, action, session_id)
    if not authorization.get("ok") or authorization.get("decision") != "granted":
        return None, None
    grant = authorization.get("grant") if isinstance(authorization.get("grant"), dict) else None
    result = controller_execute_action(action, session_id, authorization.get("authorization"))
    if grant is None:
        grant = {"id": "", "mode": "once"}
    if not (MYKOS_GATEWAY_ENABLED and MYKOS_CONTROL_TOKEN):
        record_audit(
            "permission_used",
            descriptor,
            mode=str(grant.get("mode", "")),
            status="ok" if result.get("ok") else "failed",
            permission_id=str(grant.get("id", "")),
            session_id=session_id,
            detail=str(result.get("error", "")),
        )
    return result, grant


def _auto_grant_sensitive_action(
    tool_name: str,
    arguments: dict[str, Any],
    session_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Modo "acceso total": concede permiso permanente ahora mismo (auditable, revocable) y ejecuta.

    Las operaciones de mayor riesgo (solo "once" en allowed_modes) devuelven (None, None): ni el modo
    "acceso total" se las salta, siguen pidiendo aprobación igual que en "supervisado".
    """
    action, descriptor = _permission_candidate(tool_name, arguments)
    if action is None or descriptor is None:
        return None, None
    if MYKOS_GATEWAY_ENABLED and MYKOS_CONTROL_TOKEN:
        authorization = controller_authorize_action(tool_name, action, session_id, auto_grant=True)
        if not authorization.get("ok") or authorization.get("decision") != "granted":
            return None, None
        grant = authorization.get("grant") if isinstance(authorization.get("grant"), dict) else {"id": "", "mode": "permanent"}
        result = controller_execute_action(action, session_id, authorization.get("authorization"))
        return result, grant
    try:
        grant = grant_permission(descriptor, "permanent", session_id, approval_id="auto:acceso_total")
    except ValueError:
        return None, None
    if grant is None:
        return None, None
    result = controller_execute_action(action, session_id, {"permission_id": grant.get("id", ""), "scope_key": descriptor.get("scope_key", "")})
    record_audit(
        "permission_used",
        descriptor,
        mode="permanent",
        status="ok" if result.get("ok") else "failed",
        permission_id=str(grant.get("id", "")),
        session_id=session_id,
        detail=str(result.get("error", "")),
    )
    return result, grant


def create_pending_approval(
    conversation_id: str,
    model: str,
    messages: list[dict[str, Any]],
    tool_name: str,
    arguments: dict[str, Any],
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    conversation_permission_mode: str = "supervisado",
) -> dict[str, Any]:
    prepared = prepare_approval_action(tool_name, arguments)
    if not prepared.get("ok"):
        return prepared
    action = prepared.get("action")
    if not isinstance(action, dict):
        return {"ok": False, "error": "La acción preparada no es válida."}
    if MYKOS_GATEWAY_ENABLED and MYKOS_CONTROL_TOKEN:
        return controller_create_approval(
            {
                "conversation_id": conversation_id,
                "model": model,
                "messages": messages,
                "tool_name": tool_name,
                "action": action,
                "supports_vision": supports_vision,
                "generation": generation or {},
                "conversation_permission_mode": conversation_permission_mode,
            }
        )
    permission = permission_request_view(tool_name, action)

    now = time.time()
    record = {
        "id": uuid.uuid4().hex,
        "status": "pending",
        "conversation_id": conversation_id,
        "model": model,
        "supports_vision": supports_vision,
        "generation": generation or {},
        "conversation_permission_mode": conversation_permission_mode,
        "tool_name": tool_name,
        "action": action,
        "permission": permission,
        "messages": messages,
        "created_at": utc_now(),
        "expires_at": datetime.fromtimestamp(now + APPROVAL_TTL_SECONDS, timezone.utc).isoformat(timespec="seconds"),
        "expires_at_epoch": now + APPROVAL_TTL_SECONDS,
    }
    with STORE_LOCK:
        store = load_approval_store()
        purge_approvals(store)
        store["approvals"].append(record)
        save_approval_store(store)
    record_audit(
        "approval_created",
        permission,
        mode="once",
        approval_id=str(record["id"]),
        session_id=conversation_id,
    )
    return {"ok": True, "approval": approval_public_view(record)}


def save_assistant_message(conversation_id: str, assistant_message: dict[str, Any]) -> None:
    if not str(assistant_message.get("message_id", "")).strip():
        assistant_message["message_id"] = uuid.uuid4().hex
    with STORE_LOCK:
        store = load_store()
        conversation = find_conversation(store, conversation_id)
        if conversation is None:
            return
        conversation["messages"].append(assistant_message)
        conversation["updated_at"] = utc_now()
        save_store(store)


def ollama_request(path: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"

    request = urllib.request.Request(
        f"{OLLAMA_URL}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama devolvió HTTP {error.code}: {detail[:500]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            "No se puede conectar con Ollama en "
            f"{OLLAMA_URL}. Comprueba que Ollama esté iniciado."
        ) from error

    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Ollama devolvió una respuesta que no es JSON válido.") from error
    if not isinstance(result, dict):
        raise RuntimeError("Ollama devolvió un formato de respuesta inesperado.")
    return result


def _llama_cpp_request(path: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(
        f"{LLAMA_CPP_URL}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"llama.cpp devolvió HTTP {error.code}: {detail[:500]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"No se puede conectar con llama.cpp en {LLAMA_CPP_URL}."
        ) from error
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("llama.cpp devolvió una respuesta que no es JSON válido.") from error
    if not isinstance(result, dict):
        raise RuntimeError("llama.cpp devolvió un formato de respuesta inesperado.")
    return result


def mykos_gateway_chat_request(
    messages: list[dict[str, Any]],
    conversation_id: str,
    generation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pide al plano de control del Gateway el modelo local de MyKOS."""
    generation = generation if isinstance(generation, dict) else {}
    options = generation.get("options") if isinstance(generation.get("options"), dict) else {}
    payload: dict[str, Any] = {
        "model": LLAMA_CPP_MODEL_NAME,
        "messages": [
            {
                key: value
                for key, value in item.items()
                if key in {"role", "content", "tool_calls", "tool_call_id", "images"}
            }
            for item in messages
            if isinstance(item, dict)
        ],
        "stream": False,
        "user": f"mykos-web-{conversation_id}",
    }
    if options:
        payload["max_tokens"] = int(options.get("num_predict", 1024) or 1024)
        payload["temperature"] = float(options.get("temperature", 0.5) or 0.5)
    effort = str(generation.get("effort", "")).strip().casefold()
    if effort == "off":
        payload["reasoning_effort"] = "none"
    elif effort in {"low", "medium", "high"}:
        payload["reasoning_effort"] = effort
    if TOOL_SCHEMAS:
        payload["tools"] = TOOL_SCHEMAS
        payload["tool_choice"] = "auto"
    body = json.dumps({"provider": "llama_cpp", "conversation_id": conversation_id, "payload": payload}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{MYKOS_CONTROL_URL}/mykos-control/model",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-mykos-control-token": MYKOS_CONTROL_TOKEN,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"El Gateway propio de MyKOS devolvió HTTP {error.code}: {detail[:500]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"No se puede conectar con el plano de control del Gateway propio de MyKOS en {MYKOS_CONTROL_URL}."
        ) from error
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("El plano de control del Gateway propio de MyKOS devolvió una respuesta no válida.") from error
    if not isinstance(result, dict):
        raise RuntimeError("El plano de control del Gateway propio de MyKOS devolvió un formato inesperado.")
    return result


class ControlPlaneHTTPError(RuntimeError):
    """El plano de control del Gateway respondió con un error HTTP. Sigue siendo un RuntimeError para quien ya lo captura."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"El plano de control de MyKOS devolvió HTTP {status}: {detail[:500]}")
        self.status = status
        message = ""
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict):
                message = str(parsed.get("error", "")).strip()
        except (ValueError, TypeError):
            pass
        self.client_message = message[:300]


def _control_http_error(status: int, detail: str) -> ControlPlaneHTTPError:
    return ControlPlaneHTTPError(int(status), detail)


# Errores del cliente que el plano de control decide con acierto (la solicitud no existe, ya se resolvió, el cuerpo no
# vale...) y que la API pública debe devolver tal cual en vez de disfrazarlos de «servidor interno caído» (502).
CONTROL_PLANE_CLIENT_STATUSES = {400, 404, 409, 413, 422, 429}


def mykos_gateway_model_request(provider: str, payload: dict[str, Any], conversation_id: str = "") -> dict[str, Any]:
    """Envía una petición de modelo al controlador interno del Gateway."""
    body = json.dumps({"provider": provider, "conversation_id": conversation_id, "payload": payload}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{MYKOS_CONTROL_URL}/mykos-control/model",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-mykos-control-token": MYKOS_CONTROL_TOKEN,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise _control_http_error(error.code, detail) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"No se puede conectar con el plano de control de MyKOS en {MYKOS_CONTROL_URL}."
        ) from error
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("El plano de control de MyKOS devolvió una respuesta no válida.") from error
    if not isinstance(result, dict):
        raise RuntimeError("El plano de control de MyKOS devolvió un formato inesperado.")
    return result


def mykos_gateway_control_request(operation: str, payload: dict[str, Any], timeout: int = 900) -> dict[str, Any]:
    """Manda una herramienta o acción al plano de control, con vuelta atrás local."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{MYKOS_CONTROL_URL}/mykos-control/{operation}",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-mykos-control-token": MYKOS_CONTROL_TOKEN,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise _control_http_error(error.code, detail) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"No se puede conectar con el plano de control de MyKOS en {MYKOS_CONTROL_URL}.") from error
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("El plano de control de MyKOS devolvió una respuesta no válida.") from error
    if not isinstance(result, dict):
        raise RuntimeError("El plano de control de MyKOS devolvió un formato inesperado.")
    return result


def sync_gateway_activity(operation: str, activity_id: str, payload: dict[str, Any] | None = None) -> None:
    """Replica el indicador efímero en el Gateway sin afectar al turno si falla.

    La actividad es de presentación y se puede reconstruir en la siguiente
    actualización; nunca debe interrumpir una respuesta de modelo por una
    incidencia del indicador.
    """
    if not (MYKOS_GATEWAY_ENABLED and MYKOS_CONTROL_TOKEN and activity_id):
        return
    body = {"operation": operation, "activity_id": activity_id}
    if isinstance(payload, dict):
        body.update({key: value for key, value in payload.items() if not key.endswith("_epoch")})
    try:
        mykos_gateway_control_request("activity", body, timeout=10)
    except RuntimeError:
        pass

set_sync_gateway_fn(sync_gateway_activity)


def controller_authorize_action(
    tool_name: str,
    action: dict[str, Any],
    conversation_id: str,
    *,
    auto_grant: bool = False,
) -> dict[str, Any]:
    """Pide al Gateway la decisión de permiso; Python no decide en modo Gateway."""
    if MYKOS_GATEWAY_ENABLED and MYKOS_CONTROL_TOKEN:
        return mykos_gateway_control_request(
            "authorize",
            {
                "tool_name": tool_name,
                "action": action,
                "conversation_id": conversation_id,
                "auto_grant": auto_grant,
            },
        )
    descriptor = permission_descriptor(tool_name, action)
    grant = find_grant(descriptor, conversation_id)
    if grant is None:
        return {
            "ok": True,
            "decision": "approval_required",
            "descriptor": descriptor,
            "permission": permission_request_view(tool_name, action),
        }
    return {
        "ok": True,
        "decision": "granted",
        "descriptor": descriptor,
        "permission": permission_request_view(tool_name, action),
        "grant": {key: value for key, value in grant.items() if key not in {"scope_key", "session_id", "approval_id"}},
        "authorization": {"permission_id": grant.get("id", ""), "scope_key": grant.get("scope_key", "")},
    }


def controller_create_approval(payload: dict[str, Any]) -> dict[str, Any]:
    if MYKOS_GATEWAY_ENABLED and MYKOS_CONTROL_TOKEN:
        return mykos_gateway_control_request("approval", {"operation": "create", **payload})
    return create_pending_approval(
        str(payload.get("conversation_id", "")),
        str(payload.get("model", "")),
        payload.get("messages") if isinstance(payload.get("messages"), list) else [],
        str(payload.get("tool_name", "")),
        payload.get("action") if isinstance(payload.get("action"), dict) else {},
        bool(payload.get("supports_vision", False)),
        payload.get("generation") if isinstance(payload.get("generation"), dict) else {},
        str(payload.get("conversation_permission_mode", "supervisado") or "supervisado"),
    )


def controller_resolve_approval(
    approval_id: str,
    decision: str,
    permission_mode: str,
    conversation_permission_mode: str = "supervisado",
) -> dict[str, Any]:
    if MYKOS_GATEWAY_ENABLED and MYKOS_CONTROL_TOKEN:
        return mykos_gateway_control_request(
            "approval",
            {
                "operation": "resolve",
                "approval_id": approval_id,
                "decision": decision,
                "permission_mode": permission_mode,
                "conversation_permission_mode": conversation_permission_mode,
            },
        )
    return {"ok": False, "error": "El controlador de aprobaciones local no está disponible."}


def controller_execute_remote_model(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool,
    generation: dict[str, Any] | None,
    activity_id: str | None,
    permission_mode: str,
) -> dict[str, Any]:
    if MYKOS_GATEWAY_ENABLED and MYKOS_CONTROL_TOKEN:
        return mykos_gateway_control_request(
            "remote-model",
            {
                "model": model,
                "messages": messages,
                "conversation_id": conversation_id,
                "supports_vision": supports_vision,
                "generation": generation if isinstance(generation, dict) else {},
                "activity_id": activity_id or "",
                "permission_mode": permission_mode,
            },
        )
    return {"ok": False, "error": "El controlador remoto no está disponible."}


def controller_execute_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    if MYKOS_GATEWAY_ENABLED and MYKOS_CONTROL_TOKEN:
        return mykos_gateway_control_request(
            "tool",
            {"tool_name": name, "arguments": arguments if isinstance(arguments, dict) else {}},
        )
    return execute_tool(name, arguments)


def controller_execute_action(
    action: dict[str, Any],
    conversation_id: str = "",
    authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if MYKOS_GATEWAY_ENABLED and MYKOS_CONTROL_TOKEN:
        return mykos_gateway_control_request(
            "action",
            {
                "action": action,
                "conversation_id": conversation_id or str(action.get("conversation_id", "")),
                "authorization": authorization if isinstance(authorization, dict) else {},
            },
        )
    return execute_approved_action(action)


def controller_run_chat_loop(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool,
    generation: dict[str, Any] | None,
    activity_id: str | None,
    permission_mode: str,
) -> dict[str, Any]:
    """Deja que el Gateway ejecute el bucle de herramientas del modelo local (chat-loop.js).

    El Gateway devuelve además el contexto tal como acaba (`_messages`) y los ajustes finales (`_generation`): se copian
    a las listas/diccionarios de quien llama, que los usa después para el medidor de contexto de la interfaz.
    """
    try:
        result = mykos_gateway_control_request(
            "loop",
            {
                "model": model,
                "messages": messages,
                "conversation_id": conversation_id,
                "supports_vision": supports_vision,
                "generation": generation if isinstance(generation, dict) else {},
                "activity_id": activity_id or "",
                "permission_mode": permission_mode,
            },
            timeout=3600,
        )
    except ControlPlaneHTTPError as error:
        # El mensaje del bucle (p. ej. «El modelo terminó sin devolver texto») llega tal cual, no envuelto en un HTTP 502.
        raise RuntimeError(error.client_message or str(error)) from error
    final_messages = result.pop("_messages", None)
    final_generation = result.pop("_generation", None)
    if isinstance(final_messages, list):
        messages[:] = final_messages
    if isinstance(final_generation, dict) and isinstance(generation, dict):
        generation.clear()
        generation.update(final_generation)
    return result


def _gateway_action_route_signature(raw_body: bytes) -> str:
    payload = b"gateway-action\0" + raw_body
    return hmac.new(MYKOS_CONTROL_TOKEN.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _verify_gateway_decision(method: str, path: str, header: str) -> tuple[bool, str]:
    """Comprueba la decisión firmada del Gateway. Devuelve (válida, hash del cuerpo esperado o «-»)."""
    parts = str(header or "").strip().split(".")
    if len(parts) != 4 or parts[0] != "v1" or not MYKOS_CONTROL_TOKEN:
        return False, ""
    _, raw_expires, body_hash, signature = parts
    try:
        expires = int(raw_expires)
    except (TypeError, ValueError):
        return False, ""
    now = int(time.time())
    if expires < now or expires > now + GATEWAY_DECISION_MAX_AGE:
        return False, ""
    if body_hash != "-" and not re.fullmatch(r"[0-9a-f]{64}", body_hash):
        return False, ""
    payload = f"gateway-decision|{method} {path}|{body_hash}|{expires}".encode("utf-8")
    expected = hmac.new(MYKOS_CONTROL_TOKEN.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False, ""
    return True, body_hash


def _verify_gateway_execution_grant(
    action: dict[str, Any],
    conversation_id: str,
    authorization: dict[str, Any] | None,
) -> bool:
    grant = authorization.get("gateway_execution_grant") if isinstance(authorization, dict) else None
    if not isinstance(grant, dict):
        return False
    approval_id = str(grant.get("approval_id", ""))
    grant_conversation = str(grant.get("conversation_id", ""))
    scope_key = str(grant.get("scope_key", ""))
    signature = str(grant.get("signature", ""))
    try:
        expires_at = int(grant.get("expires_at", 0))
    except (TypeError, ValueError):
        return False
    if not approval_id or grant_conversation != str(conversation_id or "") or expires_at < int(time.time()):
        return False
    descriptor = permission_descriptor(str(action.get("kind", "")), action)
    if scope_key != str(descriptor.get("scope_key", "")):
        return False
    payload = f"approval|{approval_id}|{grant_conversation}|{scope_key}|{expires_at}".encode("utf-8")
    expected = hmac.new(MYKOS_CONTROL_TOKEN.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(signature, expected)


def llama_cpp_configured() -> bool:
    return bool(
        LLAMA_CPP_EXE
        and LLAMA_CPP_MODEL
        and Path(LLAMA_CPP_EXE).is_file()
        and Path(LLAMA_CPP_MODEL).is_file()
    )


def ensure_llama_cpp_server() -> None:
    global LLAMA_CPP_PROCESS
    try:
        health = _llama_cpp_request("/health", timeout=1)
        if health.get("status") in {"ok", "loading model"}:
            return
    except RuntimeError:
        pass
    if not llama_cpp_configured():
        raise RuntimeError(
            "El motor llama.cpp CUDA no está configurado: faltan el ejecutable o el GGUF."
        )
    with LLAMA_CPP_PROCESS_LOCK:
        try:
            health = _llama_cpp_request("/health", timeout=1)
            if health.get("status") in {"ok", "loading model"}:
                return
        except RuntimeError:
            pass
        if LLAMA_CPP_PROCESS is not None and LLAMA_CPP_PROCESS.poll() is not None:
            LLAMA_CPP_PROCESS = None
        command = [
            LLAMA_CPP_EXE,
            "-m", LLAMA_CPP_MODEL,
            "-c", str(LLAMA_CPP_CONTEXT_LENGTH),
            "-n", "8192",
            "-ngl", "20",
            "-fa", "auto",
            "--reasoning", "auto",
            
            "--no-webui",
            "--host", urllib.parse.urlparse(LLAMA_CPP_URL).hostname or "127.0.0.1",
            "--port", str(urllib.parse.urlparse(LLAMA_CPP_URL).port or 8091),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        LLAMA_CPP_PROCESS = subprocess.Popen(
            command,
            cwd=str(Path(LLAMA_CPP_EXE).parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        deadline = time.monotonic() + LLAMA_CPP_START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if LLAMA_CPP_PROCESS.poll() is not None:
                code = LLAMA_CPP_PROCESS.returncode
                LLAMA_CPP_PROCESS = None
                raise RuntimeError(f"llama.cpp no pudo arrancar (código {code}).")
            try:
                health = _llama_cpp_request("/health", timeout=1)
                if health.get("status") == "ok":
                    return
            except RuntimeError:
                time.sleep(0.5)
        raise RuntimeError("llama.cpp tardó demasiado en cargar el modelo CUDA.")


def llama_cpp_model_summary() -> dict[str, Any] | None:
    if not llama_cpp_configured():
        return None
    return {
        "name": LLAMA_CPP_MODEL_NAME,
        "label": LLAMA_CPP_MODEL_LABEL,
        "provider": "llama_cpp",
        "provider_label": "llama.cpp · CUDA",
        "size": Path(LLAMA_CPP_MODEL).stat().st_size,
        "parameter_size": "35.5B",
        "family": "Qwen3.6 · qwen35moe",
        "quantization": "Q4_K_M",
        "modified_at": "",
        "capabilities": ["chat", "completion", "thinking", "tools"],
        "chat_capable": True,
        "vision_capable": False,
        "thinking_capable": True,
        "tools_capable": True,
        "context_length": LLAMA_CPP_CONTEXT_LENGTH,
        "remote": False,
        "remote_host": "",
        "benchmark_capable": True,
        "engine": "llama.cpp CUDA",
    }


def llama_cpp_chat_request(
    messages: list[dict[str, Any]],
    generation: dict[str, Any],
) -> dict[str, Any]:
    options = generation.get("options") if isinstance(generation, dict) else {}
    options = options if isinstance(options, dict) else {}
    payload: dict[str, Any] = {
        "model": LLAMA_CPP_MODEL_NAME,
        "messages": [
            {
                key: value
                for key, value in item.items()
                if key in {"role", "content", "images", "tool_calls", "tool_call_id"}
            }
            for item in messages
        ],
        "stream": False,
        "max_tokens": int(options.get("num_predict", 1536) or 1536),
        "temperature": float(options.get("temperature", 0.5) or 0.5),
    }
    effort = str(generation.get("effort", "")).strip().casefold()
    if effort == "off":
        payload["reasoning_effort"] = "none"
    elif effort in {"low", "medium", "high"}:
        payload["reasoning_effort"] = effort
    if TOOL_SCHEMAS:
        payload["tools"] = TOOL_SCHEMAS
        payload["tool_choice"] = "auto"
    if MYKOS_GATEWAY_ENABLED and MYKOS_CONTROL_TOKEN:
        return mykos_gateway_model_request("llama_cpp", payload)
    ensure_llama_cpp_server()
    return _llama_cpp_request("/v1/chat/completions", payload, timeout=600)


def model_summary(model: dict[str, Any]) -> dict[str, Any]:
    details = model.get("details") or {}
    capabilities = [str(item) for item in (model.get("capabilities") or [])]
    remote = bool(
        model.get("remote_model")
        or model.get("remote_host")
        or str(model.get("name", "")).endswith(":cloud")
    )
    return {
        "name": model.get("name", ""),
        "label": model.get("name", ""),
        "provider": "ollama",
        "size": model.get("size", 0),
        "parameter_size": details.get("parameter_size", ""),
        "family": details.get("family", ""),
        "quantization": details.get("quantization_level", ""),
        "modified_at": model.get("modified_at", ""),
        "capabilities": capabilities,
        # Sin capacidades declaradas se asume chat (Ollama antiguo), salvo que la entrada no tenga
        # formato de modelo o sea de voz/embeddings (p. ej. mannix/whisper): esas no saben conversar.
        "chat_capable": bool(CHAT_CAPABILITIES.intersection(capabilities)) if capabilities else bool(
            details.get("format") and not re.search(r"whisper|embed", str(model.get("name", "")), re.IGNORECASE)
        ),
        "vision_capable": "vision" in capabilities,
        "thinking_capable": "thinking" in capabilities,
        "tools_capable": "tools" in capabilities,
        "context_length": details.get("context_length", 0),
        "remote": remote,
        "remote_host": model.get("remote_host", ""),
        "benchmark_capable": not remote,
    }


from core.providers import (
    gemini_model_catalog,
    grok_model_catalog,
    kimi_model_catalog,
    logout_meta_ai,
    logout_openrouter,
    meta_ai_model_catalog,
    mistral_model_catalog,
    nvidia_model_catalog,
    openrouter_model_catalog,
    refresh_anthropic_models,
    refresh_antigravity_models,
    refresh_qwen_models,
    refresh_gemini_models,
    refresh_grok_models,
    refresh_kimi_models,
    refresh_meta_ai_models,
    refresh_mistral_models,
    refresh_nvidia_models,
    refresh_openrouter_models,
    start_grok_login,
    start_meta_ai_login,
    start_openrouter_login,
    _logout_anthropic,
    _logout_antigravity,
    _logout_qwen,
    _logout_gemini,
    _logout_grok,
    _logout_kimi,
    _logout_mistral,
    _logout_nvidia,
    ANTHROPIC_MODEL_CACHE,
    GEMINI_MODEL_CACHE,
    GROK_MODEL_CACHE,
    KIMI_MODEL_CACHE,
    MISTRAL_MODEL_CACHE,
    NVIDIA_MODEL_CACHE,
    OPENROUTER_MODEL_CACHE,
)


def get_ollama_models() -> list[dict[str, Any]]:
    result = ollama_request("/api/tags", timeout=10)
    models = result.get("models", [])
    if not isinstance(models, list):
        return []
    return [model_summary(model) for model in models if isinstance(model, dict)]


def get_model_catalog() -> tuple[list[dict[str, Any]], str]:
    ollama_models: list[dict[str, Any]] = []
    ollama_error = ""
    try:
        ollama_models = get_ollama_models()
    except RuntimeError as error:
        ollama_error = str(error)
    models = [*ollama_models]
    llama_model = llama_cpp_model_summary()
    if llama_model is not None:
        models.append(llama_model)
    try:
        models.extend(strata_model_catalog())
    except Exception as error:
        pass
    claude = claude_model_summary()
    if claude and claude.get("chat_capable"):
        models.append(claude)
    models.extend([m for m in openai_model_summaries() if m.get("chat_capable")])
    openrouter_models, _openrouter_authenticated, _openrouter_error = openrouter_model_catalog()
    models.extend(openrouter_models)
    nvidia_models, _nvidia_authenticated, _nvidia_error = nvidia_model_catalog()
    models.extend(nvidia_models)
    kimi_catalog, _kimi_authenticated, _kimi_error = kimi_model_catalog()
    models.extend(kimi_catalog)
    gemini_catalog, _gemini_authenticated, _gemini_error = gemini_model_catalog()
    models.extend(gemini_catalog)
    mistral_catalog, _mistral_authenticated, _mistral_error = mistral_model_catalog()
    models.extend(mistral_catalog)
    anthropic_catalog, _anthropic_authenticated, _anthropic_error = anthropic_model_catalog()
    models.extend(anthropic_catalog)
    antigravity_catalog, _antigravity_authenticated, _antigravity_error = antigravity_model_catalog()
    models.extend(antigravity_catalog)
    qwen_catalog, _qwen_authenticated, _qwen_error = qwen_model_catalog()
    models.extend(qwen_catalog)
    meta_ai_catalog, _meta_ai_authenticated, _meta_ai_error = meta_ai_model_catalog()
    models.extend(meta_ai_catalog)
    grok_catalog, _grok_authenticated, _grok_error = grok_model_catalog()
    models.extend(grok_catalog)
    return models, ollama_error


def get_models() -> list[dict[str, Any]]:
    models, _ollama_error = get_model_catalog()
    return models


def available_chat_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [model for model in models if model.get("chat_capable", True)]


def choose_default_model(models: list[dict[str, Any]]) -> str:
    chat_models = available_chat_models(models)
    local_model = next(
        (
            model for model in chat_models
            if not model.get("remote") and model.get("provider") == "ollama"
        ),
        None,
    )
    if local_model is None:
        local_model = next((model for model in chat_models if not model.get("remote")), None)
    selected = local_model or (chat_models[0] if chat_models else None)
    return str(selected.get("name", "")) if selected else ""


def normalise_generation_settings(
    raw_settings: Any,
    selected_model: dict[str, Any],
    *,
    has_attachments: bool = False,
    attachment_count: int = 0,
) -> dict[str, Any]:
    raw = raw_settings if isinstance(raw_settings, dict) else {}
    effort = str(raw.get("effort", "off")).strip().casefold()
    speed = str(raw.get("speed", "balanced")).strip().casefold()
    creativity = str(raw.get("creativity", "balanced")).strip().casefold()
    if effort not in GENERATION_EFFORTS:
        effort = "off"
    if speed not in GENERATION_SPEEDS:
        speed = "balanced"
    if creativity not in GENERATION_CREATIVITY:
        creativity = "balanced"

    preset = GENERATION_PRESETS[speed]
    context_length = selected_model.get("context_length") or 0
    try:
        context_length = int(context_length)
    except (TypeError, ValueError):
        context_length = 0
    num_ctx = int(preset["num_ctx"])
    if has_attachments:
        try:
            attachment_count = max(1, min(4, int(attachment_count)))
        except (TypeError, ValueError):
            attachment_count = 1
        num_ctx = max(num_ctx, ATTACHMENT_NUM_CTX * attachment_count)
    if context_length > 0:
        num_ctx = min(num_ctx, max(2048, context_length))
    if selected_model.get("provider") == "anthropic_oauth":
        # Claude Code manages the real tokenizer/context window. MyKOS keeps a
        # conservative 131K display budget instead of pretending that the
        # short Ollama presets are Claude's actual context limit.
        num_ctx = CLAUDE_CONTEXT_LENGTH
    elif selected_model.get("provider") == "openai_codex_oauth":
        num_ctx = 258_400

    thinking_capable = bool(selected_model.get("thinking_capable"))
    # Los modelos locales con razonamiento (p. ej. Qwen3.6) alucinan y afirman acciones que no han
    # hecho cuando piensan en modo "off". Se fuerza al menos "medium"; MYKOS_FORCE_THINK=0 lo desactiva.
    if (
        thinking_capable
        and effort == "off"
        and selected_model.get("provider") in {"ollama", "llama_cpp"}
        and os.environ.get("MYKOS_FORCE_THINK", "1").strip() != "0"
    ):
        effort = "medium"
    think: bool | str = False
    if thinking_capable and effort != "off":
        think = effort

    return {
        "effort": effort,
        "speed": speed,
        "creativity": creativity,
        "think": think,
        "thinking_supported": thinking_capable,
        "options": {
            "num_ctx": num_ctx,
            # Con razonamiento activo, el pensamiento consume tokens: sin margen se corta antes de la respuesta.
            "num_predict": max(int(preset["num_predict"]), 2048) if think else int(preset["num_predict"]),
            "temperature": CREATIVITY_TEMPERATURE[creativity],
        },
    }


def system_prompt_for_model(selected_model: dict[str, Any]) -> str:
    model_name = str(selected_model.get("name") or "modelo no identificado")
    model_label = str(selected_model.get("label") or model_name)
    provider = str(selected_model.get("provider") or "").strip()
    if not provider:
        if model_name.startswith("openai-codex-oauth/") or model_name == "gpt-live-1-codex":
            provider = "openai_codex_oauth"
        elif model_name == CLAUDE_MODEL_NAME:
            provider = "anthropic_oauth"
        elif model_name == LLAMA_CPP_MODEL_NAME:
            provider = "llama_cpp"
        elif model_name.startswith("strata/"):
            provider = "strata"
        elif model_name.startswith("openrouter/"):
            provider = "openrouter"
        elif model_name.startswith("nvidia/"):
            provider = "nvidia_api"
        elif model_name.startswith("kimi/"):
            provider = "kimi_api"
        elif model_name.startswith("gemini/"):
            provider = "gemini_api"
        elif model_name.startswith("mistral/"):
            provider = "mistral_api"
        elif model_name.startswith("antigravity/"):
            provider = "antigravity_cli"
        elif model_name.startswith("qwen-cli/"):
            provider = "qwen_cli"
    if provider == "openai_codex_oauth":
        processing_scope = "remoto a través de OpenAI Codex usando una sesión OAuth propia de MyKOS"
        provider_note = (
            "Este adaptador usa una sesión OAuth independiente de MyKOS. "
            "Codex no debe usar sus herramientas nativas: las herramientas válidas son únicamente las de MyKOS, "
            "solicitadas mediante el protocolo JSON controlado por el servidor."
        )
    elif provider == "anthropic_oauth":
        processing_scope = "remoto a través de Claude Code usando la sesión OAuth de claude.ai"
        provider_note = (
            "Este adaptador de Claude funciona sin API key dentro de MyKOS. "
            "Las herramientas de MyKOS se solicitan mediante el protocolo JSON controlado por el servidor; "
            "Claude no recibe acceso directo a PowerShell, archivos ni MCP."
        )
    elif provider == "llama_cpp":
        processing_scope = "local en este equipo mediante llama.cpp con CUDA"
        provider_note = (
            "Este MyKOS está usando el motor independiente llama.cpp con CUDA. "
            "La petición pasa por el Gateway propio de MyKOS, que ejecuta y controla las herramientas; "
            "el motor no tiene acceso directo al sistema de archivos ni a PowerShell."
        )
    elif provider == "strata":
        processing_scope = "local en este equipo mediante Strata con GPU CUDA en http://127.0.0.1:18080"
        provider_note = (
            "Este MyKOS está usando el motor local de alto rendimiento Strata con CUDA. "
            "La petición pasa por el Gateway propio de MyKOS, que ejecuta y controla las herramientas; "
            "el motor no tiene acceso directo al sistema de archivos ni al sistema operativo."
        )
    elif provider == "openrouter":
        processing_scope = "remoto a través de OpenRouter mediante OAuth propio de MyKOS"
        provider_note = (
            "La petición se envía directamente al endpoint oficial de OpenRouter. "
            "Las herramientas de MyKOS se solicitan mediante el protocolo JSON controlado por el servidor."
        )
    elif provider == "nvidia_api":
        processing_scope = "remoto a través de NVIDIA NIM mediante la API propia de MyKOS"
        provider_note = (
            "La petición se envía directamente al endpoint oficial de NVIDIA NIM. "
            "Las herramientas de MyKOS se solicitan mediante el protocolo JSON controlado por el servidor."
        )
    elif provider == "kimi_api":
        processing_scope = "remoto a través de Kimi API mediante la credencial propia de MyKOS"
        provider_note = (
            "La petición se envía directamente al endpoint oficial de Kimi API. "
            "Las herramientas de MyKOS se solicitan mediante el protocolo JSON controlado por el servidor."
        )
    elif provider == "gemini_api":
        processing_scope = "remoto a través de Google AI Studio mediante la credencial propia de MyKOS"
        provider_note = "La petición se envía directamente al endpoint oficial de Gemini API (Google AI Studio)."
    elif provider == "mistral_api":
        processing_scope = "remoto a través de Mistral AI / Vibe mediante la sesión autenticada"
        provider_note = (
            "La petición se envía directamente al endpoint oficial de Mistral AI con la sesión de Vibe. "
            "Las herramientas de MyKOS se solicitan mediante el protocolo JSON controlado por el servidor."
        )
    elif provider == "meta_ai_oauth":
        processing_scope = "remoto a través de Meta AI (gateway.meta.ai) mediante la sesión OAuth de MyKOS"
        provider_note = (
            "La petición se envía a Meta AI (Llama 4) mediante la sesión OAuth protegida de MyKOS. "
            "Las herramientas de MyKOS se solicitan mediante el protocolo JSON controlado por el servidor."
        )
    elif provider == "antigravity_cli":
        processing_scope = "remoto a través de Antigravity CLI (agy) con la sesión Google aislada de MyKOS"
        provider_note = (
            "LÍMITE DEL PROVEEDOR: en esta petición Antigravity CLI solo admite conversación de texto y "
            "no recibe herramientas de MyKOS. No declares que vas a ejecutar, abrir, guardar, buscar, ni solicitar "
            "aprobación para una herramienta: no podrías invocarla. Si Usuario pide una acción sobre el equipo o archivos, "
            "di con claridad y brevedad que este proveedor concreto no puede ejecutarla y que debe elegir un modelo de MyKOS "
            "con herramientas. No le des comandos para que haga él una acción que te ha pedido ejecutar."
        )
    elif provider == "qwen_cli":
        processing_scope = "remoto a través de Qwen Code CLI con el perfil seguro de MyKOS"
        provider_note = (
            "LÍMITE DEL PROVEEDOR: en esta petición Qwen Code CLI solo admite conversación de texto y "
            "no recibe herramientas de MyKOS. No declares que vas a ejecutar, abrir, guardar, buscar, ni solicitar "
            "aprobación para una herramienta: no podrías invocarla. Si Usuario pide una acción sobre el equipo o archivos, "
            "di con claridad y brevedad que este proveedor concreto no puede ejecutarla y que debe elegir un modelo de MyKOS "
            "con herramientas. No le des comandos para que haga él una acción que te ha pedido ejecutar."
        )
    else:
        processing_scope = "remoto a través de Ollama" if selected_model.get("remote") else "local en este equipo"
        provider_note = ""
    prompt = (
        f"{INTEGRITY_RULES}\n"
        f"{load_system_prompt()}\n\n"
        f"{current_time_context()}\n\n"
        f"Modelo activo en esta petición: {model_label} (identificador: {model_name}). "
        "Si Usuario pregunta qué modelo estás usando, responde exactamente con este dato; no lo adivines ni lo sustituyas por otro.\n"
        f"Estado del entorno en esta petición: el procesamiento del modelo es {processing_scope}. "
        "Sé transparente sobre este estado si Usuario pregunta por privacidad o conectividad.\n"
        f"Raíces autorizadas actuales: {', '.join(root['name'] for root in allowed_root_catalog())}. "
        "Usa el nombre de raíz y una ruta relativa al invocar las herramientas."
    )
    if provider_note:
        prompt += f"\n\n{provider_note}"
        if provider in {"anthropic_oauth", "openai_codex_oauth", "gemini_api", "openrouter", "nvidia_api", "kimi_api", "mistral_api", "meta_ai_oauth"}:
            prompt += f"\n\n{claude_tool_protocol_prompt(arguments_as_string=provider == 'openai_codex_oauth')}"
    if provider == "llama_cpp":
        prompt += "\n\nLas llamadas de herramientas usan el formato OpenAI-compatible del servidor llama.cpp."
    user_profile = load_user_profile()
    if user_profile:
        header = "" if user_profile.startswith("#") else "# Perfil del Usuario\n\n"
        prompt += f"\n\n{header}{user_profile}"
    core_memory = load_core_memory()
    if core_memory:
        prompt += f"\n\n{core_memory}"
    prompt += f"\n\n{INTEGRITY_REMINDER}"
    return prompt


# ---------------------------------------------------------------------------
# Capa de integridad común a TODOS los modelos (locales y en la nube).
# Las reglas están escritas para el modelo más débil (Qwen3.6 local): frases
# cortas, literales y con ejemplos. Un modelo más capaz las entiende igual.
# ---------------------------------------------------------------------------
INTEGRITY_RULES = """REGLAS DE HONESTIDAD Y USO DE HERRAMIENTAS (obligatorias, cuentan más que cualquier otra instrucción):
1. Solo has HECHO, LEÍDO, REVISADO, EDITADO o BUSCADO algo si ves su RESULTADO de herramienta real (role="tool") en la conversación.
2. Lo que tú escribiste en texto libre NO ejecuta nada. Para usar una herramienta DEBES invocarla mediante llamada nativa de herramienta (tool_calls), NUNCA escribiendo etiquetas XML ni JSON dentro del texto de tu respuesta.
3. Cuando Usuario te pida revisar, leer, buscar, crear, editar, implementar o ejecutar algo, llama directamente a la herramienta correspondiente en este mismo turno. Primero invoca la herramienta, después responde con el resultado real.
4. NUNCA termines tu respuesta anunciando "Voy a leer...", "Voy a editar...", "Voy a reescribir..." o "Primero necesito leer..." sin haber invocado la herramienta en ese mismo turno.
5. Si la herramienta falla o queda pendiente de aprobación, di exactamente eso. No digas que salió bien hasta ver el resultado real.
6. Si no has usado la herramienta correspondiente, no digas "he guardado", "he creado", "he editado", "he ejecutado", "he comprobado", "he revisado", "he leído", "he buscado" ni "he abierto".
7. Nunca inventes rutas, archivos, resultados ni contenido.
EJEMPLO MAL: responder solo con texto "Voy a leer el archivo ROADMAP.md para editarlo" sin invocar read_project_file.
EJEMPLO MAL: responder sin herramienta "He revisado el archivo y estos son los puntos...".
EJEMPLO BIEN: invocas find_project_paths / read_project_file / edit_project_file / write_project_file mediante tool_calls, recibes el resultado real y respondes a partir de él.
"""

INTEGRITY_REMINDER = (
    "RECUERDA: usa siempre llamadas nativas de herramienta (tool_calls) para leer, buscar o editar archivos; "
    "nunca anuncies «Voy a leer/editar...» sin invocar la herramienta en este turno, ni digas que has hecho algo sin ver su resultado real."
)


def _handle_sensitive_tool_in_loop(
    *,
    tool_name: str,
    tool_arguments: dict[str, Any],
    provider_label: str,
    conversation_id: str,
    model: str,
    working_messages: list[dict[str, Any]],
    source_cards: list[dict[str, str]],
    tool_names: list[str],
    supports_vision: bool,
    generation: dict[str, Any],
    permission_mode: str,
    activity_id: str | None,
    proposal: str = "",
    append_result_fn: Any = None,
) -> dict[str, Any] | None:
    """Punto único de autorización/aprobación de herramientas sensibles para todos los modelos remotos."""
    def _append(res: dict[str, Any]) -> None:
        if append_result_fn is not None:
            append_result_fn(res)
        else:
            working_messages.append(tool_message_for_result(res, supports_vision))

    if permission_mode == "solo_lectura":
        _append({
            "ok": False,
            "action": tool_name,
            "error": (
                f"Modo «Solo lectura» activo: no se pueden ejecutar acciones que modifiquen el sistema («{tool_name}»). "
                "Cambia el modo a Supervisado o Acceso total si quieres continuar."
            ),
        })
        return None
    if tool_name == "save_research_note" and not research_sources_are_verified(
        tool_arguments,
        source_cards + source_cards_from_messages(working_messages),
    ):
        _append({
            "ok": False,
            "requires_approval": True,
            "error": (
                "No se puede preparar la ficha todavía: primero debes usar web_search o web_fetch "
                "y citar únicamente las URLs que esas herramientas hayan devuelto."
            ),
        })
        return None
    auto_result, auto_grant = _authorized_sensitive_action(tool_name, tool_arguments, conversation_id)
    if auto_grant is not None:
        update_activity(
            activity_id,
            status="working",
            phase="tool",
            label="Permiso concedido; ejecutando.",
            detail=f"Se ha reutilizado un permiso {auto_grant.get('mode', 'activo')} para «{tool_name}».",
        )
        _append(auto_result or {})
        return None
    if permission_mode == "acceso_total":
        granted_result, new_grant = _auto_grant_sensitive_action(tool_name, tool_arguments, conversation_id)
        if new_grant is not None:
            update_activity(
                activity_id,
                status="working",
                phase="tool",
                label="Acceso total; permiso concedido y ejecutado.",
                detail=f"Se ha concedido permiso permanente a «{tool_name}» (modo Acceso total).",
            )
            _append(granted_result or {})
            return None
    update_activity(
        activity_id,
        status="waiting",
        phase="approval",
        label="Esperando tu aprobación…",
        detail=f"{provider_label} propone la herramienta «{tool_name}». Revisa la acción en el panel.",
    )
    pending = create_pending_approval(
        conversation_id,
        model,
        working_messages,
        tool_name,
        tool_arguments,
        supports_vision,
        generation=generation,
        conversation_permission_mode=permission_mode,
    )
    if pending.get("ok"):
        return {
            "pending_action": pending["approval"],
            "proposal": proposal,
            "tools_used": sorted(set(tool_names)),
            "sources": source_cards,
            "done": False,
        }
    _append(pending)
    return None


def run_claude_until_result(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
    permission_mode: str = "supervisado",
) -> dict[str, Any]:
    """Run Claude Code through the authenticated claude.ai subscription.

    Claude's native tools remain disabled. MyKOS executes read-only tools itself
    and turns sensitive ones into the same approval flow used by Ollama.
    """
    if model != CLAUDE_MODEL_NAME:
        raise RuntimeError(f"Modelo Claude no reconocido: {model}")
    system_prompt = next(
        (str(item.get("content", "")) for item in messages if item.get("role") == "system"),
        system_prompt_for_model({"provider": "anthropic_oauth"}),
    )
    working_messages = [dict(item) for item in messages]
    tool_names: list[str] = []
    verified_tool_trace: list[dict[str, Any]] = []
    response_guard_retries = 0
    integrity_retries = 0
    source_cards = source_cards_from_messages(working_messages, current_turn_only=True)
    generation = generation if isinstance(generation, dict) else {}
    request_deadline = time.monotonic() + MAX_REQUEST_TIMEOUT_SECONDS

    for tool_round in range(MAX_TOOL_ROUNDS + 1):
        if time.monotonic() > request_deadline:
            raise ApiError(408, f"Se superó el tiempo límite de la petición ({MAX_REQUEST_TIMEOUT_SECONDS}s). Abortando.")
        update_activity(
            activity_id,
            status="working",
            phase="model",
            label="Trabajando…",
            detail="Claude Sonnet · OAuth está procesando la petición.",
        )
        # Windows limits the complete CreateProcess command line to about
        # 32 KiB.  The MyKOS system prompt includes all tool schemas and can
        # exceed that limit when passed directly as --system-prompt, causing
        # WinError 206 before Claude Code even starts.  Use Claude's file
        # form instead and remove the short-lived file in every case.
        system_prompt_file: str | None = None
        try:
            descriptor, system_prompt_file = tempfile.mkstemp(prefix="mykos-sp-", suffix=".txt")
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(system_prompt)

            arguments = [
                "--print",
                "--model",
                CLAUDE_CLI_MODEL,
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(CLAUDE_RESPONSE_SCHEMA, ensure_ascii=False, separators=(",", ":")),
                "--no-session-persistence",
                "--tools",
                "",
                "--permission-mode",
                "dontAsk",
                "--system-prompt-file",
                system_prompt_file,
            ]
            effort = str(generation.get("effort", "off")).strip().casefold()
            if effort in {"low", "medium", "high", "xhigh", "max"}:
                arguments.extend(["--effort", effort])
            completed = run_claude_cli(
                arguments,
                input_text=claude_prompt_from_messages(working_messages),
                timeout=CLAUDE_REQUEST_TIMEOUT_SECONDS,
            )
        finally:
            if system_prompt_file:
                try:
                    Path(system_prompt_file).unlink()
                except OSError:
                    pass
        parsed = parse_claude_response(completed)
        if parsed["kind"] == "answer":
            guard_reason = claude_unverified_tool_claim_reason(parsed["content"], verified_tool_trace)
            if guard_reason:
                if response_guard_retries >= MAX_CLAUDE_RESPONSE_GUARD_RETRIES:
                    raise RuntimeError(
                        "Claude insistió en afirmar un resultado de herramienta que el host no puede verificar. "
                        "La respuesta se bloqueó para no mostrar información falsa."
                    )
                response_guard_retries += 1
                working_messages.append(
                    tool_message_for_result(
                        {
                            "ok": False,
                            "action": "response_integrity_guard",
                            "error": guard_reason,
                        },
                        supports_vision,
                    )
                )
                continue
            integrity_action, _integrity_trace = integrity_check_answer(
                working_messages, parsed["content"], integrity_retries
            )
            if integrity_action == "retry":
                integrity_retries += 1
                continue
            if integrity_action == "warn":
                parsed["content"] = str(parsed["content"]) + INTEGRITY_UNVERIFIED_NOTE
            assistant_message = {
                "role": "assistant",
                "model": model,
                "content": parsed["content"],
                "created_at": utc_now(),
            }
            if verified_tool_trace:
                assistant_message["verified_tool_trace"] = verified_tool_trace
            if source_cards:
                assistant_message["sources"] = source_cards
            save_assistant_message(conversation_id, assistant_message)
            return {
                "message": assistant_message,
                "tools_used": sorted(set(tool_names)),
                "sources": source_cards,
                "done": True,
            }

        if tool_round >= MAX_TOOL_ROUNDS:
            raise RuntimeError("Claude solicitó demasiadas rondas de herramientas.")

        tool_name = str(parsed["tool_name"])
        tool_arguments = parsed["arguments"]
        tool_names.append(tool_name)
        working_messages.append(
            {
                "role": "assistant",
                "model": model,
                "content": json.dumps(parsed, ensure_ascii=False, separators=(",", ":")),
            }
        )
        if tool_name in SENSITIVE_TOOL_NAMES:
            pending_response = _handle_sensitive_tool_in_loop(
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                provider_label="Claude",
                conversation_id=conversation_id,
                model=model,
                working_messages=working_messages,
                source_cards=source_cards,
                tool_names=tool_names,
                supports_vision=supports_vision,
                generation=generation,
                permission_mode=permission_mode,
                activity_id=activity_id,
                proposal=str(parsed.get("content", "")),
                append_result_fn=lambda res: append_verified_claude_tool_result(
                    working_messages, verified_tool_trace, tool_name, res, supports_vision
                ),
            )
            if pending_response is not None:
                return pending_response
            continue

        update_activity(
            activity_id,
            status="working",
            phase="tool",
            label="Consultando una herramienta…",
            detail=f"Claude ha solicitado «{tool_name}»; MyKOS la está consultando.",
        )
        tool_result = controller_execute_tool(tool_name, tool_arguments)
        merge_source_cards(source_cards, tool_result)
        append_verified_claude_tool_result(working_messages, verified_tool_trace, tool_name, tool_result, supports_vision)

    raise RuntimeError("Claude no terminó dentro del límite de rondas.")


def run_openai_until_result(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
    permission_mode: str = "supervisado",
) -> dict[str, Any]:
    if not model.startswith("openai-codex-oauth/"):
        raise RuntimeError(f"Modelo OpenAI no reconocido: {model}")
    working_messages = [dict(item) for item in messages]
    source_cards = source_cards_from_messages(working_messages, current_turn_only=True)
    tool_names: list[str] = []
    generation = generation if isinstance(generation, dict) else {}
    ledger_fn = globals().get("inline_verified_ledger")
    if callable(ledger_fn):
        working_messages = ledger_fn(working_messages)
    integrity_fn = globals().get("integrity_check_answer")
    integrity_retries = 0
    request_deadline = time.monotonic() + MAX_REQUEST_TIMEOUT_SECONDS
    for tool_round in range(MAX_TOOL_ROUNDS + 1):
        if time.monotonic() > request_deadline:
            raise ApiError(408, f"Se superó el tiempo límite de la petición ({MAX_REQUEST_TIMEOUT_SECONDS}s). Abortando.")
        update_activity(
            activity_id,
            status="working",
            phase="model",
            label="Trabajando…",
            detail="OpenAI · Codex OAuth propio de MyKOS está procesando la petición.",
        )
        parsed = run_openai_codex(working_messages, OPENAI_RESPONSE_SCHEMA, model.removeprefix("openai-codex-oauth/"))
        kind = str(parsed.get("kind", "")).strip().casefold()
        if kind == "answer":
            content = str(parsed.get("content", "")).strip()
            integrity_trace = []
            if callable(integrity_fn):
                integrity_action, integrity_trace = integrity_fn(working_messages, content, integrity_retries)
                if integrity_action == "retry":
                    integrity_retries += 1
                    continue
                if integrity_action == "warn":
                    content += INTEGRITY_UNVERIFIED_NOTE
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "model": model,
                "content": content,
                "created_at": utc_now(),
            }
            if integrity_trace:
                assistant_message["verified_tool_trace"] = integrity_trace
            if source_cards:
                assistant_message["sources"] = source_cards
            save_assistant_message(conversation_id, assistant_message)
            return {"message": assistant_message, "tools_used": sorted(set(tool_names)), "sources": source_cards, "done": True}
        if tool_round >= MAX_TOOL_ROUNDS:
            raise RuntimeError("OpenAI solicitó demasiadas rondas de herramientas.")
        tool_name = str(parsed.get("tool_name", "")).strip()
        raw_arguments = parsed.get("arguments", "{}")
        if isinstance(raw_arguments, str):
            try:
                tool_arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as error:
                raise RuntimeError("OpenAI devolvió argumentos de herramienta que no son JSON válidos.") from error
        else:
            tool_arguments = raw_arguments
        allowed_tools = {
            str((schema.get("function") or {}).get("name", ""))
            for schema in TOOL_SCHEMAS
            if isinstance(schema, dict) and isinstance(schema.get("function"), dict)
        }
        if not tool_name or tool_name not in allowed_tools or not isinstance(tool_arguments, dict):
            raise RuntimeError(f"OpenAI solicitó una herramienta no permitida: {tool_name or '(vacía)'}.")
        tool_names.append(tool_name)
        working_messages.append({
            "role": "assistant",
            "model": model,
            "content": json.dumps(parsed, ensure_ascii=False, separators=(",", ":")),
        })
        if tool_name in SENSITIVE_TOOL_NAMES:
            pending_response = _handle_sensitive_tool_in_loop(
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                provider_label="OpenAI",
                conversation_id=conversation_id,
                model=model,
                working_messages=working_messages,
                source_cards=source_cards,
                tool_names=tool_names,
                supports_vision=supports_vision,
                generation=generation,
                permission_mode=permission_mode,
                activity_id=activity_id,
                proposal=str(parsed.get("content", "")),
            )
            if pending_response is not None:
                return pending_response
            continue
        update_activity(activity_id, status="working", phase="tool", label="Consultando una herramienta…", detail=f"OpenAI ha solicitado «{tool_name}»; MyKOS la está consultando.")
        tool_result = controller_execute_tool(tool_name, tool_arguments)
        merge_source_cards(source_cards, tool_result)
        working_messages.append(tool_message_for_result(tool_result, supports_vision))
    raise RuntimeError("OpenAI no terminó dentro del límite de rondas.")


def run_benchmark(payload: dict[str, Any]) -> dict[str, Any]:
    return execute_benchmark_suite(
        payload,
        get_models_fn=get_models,
        available_chat_models_fn=available_chat_models,
        choose_default_model_fn=choose_default_model,
        normalise_settings_fn=normalise_generation_settings,
        ollama_request_fn=ollama_request,
        llama_cpp_chat_fn=llama_cpp_chat_request,
        strata_chat_fn=strata_chat_request,
        gateway_requester=controller_request_model if (MYKOS_GATEWAY_ENABLED and MYKOS_CONTROL_TOKEN) else None,
        utc_now_fn=utc_now,
    )


def find_conversation(store: dict[str, Any], conversation_id: str | None) -> dict[str, Any] | None:
    if not conversation_id:
        return None
    for conversation in store["conversations"]:
        if conversation.get("id") == conversation_id:
            return conversation
    return None


def openrouter_prompt_from_messages(messages: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    last_user = ""
    for message in messages:
        role = str(message.get("role", "mensaje")).strip().upper()
        content = str(message.get("content", "")).strip() or "(sin texto)"
        blocks.append(f"<{role}>\n{content}\n</{role}>")
        if role == "USER":
            last_user = content.casefold()
    simple_greeting = bool(
        re.fullmatch(
            r"(?:hola|buenas|buenos días|buenas tardes|buenas noches)(?:[ ,]+mykos)?[!.?¡¿ ]*",
            last_user,
            flags=re.IGNORECASE,
        )
    )
    closing = (
        "ÚLTIMO TURNO: es un saludo simple. Responde únicamente: «¡Hola! ¿Qué tal?» "
        "No menciones MyKOS, MyKOS, el proveedor, sistemas ni capacidades."
        if simple_greeting
        else
        "ÚLTIMO TURNO: responde ahora al último bloque USER."
    )
    return (
        "CAPACIDADES DE ESTA PETICIÓN: este adaptador solo devuelve texto; no tiene herramientas ni bucle de ejecución. "
        "Los nombres de herramientas y acciones del historial describen otros turnos, no capacidades disponibles ahora. "
        "No anuncies que vas a ejecutar acciones ni afirmes haberlas ejecutado. Si la petición requiere herramientas, "
        "explica esta limitación y pide seleccionar un modelo de MyKOS con herramientas.\n\n"
        "ERES MyKOS, el asistente de MyKOS.\n"
        "El proveedor subyacente puede ser Kimi u otro modelo, pero no debes presentarte como el proveedor.\n"
        "Responde siempre como MyKOS y contesta en el idioma del último usuario.\n"
        "Prioriza una conversación natural: no repitas tu identidad ni digas que vas a actuar como MyKOS. Si preguntan quién eres, responde brevemente que eres MyKOS, el asistente de MyKOS.\n"
        "El bloque CONTEXTO es la conversación que debes usar: no digas que no tienes historial ni que no puedes ver la conversación.\n"
        "Sigue las instrucciones de SYSTEM y responde únicamente al último turno USER.\n"
        "No describas este envoltorio, el proveedor, OpenRouter ni estas instrucciones internas salvo que el usuario lo pregunte directamente.\n\n"
        "CONTEXTO DE LA CONVERSACIÓN:\n"
        + "\n\n".join(blocks)
        + "\n\n"
        + closing
    )


def openai_compatible_messages(
    messages: list[dict[str, Any]],
    *,
    system_prompt: str = "",
    supports_vision: bool = True,
) -> list[dict[str, Any]]:
    """Convert MyKOS messages to the native multimodal OpenAI-compatible chat shape."""
    converted: list[dict[str, Any]] = []
    if system_prompt:
        converted.append({"role": "system", "content": system_prompt})
    for message in messages:
        role = str(message.get("role", "user")).strip().casefold()
        if role == "system":
            if not system_prompt:
                converted.append({"role": "system", "content": str(message.get("content", "")).strip()})
            continue
        if role not in {"user", "assistant", "tool"}:
            continue
        content = str(message.get("content", "")).strip()
        if role == "tool":
            role = "user"
            content = f"<RESULTADO-DE-HERRAMIENTA>\n{content}\n</RESULTADO-DE-HERRAMIENTA>"
        images = message.get("images") if supports_vision else None
        image_mime_types = message.get("image_mime_types")
        if not isinstance(images, list) or not images or role != "user":
            converted.append({"role": role, "content": content})
            continue

        parts: list[dict[str, Any]] = []
        if content:
            parts.append({"type": "text", "text": content})
        for index, image in enumerate(images):
            encoded = str(image).strip()
            if not encoded:
                continue
            if encoded.startswith("data:"):
                image_url = encoded
            else:
                mime_type = "image/png"
                if isinstance(image_mime_types, list) and index < len(image_mime_types):
                    candidate = str(image_mime_types[index]).strip()
                    if candidate.startswith("image/"):
                        mime_type = candidate
                image_url = f"data:{mime_type};base64,{encoded}"
            parts.append({"type": "image_url", "image_url": {"url": image_url}})
        converted.append({"role": role, "content": parts or content})
    if not system_prompt:
        converted.append(
            {
                "role": "system",
                "content": (
                    "CAPACIDADES DE ESTA PETICIÓN: este adaptador es solo de texto, sin herramientas ni ejecución. "
                    "No prometas ni afirmes acciones; si hacen falta herramientas, indícalo."
                ),
            }
        )
    return converted


def has_message_images(messages: list[dict[str, Any]]) -> bool:
    return any(isinstance(message.get("images"), list) and message.get("images") for message in messages)


def _run_openai_json_tool_loop(
    model: str,
    provider: str,
    provider_label: str,
    activity_detail: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    completion_fn: Any,
    *,
    raw_completion_fn: Any = None,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
    permission_mode: str = "supervisado",
) -> dict[str, Any]:
    return execute_openai_json_tool_loop(
        model=model,
        provider=provider,
        provider_label=provider_label,
        activity_detail=activity_detail,
        messages=messages,
        conversation_id=conversation_id,
        completion_fn=completion_fn,
        system_prompt_fn=system_prompt_for_model,
        source_cards_fn=source_cards_from_messages,
        merge_source_cards_fn=merge_source_cards,
        tool_message_fn=tool_message_for_result,
        openai_compatible_messages_fn=openai_compatible_messages,
        controller_execute_tool_fn=controller_execute_tool,
        save_assistant_message_fn=save_assistant_message,
        handle_sensitive_tool_fn=_handle_sensitive_tool_in_loop,
        utc_now_fn=utc_now,
        raw_completion_fn=raw_completion_fn,
        supports_vision=supports_vision,
        generation=generation,
        activity_id=activity_id,
        permission_mode=permission_mode,
    )


def run_openrouter_until_result(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
    permission_mode: str = "supervisado",
) -> dict[str, Any]:
    if not model.startswith("openrouter/"):
        raise RuntimeError(f"Modelo OpenRouter no reconocido: {model}")
    generation = generation if isinstance(generation, dict) else {}
    speed = str(generation.get("speed", "balanced")).strip().casefold()
    max_tokens = {"fast": 2048, "balanced": 4096, "quality": 6144, "full": 8192}.get(speed, 4096)
    creativity = str(generation.get("creativity", "precise")).strip().casefold()
    temperature = {"precise": 0.2, "balanced": 0.5, "creative": 0.8}.get(creativity, 0.2)
    model_id = model.removeprefix("openrouter/")

    def _complete(req_messages: list[dict[str, Any]]) -> str:
        result = openrouter_api_json(
            "chat/completions",
            method="POST",
            timeout=OPENROUTER_REQUEST_TIMEOUT_SECONDS,
            payload={
                "model": model_id,
                "messages": req_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            },
        )
        choices = result.get("choices") if isinstance(result.get("choices"), list) else []
        first = choices[0] if choices and isinstance(choices[0], dict) else {}
        response_message = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = response_message.get("content", "")
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
        content = str(content).strip()
        if not content:
            raise RuntimeError(str(result.get("error") or "OpenRouter no devolvió texto."))
        return content

    return _run_openai_json_tool_loop(
        model,
        "openrouter",
        "OpenRouter",
        f"{model} · OpenRouter mediante OAuth propio de MyKOS.",
        messages,
        conversation_id,
        _complete,
        supports_vision=supports_vision or has_message_images(messages),
        generation=generation,
        activity_id=activity_id,
        permission_mode=permission_mode,
    )


def run_antigravity_until_result(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
) -> dict[str, Any]:
    if not model.startswith("antigravity/"):
        raise RuntimeError(f"Modelo Antigravity no reconocido: {model}")
    if supports_vision or has_message_images(messages):
        raise RuntimeError("Antigravity CLI en MyKOS solo admite texto por ahora.")
    from antigravity_cli import ask
    update_activity(activity_id, status="working", phase="model", label="Trabajando…", detail=f"{model} · CLI aislado sin herramientas.")
    prompt = openrouter_prompt_from_messages(messages[-12:])
    if len(prompt) > 12000:
        prompt = prompt[-12000:]
    result = ask(prompt, timeout_seconds=90, model=model.removeprefix("antigravity/"))
    content = str(result.get("response", "")).strip()
    if not content:
        raise RuntimeError("Antigravity no devolvió texto.")
    assistant_message = {"role": "assistant", "model": model, "content": content, "created_at": utc_now()}
    save_assistant_message(conversation_id, assistant_message)
    return {"message": assistant_message, "tools_used": [], "sources": [], "done": True,
            "usage": result.get("usage", {}), "duration_seconds": result.get("duration_seconds")}


def run_qwen_until_result(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
) -> dict[str, Any]:
    if not model.startswith("qwen-cli/"):
        raise RuntimeError(f"Modelo Qwen CLI no reconocido: {model}")
    if supports_vision or has_message_images(messages):
        raise RuntimeError("Qwen Code CLI en MyKOS solo admite texto por ahora.")
    from qwen_cli import ask_qwen
    update_activity(activity_id, status="working", phase="model", label="Trabajando…", detail=f"{model} · Qwen Code CLI.")
    prompt = openrouter_prompt_from_messages(messages[-12:])
    if len(prompt) > 12000:
        prompt = prompt[-12000:]
    result = ask_qwen(prompt, timeout_seconds=90, model=model.removeprefix("qwen-cli/"))
    content = str(result.get("response", "")).strip()
    if not content:
        raise RuntimeError("Qwen Code CLI no devolvió texto.")
    assistant_message = {"role": "assistant", "model": model, "content": content, "created_at": utc_now()}
    save_assistant_message(conversation_id, assistant_message)
    return {"message": assistant_message, "tools_used": [], "sources": [], "done": True,
            "usage": result.get("usage", {}), "duration_seconds": result.get("duration_seconds")}


def run_nvidia_until_result(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
    permission_mode: str = "supervisado",
) -> dict[str, Any]:
    if not model.startswith("nvidia/"):
        raise RuntimeError(f"Modelo NVIDIA no reconocido: {model}")
    generation = generation if isinstance(generation, dict) else {}
    speed = str(generation.get("speed", "balanced")).strip().casefold()
    max_tokens = {"fast": 2048, "balanced": 4096, "quality": 6144, "full": 8192}.get(speed, 4096)
    creativity = str(generation.get("creativity", "precise")).strip().casefold()
    temperature = {"precise": 0.2, "balanced": 0.5, "creative": 0.8}.get(creativity, 0.2)
    return _run_openai_json_tool_loop(
        model,
        "nvidia_api",
        "NVIDIA NIM",
        f"{model} · NVIDIA NIM mediante API directa de MyKOS.",
        messages,
        conversation_id,
        lambda req_messages: nvidia_chat_completion(
            model,
            req_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ),
        supports_vision=supports_vision or has_message_images(messages),
        generation=generation,
        activity_id=activity_id,
        permission_mode=permission_mode,
    )


def run_kimi_until_result(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
    permission_mode: str = "supervisado",
) -> dict[str, Any]:
    if not model.startswith("kimi/"):
        raise RuntimeError(f"Modelo Kimi no reconocido: {model}")
    if has_message_images(messages):
        raise RuntimeError("Kimi API está disponible en MyKOS solo para texto por ahora.")
    generation = generation if isinstance(generation, dict) else {}
    speed = str(generation.get("speed", "balanced")).strip().casefold()
    max_tokens = {"fast": 2048, "balanced": 4096, "quality": 6144, "full": 8192}.get(speed, 4096)
    creativity = str(generation.get("creativity", "precise")).strip().casefold()
    temperature = {"precise": 0.2, "balanced": 0.5, "creative": 0.8}.get(creativity, 0.2)
    return _run_openai_json_tool_loop(
        model,
        "kimi_api",
        "Kimi",
        f"{model} · Kimi API directa de MyKOS.",
        messages,
        conversation_id,
        lambda req_messages: kimi_chat_completion(
            model,
            req_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ),
        supports_vision=False,
        generation=generation,
        activity_id=activity_id,
        permission_mode=permission_mode,
    )


def run_grok_until_result(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    *,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
    permission_mode: str = "supervisado",
) -> dict[str, Any]:
    if not model.startswith("grok/"):
        raise RuntimeError(f"Modelo Grok no reconocido: {model}")
    generation = generation if isinstance(generation, dict) else {}
    speed = str(generation.get("speed", "balanced")).strip().casefold()
    max_tokens = {"fast": 2048, "balanced": 4096, "quality": 8192, "full": 16384}.get(speed, 4096)
    creativity = str(generation.get("creativity", "precise")).strip().casefold()
    temperature = {"precise": 0.2, "balanced": 0.5, "creative": 0.8}.get(creativity, 0.2)
    auth = grok_auth_status()
    provider_id = "grok_oauth" if auth.get("mode") == "oauth" else "grok_api"
    return _run_openai_json_tool_loop(
        model,
        provider_id,
        "Grok",
        f"{model} · xAI Grok directa de MyKOS.",
        messages,
        conversation_id,
        lambda req_messages: grok_chat_completion(
            model,
            req_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ),
        supports_vision=supports_vision,
        generation=generation,
        activity_id=activity_id,
        permission_mode=permission_mode,
    )


def parse_gemini_response(result_text: str) -> dict[str, Any]:
    return core_parse_gemini_response(result_text)


def run_gemini_until_result(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool = True,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
    permission_mode: str = "supervisado",
) -> dict[str, Any]:
    if not model.startswith("gemini/"):
        raise RuntimeError(f"Modelo Gemini no reconocido: {model}")
    generation = generation if isinstance(generation, dict) else {}
    speed = str(generation.get("speed", "balanced")).strip().casefold()
    max_tokens = {"fast": 2048, "balanced": 4096, "quality": 6144, "full": 8192}.get(speed, 4096)
    creativity = str(generation.get("creativity", "precise")).strip().casefold()
    temperature = {"precise": 0.2, "balanced": 0.5, "creative": 0.8}.get(creativity, 0.2)
    return _run_openai_json_tool_loop(
        model,
        "gemini_api",
        "Gemini",
        f"{model} · Google AI Studio (Gemini).",
        messages,
        conversation_id,
        None,
        raw_completion_fn=lambda working_msgs, sys_prompt: gemini_chat_completion(
            model,
            working_msgs,
            max_tokens=max_tokens,
            temperature=temperature,
            system_prompt=sys_prompt,
            response_schema=GEMINI_RESPONSE_SCHEMA,
        ),
        supports_vision=supports_vision,
        generation=generation,
        activity_id=activity_id,
        permission_mode=permission_mode,
    )


def run_anthropic_until_result(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
    permission_mode: str = "supervisado",
) -> dict[str, Any]:
    generation = generation if isinstance(generation, dict) else {}
    return _run_openai_json_tool_loop(
        model,
        "anthropic_api",
        "Anthropic · Claude",
        f"{model} · Anthropic API directa en MyKOS.",
        messages,
        conversation_id,
        lambda req_messages: anthropic_chat_completion(
            model,
            req_messages,
            generation=generation,
        ),
        supports_vision=supports_vision or has_message_images(messages),
        generation=generation,
        activity_id=activity_id,
        permission_mode=permission_mode,
    )


def run_mistral_until_result(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
    permission_mode: str = "supervisado",
) -> dict[str, Any]:
    if not model.startswith("mistral/"):
        raise RuntimeError(f"Modelo Mistral no reconocido: {model}")
    generation = generation if isinstance(generation, dict) else {}
    speed = str(generation.get("speed", "balanced")).strip().casefold()
    max_tokens = {"fast": 2048, "balanced": 4096, "quality": 6144, "full": 8192}.get(speed, 4096)
    creativity = str(generation.get("creativity", "precise")).strip().casefold()
    temperature = {"precise": 0.2, "balanced": 0.5, "creative": 0.8}.get(creativity, 0.2)
    return _run_openai_json_tool_loop(
        model,
        "mistral_api",
        "Mistral · Vibe",
        f"{model} · Mistral API mediante sesión Vibe de MyKOS.",
        messages,
        conversation_id,
        lambda req_messages: mistral_chat_completion(
            model,
            req_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ),
        supports_vision=supports_vision or has_message_images(messages),
        generation=generation,
        activity_id=activity_id,
        permission_mode=permission_mode,
    )


def run_meta_ai_until_result(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
    permission_mode: str = "supervisado",
) -> dict[str, Any]:
    if not model.startswith("meta-ai/"):
        raise RuntimeError(f"Modelo Meta AI no reconocido: {model}")
    generation = generation if isinstance(generation, dict) else {}
    speed = str(generation.get("speed", "balanced")).strip().casefold()
    max_tokens = {"fast": 2048, "balanced": 4096, "quality": 6144, "full": 8192}.get(speed, 4096)
    creativity = str(generation.get("creativity", "precise")).strip().casefold()
    temperature = {"precise": 0.2, "balanced": 0.5, "creative": 0.8}.get(creativity, 0.2)
    return _run_openai_json_tool_loop(
        model,
        "meta_ai_oauth",
        "Meta AI · OAuth",
        f"{model} · Meta AI mediante sesión OAuth protegida de MyKOS.",
        messages,
        conversation_id,
        lambda req_messages: meta_ai_chat_completion(
            model,
            req_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ),
        supports_vision=False,
        generation=generation,
        activity_id=activity_id,
        permission_mode=permission_mode,
    )


def run_model_until_result(
    model: str,
    messages: list[dict[str, Any]],
    conversation_id: str,
    supports_vision: bool = False,
    generation: dict[str, Any] | None = None,
    activity_id: str | None = None,
    permission_mode: str = "supervisado",
    remote_worker: bool = False,
) -> dict[str, Any]:
    """Run the selected provider until it returns text or pauses for approval."""
    gateway_controls_models = MYKOS_GATEWAY_ENABLED and bool(MYKOS_CONTROL_TOKEN)
    is_remote_model = (
        model.startswith("antigravity/")
        or model.startswith("qwen-cli/")
        or model.startswith("meta-ai/")
        or model.startswith("nvidia/")
        or model.startswith("kimi/")
        or model.startswith("gemini/")
        or model.startswith("mistral/")
        or model.startswith("anthropic/")
        or model.startswith("openrouter/")
        or model.startswith("grok/")
        or model.startswith("openai-codex-oauth/") or model == "gpt-live-1-codex"
        or model == CLAUDE_MODEL_NAME
    )
    if gateway_controls_models and is_remote_model and not remote_worker:
        return controller_execute_remote_model(
            model,
            messages,
            conversation_id,
            supports_vision,
            generation,
            activity_id,
            permission_mode,
        )
    if gateway_controls_models and MYKOS_GATEWAY_CHAT_LOOP and not is_remote_model:
        # Modelo local (llama.cpp u Ollama): el bucle de herramientas lo ejecuta el Gateway.
        return controller_run_chat_loop(
            model,
            messages,
            conversation_id,
            supports_vision,
            generation,
            activity_id,
            permission_mode,
        )
    if model != LLAMA_CPP_MODEL_NAME and not gateway_controls_models:
        stop_llama_cpp_server()
    if model.startswith("antigravity/"):
        return run_antigravity_until_result(
            model, messages, conversation_id, supports_vision=supports_vision,
            generation=generation, activity_id=activity_id,
        )
    if model.startswith("qwen-cli/"):
        return run_qwen_until_result(
            model, messages, conversation_id, supports_vision=supports_vision,
            generation=generation, activity_id=activity_id,
        )
    if model.startswith("meta-ai/"):
        return run_meta_ai_until_result(
            model,
            messages,
            conversation_id,
            supports_vision=supports_vision,
            generation=generation,
            activity_id=activity_id,
            permission_mode=permission_mode,
        )
    if model.startswith("nvidia/"):
        return run_nvidia_until_result(
            model,
            messages,
            conversation_id,
            supports_vision=supports_vision,
            generation=generation,
            activity_id=activity_id,
            permission_mode=permission_mode,
        )
    if model.startswith("kimi/"):
        return run_kimi_until_result(
            model,
            messages,
            conversation_id,
            supports_vision=supports_vision,
            generation=generation,
            activity_id=activity_id,
            permission_mode=permission_mode,
        )
    if model.startswith("gemini/"):
        return run_gemini_until_result(
            model,
            messages,
            conversation_id,
            supports_vision=supports_vision,
            generation=generation,
            activity_id=activity_id,
            permission_mode=permission_mode,
        )
    if model.startswith("mistral/"):
        return run_mistral_until_result(
            model,
            messages,
            conversation_id,
            supports_vision=supports_vision,
            generation=generation,
            activity_id=activity_id,
            permission_mode=permission_mode,
        )
    if model.startswith("anthropic/"):
        return run_anthropic_until_result(
            model,
            messages,
            conversation_id,
            supports_vision=supports_vision,
            generation=generation,
            activity_id=activity_id,
            permission_mode=permission_mode,
        )
    if model.startswith("grok/"):
        return run_grok_until_result(
            model,
            messages,
            conversation_id,
            supports_vision=supports_vision,
            generation=generation,
            activity_id=activity_id,
            permission_mode=permission_mode,
        )
    if model.startswith("openrouter/"):
        return run_openrouter_until_result(
            model,
            messages,
            conversation_id,
            supports_vision=supports_vision,
            generation=generation,
            activity_id=activity_id,
            permission_mode=permission_mode,
        )
    if model.startswith("openai-codex-oauth/") or model == "gpt-live-1-codex":
        # "gpt-4o" no está soportado por Codex con cuenta ChatGPT (confirmado: error 400
        # del proveedor); la delegación de la llamada Realtime usa el mismo modelo que el
        # resto de MyKOS para Codex OAuth.
        return run_openai_until_result(
            "openai-codex-oauth/gpt-5.6-luna" if model == "gpt-live-1-codex" else model,
            messages,
            conversation_id,
            supports_vision=supports_vision,
            generation=generation,
            activity_id=activity_id,
            permission_mode=permission_mode,
        )
    if model == CLAUDE_MODEL_NAME:
        if get_anthropic_api_key():
            return run_anthropic_until_result(
                "anthropic/claude-3-5-sonnet-latest",
                messages,
                conversation_id,
                supports_vision=supports_vision,
                generation=generation,
                activity_id=activity_id,
                permission_mode=permission_mode,
            )
        return run_claude_until_result(
            model,
            messages,
            conversation_id,
            supports_vision=supports_vision,
            generation=generation,
            activity_id=activity_id,
            permission_mode=permission_mode,
        )
    # Cualquier modelo local (Ollama o llama.cpp) delega siempre al bucle del Gateway.
    return controller_run_chat_loop(
        model,
        messages,
        conversation_id,
        supports_vision,
        generation,
        activity_id,
        permission_mode,
    )


def fetch_ollama_catalog(query: str = "") -> dict[str, Any]:
    return core_fetch_ollama_catalog(query, get_models_fn=get_models)


def _job_public(job: dict[str, Any]) -> dict[str, Any]:
    from core.ollama_catalog import job_public
    return job_public(job)


def _set_ollama_job(job_id: str, **updates: Any) -> dict[str, Any]:
    return core_set_ollama_job(job_id, utc_now, **updates)


def _run_ollama_pull_job(job_id: str, action: dict[str, Any]) -> None:
    return core_run_ollama_pull_job(job_id, action, utc_now)


def create_panel_approval(
    tool_name: str,
    arguments: dict[str, Any],
    conversation_id: str = "",
) -> dict[str, Any]:
    prepared = prepare_approval_action(tool_name, arguments)
    if not prepared.get("ok"):
        return prepared
    action = dict(prepared["action"])
    permission = permission_request_view(tool_name, action)
    action["panel_request"] = True
    job_id = ""
    if tool_name == "pull_ollama_model":
        job_id = uuid.uuid4().hex
        action["panel_job_id"] = job_id
        _set_ollama_job(
            job_id,
            model=action.get("model", ""),
            status="awaiting_approval",
            message="Esperando aprobación…",
        )
    existing_grant = find_grant(permission, conversation_id)
    if existing_grant is not None:
        if tool_name == "pull_ollama_model":
            _set_ollama_job(job_id, status="running", message="Descargando con permiso concedido.")
            thread = threading.Thread(
                target=_run_ollama_pull_job,
                args=(job_id, action),
                daemon=True,
                name=f"mykos-ollama-pull-{job_id[:8]}",
            )
            thread.start()
            record_audit(
                "permission_used",
                permission,
                mode=str(existing_grant.get("mode", "")),
                permission_id=str(existing_grant.get("id", "")),
                session_id=conversation_id,
            )
            with OLLAMA_JOBS_LOCK:
                job = _job_public(OLLAMA_JOBS.get(job_id, {"id": job_id}))
            return {"ok": True, "executed": True, "permission_id": existing_grant.get("id", ""), "job": job}
        result = controller_execute_action(action)
        record_audit(
            "permission_used",
            permission,
            mode=str(existing_grant.get("mode", "")),
            status="ok" if result.get("ok") else "failed",
            permission_id=str(existing_grant.get("id", "")),
            session_id=conversation_id,
            detail=str(result.get("error", "")),
        )
        return {"ok": bool(result.get("ok")), "executed": True, "permission_id": existing_grant.get("id", ""), "action_result": result}
    now = time.time()
    record = {
        "id": uuid.uuid4().hex,
        "status": "pending",
        "conversation_id": conversation_id,
        "model": "",
        "supports_vision": False,
        "tool_name": tool_name,
        "action": action,
        "permission": permission,
        "messages": [],
        "created_at": utc_now(),
        "expires_at": datetime.fromtimestamp(now + APPROVAL_TTL_SECONDS, timezone.utc).isoformat(timespec="seconds"),
        "expires_at_epoch": now + APPROVAL_TTL_SECONDS,
    }
    with STORE_LOCK:
        store = load_approval_store()
        purge_approvals(store)
        store["approvals"].append(record)
        save_approval_store(store)
    record_audit(
        "approval_created",
        permission,
        mode="once",
        approval_id=str(record["id"]),
        session_id=conversation_id,
    )
    return {
        "ok": True,
        "approval": approval_public_view(record),
        "job": _job_public(OLLAMA_JOBS[job_id]) if job_id else None,
    }


def _cleanup_uploads() -> None:
    cleanup_uploads(UPLOAD_DIR, UPLOADS, UPLOADS_LOCK, UPLOAD_RETENTION_SECONDS, ALLOWED_UPLOAD_EXTENSIONS)


def register_uploads(content_type: str, body: bytes) -> list[dict[str, Any]]:
    return process_multipart_uploads(
        content_type,
        body,
        UPLOAD_DIR,
        UPLOADS,
        UPLOADS_LOCK,
        utc_now_fn=utc_now,
        api_error_cls=ApiError,
        retention_seconds=UPLOAD_RETENTION_SECONDS,
        max_request_bytes=MAX_UPLOAD_REQUEST_BYTES,
        max_upload_files=MAX_UPLOAD_FILES,
        allowed_extensions=ALLOWED_UPLOAD_EXTENSIONS,
    )


def backend_health(check_gateway: bool = False) -> dict[str, Any]:

    """Estado barato del backend para el Gateway: no toca modelos ni Ollama."""
    info: dict[str, Any] = {
        "ok": True,
        "service": "mykos-backend",
        "pid": os.getpid(),
        "ppid": os.getppid() if hasattr(os, "getppid") else None,
        "port": PORT,
        "public_port": PUBLIC_PORT,
        "backend_only": BACKEND_ONLY,
        "gateway_url": MYKOS_GATEWAY_URL,
        "store_mode": gateway_store.mode(),
    }
    if check_gateway:
        try:
            with urllib.request.urlopen(f"{MYKOS_GATEWAY_URL}/health", timeout=1.5) as response:
                info["gateway_reachable"] = response.status == 200
        except Exception:  # noqa: BLE001 - una sonda de estado nunca debe fallar
            info["gateway_reachable"] = False
        if gateway_store.ENABLED:
            docs = gateway_store.store_info()
            info["store_reachable"] = docs is not None
            if docs is not None:
                info["store_docs"] = {name: {"revision": doc.get("revision"), "count": doc.get("count")} for name, doc in docs.items()}
    return info


class MyKOSHandler(BaseHTTPRequestHandler):
    server_version = "MyKOS/1.0"

    def log_message(self, format_string: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format_string % args}")

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        try:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except UnicodeEncodeError:
            # Una mitad de par suplente (p. ej. «\ud800» en un JSON del cliente) no cabe en UTF-8: se escapa en vez de fallar.
            encoded = json.dumps(payload, ensure_ascii=True).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Length", str(len(encoded)))
        try:
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def worker_authorized(self, path: str) -> bool:
        """Solo el Gateway puede llamar a /api/* (salvo /api/health, que usan la supervisión y el diagnóstico)."""
        self._expected_body_hash = ""  # una conexión reutilizada no debe heredar la decisión de la petición anterior
        if not WORKER_GUARD or not path.startswith("/api/") or path == "/api/health":
            return True
        supplied = self.headers.get("X-MyKOS-Control-Token", "").strip()
        if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(supplied.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
            self.send_json({"error": "Esta ruta solo acepta peticiones del Gateway de MyKOS."}, status=403)
            return False
        return self.gateway_decided(path)

    def gateway_decided(self, path: str) -> bool:
        """Las rutas de servicios auxiliares solo se ejecutan con la decisión firmada del Gateway."""
        route = (self.command, path)
        if route not in GATEWAY_DECISION_ROUTES:
            return True
        valid, body_hash = _verify_gateway_decision(
            str(self.command),
            path,
            self.headers.get(GATEWAY_DECISION_HEADER, ""),
        )
        if valid and body_hash == "-" and route not in GATEWAY_DECISION_UNBOUND_BODY:
            valid = False  # en estas rutas la decisión tiene que ir ligada al cuerpo exacto
        if not valid:
            self.send_json(
                {"error": "Esta acción necesita la decisión firmada del Gateway de MyKOS."},
                status=403,
            )
            return False
        self._expected_body_hash = body_hash
        return True

    def send_bytes(self, data: bytes, content_type: str, status: int = 200, content_disposition: str = "") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        if content_disposition:
            self.send_header("Content-Disposition", content_disposition)
        self.send_header("Content-Length", str(len(data)))
        try:
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_openrouter_callback_page(self, message: str, *, success: bool) -> None:
        safe_message = html.escape(message)
        title = "OpenRouter conectado" if success else "No se pudo conectar OpenRouter"
        color = "#77f3c1" if success else "#ff9b9b"
        page = f"""<!doctype html>
<html lang=\"es\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>{html.escape(title)}</title></head>
<body style=\"margin:0;display:grid;min-height:100vh;place-items:center;background:#1d2932;color:#e7f5f8;font:16px system-ui,sans-serif;text-align:center\">
<main><h1 style=\"color:{color}\">{html.escape(title)}</h1><p>{safe_message}</p><p>Volviendo a MyKOS…</p></main>
<script>setTimeout(() => window.location.replace('/'), 1800);</script></body></html>""".encode("utf-8")
        self.send_bytes(page, "text/html; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path, _, query = self.path.partition("?")
        if not self.worker_authorized(path):
            return
        if path == "/":
            self.serve_static("index.html", "text/html; charset=utf-8")
            return
        if path == "/api/health":
            params = self.parse_query(query)
            self.send_json(backend_health(check_gateway=params.get("gateway", ["0"])[0] == "1"))
            return
        if path == "/mykos-control/activity":
            token = self.headers.get("X-MyKOS-Control-Token", "").strip()
            if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                return
            params = self.parse_query(query)
            activity_id = params.get("activity_id", [""])[0].strip()
            conversation_id = params.get("conversation_id", [""])[0].strip()
            self.send_json(activity_public_view(activity_id, conversation_id))
            return
        if path == "/mykos-control/media-status":
            token = self.headers.get("X-MyKOS-Control-Token", "").strip()
            if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                return
            self.send_json({"ok": True, "status": media_status()})
            return
        if path == "/mykos-control/management-status":
            token = self.headers.get("X-MyKOS-Control-Token", "").strip()
            if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                return
            self.send_json({"ok": True, "status": local_status()})
            return
        if path == "/mykos-control/tools-catalog":
            token = self.headers.get("X-MyKOS-Control-Token", "").strip()
            if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                return
            self.send_json({"ok": True, "tools": tool_catalog(), "allowed_roots": allowed_root_catalog()})
            return
        if path == "/mykos-control/models-catalog":
            token = self.headers.get("X-MyKOS-Control-Token", "").strip()
            if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                return
            try:
                self.send_json({"ok": True, "models": get_models()})
            except RuntimeError as error:
                self.send_json({"ok": False, "error": str(error), "models": []}, status=503)
            return
        if path == "/mykos-control/status-catalog":
            token = self.headers.get("X-MyKOS-Control-Token", "").strip()
            if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                return
            try:
                models = get_models()
                self.send_json(
                    {
                        "ok": True,
                        "ollama_url": OLLAMA_URL,
                        "models": models,
                        "default_model": DEFAULT_MODEL or choose_default_model(models),
                        "tools": tool_catalog(),
                        "allowed_roots": allowed_root_catalog(),
                        "memory": memory_catalog(),
                        "benchmark_profiles": benchmark_profile_catalog(),
                    }
                )
            except RuntimeError as error:
                self.send_json({"ok": False, "error": str(error), "models": []}, status=503)
            return
        if path == "/mykos-control/oauth/openrouter/callback":
            token = self.headers.get("X-MyKOS-Control-Token", "").strip()
            if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                return
            params = self.parse_query(query)
            code = params.get("code", [""])[0].strip()
            error = params.get("error_description", params.get("error", [""]))[0].strip()
            try:
                result = complete_openrouter_oauth(code, error)
                success = result.get("status") == "completed"
                message = "La sesión OAuth de OpenRouter está guardada en MyKOS." if success else str(result.get("error", "Autorización cancelada."))
                self.send_openrouter_callback_page(message, success=success)
            except RuntimeError as exc:
                result = complete_openrouter_oauth(error=str(exc))
                self.send_openrouter_callback_page(str(result.get("error", str(exc))), success=False)
            return
        if path.startswith("/static/"):
            relative_path = path.removeprefix("/static/")
            if "/" in relative_path or "\\" in relative_path or relative_path in {"", ".", ".."}:
                self.send_json({"error": "Recurso no válido."}, status=400)
                return
            self.serve_static(relative_path)
            return
        self.send_json({"error": "Ruta no encontrada."}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler

        path = self.path.partition("?")[0]
        if not self.worker_authorized(path):
            return
        try:
            if path == "/mykos-control/media-status":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                content_length = int(self.headers.get("Content-Length", "0") or 0)
                if content_length:
                    self.rfile.read(min(content_length, 2_000_000))
                self.send_json({"ok": True, "status": media_status()})
                return
            if path == "/mykos-control/management-status":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                content_length = int(self.headers.get("Content-Length", "0") or 0)
                if content_length:
                    self.rfile.read(min(content_length, 2_000_000))
                self.send_json({"ok": True, "status": local_status()})
                return
            if path == "/mykos-control/tools-catalog":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                content_length = int(self.headers.get("Content-Length", "0") or 0)
                if content_length:
                    self.rfile.read(min(content_length, 2_000_000))
                self.send_json({"ok": True, "tools": tool_catalog(), "allowed_roots": allowed_root_catalog()})
                return
            if path == "/mykos-control/memory-catalog":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                payload = self.read_json()
                if payload:
                    self.send_json({"ok": False, "error": "El catálogo de memoria no admite parámetros."}, status=400)
                    return
                self.send_json(memory_catalog())
                return
            if path in {"/mykos-control/library/list", "/mykos-control/library/search", "/mykos-control/library/preview"}:
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                payload = self.read_json()
                root = payload.get("root", "mykos")
                item_path = payload.get("path", "")
                query_text = payload.get("query", "")
                if not isinstance(root, str) or not isinstance(item_path, str) or not isinstance(query_text, str):
                    self.send_json({"ok": False, "error": "Los parámetros de biblioteca deben ser texto."}, status=400)
                    return
                try:
                    if path.endswith("/list"):
                        result = library_list(root, item_path)
                    elif path.endswith("/search"):
                        if not query_text.strip():
                            raise ApiError("Escribe algo que buscar en la biblioteca.")
                        result = library_search(root, item_path, query_text)
                    else:
                        if not item_path.strip():
                            raise ApiError("Falta la ruta del archivo.")
                        result = library_preview(root, item_path)
                except ApiError as error:
                    self.send_json({"ok": False, "error": str(error)}, status=400)
                    return
                self.send_json(result)
                return
            if path == "/mykos-control/models-catalog":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                content_length = int(self.headers.get("Content-Length", "0") or 0)
                if content_length:
                    self.rfile.read(min(content_length, 2_000_000))
                try:
                    self.send_json({"ok": True, "models": get_models()})
                except RuntimeError as error:
                    self.send_json({"ok": False, "error": str(error), "models": []}, status=503)
                return
            if path == "/mykos-control/status-catalog":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                payload = self.read_json()
                if payload:
                    self.send_json({"ok": False, "error": "El catálogo de estado no admite parámetros."}, status=400)
                    return
                try:
                    models = get_models()
                    self.send_json(
                        {
                            "ok": True,
                            "ollama_url": OLLAMA_URL,
                            "models": models,
                            "default_model": DEFAULT_MODEL or choose_default_model(models),
                            "tools": tool_catalog(),
                            "allowed_roots": allowed_root_catalog(),
                            "memory": memory_catalog(),
                            "benchmark_profiles": benchmark_profile_catalog(),
                        }
                    )
                except RuntimeError as error:
                    self.send_json({"ok": False, "error": str(error), "models": []}, status=503)
                return
            if path == "/mykos-control/oauth-status":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                payload = self.read_json()
                if payload:
                    self.send_json({"error": "El estado OAuth no admite parámetros.", "providers": []}, status=400)
                    return
                status = oauth_status()
                providers = status.setdefault("providers", [])
                providers.append({"id": "claude_oauth", "label": "Claude · OAuth", **claude_auth_status()})
                providers.append({"id": "anthropic_api", "label": "Anthropic · API", **anthropic_auth_status()})
                providers.append({"id": "kimi_api", "label": "Kimi · API", **kimi_auth_status()})
                providers.append({"id": "gemini_api", "label": "Gemini · API", **gemini_auth_status()})
                providers.append({"id": "mistral_api", "label": "Mistral · API / Vibe", **mistral_auth_status()})
                providers.append({"id": "antigravity_cli", "label": "Antigravity · CLI", **antigravity_auth_status()})
                providers.append({"id": "qwen_cli", "label": "Qwen Code · CLI", **qwen_auth_status()})
                providers.append({"id": "grok_oauth", "label": "Grok · xAI (OAuth / API)", **grok_auth_status()})
                self.send_json(status)
                return
            if path == "/mykos-control/gemini-live/token":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                payload = self.read_json()
                try:
                    result = create_ephemeral_token(
                        model=str(payload.get("model", "")),
                        voice=str(payload.get("voice", "")),
                    )
                    self.send_json({"ok": True, **result})
                except RuntimeError as error:
                    self.send_json({"ok": False, "error": str(error)}, status=502)
                return
            if path == "/mykos-control/gemini-live/status":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                payload = self.read_json()
                if payload:
                    self.send_json({"ok": False, "error": "El estado de Gemini Live no admite parámetros."}, status=400)
                    return
                status = gemini_auth_status()
                self.send_json({
                    "ok": True,
                    "available": bool(status.get("authenticated")),
                    "error": str(status.get("error") or "")[:300],
                })
                return
            if path in {"/mykos-control/openrouter/refresh", "/mykos-control/meta/refresh", "/mykos-control/grok/refresh", "/mykos-control/oauth/grok/refresh"}:
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                payload = self.read_json()
                if path in {"/mykos-control/grok/refresh", "/mykos-control/oauth/grok/refresh"}:
                    if payload.get("provider", "grok_oauth") not in {"grok", "grok_oauth", "grok_api"}:
                        self.send_json({"ok": False, "error": "Proveedor OAuth no compatible."}, status=400)
                        return
                    try:
                        self.send_json(refresh_grok_models())
                    except RuntimeError as error:
                        self.send_json({"ok": False, "error": str(error), "models": 0}, status=502)
                    return
                if path == "/mykos-control/meta/refresh":
                    if payload.get("provider", "meta_ai_oauth") not in {"meta", "meta_ai", "meta_ai_oauth"}:
                        self.send_json({"ok": False, "error": "Proveedor OAuth no compatible."}, status=400)
                        return
                    try:
                        self.send_json(refresh_meta_ai_models())
                    except RuntimeError as error:
                        self.send_json({"ok": False, "error": str(error), "models": 0}, status=502)
                    return
                if payload.get("provider", "openrouter") != "openrouter":
                    self.send_json({"ok": False, "error": "Proveedor OAuth no compatible."}, status=400)
                    return
                try:
                    self.send_json(refresh_openrouter_models())
                except RuntimeError as error:
                    self.send_json({"ok": False, "error": str(error), "models": 0}, status=502)
                return
            if path in {
                "/mykos-control/providers/nvidia/refresh",
                "/mykos-control/providers/kimi/refresh",
                "/mykos-control/providers/gemini/refresh",
                "/mykos-control/providers/mistral/refresh",
                "/mykos-control/providers/anthropic/refresh",
                "/mykos-control/providers/antigravity/refresh",
                "/mykos-control/providers/qwen/refresh",
                "/mykos-control/providers/grok/refresh",
            }:
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                payload = self.read_json()
                provider = path.split("/")[3]
                accepted = {provider, f"{provider}_api", f"{provider}_cli"}
                if payload.get("provider", provider) not in accepted:
                    self.send_json({"ok": False, "error": "Proveedor no compatible."}, status=400)
                    return
                try:
                    if provider == "nvidia":
                        res = refresh_nvidia_models()
                    elif provider == "gemini":
                        res = refresh_gemini_models()
                    elif provider == "kimi":
                        res = refresh_kimi_models()
                    elif provider == "mistral":
                        res = refresh_mistral_models()
                    elif provider == "anthropic":
                        res = refresh_anthropic_models()
                    elif provider == "grok":
                        res = refresh_grok_models()
                    elif provider == "qwen":
                        res = refresh_qwen_models()
                    else:
                        res = refresh_antigravity_models()
                    self.send_json(res)
                except RuntimeError as error:
                    self.send_json({"ok": False, "error": str(error), "models": 0}, status=502)
                return
            if path in {
                "/mykos-control/oauth/openai/logout",
                "/mykos-control/oauth/claude/logout",
                "/mykos-control/oauth/openrouter/logout",
                "/mykos-control/oauth/meta/logout",
                "/mykos-control/oauth/grok/logout",
                "/mykos-control/providers/nvidia/logout",
                "/mykos-control/providers/kimi/logout",
                "/mykos-control/providers/gemini/logout",
                "/mykos-control/providers/mistral/logout",
                "/mykos-control/providers/anthropic/logout",
                "/mykos-control/providers/antigravity/logout",
                "/mykos-control/providers/qwen/logout",
                "/mykos-control/providers/grok/logout",
            }:
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                payload = self.read_json()
                actions = {
                    "/mykos-control/oauth/openai/logout": ({"openai", "openai_codex", "openai_codex_oauth"}, logout_openai),
                    "/mykos-control/oauth/claude/logout": ({"claude", "anthropic", "anthropic_oauth", "claude_oauth"}, logout_claude),
                    "/mykos-control/oauth/openrouter/logout": ({"openrouter", "openrouter_oauth"}, logout_openrouter),
                    "/mykos-control/oauth/meta/logout": ({"meta", "meta_ai", "meta_ai_oauth"}, logout_meta_ai),
                    "/mykos-control/providers/nvidia/logout": ({"nvidia", "nvidia_api"}, lambda: _logout_nvidia()),
                    "/mykos-control/providers/kimi/logout": ({"kimi", "kimi_api"}, lambda: _logout_kimi()),
                    "/mykos-control/providers/gemini/logout": ({"gemini", "gemini_api"}, lambda: _logout_gemini()),
                    "/mykos-control/providers/mistral/logout": ({"mistral", "mistral_api"}, lambda: _logout_mistral()),
                    "/mykos-control/providers/anthropic/logout": ({"anthropic", "anthropic_api"}, lambda: _logout_anthropic()),
                    "/mykos-control/providers/antigravity/logout": ({"antigravity", "antigravity_cli"}, lambda: _logout_antigravity()),
                    "/mykos-control/providers/qwen/logout": ({"qwen", "qwen_cli"}, lambda: _logout_qwen()),
                    "/mykos-control/oauth/grok/logout": ({"grok", "grok_oauth", "grok_api"}, lambda: _logout_grok()),
                    "/mykos-control/providers/grok/logout": ({"grok", "grok_oauth", "grok_api"}, lambda: _logout_grok()),
                }
                accepted, action = actions[path]
                sent_provider = str(payload.get("provider", "")).strip()
                if sent_provider and sent_provider not in accepted:
                    self.send_json({"ok": False, "error": "Proveedor no compatible."}, status=400)
                    return
                try:
                    self.send_json(action())
                except RuntimeError as error:
                    self.send_json({"ok": False, "error": str(error)}, status=502)
                return
            if path == "/mykos-control/ollama/catalog":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                payload = self.read_json()
                search = payload.get("query", "")
                if not isinstance(search, str):
                    self.send_json({"error": "La búsqueda del catálogo debe ser texto.", "models": []}, status=400)
                    return
                try:
                    self.send_json(fetch_ollama_catalog(search))
                except ApiError as error:
                    self.send_json({"error": str(error), "models": []}, status=400)
                except RuntimeError as error:
                    self.send_json({"error": str(error), "models": []}, status=502)
                return
            if path == "/mykos-control/ollama/jobs":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                payload = self.read_json()
                job_id = payload.get("id", "")
                if not isinstance(job_id, str):
                    self.send_json({"error": "El identificador del trabajo debe ser texto.", "jobs": []}, status=400)
                    return
                with OLLAMA_JOBS_LOCK:
                    job = OLLAMA_JOBS.get(job_id.strip()) if job_id.strip() else None
                    jobs = [_job_public(job)] if job else ([] if job_id.strip() else [_job_public(item) for item in OLLAMA_JOBS.values()])
                self.send_json({"jobs": jobs})
                return
            if path == "/mykos-control/uploads":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                self.handle_uploads()
                return
            if path == "/mykos-control/nodes/heartbeat":
                control_token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(control_token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                token = self.headers.get("X-MyKOS-Node-Token", "").strip()
                result = heartbeat_node(self.read_json(), token)
                self.send_json(result)
                return
            if path in {"/mykos-control/transcribe", "/mykos-control/tts"}:
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                if path.endswith("/transcribe"):
                    self.handle_transcription()
                else:
                    self.handle_tts()
                return
            if path == "/mykos-control/remote-model":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                control_payload = self.read_json()
                model_name = str(control_payload.get("model", "")).strip()
                if not model_name or not isinstance(control_payload.get("messages"), list):
                    self.send_json({"ok": False, "error": "Falta el modelo remoto o el contexto."}, status=400)
                    return
                result = run_model_until_result(
                    model_name,
                    control_payload["messages"],
                    str(control_payload.get("conversation_id", "")),
                    supports_vision=bool(control_payload.get("supports_vision", False)),
                    generation=control_payload.get("generation") if isinstance(control_payload.get("generation"), dict) else None,
                    activity_id=str(control_payload.get("activity_id", "")) or None,
                    permission_mode=str(control_payload.get("permission_mode", "") or "supervisado"),
                    remote_worker=True,
                )
                self.send_json(result)
                return
            if path in {
                "/mykos-control/catalog",
                "/mykos-control/prepare",
                "/mykos-control/activity",
                "/mykos-control/save-message",
            }:
                # Servicios que el bucle de chat del Gateway pide a este trabajador (fase 3, tramo 5): el catálogo de
                # herramientas, la preparación de una acción sensible, el estado de la actividad y guardar un mensaje.
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                control_payload = self.read_json()
                if path.endswith("/catalog"):
                    raw_model = control_payload.get("model")
                    # El Gateway puede enviar el modelo como string (nombre) o como dict completo.
                    if isinstance(raw_model, str) and raw_model:
                        available = get_models()
                        chat = available_chat_models(available)
                        selected_model = next((m for m in chat if m.get("name") == raw_model), None) or {"name": raw_model}
                    elif isinstance(raw_model, dict) and raw_model:
                        selected_model = raw_model
                    else:
                        selected_model = {}
                    default_model = DEFAULT_MODEL or choose_default_model(get_models()) or ""
                    self.send_json({
                        "ok": True,
                        "schemas": TOOL_SCHEMAS,
                        "sensitive": sorted(SENSITIVE_TOOL_NAMES),
                        "system_prompt": system_prompt_for_model(selected_model) if selected_model else load_base_system_prompt(),
                        "default_model": default_model,
                    })
                    return
                if path.endswith("/prepare"):
                    tool_name = str(control_payload.get("tool_name", "")).strip()
                    if not tool_name:
                        self.send_json({"ok": False, "error": "Falta el nombre de la herramienta."}, status=400)
                        return
                    arguments = control_payload.get("arguments")
                    self.send_json(prepare_approval_action(tool_name, arguments if isinstance(arguments, dict) else {}))
                    return
                if path.endswith("/activity"):
                    update_activity(
                        str(control_payload.get("activity_id", "")).strip() or None,
                        status=str(control_payload["status"]) if "status" in control_payload else None,
                        phase=str(control_payload["phase"]) if "phase" in control_payload else None,
                        label=str(control_payload["label"]) if "label" in control_payload else None,
                        detail=str(control_payload["detail"]) if "detail" in control_payload else None,
                    )
                    self.send_json({"ok": True})
                    return
                conversation_id = str(control_payload.get("conversation_id", "")).strip()
                message = control_payload.get("message")
                if not conversation_id or not isinstance(message, dict) or message.get("role") != "assistant":
                    self.send_json({"ok": False, "error": "Falta la conversación o el mensaje del asistente."}, status=400)
                    return
                save_assistant_message(conversation_id, message)
                self.send_json({"ok": True, "message": message})
                return
            if path in {"/mykos-control/tool", "/mykos-control/action"}:
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                control_payload = self.read_json()
                if path.endswith("/tool"):
                    tool_name = str(control_payload.get("tool_name", "")).strip()
                    if not tool_name:
                        self.send_json({"ok": False, "error": "Falta el nombre de la herramienta."}, status=400)
                        return
                    self.send_json(execute_tool(tool_name, control_payload.get("arguments")))
                else:
                    action = control_payload.get("action")
                    if not isinstance(action, dict):
                        self.send_json({"ok": False, "error": "Falta la acción aprobada."}, status=400)
                        return
                    route_signature = self.headers.get("X-MyKOS-Gateway-Action", "").strip()
                    grant_ok = _verify_gateway_execution_grant(
                        action,
                        str(control_payload.get("conversation_id", "")),
                        control_payload.get("authorization") if isinstance(control_payload.get("authorization"), dict) else None,
                    )
                    route_ok = bool(route_signature) and hmac.compare_digest(
                        route_signature,
                        _gateway_action_route_signature(getattr(self, "_last_request_body", b"")),
                    )
                    if not grant_ok and not route_ok:
                        self.send_json({"ok": False, "error": "La ejecución no procede de una autorización del Gateway."}, status=403)
                        return
                    self.send_json(execute_approved_action(action))
                return
            payload = self.read_json()
            if path == "/mykos-control/approvals/resolve":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                approval_id = str(payload.get("approval_id", "")).strip()
                decision = str(payload.get("decision", "")).strip()
                if not approval_id or decision not in {"approve", "reject"}:
                    self.send_json({"error": "Falta una aprobación o la decisión no es válida."}, status=400)
                    return
                self.handle_approval_decision(approval_id, decision, payload)
                return
            if path in {"/mykos-control/ollama/pull-request", "/mykos-control/ollama/delete-request"}:
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                self.handle_ollama_panel_request(path, payload)
                return
            if path in {"/mykos-control/automations/create-request", "/mykos-control/automations/delete-request"}:
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                self.handle_automation_panel_request(path, payload)
                return
            if path == "/mykos-control/benchmark":
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                self.handle_benchmark(payload)
                return
            if path in {
                "/mykos-control/oauth/openai/start",
                "/mykos-control/oauth/claude/start",
                "/mykos-control/oauth/openrouter/start",
                "/mykos-control/oauth/meta/start",
                "/mykos-control/oauth/grok/start",
            }:
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                actions = {
                    "/mykos-control/oauth/openai/start": ({"openai", "openai_codex", "openai_codex_oauth"}, start_openai_login),
                    "/mykos-control/oauth/claude/start": ({"claude", "anthropic", "anthropic_oauth", "claude_oauth"}, start_claude_login),
                    "/mykos-control/oauth/openrouter/start": ({"openrouter", "openrouter_oauth"}, start_openrouter_login),
                    "/mykos-control/oauth/meta/start": ({"meta", "meta_ai", "meta_ai_oauth"}, start_meta_ai_login),
                    "/mykos-control/oauth/grok/start": ({"grok", "grok_oauth"}, start_grok_login),
                }
                accepted, action = actions[path]
                sent_provider = str(payload.get("provider", "")).strip()
                if sent_provider and sent_provider not in accepted:
                    self.send_json({"ok": False, "error": "Proveedor OAuth no compatible."}, status=400)
                    return
                try:
                    self.send_json(action())
                except RuntimeError as error:
                    self.send_json({"ok": False, "error": str(error)}, status=502)
                return
            if path in {
                "/mykos-control/providers/nvidia/connect",
                "/mykos-control/providers/kimi/connect",
                "/mykos-control/providers/gemini/connect",
                "/mykos-control/providers/mistral/connect",
                "/mykos-control/providers/anthropic/connect",
                "/mykos-control/providers/antigravity/connect",
                "/mykos-control/providers/qwen/connect",
                "/mykos-control/providers/grok/connect",
            }:
                token = self.headers.get("X-MyKOS-Control-Token", "").strip()
                if not (MYKOS_CONTROL_TOKEN and hmac.compare_digest(token.encode("utf-8"), MYKOS_CONTROL_TOKEN.encode("utf-8"))):
                    self.send_json({"ok": False, "error": "Plano de control no autorizado."}, status=403)
                    return
                provider = path.split("/")[3]
                accepted = {provider, f"{provider}_api", f"{provider}_cli", f"{provider}_oauth"}
                if payload.get("provider", provider) not in accepted:
                    self.send_json({"ok": False, "error": "Proveedor no compatible."}, status=400)
                    return
                if provider == "antigravity":
                    res = enable_antigravity()
                    self.send_json(res)
                    return
                if provider == "qwen":
                    res = enable_qwen()
                    self.send_json(res)
                    return
                if provider == "mistral" and payload.get("link_vibe"):
                    link_vibe_keyring()
                    with MISTRAL_LOCK:
                        MISTRAL_MODEL_CACHE.clear()
                        MISTRAL_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
                    rows = mistral_models()
                    self.send_json({"ok": True, "provider": "mistral_api", "authenticated": True, "models": len(rows)})
                    return
                api_key = str(payload.get("api_key", "")).strip()
                if not api_key:
                    provider_names = {
                        "nvidia": "NVIDIA",
                        "gemini": "Google AI Studio (Gemini)",
                        "kimi": "Kimi",
                        "mistral": "Mistral",
                        "anthropic": "Anthropic",
                        "grok": "xAI (Grok)",
                    }
                    raise ApiError(f"Introduce una clave personal de {provider_names.get(provider, provider)}.")
                if provider == "nvidia":
                    rows = validate_nvidia_api_key(api_key)
                    save_nvidia_api_key(api_key)
                    with NVIDIA_LOCK:
                        NVIDIA_MODEL_CACHE.clear()
                        NVIDIA_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
                    self.send_json({"ok": True, "provider": "nvidia_api", "authenticated": True, "models": len(rows)})
                elif provider == "gemini":
                    rows = gemini_models(api_key)
                    save_gemini_api_key(api_key)
                    with GEMINI_LOCK:
                        GEMINI_MODEL_CACHE.clear()
                        GEMINI_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
                    self.send_json({"ok": True, "provider": "gemini_api", "authenticated": True, "models": len(rows)})
                elif provider == "kimi":
                    rows = kimi_models(api_key)
                    save_kimi_api_key(api_key)
                    with KIMI_LOCK:
                        KIMI_MODEL_CACHE.clear()
                        KIMI_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
                    self.send_json({"ok": True, "provider": "kimi_api", "authenticated": True, "models": len(rows)})
                elif provider == "mistral":
                    rows = mistral_models(key=api_key)
                    save_mistral_api_key(api_key)
                    with MISTRAL_LOCK:
                        MISTRAL_MODEL_CACHE.clear()
                        MISTRAL_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
                    self.send_json({"ok": True, "provider": "mistral_api", "authenticated": True, "models": len(rows)})
                elif provider == "anthropic":
                    validate_anthropic_api_key(api_key)
                    save_anthropic_api_key(api_key)
                    with ANTHROPIC_LOCK:
                        ANTHROPIC_MODEL_CACHE.clear()
                        ANTHROPIC_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
                    self.send_json({"ok": True, "provider": "anthropic_api", "authenticated": True, "models": len(ANTHROPIC_MODELS)})
                elif provider == "grok":
                    save_grok_api_key(api_key)
                    with GROK_LOCK:
                        GROK_MODEL_CACHE.clear()
                        GROK_MODEL_CACHE.update(checked_at=0.0, models=[], authenticated=False, error="")
                    rows = grok_models(key=api_key)
                    self.send_json({"ok": True, "provider": "grok_api", "authenticated": True, "models": len(rows)})
                return
            self.send_json({"error": "Ruta no encontrada."}, status=404)
        except ApiError as error:
            self.send_json({"error": str(error)}, status=400)
        except NodeError as error:
            self.send_json({"error": str(error)}, status=400)
        except ControlPlaneHTTPError as error:
            if error.status in CONTROL_PLANE_CLIENT_STATUSES and error.client_message:
                self.send_json({"error": error.client_message}, status=error.status)
            else:
                self.send_json({"error": str(error)}, status=502)
        except RuntimeError as error:
            self.send_json({"error": str(error)}, status=502)
        except Exception as error:  # keep the API response useful without leaking a traceback
            print(f"Error interno: {error}")
            self.send_json({"error": "Error interno del servidor."}, status=500)

    def do_DELETE(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = self.path.partition("?")[0]
        if not self.worker_authorized(path):
            return
        self.send_json({"error": "Ruta no encontrada."}, status=404)

    def handle_uploads(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError) as error:
            raise ApiError("La carga no tiene un tamaño válido.") from error
        if content_length <= 0 or content_length > MAX_UPLOAD_REQUEST_BYTES:
            raise ApiError("La carga supera el límite de 32 MB o está vacía.")
        body = self.rfile.read(content_length)
        attachments = register_uploads(content_type, body)
        self.send_json({"attachments": attachments})

    def handle_transcription(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError) as error:
            raise ApiError("La carga de audio no tiene un tamaño válido.") from error
        if content_length <= 0 or content_length > MAX_TRANSCRIPTION_REQUEST_BYTES:
            raise ApiError("El audio supera el límite de 25 MB o está vacío.")
        body = self.rfile.read(content_length)
        try:
            raw_message = (
                b"Content-Type: " + content_type.encode("latin-1", errors="replace")
                + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
            )
            message = BytesParser(policy=email_default_policy).parsebytes(raw_message)
        except Exception as error:
            raise ApiError(f"No se pudo leer la carga de audio: {error}") from error
        if not message.is_multipart():
            raise ApiError("La carga de audio no tiene un formulario multipart válido.")
        parts = [part for part in message.iter_parts() if part.get_filename()]
        if len(parts) != 1:
            raise ApiError("Envía exactamente un audio desde el micrófono.")
        original_name = Path(str(parts[0].get_filename())).name
        suffix = Path(original_name).suffix.casefold()
        if suffix not in ALLOWED_AUDIO_EXTENSIONS:
            raise ApiError("El formato de audio del micrófono no es compatible.")
        data = parts[0].get_payload(decode=True) or b""
        if not data or len(data) > 25 * 1024 * 1024:
            raise ApiError("El audio está vacío o supera el límite de 25 MB.")
        media_inbox = DATA_DIR / "media" / "incoming"
        media_inbox.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="microphone-", suffix=suffix, dir=media_inbox, delete=False) as handle:
                handle.write(data)
                temporary_path = Path(handle.name)
            result = transcribe_audio_file(temporary_path)
            print(f"[transcribe] audio={len(data)} bytes ({suffix}) -> texto={len(str(result.get('text', '')))} car.: {str(result.get('text', ''))[:80]!r}", flush=True)
            self.send_json(result)
        except MediaError as error:
            raise ApiError(str(error)) from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def handle_tts(self) -> None:
        payload = self.read_json()
        text = payload.get("text")
        voice = str(payload.get("voice", "em_alex")).strip() or "em_alex"
        if not isinstance(text, str) or not text.strip():
            self.send_json({"ok": False, "error": "text debe contener texto no vacío."}, status=400)
            return
        try:
            import time
            t0 = time.time()
            result = kokoro_audio(text, voice)
            elapsed = time.time() - t0
            print(f"[tts] {len(text)} car. -> {elapsed:.2f}s ({result.get('engine', 'desconocido')})", flush=True)
            self.send_json(result)
        except MediaError as error:
            self.send_json({"ok": False, "error": str(error)}, status=502)

    def handle_ollama_panel_request(self, path: str, payload: dict[str, Any]) -> None:
        tool_name = "pull_ollama_model" if path.endswith("pull-request") else "delete_ollama_model"
        model = str(payload.get("model", "")).strip()
        conversation_id = str(payload.get("conversation_id", "")).strip()
        result = create_panel_approval(tool_name, {"model": model}, conversation_id)
        if not result.get("ok"):
            self.send_json({"error": result.get("error", "No se pudo preparar la acción.")}, status=400)
            return
        self.send_json(result)

    def handle_automation_panel_request(self, path: str, payload: dict[str, Any]) -> None:
        conversation_id = str(payload.get("conversation_id", "")).strip()
        if path.endswith("create-request"):
            arguments = {
                "title": payload.get("title", ""),
                "message": payload.get("message", ""),
                "run_at": payload.get("run_at", ""),
                "repeat_minutes": payload.get("repeat_minutes", 0),
            }
            result = create_panel_approval("create_reminder", arguments, conversation_id)
        else:
            arguments = {"id": str(payload.get("id", "")).strip()}
            result = create_panel_approval("delete_reminder", arguments, conversation_id)
        if not result.get("ok"):
            self.send_json({"error": result.get("error", "No se pudo preparar la acción.")}, status=400)
            return
        self.send_json(result)

    def handle_benchmark(self, payload: dict[str, Any]) -> None:
        self.send_json(run_benchmark(payload))

    def handle_approval_decision(
        self,
        approval_id: str,
        decision: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        payload = payload if isinstance(payload, dict) else {}
        activity_id = str(payload.get("activity_id", "")).strip() or uuid.uuid4().hex
        permission_mode = str(payload.get("permission_mode", "once") or "once").strip().casefold()
        if permission_mode not in {"once", "session", "permanent"}:
            permission_mode = "once"
        conversation_permission_mode = str(payload.get("conversation_permission_mode", "") or "").strip().casefold()
        if conversation_permission_mode not in {"solo_lectura", "supervisado", "acceso_total"}:
            conversation_permission_mode = ""
        try:
            self._handle_gateway_approval_decision(
                approval_id,
                decision,
                activity_id,
                permission_mode,
                conversation_permission_mode or "supervisado",
            )
        finally:
            finish_activity(activity_id)

    def _handle_gateway_approval_decision(
        self,
        approval_id: str,
        decision: str,
        activity_id: str,
        permission_mode: str,
        conversation_permission_mode: str = "supervisado",
    ) -> None:
        """El Gateway decide, registra y ejecuta; Python solo continúa el turno."""
        result = controller_resolve_approval(
            approval_id,
            decision,
            permission_mode,
            conversation_permission_mode=conversation_permission_mode,
        )
        if not result.get("ok"):
            self.send_json(
                {"error": str(result.get("error", "No se pudo resolver la aprobación."))},
                status=int(result.get("status", 502) or 502),
            )
            return
        if result.get("rejected"):
            self.send_json(
                {
                    "ok": True,
                    "approved": False,
                    "rejected": True,
                    "conversation_id": result.get("conversation_id", ""),
                    "action": result.get("action", {}),
                }
            )
            return

        record = result.get("_record") if isinstance(result.get("_record"), dict) else {}
        action = record.get("action") if isinstance(record.get("action"), dict) else {}
        public_result = {key: value for key, value in result.items() if key != "_record"}
        if action.get("panel_request"):
            self.send_json(public_result)
            return

        action_result = result.get("action_result") if isinstance(result.get("action_result"), dict) else {}
        messages = record.get("messages")
        model = str(record.get("model", "")).strip()
        conversation_id = str(record.get("conversation_id", "")).strip()
        start_activity(activity_id, conversation_id, model)
        effective_conv_mode = str(record.get("conversation_permission_mode", "") or conversation_permission_mode or "supervisado").strip().casefold()
        if effective_conv_mode not in {"solo_lectura", "supervisado", "acceso_total"}:
            effective_conv_mode = "supervisado"

        if not isinstance(messages, list) or not messages or "live" in model.casefold():
            summary_text = (
                f"Acción «{record.get('tool_name') or action.get('kind') or 'aprobada'}» ejecutada correctamente."
                if action_result.get("ok")
                else f"No se pudo completar la acción: {action_result.get('error', 'error desconocido')}."
            )
            assistant_message = {
                "role": "assistant",
                "model": model,
                "content": summary_text,
                "created_at": utc_now(),
            }
            if conversation_id:
                save_assistant_message(conversation_id, assistant_message)
            public_result.update({
                "conversation_id": conversation_id,
                "model": model,
                "done": True,
                "tools_used": [str(record.get("tool_name") or action.get("kind") or "")],
                "message": assistant_message,
            })
            self.send_json(public_result)
            return

        continuation_error = ""
        try:
            update_activity(
                activity_id,
                status="working",
                phase="model",
                label="Continuando después de la aprobación…",
                detail="El Gateway ha ejecutado la acción y MyKOS está preparando la respuesta.",
            )
            messages.append(tool_message_for_result(action_result, bool(record.get("supports_vision", False))))
            if not model or not conversation_id:
                raise RuntimeError("La aprobación no contiene modelo o conversación válidos.")
            continuation = run_model_until_result(
                model,
                messages,
                conversation_id,
                supports_vision=bool(record.get("supports_vision", False)),
                generation=record.get("generation") if isinstance(record.get("generation"), dict) else None,
                activity_id=activity_id,
                permission_mode=effective_conv_mode,
            )
        except Exception as error:
            continuation_error = str(error).strip() or "El modelo no pudo continuar después de la aprobación."

        if continuation_error:
            public_result.update({
                "conversation_id": record.get("conversation_id", ""),
                "model": record.get("model", ""),
                "error": continuation_error,
                "continuation_failed": True,
            })
            self.send_json(public_result, status=502)
            return

        public_result.update({
            "conversation_id": record.get("conversation_id", ""),
            "model": record.get("model", ""),
            "done": bool(continuation.get("done", True)),
            "tools_used": continuation.get("tools_used", []),
        })
        if continuation.get("pending_action"):
            public_result["needs_approval"] = True
            public_result["pending_action"] = continuation["pending_action"]
            public_result["message"] = {
                "role": "assistant",
                "model": model,
                "content": str(continuation.get("proposal", "")).strip()
                or "La siguiente acción también necesita tu aprobación.",
            }
            if continuation.get("sources"):
                public_result["message"]["sources"] = continuation["sources"]
        else:
            public_result["message"] = continuation["message"]
        self.send_json(public_result)

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ApiError("Content-Length no válido.") from error
        if length <= 0 or length > 2_000_000:
            raise ApiError("Cuerpo de petición no válido.")
        try:
            raw_body = self.rfile.read(length)
            self._last_request_body = raw_body
            expected_hash = str(getattr(self, "_expected_body_hash", "") or "")
            if expected_hash and expected_hash != "-" and hashlib.sha256(raw_body).hexdigest() != expected_hash:
                raise ApiError("El cuerpo no coincide con la decisión firmada por el Gateway.")
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiError("El cuerpo no contiene JSON válido.") from error
        if not isinstance(payload, dict):
            raise ApiError("El cuerpo debe ser un objeto JSON.")
        return payload

    @staticmethod
    def parse_query(query: str) -> dict[str, list[str]]:
        from urllib.parse import parse_qs

        return parse_qs(query, keep_blank_values=True)

    def serve_static(self, relative_path: str, content_type: str | None = None) -> None:
        if BACKEND_ONLY:
            self.send_json(
                {"error": f"Este es el servidor interno de MyKOS. La interfaz está en http://127.0.0.1:{PUBLIC_PORT}/"},
                status=404,
            )
            return
        target = (STATIC_DIR / relative_path).resolve()
        if STATIC_DIR.resolve() not in target.parents:
            self.send_json({"error": "Recurso no válido."}, status=400)
            return
        if not target.is_file():
            self.send_json({"error": "Recurso no encontrado."}, status=404)
            return
        mime = content_type or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_bytes(target.read_bytes(), mime)


def _watch_parent(server: ThreadingHTTPServer, parent_pid: int) -> None:
    """Apaga el servidor cuando el proceso padre (el Gateway) deja de existir, aunque muera sin avisar."""
    try:
        import psutil
    except ImportError:
        print("Aviso: psutil no está instalado; no se vigilará el proceso padre.")
        return

    def watch() -> None:
        try:
            parent: Any = psutil.Process(parent_pid)
        except psutil.Error:
            parent = None
        while parent is not None:
            try:
                if not parent.is_running():
                    break
            except psutil.Error:
                pass  # sin permiso para consultarlo: se da por vivo
            time.sleep(2)
        time.sleep(0.5)  # margen para que serve_forever() ya esté en marcha antes de pedir el cierre
        print(f"El proceso padre ({parent_pid}) ya no existe; cerrando el backend de MyKOS.")
        server.shutdown()

    threading.Thread(target=watch, name="parent-watchdog", daemon=True).start()


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_uploads()
    if not gateway_store.ENABLED:
        start_scheduler()
    server = ThreadingHTTPServer((HOST, PORT), MyKOSHandler)
    print(f"MyKOS escuchando en http://{HOST}:{PORT}")
    print(f"Ollama: {OLLAMA_URL}")
    if PARENT_PID:
        _watch_parent(server, PARENT_PID)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMyKOS detenido.")
    finally:
        server.server_close()
        if not gateway_store.ENABLED:
            stop_scheduler()
        if BACKEND_ONLY:
            # Lo gestiona el Gateway: al cerrarse no deja el motor llama.cpp cargado en la GPU.
            stop_llama_cpp_server()


if __name__ == "__main__":
    main()





