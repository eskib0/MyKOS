"""Navegador local aislado para MyKOS.

Usa Chrome/Edge en un perfil temporal y habla con el Chrome DevTools Protocol
por localhost. No reutiliza el perfil, cookies, sesiones ni credenciales de
MyKOS. Esta primera versión solo expone navegación y lectura de páginas.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class BrowserError(Exception):
    """Error controlado del navegador local."""


MAX_BROWSER_TEXT_CHARS = 30_000
MAX_BROWSER_LINKS = 80
BROWSER_TIMEOUT_SECONDS = 20
BROWSER_USER_AGENT = "MyKOS/1.0 (isolated browser)"


def _validate_public_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BrowserError("Debes indicar una URL pública http o https.")
    url = value.strip()
    if len(url) > 2_000:
        raise BrowserError("La URL es demasiado larga.")
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise BrowserError("Solo se permiten URLs http o https con un host público.")
    if parsed.username or parsed.password:
        raise BrowserError("No se permiten URLs con usuario o contraseña incorporados.")
    try:
        port = parsed.port
    except ValueError as error:
        raise BrowserError("La URL contiene un puerto no válido.") from error
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
        raise BrowserError("Por seguridad, no se permiten hosts locales o internos.")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            resolved = socket.getaddrinfo(
                host,
                port or (443 if parsed.scheme.lower() == "https" else 80),
                type=socket.SOCK_STREAM,
            )
            addresses = {ipaddress.ip_address(item[4][0]) for item in resolved}
        except (OSError, ValueError) as error:
            raise BrowserError("No se pudo resolver el host de la URL.") from error
    if not addresses or any(not address.is_global for address in addresses):
        raise BrowserError("Por seguridad, la URL apunta a una red local, privada o no enrutable.")
    return parsed.geturl()


def _read_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": BROWSER_USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BrowserError("No se pudo conectar con el navegador local.") from error


class _WebSocket:
    """Cliente WebSocket mínimo para el endpoint CDP local."""

    def __init__(self, ws_url: str) -> None:
        parsed = urlparse(ws_url)
        if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise BrowserError("El navegador devolvió un endpoint CDP no local.")
        self.socket = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=BROWSER_TIMEOUT_SECONDS)
        self.socket.settimeout(BROWSER_TIMEOUT_SECONDS)
        self.next_id = 1
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port or 80}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self.socket.sendall(request)
        response = self._read_until(b"\r\n\r\n")
        if not response.startswith(b"HTTP/1.1 101"):
            self.close()
            raise BrowserError("El navegador rechazó la conexión CDP.")

    def _read_until(self, marker: bytes) -> bytes:
        data = bytearray()
        while marker not in data:
            chunk = self.socket.recv(4096)
            if not chunk:
                raise BrowserError("La conexión con el navegador se cerró prematuramente.")
            data.extend(chunk)
            if len(data) > 64_000:
                raise BrowserError("La respuesta del navegador es demasiado grande.")
        return bytes(data)

    def _recv_exact(self, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = self.socket.recv(length - len(data))
            if not chunk:
                raise BrowserError("La conexión con el navegador se cerró.")
            data.extend(chunk)
        return bytes(data)

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        first = 0x80 | (opcode & 0x0F)
        length = len(payload)
        if length < 126:
            header = bytes([first, 0x80 | length])
        elif length < 65_536:
            header = bytes([first, 0x80 | 126]) + struct.pack("!H", length)
        else:
            header = bytes([first, 0x80 | 127]) + struct.pack("!Q", length)
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.socket.sendall(header + mask + masked)

    def _recv_frame(self) -> tuple[int, bytes]:
        first, second = self._recv_exact(2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        if length > 8 * 1024 * 1024:
            raise BrowserError("El mensaje del navegador supera el límite permitido.")
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        call_id = self.next_id
        self.next_id += 1
        self._send_frame(1, json.dumps({"id": call_id, "method": method, "params": params or {}}).encode("utf-8"))
        while True:
            opcode, payload = self._recv_frame()
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0x8:
                raise BrowserError("El navegador cerró la página.")
            if opcode != 0x1:
                continue
            try:
                message = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise BrowserError("El navegador devolvió un mensaje no válido.") from error
            if message.get("method") in {"Network.requestIntercepted", "Fetch.requestPaused"}:
                self._handle_intercepted_request(message)
                continue
            if message.get("id") != call_id:
                continue
            if "error" in message:
                detail = message.get("error", {}).get("message", "error CDP")
                raise BrowserError(str(detail))
            return message.get("result", {}) if isinstance(message.get("result", {}), dict) else {}

    def _handle_intercepted_request(self, message: dict[str, Any]) -> None:
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        fetch_paused = message.get("method") == "Fetch.requestPaused"
        interception_id = str(params.get("requestId" if fetch_paused else "interceptionId", "")).strip()
        request = params.get("request") if isinstance(params.get("request"), dict) else {}
        request_url = str(request.get("url", "")).strip()
        if not interception_id:
            return
        allowed = False
        try:
            parsed = urlparse(request_url)
            if parsed.scheme.lower() in {"data", "blob"}:
                allowed = True
            else:
                _validate_public_url(request_url)
                allowed = True
        except BrowserError:
            allowed = False
        command_method = "Fetch.continueRequest" if fetch_paused else "Network.continueInterceptedRequest"
        command = {
            "id": self.next_id,
            "method": command_method,
            "params": {"requestId" if fetch_paused else "interceptionId": interception_id},
        }
        self.next_id += 1
        if not allowed:
            if fetch_paused:
                command["method"] = "Fetch.failRequest"
                command["params"] = {"requestId": interception_id, "errorReason": "BlockedByClient"}
            else:
                command["params"]["errorReason"] = "BlockedByClient"
        self._send_frame(1, json.dumps(command).encode("utf-8"))

    def close(self) -> None:
        try:
            self.socket.close()
        except OSError:
            pass


class _BrowserController:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.process: subprocess.Popen[Any] | None = None
        self.port = 0
        self.profile: Path | None = None
        self.target_url = ""
        self.ws: _WebSocket | None = None

    def _find_executable(self) -> str:
        candidates = [
            os.environ.get("MYKOS_BROWSER_EXECUTABLE", ""),
            "/var/lib/flatpak/exports/bin/org.chromium.Chromium",
            shutil.which("google-chrome") or "",
            shutil.which("google-chrome-stable") or "",
            shutil.which("chromium") or "",
            shutil.which("chromium-browser") or "",
            shutil.which("brave-browser") or "",
            shutil.which("microsoft-edge") or "",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return candidate
        raise BrowserError("No se encontró Chrome, Chromium, Brave ni Edge para el navegador aislado.")

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _targets(self) -> list[dict[str, Any]]:
        result = _read_json(f"http://127.0.0.1:{self.port}/json/list")
        return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []

    def _ensure(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        executable = self._find_executable()
        self.port = self._free_port()
        self.profile = Path(tempfile.mkdtemp(prefix="mykos-browser-"))
        command = [
            executable,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile}",
            "about:blank",
        ]
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            self.close()
            raise BrowserError(f"No se pudo iniciar el navegador aislado: {error}") from error
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise BrowserError("El navegador aislado se cerró al iniciarse.")
            try:
                if self._targets():
                    return
            except BrowserError:
                time.sleep(0.2)
        self.close()
        raise BrowserError("El navegador aislado no estuvo disponible a tiempo.")

    def _page_socket(self) -> _WebSocket:
        targets = [item for item in self._targets() if item.get("type") == "page" and item.get("webSocketDebuggerUrl")]
        if not targets:
            raise BrowserError("No hay ninguna página disponible en el navegador aislado.")
        return _WebSocket(str(targets[0]["webSocketDebuggerUrl"]))

    @staticmethod
    def _extract(ws: _WebSocket, max_chars: int) -> dict[str, Any]:
        expression = """
