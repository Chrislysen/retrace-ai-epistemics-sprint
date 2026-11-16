"""Independent synthetic checks of the interrupted catalog's saved-score gate.

No actual study outputs are read. These fixtures test authentication boundaries,
not the scientific correctness of the already frozen grading implementation.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from scripts import export_frontier_v6k_partial_catalog as exporter


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


class SavedPartialCatalogReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = exporter.partial.OUTPUT
        self.directory = self.root / self.base
        self.directory.mkdir(parents=True)
        writer = self.root / 'scripts/score_frontier_v6k_partial.py'
        writer.parent.mkdir(parents=True)
        writer.write_text('# invented writer binding only\n', encoding='utf-8')
        self.views = {
            'requests': b'{ "attempt_id": "invented-1", "body": {} }\r\n',
            'responses': b'{ "attempt_id": "invented-1", "output_text": "fixture" }\n',
            'outcomes': b'{ "slot_id": "invented-slot", "issued": true }\r\n',
        }
        evidence = {'frozen_aliases': {}, 'source_files': {'fixture/source': {'sha256': 'a' * 64, 'bytes': 7}},
                    'ledger_snapshot': {'path': 'fixture/snapshot', 'sha256': 'b' * 64}}
        # The real compute() returns the frozen writer's JSON projection. Include
        # a tuple-shaped engine witness to exercise that exact object boundary.
        self.result = exporter.full.json_value({
            'summary': {'status': exporter.STATUS, 'schedule_complete': False,
                        'coverage': {'slot_categories': {'issued': 1, 'definitive_dependency_skip': 0,
                                                       'unissued_censored_by_stop': 1799}},
                        'issued_attempts_observed': 1,
                        'operational_summary': {'status': exporter.STATUS, 'stop_reasons': ['cumulative_budget_stop']},
                        'file_evidence': evidence},
            'audits': [{'slot_id': 'invented-slot', 'witness': {'baseline': ('supported', 'not_supported')}}],
            'merged_evidence': {'source_provenance': {'outcomes': [{'source_line_one_based': 1}]},
                                'source_bindings': {'fixture/source': {'sha256': 'a' * 64, 'bytes': 7}}},
        })
        objects = {'score.json': self.result['summary'], 'score-audits.json': self.result['audits'],
                   'source-provenance.json': self.result['merged_evidence']['source_provenance'],
                   'interrupted-closure.json': self.result['summary']['operational_summary']}
        payloads = {name: encoded(value) for name, value in objects.items()}
        payloads.update({name: self.views[role] for role, name in (
            ('requests', 'requests.jsonl'), ('responses', 'responses.jsonl'), ('outcomes', 'slot-outcomes.jsonl'))})
        payloads['report-facts.md'] = exporter.partial.report_facts(self.result['summary']).encode('utf-8')
        for name, raw in payloads.items():
            (self.directory / name).write_bytes(raw)
        self.manifest = {
            'schema': 'retrace.frontier-v6k-partial-artifacts.v1', 'status': exporter.STATUS,
            'planned_slots': 1800, 'schedule_complete': False, 'inference_available': False,
            'source_rows_changed': False, 'selected_jsonl_source_bytes_preserved': True,
            'files': {self.base + '/' + name: {'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
                      for name, raw in payloads.items()},
            'source_bindings': deepcopy(self.result['merged_evidence']['source_bindings']),
            'file_evidence': deepcopy(evidence), 'writer_sha256': exporter.full.sha(writer),
        }
        self.save_manifest()

    def save_manifest(self):
        (self.directory / 'partial-manifest.json').write_bytes(encoded(self.manifest))

    def replace_bound(self, name, raw):
        (self.directory / name).write_bytes(raw)
        self.manifest['files'][self.base + '/' + name] = {'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
        self.save_manifest()

    def verify(self, result=None, aliases=None):
        return exporter.verify_saved(self.root, result or self.result, self.views, aliases or {})

    def test_exact_normalized_objects_and_raw_bytes_pass_without_mutation(self):
        before = deepcopy(self.result)
        bindings = self.verify()
        self.assertEqual(self.result, before)
        self.assertEqual(len(bindings), 9)
        self.assertEqual(self.result['audits'][0]['witness']['baseline'], ['supported', 'not_supported'])
        self.assertEqual(bindings[self.base + '/requests.jsonl']['sha256'], sha256(self.views['requests']).hexdigest())

    def test_rehashed_changed_graded_objects_do_not_replace_replay(self):
        for name in ('score-audits.json', 'source-provenance.json', 'interrupted-closure.json'):
            with self.subTest(name=name):
                original = (self.directory / name).read_bytes()
                self.replace_bound(name, encoded({'invented_replacement': True}))
                with self.assertRaisesRegex(ValueError, 'differs from replay'):
                    self.verify()
                self.replace_bound(name, original)

    def test_rehashed_equivalent_jsonl_is_not_byte_preserving(self):
        raw = json.dumps(json.loads(self.views['requests'])).encode('utf-8') + b'\n'
        self.assertEqual(json.loads(raw), json.loads(self.views['requests']))
        self.assertNotEqual(raw, self.views['requests'])
        self.replace_bound('requests.jsonl', raw)
        with self.assertRaisesRegex(ValueError, 'raw-line view changed'):
            self.verify()

    def test_rehashed_score_evidence_cannot_drift_with_its_manifest(self):
        score = deepcopy(self.result['summary'])
        score['file_evidence']['source_files']['fixture/source']['sha256'] = 'c' * 64
        self.manifest['file_evidence'] = deepcopy(score['file_evidence'])
        self.replace_bound('score.json', encoded(score))
        with self.assertRaisesRegex(ValueError, 'source evidence differ'):
            self.verify()

    def test_only_declared_alias_change_is_allowed_at_relocation(self):
        relocated = deepcopy(self.result)
        relocated['summary']['file_evidence']['frozen_aliases'] = exporter.full.ALIASES
        self.verify(relocated, exporter.full.ALIASES)
        relocated['summary']['file_evidence']['ledger_snapshot']['sha256'] = 'd' * 64
        with self.assertRaisesRegex(ValueError, 'source evidence differ'):
            self.verify(relocated, exporter.full.ALIASES)

    def test_completion_or_inference_flags_and_extra_files_reject(self):
        original = deepcopy(self.manifest)
        for key, value in (('status', 'complete_amended_primary'), ('schedule_complete', True),
                           ('inference_available', True), ('planned_slots', 1799)):
            with self.subTest(key=key):
                self.manifest = deepcopy(original)
                self.manifest[key] = value
                self.save_manifest()
                with self.assertRaisesRegex(ValueError, 'interrupted diagnostic manifest'):
                    self.verify()
        self.manifest = original
        self.manifest['files'][self.base + '/unrelated.json'] = {'sha256': 'f' * 64, 'bytes': 0}
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'eight-file'):
            self.verify()

    def test_source_bindings_writer_and_factual_summary_are_authenticated(self):
        original = deepcopy(self.manifest)
        self.manifest['source_bindings']['fixture/source']['bytes'] = 8
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'source/writer binding'):
            self.verify()
        self.manifest = original
        self.save_manifest()
        writer = self.root / 'scripts/score_frontier_v6k_partial.py'
        writer.write_text('# changed writer\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'source/writer binding'):
            self.verify()
        self.manifest['writer_sha256'] = exporter.full.sha(writer)
        self.replace_bound('report-facts.md', b'Invented completed study.\n')
        with self.assertRaisesRegex(ValueError, 'factual source differs'):
            self.verify()


if __name__ == '__main__':
    unittest.main()
