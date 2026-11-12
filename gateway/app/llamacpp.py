"""
Módulo de integración con llama.cpp 0.9 (llama-server) para MyKOS.
Proporciona inferencia ultrarrápida en C++ nativo con aceleración CUDA,
catálogo dinámico de modelos GGUF locales y compatibilidad total con la API OpenAI.
"""
from __future__ import annotations

import configparser
import json
import logging
import os
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger("mykos.llamacpp")

LLAMA_CPP_URL = os.environ.get("MYKOS_LLAMA_CPP_URL", "http://127.0.0.1:9931").rstrip("/")
LLAMA_CPP_TIMEOUT_SECONDS = int(os.environ.get("MYKOS_LLAMA_CPP_TIMEOUT", "600"))
LLAMA_CPP_START_TIMEOUT = int(os.environ.get("MYKOS_LLAMA_CPP_START_TIMEOUT", "60"))

# Rutas estándar del binario llama.cpp 0.9 y modelos
DEFAULT_BIN = Path.home() / ".local" / "llama-quick" / "llama-b12211" / "llama-server"
LLAMA_CPP_EXE = os.environ.get("MYKOS_LLAMA_CPP_EXE", str(DEFAULT_BIN if DEFAULT_BIN.is_file() else Path.home() / "llama.cpp" / "build" / "bin" / "llama-server")).strip()

MODELS_DIR = Path(os.environ.get("MYKOS_MODELS_DIR", str(Path.home() / "models")))
MODELS_INI = MODELS_DIR / "models.ini"
HF_HUB_DIR = Path.home() / ".cache" / "huggingface" / "hub"

CUDA_LIB_PATHS = [
    Path.home() / ".local" / "llama-quick" / "llama-b12211",
    Path("/usr/local/lib/ollama/cuda_v12"),
    Path("/usr/local/cuda/lib64"),
]

# Proceso administrado
_SERVER_PROCESS: subprocess.Popen[str] | None = None
_SERVER_LOCK = threading.RLock()
_CURRENT_MODEL_KEY = ""


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    valid_paths = [str(p) for p in CUDA_LIB_PATHS if p.is_dir()]
    if valid_paths:
        current_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = ":".join(valid_paths) + (f":{current_ld}" if current_ld else "")
    return env


def _load_ini_presets() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    if MODELS_INI.is_file():
        try:
            config.read(str(MODELS_INI), encoding="utf-8")
        except Exception as e:
            logger.warning(f"No se pudo leer models.ini: {e}")
    return config


def llamacpp_request(path: str, payload: dict[str, Any] | None = None, timeout: int = 5) -> dict[str, Any]:
    url = f"{LLAMA_CPP_URL}{path}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise RuntimeError(f"llama.cpp no responde en {LLAMA_CPP_URL}: {err}") from err


def llamacpp_status() -> dict[str, Any]:
    """Comprueba si llama-server está en línea y qué modelo tiene cargado."""
    try:
        health = llamacpp_request("/health", timeout=1)
        if health.get("status") in {"ok", "loading model"}:
            loaded = ""
            try:
                models_data = llamacpp_request("/v1/models", timeout=2)
                data_list = models_data.get("data", [])
                for m in data_list:
                    if isinstance(m, dict) and m.get("status", {}).get("value") == "loaded":
                        loaded = m.get("id", "")
                        break
                if not loaded and data_list:
                    for m in data_list:
                        if isinstance(m, dict) and not m.get("status", {}).get("failed"):
                            loaded = m.get("id", "")
                            break
                if not loaded and data_list and isinstance(data_list[0], dict):
                    loaded = data_list[0].get("id", "")
            except Exception:
                pass
            return {"online": True, "loaded_model": loaded or _CURRENT_MODEL_KEY, "status": health.get("status")}
    except Exception:
        pass
    return {"online": False, "loaded_model": "", "status": "offline"}


