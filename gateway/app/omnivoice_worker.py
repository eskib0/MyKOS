#!/usr/bin/env python3
from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import re
import sys
import traceback
from pathlib import Path

SAMPLE_RATE = 48_000
LANGUAGE = "Spanish"
PAUSE_SECONDS = 0.15
VOICES_DIR = Path(
    os.environ.get("MYKOS_TTS_VOICES_DIR", str(Path(__file__).resolve().parent / "voices"))
)
DEVICE = os.environ.get("MYKOS_OMNIVOICE_DEVICE", "cuda").strip() or "cuda"
active_device = DEVICE


def _load_model():
    global active_device
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        from omnivoice.models.omnivoice import OmniVoice

        target = DEVICE
        if target.startswith("cuda") and not torch.cuda.is_available():
            target = "cpu"

        dtype = torch.float16 if target.startswith("cuda") else torch.float32
        try:
            if target.startswith("cuda") and torch.cuda.is_available():
                torch.cuda.empty_cache()
            model = OmniVoice.from_pretrained(
                "k2-fsa/OmniVoice",
                device_map=target,
                dtype=dtype
            )
            # Mantener tokenizer acústico en CPU para ahorrar 1.5 GB VRAM
            if hasattr(model, "audio_tokenizer") and model.audio_tokenizer is not None and target.startswith("cuda"):
                model.audio_tokenizer.to("cpu")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            active_device = target
            return model
        except Exception as e:
            if "out of memory" in str(e).lower() and target != "cpu":
                sys.stderr.write("OmniVoice: VRAM llena, usando CPU como respaldo...\n")
                if hasattr(torch, "set_num_threads"):
                    torch.set_num_threads(min(4, os.cpu_count() or 4))
                model = OmniVoice.from_pretrained(
                    "k2-fsa/OmniVoice",
                    device_map="cpu",
                    dtype=torch.float32
                )
                active_device = "cpu"
                return model
            raise


def _get_instruct(voice: str) -> str:
    v = str(voice or "").strip().lower()
    if v in {"elvira", "ef_dora", "dora", "female", "mujer"} or "female" in v:
        return "female, moderate pitch"
    return "male, low pitch"


def _normalize_text_for_voice(text: str) -> str:
    s = text.strip()
    s = re.sub(r"[¿¡]", "", s)
    s = re.sub(r"\bMyKOS\b", "Maikos", s, flags=re.IGNORECASE)
    s = re.sub(r"\bTTS\b", "te te ese", s)
    s = re.sub(r"\bVRAM\b", "uve ram", s)
    s = re.sub(r"\bGPU\b", "ge pe u", s)
    s = re.sub(r"\bCPU\b", "ce pe u", s)
    s = re.sub(r"\bNDJSON\b", "ene de jeison", s, flags=re.IGNORECASE)
    s = re.sub(r"\bJSON\b", "jeison", s, flags=re.IGNORECASE)
    s = re.sub(r"\bstreaming\b", "estriming", s, flags=re.IGNORECASE)
    s = re.sub(r"\brouter\b", "rúter", s, flags=re.IGNORECASE)
    s = re.sub(r"\bfallback\b", "respaldo", s, flags=re.IGNORECASE)
    s = re.sub(r"\btimeout\b", "taimaut", s, flags=re.IGNORECASE)
    s = re.sub(r"\bchunks?\b", "trozos", s, flags=re.IGNORECASE)
    s = re.sub(r"\.{2,}|…", ",", s)
    # En bloques cortos o medios (< 220 car.), convertir cortes internos (!, ?, .) en coma + minúscula
    # para que OmniVoice no reinicie el locutor entre la exclamación inicial y el resto de la frase.
    s = re.sub(
        r"[?!.]+\s+([A-ZÁÉÍÓÚÑa-záéíóúñ])",
        lambda m: f", {m.group(1).lower()}" if len(s) < 220 else f". {m.group(1)}",
        s,
    )
    s = re.sub(r"[?!]+", ".", s)
    s = re.sub(r",\s*,+", ",", s)
    s = re.sub(r"\s+", " ", s).strip(" ,;.")
    if s and not s[-1] in ".!?…。！？":
        s += "."
    return s


def _get_prompt(model, state: dict, voice: str, short_variant: bool = False):
    import soundfile as sf
    import torch

    v = str(voice or "").strip().lower()
    voice_key = "elvira" if (v in {"elvira", "ef_dora", "dora", "female", "mujer"} or "female" in v) else "alvaro"
    cache_key = f"{voice_key}_short" if (short_variant and voice_key == "alvaro") else voice_key
    prompts = state.setdefault("prompts", {})
    if cache_key in prompts:
        return prompts[cache_key]

    ref_audio = VOICES_DIR / f"ref_{voice_key}.wav"
    if not ref_audio.is_file():
        voice_key = "alvaro"
        cache_key = "alvaro_short" if short_variant else "alvaro"
        ref_audio = VOICES_DIR / "ref_alvaro.wav"
        if not ref_audio.is_file():
            raise FileNotFoundError(f"No existe audio de referencia para la voz: {voice}")

    if cache_key == "alvaro_short":
        wav_data, sr_in = sf.read(str(ref_audio))
        start_sample = int(2.35 * sr_in)
        if len(wav_data) > start_sample + sr_in:
            wav_tensor = torch.from_numpy(wav_data[start_sample:].astype("float32")).unsqueeze(0)
            short_ref_text = "Te presento a MyKOS, tu propio sistema operativo de inteligencia artificial, cien por cien local."
            with contextlib.redirect_stdout(sys.stderr):
                prompt = model.create_voice_clone_prompt(
                    ref_audio=(wav_tensor, sr_in),
                    ref_text=short_ref_text,
                )
            prompts[cache_key] = prompt
            return prompt

    ref_txt_path = VOICES_DIR / f"ref_{voice_key}.txt"
    if ref_txt_path.is_file():
        ref_text = ref_txt_path.read_text(encoding="utf-8").strip()
    else:
        ref_text = "Buenos días, Rubén. Hoy hace un día estupendo en Pinoso, así que después del obrador podríamos acercarnos a la sierra a buscar níscalos."

    with contextlib.redirect_stdout(sys.stderr):
        prompt = model.create_voice_clone_prompt(
            ref_audio=str(ref_audio),
            ref_text=ref_text
        )
    prompts[cache_key] = prompt
    return prompt


