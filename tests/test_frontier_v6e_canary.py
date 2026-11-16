import json
import unittest
from retrace.source_ir_v6e_prompt import example
from retrace.source_ir_v6d import compile_cited_ir
from scripts.build_frontier_v6e_canary import source_cases,expected_family,build
from scripts.score_frontier_v6e_canary import evaluate
from tests.test_frontier_v6d_regression import fixture_ir


class ExtendedCanaryTests(unittest.TestCase):
    def test_prompt_example_is_complete_and_valid(self):
        docs,registry,ir=example();result=compile_cited_ir(ir,docs,registry)
        self.assertEqual(result['status'],'compiled');self.assertEqual(result['candidate_count'],1)

    def records(self):
        _,docs,registry=source_cases()
        case={'public':{'source_documents':docs,'registry':registry},
              'evaluation':{'expected_family':[{'graph':g} for g in expected_family()],'unidentified_ancestor_targets':[]}}
        ir=fixture_ir(case)
        return [{**{k:s[k] for k in ('slot_id','model','case_id','condition')},'http_status':200,'response_status':'completed',
                 'output_text':json.dumps({'R35':'unsupported'} if s['condition']=='canary_verdict' else ir)} for s in build()]

    def test_all_new_slots_score_and_truncation_fails(self):
        records=self.records();self.assertTrue(evaluate(build(),records)['passed'])
        records[1]['response_status']='incomplete'
        self.assertEqual(evaluate(build(),records)['passed_slots'],9)

    def test_identity_mismatch_is_not_scored(self):
        records=self.records();records[1]['model']='different'
        self.assertEqual(evaluate(build(),records)['passed_slots'],9)


if __name__=='__main__':unittest.main()
