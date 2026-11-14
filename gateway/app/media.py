from __future__ import annotations

import base64
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


def _resolve_data_dir(root: Path) -> Path:
    env_dir = os.environ.get("MYKOS_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    candidate = root / "data"
    if os.access(candidate if candidate.exists() else root, os.W_OK):
        return candidate
    return (Path.home() / ".mykos" / "data").resolve()


ROOT = Path(__file__).resolve().parent
MEDIA_DIR = _resolve_data_dir(ROOT) / "media"
MAX_TTS_CHARS = 12_000
MAX_MEDIA_FILES = 100
MAX_TRANSCRIPTION_BYTES = 25 * 1024 * 1024

def _detect_whisper_model() -> str:
    env_m = os.environ.get("MYKOS_WHISPER_MODEL", "").strip()
    if env_m:
        return env_m
    cache_dir = Path.home() / ".cache" / "whisper"
    for name in ("small", "base", "large-v3-turbo", "large-v3", "medium", "tiny"):
        if (cache_dir / f"{name}.pt").is_file():
            return name
    return "small"

WHISPER_MODEL = _detect_whisper_model()
WHISPER_PYTHON = Path(
    os.environ.get(
        "MYKOS_WHISPER_PYTHON",
        str(Path.home() / ".mykos" / "venv" / "bin" / "python")
        if (Path.home() / ".mykos" / "venv" / "bin" / "python").is_file()
        else (
            str(ROOT.parent / ".venv" / "bin" / "python")
            if (ROOT.parent / ".venv" / "bin" / "python").is_file()
            else (sys.executable or shutil.which("python3") or "/usr/bin/python3")
        ),
    )
)
KOKORO_PYTHON = Path(
    os.environ.get("MYKOS_KOKORO_PYTHON", sys.executable or shutil.which("python3") or "/usr/bin/python3")
)
KOKORO_WORKER = ROOT / "kokoro_worker.py"
KOKORO_ESPEAK_DATA = Path(
    os.environ.get("MYKOS_KOKORO_ESPEAK_DATA", "/usr/lib/x86_64-linux-gnu/espeak-ng-data")
)
_KOKORO_PROCESS: subprocess.Popen[str] | None = None
_KOKORO_LOCK = threading.Lock()
WHISPER_WORKER = ROOT / "whisper_worker.py"
_WHISPER_PROCESS: subprocess.Popen[str] | None = None
_WHISPER_LOCK = threading.Lock()

TTS_CONFIG = ROOT / "config" / "tts.json"
TTS_ENGINES = {"kokoro", "chatterbox", "omnivoice"}
OMNIVOICE_PYTHON = Path(
    os.environ.get(
        "MYKOS_OMNIVOICE_PYTHON",
        str(ROOT.parent / "tts" / "venv_omni" / "bin" / "python")
        if (ROOT.parent / "tts" / "venv_omni" / "bin" / "python").is_file()
        else (
            str(Path.home() / ".mykos" / "tts" / "venv_omni" / "bin" / "python")
            if (Path.home() / ".mykos" / "tts" / "venv_omni" / "bin" / "python").is_file()
            else str(Path.home() / ".config" / "VoiceStudio" / "runtime" / "project" / ".venv" / "bin" / "python")
        ),
    )
)
OMNIVOICE_WORKER = ROOT / "omnivoice_worker.py"
_OMNIVOICE_PROCESS: subprocess.Popen[str] | None = None
_OMNIVOICE_LOCK = threading.Lock()

CHATTERBOX_PYTHON = Path(
    os.environ.get(
        "MYKOS_CHATTERBOX_PYTHON",
        str(ROOT.parent / "tts" / "venv_cb" / "bin" / "python")
        if (ROOT.parent / "tts" / "venv_cb" / "bin" / "python").is_file()
        else str(Path.home() / ".mykos" / "tts" / "venv_cb" / "bin" / "python"),
    )
)
CHATTERBOX_WORKER = ROOT / "chatterbox_worker.py"
VOICES_DIR = Path(os.environ.get("MYKOS_TTS_VOICES_DIR", str(ROOT / "voices")))
_CHATTERBOX_PROCESS: subprocess.Popen[str] | None = None
_CHATTERBOX_LOCK = threading.Lock()


class MediaError(RuntimeError):
    """Error seguro de una operación multimedia local."""


def _executable(name: str) -> str | None:
    return shutil.which(name)


def _tts_engine() -> str:
    """Motor de voz local: MYKOS_TTS_ENGINE, si no config/tts.json, si no Kokoro."""
    value = os.environ.get("MYKOS_TTS_ENGINE", "").strip().lower()
    if not value:
        try:
            value = str(json.loads(TTS_CONFIG.read_text(encoding="utf-8")).get("engine", "")).strip().lower()
        except (OSError, ValueError, AttributeError):
            value = ""
    return value if value in TTS_ENGINES else "kokoro"


def _text_to_speech_status() -> dict[str, Any]:
    engine = _tts_engine()
    if engine == "omnivoice":
        return {
            "available": OMNIVOICE_PYTHON.is_file() and OMNIVOICE_WORKER.is_file() and VOICES_DIR.is_dir(),
            "engine": "OmniVoice Neural local (GPU)" if OMNIVOICE_PYTHON.is_file() else None,
            "executable": str(OMNIVOICE_PYTHON),
            "voice": "alvaro",
        }
    if engine == "chatterbox":
        return {
            "available": CHATTERBOX_PYTHON.is_file() and CHATTERBOX_WORKER.is_file() and VOICES_DIR.is_dir(),
            "engine": "Chatterbox Multilingual local (GPU)" if CHATTERBOX_PYTHON.is_file() else None,
            "executable": str(CHATTERBOX_PYTHON),
            "voice": "alvaro",
        }
    return {
        "available": KOKORO_PYTHON.is_file() and KOKORO_WORKER.is_file() and KOKORO_ESPEAK_DATA.is_dir(),
        "engine": "Kokoro 82M local (CPU)" if KOKORO_PYTHON.is_file() else None,
        "executable": str(KOKORO_PYTHON),
        "voice": "em_alex",
    }


def media_status() -> dict[str, Any]:
    ffmpeg = _executable("ffmpeg")
    ffprobe = _executable("ffprobe")
    whisper_cli = _executable("whisper") or _executable("whisper.cpp")
    whisper_available = bool(whisper_cli) or (WHISPER_PYTHON.is_file() and WHISPER_WORKER.is_file())
    model_path = Path(os.environ.get("MYKOS_WHISPER_MODEL_PATH", "")).expanduser() if os.environ.get("MYKOS_WHISPER_MODEL_PATH") else Path.home() / ".cache" / "whisper" / f"{WHISPER_MODEL}.pt"
    model_available = model_path.is_file() and model_path.stat().st_size > 1024 * 1024 if model_path.exists() else False
    return {
        "ok": True,
        "platform": platform.platform(),
        "local_only": False,
        "engines": {
            "text_to_speech": _text_to_speech_status(),
            "image_generation": {
                "available": True,
                "engine": "FLUX Diffusion · Nube (Pollinations.ai)",
                "default_model": "flux",
                "remote": True,
                "provider": "Pollinations.ai",
            },
            "video_generation": {
                "available": bool(ffmpeg),
                "engine": "FFmpeg + FLUX Motion (mp4) · Pollinations.ai",
                "remote": True,
            },
            "ffmpeg": {"available": bool(ffmpeg), "executable": ffmpeg},
            "ffprobe": {"available": bool(ffprobe), "executable": ffprobe},
            "transcription_cli": {
                "available": whisper_available,
                "model_available": model_available,
                "model": WHISPER_MODEL,
                "model_path": str(model_path),
                "executable": whisper_cli or str(WHISPER_PYTHON),
            },
            "image_reading": {"available": True, "engine": "Pillow/OCR/visión existente"},
        },
        "media_directory": str(MEDIA_DIR),
        "external_services": True,
        "external_service_notice": "La generación de imágenes utiliza el servicio externo Pollinations.ai (FLUX); la descripción en texto se transmite a sus servidores.",
        "note": "La transcripción y síntesis de voz se ejecutan en local; la generación de imagen consulta el servicio externo Pollinations.ai.",
    }


def _whisper_process(engine_status) -> subprocess.Popen[str]:
    global _WHISPER_PROCESS
    if _WHISPER_PROCESS is None or _WHISPER_PROCESS.poll() is not None:
        if not WHISPER_PYTHON.is_file():
            raise MediaError(f"No se encuentra Python para Whisper: {WHISPER_PYTHON}")
        if not WHISPER_WORKER.is_file():
            raise MediaError(f"No se encuentra el trabajador de Whisper: {WHISPER_WORKER}")
        cache_dir = Path(engine_status["model_path"]).parent
        
        environment = os.environ.copy()
        extra_ld_paths = [
            Path("/home/ruben/mini/tts/venv_cb/lib/python3.12/site-packages/nvidia/cublas/lib"),
            Path("/home/ruben/mini/tts/venv_cb/lib/python3.12/site-packages/nvidia/cudnn/lib"),
            Path.home() / ".config" / "VoiceStudio" / "runtime" / "project" / ".venv" / "lib" / "python3.11" / "site-packages" / "cudnn8_compat" / "nvidia" / "cudnn" / "lib",
        ]
        valid_ld = [str(p) for p in extra_ld_paths if p.is_dir()]
        if valid_ld:
            current_ld = environment.get("LD_LIBRARY_PATH", "")
            environment["LD_LIBRARY_PATH"] = ":".join(valid_ld) + (f":{current_ld}" if current_ld else "")
        _WHISPER_PROCESS = subprocess.Popen(
            [str(WHISPER_PYTHON), "-u", str(WHISPER_WORKER), WHISPER_MODEL, str(cache_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=environment,
        )
        try:
            line = _WHISPER_PROCESS.stdout.readline()
            if not line:
                raise MediaError("El trabajador de Whisper se cerró inesperadamente durante el arranque.")
            res = json.loads(line)
            if not res.get("ok"):
                raise MediaError(f"Error al arrancar Whisper: {res.get('error')}")
        except Exception as e:
            raise MediaError(f"Fallo al iniciar el trabajador de Whisper: {e}")
    return _WHISPER_PROCESS


def transcribe_audio_file(audio_path: Path) -> dict[str, Any]:
    """Transcribe un audio con Whisper local de forma persistente."""
    status = media_status()
    engine = status["engines"]["transcription_cli"]
    if not engine.get("model_available"):
        raise MediaError(f"Falta el modelo Whisper local '{WHISPER_MODEL}'. Instálalo antes de usar el micrófono.")
    audio_path = Path(audio_path)
    if not audio_path.is_file() or audio_path.stat().st_size > MAX_TRANSCRIPTION_BYTES:
        raise MediaError("El audio no existe o supera el límite de 25 MB.")
    
    with _WHISPER_LOCK:
        try:
            process = _whisper_process(engine)
            if process.stdin is None or process.stdout is None:
                raise MediaError("El proceso de Whisper no tiene flujos de entrada/salida.")
            
            payload = json.dumps({"audio_path": str(audio_path)})
            process.stdin.write(payload + "\n")
            process.stdin.flush()
            
            line = process.stdout.readline()
        except (OSError, UnicodeError) as error:
            raise MediaError(f"No se pudo comunicar con Whisper local: {error}") from error
        
        if not line:
            raise MediaError("El trabajador de Whisper se cerró inesperadamente durante la transcripción.")
            
        try:
            result = json.loads(line)
        except json.JSONDecodeError as error:
            raise MediaError("Whisper devolvió una respuesta inválida.") from error
            
        if not result.get("ok"):
            raise MediaError(str(result.get("error") or "Whisper no pudo transcribir el audio."))
            
        return {
            "ok": True,
            "text": result.get("text", "").strip(),
            "engine": "Whisper local persistente",
            "model": WHISPER_MODEL,
            "external_services": False,
        }

def _kokoro_voice(voice: str) -> str:
    value = str(voice or "").strip().lower()
    if value in {"ef_dora", "dora", "female", "mujer"} or "female" in value:
        return "ef_dora"
    return "em_alex"


def _chatterbox_voice(voice: str) -> str:
    value = str(voice or "").strip().lower()
    if value in {"elvira", "ef_dora", "dora", "female", "mujer"} or "female" in value:
        return "elvira"
    return "alvaro"


_ANSWER_WRAPPER_KEYS = {"respuesta", "answer", "content", "response", "reply", "texto", "text", "message", "mensaje"}


def _unwrap_answer(text: str) -> str:
    """Quita el envoltorio JSON que a veces anida el modelo: {"respuesta": "..."}."""
    value = str(text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", value, flags=re.IGNORECASE)
    if fenced:
        value = fenced.group(1).strip()
    for _ in range(3):
        wrapped = (value.startswith("{") and value.endswith("}")) or (len(value) > 1 and value.startswith('"') and value.endswith('"'))
        if not wrapped:
            break
        try:
            parsed = json.loads(value)
        except ValueError:
            break
        if isinstance(parsed, str):
            value = parsed.strip()
            continue
        if isinstance(parsed, dict) and len(parsed) == 1:
            key, inner = next(iter(parsed.items()))
            if str(key).lower() in _ANSWER_WRAPPER_KEYS and isinstance(inner, str):
                value = inner.strip()
                continue
        break
    return value


def _spoken_text(text: str, natural: bool = False) -> str:
    """Reduce una respuesta de chat a texto natural para voz.

    Con natural=True (Chatterbox) se conservan comas, dos puntos y el nombre
    propio: ese motor usa la puntuación para la entonación y pronuncia bien
    «Usuario»; el recorte solo compensa las carencias de Kokoro.
    """
    value = _unwrap_answer(str(text or ""))
    value = re.sub(r"```[\s\S]*?```", " ", value)
    value = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"https?://\S+|file://\S+|[A-Za-z]:\\\S+", " ", value)
    value = re.sub(r"^\s*(?:tú|mykos|usuario)\s*[:：-]\s*", "", value, flags=re.IGNORECASE | re.MULTILINE)
    value = re.sub(r"^\s*[-*•>]\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*#{1,6}\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"([^\s.!?…:;,])[ \t]*\n+\s*", r"\1. ", value)  # un salto de línea se lee como pausa
    value = re.sub(r"[*_`~^|<>{}\[\]()\"“”«»\\/]", " ", value)
    value = re.sub(r"&", " y ", value)
    value = re.sub(r"%", " por ciento", value)
    # Unidades y símbolos pegados a números: el TTS los lee mal (y puede cambiar de idioma).
    value = re.sub(r"(\d)\s*[°º]\s*[Cc]\b", r"\1 grados centígrados", value)
    value = re.sub(r"(\d)\s*[°º]", r"\1 grados", value)
    value = re.sub(r"(?<![A-Za-z])pH\b", "pe hache", value)
    for unit, spoken in (("ml", "mililitros"), ("mL", "mililitros"), ("kg", "kilos"), ("mg", "miligramos"),
                         ("cm", "centímetros"), ("mm", "milímetros"), ("km", "kilómetros"), ("g", "gramos"), ("l", "litros")):
        value = re.sub(rf"(\d)\s*{unit}\b", rf"\1 {spoken}", value)
    value = re.sub(r"(\d),(\d)", r"\1 coma \2", value)
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    value = re.sub(r"\b(?:etc\.?|e\.g\.?|i\.e\.?)\b", " ", value, flags=re.IGNORECASE)
    if not natural:
        value = re.sub(r"[,:;]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .-\n\t")
    return value


def _kokoro_process() -> subprocess.Popen[str]:
    global _KOKORO_PROCESS
    if _KOKORO_PROCESS is None or _KOKORO_PROCESS.poll() is not None:
        if not KOKORO_PYTHON.is_file():
            raise MediaError(f"No se encuentra Python de Kokoro: {KOKORO_PYTHON}")
        if not KOKORO_WORKER.is_file():
            raise MediaError(f"No se encuentra el trabajador de Kokoro: {KOKORO_WORKER}")
        if not KOKORO_ESPEAK_DATA.is_dir():
            raise MediaError(f"No se encuentran los datos de eSpeak: {KOKORO_ESPEAK_DATA}")
        environment = os.environ.copy()
        environment["MYKOS_KOKORO_ESPEAK_DATA"] = str(KOKORO_ESPEAK_DATA)
        environment["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        _KOKORO_PROCESS = subprocess.Popen(
            [str(KOKORO_PYTHON), "-u", str(KOKORO_WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=environment,
        )
    return _KOKORO_PROCESS


def _chatterbox_process() -> subprocess.Popen[str]:
    global _CHATTERBOX_PROCESS
    if _CHATTERBOX_PROCESS is None or _CHATTERBOX_PROCESS.poll() is not None:
        if not CHATTERBOX_PYTHON.is_file():
            raise MediaError(f"No se encuentra Python de Chatterbox: {CHATTERBOX_PYTHON}")
        if not CHATTERBOX_WORKER.is_file():
            raise MediaError(f"No se encuentra el trabajador de Chatterbox: {CHATTERBOX_WORKER}")
        if not VOICES_DIR.is_dir():
            raise MediaError(f"No se encuentra la carpeta de voces: {VOICES_DIR}")
        environment = os.environ.copy()
        environment["MYKOS_TTS_VOICES_DIR"] = str(VOICES_DIR)
        environment["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        _CHATTERBOX_PROCESS = subprocess.Popen(
            [str(CHATTERBOX_PYTHON), "-u", str(CHATTERBOX_WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=environment,
        )
    return _CHATTERBOX_PROCESS


def chatterbox_audio(text: str, voice: str = "alvaro") -> dict[str, Any]:
    """Genera voz en castellano en local con Chatterbox; no usa API ni Gateway."""
    value = _spoken_text(text, natural=True)
    selected_voice = _chatterbox_voice(voice)
    if not value:
        raise MediaError("El texto de voz está vacío.")
    if len(value) > MAX_TTS_CHARS:
        raise MediaError(f"El texto no puede superar {MAX_TTS_CHARS} caracteres.")
    with _CHATTERBOX_LOCK:
        process = _chatterbox_process()
        if process.stdin is None or process.stdout is None:
            raise MediaError("El trabajador de Chatterbox no tiene sus canales disponibles.")
        try:
            process.stdin.write(json.dumps({"text": value, "voice": selected_voice}, ensure_ascii=False) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
        except (OSError, UnicodeError) as error:
            raise MediaError(f"Chatterbox no pudo comunicarse con su trabajador local: {error}") from error
    if not line:
        raise MediaError("El trabajador de Chatterbox se cerró inesperadamente.")
    try:
        result = json.loads(line)
    except json.JSONDecodeError as error:
        raise MediaError("Chatterbox devolvió una respuesta inválida.") from error
    if not result.get("ok"):
        raise MediaError(str(result.get("error") or "Chatterbox no pudo generar el audio."))
    return result


def _omnivoice_process() -> subprocess.Popen[str]:
    global _OMNIVOICE_PROCESS
    if _OMNIVOICE_PROCESS is None or _OMNIVOICE_PROCESS.poll() is not None:
        if not OMNIVOICE_PYTHON.is_file():
            raise MediaError(f"No se encuentra Python de OmniVoice: {OMNIVOICE_PYTHON}")
        if not OMNIVOICE_WORKER.is_file():
            raise MediaError(f"No se encuentra el trabajador de OmniVoice: {OMNIVOICE_WORKER}")
        if not VOICES_DIR.is_dir():
            raise MediaError(f"No se encuentra la carpeta de voces: {VOICES_DIR}")
        environment = os.environ.copy()
        environment["MYKOS_TTS_VOICES_DIR"] = str(VOICES_DIR)
        environment["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        _OMNIVOICE_PROCESS = subprocess.Popen(
            [str(OMNIVOICE_PYTHON), "-u", str(OMNIVOICE_WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=environment,
        )
    return _OMNIVOICE_PROCESS


def omnivoice_audio(text: str, voice: str = "alvaro") -> dict[str, Any]:
    """Genera voz neuronal en castellano en local con OmniVoice; no usa API ni servicios en la nube."""
    value = _spoken_text(text, natural=True)
    selected_voice = _chatterbox_voice(voice)
    if not value:
        raise MediaError("El texto de voz está vacío.")
    if len(value) > MAX_TTS_CHARS:
        raise MediaError(f"El texto no puede superar {MAX_TTS_CHARS} caracteres.")
    with _OMNIVOICE_LOCK:
        process = _omnivoice_process()
        if process.stdin is None or process.stdout is None:
            raise MediaError("El trabajador de OmniVoice no tiene sus canales disponibles.")
        try:
            process.stdin.write(json.dumps({"text": value, "voice": selected_voice}, ensure_ascii=False) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
        except (OSError, UnicodeError) as error:
            raise MediaError(f"OmniVoice no pudo comunicarse con su trabajador local: {error}") from error
    if not line:
        raise MediaError("El trabajador de OmniVoice se cerró inesperadamente.")
    try:
        result = json.loads(line)
    except json.JSONDecodeError as error:
        raise MediaError("OmniVoice devolvió una respuesta inválida.") from error
    if not result.get("ok"):
        raise MediaError(str(result.get("error") or "OmniVoice no pudo generar el audio."))
    return result


def kokoro_audio(text: str, voice: str = "em_alex") -> dict[str, Any]:
    """Genera voz local en español. Nombre histórico: despacha al motor activo.

    Por defecto usa Kokoro; con MYKOS_TTS_ENGINE=omnivoice, chatterbox o config/tts.json
    usa OmniVoice o Chatterbox. Sin API ni Gateway.
    """
    engine = _tts_engine()
    if engine == "omnivoice":
        return omnivoice_audio(text, voice)
    if engine == "chatterbox":
        return chatterbox_audio(text, voice)
    value = _spoken_text(text)
    selected_voice = _kokoro_voice(voice)
    if not value:
        raise MediaError("El texto de voz está vacío.")
    if len(value) > MAX_TTS_CHARS:
        raise MediaError(f"El texto no puede superar {MAX_TTS_CHARS} caracteres.")
    with _KOKORO_LOCK:
        process = _kokoro_process()
        if process.stdin is None or process.stdout is None:
            raise MediaError("El trabajador de Kokoro no tiene sus canales disponibles.")
        try:
            process.stdin.write(json.dumps({"text": value, "voice": selected_voice}, ensure_ascii=False) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
        except (OSError, UnicodeError) as error:
            raise MediaError(f"Kokoro no pudo comunicarse con su trabajador local: {error}") from error
    if not line:
        raise MediaError("El trabajador de Kokoro se cerró inesperadamente.")
    try:
        result = json.loads(line)
    except json.JSONDecodeError as error:
        raise MediaError("Kokoro devolvió una respuesta inválida.") from error
    if not result.get("ok"):
        raise MediaError(str(result.get("error") or "Kokoro no pudo generar el audio."))
    return result


def list_media(limit: int = 100) -> dict[str, Any]:
    limit = max(1, min(int(limit or MAX_MEDIA_FILES), MAX_MEDIA_FILES))
    if not MEDIA_DIR.exists():
        return {"ok": True, "files": [], "directory": str(MEDIA_DIR)}
    rows: list[dict[str, Any]] = []
    for path in sorted(MEDIA_DIR.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file() or path.suffix.lower() not in {".wav", ".mp3", ".mp4", ".webm", ".m4a", ".ogg"}:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append({
            "name": path.name,
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        })
        if len(rows) >= limit:
            break
    return {"ok": True, "files": rows, "directory": str(MEDIA_DIR)}


def prepare_text_to_speech(arguments: dict[str, Any]) -> dict[str, Any]:
    text = arguments.get("text", "")
    voice = str(arguments.get("voice", "")).strip()
    if not isinstance(text, str) or not text.strip():
        raise MediaError("text debe contener texto no vacío.")
    if len(text) > MAX_TTS_CHARS:
        raise MediaError(f"El texto no puede superar {MAX_TTS_CHARS} caracteres.")
    if len(voice) > 120 or any(char in voice for char in "\r\n\x00"):
        raise MediaError("La voz indicada no es válida.")
    filename = f"tts-{uuid.uuid4().hex}.wav"
    return {
        "kind": "text_to_speech",
        "text": text,
        "voice": voice,
        "filename": filename,
    }


def text_to_speech_approved(action: dict[str, Any]) -> dict[str, Any]:
    text = str(action.get("text", ""))
    if not text.strip() or len(text) > MAX_TTS_CHARS:
        raise MediaError("El texto ya no cumple los límites de síntesis.")
    voice = str(action.get("voice", "")).strip()
    filename = Path(str(action.get("filename", "")))
    if filename.name != str(filename) or filename.suffix.lower() != ".wav" or not filename.name.startswith("tts-"):
        raise MediaError("El archivo de salida no es válido.")
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    output = MEDIA_DIR / filename.name
    try:
        rendered = kokoro_audio(text, voice)
        output.write_bytes(base64.b64decode(rendered["audio"]))
    except Exception as error:
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        raise MediaError(f"Kokoro no pudo guardar el audio: {error}") from error
    if not output.exists() or output.stat().st_size == 0:
        raise MediaError("Kokoro no generó un archivo de audio válido.")
    try:
        relative_path = output.relative_to(ROOT).as_posix()
    except ValueError:
        relative_path = output.name
    return {
        "ok": True,
        "engine": rendered.get("engine", "Kokoro 82M local (CPU)"),
        "path": relative_path,
        "filename": output.name,
        "bytes": output.stat().st_size,
        "format": "wav",
        "voice": rendered.get("voice", "em_alex"),
        "external_services": False,
    }


def prepare_generate_image(arguments: dict[str, Any]) -> dict[str, Any]:
    prompt = str(arguments.get("prompt", "")).strip()
    if not prompt:
        raise MediaError("prompt debe contener una descripción de la imagen.")
    if len(prompt) > 4000:
        raise MediaError("El prompt no puede superar los 4000 caracteres.")
    aspect_ratio = str(arguments.get("aspect_ratio", "1:1")).strip()
    if aspect_ratio not in {"1:1", "16:9", "9:16", "4:3", "3:4"}:
        aspect_ratio = "1:1"
    width, height = {
        "1:1": (1024, 1024),
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "4:3": (1024, 768),
        "3:4": (768, 1024),
    }.get(aspect_ratio, (1024, 1024))
    filename = f"gen-{uuid.uuid4().hex[:12]}.jpg"
    model = str(arguments.get("model") or "flux").strip().lower()
    if model not in {"flux", "flux-realism", "flux-anime", "turbo"}:
        model = "flux"
    return {
        "kind": "generate_image",
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "width": width,
        "height": height,
        "filename": filename,
        "model": model,
    }


def _try_local_comfy_image(prompt: str, width: int, height: int, static_output: Path) -> bytes | None:
    """Try generating an image locally with ComfyUI FLUX.1 via mykos-media if ComfyUI is live."""
    comfy_cli = Path.home() / ".local" / "bin" / "mykos-media"
    if not comfy_cli.is_file():
        return None
    try:
        req = urllib.request.Request("http://127.0.0.1:8188/system_stats", headers={"User-Agent": "MyKOS/1.0"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status != 200:
                return None
    except Exception:
        return None

    tmp_png = static_output.with_suffix(".tmp.png")
    try:
        proc = subprocess.run(
            [
                str(comfy_cli),
                "image",
                "--prompt",
                prompt,
                "--width",
                str(width),
                "--height",
                str(height),
                "--output",
                str(tmp_png),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0 or not tmp_png.is_file() or tmp_png.stat().st_size < 1000:
            return None
        try:
            from PIL import Image
            buf = io.BytesIO()
            with Image.open(tmp_png) as img:
                img.convert("RGB").save(buf, format="JPEG", quality=92)
            return buf.getvalue()
        except Exception:
            return tmp_png.read_bytes()
    except Exception:
        return None
    finally:
        try:
            if tmp_png.is_file():
                tmp_png.unlink()
        except Exception:
            pass


def generate_image_approved(action: dict[str, Any]) -> dict[str, Any]:
    prompt = str(action.get("prompt", "")).strip()
    if not prompt:
        raise MediaError("Falta la descripción de la imagen.")
    width = int(action.get("width") or 1024)
    height = int(action.get("height") or 1024)
    filename = str(action.get("filename") or f"gen-{uuid.uuid4().hex[:12]}.jpg").strip()
    if not filename.startswith("gen-") or not filename.endswith(".jpg"):
        filename = f"gen-{uuid.uuid4().hex[:12]}.jpg"
    model = str(action.get("model") or "flux").strip().lower()
    if model not in {"flux", "flux-realism", "flux-anime", "turbo"}:
        model = "flux"

    static_media_dir = ROOT / "static" / "media"
    static_media_dir.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    static_output = static_media_dir / filename
    data_output = MEDIA_DIR / filename

    image_bytes: bytes | None = _try_local_comfy_image(prompt, width, height, static_output)
    last_err: Exception | None = None

    if not image_bytes or len(image_bytes) < 1000:
        import random
        encoded_prompt = urllib.parse.quote(prompt)
        seed = random.randint(1, 999999999)
        candidate_urls = [
            f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true&seed={seed}"
        ]
        models_to_try = [model]
        if model != "turbo":
            models_to_try.append("turbo")
        for target_model in models_to_try:
            candidate_urls.append(
                f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true&seed={seed}&model={target_model}"
            )

        for url in candidate_urls:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                },
            )
            for _attempt in range(2):
                try:
                    with urllib.request.urlopen(req, timeout=40) as resp:
                        image_bytes = resp.read(15 * 1024 * 1024 + 1)
                    if image_bytes and len(image_bytes) > 15 * 1024 * 1024:
                        raise RuntimeError("La imagen recibida supera el límite de seguridad de 15 MB.")
                    if image_bytes and len(image_bytes) >= 1000:
                        break
                except urllib.error.HTTPError as exc:
                    last_err = exc
                    if exc.code in {402, 429, 503}:
                        try:
                            body = exc.read().decode("utf-8", "ignore")
                            m = re.search(r"Retry after (\d+)s", body)
                            wait_sec = int(m.group(1)) if m else None
                        except Exception:
                            wait_sec = None
                        if wait_sec is not None:
                            if wait_sec <= 15:
                                time.sleep(wait_sec + 1)
                            else:
                                raise MediaError(
                                    f"El generador de imágenes tiene un límite temporal de uso. Por favor espera {wait_sec} segundos antes de pedir otra."
                                )
                        else:
                            time.sleep(1.5)
                    else:
                        time.sleep(1.0)
                except Exception as exc:
                    last_err = exc
                    time.sleep(1.0)
            if image_bytes and len(image_bytes) >= 1000:
                break

    if not image_bytes or len(image_bytes) < 1000:
        raise MediaError(f"Error al generar la imagen: {last_err or 'el servicio no devolvió datos válidos'}")

    static_output.write_bytes(image_bytes)
    try:
        data_output.write_bytes(image_bytes)
    except Exception:
        pass

    web_url = f"/static/media/{filename}"
    return {
        "ok": True,
        "filename": filename,
        "path": f"static/media/{filename}",
        "url": web_url,
        "bytes": len(image_bytes),
        "format": "jpg",
        "prompt": prompt,
        "markdown": f"![{prompt}]({web_url})",
        "message": f"Imagen generada con éxito y disponible en {web_url}.\n\n![{prompt}]({web_url})",
    }


def prepare_generate_video(arguments: dict[str, Any]) -> dict[str, Any]:
    prompt = str(arguments.get("prompt", "")).strip()
    image_url = str(arguments.get("image_url", "") or arguments.get("image_path", "")).strip()
    if not prompt and not image_url:
        raise MediaError("Debes indicar una descripción (prompt) o la URL de una imagen para generar el vídeo.")
    if len(prompt) > 4000:
        raise MediaError("El prompt no puede superar los 4000 caracteres.")

    duration = int(arguments.get("duration_seconds") or 4)
    if duration < 2:
        duration = 2
    elif duration > 10:
        duration = 10

    motion = str(arguments.get("motion", "cinematic")).strip().lower()
    if motion not in {"cinematic", "zoom_in", "zoom_out", "pan_left", "pan_right"}:
        motion = "cinematic"

    aspect_ratio = str(arguments.get("aspect_ratio", "1:1")).strip()
    if aspect_ratio not in {"1:1", "16:9", "9:16", "4:3", "3:4"}:
        aspect_ratio = "1:1"

    filename = f"gen-{uuid.uuid4().hex[:12]}.mp4"
    return {
        "kind": "generate_video",
        "prompt": prompt or "Animación cinemática",
        "image_url": image_url,
        "duration_seconds": duration,
        "motion": motion,
        "aspect_ratio": aspect_ratio,
        "filename": filename,
    }


def generate_video_approved(action: dict[str, Any]) -> dict[str, Any]:
    prompt = str(action.get("prompt", "")).strip()
    image_url = str(action.get("image_url", "")).strip()
    duration = int(action.get("duration_seconds") or 4)
    motion = str(action.get("motion", "cinematic")).strip().lower()
    aspect_ratio = str(action.get("aspect_ratio", "1:1")).strip()
    filename = str(action.get("filename") or f"gen-{uuid.uuid4().hex[:12]}.mp4").strip()
    if not filename.startswith("gen-") or not filename.endswith(".mp4"):
        filename = f"gen-{uuid.uuid4().hex[:12]}.mp4"

    static_media_dir = ROOT / "static" / "media"
    static_media_dir.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    static_output = static_media_dir / filename
    data_output = MEDIA_DIR / filename

    source_img_path: Path | None = None
    if image_url:
        clean_name = Path(image_url).name
        for candidate_dir in (static_media_dir, MEDIA_DIR):
            cand = candidate_dir / clean_name
            if cand.exists() and cand.is_file():
                source_img_path = cand
                break

    if not source_img_path or not source_img_path.exists():
        # Check if there is a recently generated image in static/media to animate if no prompt
        if not prompt and static_media_dir.exists():
            recent_imgs = sorted(static_media_dir.glob("gen-*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
            if recent_imgs:
                source_img_path = recent_imgs[0]

        if not source_img_path or not source_img_path.exists():
            img_action = {
                "prompt": prompt or "futuristic cinematic scene, neon lighting, 8k",
                "aspect_ratio": aspect_ratio,
                "model": "flux",
            }
            img_result = generate_image_approved(img_action)
            img_name = img_result.get("filename")
            if img_name:
                cand = static_media_dir / img_name
                if cand.exists():
                    source_img_path = cand

    if not source_img_path or not source_img_path.exists():
        raise MediaError("No se pudo obtener o generar la imagen base para el vídeo.")

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise MediaError("ffmpeg no está instalado en el sistema para renderizar vídeo.")

    width, height = {
        "1:1": (768, 768),
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "4:3": (960, 720),
        "3:4": (720, 960),
    }.get(aspect_ratio, (768, 768))

    total_frames = duration * 30
    if motion == "zoom_in":
        vf = f"zoompan=z='min(zoom+0.0018,1.3)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps=30"
    elif motion == "zoom_out":
        vf = f"zoompan=z='if(lte(zoom,1.0),1.3,max(1.001,zoom-0.0018))':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps=30"
    elif motion == "pan_right":
        vf = f"zoompan=z=1.2:d={total_frames}:x='min((on/{total_frames})*(iw-iw/zoom),iw-iw/zoom)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps=30"
    elif motion == "pan_left":
        vf = f"zoompan=z=1.2:d={total_frames}:x='max(0,(1-on/{total_frames})*(iw-iw/zoom))':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps=30"
    else:  # cinematic smooth zoom
        vf = f"zoompan=z='min(zoom+0.0014,1.22)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps=30"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-loop", "1",
        "-i", str(source_img_path),
        "-vf", vf,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(static_output),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
        if proc.returncode != 0:
            err_msg = proc.stderr.decode("utf-8", errors="replace")[-500:]
            raise MediaError(f"Error al codificar el vídeo con ffmpeg: {err_msg}")
    except subprocess.TimeoutExpired as exc:
        raise MediaError("El proceso de renderizado de vídeo superó el tiempo límite.") from exc

    try:
        shutil.copy2(static_output, data_output)
    except Exception:
        pass

    web_url = f"/static/media/{filename}"
    file_bytes = static_output.stat().st_size if static_output.exists() else 0
    return {
        "ok": True,
        "filename": filename,
        "path": f"static/media/{filename}",
        "url": web_url,
        "bytes": file_bytes,
        "format": "mp4",
        "duration_seconds": duration,
        "prompt": prompt,
        "markdown": f"![video]({web_url})",
        "message": f"Vídeo generado con éxito y disponible en {web_url}.\n\n![video]({web_url})",
    }
