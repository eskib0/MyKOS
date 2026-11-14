"""Cliente CLI oficial para el motor Multi-Agente MyKOS Swarm."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _state_dir() -> Path:
    raw = os.environ.get("MYKOS_GATEWAY_STATE_DIR", "").strip()
    return Path(raw) if raw else (Path.home() / ".mykos" / "gateway-state")


def _config_file() -> Path:
    raw = os.environ.get("MYKOS_GATEWAY_CONFIG", "").strip()
    return Path(raw) if raw else (_state_dir() / "mykos-gateway.json")


def _real_user_home() -> Path | None:
    try:
        import pwd

        pw_dir = pwd.getpwuid(os.getuid()).pw_dir
        if pw_dir:
            return Path(pw_dir)
    except Exception:
        pass
    return None


def _load_control_target() -> tuple[str, str]:
    backend_url = os.environ.get("MYKOS_CONTROL_URL", "").strip()
    token = os.environ.get("MYKOS_CONTROL_TOKEN", "").strip()
    explicit_state = bool(os.environ.get("MYKOS_GATEWAY_STATE_DIR", "").strip())
    explicit_cfg = bool(os.environ.get("MYKOS_GATEWAY_CONFIG", "").strip())
    real_home = _real_user_home() if not explicit_state else None

    cfg_candidates = [_config_file()]
    if not explicit_cfg and not explicit_state and real_home is not None:
        cfg_candidates.append(real_home / ".mykos" / "gateway-state" / "mykos-gateway.json")

    for cfg_path in cfg_candidates:
        if not cfg_path.is_file():
            continue
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            plugin_cfg = (
                cfg.get("plugins", {})
                .get("entries", {})
                .get("mykos-ui", {})
                .get("config", {})
            )
            if not backend_url:
                url = str((plugin_cfg.get("backend") or {}).get("url") or "").strip()
                if url:
                    backend_url = url
            if not token:
                tok = str((plugin_cfg.get("control") or {}).get("token") or "").strip()
                if tok:
                    token = tok
            if backend_url and token:
                break
        except Exception:
            pass

    if not token:
        candidates = [_state_dir() / "control.token"]
        if not explicit_state:
            candidates.extend([
                Path.home() / ".mykos" / "gateway-state" / "control.token",
                Path.home() / ".mykos" / "control.token",
            ])
            if real_home is not None:
                candidates.extend([
                    real_home / ".mykos" / "gateway-state" / "control.token",
                    real_home / ".mykos" / "control.token",
                ])
        for candidate in candidates:
            try:
                if candidate.is_file():
                    tok = candidate.read_text(encoding="utf-8").strip()
                    if tok:
                        token = tok
                        break
            except Exception:
                pass

    return (backend_url or "http://127.0.0.1:3211").rstrip("/"), token


def _control_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 15.0,
) -> tuple[bool, dict[str, Any] | None, str]:
    backend_url, token = _load_control_target()
    if not token:
        return False, None, "no-token"

    headers = {
        "Accept": "application/json",
        "X-MyKOS-Control-Token": token,
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        f"{backend_url}{path}",
        data=data,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            return True, parsed if isinstance(parsed, dict) else {"ok": True, "data": parsed}, ""
    except urllib.error.HTTPError as exc:
        body = exc.read(65_536).decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"ok": False, "error": body or f"HTTP {exc.code}"}
        err = str((parsed or {}).get("error") or (parsed or {}).get("message") or f"HTTP {exc.code}")
        return True, parsed if isinstance(parsed, dict) else {"ok": False, "error": err}, err
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, None, str(exc)


def _format_message_block(msg: dict[str, Any]) -> str:
    seq = msg.get("seq", "?")
    agent = msg.get("agent", "?")
    role = str(msg.get("role") or "").strip()
    model = str(msg.get("model") or "").strip()
    tools = [str(t) for t in (msg.get("tools_used") or []) if str(t).strip()]
    dur = float(msg.get("duration_seconds") or 0.0)
    meta_parts = []
    if role:
        meta_parts.append(role)
    if model:
        meta_parts.append(f"modelo={model}")
    if dur > 0:
        meta_parts.append(f"{dur:.1f}s")
    if tools:
        meta_parts.append(f"herramientas={','.join(tools)}")
    meta = f" ({' | '.join(meta_parts)})" if meta_parts else ""
    text = str(msg.get("text") or "").strip()
    return f"#{seq} @{agent}{meta}:\n  {text}"


def _print_status(data: dict[str, Any]) -> None:
    counts = data.get("counts", {})
    print(f"Swarm: {data.get('title', 'Swarm MyKOS')} | head #{data.get('head', 0)} | permisos: {data.get('permission_mode', 'supervisado')}")
    print(
        f"Agentes: {counts.get('members', 0)} | Trabajando: {counts.get('working', 0)} | "
        f"En espera: {counts.get('waiting', 0)} | Detenidos: {counts.get('killed', 0)} | Mensajes: {counts.get('messages', 0)}"
    )
    for m in data.get("member_list", []):
        err = f" | error={m.get('last_error')}" if m.get("last_error") else ""
        print(
            f"  - @{m.get('name')} [{m.get('state')}] ({m.get('role')}, "
            f"modelo={m.get('model')}, herr={m.get('tools_used_count', 0)}){err}"
        )


def _print_board(data: dict[str, Any]) -> None:
    msgs = data.get("messages") or []
    print(f"Tablón Swarm: {data.get('title', 'Swarm MyKOS')} | head #{data.get('head', 0)} | mostrando {len(msgs)} mensaje(s)")
    if not msgs:
        print("  (Sin mensajes en este rango)")
        return
    for msg in msgs:
        print(_format_message_block(msg))


def _offline_call(fn_name: str, **kwargs: Any) -> dict[str, Any]:
    import swarm_engine
    if fn_name == "status":
        return swarm_engine.get_swarm_status(
            since_seq=int(kwargs.get("since_seq", 0) or 0),
            limit=int(kwargs.get("limit", 60) or 60),
        )
    if fn_name == "add":
        res = swarm_engine.add_worker(
            name=kwargs["name"],
            role=kwargs["role"],
            brief=kwargs["brief"],
            model=kwargs["model"],
            permission_mode=kwargs.get("permission_mode"),
            title=kwargs.get("title"),
        )
        wait_s = float(kwargs.get("wait_seconds") or 0.0)
        if wait_s > 0 and res.get("ok"):
            targets = list(res.get("woken") or []) or [swarm_engine.normalize_agent_name(kwargs["name"])]
            after_seq = int((res.get("message") or {}).get("seq") or 0)
            settled = swarm_engine.wait_for_swarm_settlement(targets, after_seq, wait_s)
            res["waited_seconds"] = wait_s
            res["board_updates"] = settled.get("messages", [])
            res["member_list"] = settled.get("member_list", [])
            res["counts"] = settled.get("counts", {})
            res["head"] = settled.get("head", res.get("head"))
        return res
    if fn_name == "post":
        res = swarm_engine.post_board_message(agent=kwargs["agent"], text=kwargs["text"])
        wait_s = float(kwargs.get("wait_seconds") or 0.0)
        if wait_s > 0 and res.get("ok"):
            targets = list(res.get("woken") or [])
            after_seq = int((res.get("message") or {}).get("seq") or res.get("head") or 0)
            settled = swarm_engine.wait_for_swarm_settlement(targets, after_seq, wait_s)
            res["waited_seconds"] = wait_s
            res["board_updates"] = settled.get("messages", [])
            res["member_list"] = settled.get("member_list", [])
            res["counts"] = settled.get("counts", {})
            res["head"] = settled.get("head", res.get("head"))
        return res
    if fn_name == "kill":
        return swarm_engine.kill_worker(kwargs["name"])
    if fn_name == "reset":
        return swarm_engine.reset_swarm(
            title=kwargs["title"],
            permission_mode=kwargs.get("permission_mode"),
        )
    raise ValueError(f"Acción desconocida: {fn_name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mykos swarm", description="CLI del motor Multi-Agente MyKOS Swarm")
    subparsers = parser.add_subparsers(dest="subcommand")

    p_status = subparsers.add_parser("status", help="Estado del Swarm y agentes")
    p_status.add_argument("--limit", type=int, default=15)
    p_status.add_argument("--json", action="store_true")

    p_board = subparsers.add_parser("board", help="Mensajes del tablón compartido")
    p_board.add_argument("--since", type=int, default=0)
    p_board.add_argument("--limit", type=int, default=60)
    p_board.add_argument("--json", action="store_true")

    p_add = subparsers.add_parser("add", help="Añade y despierta un trabajador Swarm")
    p_add.add_argument("name_pos", nargs="?", default="", help="Nombre del trabajador")
    p_add.add_argument("--name", dest="name_flag", default="", help="Nombre del trabajador")
    p_add.add_argument("--role", default="Especialista")
    p_add.add_argument("--model", default="inherit")
    p_add.add_argument("--brief", default="")
    p_add.add_argument("--wait", type=float, default=0.0)
    p_add.add_argument("--title", default=None)
    p_add.add_argument("--permission-mode", dest="permission_mode", default=None)
    p_add.add_argument("--json", action="store_true")

    p_post = subparsers.add_parser("post", help="Publica un mensaje en el tablón")
    p_post.add_argument("text_parts", nargs="*", help="Texto del mensaje")
    p_post.add_argument("--text", dest="text_flag", default="")
    p_post.add_argument("--agent", default="coordinator")
    p_post.add_argument("--wait", type=float, default=0.0)
    p_post.add_argument("--json", action="store_true")

    p_kill = subparsers.add_parser("kill", help="Detiene un trabajador o todos ('all')")
    p_kill.add_argument("name_pos", nargs="?", default="")
    p_kill.add_argument("--name", dest="name_flag", default="")
    p_kill.add_argument("--json", action="store_true")

    p_reset = subparsers.add_parser("reset", help="Reinicia el Swarm")
    p_reset.add_argument("--title", default="Nuevo Swarm MyKOS")
    p_reset.add_argument("--permission-mode", dest="permission_mode", default=None)
    p_reset.add_argument("--json", action="store_true")

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    sub = args.subcommand or "status"
    if args.subcommand is None:
        args.limit = 15
        args.json = False

    if sub == "status":
        connected, data, err = _control_request("GET", f"/mykos-control/swarm/status?limit={int(args.limit)}", timeout=10.0)
        if not connected:
            data = _offline_call("status", limit=args.limit)
        elif not data or not data.get("ok"):
            print(f"❌ Error Swarm status: {err or (data or {}).get('error')}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            _print_status(data)
        return 0

    if sub == "board":
        qs = urllib.parse.urlencode({"since_seq": max(0, int(args.since)), "limit": max(1, int(args.limit))})
        connected, data, err = _control_request("GET", f"/mykos-control/swarm/status?{qs}", timeout=10.0)
        if not connected:
            data = _offline_call("status", since_seq=args.since, limit=args.limit)
        elif not data or not data.get("ok"):
            print(f"❌ Error Swarm board: {err or (data or {}).get('error')}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            _print_board(data)
        return 0

    if sub == "add":
        name = (args.name_flag or args.name_pos or "").strip()
        if not name:
            print("❌ Debes indicar el nombre del trabajador: mykos swarm add <nombre> ...", file=sys.stderr)
            return 1
        wait_s = max(0.0, min(120.0, float(args.wait or 0.0)))
        payload: dict[str, Any] = {
            "name": name,
            "role": args.role,
            "model": args.model,
            "brief": args.brief,
            "wait_seconds": wait_s,
        }
        if args.title:
            payload["title"] = args.title
        if args.permission_mode:
            payload["permission_mode"] = args.permission_mode
        connected, data, err = _control_request("POST", "/mykos-control/swarm/workers", payload, timeout=max(30.0, wait_s + 30.0))
        if not connected:
            data = _offline_call("add", **payload)
        elif not data or not data.get("ok"):
            print(f"❌ Error Swarm add: {err or (data or {}).get('error')}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return 0
        msg = data.get("message") or {}
        woken = ", ".join(f"@{w}" for w in (data.get("woken") or [name]))
        print(f"✅ Trabajador @{name} desplegado (rol={args.role}, modelo={args.model}) · despertados: {woken} · #seq={msg.get('seq', data.get('head', 0))}")
        updates = data.get("board_updates") or []
        if updates:
            print(f"── Actualizaciones en el tablón ({len(updates)}) ──")
            for u in updates:
                print(_format_message_block(u))
        elif wait_s > 0:
            print("⏳ El trabajador aún sigue procesando o no publicó respuesta adicional en el plazo.")
        counts = data.get("counts") or {}
        if counts.get("working", 0):
            print(f"ℹ️ Agentes trabajando actualmente: {counts.get('working')}. Usa «mykos swarm board» para ver avances.")
        return 0

    if sub == "post":
        text = (args.text_flag or " ".join(args.text_parts or [])).strip()
        if not text:
            print("❌ Debes indicar el mensaje: mykos swarm post \"<texto>\" [--wait 35]", file=sys.stderr)
            return 1
        wait_s = max(0.0, min(120.0, float(args.wait or 0.0)))
        payload = {"agent": args.agent, "text": text, "wait_seconds": wait_s}
        connected, data, err = _control_request("POST", "/mykos-control/swarm/board", payload, timeout=max(30.0, wait_s + 30.0))
        if not connected:
            data = _offline_call("post", **payload)
        elif not data or not data.get("ok"):
            print(f"❌ Error Swarm post: {err or (data or {}).get('error')}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return 0
        msg = data.get("message") or {}
        woken = ", ".join(f"@{w}" for w in (data.get("woken") or [])) or "(ninguno)"
        print(f"✅ Mensaje #{msg.get('seq', data.get('head', 0))} publicado por @{args.agent} · despertados: {woken}")
        updates = data.get("board_updates") or []
        if updates:
            print(f"── Respuestas en el tablón ({len(updates)}) ──")
            for u in updates:
                print(_format_message_block(u))
        return 0

    if sub == "kill":
        name = (args.name_flag or args.name_pos or "").strip()
        if not name:
            print("❌ Indica el agente a detener o 'all': mykos swarm kill <nombre|all>", file=sys.stderr)
            return 1
        connected, data, err = _control_request("POST", "/mykos-control/swarm/workers/kill", {"name": name}, timeout=15.0)
        if not connected:
            data = _offline_call("kill", name=name)
        elif not data or not data.get("ok"):
            print(f"❌ Error Swarm kill: {err or (data or {}).get('error')}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            killed = ", ".join(f"@{k}" for k in (data.get("killed") or [name])) or name
            print(f"🛑 Detenido(s): {killed}")
        return 0

    if sub == "reset":
        payload = {"title": args.title}
        if args.permission_mode:
            payload["permission_mode"] = args.permission_mode
        connected, data, err = _control_request("POST", "/mykos-control/swarm/reset", payload, timeout=15.0)
        if not connected:
            data = _offline_call("reset", **payload)
        elif not data or not data.get("ok"):
            print(f"❌ Error Swarm reset: {err or (data or {}).get('error')}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"🔄 Swarm reiniciado: «{data.get('title', args.title)}» (head #{data.get('head', 0)})")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
