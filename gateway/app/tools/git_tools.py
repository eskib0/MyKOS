"""Herramientas de inspección y operaciones Git de MyKOS.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base import (
    GIT_LOCK,
    GIT_MAX_COMMIT_MESSAGE_CHARS,
    GIT_MAX_LOG_ENTRIES,
    GIT_MAX_OUTPUT_CHARS,
    GIT_MAX_PATHS,
    GIT_REMOTE_TIMEOUT_SECONDS,
    ToolError,
    _relative_label,
    _resolve_project_path,
    _resolve_root,
)

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
            [git, "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "diff.external=", "--literal-pathspecs", *arguments],
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
        diff_targets.append(["diff", "--raw", "--no-ext-diff", "--no-textconv", "--no-color", head, "--"])
    else:
        diff_targets.append(["diff", "--raw", "--no-ext-diff", "--no-textconv", "--no-color", "--"])
    diff_targets.append(["diff", "--raw", "--cached", "--no-ext-diff", "--no-textconv", "--"])
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
    arguments = ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--stat"]
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
    git_arguments = ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--unified=3"]
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
        cached = _run_git(root_path, ["diff", "--cached", "--quiet", "--no-ext-diff", "--no-textconv", "--"], timeout=20)
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

        cached = _run_git(root_path, ["diff", "--cached", "--quiet", "--no-ext-diff", "--no-textconv", "--"], timeout=20)
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


