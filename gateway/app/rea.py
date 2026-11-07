"""
Puente nativo con REA (Reverse Engineer Anything) para MyKOS.
Conecta mediante protocolo MCP (JSON-RPC 2.0 sobre stdio) con `rea-agents`,
exponiendo las 207 herramientas de ingeniería inversa estática, decompilación,
análisis de binarios (ELF, PE, Mach-O, APK, WASM, Firmware) y aplicaciones JS/Electron.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

REA_PACKAGE = os.environ.get("MYKOS_REA_PACKAGE", "rea-agents@6.7.0").strip()
REA_TIMEOUT_SECONDS = int(os.environ.get("MYKOS_REA_TIMEOUT", "120"))

# Herramientas de REA que ejecutan instrumentación dinámica, modifican dispositivos o extraen artefactos
REA_DYNAMIC_TOOLS = {
    "start_frida_session",
    "load_frida_script",
    "instrument_with_frida",
    "start_gdb_session",
    "gdb_console",
    "start_rizin_debug_session",
    "rizin_debug_command",
    "execute_rizin_command",
    "cutter_command",
    "push_adb_file",
    "pull_adb_file",
    "install_adb_package",
    "uninstall_adb_package",
    "start_adb_app",
    "start_adb_activity",
    "stop_adb_app",
    "capture_process_scenario",
    "observe_native_calls",
    "observe_native_ui",
    "capture_native_ui_scenario",
    "observe_javascript_runtime",
    "observe_web_execution",
    "capture_electron_scenario",
    "capture_browser_scenario",
    "capture_web_screenshot",
    "export_web_scripts",
    "extract_firmware",
    "export_evidence_bundle",
    "set_address_name",
    "set_comment",
    "set_bookmark",
    "set_inline_comment",
    "import_managed_reconstruction",
}


def _clean_subproc_env() -> dict[str, str]:
    """Sanea el entorno para que paquetes npm o scripts externos no hereden tokens ni claves maestras."""
    return {
        k: v for k, v in os.environ.items()
        if not re.search(r"(TOKEN|KEY|SECRET|PASSWORD|AUTH)", k, re.IGNORECASE)
    }


class ReaError(Exception):
    """Error seguro producido al comunicarse con el motor REA."""


def _resolve_npx_command() -> list[str]:
    custom = os.environ.get("MYKOS_REA_COMMAND", "").strip()
    if custom:
        return custom.split()
    npx_bin = "npx.cmd" if sys.platform == "win32" else "npx"
    resolved = shutil.which(npx_bin) or shutil.which("npx")
    if not resolved:
        raise ReaError("No se encontró «npx» (Node.js) para iniciar el motor REA.")
    return [resolved, "-y", REA_PACKAGE, "mcp"]


class _ReaMcpSession:
    """Sesión persistente JSON-RPC 2.0 sobre stdio con el servidor MCP de REA."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._server_info: dict[str, Any] = {}
        self._tools_cache: list[dict[str, Any]] | None = None

    def _ensure_started_unlocked(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        cmd = _resolve_npx_command()
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=_clean_subproc_env(),
            )
        except OSError as exc:
            raise ReaError(f"No se pudo arrancar el servidor REA ({' '.join(cmd)}): {exc}") from exc

        init_res = self._rpc_unlocked(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mykos-gateway", "version": "1.0.0"},
            },
        )
        self._server_info = init_res.get("serverInfo", {}) if isinstance(init_res, dict) else {}
        self._notify_unlocked("notifications/initialized", {})

    def _notify_unlocked(self, method: str, params: dict[str, Any]) -> None:
        if not self._proc or not self._proc.stdin:
            raise ReaError("Sesión REA no disponible.")
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, ensure_ascii=False)
        self._proc.stdin.write(msg + "\n")
        self._proc.stdin.flush()

    def _rpc_unlocked(self, method: str, params: dict[str, Any]) -> Any:
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise ReaError("Sesión REA no iniciada.")
        req_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        try:
            self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
            while True:
                line = self._proc.stdout.readline()
                if not line:
                    stderr_tail = ""
                    if self._proc.stderr:
                        try:
                            stderr_tail = self._proc.stderr.read()[:400]
                        except Exception:
                            pass
                    self._proc = None
                    raise ReaError(f"El proceso REA cerró la conexión inesperadamente. {stderr_tail}".strip())
                line = line.strip()
                if not line:
                    continue
                try:
                    resp = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if resp.get("id") == req_id:
                    if "error" in resp:
                        err = resp["error"]
                        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                        raise ReaError(f"Error de REA en {method}: {msg}")
                    return resp.get("result")
        except BrokenPipeError as exc:
            self._proc = None
            raise ReaError("Tubería rota comunicando con REA.") from exc

    def list_tools(self) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_started_unlocked()
            if self._tools_cache is None:
                res = self._rpc_unlocked("tools/list", {})
                tools = res.get("tools", []) if isinstance(res, dict) else []
                self._tools_cache = tools if isinstance(tools, list) else []
            return self._tools_cache

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_started_unlocked()
            res = self._rpc_unlocked("tools/call", {"name": name, "arguments": arguments or {}})
            if not isinstance(res, dict):
                return {"ok": True, "tool": name, "result": res}
            is_error = bool(res.get("isError", False))
            content = res.get("content", [])
            parsed_items: list[Any] = []
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        txt = str(item.get("text", ""))
                        try:
                            parsed_items.append(json.loads(txt))
                        except json.JSONDecodeError:
                            parsed_items.append(txt)
                    else:
                        parsed_items.append(item)
            output = parsed_items[0] if len(parsed_items) == 1 else parsed_items
            return {
                "ok": not is_error,
                "tool": name,
                "server": self._server_info,
                "untrusted_target_content": True,
                "result": output,
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_started_unlocked()
            if self._tools_cache is None:
                res = self._rpc_unlocked("tools/list", {})
                tools = res.get("tools", []) if isinstance(res, dict) else []
                self._tools_cache = tools if isinstance(tools, list) else []
            return {
                "ok": True,
                "available": True,
                "package": REA_PACKAGE,
                "server": self._server_info,
                "pid": self._proc.pid if self._proc else None,
                "tools_count": len(self._tools_cache or []),
            }


_SESSION = _ReaMcpSession()


def rea_status() -> dict[str, Any]:
    """Devuelve el estado de conexión y versión del motor REA."""
    try:
        return _SESSION.status()
    except ReaError as exc:
        return {"ok": False, "available": False, "package": REA_PACKAGE, "error": str(exc)}


def rea_list_tools(query: str = "", limit: int = 35) -> dict[str, Any]:
    """Lista o busca herramientas en el catálogo de 207 herramientas de REA."""
    tools = _SESSION.list_tools()
    q = (query or "").strip().lower()
    matched = []
    for t in tools:
        name = str(t.get("name", ""))
        desc = str(t.get("description", ""))
        if not q or q in name.lower() or q in desc.lower():
            schema = t.get("inputSchema") or t.get("parameters") or {}
            props = schema.get("properties", {}) if isinstance(schema, dict) else {}
            req = schema.get("required", []) if isinstance(schema, dict) else []
            matched.append({
                "name": name,
                "dynamic_requires_approval": name in REA_DYNAMIC_TOOLS,
                "description": desc[:260] + ("…" if len(desc) > 260 else ""),
                "required_params": req,
                "optional_params": [k for k in props.keys() if k not in req],
            })
    capped = max(1, min(int(limit or 35), 100))
    return {
        "ok": True,
        "total_rea_tools": len(tools),
        "matched_count": len(matched),
        "showing": len(matched[:capped]),
        "tools": matched[:capped],
    }


SYSTEM_BIN_DIRS = (
    Path("/usr/bin"),
    Path("/bin"),
    Path("/usr/local/bin"),
    Path("/usr/sbin"),
    Path("/sbin"),
    (Path.home() / ".local" / "bin").resolve(),
)


def _is_within_allowed_roots(path: Path) -> bool:
    try:
        from tools.base import _load_allowed_roots, _is_ignored
        roots = _load_allowed_roots()
        resolved = path.resolve()
        for r in roots:
            try:
                resolved.relative_to(r["path"])
                if _is_ignored(resolved, r["path"]):
                    return False
                return True
            except (ValueError, OSError):
                continue
    except Exception:
        pass
    return False


def _is_system_binary(path: Path) -> bool:
    try:
        resolved = path.resolve()
        for b_dir in SYSTEM_BIN_DIRS:
            try:
                resolved.relative_to(b_dir)
                if os.access(resolved, os.X_OK) and not resolved.is_dir():
                    return True
            except (ValueError, OSError):
                continue
    except Exception:
        pass
    return False


def resolve_rea_target(target: str) -> str:
    """Resuelve un nombre de programa o ruta autorizada para análisis REA."""
    raw = (target or "").strip()
    if not raw:
        raise ReaError("Debes indicar el nombre del programa o la ruta del archivo a revisar con REA.")

    expanded = Path(raw).expanduser().resolve()

    # 1. Bloqueo estricto de rutas privadas, claves y secretos
    try:
        from tools.base import _is_private_path
        if _is_private_path(expanded):
            raise ReaError(f"Acceso denegado: «{expanded}» pertenece a una ruta privada protegida.")
    except ImportError:
        pass
    for part in expanded.parts:
        if part.casefold() in {".ssh", ".gnupg", ".aws", ".kube", "credentials", "oauth", "secrets"}:
            raise ReaError(f"Acceso denegado: «{expanded}» contiene componentes de ruta restringidos.")

    # 2. Si la ruta existe en disco: debe residir dentro de las raíces autorizadas o ser un ejecutable del sistema
    if expanded.exists():
        try:
            from tools.base import _load_allowed_roots, _is_ignored
            for r in _load_allowed_roots():
                try:
                    expanded.relative_to(r["path"])
                    if _is_ignored(expanded, r["path"]):
                        raise ReaError(f"Acceso denegado: «{expanded}» es un archivo protegido o ignorado (.env, claves o secretos).")
                except (ValueError, OSError):
                    pass
        except ReaError:
            raise
        except Exception:
            pass
        if _is_within_allowed_roots(expanded):
            return str(expanded)
        if _is_system_binary(expanded):
            return str(expanded)
        raise ReaError(f"Acceso denegado: «{expanded}» queda fuera de las raíces autorizadas del proyecto y no es un ejecutable del sistema.")

    # 3. Si no existe como ruta directa, buscar en el PATH del sistema
    search_path = os.environ.get("PATH", "")
    extra_dirs = [
        str(Path.home() / ".local" / "bin"),
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    full_path = os.pathsep.join(extra_dirs + ([search_path] if search_path else []))
    found = shutil.which(raw, path=full_path)
    if found:
        found_path = Path(found).resolve()
        if _is_system_binary(found_path) or _is_within_allowed_roots(found_path):
            return str(found_path)
    raise ReaError(f"No se encontró el programa o archivo «{raw}» dentro del perímetro autorizado de MyKOS.")


def resolve_rea_output_target(target: str) -> str:
    """Valida que una ruta de salida o exportación resida estrictamente dentro de las raíces autorizadas del proyecto."""
    raw = (target or "").strip()
    if not raw:
        raise ReaError("Debes indicar una ruta de destino válida.")
    expanded = Path(raw).expanduser().resolve()
    try:
        from tools.base import _is_private_path
        if _is_private_path(expanded):
            raise ReaError(f"Acceso denegado: «{expanded}» pertenece a una ruta privada protegida.")
    except ImportError:
        pass
    for part in expanded.parts:
        if part.casefold() in {".ssh", ".gnupg", ".aws", ".kube", "credentials", "oauth", "secrets"}:
            raise ReaError(f"Acceso denegado: «{expanded}» contiene componentes de ruta restringidos.")
    if not _is_within_allowed_roots(expanded):
        raise ReaError(f"Acceso denegado: el destino «{expanded}» queda fuera de las raíces autorizadas del proyecto.")
    return str(expanded)


PATH_KEYS = {
    "path", "input_path", "output_path", "file_path", "binary_path",
    "target", "file", "binary", "dir", "directory", "folder", "root",
    "output_dir", "out_dir", "destination", "dest", "source", "src",
    "input", "output", "archive", "archive_path", "bundle", "script_path"
}

OUTPUT_KEYS = {
    "output", "output_path", "output_dir", "out_dir", "destination",
    "dest", "export", "export_dir", "extract_to", "extract_dir", "save_path"
}


def _is_output_key(key: str) -> bool:
    k = key.lower().strip()
    return k in OUTPUT_KEYS or any(p in k for p in ("output", "destination", "dest", "export", "extract_to"))


def _is_path_key(key: str) -> bool:
    k = key.lower().strip()
    if k in PATH_KEYS:
        return True
    return any(k.endswith(suf) for suf in ("_path", "_dir", "_file", "_target", "_folder", "_root")) or any(
        k.startswith(pref) for pref in ("path_", "dir_", "file_")
    )


def _is_url(val: str) -> bool:
    s = val.strip().lower()
    return s.startswith(("http://", "https://", "ftp://", "ws://", "wss://"))


def _is_explicit_path_syntax(val: str) -> bool:
    """Detecta sintaxis explícita de ruta en sistema de archivos (absoluta, home, relativa explícita o UNC)."""
    s = val.strip()
    if not s or _is_url(s):
        return False
    if s.startswith(("/", "~", "./", "../")):
        return True
    if len(s) >= 3 and (s[1:3] == ":\\" or s[1:3] == ":/"):
        return True
    if s.startswith(("\\\\", "//")):
        return True
    return False


def _sanitize_rea_args(args: Any) -> Any:
    if isinstance(args, dict):
        sanitized = {}
        for k, v in args.items():
            if isinstance(v, str):
                is_out = _is_output_key(k)
                is_pk = _is_path_key(k)
                is_explicit_path = _is_explicit_path_syntax(v)
                if is_out:
                    if is_pk or is_explicit_path:
                        sanitized[k] = resolve_rea_output_target(v)
                    else:
                        sanitized[k] = v
                elif is_pk:
                    if not _is_url(v):
                        sanitized[k] = resolve_rea_target(v)
                    else:
                        sanitized[k] = v
                elif is_explicit_path:
                    sanitized[k] = resolve_rea_target(v)
                else:
                    sanitized[k] = v
            elif isinstance(v, (dict, list)):
                sanitized[k] = _sanitize_rea_args(v)
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(args, list):
        return [_sanitize_rea_args(item) for item in args]
    return args


def rea_inspect_binary(path: str) -> dict[str, Any]:
    """Abre un programa, binario o artefacto local en REA y devuelve su inspección criptográfica y cabeceras."""
    clean_path = resolve_rea_target(path)
    target_obj = Path(clean_path)
    if target_obj.is_dir() or target_obj.suffix.lower() in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        js_res = _SESSION.call_tool(
            "analyze_javascript_application",
            {"input_path": clean_path, "detail": "summary"},
        )
        return {
            "ok": js_res.get("ok", True),
            "target_path": clean_path,
            "kind": "javascript_application",
            "analysis": js_res.get("result"),
        }

    opened = _SESSION.call_tool("open_binary", {"path": clean_path})
    artifact = _SESSION.call_tool("inspect_artifact", {"detail": "summary"})
    headers = _SESSION.call_tool("inspect_with_objdump", {"path": clean_path, "operation": "file_headers"})
    sections = _SESSION.call_tool("inspect_with_objdump", {"path": clean_path, "operation": "section_headers"})
    return {
        "ok": True,
        "target_path": clean_path,
        "open_binary": opened.get("result"),
        "artifact": artifact.get("result"),
        "file_headers": headers.get("result") if headers.get("ok") else None,
        "section_headers": sections.get("result") if sections.get("ok") else None,
    }


def rea_analyze_javascript(input_path: str, detail: str = "summary") -> dict[str, Any]:
    """Ejecuta ingeniería inversa estática de REA sobre una aplicación JavaScript, TypeScript, Web o Electron."""
    clean_path = resolve_rea_target(input_path)
    detail_mode = detail if detail in {"summary", "standard", "full"} else "summary"
    return _SESSION.call_tool(
        "analyze_javascript_application",
        {"input_path": clean_path, "detail": detail_mode},
    )


def rea_call_tool(tool_name: str, arguments: dict[str, Any] | None = None, allow_dynamic: bool = False) -> dict[str, Any]:
    """Invoca cualquiera de las 207 herramientas del servidor MCP de REA."""
    name = (tool_name or "").strip()
    if not name:
        raise ReaError("Debes indicar el nombre de la herramienta de REA (tool_name).")
    if name in REA_DYNAMIC_TOOLS and not allow_dynamic:
        raise ReaError(
            f"La herramienta «{name}» realiza instrumentación dinámica en vivo y requiere aprobación explícita."
        )
    clean_args = _sanitize_rea_args(arguments or {})
    return _SESSION.call_tool(name, clean_args)
