import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from windows import stdio_router
from windows.stdio_router import is_stdio_server


class Stdio(unittest.TestCase):
    def test_app_stdio_launch(self):
        for args in (['app-server'], ['-c', 'features.code_mode_host=true', 'app-server', '--analytics-default-enabled'],
                     ['app-server', '--listen', 'stdio://'], ['app-server', '--listen=stdio://']):
            self.assertTrue(is_stdio_server(args))

    def test_other_commands_are_delegated(self):
        for args in (['--version'], ['app-server', 'proxy'], ['app-server', 'daemon', 'status'],
                     ['app-server', 'generate-json-schema'], ['app-server', '--help'],
                     ['app-server', '--listen', 'unix://'], ['app-server', '--listen=ws://127.0.0.1:8000']):
            self.assertFalse(is_stdio_server(args))

    def test_configured_home_reaches_delegated_native_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = str(Path(tmp) / 'custom-home')
            settings = Path(tmp) / 'settings.json'
            settings.write_text(json.dumps({'home': home, 'codex': str(Path(tmp) / 'native-cli'),
                                            'routes': {'sample': 'local'}}))
            with patch.dict(os.environ, {}, clear=True), \
                 patch('sys.argv', ['stdio_router', '--settings', str(settings), '--', '--version']), \
                 patch.object(stdio_router.subprocess, 'call', return_value=0) as call:
                self.assertEqual(stdio_router.main(), 0)
            self.assertEqual(Path(call.call_args.kwargs['env']['CODEX_HOME']).resolve(), Path(home).resolve())

    def test_explicit_home_override_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / 'settings.json'
            settings.write_text(json.dumps({'home': str(Path(tmp) / 'configured'),
                                            'codex': str(Path(tmp) / 'native-cli'), 'routes': {'sample': 'local'}}))
            override = str(Path(tmp) / 'override')
            with patch.dict(os.environ, {'CODEX_HOME': override, 'CODEX_CLI_PATH': 'wrapper'}), \
                 patch('sys.argv', ['stdio_router', '--settings', str(settings), '--', '--version']), \
                 patch.object(stdio_router.subprocess, 'call', return_value=0) as call:
                self.assertEqual(stdio_router.main(), 0)
            self.assertEqual(Path(call.call_args.kwargs['env']['CODEX_HOME']).resolve(), Path(override).resolve())
            self.assertNotIn('CODEX_CLI_PATH', call.call_args.kwargs['env'])
