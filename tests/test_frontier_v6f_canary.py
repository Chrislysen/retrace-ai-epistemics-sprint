import json,unittest
from scripts.build_frontier_v6f_canary import build,source_cases,expected_family
from scripts.score_frontier_v6f_canary import evaluate
from tests.test_frontier_v6d_regression import fixture_ir


class PacingCanaryScoreTests(unittest.TestCase):
    def records(self):
        docs,registry=source_cases();family=expected_family()
        case={'public':{'source_documents':docs,'registry':registry},'evaluation':{'expected_family':[{'graph':g} for g in family],'unidentified_ancestor_targets':[]}}
        return [{**{k:s[k] for k in ('slot_id','model','case_id','condition')},'http_status':200,'response_status':'completed',
                 'output_text':json.dumps(family[0] if s['condition']=='canary_sample_graph' else fixture_ir(case))} for s in build()]

    def test_exact_family_and_single_graph_have_distinct_acceptance(self):
        rows=self.records();self.assertTrue(evaluate(build(),rows)['passed'])
        rows[0]['output_text']=json.dumps({'evidence':[],'claims':[],'decisions':[]})
        self.assertEqual(evaluate(build(),rows)['passed_slots'],9)

    def test_frozen_configuration(self):
        slots=build();self.assertEqual(len(slots),10);self.assertEqual({s['temperature'] for s in slots},{1.0})
        self.assertEqual({s['max_output_tokens'] for s in slots},{16384,65536})
        docs,_=source_cases();self.assertIn('miniature harbour',docs[0]['text'])

    def test_missing_and_incomplete_remain_failures(self):
        rows=self.records();rows[0]['response_status']='incomplete'
        result=evaluate(build(),rows[:-1]);self.assertEqual(result['passed_slots'],8);self.assertEqual(result['planned'],10)


if __name__=='__main__':unittest.main()
