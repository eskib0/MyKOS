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
DEFAULT_BIN_CANDIDATES = [
    Path.home() / ".local" / "llama-quick" / "llama-b12211" / "llama-server",
    Path.home() / ".local" / "bin" / "llama-server",
    Path.home() / ".local" / "bin" / "llama",
    Path.home() / "llama.cpp" / "build" / "bin" / "llama-server",
]
DEFAULT_BIN = next((p for p in DEFAULT_BIN_CANDIDATES if p.is_file()), DEFAULT_BIN_CANDIDATES[-1])
LLAMA_CPP_EXE = os.environ.get("MYKOS_LLAMA_CPP_EXE", str(DEFAULT_BIN)).strip()

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


def _is_failed_server_model(item: dict[str, Any]) -> bool:
    st = item.get("status") if isinstance(item.get("status"), dict) else {}
    return bool(st.get("failed")) or str(st.get("value") or "").strip().lower() == "failed"


def _match_server_model_id(models_list: list[dict[str, Any]], target_key: str) -> str:
    """Devuelve el ID exacto de un modelo válido en /v1/models que coincida con target_key."""
    req = target_key.strip().lower()
    if not req:
        return ""
    valid = [m for m in models_list if isinstance(m, dict) and m.get("id") and not _is_failed_server_model(m)]
    # Priorizar modelos ya cargados antes que en reposo
    ordered = sorted(
        valid,
        key=lambda m: 0 if (isinstance(m.get("status"), dict) and m["status"].get("value") == "loaded") else 1,
    )
    for m in ordered:
        mid = str(m["id"]).strip()
        if mid.lower() == req:
            return mid
    for m in ordered:
        mid = str(m["id"]).strip()
        low = mid.lower()
        if low.endswith(f"/{req}") or req.endswith(f"/{low}") or low.split(":", 1)[0] == req.split(":", 1)[0]:
            return mid
    return ""


def llamacpp_status() -> dict[str, Any]:
    """Comprueba si llama-server está en línea y qué modelo tiene cargado."""
    try:
        health = llamacpp_request("/health", timeout=1)
        health_status = str(health.get("status") or "").strip()
        if health_status in {"ok", "loading model"}:
            loaded = ""
            data_list: list[dict[str, Any]] = []
            try:
                models_data = llamacpp_request("/v1/models", timeout=2)
                raw_list = models_data.get("data", [])
                if isinstance(raw_list, list):
                    data_list = [m for m in raw_list if isinstance(m, dict)]
                    for m in data_list:
                        st = m.get("status") if isinstance(m.get("status"), dict) else {}
                        if st.get("value") == "loaded" and not _is_failed_server_model(m):
                            loaded = str(m.get("id") or "")
                            break
                    if not loaded and len(data_list) == 1 and not _is_failed_server_model(data_list[0]):
                        st = data_list[0].get("status") if isinstance(data_list[0].get("status"), dict) else {}
                        if not st or st.get("value") != "unloaded":
                            loaded = str(data_list[0].get("id") or "")
            except Exception:
                pass
            return {
                "online": True,
                "loaded_model": loaded or _CURRENT_MODEL_KEY,
                "status": health_status,
                "models": data_list,
            }
    except Exception:
        pass
    return {"online": False, "loaded_model": "", "status": "offline", "models": []}


def get_available_gguf_models() -> dict[str, dict[str, Any]]:
    """Devuelve los modelos GGUF encontrados en MODELS_DIR y en la caché de Hugging Face de llama.cpp."""
    models: dict[str, dict[str, Any]] = {}
    ini = _load_ini_presets()
    default_section = ini["*"] if "*" in ini else (ini["default"] if "default" in ini else {})

    candidates: list[Path] = []
    if MODELS_DIR.is_dir():
        for item in sorted(MODELS_DIR.iterdir()):
            if (item.is_file() or item.is_symlink()) and item.name.endswith(".gguf"):
                candidates.append(item)

    if HF_HUB_DIR.is_dir():
        for item in sorted(HF_HUB_DIR.glob("models--*/**/snapshots/*/*.gguf")):
            if item.name.lower().startswith(("mmproj-", "dflash-")):
                continue
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


