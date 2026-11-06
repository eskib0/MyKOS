"""Motor de pruebas de rendimiento (benchmarks) de modelos locales de MyKOS.
"""
from __future__ import annotations

import time
import threading
from typing import Any, Callable

from worker_helpers import ApiError

BENCHMARK_OUTPUT_TOKENS = 192
BENCHMARK_PROFILES = {
    "fast": {
        "label": "Rápido",
        "description": "Contexto corto y respuesta ágil.",
        "generation": {"effort": "off", "speed": "fast", "creativity": "precise"},
    },
    "balanced": {
        "label": "Equilibrado",
        "description": "Contexto medio para tareas cotidianas.",
        "generation": {"effort": "off", "speed": "balanced", "creativity": "balanced"},
    },
    "coding": {
        "label": "Código",
        "description": "Instrucción técnica con algo más de contexto.",
        "generation": {"effort": "off", "speed": "coding", "creativity": "precise"},
    },
    "quality": {
        "label": "Calidad",
        "description": "Contexto amplio para evaluar estabilidad.",
        "generation": {"effort": "off", "speed": "quality", "creativity": "balanced"},
    },
}
BENCHMARK_PROMPT = (
    "Responde en español con una sola frase breve (máximo 20 palabras) confirmando "
    "que esta prueba de rendimiento ha terminado."
)
BENCHMARK_LOCK = threading.Lock()


def benchmark_profile_catalog() -> list[dict[str, str]]:
    return [
        {
            "id": profile_id,
            "label": str(profile.get("label", profile_id)),
            "description": str(profile.get("description", "")),
        }
        for profile_id, profile in BENCHMARK_PROFILES.items()
    ]


