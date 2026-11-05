"""Ejecución de comandos del sistema, entorno gráfico y semáforo heurístico de seguridad.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .base import (
    MAX_COMMAND_CHARS,
    MAX_COMMAND_TIMEOUT,
    ToolError,
    _relative_label,
    _resolve_project_path,
)


def _desktop_session_environment() -> dict[str, str]:
    """Variables de la sesión gráfica de Usuario, para que un comando aprobado pueda abrir ventanas.

    El backend arranca con un HOME propio y sin DISPLAY; se toman de un proceso del escritorio del
    mismo usuario. Si no hay sesión gráfica, se devuelve solo lo que se pueda deducir.
    """
    import pwd

    uid = os.getuid()
    wanted = (
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XAUTHORITY",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
        "XDG_CURRENT_DESKTOP",
        "XDG_SESSION_TYPE",
        "XDG_DATA_DIRS",
        "LANG",
    )
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


def _execute_run_shell_posix(
    action: dict[str, Any],
    cwd_root: str,
    cwd_root_path: Path,
    cwd_path: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Ejecuta en Linux/macOS, con bash, el comando ya aprobado por el usuario."""
    shell = shutil.which("bash") or "/bin/sh"
    environment = {
        k: v
        for k, v in os.environ.items()
        if (not re.search(r"(TOKEN|KEY|SECRET|PASSWORD|AUTH)", k, re.IGNORECASE))
        or k in {"SSH_AUTH_SOCK", "GPG_AGENT_INFO"}
    }
    environment.update(_desktop_session_environment())
    # La salida va a ficheros temporales, no a tuberías: un programa gráfico lanzado por el comando
    # (p. ej. el gestor de archivos tras xdg-open) hereda la salida y dejaría la llamada colgada.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        timed_out = False
        try:
            process = subprocess.Popen(
                [shell, "-c", action["command"]],
                cwd=str(cwd_path),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                env=environment,
                start_new_session=True,
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
            "ok": False,
            "action": "run_powershell",
            "shell": "bash",
            "timed_out": True,
            "timeout_seconds": timeout_seconds,
            "stdout": stdout,
            "stderr": "El comando superó el tiempo máximo de ejecución.",
        }
    return {
        "ok": returncode == 0,
        "action": "run_powershell",
        "shell": "bash",
        "cwd_root": cwd_root,
        "cwd_path": _relative_label(cwd_path, cwd_root_path),
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


def _execute_run_powershell(action: dict[str, Any]) -> dict[str, Any]:
    prepared = _prepare_run_powershell(action)
    action = prepared
    cwd_root, cwd_root_path, cwd_path = _resolve_project_path(
        action.get("cwd_root", "mykos"), action.get("cwd_path", "")
    )
    timeout_seconds = int(action.get("timeout_seconds", 30))
    return _execute_run_shell_posix(action, cwd_root, cwd_root_path, cwd_path, timeout_seconds)


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
