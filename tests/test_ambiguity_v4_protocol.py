"""Offline protocol integrity checks; no provider client, requests or secrets."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from retrace.ambiguity_v4_sessions import (
    ABSTENTION, BASE, BASELINE_HASHES, CONDITION, ROOT, build_config,
    build_public_corpus, build_sessions, json_bytes, prepare_artifacts,
    project_cost, public_projection, sha256_bytes,
)


class AmbiguityV4ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packets = json.loads((ROOT / 'data/ambiguity-v3-staged.json').read_text(encoding='utf-8'))

    def test_public_projection_preserves_exact_v3_prose_and_registry(self):
        public = build_public_corpus(self.packets)
        self.assertEqual(public, [p['public'] for p in self.packets])
        self.assertEqual(len(public), 10)
        for original, projected in zip(self.packets, public):
            for before, after in zip(original['public']['documents'], projected['documents']):
                self.assertEqual(before['text'].encode('utf-8'), after['text'].encode('utf-8'))
        public[0]['documents'][0]['text'] = 'Changed projected copy'
        self.assertNotEqual(public[0], self.packets[0]['public'])

    def test_hidden_and_nested_extra_poison_cannot_enter_sessions(self):
        poisoned = deepcopy(self.packets)
        marker = 'HIDDEN_ORACLE_POISON_8af218'
        for p in poisoned:
            p['hidden'] = {'answer': marker, 'graph': object()}
            p['source_context'] = {'provenance_constraints': marker}
            p['unknown_outer_key'] = marker
            p['public']['hidden_hint'] = marker
            p['public']['registry']['oracle'] = marker
            for d in p['public']['documents']:
                d['actual_answer'] = marker
        plain = build_sessions(self.packets)
        self.assertEqual(plain, build_sessions(poisoned))
        self.assertNotIn(marker, json.dumps(build_sessions(poisoned)))
        self.assertEqual(plain, build_sessions(build_public_corpus(self.packets)))

    def test_ten_unique_single_turn_sessions_use_one_fixed_prompt(self):
        sessions = build_sessions(self.packets)
        self.assertEqual(len(sessions), 10)
        self.assertEqual(len({(s['case_id'], s['condition']) for s in sessions}), 10)
        self.assertEqual({s['condition'] for s in sessions}, {CONDITION})
        self.assertEqual({s['instructions'] for s in sessions}, {BASE})
        self.assertIn('2^u', BASE)
        self.assertIn('u=4', BASE)
        self.assertIn(ABSTENTION, BASE)
        self.assertNotIn('ambiguity-v3-01', BASE)
        self.assertNotIn('R01001', BASE)
        for s in sessions:
            self.assertEqual(len(s['steps']), 1)
            self.assertEqual(s['steps'][0]['phase'], 'final')
            payload = json.loads(s['steps'][0]['input'])
            self.assertEqual(set(payload), {'id', 'title', 'documents', 'registry'})
            self.assertEqual(payload['id'], s['case_id'])
        self.assertEqual(sessions, build_sessions(self.packets))
        self.assertNotEqual([s['case_id'] for s in sessions], [s['case_id'] for s in build_sessions(self.packets, seed=1)])

    def test_duplicate_and_incomplete_case_sets_rejected(self):
        with self.assertRaises(ValueError):
            build_sessions(self.packets[:-1])
        with self.assertRaises(ValueError):
            build_sessions([self.packets[0]] * 10)
        malformed = deepcopy(self.packets[0])
        malformed['public']['registry']['claims'].append(malformed['public']['registry']['evidence'][0])
        with self.assertRaises(ValueError):
            public_projection(malformed)

    def test_decimal_projection_is_not_a_reservation(self):
        cost = project_cost()
        self.assertEqual(cost['status'], 'projected_only')
        self.assertIs(cost['reservation_created'], False)
        self.assertIs(cost['dispatch_authorized'], False)
        self.assertEqual(Decimal(cost['per_request_bound_credits']), Decimal('0.02443264'))
        self.assertEqual(Decimal(cost['hypothetical_new_bound_credits']), Decimal('0.24432640'))
        self.assertEqual(Decimal(cost['projected_cumulative_bound_credits']), Decimal('40.79280112'))
        self.assertEqual(Decimal(cost['projected_remaining_under_50_credits']), Decimal('9.20719888'))
        self.assertLess(Decimal(cost['projected_cumulative_bound_credits']), Decimal(41))
        for kwargs in ({'requests': 20}, {'requests': True}, {'max_output_tokens': 8192},
                       {'baseline_credits': '49.9'}, {'input_rate': 'NaN'}, {'output_rate': '-0.34'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                project_cost(**kwargs)

    def test_baseline_evidence_hashes_unchanged(self):
        for path, expected in BASELINE_HASHES.items():
            with self.subTest(path=path):
                self.assertEqual(sha256_bytes((ROOT / path).read_bytes()), expected)

    def test_config_is_projected_and_records_exact_sources(self):
        public = build_public_corpus(self.packets)
        sessions = build_sessions(public)
        config = build_config(ROOT, public, sessions)
        self.assertEqual(config['status'], 'projected_only')
        self.assertIs(config['reservation_created'], False)
        self.assertIs(config['dispatch_authorized'], False)
        self.assertIs(config['requires_later_user_approval'], True)
        self.assertEqual(config['public_sha256'], sha256_bytes(json_bytes(public)))
        self.assertEqual(config['sessions_sha256'], sha256_bytes(json_bytes(sessions)))
        self.assertEqual(config['baseline_evidence_sha256'], BASELINE_HASHES)
        self.assertFalse(config['comparison']['fresh_heldout'])
        self.assertTrue(config['comparison']['subset_selected_after_v3_results'])
        self.assertEqual(config['comparison']['primary_diagnostic_subset'], ['ambiguity-v3-01', 'ambiguity-v3-02', 'ambiguity-v3-04'])
        self.assertNotIn('reservation_id', config)
        self.assertNotIn('output_directory', config)

    def test_config_rejects_changed_public_prose_or_session_instructions(self):
        public = build_public_corpus(self.packets)
        sessions = build_sessions(public)
        changed_sessions = deepcopy(sessions)
        changed_sessions[0]['instructions'] += '\nCase-specific rescue instruction'
        with self.assertRaises(ValueError):
            build_config(ROOT, public, changed_sessions)
        changed_public = deepcopy(public)
        changed_public[0]['documents'][0]['text'] += ' Added answer hint.'
        with self.assertRaises(ValueError):
            build_config(ROOT, changed_public, build_sessions(changed_public))

    def test_generated_artifacts_match_offline_builder_and_price_evidence(self):
        public = build_public_corpus(self.packets)
        sessions = build_sessions(public)
        config = build_config(ROOT, public, sessions)
        for name, value in [('public', public), ('sessions', sessions), ('config', config)]:
            with self.subTest(name=name):
                self.assertEqual((ROOT / f'data/ambiguity-v4-{name}.json').read_bytes(), json_bytes(value))
        self.assertEqual(config['pricing']['verification_status'], 'reverified_by_root')
        self.assertEqual(config['pricing']['verified_date'], '2026-11-13')
        self.assertFalse(config['pricing']['cached_rate_used_in_projection'])

    def test_prepare_refuses_existing_or_frozen_outputs_before_writing(self):
        for name in ('ambiguity-v4-public.json', 'ambiguity-v4-freeze.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix='retrace-v4-protocol-') as directory:
                root = Path(directory)
                (root / 'data').mkdir()
                (root / 'data' / name).write_text('sentinel', encoding='utf-8')
                with self.assertRaises(FileExistsError):
                    prepare_artifacts(root)
                self.assertEqual(list((root / 'data').iterdir()), [root / 'data' / name])
                self.assertEqual((root / 'data' / name).read_text(encoding='utf-8'), 'sentinel')

    def test_v3_primary_mechanisms_are_not_all_selector_errors(self):
        responses = [json.loads(line) for line in (ROOT / 'results/ambiguity-v3/gemma-4-31b-it/responses.jsonl').read_text(encoding='utf-8').splitlines()]
        by_case = {cid: [r['output_text'] for r in responses if r['case_id'] == cid]
                   for cid in ('ambiguity-v3-01', 'ambiguity-v3-02', 'ambiguity-v3-04')}
        self.assertTrue(all(len(values) == 2 for values in by_case.values()))
        self.assertNotEqual(*by_case['ambiguity-v3-01'])
        self.assertTrue(all('R01001+R01002+R01003' in text for text in by_case['ambiguity-v3-01']))
        self.assertTrue(all('E R02002 R 1 -' in text for text in by_case['ambiguity-v3-02']))
        self.assertTrue(all('C R04005 R04003|R04004' in text for text in by_case['ambiguity-v3-04']))


if __name__ == '__main__':
    unittest.main()
