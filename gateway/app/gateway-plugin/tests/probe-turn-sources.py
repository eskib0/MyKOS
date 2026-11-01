"""Offline regression: load only pure server helpers, never app startup/storage."""
import ast
import json
import re
import unittest
from pathlib import Path
from typing import Any

SOURCE = Path(__file__).resolve().parents[2] / "server.py"
NAMES = {"source_cards_from_tool_result", "merge_source_cards", "source_cards_from_messages", "research_sources_are_verified", "openrouter_prompt_from_messages", "openai_compatible_messages"}
ns = {"Any": Any, "json": json, "re": re}
tree = ast.parse(SOURCE.read_text())
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES], type_ignores=[]), str(SOURCE), "exec"), ns)
card = {"title": "Old", "url": "https://example.org/old"}
result = {"ok": True, "action": "web_search", "results": [card]}
tool = {"role": "tool", "content": json.dumps(result)}

class TurnSources(unittest.TestCase):
    def test_new_turn_does_not_repeat_assistant_sources(self):
        messages = [{"role": "user", "content": "search"}, {"role": "assistant", "content": "answer", "sources": [card]}, {"role": "user", "content": "hello"}]
        self.assertEqual(ns["source_cards_from_messages"](messages, current_turn_only=True), [])
        self.assertEqual(len(ns["source_cards_from_messages"](messages)), 1)
        self.assertTrue(ns["research_sources_are_verified"]({"sources": [card]}, ns["source_cards_from_messages"](messages)))

    def test_text_only_contract(self):
        messages = [{"role": "assistant", "content": "Tengo web_search"}, {"role": "user", "content": "busca"}]
        self.assertIn("no tiene herramientas ni bucle de ejecución", ns["openrouter_prompt_from_messages"](messages))
        native = ns["openai_compatible_messages"](messages)
        self.assertEqual(native[-1]["role"], "system")
        self.assertIn("sin herramientas ni ejecución", native[-1]["content"])

    def test_old_tool_does_not_repeat(self):
        self.assertEqual(ns["source_cards_from_messages"]([tool, {"role": "user", "content": "new"}], current_turn_only=True), [])

    def test_approval_continuation_keeps_current_sources(self):
        messages = [{"role": "user", "content": "search and save"}, tool, {"role": "assistant", "content": "approval"}, {"role": "tool", "content": "{}"}]
        self.assertEqual(len(ns["source_cards_from_messages"](messages, current_turn_only=True)), 1)

if __name__ == "__main__":
    unittest.main()
