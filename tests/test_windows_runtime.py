import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from subprocess import CompletedProcess
from unittest.mock import patch

from windows.native_runtime import REQUIRED, OPTIONAL, app_resources, resolve_native, snapshot, startup_probe


class NativeRuntime(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'package'
        self.source.mkdir()
        self.cache = self.root / 'runtime' / 'native'
        for name in (*REQUIRED, *OPTIONAL):
            (self.source / name).write_bytes(('native fixture ' + name).encode())

    def test_snapshot_contains_all_companions_and_is_reused(self):
        cli = snapshot(self.source, self.cache)
        self.assertEqual(cli, snapshot(self.source, self.cache))
        self.assertEqual(cli.parent.parent, self.cache.resolve())
        for name in (*REQUIRED, *OPTIONAL):
            self.assertEqual((cli.parent / name).read_bytes(), (self.source / name).read_bytes())
            self.assertFalse((cli.parent / name).samefile(self.source / name))

    def test_source_update_keeps_the_previous_runtime(self):
        old = snapshot(self.source, self.cache)
        previous = old.read_bytes()
        (self.source / 'codex.exe').write_bytes(b'new native fixture')
        new = snapshot(self.source, self.cache)
        self.assertNotEqual(old, new)
        self.assertEqual(old.read_bytes(), previous)
        self.assertEqual(new.read_bytes(), b'new native fixture')

    def test_missing_companion_is_rejected_before_copy(self):
        (self.source / 'codex-code-mode-host.exe').unlink()
        with self.assertRaisesRegex(RuntimeError, 'code-mode-host'):
            snapshot(self.source, self.cache)
        self.assertFalse(self.cache.exists())

    def test_modified_snapshot_is_preserved_and_rejected(self):
        cli = snapshot(self.source, self.cache)
        cli.write_bytes(b'modified fixture')
        with self.assertRaisesRegex(RuntimeError, 'modified'):
            snapshot(self.source, self.cache)
        self.assertEqual(cli.read_bytes(), b'modified fixture')

    def test_simultaneous_starts_publish_one_complete_snapshot(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(lambda _: snapshot(self.source, self.cache), range(4)))
        self.assertEqual(len(set(paths)), 1)
        self.assertEqual([p.name for p in self.cache.iterdir()], [paths[0].parent.name])

    def test_app_mode_uses_installed_package_not_cached_path(self):
        with patch('windows.native_runtime.app_resources', return_value=self.source):
            cli = resolve_native({'native_source': 'app', 'codex': '/removed/cache/codex.exe'}, self.cache.parent)
        self.assertEqual(cli.read_bytes(), (self.source / 'codex.exe').read_bytes())

    def test_explicit_source_and_legacy_paths(self):
        cli = resolve_native({'native_source': {'directory': str(self.source)}}, self.cache.parent)
        self.assertTrue(cli.is_file())
        self.assertEqual(resolve_native({'codex': 'native-cli'}, self.root), Path('native-cli'))
        with self.assertRaises(ValueError):
            resolve_native({'native_source': {'unknown': 'value'}}, self.root)

    def test_app_discovery_is_structured_and_fails_closed(self):
        response = CompletedProcess([], 0, json.dumps(str(self.source)), '')
        with patch('windows.native_runtime.subprocess.run', return_value=response) as call:
            self.assertEqual(app_resources(), self.source)
        self.assertIn('-NoProfile', call.call_args.args[0])
        with patch('windows.native_runtime.subprocess.run', return_value=CompletedProcess([], 1, '', 'failed')):
            with self.assertRaises(RuntimeError):
                app_resources()

    def test_startup_probe_requires_the_real_app_contract(self):
        valid = {'appServerVersion': 'test', 'configRequirements': {'requirements': None}}
        with patch('windows.native_runtime.subprocess.run', return_value=CompletedProcess([], 0, json.dumps(valid), '')) as call:
            self.assertEqual(startup_probe(['launcher'], self.root), 'test')
        args = call.call_args.args[0]
        self.assertLess(args.index('app-server'), args.index('--print-startup-config'))
        for stdout, code in [('not JSON', 0), ('{}', 0), (json.dumps(valid), 1)]:
            with patch('windows.native_runtime.subprocess.run', return_value=CompletedProcess([], code, stdout, '')):
                with self.assertRaises(RuntimeError):
                    startup_probe(['launcher'], self.root)


if __name__ == '__main__':
    unittest.main()
