import sys
import os
import json
import warnings
import traceback

warnings.filterwarnings("ignore")

def is_hallucination(text):
    t = text.strip().lower()
    hallucinations = [
        "gracias", "gracias.", "muchas gracias", "muchas gracias.",
        "subtítulos realizados por", "subtitulaci", 
        "suscríbete", "dale a like", "continuará", "continuará..."
    ]
    for h in hallucinations:
        if t == h or (h in t and len(t) < 30):
            return True
    return False

def main():
    try:
        model_name = sys.argv[1] if len(sys.argv) > 1 else "small"
        model_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~/.cache/whisper")
        
        # Intentar cargar con faster-whisper (CTranslate2) primero
        use_faster = False
        model = None
        try:
            from faster_whisper import WhisperModel
            import torch
            
            # Comprobar si CUDA está disponible para faster-whisper
            device = "cpu"
            compute_type = "int8"
            if torch.cuda.is_available():
                try:
                    test_model = WhisperModel(model_name, device="cuda", compute_type="float16", download_root=model_dir)
                    model = test_model
                    device = "cuda"
                    compute_type = "float16"
                    use_faster = True
                except Exception:
                    pass
            
            if not use_faster:
                model = WhisperModel(model_name, device="cpu", compute_type="int8", download_root=model_dir)
                use_faster = True
                device = "cpu"
                compute_type = "int8"
                
            sys.stderr.write(f"Whisper cargado con faster-whisper ({device}, {compute_type})\n")
        except Exception as e:
            sys.stderr.write(f"No se pudo cargar faster-whisper ({e}), usando whisper oficial...\n")
            import whisper
            model = whisper.load_model(model_name, download_root=model_dir)
            use_faster = False
            
        print(json.dumps({"ok": True, "event": "ready", "engine": "faster-whisper" if use_faster else "whisper"}), flush=True)
        
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            try:
                req = json.loads(line)
                audio_path = req["audio_path"]
                
                if use_faster:
                    segments, info = model.transcribe(
                        audio_path,
                        language="es",
                        task="transcribe",
                        beam_size=1,
                        temperature=0.0,
                        condition_on_previous_text=False,
                        vad_filter=False
                    )
                    text = " ".join([s.text for s in segments]).strip()
                else:
                    result = model.transcribe(
                        audio_path,
                        language="es",
                        task="transcribe",
                        fp16=False,
                        condition_on_previous_text=False,
                        no_speech_threshold=0.6,
                        logprob_threshold=-1.0
                    )
                    text = result["text"].strip()
                    
                if is_hallucination(text):
                    text = ""
                
                print(json.dumps({"ok": True, "text": text}), flush=True)
            except Exception as e:
                print(json.dumps({"ok": False, "error": str(e)}), flush=True)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "trace": traceback.format_exc()}), flush=True)

if __name__ == "__main__":
    main()
