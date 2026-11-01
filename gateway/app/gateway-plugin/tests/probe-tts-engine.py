"""Prueba del selector de motor de voz local (Kokoro / Chatterbox) de media.py.

No toca el servicio real: importa media.py directamente. Comprueba:
  1. sin configuración el motor es Kokoro (comportamiento anterior);
  2. MYKOS_TTS_ENGINE y config/tts.json activan Chatterbox; el valor inválido cae a Kokoro;
  3. el texto hablado conserva comas y el nombre con Chatterbox y los recorta con Kokoro;
  4. (opcional, --real) una síntesis real con Chatterbox: WAV válido en 24 kHz.

Uso: py -3.11 gateway-plugin/tests/probe-tts-engine.py [--real]
"""
import base64, io, json, os, sys, tempfile, time, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.pop("MYKOS_TTS_ENGINE", None)

import media  # noqa: E402

failures = 0


def check(name, ok, detail=""):
    global failures
    print(("OK   " if ok else "FALLO"), name, detail)
    if not ok:
        failures += 1


with tempfile.TemporaryDirectory() as tmp:
    media.TTS_CONFIG = Path(tmp) / "tts.json"

    check("sin config: kokoro", media._tts_engine() == "kokoro")
    media.TTS_CONFIG.write_text(json.dumps({"engine": "chatterbox"}), encoding="utf-8")
    check("config/tts.json: chatterbox", media._tts_engine() == "chatterbox")
    media.TTS_CONFIG.write_text("no es json", encoding="utf-8")
    check("config corrupta: kokoro", media._tts_engine() == "kokoro")
    media.TTS_CONFIG.write_text(json.dumps({"engine": "otro"}), encoding="utf-8")
    check("motor desconocido: kokoro", media._tts_engine() == "kokoro")
    media.TTS_CONFIG.write_text(json.dumps({"engine": "chatterbox"}), encoding="utf-8")
    os.environ["MYKOS_TTS_ENGINE"] = "kokoro"
    check("la variable de entorno manda sobre el fichero", media._tts_engine() == "kokoro")
    os.environ.pop("MYKOS_TTS_ENGINE")

status_default = media.media_status()["engines"]["text_to_speech"]
check("estado por defecto describe Kokoro", "Kokoro" in str(status_default.get("engine")), str(status_default.get("engine")))
os.environ["MYKOS_TTS_ENGINE"] = "chatterbox"
status_cb = media.media_status()["engines"]["text_to_speech"]
check("estado con Chatterbox", "Chatterbox" in str(status_cb.get("engine")) and status_cb["available"], str(status_cb))

sample = "Hola Usuario, ¿qué tal? Mira esto: funciona."
kokoro_text = media._spoken_text(sample)
natural_text = media._spoken_text(sample, natural=True)
check("kokoro recorta comas y nombre", "," not in kokoro_text and "Rub" not in kokoro_text, repr(kokoro_text))
check("chatterbox conserva comas y nombre", "," in natural_text and "Usuario" in natural_text, repr(natural_text))
wrapped = '{"respuesta":"Entendido, Usuario. Todo listo."}'
check("quita el envoltorio JSON del modelo (natural)", media._spoken_text(wrapped, natural=True) == "Entendido, Usuario. Todo listo", repr(media._spoken_text(wrapped, natural=True)))  # el punto final ya se recortaba antes
check("quita el envoltorio JSON del modelo (Kokoro)", "respuesta" not in media._spoken_text(wrapped) and "{" not in media._spoken_text(wrapped), repr(media._spoken_text(wrapped)))
symbols = media._spoken_text('Mira "esto" {ahora} [aquí] (bien) «así» \\ 50% y a/b', natural=True)
check("no deja comillas, llaves ni corchetes para leer", not any(ch in symbols for ch in '"{}[]()«»\\/%'), repr(symbols))
check("un salto de línea es una pausa", media._spoken_text("Resumen\nTodo bien", natural=True) == "Resumen. Todo bien", repr(media._spoken_text("Resumen\nTodo bien", natural=True)))
check("voz masculina por defecto", media._chatterbox_voice("") == "alvaro" and media._chatterbox_voice("em_alex") == "alvaro")
check("voz femenina", media._chatterbox_voice("ef_dora") == "elvira" and media._chatterbox_voice("mujer") == "elvira")

if "--real" in sys.argv:
    os.environ["MYKOS_TTS_ENGINE"] = "chatterbox"
    t0 = time.time()
    result = media.kokoro_audio("Hola Usuario, soy Igor. ¿Qué tal ha ido el obrador esta mañana?", "alvaro")
    first = time.time() - t0
    t1 = time.time()
    media.kokoro_audio("Segunda frase de prueba para medir el modelo ya cargado.", "alvaro")
    second = time.time() - t1
    audio = base64.b64decode(result["audio"])
    with wave.open(io.BytesIO(audio)) as w:
        seconds = w.getnframes() / w.getframerate()
        check("WAV real 24 kHz mono", w.getframerate() == 24000 and w.getnchannels() == 1, f"{seconds:.1f}s de audio")
    check("motor declarado", "Chatterbox" in result.get("engine", ""), result.get("engine", ""))
    print(f"     primera llamada (carga del modelo): {first:.1f}s; segunda: {second:.1f}s")
    out = ROOT / "data" / "media" / "probe-tts-chatterbox.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    print("     guardado en", out)
    if media._CHATTERBOX_PROCESS is not None:
        media._CHATTERBOX_PROCESS.terminate()

print("\nRESULTADO:", "todo correcto" if failures == 0 else f"{failures} fallo(s)")
sys.exit(1 if failures else 0)
