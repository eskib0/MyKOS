"""Pruebas unitarias e integración local para el motor multi-agente MyKOS Swarm."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parent.parent / "gateway" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import swarm_engine  # noqa: E402
from cortex import CortexEngine  # noqa: E402
from tools import execute_tool  # noqa: E402
from tools.schemas import TOOL_SCHEMAS  # noqa: E402


def _bind_isolated_swarm_storage(test_case: unittest.TestCase, tmpdir_path: Path, swarm_file: Path) -> CortexEngine:
    """Aísla por completo los tests del store ACID real del Gateway y de la bóveda real de Cortex."""
    cortex_vault = tmpdir_path / "cortex"
    cortex_vault.mkdir(parents=True, exist_ok=True)
    test_cortex = CortexEngine(cortex_vault)

    def _fake_load(name, legacy_file=None, default=None):
        if swarm_file.is_file():
            return json.loads(swarm_file.read_text(encoding="utf-8"))
        return json.loads(json.dumps(default)) if default is not None else {}

    def _fake_save(name, data, legacy_file=None, indent=2, source=""):
        swarm_file.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")

    p1 = patch.object(swarm_engine, "load_document", side_effect=_fake_load)
    p2 = patch.object(swarm_engine, "save_document", side_effect=_fake_save)
    p3 = patch.object(swarm_engine, "_get_cortex_engine", return_value=test_cortex)
    p1.start()
    p2.start()
    p3.start()
    test_case.addCleanup(p1.stop)
    test_case.addCleanup(p2.stop)
    test_case.addCleanup(p3.stop)
    return test_cortex


class SwarmEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.swarm_file = Path(self.tmpdir.name) / "swarm.json"
        self.orig_swarm_file = swarm_engine.SWARM_FILE
        self.orig_hooks = dict(swarm_engine._RUNTIME_HOOKS)
        swarm_engine.SWARM_FILE = self.swarm_file
        swarm_engine._RUNTIME_HOOKS.clear()
        self.test_cortex = _bind_isolated_swarm_storage(self, Path(self.tmpdir.name), self.swarm_file)
        swarm_engine.reset_swarm("Swarm de Pruebas")

    def tearDown(self) -> None:
        swarm_engine.reset_swarm("Swarm Limpio")
        swarm_engine.SWARM_FILE = self.orig_swarm_file
        swarm_engine._RUNTIME_HOOKS.clear()
        swarm_engine._RUNTIME_HOOKS.update(self.orig_hooks)
        self.tmpdir.cleanup()

    def _fake_models(self) -> list[dict]:
        return [
            {"name": "qwen3:8b", "provider": "ollama", "remote": False, "chat_capable": True, "thinking_capable": False},
            {"name": "openai/gpt-4o", "provider": "openai_api", "remote": True, "chat_capable": True, "thinking_capable": False},
            {"name": "qwen-cli/qwen-plus", "provider": "qwen_cli", "remote": True, "chat_capable": True, "thinking_capable": False},
        ]

    def test_status_title_and_permission_mode(self) -> None:
        status = swarm_engine.get_swarm_status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["title"], "Swarm de Pruebas")
        self.assertEqual(status["head"], 0)
        self.assertEqual(status["permission_mode"], "supervisado")
        self.assertIn("coordinator", status["members"])

        updated = swarm_engine.set_swarm_title(title="Auditoría Core", permission_mode="acceso_total")
        self.assertTrue(updated["ok"])
        self.assertEqual(updated["title"], "Auditoría Core")
        self.assertEqual(updated["permission_mode"], "acceso_total")

        invalid = swarm_engine.set_swarm_title(permission_mode="modo_inventado")
        self.assertFalse(invalid["ok"])

    def test_add_worker_executes_turn_with_tools_and_mentions_chain(self) -> None:
        observed_calls: list[dict] = []

        def fake_runner(model, messages, conversation_id, **kwargs):
            observed_calls.append({"model": model, "conversation_id": conversation_id, "kwargs": kwargs, "messages": messages})
            if conversation_id == "swarm:investigador":
                return {
                    "message": {"role": "assistant", "content": "Hallazgo en #1 verificado. @verificador revisa #2 y reporta a @coordinator."},
                    "tools_used": ["read_project_file", "git_status"],
                    "done": True,
                }
            return {
                "message": {"role": "assistant", "content": "@coordinator Verificación de #2 superada sin incidencias."},
                "tools_used": ["search_cortex"],
                "done": True,
            }

        swarm_engine.configure_runtime(
            run_model_until_result=fake_runner,
            get_models=self._fake_models,
            available_chat_models=lambda ms: ms,
            choose_default_model=lambda ms: "qwen3:8b",
            normalise_generation_settings=lambda raw, m: {"options": {"num_ctx": 8192}},
            load_user_profile=lambda: "Nombre: Ruben",
            load_core_memory=lambda: "Proyecto: MyKOS",
            default_model_getter=lambda: "qwen3:8b",
        )

        # Alta de verificador sin brief primero, y después investigador con brief que menciona @verificador.
        r1 = swarm_engine.add_worker("  Verificador QA ", role="QA", brief="", model="openai/gpt-4o")
        self.assertTrue(r1["ok"])
        self.assertIn("verificadorqa", r1["members"])

        # Reasignar nombre exacto 'verificador' con arroba para probar normalización.
        swarm_engine.add_worker("@Verificador", role="QA", brief="", model="openai/gpt-4o")
        r2 = swarm_engine.add_worker("Investigador", role="Analista", brief="Analiza server.py y coordina el traspaso posterior", model="qwen3:8b")
        self.assertTrue(r2["ok"])

        settled = swarm_engine.wait_for_swarm_settlement(["investigador", "verificador"], after_seq=0, wait_seconds=5.0)
        self.assertGreaterEqual(settled["head"], 3)
        authors = [m["agent"] for m in settled["messages"]]
        self.assertEqual(authors, ["coordinator", "investigador", "verificador"])
        self.assertEqual(settled["members"]["investigador"]["tools_used_count"], 2)
        self.assertEqual(settled["members"]["verificador"]["tools_used_count"], 1)
        self.assertEqual(settled["members"]["investigador"]["state"], "waiting")
        self.assertEqual(settled["members"]["verificador"]["state"], "waiting")
        # El prompt del trabajador incluye memoria Cortex/perfil del usuario.
        inv_call = next(c for c in observed_calls if c["conversation_id"] == "swarm:investigador")
        self.assertIn("Nombre: Ruben", inv_call["messages"][0]["content"])
        self.assertIn("Proyecto: MyKOS", inv_call["messages"][0]["content"])
        # Grafo de interacciones incluye coordinator->investigador, investigador->verificador, verificador->coordinator.
        edge_pairs = {(e["from"], e["to"]) for e in settled["edges"]}
        self.assertIn(("coordinator", "investigador"), edge_pairs)
        self.assertIn(("investigador", "verificador"), edge_pairs)
        self.assertIn(("verificador", "coordinator"), edge_pairs)

    def test_remote_models_run_in_parallel_without_gpu_lock(self) -> None:
        barrier = threading.Barrier(2, timeout=2.5)
        parallel_ok = {"reached": False}

        def parallel_runner(model, messages, conversation_id, **kwargs):
            barrier.wait()
            parallel_ok["reached"] = True
            return {"message": {"role": "assistant", "content": f"Listo desde {model}."}, "tools_used": [], "done": True}

        swarm_engine.configure_runtime(
            run_model_until_result=parallel_runner,
            get_models=self._fake_models,
            available_chat_models=lambda ms: ms,
            choose_default_model=lambda ms: "qwen3:8b",
            normalise_generation_settings=lambda raw, m: {"options": {}},
            load_user_profile=lambda: "",
            load_core_memory=lambda: "",
            default_model_getter=lambda: "qwen3:8b",
        )

        swarm_engine.add_worker("nube1", role="A", brief="", model="openai/gpt-4o")
        swarm_engine.add_worker("nube2", role="B", brief="", model="qwen-cli/qwen-plus")
        posted = swarm_engine.post_board_message("coordinator", "@all ejecutad comprobación en paralelo")
        self.assertEqual(set(posted["woken"]), {"nube1", "nube2"})

        settled = swarm_engine.wait_for_swarm_settlement(["nube1", "nube2"], after_seq=0, wait_seconds=5.0)
        self.assertTrue(parallel_ok["reached"])
        self.assertEqual(settled["head"], 3)

    def test_anti_loop_protection_max_auto_hops(self) -> None:
        swarm_engine.add_worker("a", role="A", brief="", model="openai/gpt-4o")
        swarm_engine.add_worker("b", role="B", brief="", model="openai/gpt-4o")

        with patch.object(swarm_engine, "_wake_worker") as mock_wake:
            swarm_engine.post_board_message("coordinator", "@a arranca", trigger_wake=True)
            for idx in range(swarm_engine.MAX_AUTO_HOPS):
                sender = "a" if idx % 2 == 0 else "b"
                target = "b" if sender == "a" else "a"
                res = swarm_engine.post_board_message(sender, f"@{target} rebote {idx + 1}", trigger_wake=True)
                self.assertFalse(res["loop_guarded"])

            blocked = swarm_engine.post_board_message("a", "@b rebote excedido", trigger_wake=True)
            self.assertTrue(blocked["loop_guarded"])
            self.assertEqual(blocked["woken"], [])
            # La intervención de coordinator reinicia el contador anti-bucle.
            reset_turn = swarm_engine.post_board_message("coordinator", "@a retoma el control", trigger_wake=True)
            self.assertFalse(reset_turn["loop_guarded"])
            self.assertEqual(reset_turn["woken"], ["a"])
            self.assertGreaterEqual(mock_wake.call_count, 2)

    def test_chat_tools_and_kill_reset(self) -> None:
        tool_names = {s["function"]["name"] for s in TOOL_SCHEMAS}
        for required in {"swarm_status", "swarm_add_worker", "swarm_post", "swarm_read_board", "swarm_kill", "list_subagents", "spawn_subagent"}:
            self.assertIn(required, tool_names)

        swarm_engine.configure_runtime(
            run_model_until_result=lambda model, messages, cid, **kw: {
                "message": {"role": "assistant", "content": "@coordinator Recibido desde chat tool."},
                "tools_used": ["get_local_status"],
                "done": True,
            },
            get_models=self._fake_models,
            available_chat_models=lambda ms: ms,
            choose_default_model=lambda ms: "qwen3:8b",
            normalise_generation_settings=lambda raw, m: {"options": {}},
            load_user_profile=lambda: "",
            load_core_memory=lambda: "",
            default_model_getter=lambda: "qwen3:8b",
        )

        add_res = execute_tool("swarm_add_worker", {"name": "auditor", "role": "Seguridad", "brief": "Revisa permisos", "model": "openai/gpt-4o"})
        self.assertTrue(add_res["ok"])
        time.sleep(0.15)
        post_res = execute_tool("swarm_post", {"text": "@auditor confirma el informe", "wait_seconds": 3})
        self.assertTrue(post_res["ok"])
        self.assertGreaterEqual(post_res["head"], 2)

        board = execute_tool("swarm_read_board", {"since_seq": 0, "limit": 20})
        self.assertTrue(board["ok"])
        self.assertGreaterEqual(len(board["messages"]), 2)

        killed = execute_tool("swarm_kill", {"name": "auditor"})
        self.assertEqual(killed["members"]["auditor"]["state"], "killed")

        reset_res = execute_tool("swarm_kill", {"name": "all", "reset": True, "title": "Misión Nueva"})
        self.assertTrue(reset_res["ok"])
        self.assertEqual(reset_res["title"], "Misión Nueva")
        self.assertEqual(reset_res["head"], 0)
        self.assertEqual(list(reset_res["members"].keys()), ["coordinator"])

    def test_queued_mention_while_worker_is_working(self) -> None:
        entered_first = threading.Event()
        release_first = threading.Event()
        turn_count = {"n": 0}

        def slow_runner(model, messages, conversation_id, **kwargs):
            turn_count["n"] += 1
            if turn_count["n"] == 1:
                entered_first.set()
                release_first.wait(timeout=3.0)
                return {"message": {"role": "assistant", "content": "Turno 1 completado."}, "tools_used": [], "done": True}
            return {"message": {"role": "assistant", "content": "@coordinator Turno 2 encolado completado."}, "tools_used": [], "done": True}

        swarm_engine.configure_runtime(
            run_model_until_result=slow_runner,
            get_models=self._fake_models,
            available_chat_models=lambda ms: ms,
            choose_default_model=lambda ms: "qwen3:8b",
            normalise_generation_settings=lambda raw, m: {"options": {}},
            load_user_profile=lambda: "",
            load_core_memory=lambda: "",
            default_model_getter=lambda: "qwen3:8b",
        )

        swarm_engine.add_worker("worker1", role="Trabajador", brief="Primer encargo", model="openai/gpt-4o")
        self.assertTrue(entered_first.wait(timeout=2.5))
        # Mientras worker1 está working, llega otra mención.
        swarm_engine.post_board_message("coordinator", "@worker1 Segundo encargo mientras trabajas")
        release_first.set()

        settled = swarm_engine.wait_for_swarm_settlement(["worker1"], after_seq=0, wait_seconds=5.0)
        worker_msgs = [m for m in settled["messages"] if m["agent"] == "worker1"]
        self.assertEqual(len(worker_msgs), 2)
        self.assertEqual(settled["members"]["worker1"]["state"], "waiting")

    def test_resolve_local_llamacpp_models(self) -> None:
        fake_catalog = [
            {
                "name": "llama_cpp/GLM-4.7-Flash",
                "provider": "llama_cpp",
                "chat_capable": True,
                "status": "standby",
                "remote": False,
            },
            {
                "name": "llama_cpp/ggml-org/GLM-4.7-Flash-GGUF:Q4_K",
                "provider": "llama_cpp",
                "chat_capable": True,
                "status": "online",
                "remote": False,
            },
            {
                "name": "qwen3.5:9b",
                "provider": "ollama",
                "chat_capable": True,
                "remote": False,
            },
        ]
        swarm_engine.configure_runtime(get_models=lambda: fake_catalog)

        resolved, entry, is_local = swarm_engine._resolve_model_and_locality("ggml-org/GLM-4.7-Flash-GGUF:Q4_K")
        self.assertEqual(resolved, "llama_cpp/ggml-org/GLM-4.7-Flash-GGUF:Q4_K")
        self.assertEqual(entry["provider"], "llama_cpp")
        self.assertTrue(is_local)

        resolved2, entry2, is_local2 = swarm_engine._resolve_model_and_locality("llamacpp/ggml-org/GLM-4.7-Flash-GGUF:Q4_K")
        self.assertEqual(resolved2, "llama_cpp/ggml-org/GLM-4.7-Flash-GGUF:Q4_K")
        self.assertEqual(entry2["provider"], "llama_cpp")
        self.assertTrue(is_local2)

        for alias in ("mykos-cuda", "llama-cpp/mykos-cuda"):
            res_alias, ent_alias, loc_alias = swarm_engine._resolve_model_and_locality(alias)
            self.assertEqual(res_alias, "llama_cpp/ggml-org/GLM-4.7-Flash-GGUF:Q4_K")
            self.assertEqual(ent_alias["provider"], "llama_cpp")
            self.assertTrue(loc_alias)

        swarm_engine.configure_runtime(get_models=lambda: [])
        res_fb, ent_fb, loc_fb = swarm_engine._resolve_model_and_locality("mykos-cuda")
        self.assertEqual(res_fb, "mykos-cuda")
        self.assertEqual(ent_fb["provider"], "llama_cpp")
        self.assertTrue(loc_fb)

        res_gguf, ent_gguf, loc_gguf = swarm_engine._resolve_model_and_locality("ggml-org/GLM-4.7-Flash-GGUF:Q4_K")
        self.assertEqual(res_gguf, "ggml-org/GLM-4.7-Flash-GGUF:Q4_K")
        self.assertEqual(ent_gguf["provider"], "llama_cpp")
        self.assertTrue(loc_gguf)


class SwarmHybridAndCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.swarm_file = Path(self.tmpdir.name) / "swarm.json"
        self.orig_swarm_file = swarm_engine.SWARM_FILE
        self.orig_hooks = dict(swarm_engine._RUNTIME_HOOKS)
        swarm_engine.SWARM_FILE = self.swarm_file
        swarm_engine._RUNTIME_HOOKS.clear()
        self.test_cortex = _bind_isolated_swarm_storage(self, Path(self.tmpdir.name), self.swarm_file)

    def tearDown(self) -> None:
        swarm_engine.kill_worker("all")
        swarm_engine.SWARM_FILE = self.orig_swarm_file
        swarm_engine._RUNTIME_HOOKS.clear()
        swarm_engine._RUNTIME_HOOKS.update(self.orig_hooks)
        self.tmpdir.cleanup()

    def test_llamacpp_tool_loop_and_qwen_prompt(self) -> None:
        from unittest.mock import patch
        import server

        prompt = server.qwen_prompt_from_messages(
            [{"role": "user", "content": "Crea un agente"}],
            workspace_dir=str(APP_DIR.parent.parent),
        )
        self.assertIn("MOTOR MYKOS SWARM EN QWEN CLI", prompt)
        self.assertIn("./bin/mykos swarm add", prompt)

        worker_prompt = server.qwen_prompt_from_messages(
            [
                {"role": "system", "content": "REGLAS DE OPERACIÓN EN EL SWARM:\n2. Respuesta auto."},
                {"role": "user", "content": "Revisa #1"},
            ],
            workspace_dir=str(APP_DIR.parent.parent),
        )
        self.assertNotIn("MOTOR MYKOS SWARM EN QWEN CLI", worker_prompt)

        captured_requests: list[tuple[list[dict], list[dict] | None, str]] = []
        executed_tools: list[tuple[str, dict]] = []

        def fake_llama_chat(messages, generation, tool_schemas=None, model_name="mykos-cuda"):
            captured_requests.append(([dict(m) for m in messages], tool_schemas, model_name))
            if len(captured_requests) == 1:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {"name": "search_cortex", "arguments": '{"query": "MyKOS"}'},
                                    },
                                    {
                                        "id": "call_2",
                                        "type": "function",
                                        "function": {"name": "read_project_file", "arguments": '{"path": "version.json"}'},
                                    },
                                ],
                            }
                        }
                    ]
                }
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Resumen verificado de Cortex y version.json.",
                        }
                    }
                ]
            }

        def fake_exec_tool(name, args):
            executed_tools.append((name, dict(args or {})))
            if name == "read_project_file":
                return {"ok": True, "action": "read_project_file", "content": '{"version":"test"}'}
            return {"ok": True, "action": name, "results": []}

        with (
            patch.object(server, "llama_cpp_chat_request", side_effect=fake_llama_chat),
            patch.object(server, "controller_execute_tool", side_effect=fake_exec_tool),
            patch.object(server, "get_models", return_value=[]),
            patch.object(server, "update_activity", lambda *a, **k: None),
            patch.object(server, "save_assistant_message", lambda *a, **k: None),
        ):
            res = server.run_model_until_result(
                "llama_cpp/ggml-org/GLM-4.7-Flash-GGUF:Q4_K",
                [
                    {"role": "system", "content": "Eres @local-cuda"},
                    {"role": "user", "content": "Consulta Cortex y lee version.json"},
                ],
                "swarm:local-cuda",
                remote_worker=True,
            )

        self.assertTrue(res["done"])
        self.assertEqual(res["message"]["content"], "Resumen verificado de Cortex y version.json.")
        self.assertEqual([t[0] for t in executed_tools], ["search_cortex", "read_project_file"])
        self.assertEqual(len(captured_requests), 2)
        self.assertIs(captured_requests[0][1], server.TOOL_SCHEMAS)
        self.assertIn("Eres @local-cuda", captured_requests[0][0][0]["content"])
        tool_msgs = [m for m in captured_requests[1][0] if m.get("role") == "tool"]
        self.assertEqual([m.get("tool_call_id") for m in tool_msgs], ["call_1", "call_2"])

        with (
            patch.object(server, "get_models", return_value=[]),
            patch.object(
                server,
                "run_llamacpp_until_result",
                return_value={"done": True, "message": {"role": "assistant", "content": "routed"}, "tools_used": []},
            ) as mock_llama_loop,
        ):
            routed = server.run_model_until_result(
                "ggml-org/GLM-4.7-Flash-GGUF:Q4_K",
                [{"role": "user", "content": "hola"}],
                "swarm:local-cuda",
                remote_worker=True,
            )
        self.assertTrue(routed["done"])
        mock_llama_loop.assert_called_once()

    def test_swarm_cli_offline_subcommands(self) -> None:
        import io
        import json
        import os
        from contextlib import redirect_stdout
        from unittest.mock import patch
        import swarm_cli

        swarm_engine.configure_runtime(
            run_model_until_result=lambda model, messages, cid, **kw: {
                "done": True,
                "message": {"content": "Respuesta CLI verificada", "tools_used": []},
            },
            get_models=lambda: [],
        )
        env = {
            "MYKOS_GATEWAY_STATE_DIR": self.tmpdir.name,
            "MYKOS_GATEWAY_CONFIG": str(Path(self.tmpdir.name) / "missing.json"),
            "MYKOS_CONTROL_URL": "http://127.0.0.1:1",
            "MYKOS_CONTROL_TOKEN": "",
        }
        with patch.dict(os.environ, env, clear=False):
            _, tok = swarm_cli._load_control_target()
            self.assertEqual(tok, "")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = swarm_cli.main(["reset", "--title", "Mision CLI", "--json"])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(buf.getvalue())["title"], "Mision CLI")

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = swarm_cli.main([
                    "add", "inspector", "--role", "Auditor", "--model", "fake/model",
                    "--brief", "Revisa todo", "--wait", "5", "--json",
                ])
            self.assertEqual(rc, 0)
            add_data = json.loads(buf.getvalue())
            self.assertTrue(add_data["ok"])
            self.assertTrue(any(m.get("agent") == "inspector" for m in add_data.get("board_updates", [])))

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = swarm_cli.main(["post", "@inspector segunda ronda", "--wait", "5", "--json"])
            self.assertEqual(rc, 0)

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = swarm_cli.main(["board", "--since", "0", "--json"])
            self.assertEqual(rc, 0)
            self.assertGreaterEqual(len(json.loads(buf.getvalue())["messages"]), 3)

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = swarm_cli.main(["kill", "inspector", "--json"])
            self.assertEqual(rc, 0)

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = swarm_cli.main(["status", "--json"])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(buf.getvalue())["members"]["inspector"]["state"], "killed")

    def test_llamacpp_online_server_bypasses_missing_models_dir(self) -> None:
        from unittest.mock import patch
        import llamacpp

        online_status = {
            "online": True,
            "loaded_model": "GLM-4.7-Flash",
            "status": "ok",
            "models": [{"id": "GLM-4.7-Flash", "status": {"value": "loaded"}}],
        }
        with (
            patch.object(llamacpp, "llamacpp_status", return_value=online_status),
            patch.object(llamacpp, "get_available_gguf_models", return_value={}),
        ):
            self.assertEqual(llamacpp.ensure_llamacpp_model("ggml-org/GLM-4.7-Flash-GGUF:Q4_K"), "GLM-4.7-Flash")
            self.assertEqual(llamacpp.ensure_llamacpp_model("mykos-cuda"), "GLM-4.7-Flash")
            self.assertEqual(llamacpp.ensure_llamacpp_model("llama-cpp/otro-modelo-cualquiera"), "GLM-4.7-Flash")

    def test_save_swarm_report_to_cortex_and_auto_archive_on_reset(self) -> None:
        swarm_engine.configure_runtime(
            run_model_until_result=lambda model, messages, cid, **kw: {
                "done": True,
                "message": {"content": "Hallazgo técnico verificado por @auditor.", "tools_used": ["read_project_file"]},
            },
            get_models=lambda: [{"name": "openai/gpt-4o", "provider": "openai_api", "remote": True, "chat_capable": True}],
        )
        swarm_engine.reset_swarm("Auditoría Cortex")
        # Sin respuestas de trabajadores aún: reset no debe auto-archivar.
        swarm_engine.post_board_message("coordinator", "Solo mensaje de coordinador", trigger_wake=False)
        empty_reset = swarm_engine.reset_swarm("Auditoría Cortex")
        self.assertNotIn("archived_path", empty_reset)

        swarm_engine.add_worker("auditor", role="Auditor", brief="Revisa módulos", model="openai/gpt-4o")
        settled = swarm_engine.wait_for_swarm_settlement(["auditor"], after_seq=0, wait_seconds=5.0)
        self.assertGreaterEqual(settled["head"], 2)

        # Guardar informe completo mediante herramienta swarm_save_cortex
        saved_full = execute_tool("swarm_save_cortex", {"title": "Informe Completo QA"})
        self.assertTrue(saved_full["ok"])
        self.assertTrue(saved_full["path"].startswith("01 - Proyectos MyKOS/Informes Swarm/"))
        note = self.test_cortex.get_note(saved_full["path"])
        self.assertIn("tags: [swarm, informe, mykos]", note["content"])
        self.assertIn("[[00 - Dashboard MyKOS]]", note["content"])
        self.assertIn("Hallazgo técnico verificado por @auditor.", note["content"])

        # Guardar mensaje individual #seq
        saved_msg = swarm_engine.save_swarm_report_to_cortex(seq=2)
        self.assertTrue(saved_msg["ok"])
        self.assertIn("msg-2.md", saved_msg["path"])

        # Al reiniciar con respuesta de trabajador, auto-archiva en Cortex antes de limpiar.
        reset_res = swarm_engine.reset_swarm("Nueva Misión Limpia")
        self.assertTrue(reset_res["ok"])
        self.assertEqual(reset_res["head"], 0)
        self.assertTrue(reset_res.get("archived_path"))
        archived_note = self.test_cortex.get_note(reset_res["archived_path"])
        self.assertIn("Auto-archivo al reiniciar Swarm", archived_note["content"])


if __name__ == "__main__":
    unittest.main()
