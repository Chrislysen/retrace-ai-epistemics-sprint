import copy
import json
import unittest
from pathlib import Path

from retrace.engine_v5 import analyze_v5, preview_exposure

ROOT = Path(__file__).resolve().parents[1]


def diagnostic():
    rows = json.loads((ROOT / 'results/ambiguity-v5-live-briefs.json').read_text(encoding='utf-8'))['briefs']
    return next(row for row in rows if row['id'] == 'exposure-diagnostic-ambiguity-v3-08')


class EngineV5Tests(unittest.TestCase):
    def test_inline_source_is_authoritative_and_pruning_still_works(self):
        brief = {'compact_v5': 'E a R 1 -\nE b R 0 -\nC c AMBIGUOUS_GATE(a, b)\nD d c\nEND', 'candidates': []}
        first = analyze_v5(brief)
        self.assertEqual(len(first['candidate_ids']), 2)
        self.assertEqual(first['ambiguity_compilation']['source_text'], brief['compact_v5'])
        after = analyze_v5(first['compiled_brief'], {'answers': {'resolve_c': True}})
        self.assertEqual(after['decision_states']['d']['classification'], 'supported')
        self.assertEqual(len(after['candidate_ids']), 1)

    def test_dormant_preview_does_not_change_source_or_normal_state(self):
        brief = diagnostic()
        saved = copy.deepcopy(brief)
        before = analyze_v5(brief)
        row = before['exposure']['decisions']['R08007']
        self.assertIsNone(row['minimum_without_enabling'])
        self.assertEqual((row['minimum']['enable_count'], row['minimum']['withdraw_count']), (1, 1))
        preview = preview_exposure(brief, {}, row['minimum']['enable'], row['minimum']['withdraw'])
        self.assertEqual(preview['outcomes']['observed-model']['R08007'], False)
        self.assertEqual(preview['outcomes']['authored-reference']['R08007'], True)
        self.assertEqual(brief, saved)
        self.assertEqual(analyze_v5(brief)['decision_states'], before['decision_states'])

    def test_explicit_exclusions_cannot_be_enabled_by_preview(self):
        brief = diagnostic()
        brief['documents'] = [{'id': 'doc', 'label': 'Certification', 'evidence_ids': ['R08001']}]
        for state in ({'revoked_documents': ['doc']}, {'revoked_passages': ['R08001']}, {'scenario_withdrawals': ['R08001']}):
            with self.subTest(state=state):
                result = analyze_v5(brief, state)
                self.assertFalse(result['exposure']['decisions']['R08007']['exposure_exists'])
                with self.assertRaises(ValueError):
                    preview_exposure(brief, state, ['R08001'], [])

    def test_bad_preview_sets_fail_closed(self):
        brief = diagnostic()
        for enable, withdraw in [(['unknown'], []), (['R08002'], []), ([], ['R08001']),
                                  (['R08001', 'R08001'], []), ('R08001', []), ([], None)]:
            with self.subTest(enable=enable, withdraw=withdraw), self.assertRaises((ValueError, TypeError)):
                preview_exposure(brief, {}, enable, withdraw)

    def test_wrong_exposure_scope_does_not_destroy_ordinary_analysis(self):
        brief = diagnostic()
        brief['allowed_exposure_changes'] = ['not-a-node']
        result = analyze_v5(brief)
        self.assertEqual(result['exposure']['status'], 'unavailable')
        self.assertEqual(result['decision_states']['R08007']['classification'], 'unsupported')

    def test_null_scope_uses_normalized_audit_scope_in_preview(self):
        brief = diagnostic()
        brief['allowed_exposure_changes'] = None
        row = analyze_v5(brief)['exposure']['decisions']['R08007']['minimum']
        preview = preview_exposure(brief, {}, row['enable'], row['withdraw'])
        self.assertNotEqual(preview['outcomes']['observed-model'], preview['outcomes']['authored-reference'])


if __name__ == '__main__':
    unittest.main()
