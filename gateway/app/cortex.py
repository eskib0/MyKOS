"""
cortex.py — Motor oficial de índice de conocimiento, enlaces y grafo de MyKOS Cortex.

Basado en Python stdlib (PyYAML opcional si está disponible).
Implementa el indexador incremental de notas Markdown de la bóveda Cortex nativa:
  - Escaneo seguro con `followlinks=False` (evita bucles por symlinks recursivos).
  - Caché de metadatos por hash SHA-256 de contenido.
  - Resolución fiel de wikilinks (`[[Nota|alias]]`, `[[Nota#Sección]]`),
    enlaces Markdown internos, embeds (`![[...]]`), frontmatter YAML y tags.
  - Construcción de grafo (`nodes`, `edges`, `stats`) listo para JSON,
    lectura/guardado incremental de notas y búsqueda en título, tags y contenido.
"""
from __future__ import annotations

import datetime
import hashlib
import os
import re
import shutil
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

try:
    import yaml  # PyYAML (opcional)
except Exception:  # pragma: no cover
    yaml = None

DEFAULT_VAULT_PATH = Path.home() / ".mykos" / "cortex"
FALLBACK_VAULT_PATH = Path.home() / ".mykos" / "workspace"
_OFFICIAL_DEFAULT_VAULT = DEFAULT_VAULT_PATH

# ───────────────────────── 1. PARSER ─────────────────────────
WIKILINK_RE = re.compile(r"(!?)\[\[(.+?)\]\]")
MDLINK_RE = re.compile(
    r"(!?)\[([^\]]*)\]\(\s*(<[^>]*?>|[^ \")]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)
TAG_RE = re.compile(
    r"(?:(?<=\s)|^)#([^\u2000-\u206F\u2E00-\u2E7F'!\"#$%&()*+,.:;<=>?@^`{|}~\[\]\\\s]+)"
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)
FENCE_RE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.M | re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
EXTERNAL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s.replace("\u00a0", " ")).strip()


