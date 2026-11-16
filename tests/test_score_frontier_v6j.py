"""Offline CLI authentication/writer tests; scientific and runtime proofs are mocked.

The real composite evaluator and runtime auditor have their own full-schema tests.
These isolated fixtures never use live results, provider transports, or credentials.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import score_frontier_v6j as cli


class CompositeCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, value, raw=False):
        path = self.root/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if raw else (json.dumps(value)+'\n').encode())
        return path

    def fixture(self):
        frozen = []
        for name in cli.INPUTS.values(): self.write(name, {})
        starts = ['scripts/score_frontier_v6j.py', 'retrace/frontier_v6j_eval.py', 'scripts/audit_frontier_v6j_runtime.py']
        for name in starts: self.write(name, b'# isolated local closure fixture\n', raw=True)
        lock, alias = next(iter(cli.ALIASES.items()))
        self.write(alias, b'inert historical original bytes\n', raw=True)
        for name in set(cli.INPUTS.values()) | set(starts): frozen.append({'path': name, **cli.binding(self.root/name)})
        frozen.append({'path': lock, **cli.binding(self.root/alias)})
        self.write(cli.FREEZE, {'schema': 'retrace.frontier-v6j-freeze.v1', 'scheduled_slots': 1800,
            'continuation_slots': 1794, 'carried_issued_slots': 6, 'files': frozen})
        self.snapshot = 'data/immutable-final-ledger.jsonl'
        self.write(self.snapshot, b'{"ledger_fixture": true}\n', raw=True)
        segments = {}; merged = {'requests': [], 'responses': [], 'outcomes': [],
            'source_provenance': {role: [] for role in ('requests', 'responses', 'outcomes')}, 'source_bindings': {}}
        runtime_bindings = {}
        for which, prefix in cli.PREFIXES.items():
            paths = {role: prefix+name for role, name in cli.NAMES.items()}
            for role in cli.NAMES:
                if role in ('requests', 'responses', 'outcomes'):
                    row = {'slot_id': which+'-slot', 'attempt_id': which+'-attempt', 'kind': role}
                    line = (' { "slot_id": '+json.dumps(row['slot_id'])+', "attempt_id": '+json.dumps(row['attempt_id'])+', "kind": '+json.dumps(role)+' }\r\n').encode()
                    self.write(paths[role], line, raw=True)
                    merged[role].append(row)
                    merged['source_provenance'][role].append({'segment': which, 'source_path': paths[role],
                        'source_line_one_based': 1, 'source_file_sha256': hashlib.sha256(line).hexdigest(),
                        'source_line_sha256': hashlib.sha256(line).hexdigest()})
                else: self.write(paths[role], {'run_id': which, 'kind': role})
                runtime_bindings[paths[role]] = cli.binding(self.root/paths[role])
                merged['source_bindings'][paths[role]] = runtime_bindings[paths[role]]
            segments[which] = cli.segment(self.root, which)
        runtime_bindings['results/frontier-v6j/budget/ledger.jsonl'] = cli.binding(self.root/self.snapshot)
        self.old_audit = {'schema': 'original-fixture', 'passed': True, 'schedule_status': 'stopped'}
        self.new_audit = {'schema': 'continuation-fixture', 'passed': True, 'final_closed': True,
            'schedule_status': 'completed', 'all_scheduled_outcomes_accounted': True,
            'original_audit': self.old_audit, 'input_bindings': runtime_bindings}
        self.write(cli.AUDITS['original'], self.old_audit); self.write(cli.AUDITS['continuation'], self.new_audit)
        self.result = {'summary': {'status': 'complete_amended_primary', 'primary_holm_family_size': 21,
            'issued_attempts_observed': 2, 'operational_summary': {'schema': 'derived-fixture'}},
            'audits': [{'fixture_only': True}], 'merged_evidence': merged}
        self.args = (self.root, cli.sha(self.root/cli.FREEZE), cli.sha(self.root/cli.AUDITS['original']),
                     cli.sha(self.root/cli.AUDITS['continuation']), self.snapshot, cli.sha(self.root/self.snapshot))
        return segments

    def compute(self, **kwargs):
        with patch.object(cli, 'audit_runtime', return_value=deepcopy(self.new_audit)), \
             patch.object(cli, 'evaluate_composite', return_value=deepcopy(self.result)):
            return cli.compute(*self.args, frozen_aliases=cli.ALIASES, **kwargs)

    def test_authenticated_relocated_paths_and_selected_raw_bytes(self):
        segments = self.fixture(); result, views = self.compute()
        for role in ('requests', 'responses', 'outcomes'):
            self.assertEqual(views[role], segments['original'][role]+segments['continuation'][role])
            self.assertIn(b'\r\n', views[role])
        self.assertTrue(result['summary']['file_evidence']['runtime_audits_replayed'])
        self.assertFalse((self.root/'results/frontier-v6f/budget/active.lock').exists())
        self.assertFalse((self.root/cli.OUTPUT).exists())

    def test_wrong_audit_hash_or_unreproduced_result_rejected(self):
        self.fixture(); args = list(self.args); args[2] = 'f'*64
        with self.assertRaisesRegex(ValueError, 'saved_runtime_audit_hash'):
            cli.compute(*args, frozen_aliases=cli.ALIASES)
        with patch.object(cli, 'audit_runtime', return_value={**self.new_audit, 'passed': False}):
            with self.assertRaisesRegex(ValueError, 'runtime_audits_do_not_reproduce'):
                cli.compute(*self.args, frozen_aliases=cli.ALIASES)

    def test_stopped_continuation_cannot_score_even_if_saved_audit_matches(self):
        self.fixture(); self.new_audit['schedule_status'] = 'stopped'
        self.write(cli.AUDITS['continuation'], self.new_audit)
        args = list(self.args); args[3] = cli.sha(self.root/cli.AUDITS['continuation'])
        with patch.object(cli, 'audit_runtime', return_value=self.new_audit):
            with self.assertRaisesRegex(ValueError, 'continuation_not_complete'):
                cli.compute(*args, frozen_aliases=cli.ALIASES)

    def test_changed_source_not_bound_to_runtime_is_rejected(self):
        self.fixture()
        self.write(cli.PREFIXES['continuation']+'responses.jsonl', b'{"changed":true}\n', raw=True)
        with patch.object(cli, 'audit_runtime', return_value=self.new_audit):
            with self.assertRaisesRegex(ValueError, 'runtime_bindings_differ'):
                cli.compute(*self.args, frozen_aliases=cli.ALIASES)

    def test_source_change_during_scoring_prevents_outputs(self):
        self.fixture()
        def evaluate(*args):
            self.write(cli.PREFIXES['continuation']+'responses.jsonl', b'changed during scoring\n', raw=True)
            return deepcopy(self.result)
        with patch.object(cli, 'audit_runtime', return_value=self.new_audit), patch.object(cli, 'evaluate_composite', side_effect=evaluate):
            with self.assertRaisesRegex(ValueError, 'source_changed_during_scoring'):
                cli.compute(*self.args, frozen_aliases=cli.ALIASES)
        self.assertFalse((self.root/cli.OUTPUT).exists())

    def test_raw_stream_change_after_audit_is_detected(self):
        self.fixture(); name = cli.PREFIXES['continuation']+'streams/fixture.sse'
        self.write(name, b'original stream bytes', raw=True)
        self.new_audit['input_bindings'][name] = cli.binding(self.root/name)
        self.write(cli.AUDITS['continuation'], self.new_audit)
        args = list(self.args); args[3] = cli.sha(self.root/cli.AUDITS['continuation'])
        def evaluate(*_):
            self.write(name, b'changed after independent audit', raw=True)
            return deepcopy(self.result)
        with patch.object(cli, 'audit_runtime', return_value=self.new_audit), patch.object(cli, 'evaluate_composite', side_effect=evaluate):
            with self.assertRaisesRegex(ValueError, 'runtime_evidence_changed_during_scoring'):
                cli.compute(*args, frozen_aliases=cli.ALIASES)
        self.assertFalse((self.root/cli.OUTPUT).exists())

    def test_unknown_alias_and_missing_transitive_code_rejected(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError, 'unsupported_frozen_alias'):
            cli.verify_inventory(self.root, self.args[1], {'another.lock': 'alias.txt'})
        self.write('scripts/new_helper.py', b'pass\n', raw=True)
        self.write('scripts/score_frontier_v6j.py', b'import scripts.new_helper\n', raw=True)
        freeze = cli.strict((self.root/cli.FREEZE).read_bytes())
        for row in freeze['files']:
            if row['path']=='scripts/score_frontier_v6j.py': row.update(cli.binding(self.root/row['path']))
        self.write(cli.FREEZE, freeze)
        with self.assertRaisesRegex(ValueError, 'missing_scientific_dependency'):
            cli.verify_inventory(self.root, cli.sha(self.root/cli.FREEZE), cli.ALIASES)

    def test_snapshot_must_be_immutable_member_and_hash_bound(self):
        self.fixture(); args = list(self.args); args[4] = 'results/frontier-v6j/budget/ledger.jsonl'
        with self.assertRaisesRegex(ValueError, 'immutable_ledger_snapshot_required'):
            cli.compute(*args, frozen_aliases=cli.ALIASES)
        args = list(self.args); args[5] = 'f'*64
        with self.assertRaisesRegex(ValueError, 'ledger_snapshot_hash'):
            cli.compute(*args, frozen_aliases=cli.ALIASES)

    def test_provenance_cannot_select_another_line_or_changed_row(self):
        segments = self.fixture(); merged = deepcopy(self.result['merged_evidence'])
        merged['outcomes'][0]['slot_id'] = 'modified'
        with self.assertRaisesRegex(ValueError, 'selected_view_changed_source_row'):
            cli.selected_source_lines(merged, segments, 'outcomes')
        merged = deepcopy(self.result['merged_evidence']); merged['source_provenance']['outcomes'][0]['source_line_one_based'] = 0
        with self.assertRaisesRegex(ValueError, 'source_line_index'):
            cli.selected_source_lines(merged, segments, 'outcomes')

    def test_writer_is_exclusive_and_manifest_binds_every_output(self):
        self.fixture(); result, views = self.compute()
        original_bytes = (self.root/(cli.PREFIXES['original']+'responses.jsonl')).read_bytes()
        manifest = cli.write_outputs(self.root, result, views)
        self.assertEqual(manifest['status'], 'complete_amended_primary')
        self.assertEqual(len(manifest['files']), 7)
        for name, expected in manifest['files'].items(): self.assertEqual(cli.binding(self.root/name), expected)
        self.assertEqual((self.root/(cli.PREFIXES['original']+'responses.jsonl')).read_bytes(), original_bytes)
        with self.assertRaisesRegex(ValueError, 'composite_output_already_exists'): cli.write_outputs(self.root, result, views)

    def test_paths_cannot_escape_root(self):
        for name in ('../outside', 'C:/outside', '/outside', 'a/../../b', 'a//b', 'file:stream'):
            with self.subTest(name=name), self.assertRaises(ValueError): cli.safe(self.root, name)


if __name__ == '__main__':
    unittest.main()
