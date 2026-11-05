"""Búsqueda web y descarga de páginas públicas para MyKOS con protección SSRF.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse, urlsplit, urlunsplit

from .base import (
    ToolError,
    WEB_MAX_BYTES,
    WEB_MAX_RESULTS,
    WEB_MAX_TEXT_CHARS,
    WEB_REQUEST_TIMEOUT_SECONDS,
    WEB_USER_AGENT,
)

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


