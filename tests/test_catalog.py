import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.merge_catalog import merge_catalog, write_catalog


class Catalog(unittest.TestCase):
    def test_upstream_entries_stay_exact_and_cache_identity_is_omitted(self):
        model = {'slug': 'hosted-model', 'model_messages': {'unknown_version_field': ['preserve']},
                 'supported_reasoning_levels': [{'effort': 'high'}]}
        base = {'identity': {'private': 'do not copy'}, 'etag': 'cache metadata', 'models': [model]}
        original = copy.deepcopy(base)
        result = merge_catalog(base, {'models': [{'slug': 'local-model', 'visibility': 'list'}]})
        self.assertEqual(result['models'][0], model)
        self.assertEqual(base, original)
        self.assertEqual(set(result), {'models'})
        result['models'][0]['model_messages'].clear()
        self.assertEqual(base, original)

    def test_custom_id_cannot_replace_upstream_model(self):
        with self.assertRaisesRegex(ValueError, 'already exist'):
            merge_catalog({'models': [{'slug': 'same'}]}, {'models': [{'slug': 'same'}]})

    def test_incomplete_or_duplicate_catalog_is_rejected(self):
        for bad in ({'data': [{'id': 'model'}]}, {'models': []}, {'models': [{'id': 'model'}]},
                    {'models': [{'slug': 'x'}, {'slug': 'x'}]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                merge_catalog(bad, {'models': [{'slug': 'custom'}]})

    def test_bundled_array_export_is_accepted(self):
        result = merge_catalog([{'slug': 'hosted'}], {'models': [{'slug': 'custom'}]})
        self.assertEqual([m['slug'] for m in result['models']], ['hosted', 'custom'])

    def test_overwrite_keeps_previous_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'models.json'
            path.write_text('previous catalog')
            with self.assertRaises(FileExistsError):
                write_catalog(path, {'models': []})
            backup = write_catalog(path, {'models': [{'slug': 'custom'}]}, overwrite=True)
            self.assertEqual(backup.read_text(), 'previous catalog')
            self.assertEqual(json.loads(path.read_text())['models'][0]['slug'], 'custom')
