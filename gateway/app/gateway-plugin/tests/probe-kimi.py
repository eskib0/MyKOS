"""Prueba sin red de Kimi: DPAPI, catálogo y completado OpenAI-compatible."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import kimi


class Response:
    def __init__(self, data): self.data = data
    def read(self): return json.dumps(self.data).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *_): return False


with tempfile.TemporaryDirectory() as directory:
    old_file = kimi.FILE
    kimi.FILE = Path(directory) / "credentials.json"
    kimi.save_kimi_api_key("sk-test-secret")
    assert "sk-test-secret" not in kimi.FILE.read_text(encoding="utf-8")
    assert kimi.kimi_auth_status()["authenticated"]

    calls = []
    def fake_open(request, timeout):
        calls.append((request.full_url, request.get_header("Authorization"), request.data))
        if request.full_url.endswith("/models"):
            return Response({"data": [{"id": "kimi-test"}]})
        return Response({"choices": [{"message": {"content": "respuesta simulada"}}]})

    with patch("urllib.request.urlopen", fake_open):
        assert kimi.kimi_models() == [{"id": "kimi-test"}]
        assert kimi.kimi_chat_completion("kimi/kimi-test", [{"role": "user", "content": "hola"}]) == "respuesta simulada"
    assert calls[0][0].endswith("/models") and calls[0][1] == "Bearer sk-test-secret"
    assert json.loads(calls[1][2])["model"] == "kimi-test"
    assert json.loads(calls[1][2])["temperature"] == 1
    kimi.clear_kimi_api_key()
    assert not kimi.kimi_auth_status()["authenticated"]
    kimi.FILE = old_file

print("OK Kimi: 7/7 (clave protegida, catálogo y chat simulados)")