def _split_sentences(text: str) -> list[str]:
    text = text.strip()
    if len(text) <= 500:
        return [text]
    parts = re.split(r"(?<=[.!?…;:])\s+", text)
    chunks: list[str] = []
    buffer = ""
    for part in parts:
        if not part.strip():
            continue
        buffer = f"{buffer} {part}".strip()
        if len(buffer) >= 240:
            chunks.append(buffer)
            buffer = ""
    if buffer:
        if chunks and len(buffer) < 90:
            chunks[-1] = f"{chunks[-1]} {buffer}".strip()
        else:
            chunks.append(buffer)
    return chunks or [text]


def _spectral_centroid(audio_arr, sr: int) -> float:
    import numpy as np

    if len(audio_arr) == 0:
        return 0.0
    fft = np.abs(np.fft.rfft(audio_arr))
    freqs = np.fft.rfftfreq(len(audio_arr), 1.0 / sr)
    return float(np.sum(freqs * fft) / (np.sum(fft) + 1e-9))


def _render(model, state: dict, text: str, voice: str) -> bytes:
    import numpy as np
    import soundfile as sf
    import torch

    prompt = _get_prompt(model, state, voice, short_variant=False)
    # En modo Voice Clone (con prompt de referencia) instruct debe ser None para no
    # activar el modo Voice Design de OmniVoice, que muestrea timbres distintos en frases cortas.
    instruct = None if prompt is not None else _get_instruct(voice)
    sr = getattr(model, "sampling_rate", SAMPLE_RATE)
    pause = np.zeros(int(sr * PAUSE_SECONDS), dtype=np.float32)
    pieces = []

    with contextlib.redirect_stdout(sys.stderr):
        for raw_sentence in _split_sentences(text):
            sentence = _normalize_text_for_voice(raw_sentence)
            if not sentence.strip():
                continue
            use_short = len(sentence) < 60
            active_prompt = _get_prompt(model, state, voice, short_variant=True) if use_short else prompt
            torch.manual_seed(42)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(42)
            aud = model.generate(
                text=sentence,
                language=LANGUAGE,
                voice_clone_prompt=active_prompt,
                instruct=instruct,
                speed=1.05,
                num_step=32,
                guidance_scale=2.2,
                position_temperature=0.5,
                class_temperature=0.0,
            )
            # aud[0] es tensor [1, samples] o [samples]
            audio_arr = aud[0].squeeze().cpu().numpy().astype(np.float32)
            if not use_short and _spectral_centroid(audio_arr, sr) > 2000.0:
                short_prompt = _get_prompt(model, state, voice, short_variant=True)
                torch.manual_seed(42)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(42)
                aud_retry = model.generate(
                    text=sentence,
                    language=LANGUAGE,
                    voice_clone_prompt=short_prompt,
                    instruct=instruct,
                    speed=1.05,
                    num_step=32,
                    guidance_scale=2.2,
                    position_temperature=0.5,
                    class_temperature=0.0,
                )
                retry_arr = aud_retry[0].squeeze().cpu().numpy().astype(np.float32)
                if _spectral_centroid(retry_arr, sr) < _spectral_centroid(audio_arr, sr):
                    audio_arr = retry_arr
            pieces.append(audio_arr)
            pieces.append(pause)

    if not pieces:
        raise RuntimeError("OmniVoice no devolvió audio.")

    concatenated = np.concatenate(pieces[:-1]) if len(pieces) > 1 else pieces[0]
    output = io.BytesIO()
    sf.write(output, concatenated, sr, format="WAV", subtype="PCM_16")
    return output.getvalue()


def main() -> None:
    model = None
    state: dict = {}
    for line in sys.stdin:
        try:
            request = json.loads(line)
            text = str(request.get("text", "")).strip()
            voice = str(request.get("voice", "alvaro")).strip() or "alvaro"
            if not text:
                raise ValueError("El texto de voz está vacío")
            if model is None:
                model = _load_model()
            audio = _render(model, state, text, voice)
            response = {
                "ok": True,
                "audio": base64.b64encode(audio).decode("ascii"),
                "content_type": "audio/wav",
                "voice": voice,
                "engine": f"OmniVoice Neural local ({'GPU' if active_device.startswith('cuda') else 'CPU'})",
                "external_services": False,
                "api_key_required": False,
            }
        except Exception as error:
            response = {
                "ok": False,
                "error": str(error),
                "traceback": traceback.format_exc(limit=2),
            }
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
