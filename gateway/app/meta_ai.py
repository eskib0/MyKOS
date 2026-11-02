from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any

from nvidia import _decode_key, _encode_key


ROOT = Path(__file__).resolve().parent
OAUTH_ROOT = Path(os.environ.get("MYKOS_CREDENTIALS_DIR", str(ROOT / "data" / "oauth"))).expanduser()
META_AI_DIR = OAUTH_ROOT / "meta-ai"
META_AI_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
META_AI_CREDENTIALS_PATH = META_AI_DIR / "credentials.json"
META_AI_DGW_SCRIPT = Path(__file__).resolve().parent / "meta_ai_dgw.mjs"
META_AI_OIDC_URL = "https://www.meta.ai/api/oidc/start"
META_AI_WEB_URL = "https://www.meta.ai/"

META_AI_MODELS: list[dict[str, Any]] = [
    {
        "name": "meta-ai/llama-4-fast",
        "label": "Meta AI · Llama 4 Fast",
        "size": "meta-ai-oauth",
        "modified": "remoto",
        "provider": "meta_ai_oauth",
        "remote": True,
        "free": True,
        "recommended": True,
        "context_length": 128000,
        "enable_thinking": False,
    },
    {
        "name": "meta-ai/llama-4-reasoning",
        "label": "Meta AI · Llama 4 Reasoning (Think Hard)",
        "size": "meta-ai-oauth",
        "modified": "remoto",
        "provider": "meta_ai_oauth",
        "remote": True,
        "free": True,
        "recommended": True,
        "context_length": 128000,
        "enable_thinking": True,
    },
    {
        "name": "meta-ai/meta-ai-assistant",
        "label": "Meta AI · Asistente Oficial Web",
        "size": "meta-ai-oauth",
        "modified": "remoto",
        "provider": "meta_ai_oauth",
        "remote": True,
        "free": True,
        "recommended": False,
        "context_length": 128000,
        "enable_thinking": False,
    },
]

_LOGIN_STATE: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "returncode": None,
    "login_url": None,
    "output": "",
    "error": None,
}


def _find_node_binary() -> str:
  for candidate in (
      os.environ.get("MYKOS_NODE_BIN", ""),
      shutil.which("node") or "",
      "/usr/bin/node",
      "/usr/local/bin/node",
  ):
    if candidate and Path(candidate).is_file():
      return candidate
  nvm_dir = Path.home() / ".nvm" / "versions" / "node"
  if nvm_dir.is_dir():
    versions = sorted(nvm_dir.glob("*/bin/node"), reverse=True)
    if versions:
      return str(versions[0])
  return "node"


def _load_meta_ai_session() -> dict[str, Any] | None:
  if not META_AI_CREDENTIALS_PATH.exists():
    return None
  try:
    payload = json.loads(META_AI_CREDENTIALS_PATH.read_text(encoding="utf-8"))
  except Exception:
    return None
  raw_session = _decode_key(payload)
  if not raw_session:
    return None
  try:
    session = json.loads(raw_session)
  except Exception:
    return None
  if not isinstance(session, dict) or not session.get("accessToken") or not session.get("abraUserId"):
    return None
  return session


def _save_meta_ai_session(session: dict[str, Any]) -> None:
  META_AI_DIR.mkdir(parents=True, exist_ok=True)
  raw_json = json.dumps(session, ensure_ascii=False)
  payload = {
      **_encode_key(raw_json),
      "provider": "meta_ai_oauth",
      "updated_at": int(time.time()),
      "abra_user_id": str(session.get("abraUserId") or "")[:16],
  }
  META_AI_CREDENTIALS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
  os.chmod(META_AI_CREDENTIALS_PATH, 0o600)


def _open_chrome(url: str) -> None:
  for candidate in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "xdg-open"):
    binary = shutil.which(candidate)
    if not binary:
      continue
    try:
      subprocess.Popen(
          [binary, url],
          stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL,
          start_new_session=True,
      )
      return
    except Exception:
      continue


def _invoke_dgw_bridge(payload: dict[str, Any], timeout: int = 75) -> dict[str, Any]:
  node_bin = _find_node_binary()
  META_AI_DIR.mkdir(parents=True, exist_ok=True)
  bridge_input = {
      **payload,
      "cacheDir": str(META_AI_DIR),
  }
  proc = subprocess.run(
      [node_bin, str(META_AI_DGW_SCRIPT)],
      input=json.dumps(bridge_input, ensure_ascii=False),
      capture_output=True,
      text=True,
      timeout=timeout,
      check=False,
  )
  stdout = (proc.stdout or "").strip()
  if stdout:
    last_line = stdout.splitlines()[-1].strip()
    try:
      parsed = json.loads(last_line)
      if isinstance(parsed, dict):
        return parsed
    except Exception:
      pass
  stderr = (proc.stderr or "").strip()
  raise RuntimeError(stderr or stdout or f"El puente DGW de Meta AI falló (código {proc.returncode}).")


def meta_ai_auth_status() -> dict[str, Any]:
  session = _load_meta_ai_session()
  token = str((session or {}).get("accessToken") or "")
  user_id = str((session or {}).get("abraUserId") or "")
  masked = f"{token[:10]}...{token[-4:]}" if len(token) > 16 else None
  return {
      "provider": "meta_ai_oauth",
      "authenticated": bool(session),
      "credentials_path": str(META_AI_CREDENTIALS_PATH),
      "token_preview": masked,
      "abra_user_id": user_id[:12] + "..." if len(user_id) > 12 else (user_id or None),
      "updated_at": int((session or {}).get("acquiredAt") or 0) or None,
      "web_url": META_AI_WEB_URL,
      "oidc_url": META_AI_OIDC_URL,
  }


