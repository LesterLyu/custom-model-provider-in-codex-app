import copy
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codex_provider_routing import catalog_refresh as cr


class Refresh(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.catalog = self.home / 'models.json'
        self.custom = [{'slug': 'qwen', 'default_reasoning_level': 'high', 'tool_mode': 'code_mode',
                        'base_instructions': 'retain verbatim'},
                       {'slug': 'review', 'visibility': 'hide', 'default_reasoning_level': 'low'}]
        self.original = {'models': [{'slug': 'old-hosted'}, *copy.deepcopy(self.custom)]}
        self.catalog.write_text(json.dumps(self.original), encoding='utf-8')
        (self.home / 'config.toml').write_text('model_catalog_json=' + json.dumps(str(self.catalog)), encoding='utf-8')
        (self.home / 'auth.json').write_text(json.dumps({'auth_mode': 'chatgpt', 'tokens': {
            'access_token': 'fixture-token', 'account_id': 'fixture-account'}}), encoding='utf-8')
        cr.enable(self.home, ['qwen', 'review'])
        self.root = self.home / 'provider-catalog'
        self.initial = self.catalog.read_bytes()
        self.upstream = {'models': [{'slug': 'new-hosted', 'future_field': {'keep': [1, 2]}}]}
        self.version = patch.object(cr, 'cli_version', return_value='0.164.0').start()
        self.fetch = patch.object(cr, 'fetch_catalog', return_value=(self.upstream, None)).start()
        self.validate = patch.object(cr, 'validate_catalog').start()
        self.addCleanup(patch.stopall)

    def refresh(self, **kwargs):
        return cr.refresh_catalog(self.home, 'native-cli', **kwargs)

    def test_success_preserves_custom_and_upstream_metadata_and_backup(self):
        self.assertEqual(self.refresh(), 'updated')
        actual = cr.read_json(self.catalog)
        self.assertEqual(actual['models'], self.upstream['models'] + self.custom)
        self.assertEqual(cr.read_json(self.root / 'previous.json'), self.original)
        self.assertEqual(cr.read_json(self.root / 'original.json'), self.original)
        self.assertEqual(cr.read_json(self.root / 'custom.json')['models'], self.custom)
        self.assertNotIn('fixture-token', (self.root / 'state.json').read_text())
        self.assertNotIn('fixture-account', (self.root / 'state.json').read_text())

    def test_offline_auth_and_native_validation_failure_keep_exact_old_bytes(self):
        for target, failure in ((self.fetch, TimeoutError()), (self.fetch, ValueError()),
                                (self.validate, subprocess.CalledProcessError(1, 'native-cli'))):
            target.side_effect = failure
            self.assertEqual(self.refresh(), 'failed')
            self.assertEqual(self.catalog.read_bytes(), self.initial)
            target.side_effect = None
        (self.home / 'auth.json').unlink()
        self.assertEqual(self.refresh(), 'failed')
        self.assertEqual(self.catalog.read_bytes(), self.initial)

    def test_freshness_is_scoped_to_token_version_custom_and_catalog(self):
        self.assertEqual(self.refresh(), 'updated')
        self.assertEqual(self.refresh(), 'cached')
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.refresh(force=True), 'unchanged')
        self.version.return_value = '0.165.0'
        self.assertEqual(self.refresh(), 'unchanged')
        (self.home / 'auth.json').write_text(json.dumps({'OPENAI_API_KEY': 'another-fixture-token'}))
        self.assertEqual(self.refresh(), 'unchanged')
        custom = cr.read_json(self.root / 'custom.json')
        custom['models'][0]['default_reasoning_level'] = 'low'
        cr.write_json(self.root / 'custom.json', custom)
        self.assertEqual(self.refresh(), 'updated')
        self.assertEqual(cr.read_json(self.catalog)['models'][1]['default_reasoning_level'], 'low')

    def test_short_upstream_cache_lifetime_is_respected(self):
        self.fetch.return_value = self.upstream, 0
        self.assertEqual(self.refresh(), 'updated')
        self.assertEqual(self.refresh(), 'unchanged')
        self.assertEqual(self.fetch.call_count, 2)

    def test_corrupt_optional_state_is_ignored(self):
        for state in ([], {'fetched_at': 'invalid', 'ttl': None}):
            cr.write_json(self.root / 'state.json', state)
            self.assertIn(self.refresh(), ('updated', 'unchanged'))

    def test_candidate_cleanup_failure_occurs_before_publish(self):
        original = cr.tempfile.TemporaryDirectory
        class FailingCleanup:
            def __init__(self, *args, **kwargs):
                self.inner = original(*args, **kwargs)
            def __enter__(self):
                return self.inner.__enter__()
            def __exit__(self, *args):
                self.inner.__exit__(*args)
                raise PermissionError('fixture cleanup failure')
        with patch.object(cr.tempfile, 'TemporaryDirectory', FailingCleanup):
            self.assertEqual(self.refresh(), 'failed')
        self.assertEqual(self.catalog.read_bytes(), self.initial)

    def test_duplicate_upstream_or_collision_does_not_overwrite(self):
        for bad in ({'models': [{'slug': 'review'}]}, {'models': []},
                    {'models': [{'slug': 'x'}, {'slug': 'x'}]}, {'data': [{'id': 'x'}]}):
            self.fetch.return_value = bad, None
            self.assertEqual(self.refresh(), 'failed')
            self.assertEqual(self.catalog.read_bytes(), self.initial)

    def test_native_check_happens_before_atomic_replace(self):
        def check(cli, candidate, env):
            self.assertEqual(self.catalog.read_bytes(), self.initial)
            self.assertEqual(cr.read_json(candidate)['models'], self.upstream['models'] + self.custom)
        self.validate.side_effect = check
        self.assertEqual(self.refresh(), 'updated')

    def test_concurrent_human_edit_wins(self):
        def edit(*args):
            self.catalog.write_bytes(b'human edit')
        self.validate.side_effect = edit
        self.assertEqual(self.refresh(), 'failed')
        self.assertEqual(self.catalog.read_bytes(), b'human edit')

    def test_lock_contention_does_not_fetch_or_remove_lock(self):
        with cr.locked(self.root / 'refresh.lock') as acquired:
            self.assertTrue(acquired)
            self.assertEqual(self.refresh(), 'busy')
        self.fetch.assert_not_called()
        self.assertTrue((self.root / 'refresh.lock').is_file())
        self.assertEqual(self.refresh(), 'updated')

    def test_atomic_write_failure_keeps_previous_catalog(self):
        original = cr.os.replace
        def replace(source, target):
            if Path(target) == self.catalog:
                raise PermissionError('fixture')
            return original(source, target)
        with patch.object(cr.os, 'replace', side_effect=replace):
            self.assertEqual(self.refresh(), 'failed')
        self.assertEqual(self.catalog.read_bytes(), self.initial)

    def test_metadata_write_failure_does_not_invalidate_successful_publish(self):
        original = cr.write_json
        def write(path, data):
            if Path(path).name == 'state.json':
                raise PermissionError('fixture')
            return original(path, data)
        with patch.object(cr, 'write_json', side_effect=write):
            self.assertEqual(self.refresh(), 'updated')
        self.assertEqual(cr.read_json(self.catalog)['models'], self.upstream['models'] + self.custom)

    def test_disabled_home_has_no_side_effect(self):
        missing = self.home / 'unconfigured-home'
        self.assertEqual(cr.refresh_catalog(missing, 'native-cli'), 'disabled')
        self.assertFalse(missing.exists())

    def test_reenable_cannot_discard_custom_definitions(self):
        before = (self.root / 'custom.json').read_bytes()
        with self.assertRaises(ValueError):
            cr.enable(self.home, ['qwen'])
        self.assertEqual((self.root / 'custom.json').read_bytes(), before)


