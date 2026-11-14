from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any
import urllib.error
import urllib.request

from nvidia import _decode_key, _encode_key


ROOT = Path(__file__).resolve().parent
_GATEWAY_CREDS = Path.home() / ".mykos" / "gateway-state" / "mykos" / "credentials"
_CREDS_BASE = os.environ.get("MYKOS_CREDENTIALS_DIR")
if _CREDS_BASE:
  OAUTH_ROOT = Path(_CREDS_BASE).expanduser()
elif _GATEWAY_CREDS.exists():
  OAUTH_ROOT = _GATEWAY_CREDS
else:
  OAUTH_ROOT = ROOT / "data" / "oauth"
META_AI_DIR = OAUTH_ROOT / "meta-ai"
META_AI_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
META_AI_CREDENTIALS_PATH = META_AI_DIR / "credentials.json"
META_AI_API_KEY_PATH = META_AI_DIR / "api_key.json"
META_AI_DGW_SCRIPT = Path(__file__).resolve().parent / "meta_ai_dgw.mjs"
META_AI_OIDC_URL = "https://www.meta.ai/api/oidc/start"
META_AI_WEB_URL = "https://www.meta.ai/"

META_AI_MODELS: list[dict[str, Any]] = [
    # --- Modelos disponibles vía OAuth (puente DGW, gratuitos) ---
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
    # --- Modelos Muse (requieren Meta Model API con clave API) ---
    {
        "name": "meta-ai/muse-wonder",
        "label": "Meta AI · Muse Wonder (Frontier Coding)",
        "size": "meta-ai-api",
        "modified": "remoto",
        "provider": "meta_ai_api",
        "remote": True,
        "free": False,
        "recommended": True,
        "context_length": 128000,
        "enable_thinking": True,
        "description": "Codificación frontier, agentes de larga duración, planificación avanzada",
    },
    {
        "name": "meta-ai/muse-wonder-full",
        "label": "Meta AI · Muse Wonder Full (SOTA)",
        "size": "meta-ai-api",
        "modified": "remoto",
        "provider": "meta_ai_api",
        "remote": True,
        "free": False,
        "recommended": True,
        "context_length": 128000,
        "enable_thinking": True,
        "description": "Rendimiento SOTA para flujos críticos y benchmarks",
    },
    {
        "name": "meta-ai/muse-ember",
        "label": "Meta AI · Muse Ember (Multimodal Eficiente)",
        "size": "meta-ai-api",
        "modified": "remoto",
        "provider": "meta_ai_api",
        "remote": True,
        "free": False,
        "recommended": True,
        "context_length": 128000,
        "enable_thinking": False,
        "description": "Multimodal eficiente para codificación diaria y tool calling",
    },
    {
        "name": "meta-ai/muse-spark-1.3",
        "label": "Meta AI · Muse Spark 1.3",
        "size": "meta-ai-api",
        "modified": "remoto",
        "provider": "meta_ai_api",
        "remote": True,
        "free": False,
        "recommended": True,
        "context_length": 128000,
        "enable_thinking": False,
        "description": "Codificación y flujos agénticos, código más limpio y menos tokens",
    },
    {
        "name": "meta-ai/muse-spark-1.2",
        "label": "Meta AI · Muse Spark 1.2",
        "size": "meta-ai-api",
        "modified": "remoto",
        "provider": "meta_ai_api",
        "remote": True,
        "free": False,
        "recommended": False,
        "context_length": 128000,
        "enable_thinking": False,
        "description": "Optimizado para programación y flujos agénticos",
    },
    {
        "name": "meta-ai/muse-spark-1.1",
        "label": "Meta AI · Muse Spark 1.1",
        "size": "meta-ai-api",
        "modified": "remoto",
        "provider": "meta_ai_api",
        "remote": True,
        "free": False,
        "recommended": False,
        "context_length": 128000,
        "enable_thinking": False,
        "description": "Flujos agénticos, programación y percepción multimodal",
    },
    {
        "name": "meta-ai/muse-image",
        "label": "Meta AI · Muse Image (Generación)",
        "size": "meta-ai-api",
        "modified": "remoto",
        "provider": "meta_ai_api",
        "remote": True,
        "free": False,
        "recommended": False,
        "context_length": 128000,
        "enable_thinking": False,
        "description": "Generación de imágenes con autocorrección y planificación",
    },
    {
        "name": "meta-ai/sam-3.1",
        "label": "Meta AI · SAM 3.1 (Segmentación)",
        "size": "meta-ai-api",
        "modified": "remoto",
        "provider": "meta_ai_api",
        "remote": True,
        "free": False,
        "recommended": False,
        "context_length": 128000,
        "enable_thinking": False,
        "description": "Segmentación y detección de objetos en imágenes y vídeo",
    },
    {
        "name": "meta-ai/muse-voice-transcribe",
        "label": "Meta AI · Muse Voice Transcribe",
        "size": "meta-ai-api",
        "modified": "remoto",
        "provider": "meta_ai_api",
        "remote": True,
        "free": False,
        "recommended": False,
        "context_length": 128000,
        "enable_thinking": False,
        "description": "Transcripción con diarización y detección de turnos",
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
  META_AI_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
  try:
    os.chmod(META_AI_DIR, 0o700)
  except OSError:
    pass
  bridge_input = {
      **payload,
      "cacheDir": str(META_AI_DIR),
  }
  clean_env = {
      "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
      "HOME": str(META_AI_DIR),
      "NODE_NO_WARNINGS": "1",
  }
  for proxy_var in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS"):
    if proxy_var in os.environ:
      clean_env[proxy_var] = os.environ[proxy_var]
  proc = subprocess.run(
      [node_bin, str(META_AI_DGW_SCRIPT)],
      input=json.dumps(bridge_input, ensure_ascii=False),
      capture_output=True,
      text=True,
      timeout=timeout,
      check=False,
      env=clean_env,
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


def save_meta_ai_api_key(key: str) -> dict[str, Any]:
  value = str(key).strip()
  if not value or len(value) < 8:
    raise RuntimeError("Introduce una clave válida de Meta Model API.")
  META_AI_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
  temporary = META_AI_API_KEY_PATH.with_suffix(".tmp")
  temporary.write_text(json.dumps(_encode_key(value), ensure_ascii=False), encoding="utf-8")
  try:
    os.chmod(temporary, 0o600)
  except OSError:
    pass
  temporary.replace(META_AI_API_KEY_PATH)
  return {"ok": True, "provider": "meta_ai_api", "auth_method": "Meta Model API Key"}


def get_meta_ai_api_key() -> str:
  if not META_AI_API_KEY_PATH.is_file():
    return ""
  try:
    data = json.loads(META_AI_API_KEY_PATH.read_text(encoding="utf-8"))
    if isinstance(data, dict):
      return _decode_key(data)
  except Exception:
    pass
  return ""


def meta_ai_auth_status() -> dict[str, Any]:
  session = _load_meta_ai_session()
  api_key = get_meta_ai_api_key()
  authenticated = bool(session or api_key)
  token = str((session or {}).get("accessToken") or "")
  user_id = str((session or {}).get("abraUserId") or "")
  if token and len(token) > 16:
    masked = f"{token[:10]}...{token[-4:]}"
  elif api_key and len(api_key) > 12:
    masked = f"{api_key[:8]}...{api_key[-4:]}"
  else:
    masked = None

  if session and api_key:
    auth_method = "Meta AI (OAuth + API Key)"
  elif api_key:
    auth_method = "Meta Model API Key"
  elif session:
    auth_method = "Meta AI OAuth (ecto1 / DGW)"
  else:
    auth_method = ""

  return {
      "provider": "meta_ai_oauth",
      "authenticated": authenticated,
      "has_oauth": bool(session),
      "has_api_key": bool(api_key),
      "auth_method": auth_method,
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
  if META_AI_API_KEY_PATH.exists():
    META_AI_API_KEY_PATH.unlink()
    removed.append(str(META_AI_API_KEY_PATH))
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
      "ok": True,
      "provider": "meta_ai_oauth",
      "status": "logged_out",
      "removed": removed,
      "auth": meta_ai_auth_status(),
      "login": meta_ai_login_state(),
  }


_NON_CHAT_META_MODELS = {
    "meta-ai/muse-image",
    "meta-ai/sam-3.1",
    "meta-ai/muse-voice-transcribe",
}


def meta_ai_models(*, force: bool = False) -> list[dict[str, Any]]:
  _ = force
  has_oauth_session = bool(_load_meta_ai_session())
  has_api_key = bool(get_meta_ai_api_key())
  result: list[dict[str, Any]] = []
  for item in META_AI_MODELS:
    name = str(item.get("name", "")).strip()
    if name in _NON_CHAT_META_MODELS:
      continue
    provider = item.get("provider", "meta_ai_oauth")
    if provider == "meta_ai_oauth" and not has_oauth_session:
      continue
    if provider == "meta_ai_api" and not has_api_key:
      continue
    row = dict(item)
    is_auth = has_api_key if provider == "meta_ai_api" else has_oauth_session
    row["chat_capable"] = bool(is_auth)
    row["auth_status"] = "autenticado" if is_auth else "no autenticado"
    result.append(row)
  return result


def _strip_meta_ai_command_prefix(text: str) -> str:
  cleaned = str(text or "").strip()
  ts_match = re.match(r"^(\[Fecha y hora actuales:[^\]]*\]\s*)", cleaned)
  ts_prefix = ts_match.group(1) if ts_match else ""
  body = cleaned[len(ts_prefix) :] if ts_prefix else cleaned
  body = re.sub(r"^\s*/(?:imagine|imgine|imagen)(?:\s+|$)", "", body, flags=re.IGNORECASE).strip()
  return f"{ts_prefix}{body}".strip() if body else cleaned


def _extract_meta_ai_image_prompt(messages: list[dict[str, Any]]) -> str:
  generic_confirmations = {"si", "sí", "ok", "vale", "dale", "hazlo", "generala", "genérala", "perfecto", "adelante", "claro"}
  candidates: list[str] = []
  for msg in reversed(messages):
    if not isinstance(msg, dict):
      continue
    if str(msg.get("role") or "").strip().casefold() != "user" or msg.get("integrity_guard"):
      continue
    content = msg.get("content")
    if isinstance(content, list):
      raw = "\n".join(str(item.get("text") or "") for item in content if isinstance(item, dict) and item.get("text")).strip()
    else:
      raw = str(content or "").strip()
    if not raw:
      continue
    cleaned = re.sub(r"^\[Fecha y hora actuales:[^\]]*\]\s*", "", raw).strip()
    cleaned = re.sub(r"\[NOTA DEL HOST MYKOS:[\s\S]*?\]", "", cleaned).strip()
    cleaned = re.sub(r"^\s*/(?:imagine|imgine|imagen)(?:\s+|$)", "", cleaned, flags=re.IGNORECASE).strip()
    if not cleaned:
      continue
    candidates.append(cleaned)
    normalized = re.sub(r"[.!?,¡¿]+", "", cleaned.casefold()).strip()
    if normalized not in generic_confirmations and len(cleaned) >= 12:
      return cleaned[:1000]
  return (candidates[0] if candidates else "creative detailed illustration")[:1000]


def _format_messages_for_meta_ai(messages: list[dict[str, Any]]) -> str:
  parts: list[str] = []
  last_user_idx = -1
  for idx, msg in enumerate(messages):
    if (
      isinstance(msg, dict)
      and str(msg.get("role") or "user").strip().lower() == "user"
      and not msg.get("integrity_guard")
    ):
      last_user_idx = idx

  for idx, msg in enumerate(messages):
    if not isinstance(msg, dict):
      continue
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
      aliased = text.replace("generate_image", "flux_dispatch").replace("generate_video", "wan_dispatch")
      aliased += (
          "\n[NOTA DE HERRAMIENTAS EXTERNAS: Usa flux_dispatch para generar imágenes y wan_dispatch para generar vídeos "
          "mediante el motor externo de MyKOS pasando siempre una descripción visual detallada en inglés. "
          "NUNCA uses la capacidad interna de Meta AI ni pidas al usuario iniciar sesión.]"
      )
      parts.append(f"[INSTRUCCIONES DEL SISTEMA MYKOS]\n{aliased}\n[/INSTRUCCIONES DEL SISTEMA MYKOS]")
    elif role == "assistant":
      cleaned_assistant = re.sub(r"<ui-widget\b[^>]*>.*?</ui-widget>", "", text, flags=re.DOTALL)
      cleaned_assistant = re.sub(
          r"[^\n]*(?:disponible después de iniciar sesión|image generation is available after|iniciar sesión para generar)[^\n]*",
          "",
          cleaned_assistant,
          flags=re.IGNORECASE,
      )
      cleaned_assistant = (
          cleaned_assistant.replace("generate_image", "flux_dispatch")
          .replace("generate_video", "wan_dispatch")
          .strip()
      )
      if cleaned_assistant:
        parts.append(f"[ASISTENTE]\n{cleaned_assistant}")
    elif role == "tool":
      parts.append(
          f"[RESULTADO DE HERRAMIENTA EJECUTADA EN EL SERVIDOR MYKOS]\n{text}\n"
          "Instrucción para el asistente: la herramienta se ha ejecutado con éxito en el servidor de MyKOS. "
          "Si el resultado contiene una imagen o vídeo en formato markdown ![...](url), debes incluirla en tu respuesta "
          "exactamente en formato Markdown y presentarla al usuario sin requerir inicio de sesión ni mencionar widgets de Meta AI."
      )
    else:
      user_text = _strip_meta_ai_command_prefix(text)
      if idx == last_user_idx:
        user_text += (
            "\n\n[NOTA DEL HOST MYKOS: No uses widgets internos ni generación de imágenes nativa de Meta AI, y nunca "
            "pidas iniciar sesión. Si el usuario pide o confirma crear una imagen, foto, dibujo o ilustración, responde "
            'EXCLUSIVAMENTE con JSON: {"kind":"tool_call","content":"","tool_name":"flux_dispatch",'
            '"arguments":{"prompt":"<descripción visual detallada en inglés>","aspect_ratio":"1:1","model":"flux"}}.]'
        )
      parts.append(f"[USUARIO]\n{user_text}")
  return "\n\n".join(parts).strip()


def meta_ai_chat_completion(
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
  api_key = get_meta_ai_api_key()
  session = _load_meta_ai_session()
  is_muse = "muse" in str(model or "").lower()
  if is_muse and not api_key:
    raise RuntimeError("Los modelos Meta AI · Muse requieren una clave personal de Meta Model API.")
  if api_key and (is_muse or not session):
    clean_model = model.removeprefix("meta-ai/")
    req_data = {
        "model": clean_model,
        "messages": messages,
        "max_tokens": max(1, min(16384, int(max_tokens))),
        "temperature": max(0.0, min(2.0, float(temperature))),
        "stream": False,
    }
    body = json.dumps(req_data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.meta.ai/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
      with urllib.request.urlopen(req, timeout=75) as resp:
        data = json.loads(resp.read().decode("utf-8"))
      choices = data.get("choices", [])
      if not choices:
        raise RuntimeError("Meta Model API no devolvió choices válidas.")
      return str(choices[0].get("message", {}).get("content", ""))
    except Exception as exc:
      raise RuntimeError(f"Error consultando Meta Model API: {exc}") from exc

  _ = (max_tokens, temperature)
  if not session:
    raise RuntimeError("Meta AI OAuth no está conectado. Inicia sesión con Meta AI en Proveedores.")

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
  raw_text = str(result.get("response") or "").strip()
  widget_blocks = re.findall(r"<ui-widget\b[^>]*>.*?</ui-widget>", raw_text, flags=re.DOTALL | re.IGNORECASE)
  has_login_widget = any(
      "image_generation" in block.casefold() and "login_required" in block.casefold()
      for block in widget_blocks
  )
  login_block_phrases = (
      "disponible después de iniciar sesión",
      "iniciar sesión para generar",
      "image generation is available after",
      "sign in to generate images",
      "log in to generate images",
  )
  has_login_phrase = any(phrase in raw_text.casefold() for phrase in login_block_phrases)
  if has_login_widget or has_login_phrase:
    extracted_prompt = _extract_meta_ai_image_prompt(messages)
    return json.dumps(
        {
            "kind": "tool_call",
            "content": "",
            "tool_name": "generate_image",
            "arguments": {
                "prompt": extracted_prompt,
                "aspect_ratio": "1:1",
                "model": "flux",
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

  text = re.sub(r"<ui-widget\b[^>]*>.*?</ui-widget>", "", raw_text, flags=re.DOTALL).strip()
  if not text:
    raise RuntimeError("Meta AI devolvió una respuesta vacía.")
  text = text.replace("flux_dispatch", "generate_image").replace("wan_dispatch", "generate_video")
  return text
