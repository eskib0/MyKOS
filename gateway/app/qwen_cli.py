"""Adaptador para el CLI oficial de Qwen Code (qwen).

Usa la sesión y configuración propia del CLI de Qwen Code de forma aislada.
Garantiza un perfil seguro sin herramientas autónomas ni búsqueda web no configurada.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MAX_PROMPT_CHARS = 120000

SAFE_HOME = Path(
    os.environ.get(
        "MYKOS_QWEN_HOME",
        str(Path(__file__).resolve().parent.parent / "runtime" / "qwen-home"),
    )
).expanduser()
SAFE_SETTINGS = SAFE_HOME / ".qwen" / "settings.json"
DENIED_TOOLS: set[str] = set()

CONFIG_DIR = Path(
    os.environ.get(
        "MYKOS_CREDENTIALS_DIR",
        str(Path(__file__).resolve().parent / "data" / "oauth"),
    )
).expanduser() / "qwen"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_QWEN_MODELS: list[tuple[str, str, str]] = [
    ("qwen-code-default", "Qwen Code · CLI (Predeterminado)", "Qwen"),
]

CLOUD_QWEN_MODELS: list[tuple[str, str, str]] = [
    ("qwen-turbo", "Qwen Turbo · Nube (DashScope)", "Qwen"),
    ("qwen-plus", "Qwen Plus · Nube (DashScope)", "Qwen"),
    ("qwen-max", "Qwen Max · Nube (DashScope)", "Qwen"),
    ("qwen3-coder-plus", "Qwen 3 Coder Plus · Nube (DashScope)", "Qwen Coder"),
]

QWEN_LOCK = threading.Lock()
QWEN_CACHE: dict[str, Any] = {"checked_at": 0.0, "models": []}
CACHE_TTL_SECONDS = 300.0


def qwen_executable_path() -> str:
    configured = os.environ.get("MYKOS_QWEN_PATH", "").strip()
    candidates = [configured] if configured else []
    candidates.extend(
        [
            shutil.which("qwen") or "",
            str(Path.home() / ".local" / "bin" / "qwen"),
            str(Path.home() / ".local" / "lib" / "qwen-code" / "bin" / "qwen"),
            "/usr/local/bin/qwen",
            "/usr/bin/qwen",
        ]
    )
    for candidate in candidates:
        if candidate and (shutil.which(candidate) or Path(candidate).is_file()):
            return str(Path(candidate))
    return ""


_QWEN_CREDENTIAL_FILES = ("subscription_credentials.json", "oauth_creds.json")
_CLOUD_MODEL_IDS = {
    "qwen-turbo",
    "qwen-plus",
    "qwen-max",
    "qwen3-coder-plus",
    "qwen3-coder-flash",
    "qwen3.8-max",
    "qwen3.8-flash",
}
_LOCAL_ENV_OVERRIDE_KEYS = ("OPENAI_BASE_URL", "OLLAMA_HOST", "OLLAMA_API_KEY")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def _scrub_local_endpoints(safe_data: dict[str, Any], *, has_cloud_creds: bool) -> None:
    """Elimina configuraciones locales heredadas (ej. 127.0.0.1:11434) del perfil aislado."""
    model_cfg = safe_data.get("model")
    if isinstance(model_cfg, dict):
        model_base = str(model_cfg.get("baseUrl") or "").strip()
        if model_base and _is_local_endpoint(model_base):
            model_cfg.pop("baseUrl", None)
        active_name = str(model_cfg.get("name") or "").strip()
        if has_cloud_creds and active_name and _is_known_ollama_model(active_name):
            model_cfg.pop("name", None)
        if not model_cfg:
            safe_data.pop("model", None)

    sec_cfg = safe_data.get("security")
    if isinstance(sec_cfg, dict):
        auth_cfg = sec_cfg.get("auth")
        if isinstance(auth_cfg, dict):
            auth_base = str(auth_cfg.get("baseUrl") or "").strip()
            if auth_base and _is_local_endpoint(auth_base):
                auth_cfg.pop("baseUrl", None)
                if auth_cfg.get("selectedType") == "openai":
                    auth_cfg.pop("selectedType", None)

    providers_cfg = safe_data.get("modelProviders")
    if isinstance(providers_cfg, dict):
        cleaned_providers: dict[str, Any] = {}
        for prov_key, entries in providers_cfg.items():
            if prov_key == "ollama":
                continue
            if isinstance(entries, list):
                kept = [
                    entry
                    for entry in entries
                    if not (isinstance(entry, dict) and _is_local_endpoint(str(entry.get("baseUrl") or "").strip()))
                ]
                if kept:
                    cleaned_providers[prov_key] = kept
            else:
                cleaned_providers[prov_key] = entries
        if cleaned_providers:
            safe_data["modelProviders"] = cleaned_providers
        else:
            safe_data.pop("modelProviders", None)

    env_cfg = safe_data.get("env")
    if isinstance(env_cfg, dict):
        base_env = str(env_cfg.get("OPENAI_BASE_URL") or "").strip()
        ollama_host = str(env_cfg.get("OLLAMA_HOST") or "").strip()
        if not base_env or _is_local_endpoint(base_env):
            env_cfg.pop("OPENAI_BASE_URL", None)
        if not ollama_host or _is_local_endpoint(ollama_host):
            env_cfg.pop("OLLAMA_HOST", None)
            env_cfg.pop("OLLAMA_API_KEY", None)
        if not env_cfg:
            safe_data.pop("env", None)


_QWEN_CORTEX_CORE_FILES = (
    ("workspace/USER.md", "## Perfil del Usuario (USER.md)"),
    ("00 - Centro de Mando/00 - Preferencias y Memoria.md", "## Preferencias y Memoria (Cortex)"),
    ("00 - Centro de Mando/00 - Dashboard MyKOS.md", "## Dashboard MyKOS (Cortex)"),
)
_QWEN_CORTEX_SKIP_DIRS = {".cortex", ".git", ".trash", "node_modules", "workspace"}
_QWEN_MEMORY_MAX_CHARS = 8000
_QWEN_INDEX_MAX_NOTES = 80


def _cortex_vault_dir() -> Path:
    """Resuelve la ruta de la bóveda Cortex activa de forma multiplataforma."""
    env_vault = (
        os.environ.get("MYKOS_CORTEX_VAULT")
        or os.environ.get("MYKOS_BRAIN_VAULT")
        or ""
    ).strip()
    if env_vault:
        return Path(env_vault).expanduser().resolve()
    try:
        from cortex import get_cortex

        engine = get_cortex()
        root = getattr(engine, "root", None)
        if root:
            return Path(root)
    except Exception:
        pass
    return (Path.home() / ".mykos" / "cortex")


def _collect_cortex_markdown_paths(cortex_dir: Path) -> list[str]:
    if not cortex_dir.is_dir():
        return []
    notes: list[str] = []
    for dp, dn, fn in os.walk(cortex_dir, followlinks=False):
        dp_path = Path(dp)
        dn[:] = sorted(
            d
            for d in dn
            if d not in _QWEN_CORTEX_SKIP_DIRS and not d.startswith(".") and not (dp_path / d).is_symlink()
        )
        for fname in sorted(fn):
            if fname.startswith(".") or not fname.lower().endswith(".md"):
                continue
            full = dp_path / fname
            if full.is_symlink():
                continue
            try:
                notes.append(full.relative_to(cortex_dir).as_posix())
            except ValueError:
                pass
    return sorted(notes)


def _sync_qwen_memory_md(cortex_dir: Path | None = None) -> Path:
    """Sincroniza `SAFE_HOME/.qwen/QWEN.md` con la memoria persistente real en MyKOS Cortex."""
    vault = (cortex_dir or _cortex_vault_dir()).expanduser()
    workspace_dir = vault / "workspace"
    qwen_md = SAFE_SETTINGS.parent / "QWEN.md"
    qwen_md.parent.mkdir(parents=True, exist_ok=True)

    sections: list[str] = [
        "# Memoria Persistente de MyKOS (Cortex)",
        (
            "Tu memoria persistente real en MyKOS **NO** es `~/.qwen/memories/MEMORY.md`, sino **MyKOS Cortex**.\n"
            f"- **Bóveda Cortex:** `{vault}`\n"
            f"- **Workspace vivo:** `{workspace_dir}`\n"
            "- Puedes leer, buscar o actualizar las notas Markdown de Cortex directamente con tus herramientas sobre esa ruta."
        ),
    ]

    loaded_rel_paths: set[str] = set()
    for rel_path, heading in _QWEN_CORTEX_CORE_FILES:
        note_path = vault / Path(*rel_path.split("/"))
        content = ""
        try:
            content = note_path.read_text(encoding="utf-8").strip()
        except OSError:
            if rel_path == "workspace/USER.md":
                fallback_user = Path.home() / ".mykos" / "workspace" / "USER.md"
                try:
                    content = fallback_user.read_text(encoding="utf-8").strip()
                except OSError:
                    content = ""
        if content:
            loaded_rel_paths.add(rel_path)
            if len(content) > _QWEN_MEMORY_MAX_CHARS:
                content = (
                    content[:_QWEN_MEMORY_MAX_CHARS].rstrip()
                    + "\n\n[... contenido truncado; lee el archivo completo en Cortex]"
                )
            sections.append(f"{heading} (`{rel_path}`)\n\n{content}")

    all_notes = _collect_cortex_markdown_paths(vault)
    other_notes = [p for p in all_notes if p not in loaded_rel_paths]
    if other_notes:
        shown = other_notes[:_QWEN_INDEX_MAX_NOTES]
        index_lines = ["## Otras notas disponibles en Cortex", ""]
        index_lines.extend(f"- `{rel}`" for rel in shown)
        if len(other_notes) > _QWEN_INDEX_MAX_NOTES:
            index_lines.append(f"- ... (+{len(other_notes) - _QWEN_INDEX_MAX_NOTES} notas más en Cortex)")
        sections.append("\n".join(index_lines))

    rendered = "\n\n---\n\n".join(sections) + "\n"
    try:
        if qwen_md.is_file() and qwen_md.read_text(encoding="utf-8") == rendered:
            return qwen_md
    except OSError:
        pass

    tmp_md = qwen_md.with_suffix(".md.tmp")
    tmp_md.write_text(rendered, encoding="utf-8")
    try:
        os.chmod(tmp_md, 0o600)
    except OSError:
        pass
    tmp_md.replace(qwen_md)
    return qwen_md


def setup_safe_environment() -> None:
    """Crea o sincroniza el perfil seguro de Qwen desactivando herramientas peligrosas y sincronizando credenciales."""
    SAFE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    user_qwen_dir = Path.home() / ".qwen"
    user_settings_file = user_qwen_dir / "settings.json"

    for fname in _QWEN_CREDENTIAL_FILES:
        src = user_qwen_dir / fname
        dst = SAFE_SETTINGS.parent / fname
        if src.is_file():
            try:
                dst.write_bytes(src.read_bytes())
                os.chmod(dst, 0o600)
            except OSError:
                pass

    safe_sub_file = SAFE_SETTINGS.parent / "subscription_credentials.json"
    safe_oauth_file = SAFE_SETTINGS.parent / "oauth_creds.json"
    has_cloud_creds = safe_sub_file.is_file() or safe_oauth_file.is_file()

    safe_data: dict[str, Any] = {
        "$version": 4,
        "permissions": {
            "allow": ["*"],
        },
        "tools": {
            "codeModeOnly": True,
            "shell": {"enableInteractiveShell": True},
        },
    }
    if user_settings_file.is_file():
        try:
            user_data = json.loads(user_settings_file.read_text(encoding="utf-8"))
            if isinstance(user_data, dict):
                for key in ("model", "modelProviders", "security", "env", "fastModel"):
                    if key in user_data:
                        safe_data[key] = user_data[key]
        except (OSError, ValueError, TypeError):
            pass

    _scrub_local_endpoints(safe_data, has_cloud_creds=has_cloud_creds)

    if safe_sub_file.is_file():
        sec = safe_data.setdefault("security", {})
        if isinstance(sec, dict):
            auth = sec.setdefault("auth", {})
            if isinstance(auth, dict):
                auth["selectedType"] = "qwen-subscription"
    elif safe_oauth_file.is_file():
        sec = safe_data.setdefault("security", {})
        if isinstance(sec, dict):
            auth = sec.setdefault("auth", {})
            if isinstance(auth, dict) and not auth.get("selectedType"):
                auth["selectedType"] = "qwen-oauth"

    temp_file = SAFE_SETTINGS.with_suffix(".tmp")
    temp_file.write_text(json.dumps(safe_data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temp_file, 0o600)
    except OSError:
        pass
    temp_file.replace(SAFE_SETTINGS)
    _sync_qwen_memory_md()


def ensure_chat_safe() -> None:
    """Sincroniza el perfil de Qwen, credenciales y QWEN.md asegurando disponibilidad y sin contaminación local."""
    user_qwen_dir = Path.home() / ".qwen"
    user_settings_file = user_qwen_dir / "settings.json"

    need_sync = not SAFE_SETTINGS.is_file()
    if not need_sync and user_settings_file.is_file():
        try:
            if user_settings_file.stat().st_mtime > SAFE_SETTINGS.stat().st_mtime:
                need_sync = True
        except OSError:
            pass
    if not need_sync:
        for fname in _QWEN_CREDENTIAL_FILES:
            src = user_qwen_dir / fname
            dst = SAFE_SETTINGS.parent / fname
            if src.is_file():
                if not dst.is_file():
                    need_sync = True
                    break
                try:
                    if src.stat().st_mtime > dst.stat().st_mtime:
                        need_sync = True
                        break
                except OSError:
                    pass
    if not need_sync and SAFE_SETTINGS.is_file():
        try:
            raw_safe = SAFE_SETTINGS.read_text(encoding="utf-8")
            if "11434" in raw_safe:
                need_sync = True
        except OSError:
            pass

    cortex_dir = _cortex_vault_dir()
    qwen_md = SAFE_SETTINGS.parent / "QWEN.md"
    need_memory_sync = not qwen_md.is_file()
    if not need_memory_sync:
        try:
            qwen_md_mtime = qwen_md.stat().st_mtime
            for rel_path, _heading in _QWEN_CORTEX_CORE_FILES:
                src_note = cortex_dir / Path(*rel_path.split("/"))
                if src_note.is_file() and src_note.stat().st_mtime > qwen_md_mtime:
                    need_memory_sync = True
                    break
        except OSError:
            need_memory_sync = True

    if need_sync:
        setup_safe_environment()
    elif need_memory_sync:
        _sync_qwen_memory_md(cortex_dir)


def is_qwen_enabled() -> bool:
    try:
        if CONFIG_FILE.is_file():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return bool(data.get("enabled", False))
    except (OSError, ValueError, TypeError):
        pass
    return False


def enable_qwen() -> dict[str, Any]:
    executable = qwen_executable_path()
    if not executable:
        raise RuntimeError("No se encuentra el ejecutable qwen en este equipo.")
    setup_safe_environment()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps({"enabled": True}, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(CONFIG_FILE)
    return {"ok": True, "provider": "qwen_cli", "authenticated": True, "enabled": True}


def disable_qwen() -> dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps({"enabled": False}, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(CONFIG_FILE)
    with QWEN_LOCK:
        QWEN_CACHE["models"] = []
        QWEN_CACHE["checked_at"] = 0.0
    return {"ok": True, "provider": "qwen_cli", "authenticated": False, "enabled": False}


def qwen_auth_status() -> dict[str, Any]:
    has_binary = bool(qwen_executable_path())
    enabled = is_qwen_enabled()
    error = ""
    if not has_binary:
        error = "No se encuentra el ejecutable qwen en este equipo."
    elif not enabled:
        error = "Qwen Code CLI está desactivado en MyKOS."
    return {
        "available": has_binary,
        "authenticated": enabled and has_binary,
        "enabled": enabled,
        "provider": "qwen_cli",
        "error": error,
    }


ALLOWED_QWEN_ENV_VARS = {
    "DASHSCOPE_API_KEY",
    "BAILIAN_CODING_PLAN_API_KEY",
    "QWEN_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OLLAMA_API_KEY",
    "OLLAMA_HOST",
}


def _is_local_endpoint(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()
        return hostname in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
    except Exception:
        return False


def _is_cloud_qwen_model(model_name: str) -> bool:
    clean = (model_name or "").strip().removeprefix("qwen-cli/")
    if not clean or clean == "qwen-code-default":
        return False
    if clean in _CLOUD_MODEL_IDS:
        return True
    # Revisar también modelos cacheados declarados como remotos no-Ollama
    with QWEN_LOCK:
        for m in QWEN_CACHE.get("models", []):
            m_id = str(m.get("name") or "").removeprefix("qwen-cli/").strip()
            if (m_id == clean or m.get("name") == model_name) and bool(m.get("remote", False)):
                return not bool(m.get("benchmark_capable", False))
    return False


def _get_qwen_configured_endpoint(model_name: str = "") -> tuple[str, bool]:
    """Lee ~/.qwen/settings.json y determina el baseUrl configurado (revisando model, security y modelProviders)."""
    try:
        user_cfg = Path.home() / ".qwen" / "settings.json"
        if user_cfg.is_file():
            data = json.loads(user_cfg.read_text(encoding="utf-8"))
            explicit_model = (model_name or "").strip().removeprefix("qwen-cli/")
            is_default_lookup = not explicit_model or explicit_model == "qwen-code-default"
            active_model = str(data.get("model", {}).get("name") or "").strip().removeprefix("qwen-cli/")
            lookup_model = active_model if is_default_lookup else explicit_model

            # 1. Comprobar modelProviders (proveedores personalizados como openai, ollama, gemini)
            providers = data.get("modelProviders", {})
            if isinstance(providers, dict):
                for prov_list in providers.values():
                    if isinstance(prov_list, list):
                        for entry in prov_list:
                            if isinstance(entry, dict):
                                e_id = str(entry.get("id") or "").strip().removeprefix("qwen-cli/")
                                e_name = str(entry.get("name") or "").strip().removeprefix("qwen-cli/")
                                if not lookup_model or e_id == lookup_model or e_name == lookup_model:
                                    b_url = str(entry.get("baseUrl") or "").strip()
                                    if b_url:
                                        return b_url, _is_local_endpoint(b_url)

            # 2. Comprobar model.baseUrl o security.auth.baseUrl
            # No heredar baseUrl local (ej. 127.0.0.1:11434) para modelos cloud explícitos.
            base_url = str(
                data.get("model", {}).get("baseUrl")
                or data.get("security", {}).get("auth", {}).get("baseUrl")
                or ""
            ).strip()
            if base_url:
                is_local = _is_local_endpoint(base_url)
                if not is_default_lookup and is_local and explicit_model != active_model:
                    return "", False
                if _is_cloud_qwen_model(lookup_model) and is_local:
                    return "", False
                return base_url, is_local
    except Exception:
        pass
    return "", False


def _is_known_ollama_model(name: str) -> bool:
    if not name or name == "qwen-code-default":
        return False
    clean = name.removeprefix("qwen-cli/").strip()
    with QWEN_LOCK:
        for m in QWEN_CACHE.get("models", []):
            m_id = m.get("name", "").removeprefix("qwen-cli/").strip()
            if m_id == clean or m.get("name") == name:
                return not m.get("remote", True) or bool(m.get("benchmark_capable", False))
    if ":" in clean and not any(clean.startswith(p) for p in ("http:", "https:", "file:")):
        return True
    return False


def _get_ollama_model_names() -> set[str]:
    """Obtiene los nombres de modelos realmente instalados en Ollama local."""
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {str(m.get("name", "")).strip() for m in data.get("models", []) if m.get("name")}
    except Exception:
        return set()


def _discover_qwen_models() -> list[dict[str, Any]]:
    endpoint_url, is_endpoint_local = _get_qwen_configured_endpoint()
    discovered: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1. Modelo predeterminado de Qwen Code
    default_host = "local (Ollama / endpoint local)" if is_endpoint_local else (endpoint_url or "Alibaba Cloud / Remoto")
    default_label_prov = "Qwen Code · Local" if is_endpoint_local else "Qwen Code · Remoto"
    default_auth = "CLI Qwen Code local" if is_endpoint_local else "DashScope / Configuración CLI"
    discovered.append({
        "id": "qwen-code-default",
        "label": "Qwen Code · CLI (Predeterminado)",
        "family": "Qwen",
        "remote": not is_endpoint_local,
        "remote_host": default_host,
        "provider_label": default_label_prov,
        "auth_method": default_auth,
        "is_ollama": False,
    })
    seen.add("qwen-code-default")

    # 2. Modelo activo en ~/.qwen/settings.json (solo si no es local/Ollama)
    try:
        user_cfg = Path.home() / ".qwen" / "settings.json"
        if user_cfg.is_file():
            data = json.loads(user_cfg.read_text(encoding="utf-8"))
            active_model = str(data.get("model", {}).get("name", "")).strip()
            if active_model and active_model not in seen and not _is_known_ollama_model(active_model):
                family = "Qwen Coder" if "coder" in active_model.lower() else "Qwen"
                active_endpoint, is_active_local = _get_qwen_configured_endpoint(active_model)
                if not is_active_local:
                    discovered.append({
                        "id": active_model,
                        "label": f"Qwen Code · {active_model}",
                        "family": family,
                        "remote": True,
                        "remote_host": active_endpoint or default_host,
                        "provider_label": "Qwen Code · Remoto",
                        "auth_method": default_auth,
                        "is_ollama": False,
                    })
                    seen.add(active_model)
    except Exception:
        pass

    # 3. Modelos de suscripción oficial (Qwen Plus / chat.qwen.ai) y OAuth
    sub_file = Path.home() / ".qwen" / "subscription_credentials.json"
    safe_sub_file = SAFE_SETTINGS.parent / "subscription_credentials.json"
    sub_to_check = sub_file if sub_file.is_file() else safe_sub_file
    oauth_file = Path.home() / ".qwen" / "oauth_creds.json"
    safe_oauth_file = SAFE_SETTINGS.parent / "oauth_creds.json"
    oauth_to_check = oauth_file if oauth_file.is_file() else safe_oauth_file

    if sub_to_check.is_file():
        try:
            sub_data = json.loads(sub_to_check.read_text(encoding="utf-8"))
            if sub_data.get("tokens") or sub_data.get("models"):
                for s_id in sub_data.get("models", []):
                    s_id = str(s_id).strip()
                    if s_id and s_id not in seen:
                        s_fam = "Qwen Coder" if "coder" in s_id.lower() else "Qwen"
                        discovered.append({
                            "id": s_id,
                            "label": f"Qwen · {s_id} (Plus)",
                            "family": s_fam,
                            "remote": True,
                            "remote_host": "api.qwen.ai (Qwen Plus)",
                            "provider_label": "Qwen Code · Plus (Suscripción)",
                            "auth_method": "Suscripción Oficial Qwen Plus (chat.qwen.ai)",
                            "is_ollama": False,
                        })
                        seen.add(s_id)
                plus_catalog = [
                    ("qwen3.8-max", "Qwen 3.8 Max · Nube (Plus)", "Qwen"),
                    ("qwen3.8-flash", "Qwen 3.8 Flash · Nube (Plus)", "Qwen"),
                    ("qwen-plus", "Qwen Plus · Nube (chat.qwen.ai)", "Qwen"),
                    ("qwen-turbo", "Qwen Turbo · Nube (chat.qwen.ai)", "Qwen"),
                    ("qwen-max", "Qwen Max · Nube (chat.qwen.ai)", "Qwen"),
                ]
                for p_id, p_label, p_fam in plus_catalog:
                    if p_id not in seen:
                        discovered.append({
                            "id": p_id,
                            "label": p_label,
                            "family": p_fam,
                            "remote": True,
                            "remote_host": "api.qwen.ai (Qwen Plus)",
                            "provider_label": "Qwen Code · Plus (Suscripción)",
                            "auth_method": "Suscripción Oficial Qwen Plus (chat.qwen.ai)",
                            "is_ollama": False,
                        })
                        seen.add(p_id)
        except Exception:
            pass

    if oauth_to_check.is_file():
        try:
            oauth_data = json.loads(oauth_to_check.read_text(encoding="utf-8"))
            if isinstance(oauth_data, dict) and (
                oauth_data.get("access_token")
                or oauth_data.get("refresh_token")
                or oauth_data.get("tokens")
            ):
                for o_id, o_label, o_fam in (
                    ("qwen3-coder-plus", "Qwen 3 Coder Plus · Nube (OAuth)", "Qwen Coder"),
                    ("qwen3-coder-flash", "Qwen 3 Coder Flash · Nube (OAuth)", "Qwen Coder"),
                ):
                    if o_id not in seen:
                        discovered.append({
                            "id": o_id,
                            "label": o_label,
                            "family": o_fam,
                            "remote": True,
                            "remote_host": "portal.qwen.ai (Qwen OAuth)",
                            "provider_label": "Qwen Code · OAuth",
                            "auth_method": "Qwen OAuth (oauth_creds.json)",
                            "is_ollama": False,
                        })
                        seen.add(o_id)
        except Exception:
            pass

    # 5. Modelos de nube solo si se dispone de clave de DashScope / Alibaba
    has_dashscope = bool(
        os.environ.get("DASHSCOPE_API_KEY", "").strip()
        or os.environ.get("BAILIAN_CODING_PLAN_API_KEY", "").strip()
    )
    if has_dashscope:
        for c_id, c_label, c_fam in CLOUD_QWEN_MODELS:
            if c_id not in seen:
                discovered.append({
                    "id": c_id,
                    "label": c_label,
                    "family": c_fam,
                    "remote": True,
                    "remote_host": "Alibaba Cloud DashScope",
                    "provider_label": "Qwen · Nube (DashScope API)",
                    "auth_method": "DashScope API Key",
                    "is_ollama": False,
                })
                seen.add(c_id)

    return discovered


def qwen_model_catalog(force: bool = False) -> tuple[list[dict[str, Any]], bool, str]:
    if not is_qwen_enabled():
        return [], False, ""
    executable = qwen_executable_path()
    if not executable:
        return [], False, "No se encuentra el ejecutable qwen."

    now = time.monotonic()
    with QWEN_LOCK:
        cached = QWEN_CACHE.get("models")
        checked_at = float(QWEN_CACHE.get("checked_at", 0.0))
        if not force and cached and (now - checked_at < CACHE_TTL_SECONDS):
            return list(cached), True, ""

    raw_models = _discover_qwen_models()
    models: list[dict[str, Any]] = []
    for m in raw_models:
        is_cloud = bool(m["remote"])
        models.append(
            {
                "name": f"qwen-cli/{m['id']}",
                "label": m["label"],
                "provider": "qwen_cli",
                "provider_label": m["provider_label"],
                "size": 0,
                "parameter_size": "",
                "family": m["family"],
                "quantization": "",
                "modified_at": "",
                "capabilities": ["chat", "completion", "thinking", "tools"],
                "chat_capable": True,
                "vision_capable": False,
                "thinking_capable": True,
                "tools_capable": True,
                "context_length": 32768,
                "remote": is_cloud,
                "remote_host": m["remote_host"],
                "benchmark_capable": bool(m.get("is_ollama", False)),
                "auth_method": m["auth_method"],
                "auth_status": "autenticado",
                "auth_error": "",
            }
        )

    with QWEN_LOCK:
        QWEN_CACHE["models"] = list(models)
        QWEN_CACHE["checked_at"] = now

    return models, True, ""


def extract_qwen_response(payload: Any) -> tuple[str, dict[str, Any], float, list[str]]:
    """Extrae el texto de respuesta, uso de tokens, duración y herramientas usadas del JSON de Qwen Code."""
    if isinstance(payload, dict):
        payload = [payload]
    tools_used: list[str] = []
    if isinstance(payload, list):
        result_item = None
        assistant_text = ""
        for item in payload:
            if isinstance(item, dict) and item.get("type") == "assistant":
                msg = item.get("message", {})
                content_list = msg.get("content", [])
                if isinstance(content_list, list):
                    for part in content_list:
                        if isinstance(part, dict) and part.get("type") == "tool_use":
                            t_name = str(part.get("name") or "").strip()
                            if t_name and t_name not in tools_used:
                                tools_used.append(t_name)
        for item in reversed(payload):
            if isinstance(item, dict):
                if item.get("type") == "result" and result_item is None:
                    result_item = item
                if not assistant_text and item.get("type") == "assistant":
                    msg = item.get("message", {})
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                assistant_text = part.get("text", "")
                                if assistant_text:
                                    break
        if result_item:
            if result_item.get("is_error"):
                err = result_item.get("error", {})
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(msg or "Qwen devolvió un error de ejecución.")
            text = str(result_item.get("result") or assistant_text).strip()
            usage = result_item.get("usage") or {}
            duration = float(result_item.get("duration_ms", 0.0)) / 1000.0
            return text, usage, duration, tools_used
        if assistant_text:
            return assistant_text.strip(), {}, 0.0, tools_used
    raise RuntimeError("Qwen no devolvió una respuesta válida.")


def _parse_qwen_output(raw_stdout: str) -> Any:
    """Parsea la salida de Qwen tolerando ANSI, NDJSON y banners previos al JSON."""
    cleaned = _ANSI_RE.sub("", raw_stdout or "").strip()
    if not cleaned:
        raise RuntimeError("qwen no devolvió un JSON válido.")

    try:
        return json.loads(cleaned)
    except (ValueError, TypeError):
        pass

    ndjson_items: list[Any] = []
    for line in cleaned.splitlines():
        candidate = line.strip()
        if not candidate or candidate[0] not in "{[":
            continue
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, list):
            ndjson_items.extend(parsed)
        elif isinstance(parsed, dict):
            ndjson_items.append(parsed)
    if ndjson_items:
        return ndjson_items

    decoder = json.JSONDecoder()
    for idx, ch in enumerate(cleaned):
        if ch not in "{[":
            continue
        try:
            obj, _ = decoder.raw_decode(cleaned, idx)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, (dict, list)):
            return obj

    raise RuntimeError("qwen no devolvió un JSON válido.")


def ask_qwen(
    prompt: str,
    timeout_seconds: int = 120,
    model: str = "",
    cwd: str = "",
    add_dirs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Ejecuta un turno en Qwen Code con herramientas autónomas y devuelve respuesta, uso, duración y herramientas."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("El prompt debe contener texto.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"El prompt supera {MAX_PROMPT_CHARS} caracteres.")
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 300:
        raise ValueError("timeout_seconds debe estar entre 1 y 300.")

    ensure_chat_safe()
    executable = qwen_executable_path()
    if not executable:
        raise RuntimeError("No se encuentra el ejecutable qwen en este equipo.")

    clean_model = (model or "").strip()
    raw_name = clean_model.removeprefix("qwen-cli/")
    ollama_models = _get_ollama_model_names()
    is_ollama = bool(raw_name and (clean_model in ollama_models or raw_name in ollama_models))
    is_cloud = _is_cloud_qwen_model(raw_name)
    endpoint_url, is_local = (
        ("", False)
        if (is_ollama or is_cloud)
        else _get_qwen_configured_endpoint(clean_model or raw_name)
    )

    # Fail closed si el modelo era local de Ollama pero Ollama no responde
    if _is_known_ollama_model(clean_model or raw_name) and not is_ollama:
        raise RuntimeError("El modelo local de Ollama no está accesible. No se enviará a la nube por seguridad.")

    command = [
        executable,
        "--output-format",
        "json",
        "-y",
    ]
    if raw_name and raw_name != "qwen-code-default":
        command.extend(["-m", raw_name])

    child_environment = {
        "HOME": str(SAFE_HOME),
        "XDG_CONFIG_HOME": str(SAFE_HOME / ".config"),
        "XDG_CACHE_HOME": str(SAFE_HOME / ".cache"),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    }
    for key, val in os.environ.items():
        if key in ALLOWED_QWEN_ENV_VARS or (key.startswith("QWEN_") and not key.startswith("QWEN_SECRET")):
            if key in _LOCAL_ENV_OVERRIDE_KEYS and (is_cloud or (not is_ollama and _is_local_endpoint(val))):
                continue
            child_environment[key] = val

    # Enrutamiento explícito a endpoint local si el modelo reside en Ollama o tiene baseUrl local
    if is_ollama:
        command.extend(["--openai-base-url", "http://127.0.0.1:11434/v1", "--auth-type", "openai"])
        child_environment["OPENAI_BASE_URL"] = "http://127.0.0.1:11434/v1"
        child_environment["OPENAI_API_KEY"] = "ollama"
        child_environment["OLLAMA_HOST"] = "http://127.0.0.1:11434"
    elif is_local and endpoint_url and not is_cloud:
        command.extend(["--openai-base-url", endpoint_url, "--auth-type", "openai"])
        child_environment["OPENAI_BASE_URL"] = endpoint_url
        child_environment.setdefault("OPENAI_API_KEY", "local")
    elif (SAFE_SETTINGS.parent / "subscription_credentials.json").is_file():
        command.extend(["--auth-type", "qwen-subscription"])
    elif (SAFE_SETTINGS.parent / "oauth_creds.json").is_file():
        command.extend(["--auth-type", "qwen-oauth"])

    target_cwd = Path(cwd) if cwd and Path(cwd).is_dir() else SAFE_HOME
    try:
        resolved_cwd = target_cwd.resolve()
    except OSError:
        resolved_cwd = target_cwd
    seen_dirs: set[Path] = {resolved_cwd}
    raw_extra_dirs: list[Path] = [_cortex_vault_dir()]
    if add_dirs:
        raw_extra_dirs.extend(Path(str(d)).expanduser() for d in add_dirs if str(d).strip())
    for extra in raw_extra_dirs:
        if not extra.is_dir():
            continue
        try:
            resolved_extra = extra.resolve()
        except OSError:
            resolved_extra = extra
        if resolved_extra in seen_dirs:
            continue
        seen_dirs.add(resolved_extra)
        command.extend(["--add-dir", str(extra)])

    command.extend(["-p", prompt])

    options: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout_seconds + 15,
        "check": False,
        "cwd": str(target_cwd),
        "env": child_environment,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        options["start_new_session"] = True

    try:
        result = subprocess.run(command, **options)
    except FileNotFoundError as exc:
        raise RuntimeError("No se encuentra el ejecutable qwen.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Qwen Code excedió el tiempo máximo de respuesta.") from exc

    if result.returncode != 0 and not result.stdout:
        err_msg = (result.stderr or "").strip()
        raise RuntimeError(f"qwen terminó con código {result.returncode}. {err_msg}".strip())

    payload = _parse_qwen_output(result.stdout)

    response_text, usage, duration_seconds, tools_used = extract_qwen_response(payload)
    if not response_text:
        raise RuntimeError("qwen no devolvió texto de respuesta.")

    return {
        "response": response_text,
        "usage": usage,
        "duration_seconds": duration_seconds,
        "tools_used": tools_used,
    }