def _json_safe(value: Any) -> Any:
    """Convierte valores YAML/Python (p. ej. datetime.date) a tipos serializables en JSON."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def split_link(raw: str) -> dict[str, Any]:
    """Separa `href|alias`; si no hay alias, convierte `#` en ` > `."""
    bar = raw.find("|")
    is_alias = bar > 0
    if is_alias:
        title, href = raw[bar + 1 :].strip(), raw[:bar].strip()
    else:
        href = raw.strip()
        title = " > ".join(p for p in href.split("#") if p).strip()
    if href.endswith("\\"):
        href = href[:-1]
    return {"href": _norm(href), "title": title, "isAlias": is_alias}


def strip_subpath(link: str) -> str:
    i = link.find("#")
    return link if i == -1 else link[:i]


def _mask_code(text: str) -> str:
    """Sustituye bloques e inline code por espacios preservando saltos de línea y offsets."""
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))
    return INLINE_CODE_RE.sub(blank, FENCE_RE.sub(blank, text))


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[,\n]", v) if x.strip()] if "," in v else [v.strip()]
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if isinstance(x, (str, int, float))]
    return []


def _parse_yaml(block: str) -> dict[str, Any]:
    if yaml is not None:
        try:
            parsed = yaml.safe_load(block)
            return _json_safe(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    out: dict[str, Any] = {}
    key: str | None = None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([\w\- ]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                out[key] = [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()]
            elif val == "":
                out[key] = []
            else:
                out[key] = val.strip("'\"")
        elif key and re.match(r"^\s*-\s+", line) and isinstance(out.get(key), list):
            out[key].append(re.sub(r"^\s*-\s+", "", line).strip().strip("'\""))
    return out


def _frontmatter_links(fm: Any, prefix: str = "") -> list[dict[str, Any]]:
    """Extrae enlaces `[[x]]` en valores string del frontmatter."""
    res: list[dict[str, Any]] = []
    items = enumerate(fm) if isinstance(fm, list) else fm.items() if isinstance(fm, dict) else []
    for k, v in items:
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, str) and v.startswith("[[") and v.endswith("]]"):
            p = split_link(v[2:-2])
            res.append({"key": key, "link": p["href"], "original": v, "displayText": p["title"]})
        elif isinstance(v, (dict, list)):
            res.extend(_frontmatter_links(v, key))
    return res


def parse_note(text: str) -> dict[str, Any]:
    """Parsea una nota Markdown y devuelve su metadata cacheada."""
    meta: dict[str, Any] = {"links": [], "embeds": [], "tags": [], "headings": []}
    body_off = 0
    m = FRONTMATTER_RE.match(text)
    if m:
        fm = _parse_yaml(m.group(1))
        meta["frontmatter"] = fm
        meta["frontmatterLinks"] = _frontmatter_links(fm)
        body_off = m.end()

    masked = _mask_code(text)
    masked = re.sub(r"[^\n]", " ", masked[:body_off]) + masked[body_off:]

    def line_of(off: int) -> int:
        return text.count("\n", 0, off)

    for mt in WIKILINK_RE.finditer(masked):
        inner = mt.group(2).strip()
        if "[[" in inner:
            continue
        p = split_link(inner)
        item = {
            "link": p["href"],
            "original": mt.group(0),
            "displayText": p["title"],
            "line": line_of(mt.start()),
        }
        (meta["embeds"] if mt.group(1) == "!" else meta["links"]).append(item)

    for mt in MDLINK_RE.finditer(masked):
        target = mt.group(3)
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].strip()
        if EXTERNAL_RE.match(target) or target.startswith("#"):
            continue
        try:
            target = unquote(target)
        except Exception:
            pass
        item = {
            "link": _norm(target),
            "original": mt.group(0),
            "displayText": mt.group(2),
            "line": line_of(mt.start()),
        }
        (meta["embeds"] if mt.group(1) == "!" else meta["links"]).append(item)

    for mt in TAG_RE.finditer(masked):
        tag = "#" + mt.group(1)
        if re.fullmatch(r"#\d+", tag):
            continue
        meta["tags"].append({"tag": tag, "line": line_of(mt.start())})

    for mt in HEADING_RE.finditer(masked):
        if mt.start() >= body_off:
            meta["headings"].append(
                {"heading": mt.group(2), "level": len(mt.group(1)), "line": line_of(mt.start())}
            )

    return meta


def note_tags(meta: dict[str, Any]) -> list[str]:
    """Devuelve tags de frontmatter e inline normalizados con `#`, deduplicados."""
    out: list[str] = []
    seen: set[str] = set()

    def _add(tag: str) -> None:
        low = tag.lower()
        if low not in seen:
            seen.add(low)
            out.append(tag)

    fm = meta.get("frontmatter") or {}
    for k, v in fm.items():
        if k.lower() in ("tags", "tag"):
            for t in _as_list(v):
                if t and " " not in t:
                    _add("#" + t.lstrip("#"))
    for t in meta.get("tags", []):
        _add(t["tag"])
    return out


def note_aliases(meta: dict[str, Any]) -> list[str]:
    fm = meta.get("frontmatter") or {}
    for k, v in fm.items():
        if k.lower() in ("aliases", "alias"):
            return [a for a in _as_list(v) if a]
    return []


# ───────────────────────── 2. ÍNDICE Y MOTOR CORTEX ─────────────────────────
@dataclass
class FileInfo:
    path: str
    mtime: float
    size: int
    hash: str = ""
    ext: str = "md"


@dataclass
class Diff:
    nodes_add: dict[str, dict[str, Any]] = field(default_factory=dict)
    nodes_remove: list[str] = field(default_factory=list)
    nodes_update: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges_add: list[dict[str, Any]] = field(default_factory=list)
    edges_remove: list[str] = field(default_factory=list)

    def empty(self) -> bool:
        return not (
            self.nodes_add
            or self.nodes_remove
            or self.nodes_update
            or self.edges_add
            or self.edges_remove
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "nodes": {
                "add": list(self.nodes_add.values()),
                "remove": self.nodes_remove,
                "update": list(self.nodes_update.values()),
            },
            "edges": {
                "add": self.edges_add,
                "remove": self.edges_remove,
            },
        }


def _has_markdown_notes(root: Path, *, ignore_subdirs: set[str] | None = None) -> bool:
    if not root.exists():
        return False
    skip_dirs = ignore_subdirs or set()
    for dp, dn, fn in os.walk(root, followlinks=False):
        dp_path = Path(dp)
        is_top = dp_path == root
        dn[:] = [
            d
            for d in dn
            if not d.startswith(".")
            and d != "node_modules"
            and not (is_top and d in skip_dirs)
            and not (dp_path / d).is_symlink()
        ]
        for fname in fn:
            if not fname.startswith(".") and fname.lower().endswith(".md") and not (dp_path / fname).is_symlink():
                return True
    return False


def _unlink_if_symlink(path: Path) -> None:
    try:
        if path.is_symlink():
            path.unlink()
    except OSError:
        pass


def _copy_legacy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for dp, dn, fn in os.walk(src, followlinks=False):
        dp_path = Path(dp)
        dn[:] = [
            d
            for d in dn
            if not d.startswith(".")
            and d != "node_modules"
            and not (dp_path / d).is_symlink()
        ]
        rel_dir = dp_path.relative_to(src)
        target_dir = dst / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname in fn:
            if fname.startswith("."):
                continue
            src_file = dp_path / fname
            if src_file.is_symlink():
                continue
            dst_file = target_dir / fname
            if not dst_file.exists():
                try:
                    shutil.copy2(src_file, dst_file)
                except OSError:
                    pass


def _sync_workspace_into_cortex(cortex_root: Path) -> None:
    target_ws = cortex_root / "workspace"
    home_ws = Path.home() / ".mykos" / "workspace"
    legacy_ws_link_name = "Cerebro_" + "Obsidian"

    _unlink_if_symlink(home_ws / legacy_ws_link_name)
    if home_ws.is_dir() and not home_ws.is_symlink():
        try:
            if not target_ws.exists() and not target_ws.is_symlink():
                shutil.move(str(home_ws), str(target_ws))
                home_ws.symlink_to(target_ws)
            elif target_ws.is_dir() and not target_ws.is_symlink() and not any(target_ws.iterdir()):
                target_ws.rmdir()
                shutil.move(str(home_ws), str(target_ws))
                home_ws.symlink_to(target_ws)
        except OSError:
            pass
    elif not home_ws.exists() and not home_ws.is_symlink():
        target_ws.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            home_ws.symlink_to(target_ws)
        except OSError:
            pass
    _unlink_if_symlink(target_ws / legacy_ws_link_name)


def _migrate_legacy_vault(target: Path) -> None:
    """Migra bóveda y workspace previos hacia la bóveda Cortex nativa en `~/.mykos/cortex`."""
    target.mkdir(parents=True, exist_ok=True)
    legacy_ws_link = Path.home() / ".mykos" / "workspace" / ("Cerebro_" + "Obsidian")
    legacy_docs_vault = Path.home() / "Documentos" / ("Obsidian" + " Vault")

    legacy_sources: list[Path] = []
    if legacy_ws_link.is_symlink():
        try:
            resolved_legacy = legacy_ws_link.resolve()
            if resolved_legacy.is_dir():
                legacy_sources.append(resolved_legacy)
        except OSError:
            pass
    elif legacy_ws_link.is_dir():
        legacy_sources.append(legacy_ws_link)
    if legacy_docs_vault.is_dir():
        legacy_sources.append(legacy_docs_vault)

    if not _has_markdown_notes(target, ignore_subdirs={"workspace"}):
        for src in legacy_sources:
            if src != target.resolve() and _has_markdown_notes(src):
                _copy_legacy_tree(src, target)
                break

    _unlink_if_symlink(target / "01 - Proyectos MyKOS" / "Workspace (Archivos MyKOS)")
    _sync_workspace_into_cortex(target)


def resolve_vault_path(vault_path: str | Path | None = None) -> Path:
    """Resuelve la ruta de la bóveda: explícita -> env -> default -> fallback."""
    if vault_path is not None and str(vault_path).strip():
        return Path(vault_path).expanduser().resolve()

    env_vault = os.environ.get("MYKOS_CORTEX_VAULT") or os.environ.get("MYKOS_BRAIN_VAULT")
    if env_vault and env_vault.strip():
        return Path(env_vault).expanduser().resolve()

    if DEFAULT_VAULT_PATH == _OFFICIAL_DEFAULT_VAULT:
        _migrate_legacy_vault(DEFAULT_VAULT_PATH)
        return DEFAULT_VAULT_PATH.resolve()

    if DEFAULT_VAULT_PATH.exists():
        return DEFAULT_VAULT_PATH.resolve()
    if FALLBACK_VAULT_PATH.exists():
        return FALLBACK_VAULT_PATH.resolve()
    return DEFAULT_VAULT_PATH


class CortexEngine:
    """Motor principal de indexación, grafo y gestión de notas para MyKOS Cortex."""

    ATTACH_EXT = {"png", "jpg", "jpeg", "gif", "svg", "webp", "pdf", "mp3", "wav", "mp4", "webm", "canvas"}

    def __init__(
        self,
        vault_path: str | Path | None = None,
        ignore: tuple[str, ...] = (".cortex", ".git", ".trash", "node_modules"),
        auto_build: bool = True,
    ):
        self.root: Path = resolve_vault_path(vault_path)
        self.ignore = ignore
        self._lock = threading.RLock()
        self.files: dict[str, FileInfo] = {}
        self.meta: dict[str, dict[str, Any]] = {}
        self.by_name: dict[str, list[str]] = {}
        self.resolved: dict[str, dict[str, int]] = {}
        self.unresolved: dict[str, dict[str, int]] = {}
        self.backlinks: dict[str, set[str]] = {}
        self.rev: int = 0
        self._graph_cache: dict[str, dict[str, Any]] = {}
        self._last_build_ms: float = 0.0
        self._last_sync_time: float = time.perf_counter()

        if auto_build:
            self.root.mkdir(parents=True, exist_ok=True)
            self._ensure_starter_vault()
            self.full_build()

    def _ensure_starter_vault(self) -> None:
        """Inicializa la estructura base de memoria MyKOS si la bóveda Cortex aún no tiene notas."""
        try:
            official = _OFFICIAL_DEFAULT_VAULT.resolve()
        except OSError:
            official = _OFFICIAL_DEFAULT_VAULT
        is_official = self.root == official
        if is_official:
            (self.root / "workspace").mkdir(parents=True, exist_ok=True)
            repo_docs = Path(__file__).resolve().parents[2] / "docs"
            docs_link = self.root / "docs"
            if repo_docs.is_dir() and not docs_link.exists() and not docs_link.is_symlink():
                try:
                    docs_link.symlink_to(repo_docs)
                except OSError:
                    pass

        ignore_subdirs = {"workspace"} if is_official else set()
        if _has_markdown_notes(self.root, ignore_subdirs=ignore_subdirs):
            return

        starter_notes: dict[str, str] = {
            "00 - Centro de Mando/00 - Dashboard MyKOS.md": (
                "---\n"
                "aliases: [Dashboard, Inicio, Home]\n"
                "tags: [moc, dashboard, mykos]\n"
                "---\n\n"
                "# Centro de Mando — MyKOS Cortex\n\n"
                "Bóveda nativa integrada en `~/.mykos/cortex` (con `workspace/` vivo incluido).\n\n"
                "## Mapa de Contenidos\n"
                "- [[00 - Preferencias y Memoria]]\n"
                "- [[01 - Arquitectura MyKOS]]\n"
                "- [[Bitacora Inicial]]\n"
            ),
            "00 - Centro de Mando/00 - Preferencias y Memoria.md": (
                "---\n"
                "aliases: [Preferencias, Memoria, Perfil del Usuario]\n"
                "tags: [memoria, preferencias, perfil, mykos]\n"
                "---\n\n"
                "# Preferencias y Memoria Persistente\n\n"
                "Aquí guarda MyKOS tus preferencias de trato, idioma, proyectos y recuerdos clave.\n\n"
                "- Plataforma soberana ejecutada localmente (GPU CUDA, Ollama o proveedores configurados en MyKOS).\n"
                "- Vuelve al índice en [[00 - Dashboard MyKOS]].\n"
                "- Documentación técnica del sistema en [[01 - Arquitectura MyKOS]].\n"
            ),
            "01 - Proyectos MyKOS/01 - Arquitectura MyKOS.md": (
                "---\n"
                "tags: [proyecto, arquitectura, mykos]\n"
                "---\n\n"
                "# Arquitectura MyKOS\n\n"
                "- Gateway HTTP y políticas en Node.js (`gateway/app/gateway-plugin/mykos-ui`).\n"
                "- Worker Python de herramientas y memoria (`gateway/app/server.py`).\n"
                "- Documentación técnica del repositorio disponible en `docs/`.\n"
                "- Índice general: [[00 - Dashboard MyKOS]] · Registro inicial: [[Bitacora Inicial]].\n"
            ),
            "04 - Bitácora y Diario/Bitacora Inicial.md": (
                "---\n"
                "tags: [bitacora, diario, mykos]\n"
                "---\n\n"
                "# Bitácora Inicial de Cortex\n\n"
                "Bóveda inicializada automáticamente por MyKOS Cortex para seguimiento diario, "
                "investigaciones en `workspace/` y memoria viva enlazada.\n\n"
                "- Volver a [[00 - Dashboard MyKOS]].\n"
                "- Ver [[00 - Preferencias y Memoria]] y [[01 - Arquitectura MyKOS]].\n"
            ),
        }
        for rel_path, content in starter_notes.items():
            dst = self.root / rel_path
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(content, encoding="utf-8")

    # ---- escaneo y utilidades internas
    def _scan(self) -> dict[str, FileInfo]:
        out: dict[str, FileInfo] = {}
        if not self.root.exists():
            return out
        for dp, dn, fn in os.walk(self.root, followlinks=False):
            dp_path = Path(dp)
            dn[:] = [
                d
                for d in dn
                if d not in self.ignore
                and not d.startswith(".")
                and not (dp_path / d).is_symlink()
            ]
            for f in fn:
                if f.startswith("."):
                    continue
                p = dp_path / f
                if p.is_symlink():
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                rel = p.relative_to(self.root).as_posix()
                out[rel] = FileInfo(
                    path=rel,
                    mtime=st.st_mtime,
                    size=st.st_size,
                    ext=p.suffix.lstrip(".").lower(),
                )
        return out

    def _safe_rel(self, relative_path: str | Path, *, ensure_md: bool = False) -> str:
        raw = str(relative_path).strip().replace("\\", "/")
        if not raw:
            raise ValueError("La ruta de la nota no puede estar vacía")
        candidate = Path(raw)
        if not candidate.is_absolute():
            rel_candidate = raw.lstrip("/")
            if ensure_md and not rel_candidate.lower().endswith(".md") and Path(rel_candidate).suffix == "":
                rel_candidate = f"{rel_candidate}.md"
            target = (self.root / rel_candidate).resolve()
        else:
            target = candidate.resolve()

        if not target.is_relative_to(self.root) or target == self.root:
            raise ValueError(f"Ruta fuera de la bóveda: {relative_path}")

        rel = target.relative_to(self.root).as_posix()
        first_part = rel.split("/", 1)[0]
        if first_part in self.ignore or first_part.startswith("."):
            raise ValueError(f"Ruta reservada/ignorada en la bóveda: {rel}")
        return rel

    def _add_lookup(self, path: str) -> None:
        self.by_name.setdefault(os.path.basename(path).lower(), []).append(path)

    def _del_lookup(self, path: str) -> None:
        k = os.path.basename(path).lower()
        cands = self.by_name.get(k)
        if cands and path in cands:
            cands.remove(path)
            if not cands:
                del self.by_name[k]

    def _meta(self, path: str) -> dict[str, Any] | None:
        fi = self.files.get(path)
        return self.meta.get(fi.hash) if fi and fi.hash else None

    # ---- resolución de enlaces (getLinkpathDest)
    def resolve_link(self, link: str, source: str) -> str | None:
        link = link.strip()
        if link == "" and source:
            return source
        if link.startswith("/"):
            link = link[1:]
        n = link.lower()
        cands = None
        if "." in os.path.basename(n):
            cands = self.by_name.get(os.path.basename(n))
        if not cands:
            n = (link + ".md").lower()
            cands = self.by_name.get(os.path.basename(n))
        if not cands:
            return None
        if os.path.basename(n) == n and len(cands) == 1:
            return cands[0]
        src_dir = os.path.dirname(source).lower()
        if n.startswith("./") or n.startswith("../"):
            base = src_dir
            while n.startswith("../"):
                n, base = n[3:], os.path.dirname(base)
            n = n[2:] if n.startswith("./") else n
            n = (base + "/" + n) if base else n
        for c in cands:
            if c.lower() == n:
                return c
        suffix = [c for c in cands if c.lower().endswith(n)]
        same = sorted((c for c in suffix if c.lower().startswith(src_dir)), key=len)
        other = sorted((c for c in suffix if not c.lower().startswith(src_dir)), key=len)
        res = same + other
        return res[0] if res else None

    def _refs(self, path: str):
        m = self._meta(path) or {}
        for l in m.get("frontmatterLinks", []) + m.get("links", []) + m.get("embeds", []):
            yield l

    def resolve_file(self, path: str) -> None:
        """Calcula resolved/unresolved y actualiza backlinks de un fichero."""
        r: dict[str, int] = {}
        u: dict[str, int] = {}
        for l in self._refs(path):
            tgt = self.resolve_link(strip_subpath(l["link"]), path)
            if tgt:
                r[tgt] = r.get(tgt, 0) + 1
            else:
                key = strip_subpath(l["link"])
                key = key[:-3] if key.lower().endswith(".md") else key
                u[key] = u.get(key, 0) + 1
        for old in self.resolved.get(path, {}):
            self.backlinks.get(old, set()).discard(path)
        for new in r:
            self.backlinks.setdefault(new, set()).add(path)
        self.resolved[path], self.unresolved[path] = r, u

    def update_related(self, names: list[str]) -> list[str]:
        """Re-resuelve solo ficheros cuyos enlaces tocan los nombres indicados."""
        low_names = [n.lower() for n in names]
        stems = [n[:-3] for n in low_names if n.endswith(".md")] + low_names
        touched: list[str] = []
        for p in list(self.files):
            res = self.resolved.get(p, {})
            hit = any(os.path.basename(k).lower() in low_names for k in res) or any(
                os.path.basename(k).lower() in stems for k in self.unresolved.get(p, {})
            )
            if hit:
                touched.append(p)
        return touched

    def _parse_into(self, path: str) -> bool:
        fi = self.files[path]
        data = (self.root / path).read_bytes()
        h = hashlib.sha256(data).hexdigest()
        changed = h != fi.hash
        fi.hash = h
        if h not in self.meta:
            self.meta[h] = parse_note(data.decode("utf-8", "replace"))
        return changed

    def full_build(self) -> dict[str, Any]:
        """Reconstruye todo el índice de la bóveda desde disco (sin seguir symlinks)."""
        with self._lock:
            t0 = time.perf_counter()
            self.files = self._scan()
            self.by_name.clear()
            self.resolved.clear()
            self.unresolved.clear()
            self.backlinks.clear()
            for p in self.files:
                self._add_lookup(p)
            for p, fi in self.files.items():
                if fi.ext == "md":
                    self._parse_into(p)
            for p, fi in self.files.items():
                if fi.ext == "md":
                    self.resolve_file(p)
            self._graph_cache = self.build_graph()["nodes_by_id"]
            self.rev += 1
            self._last_build_ms = round((time.perf_counter() - t0) * 1000, 2)
            self._last_sync_time = time.perf_counter()
            return {"files": len(self.files), "ms": self._last_build_ms, "rev": self.rev}

    # ---- sincronización incremental
    def apply_fs_event(
        self,
        kind: str,
        path: str,
        old_path: str | None = None,
        *,
        force: bool = False,
    ) -> Diff:
        """Aplica evento `created|modified|deleted|moved` y devuelve el delta de grafo."""
        with self._lock:
            rel = (
                Path(path).as_posix()
                if not os.path.isabs(path)
                else Path(path).resolve().relative_to(self.root).as_posix()
            )
            names: list[str] = []
            to_resolve: set[str] = set()

            if kind in ("created", "modified"):
                full_p = self.root / rel
                if not full_p.exists() or full_p.is_symlink():
                    return Diff()
                st = full_p.stat()
                existed = rel in self.files
                fi = self.files.get(rel) or FileInfo(
                    rel, st.st_mtime, st.st_size, ext=Path(rel).suffix.lstrip(".").lower()
                )
                if (
                    not force
                    and existed
                    and fi.mtime == st.st_mtime
                    and fi.size == st.st_size
                    and kind == "modified"
                ):
                    return Diff()
                fi.mtime, fi.size = st.st_mtime, st.st_size
                self.files[rel] = fi
                if not existed:
                    self._add_lookup(rel)
                    names.append(os.path.basename(rel))
                if fi.ext == "md":
                    self._parse_into(rel)
                    to_resolve.add(rel)

            elif kind == "deleted":
                if rel in self.files:
                    self._del_lookup(rel)
                    names.append(os.path.basename(rel))
                    for dst in self.resolved.pop(rel, {}):
                        self.backlinks.get(dst, set()).discard(rel)
                    self.unresolved.pop(rel, None)
                    del self.files[rel]

            elif kind == "moved" and old_path:
                old = Path(old_path).as_posix()
                fi = self.files.pop(old, None)
                if fi:
                    self._del_lookup(old)
                    fi.path = rel
                    self.files[rel] = fi
                    self._add_lookup(rel)
                    for k in ("resolved", "unresolved"):
                        d = getattr(self, k)
                        if old in d:
                            d[rel] = d.pop(old)
                    for s in self.backlinks.values():
                        if old in s:
                            s.discard(old)
                            s.add(rel)
                    if old in self.backlinks:
                        self.backlinks[rel] = self.backlinks.pop(old)
                    names.extend([os.path.basename(old), os.path.basename(rel)])
                    to_resolve.add(rel)

            if names:
                to_resolve.update(self.update_related(names))
            for p in to_resolve:
                if p in self.files and self.files[p].ext == "md":
                    self.resolve_file(p)
            return self._diff_graph()

    def sync(self) -> Diff:
        """Escanea el sistema de ficheros y sincroniza altas, bajas y modificaciones externas."""
        with self._lock:
            self._last_sync_time = time.perf_counter()
            current = self._scan()
            diff = Diff()
            # Ficheros eliminados
            for p in list(self.files):
                if p not in current:
                    d = self.apply_fs_event("deleted", p)
                    diff.nodes_remove.extend(d.nodes_remove)
                    diff.edges_remove.extend(d.edges_remove)
            # Ficheros creados o modificados
            for p, cur_fi in current.items():
                old_fi = self.files.get(p)
                if old_fi is None:
                    d = self.apply_fs_event("created", p)
                    diff.nodes_add.update(d.nodes_add)
                    diff.edges_add.extend(d.edges_add)
                elif old_fi.mtime != cur_fi.mtime or old_fi.size != cur_fi.size:
                    d = self.apply_fs_event("modified", p)
                    diff.nodes_update.update(d.nodes_update)
                    diff.edges_add.extend(d.edges_add)
                    diff.edges_remove.extend(d.edges_remove)
            return diff

    # ---- construcción y contrato del grafo
    def build_graph(
        self,
        *,
        show_tags: bool = False,
        show_attachments: bool = False,
        hide_unresolved: bool = False,
        show_orphans: bool = True,
        path_filter: Callable[[str, str], bool] | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Construye la estructura `{nodes_by_id: {id: {type, links}}}`."""
        with self._lock:
            nodes: dict[str, dict[str, Any]] = {}
            keep = path_filter or (lambda _p, _t: True)
            tag_canon: dict[str, str] = {}

            for p, fi in self.files.items():
                is_att = fi.ext != "md"
                if is_att and not show_attachments:
                    continue
                ntype = "attachment" if is_att else "note"
                if not keep(p, ntype):
                    continue
                n = nodes.setdefault(p, {"type": ntype, "links": {}})
                for dst in self.resolved.get(p, {}):
                    dst_att = self.files[dst].ext != "md" if dst in self.files else False
                    if dst_att and not show_attachments:
                        continue
                    if not keep(dst, "attachment" if dst_att else "note"):
                        continue
                    n["links"][dst] = True
                if not hide_unresolved:
                    for g in self.unresolved.get(p, {}):
                        if keep(g, "unresolved"):
                            n["links"][g] = True
                            nodes.setdefault(g, {"type": "unresolved", "links": {}})
                if show_tags:
                    for t in note_tags(self._meta(p) or {}):
                        canon = tag_canon.setdefault(t.lower(), t)
                        n["links"][canon] = True
                        nodes.setdefault(canon, {"type": "tag", "links": {}})

            if not show_orphans:
                incoming = {d for s, nd in nodes.items() for d in nd["links"] if d != s}
                for s in list(nodes):
                    has_out = any(d in nodes and d != s for d in nodes[s]["links"])
                    if not has_out and s not in incoming:
                        del nodes[s]

            return {"nodes_by_id": nodes}

    @staticmethod
    def weights(nodes: dict[str, dict[str, Any]]) -> dict[str, int]:
        w = {i: 0 for i in nodes}
        for s, n in nodes.items():
            for d in n["links"]:
                if d in nodes:
                    w[s] += 1
                    w[d] += 1
        return w

    @staticmethod
    def public_id(raw: str, ntype: str) -> str:
        return {"note": "n:", "attachment": "a:", "unresolved": "u:", "tag": "t:"}[ntype] + raw

    def _type_of(self, raw: str) -> str:
        if raw in self.files:
            return "note" if self.files[raw].ext == "md" else "attachment"
        if raw.startswith("#"):
            return "tag"
        return "unresolved"

    def _node_json(self, raw_id: str, n: dict[str, Any], weight: int) -> dict[str, Any]:
        t = n["type"]
        meta = self._meta(raw_id) or {} if t == "note" else {}
        label = (
            (os.path.basename(raw_id)[:-3] if t == "note" else os.path.basename(raw_id))
            if t in ("note", "attachment")
            else raw_id
        )
        return {
            "id": self.public_id(raw_id, t),
            "type": t,
            "label": label,
            "path": raw_id if t in ("note", "attachment") else None,
            "folder": os.path.dirname(raw_id) if t in ("note", "attachment") else None,
            "weight": weight,
            "size": round(max(8, min((weight + 1) ** 0.5 * 3, 30)), 2),
            "tags": note_tags(meta) if t == "note" else [],
            "aliases": note_aliases(meta) if t == "note" else [],
            "mtime": self.files[raw_id].mtime if raw_id in self.files else None,
        }

    def _edge_json(self, s: str, d: str) -> dict[str, Any]:
        st = self._type_of(s)
        dt = self._type_of(d)
        sid, did = self.public_id(s, st), self.public_id(d, dt)
        cnt = self.resolved.get(s, {}).get(d) or self.unresolved.get(s, {}).get(d, 1)
        kind = {"unresolved": "unresolved", "tag": "tag"}.get(dt, "link")
        return {"id": f"{sid}>{did}", "source": sid, "target": did, "kind": kind, "count": cnt}

    def _diff_graph(self, **opts: Any) -> Diff:
        new = self.build_graph(**opts)["nodes_by_id"]
        old = self._graph_cache
        wn, wo = self.weights(new), self.weights(old)
        d = Diff()
        for i, n in new.items():
            if i not in old:
                j = self._node_json(i, n, wn[i])
                d.nodes_add[j["id"]] = j
            elif wn[i] != wo.get(i) or old[i].get("type") != n["type"]:
                j = self._node_json(i, n, wn[i])
                d.nodes_update[j["id"]] = j
        for i, n in old.items():
            if i not in new:
                d.nodes_remove.append(self.public_id(i, n["type"]))
        oe = {(s, t) for s, n in old.items() for t in n["links"] if t in old}
        ne = {(s, t) for s, n in new.items() for t in n["links"] if t in new}
        for s, t in ne - oe:
            d.edges_add.append(self._edge_json(s, t))
        for s, t in oe - ne:
            d.edges_remove.append(
                f"{self.public_id(s, old[s]['type'])}>{self.public_id(t, old[t]['type'])}"
            )
        self._graph_cache = new
        if not d.empty():
            self.rev += 1
        return d

    # ───────────────────────── 3. API PÚBLICA REQUERIDA ─────────────────────────
    def get_graph(
        self,
        *,
        show_tags: bool = False,
        show_attachments: bool = False,
        hide_unresolved: bool = False,
        show_orphans: bool = True,
        path_filter: Callable[[str, str], bool] | None = None,
    ) -> dict[str, Any]:
        """Devuelve `{nodes, edges, stats, rev}` listo para serializar a JSON."""
        with self._lock:
            if time.perf_counter() - self._last_sync_time > 1.0:
                self.sync()
            g = self.build_graph(
                show_tags=show_tags,
                show_attachments=show_attachments,
                hide_unresolved=hide_unresolved,
                show_orphans=show_orphans,
                path_filter=path_filter,
            )["nodes_by_id"]
            w = self.weights(g)
            nodes: list[dict[str, Any]] = []
            edges: list[dict[str, Any]] = []
            for i, n in g.items():
                nodes.append(self._node_json(i, n, w[i]))
                for d in n["links"]:
                    if d in g:
                        edges.append(self._edge_json(i, d))
            return {
                "rev": self.rev,
                "nodes": nodes,
                "edges": edges,
                "stats": {
                    "notes": sum(1 for n in nodes if n["type"] == "note"),
                    "ghosts": sum(1 for n in nodes if n["type"] == "unresolved"),
                    "tags": sum(1 for n in nodes if n["type"] == "tag"),
                    "attachments": sum(1 for n in nodes if n["type"] == "attachment"),
                    "edges": len(edges),
                    "files": len(self.files),
                },
            }

    def get_note(self, relative_path: str) -> dict[str, Any]:
        """Devuelve `{path, content, frontmatter, tags, links, backlinks}` de una nota."""
        with self._lock:
            rel = self._safe_rel(relative_path)
            if rel not in self.files and not rel.lower().endswith(".md") and Path(rel).suffix == "":
                md_rel = f"{rel}.md"
                if md_rel in self.files:
                    rel = md_rel
            full_p = self.root / rel
            if not full_p.is_file() or full_p.is_symlink():
                raise FileNotFoundError(f"Nota no encontrada: {relative_path}")

            if rel in self.files:
                try:
                    st = full_p.stat()
                    if st.st_mtime != self.files[rel].mtime or st.st_size != self.files[rel].size:
                        self.apply_fs_event("modified", rel, force=True)
                except OSError:
                    pass
            else:
                self.apply_fs_event("created", rel)

            content = full_p.read_text("utf-8", "replace")
            meta = self._meta(rel) or parse_note(content)
            fm = _json_safe(meta.get("frontmatter") or {})
            tags = note_tags(meta)

            links: list[dict[str, Any]] = []
            for ref in self._refs(rel):
                raw_link = ref["link"]
                tgt = self.resolve_link(strip_subpath(raw_link), rel)
                if tgt:
                    tgt_type = self._type_of(tgt)
                    tgt_id = self.public_id(tgt, tgt_type)
                else:
                    ghost = strip_subpath(raw_link)
                    ghost = ghost[:-3] if ghost.lower().endswith(".md") else ghost
                    tgt_id = self.public_id(ghost, "unresolved")
                links.append(
                    {
                        "link": raw_link,
                        "target": tgt_id,
                        "path": tgt,
                        "displayText": ref.get("displayText", raw_link),
                        "line": ref.get("line"),
                        "resolved": tgt is not None,
                    }
                )

            backlinks = self.backlinks_of(rel)
            fi = self.files.get(rel)
            return {
                "path": rel,
                "title": Path(rel).stem,
                "content": content,
                "frontmatter": fm,
                "tags": tags,
                "aliases": note_aliases(meta),
                "headings": meta.get("headings", []),
                "links": links,
                "backlinks": backlinks,
                "hash": fi.hash if fi else hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "mtime": fi.mtime if fi else full_p.stat().st_mtime,
            }

    def save_note(self, relative_path: str, content: str) -> dict[str, Any]:
        """Guarda el archivo `.md` en la bóveda y actualiza la caché incrementalmente."""
        with self._lock:
            rel = self._safe_rel(relative_path, ensure_md=True)
            full_p = self.root / rel
            existed = rel in self.files
            full_p.parent.mkdir(parents=True, exist_ok=True)
            full_p.write_text(content, "utf-8")
            diff = self.apply_fs_event("modified" if existed else "created", rel, force=True)
            fi = self.files[rel]
            return {
                "ok": True,
                "path": rel,
                "hash": fi.hash,
                "mtime": fi.mtime,
                "rev": self.rev,
                "diff": diff.to_json(),
            }

    def search_notes(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Busca notas por coincidencia en título, aliases, tags o contenido."""
        q = (query or "").strip()
        if not q:
            return []
        q_low = q.lower()
        q_tag = q_low.lstrip("#")
        terms = [t for t in q_low.split() if t]

        with self._lock:
            if time.perf_counter() - self._last_sync_time > 1.0:
                self.sync()
            results: list[dict[str, Any]] = []
            for p, fi in self.files.items():
                if fi.ext != "md":
                    continue
                title = Path(p).stem
                title_low = title.lower()
                path_low = p.lower()
                meta = self._meta(p) or {}
                tags = note_tags(meta)
                aliases = note_aliases(meta)

                score = 0
                matches: list[str] = []

                if title_low == q_low:
                    score += 120
                    matches.append("title")
                elif q_low in title_low or q_low in path_low:
                    score += 70
                    matches.append("title")
                elif len(terms) > 1 and all(t in title_low or t in path_low for t in terms):
                    score += 55
                    matches.append("title")

                if any(q_low in a.lower() for a in aliases):
                    score += 50
                    matches.append("aliases")

                if any(q_tag in t.lower().lstrip("#") for t in tags):
                    score += 45
                    matches.append("tags")

                snippet = ""
                try:
                    text = (self.root / p).read_text("utf-8", "replace")
                except OSError:
                    text = ""
                text_low = text.lower()
                idx = text_low.find(q_low)
                if idx != -1:
                    score += 25
                    matches.append("content")
                    start = max(0, idx - 50)
                    end = min(len(text), idx + len(q) + 70)
                    snippet = text[start:end].replace("\n", " ").strip()
                elif len(terms) > 1 and all(t in text_low for t in terms):
                    score += 15
                    matches.append("content")
                    first_idx = min(text_low.find(t) for t in terms)
                    start = max(0, first_idx - 50)
                    end = min(len(text), first_idx + 120)
                    snippet = text[start:end].replace("\n", " ").strip()

                if score > 0:
                    results.append(
                        {
                            "path": p,
                            "id": self.public_id(p, "note"),
                            "title": title,
                            "tags": tags,
                            "aliases": aliases,
                            "score": score,
                            "matches": matches,
                            "snippet": snippet,
                            "mtime": fi.mtime,
                        }
                    )

            results.sort(key=lambda item: (-item["score"], item["title"].lower()))
            return results[: max(1, limit)]

    # ---- consultas auxiliares
    def backlinks_of(self, path: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "source": s,
                    "id": self.public_id(s, "note"),
                    "count": self.resolved.get(s, {}).get(path, 0),
                }
                for s in sorted(self.backlinks.get(path, ()))
            ]

    def unlinked_mentions(self, path: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            names = [Path(path).stem] + note_aliases(self._meta(path) or {})
            names = [n for n in names if n]
            if not names:
                return []
            pat = re.compile(
                "|".join(r"(?<![\w\[])" + re.escape(n) + r"(?![\w\]])" for n in names),
                re.I,
            )
            out: list[dict[str, Any]] = []
            for p, fi in self.files.items():
                if fi.ext != "md" or p == path or path in self.resolved.get(p, {}):
                    continue
                try:
                    txt = _mask_code((self.root / p).read_text("utf-8", "replace"))
                except OSError:
                    continue
                m = pat.search(txt)
                if m:
                    out.append(
                        {
                            "source": p,
                            "line": txt.count("\n", 0, m.start()),
                            "snippet": txt[max(0, m.start() - 40) : m.end() + 40].replace("\n", " "),
                        }
                    )
                    if len(out) >= limit:
                        break
            return out

    def local_graph(
        self,
        path: str,
        jumps: int = 1,
        forelinks: bool = True,
        backlinks: bool = True,
        interlinks: bool = False,
        **opts: Any,
    ) -> dict[str, Any]:
        with self._lock:
            if time.perf_counter() - self._last_sync_time > 1.0:
                self.sync()
            g = self.build_graph(**opts)["nodes_by_id"]
            if path not in g:
                return {"nodes_by_id": {path: {"type": "note", "links": {}}}, "weights": {path: 30}}
            keep = {path: {"type": g[path]["type"], "links": {}}}
            weights = {path: 30.0}
            step = 30.0 / max(1, jumps)
            for j in range(max(1, jumps)):
                add: dict[str, dict[str, Any]] = {}
                for s, n in g.items():
                    if n["type"] == "tag":
                        continue
                    for d in n["links"]:
                        if forelinks and s in keep and d not in keep and keep[s]["type"] != "tag":
                            add.setdefault(d, {"type": g[d]["type"], "links": {}})
                            keep[s]["links"][d] = True
                        elif backlinks and d in keep and s not in keep and keep[d]["type"] != "tag":
                            add.setdefault(s, {"type": g[s]["type"], "links": {}})
                            add[s]["links"][d] = True
                for k, v in add.items():
                    keep[k] = v
                    weights[k] = 30.0 - step * (j + 1)
            if interlinks:
                for k in keep:
                    keep[k] = g[k]
            return {"nodes_by_id": keep, "weights": weights}


# ───────────────────────── 4. SINGLETON ─────────────────────────
_SINGLETON_LOCK = threading.Lock()
_CORTEX_INSTANCE: CortexEngine | None = None


def get_cortex(vault_path: str | Path | None = None) -> CortexEngine:
    """Devuelve la instancia singleton de `CortexEngine`."""
    global _CORTEX_INSTANCE
    with _SINGLETON_LOCK:
        if _CORTEX_INSTANCE is None:
            _CORTEX_INSTANCE = CortexEngine(vault_path=vault_path)
        elif vault_path is not None:
            requested = resolve_vault_path(vault_path)
            if requested != _CORTEX_INSTANCE.root:
                _CORTEX_INSTANCE = CortexEngine(vault_path=requested)
        return _CORTEX_INSTANCE


__all__ = [
    "CortexEngine",
    "DEFAULT_VAULT_PATH",
    "FALLBACK_VAULT_PATH",
    "Diff",
    "FileInfo",
    "get_cortex",
    "note_aliases",
    "note_tags",
    "parse_note",
    "resolve_vault_path",
    "split_link",
    "strip_subpath",
]
