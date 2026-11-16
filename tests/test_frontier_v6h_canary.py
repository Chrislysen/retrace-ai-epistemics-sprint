"""Independent constructed checks for the outside-corpus v6h contract probes.

No provider calls or observed model outputs. The scalar source oracle below
does not use the builder's positive-expression helper or the compiler scorer.
"""
from collections import Counter
from copy import deepcopy
from itertools import product
import json
import unittest

from scripts.build_frontier_v6h_canary import build, source, reference_ir, expected_family, seeds, CASE_ID
from scripts.score_frontier_v6h_canary import evaluate
from scripts.run_frontier_v6h import verify_canary
from retrace.adaption_v6h import PRIMARY_MODELS
from retrace.prompts_v6h import IR_INSTRUCTIONS, REFUTER_INSTRUCTIONS
from retrace.source_ir_v6h import compile_ir
from retrace.source_ir_v6d import source_segments, model_source
from retrace.graph_identity_v6h import graph_key
from retrace.tiered_v6h import family_supervaluation


def output_for(slot, ir=None):
    ir = deepcopy(reference_ir() if ir is None else ir)
    if slot['condition'] == 'canary_refuter':
        spans = {row['document_id']:row['span_id'] for row in source_segments(source()[0])}
        return json.dumps({'status':'objection', 'ir':ir, 'objection_spans':[spans['assembly'], spans['polarity']], 'warning_score':.7})
    return json.dumps(ir)


def attempt(slot, number=1, outcome='completed', text=None):
    completed = outcome == 'completed'; truncated = outcome == 'truncated_max_output_tokens'; limited = outcome == 'http_429'
    return {**{key:slot[key] for key in ('slot_id','case_id','model','condition','phase')},
        'run_id':'constructed-canary-test', 'attempt_id':f"constructed-canary-test:{slot['slot_id']}:attempt-{number}",
        'attempt_number':number, 'first_attempt':number == 1, 'issued':True,
        'terminal_valid':completed or truncated, 'model_outcome':outcome,
        'response_status':'completed' if completed else 'incomplete' if truncated else None,
        'http_status':429 if limited else 200 if completed or truncated else 500,
        'error':None if completed or truncated else outcome,
        'output_text':output_for(slot) if text is None and completed else text or '',
        'partial_output_text':output_for(slot) if truncated else '',
        'latency_ms':10, 'usage':None, 'settled_credits':None}


def final(record, first=None):
    return {**deepcopy(record), 'slot_final':True, 'attempts_issued':record['attempt_number'],
            'first_attempt_id':(first or record)['attempt_id']}


class CanarySourceTests(unittest.TestCase):
    def test_ten_exact_public_projections_no_reference_or_annotations(self):
        slots = build(); docs, registry = source(); public = model_source(docs, registry)
        self.assertEqual(len(slots), 10)
        self.assertEqual(Counter(s['model'] for s in slots), Counter({m:2 for m in PRIMARY_MODELS}))
        for slot in slots:
            expected = deepcopy(public)
            if slot['condition'] == 'canary_refuter': expected['supplied_candidates'] = seeds()
            self.assertEqual(json.loads(slot['input']), expected)
            self.assertEqual(slot['instructions'], REFUTER_INSTRUCTIONS if slot['condition'] == 'canary_refuter' else IR_INSTRUCTIONS)
            self.assertEqual(slot['case_id'], CASE_ID)
            self.assertEqual(slot['max_output_tokens'], 32768)
            self.assertNotIn('history_from', slot); self.assertNotIn('input_from', slot)

    def test_exact_spans_complete_two_readings_and_shared_joint_parents(self):
        docs, registry = source(); text = {d['id']:d['text'] for d in docs}
        spans = source_segments(docs)
        for span in spans: self.assertEqual(text[span['document_id']][span['start']:span['end']], span['text'])
        ir = reference_ir(); known = {s['span_id'] for s in spans}
        self.assertTrue(all(set(p['citations']) <= known and p['citations'] for p in ir['propositions']))
        result = compile_ir(ir, docs, registry)
        self.assertEqual(result['candidate_count'], 2)
        self.assertEqual({graph_key(r['graph']) for r in result['candidates']}, {graph_key(r['graph']) for r in expected_family()})
        for row in result['candidates']:
            evidence = {e['id']:e for e in row['graph']['evidence']}
            self.assertEqual(evidence['I72']['parents'], ['H71']); self.assertEqual(evidence['J73']['parents'], ['H71'])
            self.assertEqual(set(evidence['K74']['parents']), {'I72','J73'})
            claim = next(c for c in row['graph']['claims'] if c['id'] == 'P78')
            self.assertEqual(claim['negative'], {'ref':'N77'})

    def test_all_128_eligibility_states_match_independent_scoped_polar_oracle(self):
        identifiers = ['H71','I72','J73','K74','L75','M76','N77']
        families = expected_family()
        for bits in product((False, True), repeat=len(identifiers)):
            active = dict(zip(identifiers, bits)); exclusions = [i for i in identifiers if not active[i]]
            copied = active['H71'] and active['I72'] and active['J73'] and active['K74']
            for row in families:
                positive = ((copied and not active['M76']) or active['L75']) if row['id'] == 'narrow' else ((copied or active['L75']) and not active['M76'])
                status = 'contested' if positive and active['N77'] else 'supported' if positive else 'not_supported'
                actual = family_supervaluation([row['graph']], scenario_withdrawals=exclusions)['candidates'][0]['decisions']
                self.assertEqual(actual['R80']['state'], status, (row['id'], active))
                self.assertEqual(actual['S81']['state'], 'supported' if active['L75'] else 'not_supported')

    def test_controlled_seeds_have_only_the_declared_two_defects(self):
        for seeded, faithful in zip(seeds(), expected_family()):
            repaired = deepcopy(seeded['graph'])
            next(e for e in repaired['evidence'] if e['id'] == 'K74')['parents'] = ['I72','J73']
            next(c for c in repaired['claims'] if c['id'] == 'P78')['negative'] = {'ref':'N77'}
            self.assertEqual(repaired, faithful['graph'])
            self.assertNotEqual(graph_key(seeded['graph']), graph_key(faithful['graph']))


class CanaryScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.slots = build()

    def test_empty_run_retains_ten_missing_denominator_slots(self):
        result = evaluate(self.slots, [], [])
        self.assertEqual((result['planned'], result['observed_attempts'], result['final_exact_family']), (10,0,0))
        self.assertEqual(len(result['final_slots']), 10)
        self.assertTrue(all(r['failure'] == 'missing_outcome' for r in result['final_slots']))

    def test_all_exact_authored_outputs_and_all_attempts_remain_visible(self):
        rows = [attempt(s) for s in self.slots]
        result = evaluate(self.slots, [final(r) for r in rows], rows)
        self.assertEqual(result['final_operational_completed'], 10)
        self.assertEqual(result['final_schema_accepted'], 10)
        self.assertEqual(result['final_exact_family'], 10)
        self.assertEqual(result['first_attempt_exact_family'], 10)

    def test_429_then_success_counts_first_attempt_and_eventual_separately(self):
        first = attempt(self.slots[0], outcome='http_429'); second = attempt(self.slots[0], 2)
        result = evaluate(self.slots, [final(second, first)], [first, second])
        self.assertEqual(result['observed_attempts'], 2); self.assertEqual(result['first_attempt_exact_family'], 0)
        self.assertEqual(result['final_exact_family'], 1)
        self.assertFalse(result['all_attempts'][0]['accepted']); self.assertTrue(result['all_attempts'][1]['exact_family'])
        self.assertEqual(sum(r['failure'] == 'missing_outcome' for r in result['final_slots'] if 'failure' in r), 9)

    def test_truncation_and_schema_failure_cannot_be_repaired_by_partial_text(self):
        truncated = attempt(self.slots[0], outcome='truncated_max_output_tokens')
        malformed = attempt(self.slots[2], text='{"schema":')
        result = evaluate(self.slots, [final(truncated),final(malformed)], [truncated,malformed])
        self.assertEqual(result['final_schema_accepted'], 0)
        self.assertEqual(result['final_operational_completed'], 1)
        self.assertEqual(result['final_exact_family'], 0)

    def test_exact_citation_but_semantically_wrong_claim_is_not_source_faithful(self):
        ir = reference_ir()
        for p in ir['propositions']:
            if p['kind'] == 'support' and p['target'] == 'P78': p['body']['negative'] = {'const':False}
        row = attempt(self.slots[0], text=output_for(self.slots[0], ir))
        scored = evaluate(self.slots, [final(row)], [row])['final_slots'][0]
        self.assertTrue(scored['accepted']); self.assertFalse(scored['exact_family'])
        self.assertEqual(scored['family']['missing_distinct'], 2)
        self.assertEqual(scored['family']['spurious_distinct'], 2)

    def test_refuter_abstention_is_retained_and_never_source_family_success(self):
        row = attempt(self.slots[1], text=json.dumps({'status':'no_counter_reading','ir':None,'objection_spans':[],'warning_score':0.0}))
        scored = evaluate(self.slots, [final(row)], [row])['final_slots'][1]
        self.assertTrue(scored['operational_completed']); self.assertFalse(scored['exact_family'])
        self.assertEqual(scored['gate_status'], 'abstained')

    def test_unknown_citation_atomic_rejection_not_partial_family_credit(self):
        ir = reference_ir(); ir['propositions'][-1]['citations'] = ['absent']
        row = attempt(self.slots[1], text=output_for(self.slots[1], ir))
        scored = evaluate(self.slots, [final(row)], [row])['final_slots'][1]
        self.assertFalse(scored['accepted']); self.assertFalse(scored['exact_family'])

    def test_identity_duplicate_attempt_and_duplicate_final_rejected(self):
        row = attempt(self.slots[0])
        with self.assertRaises(ValueError): evaluate(self.slots, [final(row),final(row)], [row])
        with self.assertRaises(ValueError): evaluate(self.slots, [final(row)], [row,row])
        broken = deepcopy(row); broken['model'] = self.slots[2]['model']
        with self.assertRaises(ValueError): evaluate(self.slots, [final(broken)], [broken])

    def test_final_requires_observed_matching_last_attempt(self):
        row = attempt(self.slots[0])
        with self.assertRaises(ValueError): evaluate(self.slots, [final(row)], [])
        changed = final(row); changed['output_text'] = '{}'
        with self.assertRaises(ValueError): evaluate(self.slots, [changed], [row])

    def test_attempt_sequence_rejects_duplicate_number_and_non429_retry(self):
        first = attempt(self.slots[0]); duplicate = deepcopy(first); duplicate['attempt_id'] += '-different'
        with self.assertRaises(ValueError): evaluate(self.slots, [final(duplicate)], [first,duplicate])
        later = attempt(self.slots[0], 2)
        with self.assertRaises(ValueError): evaluate(self.slots, [final(later,first)], [first,later])
        with self.assertRaises(ValueError): evaluate(self.slots, [final(later)], [later])

    def test_inconsistent_completed_flags_cannot_enter_semantic_scoring(self):
        for field, value in (('http_status',429),('error','http_429'),('response_status','incomplete'),('issued',False)):
            row = attempt(self.slots[0]); row[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): evaluate(self.slots, [final(row)], [row])

    def test_unissued_final_cannot_fabricate_completion_without_attempts(self):
        row = final(attempt(self.slots[0])); row['issued'] = False
        row['attempts_issued'] = 0; row['first_attempt_id'] = None
        with self.assertRaises(ValueError): evaluate(self.slots, [row], [])

    def test_exhausted429_operational_failure_and_explicit_skips_remain_failures(self):
        limited = [attempt(self.slots[0], n, 'http_429') for n in (1,2,3)]
        failed = attempt(self.slots[1], outcome='operational_failure')
        slot = self.slots[2]
        skipped = {**{k:slot[k] for k in ('slot_id','case_id','model','condition','phase')},
            'run_id':'constructed-canary-test', 'issued':False, 'terminal_valid':False,
            'model_outcome':'not_issued_global_stop', 'error':'not_issued_global_stop',
            'response_status':None, 'output_text':'', 'slot_final':True, 'attempts_issued':0, 'first_attempt_id':None}
        result = evaluate(self.slots, [final(limited[-1],limited[0]),final(failed),skipped], limited+[failed])
        self.assertEqual(result['observed_attempts'], 4); self.assertEqual(result['final_exact_family'], 0)
        self.assertEqual(result['final_operational_completed'], 0)
        self.assertEqual(len(result['all_attempts']), 4)
        self.assertEqual(result['final_slots'][2]['model_outcome'], 'not_issued_global_stop')

    def test_runtime_canary_gate_is_operational_not_perfect_semantics(self):
        value = {'schema':'retrace.adaption-v6h-summary.v1','canary':True,'status':'completed','stream':True,'planned':10,
            'issued_slots':10,'slot_outcomes':10,'valid_terminal_records':10,'issued_operational_failures':0,'dependency_skips':0,
            'unissued_slot_ids':[],'issued_without_outcome_attempt_ids':[],'models':{m:2 for m in PRIMARY_MODELS},
            'truncated':3, 'eventual_completed':7, 'http_429_attempts':2, 'issued_attempts':12}
        verify_canary(value)
        broken = deepcopy(value); broken['unissued_slot_ids'] = ['missing']
        with self.assertRaises(ValueError): verify_canary(broken)


if __name__ == '__main__': unittest.main()