def get_available_gguf_models() -> dict[str, dict[str, Any]]:
    """Devuelve los modelos GGUF encontrados en MODELS_DIR y en la caché de Hugging Face de llama.cpp."""
    models: dict[str, dict[str, Any]] = {}
    ini = _load_ini_presets()
    default_section = ini["default"] if "default" in ini else {}

    candidates: list[Path] = []
    if MODELS_DIR.is_dir():
        for item in sorted(MODELS_DIR.iterdir()):
            if (item.is_file() or item.is_symlink()) and item.name.endswith(".gguf"):
                candidates.append(item)

    if HF_HUB_DIR.is_dir():
        for item in sorted(HF_HUB_DIR.glob("models--*/**/snapshots/*/*.gguf")):
            try:
                if item.stat().st_size > 200_000_000:
                    candidates.append(item)
            except Exception:
                pass

    for item in candidates:
        key = item.stem  # e.g. "GLM-4.7-Flash" o "qwen2.5-7b"
        if key.endswith(("-Q4_K", "-Q4_0", "-Q8_0", "-Q5_K_M", "-Q6_K")):
            key = key.rsplit("-", 1)[0]

        resolved_path = item.resolve()
        size_bytes = resolved_path.stat().st_size if resolved_path.is_file() else 0

        # Evitar duplicados si ya está registrado
        if key in models or any(m["path"] == str(resolved_path) for m in models.values()):
            continue

        lower_key = key.lower()
        section = ini[key] if key in ini else (ini[lower_key] if lower_key in ini else default_section)
        n_gpu_layers = int(section.get("n-gpu-layers", section.get("ngl", 6 if ("35b" in lower_key or "glm" in lower_key or "74b" in lower_key) else 20)))
        ctx_size = int(section.get("ctx-size", section.get("c", 32768)))
        reasoning = str(section.get("reasoning", "auto")).strip().lower()

        # Determinar familia y parámetros a partir del nombre
        if "glm" in lower_key:
            param_size = "Flash (MoE)" if "flash" in lower_key else "GLM"
            family = "Zhipu AI · GLM-4.7"
        elif "74b" in lower_key:
            param_size = "74B (MoE)"
            family = "Nemotron 3.5 · NV-Bolt"
        elif "35b" in lower_key:
            param_size = "35B (MoE)"
            family = "Qwen3.6 / Qwen3.8"
        elif "27b" in lower_key:
            param_size = "27B"
            family = "Qwen3.8 · NVFP4"
        elif "7b" in lower_key:
            param_size = "7B"
            family = "Qwen 2.5"
        elif "0.8b" in lower_key or "1b" in lower_key:
            param_size = "1B"
            family = "Qwen"
        else:
            param_size = "Local GGUF"
            family = "llama.cpp"

        models[key] = {
            "key": key,
            "path": str(resolved_path),
            "label": f"llama.cpp 0.9 · {key}",
            "size": size_bytes,
            "parameter_size": param_size,
            "family": family,
            "n_gpu_layers": n_gpu_layers,
            "ctx_size": ctx_size,
            "reasoning": reasoning,
        }

    return models


def llamacpp_model_catalog() -> list[dict[str, Any]]:
    """Devuelve los modelos de llama.cpp para el catálogo /api/models de MyKOS.
    Solo muestra modelos si el servidor llama.cpp está ONLINE y activo.
    Si llama.cpp está apagado, no se muestra ningún modelo fantasma en el selector.
    """
    status = llamacpp_status()
    online = status.get("online", False)
    if not online:
        return []

    loaded = status.get("loaded_model", "")
    available = get_available_gguf_models()
    catalog = []

    # Si hay un modelo cargado y coincide con un modelo registrado en ~/models o HF
    matched = False
    clean_loaded = loaded.lower().replace("-gguf", "").replace(":q4_k", "").replace(":q8_0", "").replace("_", "-")
    for key, info in available.items():
        clean_key = key.lower().replace("-gguf", "").replace("_", "-")
        if (loaded == key or loaded.endswith(f"/{key}") or loaded == info["path"]
            or clean_key in clean_loaded or clean_loaded.endswith(f"/{clean_key}")):
            matched = True
            catalog.append({
                "name": f"llama_cpp/{loaded}",
                "label": f"llama.cpp 0.9 · {key}",
                "provider": "llama_cpp",
                "provider_label": "llama.cpp 0.9 · CUDA",
                "size": info["size"],
                "parameter_size": info["parameter_size"],
                "family": info["family"],
                "quantization": "GGUF",
                "modified_at": "",
                "capabilities": ["chat", "completion", "thinking", "tools"],
                "chat_capable": True,
                "vision_capable": False,
                "thinking_capable": True,
                "tools_capable": True,
                "context_length": info["ctx_size"],
                "remote": False,
                "remote_host": "",
                "benchmark_capable": True,
                "engine": "llama.cpp 0.9 (En línea)",
                "status": "online",
            })
            break

    # Si el servidor llama.cpp está online con un modelo genérico o alias directo
    if not matched:
        model_name = loaded or "llama-model"
        catalog.append({
            "name": f"llama_cpp/{model_name}",
            "label": f"llama.cpp 0.9 · {model_name}",
            "provider": "llama_cpp",
            "provider_label": "llama.cpp 0.9 · CUDA",
            "size": 0,
            "parameter_size": "Activo",
            "family": "llama.cpp GGUF",
            "quantization": "GGUF",
            "modified_at": "",
            "capabilities": ["chat", "completion", "thinking", "tools"],
            "chat_capable": True,
            "vision_capable": False,
            "thinking_capable": True,
            "tools_capable": True,
            "context_length": 32768,
            "remote": False,
            "remote_host": "",
            "benchmark_capable": True,
            "engine": "llama.cpp 0.9 (En línea)",
            "status": "online",
        })

    return catalog