class Fetch(unittest.TestCase):
    def test_request_uses_only_official_origin_and_rejects_redirects(self):
        body = BytesIO(json.dumps({'models': [{'slug': 'hosted'}]}).encode())
        body.headers = {'Cache-Control': 'private, max-age=120'}
        with patch.object(cr.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value = body
            result, ttl = cr.fetch_catalog({'Authorization': 'Bearer fixture'}, '0.164.0', 3)
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, cr.ENDPOINT + '?client_version=0.164.0')
        self.assertEqual(ttl, 120)
        self.assertEqual(result['models'][0]['slug'], 'hosted')
        self.assertIsInstance(opener.call_args.args[0], cr.NoRedirect)
        self.assertIsNone(cr.NoRedirect().redirect_request(None, None, None, None, None))

    def test_no_store_disables_freshness_reuse(self):
        body = BytesIO(json.dumps({'models': [{'slug': 'hosted'}]}).encode())
        body.headers = {'Cache-Control': 'no-store, max-age=3600'}
        with patch.object(cr.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value = body
            _, ttl = cr.fetch_catalog({}, '0.164.0', 1)
        self.assertEqual(ttl, 0)

    def test_oversize_is_rejected(self):
        for content, headers in ((b'x' * (cr.MAX_BYTES + 1), {}),):
            body = BytesIO(content)
            body.headers = headers
            with patch.object(cr.urllib.request, 'build_opener') as opener:
                opener.return_value.open.return_value.__enter__.return_value = body
                with self.assertRaises(ValueError):
                    cr.fetch_catalog({}, '0.164.0', 1)

    def test_prerelease_cli_version_uses_release_schema_number(self):
        with patch.object(cr.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'codex-cli 0.164.0-alpha.11.1', '')):
            self.assertEqual(cr.cli_version('native-cli', {}), '0.164.0')


if __name__ == '__main__':
    unittest.main()