def meta_ai_login_state() -> dict[str, Any]:
  return dict(_LOGIN_STATE)


def start_meta_ai_oauth(*, open_browser: bool = False) -> dict[str, Any]:
  _LOGIN_STATE.update(
      {
          "running": True,
          "started_at": int(time.time()),
          "finished_at": None,
          "returncode": None,
          "login_url": META_AI_OIDC_URL,
          "output": "Negociando challenge y sesión OAuth con Meta AI (ecto1 / DGW)...",
          "error": None,
      }
  )
  try:
    result = _invoke_dgw_bridge({"action": "auth"}, timeout=45)
    if not result.get("ok") or not isinstance(result.get("session"), dict):
      raise RuntimeError(str(result.get("error") or "No se pudo establecer sesión OAuth con Meta AI."))
    session = result["session"]
    _save_meta_ai_session(session)
    if open_browser:
      _open_chrome(META_AI_OIDC_URL)
    _LOGIN_STATE.update(
        {
            "running": False,
            "finished_at": int(time.time()),
            "returncode": 0,
            "login_url": META_AI_OIDC_URL,
            "output": "Sesión OAuth de Meta AI (ecto1 + DGW) vinculada y cifrada en MyKOS.",
            "error": None,
        }
    )
  except Exception as exc:
    _LOGIN_STATE.update(
        {
            "running": False,
            "finished_at": int(time.time()),
            "returncode": 1,
            "login_url": META_AI_OIDC_URL,
            "output": "",
            "error": str(exc),
        }
    )
    raise
  return {
      "started": True,
      "already_running": False,
      "login": meta_ai_login_state(),
      "oauth": meta_ai_auth_status(),
  }


def logout_meta_ai_oauth() -> dict[str, Any]:
  removed: list[str] = []
  if META_AI_CREDENTIALS_PATH.exists():
    META_AI_CREDENTIALS_PATH.unlink()
    removed.append(str(META_AI_CREDENTIALS_PATH))
  _LOGIN_STATE.update(
      {
          "running": False,
          "started_at": None,
          "finished_at": int(time.time()),
          "returncode": 0,
          "login_url": None,
          "output": "",
          "error": None,
      }
  )
  return {
      "removed": removed,
      "status": meta_ai_auth_status(),
      "login": meta_ai_login_state(),
  }


def meta_ai_models(*, force: bool = False) -> list[dict[str, Any]]:
  _ = force
  if not _load_meta_ai_session():
    return []
  return [dict(item) for item in META_AI_MODELS]


def _format_messages_for_meta_ai(messages: list[dict[str, Any]]) -> str:
  parts: list[str] = []
  for msg in messages:
    role = str(msg.get("role") or "user").strip().lower()
    content = msg.get("content")
    if isinstance(content, list):
      text_items = [
          str(item.get("text") or "")
          for item in content
          if isinstance(item, dict) and item.get("text")
      ]
      text = "\n".join(text_items).strip()
    else:
      text = str(content or "").strip()
    if not text:
      continue
    if role == "system":
      parts.append(f"[INSTRUCCIONES DEL SISTEMA MYKOS]\n{text}\n[/INSTRUCCIONES DEL SISTEMA MYKOS]")
    elif role == "assistant":
      parts.append(f"[ASISTENTE]\n{text}")
    elif role == "tool":
      parts.append(
          f"[RESULTADO DE HERRAMIENTA EJECUTADA EN EL SERVIDOR MYKOS]\n{text}\n"
          "Instrucción para el asistente: la herramienta se ha ejecutado con éxito en el servidor de MyKOS. "
          "Si el resultado contiene una imagen o vídeo en formato markdown ![...](url), debes incluirla en tu respuesta "
          "exactamente en formato Markdown y presentarla al usuario sin requerir inicio de sesión ni mencionar widgets de Meta AI."
      )
    else:
      parts.append(f"[USUARIO]\n{text}")
  return "\n\n".join(parts).strip()


def meta_ai_chat_completion(
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
  _ = (max_tokens, temperature)
  session = _load_meta_ai_session()
  if not session:
    start_meta_ai_oauth(open_browser=False)
    session = _load_meta_ai_session()
  if not session:
    raise RuntimeError("Meta AI OAuth no está conectado. Pulsa «Conectar Meta AI OAuth» en la barra lateral.")

  enable_thinking = "reasoning" in str(model or "").lower() or "think" in str(model or "").lower()
  prompt = _format_messages_for_meta_ai(messages)
  result = _invoke_dgw_bridge(
      {
          "action": "chat",
          "prompt": prompt,
          "enableThinking": enable_thinking,
          "session": session,
      },
      timeout=75,
  )
  if not result.get("ok"):
    raise RuntimeError(str(result.get("error") or "Error al consultar Meta AI por DGW."))
  new_session = result.get("session")
  if isinstance(new_session, dict) and new_session.get("accessToken"):
    _save_meta_ai_session(new_session)
  text = str(result.get("response") or "").strip()
  text = re.sub(r"<ui-widget\b[^>]*>.*?</ui-widget>", "", text, flags=re.DOTALL).strip()
  if not text:
    raise RuntimeError("Meta AI devolvió una respuesta vacía.")
  return text
