"""Tests de regresión para generación de imagen/vídeo y compatibilidad Meta AI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / "gateway" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import media  # noqa: E402
import meta_ai  # noqa: E402
import server  # noqa: E402
from core.runners import ensure_generated_media_markdown, execute_openai_json_tool_loop  # noqa: E402


class SystemPromptIntegrityTests(unittest.TestCase):
    def test_json_providers_receive_json_integrity_rules_not_native_contradiction(self) -> None:
        for provider in (
            "meta_ai_oauth",
            "meta_ai_api",
            "anthropic_oauth",
            "openai_codex_oauth",
            "openrouter",
            "nvidia_api",
            "gemini_api",
        ):
            prompt = server.system_prompt_for_model({"name": "test-model", "provider": provider})
            self.assertIn('"kind":"tool_call"', prompt, msg=f"Falta regla JSON en {provider}")
            self.assertNotIn(
                "NUNCA escribiendo etiquetas XML ni JSON dentro del texto",
                prompt,
                msg=f"Regla nativa contradictoria presente en {provider}",
            )

    def test_native_providers_keep_native_tool_call_integrity_rules(self) -> None:
        for provider in ("ollama", "llama_cpp", "strata"):
            prompt = server.system_prompt_for_model({"name": "qwen3.6:latest", "provider": provider})
            self.assertIn("NUNCA escribiendo etiquetas XML ni JSON dentro del texto", prompt)
            self.assertIn("llamada nativa de herramienta (tool_calls)", prompt)


class DirectMediaCommandTests(unittest.TestCase):
    def test_extract_direct_media_commands_and_guard_against_tool_loop(self) -> None:
        self.assertEqual(
            server._extract_direct_media_command([{"role": "user", "content": "/imagine un gato astronauta"}]),
            ("generate_image", {"prompt": "un gato astronauta", "aspect_ratio": "1:1", "model": "flux"}),
        )
        self.assertEqual(
            server._extract_direct_media_command([
                {"role": "user", "content": "[Fecha y hora actuales: sábado]\n/imgine cristiano ronaldo"}
            ]),
            ("generate_image", {"prompt": "cristiano ronaldo", "aspect_ratio": "1:1", "model": "flux"}),
        )
        self.assertEqual(
            server._extract_direct_media_command([
                {"role": "user", "content": "dibuja un dragón azul en Madrid"},
                {"role": "assistant", "content": "¿Lo genero?"},
                {"role": "user", "content": "/imagen"},
            ]),
            ("generate_image", {"prompt": "dibuja un dragón azul en Madrid", "aspect_ratio": "1:1", "model": "flux"}),
        )
        self.assertEqual(
            server._extract_direct_media_command([{"role": "user", "content": "/video coche futurista"}]),
            ("generate_video", {"prompt": "coche futurista"}),
        )
        # No debe dispararse cuando el último mensaje es role="tool" (continuación tras aprobar)
        self.assertIsNone(
            server._extract_direct_media_command([
                {"role": "user", "content": "/imagine un perro"},
                {"role": "assistant", "content": '{"kind":"tool_call"}'},
                {"role": "tool", "content": '{"ok":true}'},
            ])
        )

    def test_run_model_until_result_executes_direct_command_without_calling_llm(self) -> None:
        saved_messages: list[dict] = []
        fake_media = {
            "ok": True,
            "url": "/static/media/gen-test123.jpg",
            "markdown": "![cristiano](/static/media/gen-test123.jpg)",
            "message": "Imagen generada con éxito.\n\n![cristiano](/static/media/gen-test123.jpg)",
        }
        with patch.object(server, "_authorized_sensitive_action", return_value=(None, None)), \
             patch.object(server, "_auto_grant_sensitive_action", return_value=(fake_media, {"id": "g1", "mode": "permanent"})), \
             patch.object(server, "save_assistant_message", side_effect=lambda cid, msg: saved_messages.append(msg)), \
             patch.object(server, "run_meta_ai_until_result", side_effect=AssertionError("No debía llamar al LLM")):
            res = server.run_model_until_result(
                "meta-ai/llama-4-reasoning",
                [{"role": "user", "content": "/imgine Cristiano Ronaldo marcando gol"}],
                "conv-test-direct",
                permission_mode="acceso_total",
            )
        self.assertTrue(res["done"])
        self.assertEqual(res["tools_used"], ["generate_image"])
        self.assertIn("/static/media/gen-test123.jpg", res["message"]["content"])
        self.assertEqual(len(saved_messages), 1)

    def test_run_model_until_result_requests_approval_in_supervised_mode(self) -> None:
        with patch.object(server, "_authorized_sensitive_action", return_value=(None, None)), \
             patch.object(server, "create_pending_approval", return_value={"ok": True, "approval": {"id": "ap-1", "tool_name": "generate_image"}}), \
             patch.object(server, "run_meta_ai_until_result", side_effect=AssertionError("No debía llamar al LLM")):
            res = server.run_model_until_result(
                "meta-ai/llama-4-reasoning",
                [{"role": "user", "content": "/imagine un faro en la tormenta"}],
                "conv-test-sup",
                permission_mode="supervisado",
            )
        self.assertFalse(res["done"])
        self.assertEqual(res["pending_action"]["id"], "ap-1")


class MetaAiImageUnblockTests(unittest.TestCase):
    def test_format_messages_aliases_tools_and_cleans_login_widgets(self) -> None:
        messages = [
            {"role": "system", "content": "Dispones de generate_image y generate_video."},
            {
                "role": "assistant",
                "content": 'La generación de imágenes está disponible después de iniciar sesión.\n<ui-widget>{"type":"login_required"}</ui-widget>',
            },
            {"role": "user", "content": "/imagine un león dorado"},
        ]
        formatted = meta_ai._format_messages_for_meta_ai(messages)
        self.assertNotIn("generate_image", formatted)
        self.assertNotIn("generate_video", formatted)
        self.assertIn("flux_dispatch", formatted)
        self.assertIn("wan_dispatch", formatted)
        self.assertNotIn("disponible después de iniciar sesión", formatted)
        self.assertNotIn("<ui-widget>", formatted)
        self.assertNotIn("/imagine", formatted)
        self.assertIn("un león dorado", formatted)
        self.assertIn("[NOTA DEL HOST MYKOS:", formatted)

    def test_meta_ai_chat_completion_converts_login_widget_to_generate_image_tool_call(self) -> None:
        messages = [
            {"role": "system", "content": "Usa generate_image."},
            {"role": "user", "content": "hazme una imagen de Cristiano Ronaldo metiendo gol con camiseta blanca del Real Madrid"},
            {"role": "assistant", "content": "¿Quieres que la genere ahora?"},
            {"role": "user", "content": "sí, dale"},
        ]
        fake_session = {"accessToken": "tok-test"}
        blocked_reply = {
            "ok": True,
            "response": (
                "La generación de imágenes está disponible después de iniciar sesión."
                '<ui-widget>{"capability":"image_generation","type":"login_required"}</ui-widget>'
            ),
        }
        with patch.object(meta_ai, "get_meta_ai_api_key", return_value=""), \
             patch.object(meta_ai, "_load_meta_ai_session", return_value=fake_session), \
             patch.object(meta_ai, "_invoke_dgw_bridge", return_value=blocked_reply):
            raw = meta_ai.meta_ai_chat_completion("meta-ai/llama-4-reasoning", messages)
        parsed = json.loads(raw)
        self.assertEqual(parsed["kind"], "tool_call")
        self.assertEqual(parsed["tool_name"], "generate_image")
        self.assertIn("Cristiano Ronaldo", parsed["arguments"]["prompt"])

    def test_meta_ai_chat_completion_translates_flux_and_wan_dispatch(self) -> None:
        fake_session = {"accessToken": "tok-test"}
        alias_reply = {
            "ok": True,
            "response": '{"kind":"tool_call","content":"","tool_name":"flux_dispatch","arguments":{"prompt":"white tiger","aspect_ratio":"1:1","model":"flux"}}',
        }
        with patch.object(meta_ai, "get_meta_ai_api_key", return_value=""), \
             patch.object(meta_ai, "_load_meta_ai_session", return_value=fake_session), \
             patch.object(meta_ai, "_invoke_dgw_bridge", return_value=alias_reply):
            raw = meta_ai.meta_ai_chat_completion("meta-ai/llama-4-reasoning", [{"role": "user", "content": "tigre blanco"}])
        parsed = json.loads(raw)
        self.assertEqual(parsed["tool_name"], "generate_image")


class MediaResilienceAndMarkdownTests(unittest.TestCase):
    def test_pollinations_retries_503_and_uses_seed_without_model_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            requested_urls: list[str] = []

            class _OkResp:
                def __init__(self, data: bytes) -> None:
                    self._data = data

                def __enter__(self) -> "_OkResp":
                    return self

                def __exit__(self, *args: object) -> None:
                    return None

                def read(self, _n: int = -1) -> bytes:
                    return self._data

            def _fake_urlopen(req: object, timeout: int = 40) -> _OkResp:
                url = req.full_url if hasattr(req, "full_url") else str(req)
                requested_urls.append(url)
                if len(requested_urls) == 1:
                    raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)
                return _OkResp(b"\xff\xd8\xff" + b"x" * 2048)

            with patch.object(media, "ROOT", tmp_root), \
                 patch.object(media, "MEDIA_DIR", tmp_root / "data_media"), \
                 patch.object(media, "_try_local_comfy_image", return_value=None), \
                 patch.object(media.time, "sleep", return_value=None), \
                 patch.object(media.urllib.request, "urlopen", side_effect=_fake_urlopen):
                out = media.generate_image_approved({"prompt": "sunset over madrid", "model": "flux"})

            self.assertTrue(out["ok"])
            self.assertTrue(out["url"].startswith("/static/media/gen-"))
            self.assertIn("seed=", requested_urls[0])
            self.assertNotIn("&model=", requested_urls[0])
            self.assertTrue((tmp_root / out["path"]).is_file())

    def test_ensure_generated_media_markdown_appends_missing_image(self) -> None:
        msgs = [
            {"role": "user", "content": "dibuja un coche"},
            {"role": "assistant", "content": '{"kind":"tool_call","tool_name":"generate_image"}'},
            {
                "role": "tool",
                "content": json.dumps({
                    "ok": True,
                    "url": "/static/media/gen-abc123.jpg",
                    "markdown": "![coche](/static/media/gen-abc123.jpg)",
                }),
            },
        ]
        result = ensure_generated_media_markdown("Aquí tienes tu imagen.", msgs)
        self.assertIn("![coche](/static/media/gen-abc123.jpg)", result)

        # In execute_openai_json_tool_loop, final answer without URL still appends Markdown
        saved: list[dict] = []
        responses = iter([
            '{"kind":"tool_call","content":"","tool_name":"generate_image","arguments":{"prompt":"red car"}}',
            '{"kind":"answer","content":"Aquí está el coche generado."}',
        ])

        def _fake_sensitive(**kwargs: object) -> None:
            wm = kwargs["working_messages"]
            assert isinstance(wm, list)
            wm.append({
                "role": "tool",
                "content": json.dumps({
                    "ok": True,
                    "url": "/static/media/gen-loop999.jpg",
                    "markdown": "![red car](/static/media/gen-loop999.jpg)",
                }),
            })
            return None

        res = execute_openai_json_tool_loop(
            model="meta-ai/llama-4-reasoning",
            provider="meta_ai_oauth",
            provider_label="Meta AI",
            activity_detail="test",
            messages=[{"role": "user", "content": "genera un coche rojo"}],
            conversation_id="conv-loop",
            completion_fn=lambda _msgs: next(responses),
            system_prompt_fn=lambda _m: "SYS",
            source_cards_fn=lambda _m, current_turn_only=True: [],
            merge_source_cards_fn=lambda _s, _r: None,
            tool_message_fn=lambda r, _v: {"role": "tool", "content": json.dumps(r)},
            openai_compatible_messages_fn=lambda m, system_prompt="", supports_vision=False: m,
            controller_execute_tool_fn=lambda _n, _a: {},
            save_assistant_message_fn=lambda _c, m: saved.append(m),
            handle_sensitive_tool_fn=_fake_sensitive,
            utc_now_fn=lambda: "2026-11-14T14:00:00Z",
        )
        self.assertIn("![red car](/static/media/gen-loop999.jpg)", res["message"]["content"])

    def test_chat_loop_js_direct_imgine_command(self) -> None:
        chat_loop_path = ROOT_DIR / "gateway" / "app" / "gateway-plugin" / "mykos-ui" / "chat-loop.js"
        script = f"""
