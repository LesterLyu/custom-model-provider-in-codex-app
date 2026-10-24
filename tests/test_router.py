import json
from pathlib import Path
import sqlite3
import os
import socket
import tempfile
import unittest

from codex_provider_routing.router import Router, remove_socket


class Routing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        with sqlite3.connect(self.home / 'state_5.sqlite') as db:
            db.execute('CREATE TABLE threads (id TEXT PRIMARY KEY, model TEXT)')
            db.executemany('INSERT INTO threads VALUES (?, ?)', [
                ('local-thread', 'example-local-model'), ('hosted-thread', 'example-hosted-model')])
        self.router = Router(self.home, {"example-local-model": "local", "example-review-model": "local"})

    def tearDown(self):
        self.tmp.cleanup()

    def message(self, method='thread/resume', **params):
        return json.dumps({'id': 7, 'method': method, 'params': params}, indent=2)

    def test_local_model_overrides_wrong_provider(self):
        for method in ('thread/start', 'thread/resume', 'thread/fork'):
            text = self.message(method, model='example-local-model', modelProvider='openai',
                                approvalPolicy='on-request', effort='high')
            result = json.loads(self.router.rewrite(text))['params']
            self.assertEqual(result['modelProvider'], 'local')
            self.assertEqual(result['approvalPolicy'], 'on-request')
            self.assertEqual(result['effort'], 'high')

    def test_saved_local_model_without_explicit_model(self):
        result = json.loads(self.router.rewrite(self.message(threadId='local-thread', modelProvider='openai')))
        self.assertEqual(result['params']['model'], 'example-local-model')
        self.assertEqual(result['params']['modelProvider'], 'local')

    def test_app_resume_with_model_but_no_provider(self):
        for extra in ({}, {'modelProvider': None}):
            text = self.message(threadId='local-thread', model='example-local-model', **extra)
            params = json.loads(self.router.rewrite(text))['params']
            self.assertEqual(params['modelProvider'], 'local')

    def test_explicit_hosted_model_is_unchanged(self):
        text = self.message(threadId='local-thread', model='example-hosted-model', modelProvider='openai')
        self.assertEqual(self.router.rewrite(text), text)

    def test_hosted_default_and_unknown_threads_are_unchanged(self):
        for params in ({}, {'threadId': 'hosted-thread'}, {'threadId': 'missing-thread'},
                       {'model': 'another-Qwen-model'}, {'model': ['invalid']}):
            text = self.message(**params)
            self.assertEqual(self.router.rewrite(text), text)

    def test_nested_provider_override(self):
        text = self.message(model='example-local-model',
                            config={'model_provider': 'openai', 'model_reasoning_effort': 'high'})
        config = json.loads(self.router.rewrite(text))['params']['config']
        self.assertEqual(config, {'model_provider': 'local', 'model_reasoning_effort': 'high'})

    def test_existing_correct_request_is_unchanged(self):
        text = self.message(model='example-local-model', modelProvider='local')
        self.assertEqual(self.router.rewrite(text), text)

    def test_review_alias_is_local(self):
        result = json.loads(self.router.rewrite(self.message(model='example-review-model')))
        self.assertEqual(result['params']['modelProvider'], 'local')

    def test_other_methods_binary_and_invalid_messages_are_unchanged(self):
        values = [b'\x00\xff', 'not json', '[]', self.message('turn/start', model='example-local-model'),
                  self.message('config/value/write', model='example-local-model')]
        for value in values:
            self.assertEqual(self.router.rewrite(value), value)

    def test_stale_native_socket_symlink_is_removed(self):
        safe = Path('/tmp') / f'codex-daemon-{os.getuid()}'
        safe.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=safe, prefix='router-test-') as tmp:
            target = Path(tmp) / 'native.sock'
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(target))
            sock.close()
            link = self.home / 'native.sock'
            link.symlink_to(target)
            remove_socket(link)
            self.assertFalse(link.is_symlink())

    def test_dangling_native_socket_symlink_is_removed(self):
        link = self.home / 'dangling.sock'
        link.symlink_to(Path('/tmp') / f'codex-daemon-{os.getuid()}' / 'missing-router-target')
        remove_socket(link)
        self.assertFalse(link.is_symlink())

    def test_active_native_socket_symlink_is_preserved(self):
        safe = Path('/tmp') / f'codex-daemon-{os.getuid()}'
        safe.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=safe, prefix='router-test-') as tmp:
            target = Path(tmp) / 'native.sock'
            with socket.socket(socket.AF_UNIX) as sock:
                sock.bind(str(target))
                sock.listen()
                link = self.home / 'active.sock'
                link.symlink_to(target)
                with self.assertRaisesRegex(RuntimeError, 'active socket'):
                    remove_socket(link)
                self.assertTrue(link.is_symlink())


if __name__ == '__main__':
    unittest.main()
