"""Herramientas de inspección de hardware, procesos y servicios del sistema.
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import (
    MAX_PROCESS_QUERY_CHARS,
    MAX_PROCESS_RESULTS,
    MAX_SERVICE_NAME_CHARS,
    MAX_SERVICE_RESULTS,
    ToolError,
)

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


