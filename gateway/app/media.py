from __future__ import annotations

import base64
import io
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parent
MEDIA_DIR = ROOT / "data" / "media"
MAX_TTS_CHARS = 12_000
MAX_MEDIA_FILES = 100
MAX_TRANSCRIPTION_BYTES = 25 * 1024 * 1024

def _detect_whisper_model() -> str:
    env_m = os.environ.get("MYKOS_WHISPER_MODEL", "").strip()
    if env_m:
        return env_m
    cache_dir = Path.home() / ".cache" / "whisper"
    if (cache_dir / "large-v3-turbo.pt").is_file():
        return "large-v3-turbo"
    for name in ("medium", "small", "base", "tiny"):
        if (cache_dir / f"{name}.pt").is_file():
            return name
    return "base"

WHISPER_MODEL = _detect_whisper_model()
WHISPER_PYTHON = Path(
    os.environ.get(
        "MYKOS_WHISPER_PYTHON",
        str(Path.home() / ".mykos" / "venv" / "bin" / "python")
        if (Path.home() / ".mykos" / "venv" / "bin" / "python").is_file()
        else (
            str(ROOT.parent / ".venv" / "bin" / "python")
            if (ROOT.parent / ".venv" / "bin" / "python").is_file()
            else (shutil.which("python3") or "/usr/bin/python3")
        ),
    )
)
KOKORO_PYTHON = Path(
    os.environ.get("MYKOS_KOKORO_PYTHON", shutil.which("python3") or "/usr/bin/python3")
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
TTS_ENGINES = {"kokoro", "chatterbox"}
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
    if _tts_engine() == "chatterbox":
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
        "local_only": True,
        "engines": {
            "text_to_speech": _text_to_speech_status(),
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
        "external_services": False,
        "note": "La transcripción requiere un modelo Whisper local ya disponible; no se descarga automáticamente.",
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


def kokoro_audio(text: str, voice: str = "em_alex") -> dict[str, Any]:
    """Genera voz local en español. Nombre histórico: despacha al motor activo.

    Por defecto usa Kokoro; con MYKOS_TTS_ENGINE=chatterbox o config/tts.json
    ({"engine": "chatterbox"}) usa Chatterbox. Sin API ni Gateway.
    """
    if _tts_engine() == "chatterbox":
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
    return {
        "kind": "generate_image",
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "width": width,
        "height": height,
        "filename": filename,
    }


def generate_image_approved(action: dict[str, Any]) -> dict[str, Any]:
    prompt = str(action.get("prompt", "")).strip()
    if not prompt:
        raise MediaError("Falta la descripción de la imagen.")
    width = int(action.get("width") or 1024)
    height = int(action.get("height") or 1024)
    filename = str(action.get("filename") or f"gen-{uuid.uuid4().hex[:12]}.jpg").strip()
    if not filename.startswith("gen-") or not filename.endswith(".jpg"):
        filename = f"gen-{uuid.uuid4().hex[:12]}.jpg"

    static_media_dir = ROOT / "static" / "media"
    static_media_dir.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    static_output = static_media_dir / filename
    data_output = MEDIA_DIR / filename

    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        },
    )

    image_bytes: bytes | None = None
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                image_bytes = resp.read()
            if image_bytes and len(image_bytes) >= 1000:
                break
        except Exception as exc:
            last_err = exc
            time.sleep(1.2)

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