def unload_ollama_models(ollama_url: str = "http://127.0.0.1:11434") -> None:
    """Libera la VRAM de Ollama antes de arrancar llama.cpp si hay modelos cargados."""
    try:
        req = urllib.request.Request(f"{ollama_url.rstrip('/')}/api/ps", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=1) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models", [])
            for m in models:
                name = m.get("name") or m.get("model")
                if name:
                    payload = json.dumps({"model": name, "keep_alive": 0}).encode("utf-8")
                    gen_req = urllib.request.Request(
                        f"{ollama_url.rstrip('/')}/api/generate",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(gen_req, timeout=2):
                        pass
    except Exception:
        pass


def stop_llamacpp_server() -> None:
    """Detiene el servidor llama.cpp gestionado si está en marcha."""
    global _SERVER_PROCESS, _CURRENT_MODEL_KEY
    with _SERVER_LOCK:
        if _SERVER_PROCESS is not None:
            try:
                _SERVER_PROCESS.terminate()
                _SERVER_PROCESS.wait(timeout=3)
            except Exception:
                try:
                    _SERVER_PROCESS.kill()
                except Exception:
                    pass
            _SERVER_PROCESS = None
            _CURRENT_MODEL_KEY = ""
        try:
            from core.activity import LLAMA_PID_FILE
            if LLAMA_PID_FILE.is_file():
                LLAMA_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass


def ensure_llamacpp_model(model_name: str) -> None:
    """Asegura que el modelo solicitado esté cargado en llama-server."""
    global _SERVER_PROCESS, _CURRENT_MODEL_KEY

    clean_key = model_name
    if clean_key.startswith("llama_cpp/"):
        clean_key = clean_key[len("llama_cpp/"):]
    if clean_key.startswith("llamacpp/"):
        clean_key = clean_key[len("llamacpp/"):]
    if clean_key == "mykos-cuda":
        clean_key = "qwen2.5-7b"

    status = llamacpp_status()
    if status["online"]:
        if status.get("loaded_model") == clean_key or _CURRENT_MODEL_KEY == clean_key:
            return

    with _SERVER_LOCK:
        # Volver a verificar con cerrojo adquirido
        status = llamacpp_status()
        if status["online"] and (status.get("loaded_model") == clean_key or _CURRENT_MODEL_KEY == clean_key):
            return

        available = get_available_gguf_models()
        if clean_key not in available:
            # Buscar por coincidencia insensible a mayúsculas o nombre base
            matched = next((k for k in available if k.lower() == clean_key.lower()), "")
            if matched:
                clean_key = matched
            elif available:
                clean_key = next(iter(available))
            else:
                raise RuntimeError(f"No se encuentra ningún modelo GGUF para llama.cpp en {MODELS_DIR}")

        info = available[clean_key]
        model_path = info["path"]
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"No existe el archivo del modelo: {model_path}")

        if not Path(LLAMA_CPP_EXE).is_file():
            raise FileNotFoundError(f"No existe el binario de llama.cpp: {LLAMA_CPP_EXE}")

        # Descargar modelos de Ollama de la GPU para evitar OOM
        unload_ollama_models()

        # Detener servidor anterior si estaba activo
        stop_llamacpp_server()

        parsed_url = urllib.parse.urlparse(LLAMA_CPP_URL)
        port = str(parsed_url.port or 9931)
        host = parsed_url.hostname or "127.0.0.1"

        cmd = [
            LLAMA_CPP_EXE,
            "-m", model_path,
            "-c", str(info["ctx_size"]),
            "-ngl", str(info["n_gpu_layers"]),
            "-np", "1",
            "-fa", "auto",
            "--no-webui",
            "--host", host,
            "--port", port,
            "--alias", clean_key,
        ]
        reasoning_opt = str(info.get("reasoning", "")).strip().lower()
        if reasoning_opt in ("off", "on", "auto"):
            cmd.extend(["--reasoning", reasoning_opt])

        logger.info(f"Arrancando llama-server para {clean_key}: {' '.join(cmd)}")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

        _SERVER_PROCESS = subprocess.Popen(
            cmd,
            cwd=str(Path(LLAMA_CPP_EXE).parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_build_env(),
            creationflags=creationflags,
        )
        _CURRENT_MODEL_KEY = clean_key

        try:
            from core.activity import LLAMA_PID_FILE, _process_starttime
            LLAMA_PID_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            pid = int(_SERVER_PROCESS.pid)
            st = _process_starttime(pid)
            payload = json.dumps({"pid": pid, "starttime": st}, ensure_ascii=False)
            LLAMA_PID_FILE.write_text(payload, encoding="utf-8")
            try:
                os.chmod(LLAMA_PID_FILE, 0o600)
            except OSError:
                pass
        except Exception:
            pass

        deadline = time.monotonic() + LLAMA_CPP_START_TIMEOUT
        while time.monotonic() < deadline:
            if _SERVER_PROCESS.poll() is not None:
                code = _SERVER_PROCESS.returncode
                _SERVER_PROCESS = None
                _CURRENT_MODEL_KEY = ""
                raise RuntimeError(f"llama-server terminó inesperadamente (código {code}).")
            try:
                h = llamacpp_request("/health", timeout=1)
                if h.get("status") == "ok":
                    logger.info(f"llama-server listo con modelo {clean_key}")
                    return
            except Exception:
                pass
            time.sleep(0.5)

        raise TimeoutError(f"llama-server tardó demasiado en cargar {clean_key}.")


def llamacpp_chat_request(
    messages: list[dict[str, Any]],
    generation: dict[str, Any],
    tool_schemas: list[dict[str, Any]] | None = None,
    model_name: str = "qwen2.5-7b",
    gateway_requester: Any = None,
) -> dict[str, Any]:
    """Envía la petición de chat a llama.cpp 0.9 y extrae el texto, herramientas y telemetría."""
    options = generation.get("options") if isinstance(generation, dict) else {}
    options = options if isinstance(options, dict) else {}

    clean_model = model_name
    if clean_model.startswith("llama_cpp/"):
        clean_model = clean_model[len("llama_cpp/"):]
    if clean_model.startswith("llamacpp/"):
        clean_model = clean_model[len("llamacpp/"):]

    # Asegurar que el modelo está en marcha
    ensure_llamacpp_model(clean_model)

    payload: dict[str, Any] = {
        "model": clean_model,
        "messages": [
            {
                key: value
                for key, value in item.items()
                if key in {"role", "content", "images", "tool_calls", "tool_call_id"}
            }
            for item in messages
        ],
        "stream": False,
        "max_tokens": int(options.get("num_predict", 2048) or 2048),
        "temperature": float(options.get("temperature", 0.5) or 0.5),
    }

    effort = str(generation.get("effort", "")).strip().casefold()
    if effort == "off":
        payload["reasoning_effort"] = "none"
    elif effort in {"low", "medium", "high"}:
        payload["reasoning_effort"] = effort

    if tool_schemas:
        payload["tools"] = tool_schemas
        payload["tool_choice"] = "auto"

    if gateway_requester is not None:
        return gateway_requester("llama_cpp", payload)

    return llamacpp_request("/v1/chat/completions", payload, timeout=LLAMA_CPP_TIMEOUT_SECONDS)
