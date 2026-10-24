import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from codex_provider_routing.manage import load_state, private_json, quote_unit, render_unit
from codex_provider_routing.router import Router, remove_socket, validate_routes


class Management(unittest.TestCase):
    def test_systemd_paths_are_quoted(self):
        unit = render_unit('/example home/venv/bin/python', '/example home/100%/state.json')
        self.assertIn('"/example home/venv/bin/python"', unit)
        self.assertIn('100%%', unit)
        self.assertIn('KillMode=control-group', unit)
        self.assertIn('UMask=0077', unit)
        self.assertEqual(quote_unit('$HOME'), '"$$HOME"')
        with self.assertRaises(ValueError):
            quote_unit('value\nExecStart=other')

    def test_state_is_private_and_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'installation.json'
            private_json(path, {'format': 1, 'sample': True})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertTrue(load_state(path)['sample'])
            with self.assertRaises(FileExistsError):
                private_json(path, {'format': 1})
            path.chmod(0o644)
            with self.assertRaises(RuntimeError):
                load_state(path)

    def test_invalid_routes_are_rejected(self):
        for data in (None, [], {}, {'model': ''}, {'': 'local'}, {'model': 'openai'}, {'model': 3}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_routes(data)

    def test_multiple_providers_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            router = Router(tmp, {'first': 'provider_a', 'second': 'provider_b'})
            for model, expected in router.routes.items():
                request = json.dumps({'method': 'thread/start', 'params': {'model': model}})
                self.assertEqual(json.loads(router.rewrite(request))['params']['modelProvider'], expected)

    def test_metadata_audit_does_not_capture_user_input_or_identifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = str(Path(tmp) / 'audit.jsonl')
            router = Router(tmp, {'sample': 'local'}, audit)
            request = json.dumps({'id': 'private-request', 'method': 'thread/resume',
                                  'params': {'model': 'sample', 'threadId': 'private-thread',
                                             'input': 'private-prompt', 'token': 'private-token'}})
            router.rewrite(request)
            text = Path(audit).read_text()
            self.assertNotIn('private-', text)
            self.assertEqual(stat.S_IMODE(Path(audit).stat().st_mode), 0o600)

    def test_missing_database_fails_open_for_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            router = Router(tmp, {'sample': 'local'})
            message = json.dumps({'method': 'thread/resume', 'params': {'threadId': 'missing'}})
            self.assertEqual(router.rewrite(message), message)

    def test_arbitrary_symlink_and_regular_file_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'file'
            file.write_text('keep')
            link = Path(tmp) / 'link'
            link.symlink_to(file)
            for path in (file, link):
                with self.assertRaises(RuntimeError):
                    remove_socket(path)
            self.assertEqual(file.read_text(), 'keep')