(() => {
  const body = document.body;
  const links = Array.from(document.querySelectorAll('a[href]')).slice(0, 80).map(a => ({
    text: (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240),
    url: a.href
  })).filter(item => item.url);
  return JSON.stringify({
    title: document.title || '',
    url: location.href,
    ready_state: document.readyState,
    text: (body ? (body.innerText || body.textContent || '') : '').replace(/\\s+/g, ' ').trim(),
    links
  });
})()
"""
        result = ws.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        remote = result.get("result", {})
        value = remote.get("value") if isinstance(remote, dict) else None
        if not isinstance(value, str):
            raise BrowserError("La página no devolvió texto legible.")
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise BrowserError("No se pudo interpretar el contenido de la página.") from error
        if not isinstance(parsed, dict):
            raise BrowserError("El contenido de la página no tiene un formato válido.")
        text = str(parsed.get("text", ""))
        parsed["text"] = text[:max_chars] + ("…" if len(text) > max_chars else "")
        parsed["truncated"] = len(text) > max_chars
        links = parsed.get("links")
        parsed["links"] = links[:MAX_BROWSER_LINKS] if isinstance(links, list) else []
        return parsed

    def open(self, url: str, max_chars: int) -> dict[str, Any]:
        with self.lock:
            self._ensure()
            if self.ws is not None:
                self.ws.close()
                self.ws = None
            ws = self._page_socket()
            self.ws = ws
            try:
                ws.call("Page.enable")
                ws.call("Runtime.enable")
                ws.call("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
                ws.call("Page.navigate", {"url": url})
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    state = ws.call("Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True})
                    value = (state.get("result") or {}).get("result", {}).get("value")
                    if value == "complete":
                        break
                    time.sleep(0.25)
                result = self._extract(ws, max_chars)
                final_url = _validate_public_url(str(result.get("url", "")))
                self.target_url = final_url
                result["url"] = final_url
                return result
            except Exception:
                self.close()
                raise

    def snapshot(self, max_chars: int) -> dict[str, Any]:
        with self.lock:
            if not self.target_url or self.ws is None:
                raise BrowserError("Todavía no hay una página abierta en el navegador aislado.")
            self._ensure()
            try:
                result = self._extract(self.ws, max_chars)
                final_url = _validate_public_url(str(result.get("url", "")))
                self.target_url = final_url
                result["url"] = final_url
                return result
            except Exception:
                self.close()
                raise

    def close(self) -> None:
        if self.ws is not None:
            self.ws.close()
            self.ws = None
        process = self.process
        profile = self.profile
        self.process = None
        self.profile = None
        self.port = 0
        self.target_url = ""
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        if profile is not None:
            shutil.rmtree(profile, ignore_errors=True)


_CONTROLLER = _BrowserController()


def _max_chars(arguments: dict[str, Any]) -> int:
    try:
        value = int(arguments.get("max_chars", MAX_BROWSER_TEXT_CHARS))
    except (TypeError, ValueError) as error:
        raise BrowserError("max_chars debe ser un número entero.") from error
    return max(1_000, min(value, MAX_BROWSER_TEXT_CHARS))


def browser_open(arguments: dict[str, Any]) -> dict[str, Any]:
    url = _validate_public_url(arguments.get("url"))
    result = _CONTROLLER.open(url, _max_chars(arguments))
    return {
        "ok": True,
        "action": "browser_open",
        "isolated": True,
        "title": result.get("title", ""),
        "url": result.get("url", url),
        "ready_state": result.get("ready_state", ""),
        "text": result.get("text", ""),
        "truncated": bool(result.get("truncated", False)),
        "links": result.get("links", []),
    }


def browser_snapshot(arguments: dict[str, Any]) -> dict[str, Any]:
    result = _CONTROLLER.snapshot(_max_chars(arguments))
    return {
        "ok": True,
        "action": "browser_snapshot",
        "isolated": True,
        "title": result.get("title", ""),
        "url": result.get("url", ""),
        "ready_state": result.get("ready_state", ""),
        "text": result.get("text", ""),
        "truncated": bool(result.get("truncated", False)),
        "links": result.get("links", []),
    }


def browser_close() -> dict[str, Any]:
    _CONTROLLER.close()
    return {"ok": True, "action": "browser_close", "closed": True}
