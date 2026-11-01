"""Prueba sin red de Gemini: DPAPI, catálogo y generateContent nativo de Google AI Studio."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import gemini


class Response:
    def __init__(self, data):
        self.data = data

    def read(self):
        return json.dumps(self.data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


with tempfile.TemporaryDirectory() as directory:
    old_file = gemini.FILE
    gemini.FILE = Path(directory) / "credentials.json"
    
    # 1. Probar guardado seguro
    gemini.save_gemini_api_key("AIzaSy-test-secret-key")
    raw_saved = gemini.FILE.read_text(encoding="utf-8")
    assert "AIzaSy-test-secret-key" not in raw_saved, "La clave no debe guardarse en texto plano"
    assert gemini.gemini_auth_status()["authenticated"]
    assert gemini._key() == "AIzaSy-test-secret-key"

    calls = []

    def fake_open(request, timeout):
        calls.append((request.full_url, request.get_header("X-goog-api-key"), request.data))
        if request.full_url.endswith("/models"):
            return Response({
                "models": [
                    {
                        "name": "models/gemini-2.5-flash",
                        "displayName": "Gemini 2.5 Flash",
                        "description": "Next-gen fast model",
                        "supportedGenerationMethods": ["generateContent", "countTokens"],
                        "inputTokenLimit": 1048576,
                        "outputTokenLimit": 8192,
                    },
                    {
                        "name": "models/text-embedding-004",
                        "displayName": "Embedding Model",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                    {
                        "name": "models/gemini-2.5-flash-tts",
                        "displayName": "Gemini 2.5 Flash TTS",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/gemini-2.5-flash-image",
                        "displayName": "Gemini 2.5 Flash Image",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                ]
            })
        return Response({
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hola, soy Gemini."}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ]
        })

    with patch("urllib.request.urlopen", fake_open):
        # 2. Probar catálogo filtrado
        models = gemini.gemini_models()
        assert len(models) == 1
        assert models[0]["id"] == "gemini-2.5-flash"
        assert models[0]["name"] == "Gemini 2.5 Flash"
        assert models[0]["context_length"] == 1048576

        # 3. Probar llamada de chat generateContent
        reply = gemini.gemini_chat_completion(
            "gemini/gemini-2.5-flash",
            [
                {"role": "system", "content": "Eres un asistente útil."},
                {"role": "user", "content": "Hola Gemini"},
            ],
            temperature=0.7,
            max_tokens=1000,
        )
        assert reply == "Hola, soy Gemini."

    # Validar headers y payloads enviados
    assert calls[0][0].endswith("/models")
    assert calls[0][1] == "AIzaSy-test-secret-key"

    assert "models/gemini-2.5-flash:generateContent" in calls[1][0]
    assert calls[1][1] == "AIzaSy-test-secret-key"
    payload = json.loads(calls[1][2])
    assert payload["systemInstruction"]["parts"][0]["text"] == "Eres un asistente útil."
    assert payload["contents"][0]["role"] == "user"
    assert payload["contents"][0]["parts"][0]["text"] == "Hola Gemini"
    assert payload["generationConfig"]["temperature"] == 0.7
    assert payload["generationConfig"]["maxOutputTokens"] == 1000

    # 4. Probar logout / borrado
    gemini.clear_gemini_api_key()
    assert not gemini.gemini_auth_status()["authenticated"]

    gemini.FILE = old_file

print("OK Gemini: 8/8 (clave DPAPI, catálogo filtrado, estructura generateContent y logout)")