import {{ runChatLoop }} from {json.dumps(chat_loop_path.as_uri())};
const saved = [];
const deps = {{
  now: () => "2026-11-14T14:00:00Z",
  authority: {{
    descriptor: (t, a) => ({{ scope_key: t }}),
    authorize: () => ({{ ok: false }}),
    grant: (t, a, c) => ({{ id: "g1", mode: "permanent" }}),
    audit: () => {{}},
    createApproval: () => ({{ ok: true, approval: {{ id: "ap1" }} }}),
  }},
  worker: {{
    catalog: async () => ({{ schemas: [], sensitive: ["generate_image", "generate_video"] }}),
    prepare: async (t, a) => ({{ ok: true, action: {{ kind: t, ...a }} }}),
    action: async (a) => ({{
      ok: true,
      url: "/static/media/gen-js123.jpg",
      markdown: "![js](/static/media/gen-js123.jpg)",
      message: "Listo\\n\\n![js](/static/media/gen-js123.jpg)"
    }}),
    saveMessage: async (c, m) => {{ saved.push(m); return m; }},
    activity: async () => {{}},
  }},
  model: {{ chat: async () => {{ throw new Error("should not call model"); }} }},
}};
const res = await runChatLoop({{
  model: "qwen3.6:latest",
  conversation_id: "conv-js",
  permission_mode: "acceso_total",
  messages: [{{ role: "user", content: "/imgine perro espacial" }}],
}}, deps);
console.log(JSON.stringify(res));
"""
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout.strip())
        self.assertTrue(data["done"])
        self.assertEqual(data["tools_used"], ["generate_image"])
        self.assertIn("/static/media/gen-js123.jpg", data["message"]["content"])


if __name__ == "__main__":
    unittest.main()
