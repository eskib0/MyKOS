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


SAMPLE_RATE = 24_000
LANGUAGE = "es"
PAUSE_SECONDS = 0.15
VOICES_DIR = Path(
    os.environ.get("MYKOS_TTS_VOICES_DIR", str(Path(__file__).resolve().parent / "voices"))
)
DEVICE = os.environ.get("MYKOS_CHATTERBOX_DEVICE", "cuda").strip() or "cuda"
active_device = DEVICE

def _load_model():
    global active_device
    # Las bibliotecas escriben en stdout; ese canal es el protocolo JSON.
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        target = DEVICE
        if target.startswith("cuda") and not torch.cuda.is_available():
            target = "cpu"
        try:
            if target.startswith("cuda") and torch.cuda.is_available():
                torch.cuda.empty_cache()
            model = ChatterboxMultilingualTTS.from_pretrained(device=target)
            active_device = target
            return model
        except Exception as e:
            if "out of memory" in str(e).lower() and target != "cpu":
                sys.stderr.write("Chatterbox: VRAM llena, reintentando tras vaciar caché...\n")
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    import time
                    time.sleep(1.0)
                    try:
                        model = ChatterboxMultilingualTTS.from_pretrained(device=target)
                        active_device = target
                        return model
                    except Exception:
                        pass
                sys.stderr.write("Chatterbox: VRAM no disponible, usando CPU como respaldo...\n")
                if hasattr(torch, "set_num_threads"):
                    torch.set_num_threads(min(4, os.cpu_count() or 4))
                model = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
                active_device = "cpu"
                return model
            raise


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…;:])\s+", text.strip())
    chunks: list[str] = []
    buffer = ""
    for part in parts:  # agrupa fragmentos cortos para no romper la prosodia
        buffer = f"{buffer} {part}".strip()
        if len(buffer) >= 40:
            chunks.append(buffer)
            buffer = ""
    if buffer:
        chunks.append(buffer)
    return chunks or [text]


def _render(model, state: dict, text: str, voice: str) -> bytes:
    import numpy as np
    import soundfile as sf

    reference = VOICES_DIR / f"ref_{voice}.wav"
    if not reference.is_file():
        raise FileNotFoundError(f"No existe la voz de referencia: {reference.name}")
    pause = np.zeros(int(SAMPLE_RATE * PAUSE_SECONDS), dtype=np.float32)
    pieces = []
    with contextlib.redirect_stdout(sys.stderr):
        if state.get("voice") != voice:  # la referencia se procesa una vez por voz
            model.prepare_conditionals(str(reference))
            state["voice"] = voice
        for sentence in _split_sentences(text):
            audio = model.generate(sentence, language_id=LANGUAGE)
            pieces.append(audio.squeeze().cpu().numpy().astype(np.float32))
            pieces.append(pause)
    if not pieces:
        raise RuntimeError("Chatterbox no devolvió audio")
    output = io.BytesIO()
    sf.write(output, np.concatenate(pieces[:-1]), model.sr, format="WAV", subtype="PCM_16")
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
                "engine": f"Chatterbox Multilingual local ({'GPU' if active_device.startswith('cuda') else 'CPU'})",
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
