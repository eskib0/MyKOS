import ast
import pathlib
import sys
import unittest
from unittest.mock import patch
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import antigravity_cli

class SafetyTests(unittest.TestCase):
    def test_spawn_uses_isolated_profile(self):
        with patch.object(antigravity_cli.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{"status":"SUCCESS","response":"OK","usage":{},"duration_seconds":1}'
            antigravity_cli.ask('Synthetic chat')
            environment = run.call_args.kwargs['env']
            self.assertEqual(environment['HOME'], str(antigravity_cli.SAFE_HOME))
            self.assertTrue(antigravity_cli.DENIED_TOOLS.issubset(set(__import__('json').loads(antigravity_cli.SAFE_SETTINGS.read_text())['permissions']['deny'])))

    def test_validation(self):
        for prompt, timeout in [('', 60), ('x' * 12001, 60), ('x', 0), ('x', 301)]:
            with self.assertRaises(ValueError):
                antigravity_cli.ask(prompt, timeout)

    def test_python_dispatch_is_remote_and_tool_free(self):
        source = (ROOT / 'server.py').read_text()
        cli_source = (ROOT / 'antigravity_cli.py').read_text()
        self.assertIn('model.startswith("antigravity/")', source)
        self.assertIn('return run_antigravity_until_result(', source)
        self.assertIn('"tools_capable": False', cli_source)

    def test_gateway_dispatches_as_remote(self):
        source = (ROOT / 'gateway-plugin/mykos-ui/index.js').read_text()
        route = source[source.index('if (req.method === "POST" && apiPath === "/api/chat")'):]
        self.assertIn('"antigravity/"', route[:route.index('result = await worker.remoteModel')])

    def test_allowed_modes_core_files_deny_permanent(self):
        import permissions
        desc_core = permissions.permission_descriptor("write_project_file", {"kind": "write_file", "root": "mykos", "path": "server.py"})
        self.assertEqual(permissions.allowed_modes(desc_core), ["once"])
        desc_user = permissions.permission_descriptor("write_project_file", {"kind": "write_file", "root": "workspace", "path": "notes.txt"})
        self.assertEqual(permissions.allowed_modes(desc_user), ["once", "permanent"])
        desc_rea = permissions.permission_descriptor("rea_call_tool", {"kind": "rea_call_tool", "tool_name": "gdb_console"})
        self.assertEqual(permissions.allowed_modes(desc_rea), ["once"])

    def test_rea_call_tool_is_sensitive(self):
        import tools
        self.assertIn("rea_call_tool", tools.SENSITIVE_TOOL_NAMES)
        res = tools.execute_tool("rea_call_tool", {"tool_name": "gdb_console"})
        self.assertTrue(res.get("requires_approval"))

    def test_gateway_chat_and_context_handle_store_corrupt(self):
        source = (ROOT / 'gateway-plugin/mykos-ui/index.js').read_text()
        self.assertIn('convState?.error === "store_corrupt"', source)
        self.assertIn('state?.error === "store_corrupt"', source)
        self.assertIn('"store_corrupt"', source)

    def test_rea_clean_subproc_env_scrubbing(self):
        import rea
        with patch.dict(rea.os.environ, {
            "GITHUB_TOKEN": "gh_secret_123",
            "NPM_TOKEN": "npm_secret_456",
            "AWS_ACCESS_KEY_ID": "aws_secret_789",
            "ANTHROPIC_AUTH_TOKEN": "ant_secret_012",
            "MYKOS_CONTROL_TOKEN": "mykos_secret",
            "USER_PASSWORD": "super_secret_pw",
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/user",
            "LANG": "es_ES.UTF-8",
        }, clear=True):
            cleaned = rea._clean_subproc_env()
            self.assertIn("PATH", cleaned)
            self.assertIn("HOME", cleaned)
            self.assertIn("LANG", cleaned)
            self.assertNotIn("GITHUB_TOKEN", cleaned)
            self.assertNotIn("NPM_TOKEN", cleaned)
            self.assertNotIn("AWS_ACCESS_KEY_ID", cleaned)
            self.assertNotIn("ANTHROPIC_AUTH_TOKEN", cleaned)
            self.assertNotIn("MYKOS_CONTROL_TOKEN", cleaned)
            self.assertNotIn("USER_PASSWORD", cleaned)

if __name__ == '__main__':
    unittest.main()
