"""Regresión: la UI abre la pestaña de login OAuth y el backend no debe abrir otra.

Verifica que start_openai_login / start_meta_ai_login aceptan open_browser=False
y que con ese flag el backend nunca llama a su apertura de navegador.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
GATEWAY_APP = ROOT / "gateway" / "app"
if str(GATEWAY_APP) not in sys.path:
    sys.path.insert(0, str(GATEWAY_APP))

import oauth
import meta_ai


class TestOpenAIOpenBrowserFlag(unittest.TestCase):
    def test_no_browser_when_ui_handles_it(self):
        with mock.patch.object(oauth, "_paths", return_value=(None, "")), \
             mock.patch.object(oauth, "_open_chrome") as chrome:
            state = oauth.start_openai_login(open_browser=False)
        self.assertIsInstance(state, dict)
        chrome.assert_not_called()

    def test_default_keeps_browser_for_headless_clients(self):
        opened = []

        def fake_run_login(open_browser=True):
            if open_browser:
                opened.append(True)

        with mock.patch.object(oauth, "_run_login", side_effect=fake_run_login):
            oauth.start_openai_login()
        self.assertEqual(opened, [True])


class TestMetaOpenBrowserFlag(unittest.TestCase):
    def test_start_meta_ai_login_forwards_flag(self):
        from core import providers

        with mock.patch.object(providers, "start_meta_ai_oauth", return_value={"ok": True}) as starter:
            providers.start_meta_ai_login(open_browser=False)
        starter.assert_called_once_with(open_browser=False)

    def test_no_browser_on_successful_session_when_disabled(self):
        session = {"access_token": "x"}
        with mock.patch.object(meta_ai, "_invoke_dgw_bridge", return_value={"ok": True, "session": session}), \
             mock.patch.object(meta_ai, "_save_meta_ai_session"), \
             mock.patch.object(meta_ai, "_open_chrome") as chrome:
            meta_ai.start_meta_ai_oauth(open_browser=False)
        chrome.assert_not_called()


if __name__ == "__main__":
    unittest.main()
