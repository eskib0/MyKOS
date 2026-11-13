"""Tests para el motor oficial de MyKOS Cortex (`gateway/app/cortex.py`)."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "gateway" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import cortex  # noqa: E402
from cortex import CortexEngine, get_cortex  # noqa: E402


class TestCortexRealVault(unittest.TestCase):
    def test_singleton_and_real_vault_readonly(self) -> None:
        c1 = get_cortex()
        c2 = get_cortex()
        self.assertIs(c1, c2)
        self.assertTrue(c1.root.exists(), f"No existe la bóveda: {c1.root}")

        # Grafo serializable a JSON y sin seguir el symlink recursivo
        graph = c1.get_graph()
        self.assertIn("nodes", graph)
        self.assertIn("edges", graph)
        self.assertIn("stats", graph)
        self.assertGreater(graph["stats"]["notes"], 0)
        dumped = json.dumps(graph, ensure_ascii=False)
        self.assertIsInstance(dumped, str)

        for node in graph["nodes"]:
            if node["path"]:
                self.assertNotIn("Workspace (Archivos MyKOS)", node["path"])

        # get_note con frontmatter que incluye fecha (debe serializar a JSON)
        note = c1.get_note("00 - Centro de Mando/00 - Dashboard MyKOS.md")
        for key in ("path", "content", "frontmatter", "tags", "links", "backlinks"):
            self.assertIn(key, note)
        self.assertIn("#moc", note["tags"])
        self.assertGreater(len(note["links"]), 0)
        self.assertGreater(len(note["backlinks"]), 0)
        json.dumps(note, ensure_ascii=False)

        # search_notes por título, tag y contenido
        by_title = c1.search_notes("Dashboard MyKOS")
        self.assertTrue(any(r["path"] == "00 - Centro de Mando/00 - Dashboard MyKOS.md" for r in by_title))

        by_tag = c1.search_notes("#moc")
        self.assertTrue(any("#moc" in r["tags"] for r in by_tag))

        by_content = c1.search_notes("RTX 5060")
        self.assertGreater(len(by_content), 0)
        json.dumps(by_content, ensure_ascii=False)

    def test_fallback_vault_resolution(self) -> None:
        orig_default = cortex.DEFAULT_VAULT_PATH
        try:
            cortex.DEFAULT_VAULT_PATH = Path("/ruta/que/no/existe/Obsidian Vault")
            resolved = cortex.resolve_vault_path()
            if cortex.FALLBACK_VAULT_PATH.exists():
                self.assertEqual(resolved, cortex.FALLBACK_VAULT_PATH.resolve())
        finally:
            cortex.DEFAULT_VAULT_PATH = orig_default


class TestCortexIncrementalAndStdlib(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cortex_test_"))
        (self.tmp / "A.md").write_text("---\ntags: [alpha]\n---\n# Nota A\nEnlace a [[Fantasma]]\n", "utf-8")
        self.engine = CortexEngine(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_note_incremental_updates_graph_and_backlinks(self) -> None:
        g0 = self.engine.get_graph()
        ids0 = {n["id"] for n in g0["nodes"]}
        self.assertIn("u:Fantasma", ids0)
        self.assertNotIn("n:Fantasma.md", ids0)

        # Crear la nota fantasma vía save_note -> debe resolver el enlace de A.md
        res = self.engine.save_note("Fantasma.md", "---\ntags: [beta, gamma]\n---\n# Fantasma\nHola mundo #inline\n")
        self.assertTrue(res["ok"])

        g1 = self.engine.get_graph()
        ids1 = {n["id"] for n in g1["nodes"]}
        self.assertNotIn("u:Fantasma", ids1)
        self.assertIn("n:Fantasma.md", ids1)

        note_f = self.engine.get_note("Fantasma.md")
        self.assertEqual([b["source"] for b in note_f["backlinks"]], ["A.md"])
        self.assertIn("#beta", note_f["tags"])
        self.assertIn("#inline", note_f["tags"])

        # Modificar inmediatamente con mismo tamaño en bytes (fuerza refresco de caché)
        res2 = self.engine.save_note("Fantasma.md", "---\ntags: [beta, gamma]\n---\n# Fantasma\nChao mundo #cambio\n")
        self.assertTrue(res2["ok"])
        note_f2 = self.engine.get_note("Fantasma.md")
        self.assertIn("#cambio", note_f2["tags"])
        self.assertTrue(any(r["path"] == "Fantasma.md" for r in self.engine.search_notes("Chao mundo")))

        # Consistencia incremental == full_build
        inc_graph = self.engine.get_graph()
        fresh = CortexEngine(self.tmp)
        full_graph = fresh.get_graph()
        self.assertEqual(
            sorted(n["id"] for n in inc_graph["nodes"]),
            sorted(n["id"] for n in full_graph["nodes"]),
        )
        self.assertEqual(
            sorted(e["id"] for e in inc_graph["edges"]),
            sorted(e["id"] for e in full_graph["edges"]),
        )

    def test_external_sync_detection(self) -> None:
        # Simular creación y edición externa (e.g. desde Obsidian desktop)
        ext_file = self.tmp / "Externo.md"
        ext_file.write_text("# Externo\nEnlace a [[A]]\n", "utf-8")
        # Forzar que el throttle expire
        self.engine._last_sync_time = 0.0
        g = self.engine.get_graph()
        ids = {n["id"] for n in g["nodes"]}
        self.assertIn("n:Externo.md", ids)

        # Modificación externa
        ext_file.write_text("# Externo\nContenido modificado con #externotag\n", "utf-8")
        note = self.engine.get_note("Externo.md")
        self.assertIn("#externotag", note["tags"])
        self.assertTrue(any(r["path"] == "Externo.md" for r in self.engine.search_notes("externotag")))

        # Eliminación externa
        ext_file.unlink()
        diff = self.engine.sync()
        self.assertIn("n:Externo.md", diff.nodes_remove)
        self.assertNotIn("Externo.md", self.engine.files)

    def test_security_path_traversal_and_stdlib_yaml_fallback(self) -> None:
        with self.assertRaises(ValueError):
            self.engine.get_note("../secreto.md")
        with self.assertRaises(ValueError):
            self.engine.save_note("../../fuera.md", "nope")
        with self.assertRaises(ValueError):
            self.engine.save_note(".obsidian/config.md", "nope")

        # Forzar modo sin PyYAML
        orig_yaml = cortex.yaml
        try:
            cortex.yaml = None
            self.engine.save_note(
                "Stdlib.md",
                "---\naliases: [Uno, Dos]\ntags:\n  - pure\n  - stdlib\n---\n# Stdlib\nTexto [[A]]\n",
            )
            n = self.engine.get_note("Stdlib.md")
            self.assertEqual(n["aliases"], ["Uno", "Dos"])
            self.assertEqual(n["tags"], ["#pure", "#stdlib"])
            self.assertEqual(n["links"][0]["path"], "A.md")
        finally:
            cortex.yaml = orig_yaml


if __name__ == "__main__":
    unittest.main(verbosity=2)
