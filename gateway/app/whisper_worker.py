import sys
import json
import warnings
import traceback

warnings.filterwarnings("ignore")

def is_hallucination(text):
    t = text.strip().lower()
    hallucinations = [
        "gracias", "gracias.", "muchas gracias", "muchas gracias.",
        "subtítulos realizados por", "subtitulaci", 
        "suscríbete", "dale a like"
    ]
    for h in hallucinations:
        if h in t and len(t) < 40:
            return True
    return False

def main():
    try:
        import whisper
        model_name = sys.argv[1]
        model_dir = sys.argv[2]
        
        model = whisper.load_model(model_name, download_root=model_dir)
        print(json.dumps({"ok": True, "event": "ready"}), flush=True)
        
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            try:
                req = json.loads(line)
                audio_path = req["audio_path"]
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