def _extract_args_ctx_and_model(args: Any) -> tuple[int, str]:
    """Extrae --ctx-size / -c y --model desde los argumentos de estado de llama-server."""
    if not isinstance(args, list):
        return 0, ""
    ctx = 0
    model_path = ""
    for i, token in enumerate(args):
        if i + 1 >= len(args):
            continue
        if token in {"--ctx-size", "-c"}:
            try:
                ctx = int(args[i + 1])
            except (TypeError, ValueError):
                pass
        elif token in {"--model", "-m"}:
            model_path = str(args[i + 1] or "")
    return ctx, model_path


def _format_param_count(n_params: Any) -> str:
    try:
        val = int(n_params)
    except (TypeError, ValueError):
        return ""
    if val >= 1_000_000_000:
        billions = val / 1_000_000_000
        return f"{billions:.0f}B" if abs(billions - round(billions)) < 0.1 else f"{billions:.1f}B"
    if val >= 1_000_000:
        return f"{val / 1_000_000:.0f}M"
    return ""


def _infer_quant_from_id(model_id: str, meta: dict[str, Any]) -> str:
    ftype = str(meta.get("ftype") or "").strip()
    if ftype:
        return ftype
    if ":" in model_id:
        return model_id.rsplit(":", 1)[1].strip()
    return "GGUF"


