"""Composition checks across compilation, intervention, clarification and coverage."""
import copy
import json
import unittest
from pathlib import Path

from retrace.engine_v4 import analyze_v4
from retrace.stress import analyze_stress

ROOT = Path(__file__).resolve().parents[1]
GATE = 'E a R 1 -\nE b R 0 -\nC c ?\nD d c\nAMBIGUOUS_GATE(c: a, b)\nEND'
OR = 'E a R 1 -\nE b R 1 -\nC c a|b\nD d c\nEND'


class EngineV4Tests(unittest.TestCase):
    def test_gate_disagreement_question_pruning_and_unknown(self):
        brief = {'compact_v4': GATE}
        result = analyze_v4(brief)
        self.assertEqual(result['decision_states']['d']['state'], 'needs_review')
        self.assertEqual(result['next_question']['id'], 'resolve_c')
        self.assertEqual(len(analyze_v4(brief, {'answers': {'resolve_c': None}})['candidate_ids']), 2)
        for answer, expected in ((False, 'unsupported'), (True, 'supported')):
            after = analyze_v4(brief, {'answers': {'resolve_c': answer}})
            self.assertEqual(len(after['candidate_ids']), 1)
            self.assertEqual(after['decision_states']['d']['classification'], expected)
            self.assertIsNone(after['next_question'])

    def test_source_authoritative_and_inputs_unmodified(self):
        brief = {'compact_v4': GATE, 'candidates': [], 'questions': [{'bad': True}]}
        state = {'answers': {'resolve_c': True}}
        original = copy.deepcopy((brief, state))
        result = analyze_v4(brief, state)
        exported = result['compiled_brief']
        exported['candidates'][0]['graph']['claims'][0]['supports'] = []
        second = analyze_v4(exported, state)
        self.assertEqual(second['decision_states'], result['decision_states'])
        self.assertEqual((brief, state), original)

    def test_declared_graph_legacy_semantics_stay_identical(self):
        brief = json.loads((ROOT / 'data/stress-demo.json').read_text(encoding='utf-8'))
        state = {'revoked_passages': ['V'], 'scenario_withdrawals': ['A']}
        before = analyze_stress(brief, state)
        after = analyze_v4(brief, state)
        for key in before.keys() - {'schema', 'scope'}:
            self.assertEqual(after[key], before[key], key)

    def test_coverage_uses_effective_document_passage_and_scenario_flags(self):
        brief = {'compact_v4': OR, 'documents': [{'id': 'doc', 'label': 'Both roots', 'evidence_ids': ['a', 'b']}]}
        self.assertTrue(analyze_v4(brief)['root_coverage']['warning'])
        for state in ({'revoked_documents': ['doc']}, {'revoked_passages': ['a']}, {'scenario_withdrawals': ['b']}):
            after = analyze_v4(brief, state)
            self.assertFalse(after['root_coverage']['warning'])
        after = analyze_v4(brief, {'revoked_documents': ['doc'], 'revoked_passages': ['a']})
        self.assertEqual(after['decision_states']['d']['classification'], 'revoked')
        self.assertTrue(after['revocation_flags']['a']['document_veto'])
        self.assertTrue(after['revocation_flags']['a']['passage_veto'])
        restored_document = analyze_v4(brief, {'revoked_passages': ['a']})
        self.assertFalse(restored_document['revocation_flags']['a']['document_veto'])
        self.assertTrue(restored_document['revocation_flags']['a']['passage_veto'])

    def test_guard_witness_reproduces_loss_with_strict_revoked_label(self):
        brief = {'compact_v4': OR}
        result = analyze_v4(brief)
        witness = result['root_coverage']['decisions']['d']['witnesses'][0]
        after = analyze_v4(brief, {'scenario_withdrawals': witness['roots']})
        self.assertEqual(after['decision_states']['d']['classification'], 'revoked')
        self.assertFalse(after['root_coverage']['merge_only_changes_current_support'])

    def test_guard_can_cover_roots_outside_interactive_scope(self):
        result = analyze_v4({'compact_v4': OR, 'allowed_withdrawals': []})
        self.assertTrue(result['root_coverage']['warning'])
        self.assertIsNone(result['decision_witnesses']['d']['minimum_break_any'])

    def test_scoped_attestation_projects_after_question_resolution(self):
        source = 'E a R 1 -\nE b ? 1 -\nC c a|b\nD d c\nUNVERIFIED_INDEPENDENCE(b, a)\nEND'
        brief = {'compact_v4': source, 'verified_independence': [
            {'roots': ['a', 'b'], 'basis': 'External provenance declaration', 'candidate_ids': ['branch-1']}]}
        self.assertFalse(analyze_v4(brief)['root_coverage']['warning'])
        self.assertFalse(analyze_v4(brief, {'answers': {'resolve_b': False}})['root_coverage']['warning'])
        self.assertFalse(analyze_v4(brief, {'answers': {'resolve_b': True}})['root_coverage']['warning'])
        brief['verified_independence'][0]['candidate_ids'] = ['typo-eliminated']
        with self.assertRaises(ValueError):
            analyze_v4(brief, {'answers': {'resolve_b': False}})

    def test_attestations_cannot_silently_accept_wrong_shapes(self):
        for value in ({}, False, '', 0, [{'roots': ['a', 'b']}], [{'roots': ['a', 'b'], 'basis': ' '}], [None]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                analyze_v4({'compact_v4': OR, 'verified_independence': value})
        self.assertTrue(analyze_v4({'compact_v4': OR, 'verified_independence': None})['root_coverage']['warning'])

    def test_current_equivalent_branches_survive_and_target_scope_stops_planner(self):
        source = GATE.replace('E b R 0', 'E b R 1') + '\n'
        result = analyze_v4({'compact_v4': source})
        self.assertEqual(len(result['candidate_ids']), 2)
        self.assertIsNone(result['next_question'])
        after = analyze_v4({'compact_v4': source}, {'scenario_withdrawals': ['b']})
        self.assertEqual(after['next_question']['id'], 'resolve_c')

    def test_demo_roundtrip_and_branch_count(self):
        source = (ROOT / 'data/ambiguity-v4-demo.txt').read_text(encoding='utf-8')
        result = analyze_v4({'compact_v4': source})
        self.assertEqual(len(result['candidate_ids']), 8)
        self.assertEqual(analyze_v4(result['compiled_brief'])['candidate_ids'], result['candidate_ids'])


if __name__ == '__main__':
    unittest.main()
