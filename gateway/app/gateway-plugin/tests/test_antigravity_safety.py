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

if __name__ == '__main__':
    unittest.main()