def _metric_ms(value: Any, fallback_ms: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return round(fallback_ms, 1)
    if numeric <= 0:
        return round(fallback_ms, 1)
    return round(numeric / 1_000_000, 1)


def _rate_per_second(count: Any, duration_ns: Any) -> float | None:
    try:
        tokens = float(count)
        duration = float(duration_ns)
    except (TypeError, ValueError):
        return None
    if tokens <= 0 or duration <= 0:
        return None
    return round(tokens / (duration / 1_000_000_000), 1)


def run_model_benchmark(
    model: str,
    selected_model: dict[str, Any],
    profile_id: str,
    *,
    normalise_settings_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    ollama_request_fn: Callable[..., dict[str, Any]],
    llama_cpp_chat_fn: Callable[..., dict[str, Any]],
    strata_chat_fn: Callable[..., dict[str, Any]],
    gateway_requester: Any = None,
    utc_now_fn: Callable[[], str],
) -> dict[str, Any]:
    profile = BENCHMARK_PROFILES[profile_id]
    generation = normalise_settings_fn(
        profile.get("generation", {}),
        selected_model,
    )
    # El benchmark mide latencia y rendimiento del motor, no calidad de
    # razonamiento. Desactivarlo aquí evita que una respuesta de 192 tokens
    # se consuma entera en pensamiento y no llegue al texto final.
    generation["effort"] = "off"
    generation["think"] = False
    options = dict(generation.get("options") or {})
    # La salida corta hace comparables las pruebas y evita que un modelo
    # convierta el benchmark en una conversación larga.
    options["num_predict"] = BENCHMARK_OUTPUT_TOKENS
    if selected_model.get("provider") in {"llama_cpp", "strata"}:
        provider_name = str(selected_model.get("provider"))
        started_ns = time.perf_counter_ns()
        try:
            if provider_name == "strata":
                result = strata_chat_fn(
                    [{"role": "user", "content": BENCHMARK_PROMPT}],
                    {**generation, "options": options},
                    model_name=model,
                    gateway_requester=gateway_requester,
                )
            else:
                result = llama_cpp_chat_fn(
                    [{"role": "user", "content": BENCHMARK_PROMPT}],
                    {**generation, "options": options},
                )
        except RuntimeError as error:
            return {
                "profile": profile_id,
                "label": profile.get("label", profile_id),
                "ok": False,
                "error": str(error),
                "context": options.get("num_ctx", 0),
                "thinking": False,
            }
        wall_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        choices = result.get("choices") if isinstance(result.get("choices"), list) else []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        response_message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        response_text = str(response_message.get("content") or response_message.get("reasoning_content") or "").strip()
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        timings = result.get("timings") if isinstance(result.get("timings"), dict) else {}
        output_tokens = int(usage.get("completion_tokens", 0) or timings.get("predicted_n", 0) or 0)
        prompt_tokens = int(usage.get("prompt_tokens", 0) or timings.get("prompt_n", 0) or 0)
        try:
            prompt_ms = round(float(timings.get("prompt_ms", 0) or 0), 1)
        except (TypeError, ValueError):
            prompt_ms = 0.0
        try:
            eval_ms = round(float(timings.get("predicted_ms", 0) or 0), 1)
        except (TypeError, ValueError):
            eval_ms = 0.0
        prompt_rate = timings.get("prompt_per_second")
        output_rate = timings.get("predicted_per_second")
        if not isinstance(prompt_rate, (int, float)):
            prompt_rate = _rate_per_second(prompt_tokens, prompt_ms * 1_000_000)
        if not isinstance(output_rate, (int, float)):
            output_rate = _rate_per_second(output_tokens, (eval_ms or wall_ms) * 1_000_000)
        engine_label = "Strata" if provider_name == "strata" else "llama.cpp"
        return {
            "profile": profile_id,
            "label": profile.get("label", profile_id),
            "description": profile.get("description", ""),
            "ok": bool(response_text),
            "error": "" if response_text else f"{engine_label} terminó sin devolver texto.",
            "context": options.get("num_ctx", 0),
            "thinking": False,
            "temperature": options.get("temperature"),
            "total_ms": round(wall_ms, 1),
            "wall_ms": round(wall_ms, 1),
            "load_ms": max(0.0, round(wall_ms - prompt_ms - eval_ms, 1)),
            "prompt_ms": prompt_ms,
            "eval_ms": eval_ms,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "prompt_tokens_per_second": round(float(prompt_rate), 1) if isinstance(prompt_rate, (int, float)) else None,
            "tokens_per_second": round(float(output_rate), 1) if isinstance(output_rate, (int, float)) else None,
            "sample": response_text[:240],
            "generated_at": utc_now_fn(),
        }
    ollama_model = model.removeprefix("qwen-cli/") if isinstance(model, str) else model
    payload = {
        "model": ollama_model,
        "messages": [{"role": "user", "content": BENCHMARK_PROMPT}],
        "stream": False,
        "think": generation.get("think", False),
        "options": options,
        "keep_alive": "5m",
    }
    started_ns = time.perf_counter_ns()
    try:
        result = ollama_request_fn("/api/chat", payload, timeout=900)
    except RuntimeError as error:
        return {
            "profile": profile_id,
            "label": profile.get("label", profile_id),
            "ok": False,
            "error": str(error),
            "context": options.get("num_ctx", 0),
            "thinking": generation.get("think", False),
        }

    wall_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
    response_message = result.get("message") or {}
    response_text = str(response_message.get("content", "")).strip()
    total_duration_ns = result.get("total_duration")
    if not total_duration_ns:
        total_duration_ns = wall_ms * 1_000_000
    eval_count = result.get("eval_count", 0)
    prompt_eval_count = result.get("prompt_eval_count", 0)
    eval_duration = result.get("eval_duration", 0)
    prompt_eval_duration = result.get("prompt_eval_duration", 0)
    return {
        "profile": profile_id,
        "label": profile.get("label", profile_id),
        "description": profile.get("description", ""),
        "ok": bool(response_text),
        "error": "" if response_text else "Ollama terminó sin devolver texto.",
        "context": options.get("num_ctx", 0),
        "thinking": generation.get("think", False),
        "temperature": options.get("temperature"),
        "total_ms": _metric_ms(total_duration_ns, wall_ms),
        "wall_ms": round(wall_ms, 1),
        "load_ms": _metric_ms(result.get("load_duration")),
        "prompt_ms": _metric_ms(prompt_eval_duration),
        "eval_ms": _metric_ms(eval_duration),
        "prompt_tokens": int(prompt_eval_count or 0),
        "output_tokens": int(eval_count or 0),
        "prompt_tokens_per_second": _rate_per_second(prompt_eval_count, prompt_eval_duration),
        "tokens_per_second": _rate_per_second(eval_count, eval_duration),
        "sample": response_text[:240],
        "generated_at": utc_now_fn(),
    }


def execute_benchmark_suite(
    payload: dict[str, Any],
    *,
    get_models_fn: Callable[[], list[dict[str, Any]]],
    available_chat_models_fn: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    choose_default_model_fn: Callable[[list[dict[str, Any]]], str],
    normalise_settings_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    ollama_request_fn: Callable[..., dict[str, Any]],
    llama_cpp_chat_fn: Callable[..., dict[str, Any]],
    strata_chat_fn: Callable[..., dict[str, Any]],
    gateway_requester: Any = None,
    utc_now_fn: Callable[[], str],
) -> dict[str, Any]:
    requested_model = str(payload.get("model", "")).strip()
    raw_profiles = payload.get("profiles")
    if isinstance(raw_profiles, list):
        profile_ids = [str(item).strip().casefold() for item in raw_profiles]
    else:
        profile_ids = ["fast", "balanced", "deep"]
    profile_ids = list(dict.fromkeys(profile_ids))
    if not profile_ids:
        raise ApiError("Selecciona al menos un perfil de rendimiento.")
    if len(profile_ids) > 4:
        raise ApiError("El benchmark admite como máximo cuatro perfiles.")
    unknown = [profile_id for profile_id in profile_ids if profile_id not in BENCHMARK_PROFILES]
    if unknown:
        raise ApiError(f"Perfil de rendimiento no válido: {', '.join(unknown)}.")

    models = available_chat_models_fn(get_models_fn())
    model = requested_model or choose_default_model_fn(models)
    selected_model = next((item for item in models if item.get("name") == model), None)
    if selected_model is None:
        raise ApiError(f"El modelo '{model}' no está disponible para chat.")
    if selected_model.get("remote"):
        raise ApiError("El panel de rendimiento solo mide modelos locales para evitar consumo remoto accidental.")
    if not BENCHMARK_LOCK.acquire(blocking=False):
        raise ApiError("Ya hay una medición en curso. Espera a que termine antes de iniciar otra.")
    try:
        results = [
            run_model_benchmark(
                model,
                selected_model,
                profile_id,
                normalise_settings_fn=normalise_settings_fn,
                ollama_request_fn=ollama_request_fn,
                llama_cpp_chat_fn=llama_cpp_chat_fn,
                strata_chat_fn=strata_chat_fn,
                gateway_requester=gateway_requester,
                utc_now_fn=utc_now_fn,
            )
            for profile_id in profile_ids
        ]
    finally:
        BENCHMARK_LOCK.release()
    return {
        "ok": True,
        "model": model,
        "remote": bool(selected_model.get("remote")),
        "context_length": selected_model.get("context_length", 0),
        "results": results,
    }
