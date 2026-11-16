from copy import deepcopy
import json
import unittest
from scripts.build_frontier_v6d_canary import build, source_cases
from scripts.score_frontier_v6d_canary import evaluate
from retrace.source_ir_v6d import source_segments


def valid_ir():
    _, docs, registry = source_cases()
    spans = {s['document_id']: s['span_id'] for s in source_segments(docs)}
    ir = {'schema': 'retrace.source-ir.v6d', 'entities': [], 'bindings': [],
          'choices': [{'id': 'reading', 'options': ['joint', 'single'], 'citations': [spans['policy']]}],
          'combination': {'mode': 'cartesian', 'assignments': [], 'citations': []}, 'propositions': []}
    for plural, ids in registry.items():
        typ = {'evidence': 'evidence', 'claims': 'claim', 'decisions': 'decision'}[plural]
        for entity in ids:
            ir['entities'].append({'id': entity, 'type': typ, 'operational': True,
                                   'citations': [spans['register' if typ == 'evidence' else 'policy']]})
    def prop(target, kind, body, doc='policy', when=None, polarity='assert'):
        ir['propositions'].append({'id': 'p' + str(len(ir['propositions'])), 'kind': kind,
                                  'target': target, 'body': body, 'scope': 'current', 'polarity': polarity,
                                  'when': when or {}, 'citations': [spans[doc]], 'bindings': []})
    for entity in registry['evidence']:
        prop(entity, 'eligibility', {'active': entity != 'H4'}, 'register')
        prop(entity, 'origin', {'kind': 'copy' if entity == 'T5' else 'root',
                               'parents': ['F2'] if entity == 'T5' else []},
             'production' if entity == 'T5' else 'register')
    prop('V6', 'support', {'expr': {'all': [{'ref': 'T5'}, {'ref': 'H4'}]}}, when={'reading': 'joint'})
    prop('V6', 'support', {'expr': {'ref': 'T5'}}, when={'reading': 'single'})
    prop('W7', 'support', {'expr': {'ref': 'H4'}})
    prop('Y8', 'requirement', {'requires': ['V6']})
    prop('Z9', 'requirement', {'requires': ['W7']})
    prop('T5', 'dependency', {'relation': 'parent', 'refs': ['G3']}, 'production', polarity='deny')
    return ir


class CanaryScoreTests(unittest.TestCase):
    def records(self):
        return [{'slot_id': s['slot_id'], 'output_text': json.dumps(
            {'Z6': 'supported'} if s['condition'] == 'canary_verdict' else valid_ir())} for s in build()]

    def test_exact_two_worlds_and_all_ten_denominator(self):
        result = evaluate(build(), self.records())
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['passed_slots'], 10)
        self.assertEqual(evaluate(build(), self.records()[:-1])['passed_slots'], 9)

    def test_wrong_parent_is_not_repaired(self):
        rows = self.records()
        ir = valid_ir()
        next(p for p in ir['propositions'] if p['target'] == 'T5' and p['kind'] == 'origin')['body']['parents'] = ['G3']
        rows[1]['output_text'] = json.dumps(ir)
        self.assertFalse(evaluate(build(), rows)['passed'])

    def test_outer_fence_preserves_strict_format_failure(self):
        rows = self.records()
        rows[0]['output_text'] = '```json\n' + rows[0]['output_text'] + '\n```'
        result = evaluate(build(), rows)
        self.assertTrue(result['passed'])
        self.assertFalse(result['results'][0]['strict_bare_json'])


if __name__ == '__main__':
    unittest.main()