def _match_available_gguf(model_id: str, model_path: str, available: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if model_path:
        for info in available.values():
            try:
                if Path(model_path).resolve() == Path(info["path"]).resolve():
                    return info
            except Exception:
                if model_path == info["path"]:
                    return info
    clean = model_id.lower().split(":", 1)[0].replace("-gguf", "").replace("_", "-")
    for key, info in available.items():
        clean_key = key.lower().replace("-gguf", "").replace("_", "-")
        if (
            model_id == key
            or model_id.endswith(f"/{key}")
            or clean == clean_key
            or clean.endswith(f"/{clean_key}")
        ):
            return info
    return None


def llamacpp_model_catalog() -> list[dict[str, Any]]:
    """Devuelve todos los modelos válidos de llama.cpp para el catálogo /api/models de MyKOS.
    Solo muestra modelos si el servidor llama.cpp está ONLINE y activo.
    Excluye modelos en estado failed.
    """
    status = llamacpp_status()
    if not status.get("online"):
        return []

    data_list = [m for m in (status.get("models") or []) if isinstance(m, dict)]
    available = get_available_gguf_models()
    catalog: list[dict[str, Any]] = []

    for m in data_list:
        model_id = str(m.get("id") or "").strip()
        if not model_id or _is_failed_server_model(m):
            continue

        st = m.get("status") if isinstance(m.get("status"), dict) else {}
        st_val = str(st.get("value") or "").strip().lower()
        is_loaded = (st_val == "loaded") if st_val else True

        meta = m.get("meta") if isinstance(m.get("meta"), dict) else {}
        args_ctx, args_model_path = _extract_args_ctx_and_model(st.get("args"))
        matched_info = _match_available_gguf(model_id, args_model_path, available)

        size_bytes = int(meta.get("size") or (matched_info or {}).get("size") or 0)
        param_size = (
            _format_param_count(meta.get("n_params"))
            or str((matched_info or {}).get("parameter_size") or "")
            or ("Activo" if is_loaded else "GGUF")
        )
        family = str((matched_info or {}).get("family") or m.get("owned_by") or "llama.cpp GGUF")
        ctx_size = int(
            meta.get("n_ctx")
            or args_ctx
            or (matched_info or {}).get("ctx_size")
            or m.get("context_length")
            or 32768
        )
        arch = m.get("architecture") if isinstance(m.get("architecture"), dict) else {}
        input_mods = [str(x).lower() for x in (arch.get("input_modalities") or [])]
        vision_capable = "image" in input_mods

        caps = ["chat", "completion", "thinking", "tools"] + (["vision"] if vision_capable else [])
        catalog.append({
            "name": f"llama_cpp/{model_id}",
            "label": f"llama.cpp · {model_id}",
            "provider": "llama_cpp",
            "provider_label": "llama.cpp · CUDA",
            "size": size_bytes,
            "parameter_size": param_size,
            "family": family,
            "quantization": _infer_quant_from_id(model_id, meta),
            "modified_at": "",
            "capabilities": caps,
            "chat_capable": True,
            "vision_capable": vision_capable,
            "thinking_capable": True,
            "tools_capable": True,
            "context_length": ctx_size,
            "remote": False,
            "remote_host": "",
            "benchmark_capable": True,
            "engine": "llama.cpp 0.9 (Cargado)" if is_loaded else "llama.cpp 0.9 (En reposo)",
            "status": "online" if is_loaded else "standby",
        })

    if not catalog and not data_list:
        model_name = str(status.get("loaded_model") or "").strip() or "llama-model"
        catalog.append({
            "name": f"llama_cpp/{model_name}",
            "label": f"llama.cpp · {model_name}",
            "provider": "llama_cpp",
            "provider_label": "llama.cpp · CUDA",
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


def _resolve_online_llama_model(status: dict[str, Any], clean_key: str) -> str:
    """Resuelve clean_key contra el servidor llama.cpp activo si ya sirve el modelo o es el alias genérico."""
    if not status.get("online"):
        return ""
    models_list = [m for m in (status.get("models") or []) if isinstance(m, dict)]
    if clean_key in {"", "mykos-cuda"}:
        if status.get("loaded_model"):
            return str(status["loaded_model"])
        first_valid = next((str(m.get("id") or "") for m in models_list if m.get("id") and not _is_failed_server_model(m)), "")
        return first_valid or "mykos-cuda"
    matched_id = _match_server_model_id(models_list, clean_key)
    if matched_id:
        return matched_id
    if not models_list and _CURRENT_MODEL_KEY == clean_key:
        return clean_key
    return ""


def ensure_llamacpp_model(model_name: str) -> str:
    """Asegura que el modelo solicitado esté cargado en llama-server y devuelve su ID efectivo."""
    global _SERVER_PROCESS, _CURRENT_MODEL_KEY

    clean_key = str(model_name or "").strip()
    if clean_key.startswith("llama_cpp/"):
        clean_key = clean_key[len("llama_cpp/"):]
    if clean_key.startswith("llamacpp/"):
        clean_key = clean_key[len("llamacpp/"):]

    status = llamacpp_status()
    resolved_online = _resolve_online_llama_model(status, clean_key)
    if resolved_online:
        return resolved_online

    with _SERVER_LOCK:
        # Volver a verificar con cerrojo adquirido
        status = llamacpp_status()
        resolved_online = _resolve_online_llama_model(status, clean_key)
        if resolved_online:
            return resolved_online

        available = get_available_gguf_models()
        if clean_key in {"", "mykos-cuda"}:
            if not available:
                raise RuntimeError(f"No se encuentra ningún modelo GGUF para llama.cpp en {MODELS_DIR}")
            clean_key = next(iter(available))
        elif clean_key not in available:
            lower_target = clean_key.lower()
            norm_target = lower_target.split(":", 1)[0].replace("-gguf", "").replace("_", "-")
            matched = next(
                (
                    k for k in available
                    if k.lower() == lower_target
                    or k.lower().replace("-gguf", "").replace("_", "-") == norm_target
                    or norm_target.endswith(f"/{k.lower().replace('-gguf', '').replace('_', '-')}")
                ),
                "",
            )
            if matched:
                clean_key = matched
            else:
                raise RuntimeError(f"Modelo GGUF '{clean_key}' no disponible en {MODELS_DIR} ni en la caché de Hugging Face.")

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
                    return clean_key
            except Exception:
                pass
            time.sleep(0.5)

        raise TimeoutError(f"llama-server tardó demasiado en cargar {clean_key}.")


def llamacpp_chat_request(
    messages: list[dict[str, Any]],
    generation: dict[str, Any],
    tool_schemas: list[dict[str, Any]] | None = None,
    model_name: str = "mykos-cuda",
    gateway_requester: Any = None,
) -> dict[str, Any]:
    """Envía la petición de chat a llama.cpp 0.9 y extrae el texto, herramientas y telemetría."""
    options = generation.get("options") if isinstance(generation, dict) else {}
    options = options if isinstance(options, dict) else {}

    clean_model = str(model_name or "").strip()
    if clean_model.startswith("llama_cpp/"):
        clean_model = clean_model[len("llama_cpp/"):]
    if clean_model.startswith("llamacpp/"):
        clean_model = clean_model[len("llamacpp/"):]

    # Asegurar que el modelo está en marcha y usar su ID efectivo en la petición
    resolved_model = ensure_llamacpp_model(clean_model)
    raw_temp = options.get("temperature")

    payload: dict[str, Any] = {
        "model": resolved_model,
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
        "temperature": float(raw_temp) if raw_temp is not None else 0.5,
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
