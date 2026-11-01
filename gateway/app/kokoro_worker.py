from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import sys
import traceback


SAMPLE_RATE = 24_000
ESPEAK_DATA_PATH = os.environ.get(
    "MYKOS_KOKORO_ESPEAK_DATA",
    "/usr/lib/x86_64-linux-gnu/espeak-ng-data",
)


def _load_pipeline():
    with contextlib.redirect_stdout(sys.stderr):
        from kokoro import KPipeline
        from phonemizer.backend.espeak.wrapper import EspeakWrapper

        if os.path.isdir(ESPEAK_DATA_PATH):
            EspeakWrapper.set_data_path(ESPEAK_DATA_PATH)
        return KPipeline(lang_code="e", device="cpu")


def _render(pipeline, text: str, voice: str) -> bytes:
    import numpy as np
    import soundfile as sf

    with contextlib.redirect_stdout(sys.stderr):
        chunks = [
            result.audio.detach().cpu().numpy()
            for result in pipeline(text, voice=voice, speed=1.0)
            if result.audio is not None
        ]
    if not chunks:
        raise RuntimeError("Kokoro no devolvió audio")
    audio = np.concatenate(chunks)
    output = io.BytesIO()
    sf.write(output, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return output.getvalue()


def main() -> None:
    pipeline = None
    for line in sys.stdin:
        try:
            request = json.loads(line)
            text = str(request.get("text", "")).strip()
            voice = str(request.get("voice", "em_alex")).strip() or "em_alex"
            if not text:
                raise ValueError("El texto de voz está vacío")
            if pipeline is None:
                pipeline = _load_pipeline()
            audio = _render(pipeline, text, voice)
            response = {
                "ok": True,
                "audio": base64.b64encode(audio).decode("ascii"),
                "content_type": "audio/wav",
                "voice": voice,
                "engine": "Kokoro 82M local (CPU)",
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
