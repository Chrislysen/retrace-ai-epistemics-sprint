from copy import deepcopy
from pathlib import Path
import json
import unittest
from scripts.build_frontier_v6e_sessions import build,public_source,ir_source,verdict_input

ROOT=Path(__file__).resolve().parents[1]


class ProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus=json.loads((ROOT/'data/frontier-v6c-staged.json').read_text(encoding='utf-8'))
        cls.dossiers=json.loads((ROOT/'data/frontier-v6d-dossiers.json').read_text(encoding='utf-8'))

    def test_gold_and_family_poison_never_changes_request_text(self):
        case=deepcopy(self.corpus['cases'][0]);original=deepcopy(case)
        case['evaluation']={'gold':'FORBIDDEN_EVALUATION_POISON'}
        case['family']='FORBIDDEN_FAMILY_POISON';case['title']='FORBIDDEN_TITLE_POISON'
        for projection in [public_source,ir_source]:self.assertEqual(projection(original),projection(case))
        for phase in case['phases']:
            self.assertEqual(verdict_input(original,phase),verdict_input(case,phase))

    def test_4560_slots_exact_per_model_phases_draws_long(self):
        slots=build(self.corpus,self.dossiers)
        self.assertEqual(len(slots),4560);self.assertEqual(len({s['slot_id'] for s in slots}),4560)
        from collections import Counter
        self.assertEqual(set(Counter(s['model'] for s in slots).values()),{912})
        self.assertEqual(Counter(s['condition'] for s in slots),{'commitment':1440,'sample_graph':2400,'source_ir':240,'adversarial_refuter':240,'long_commitment':120,'long_source_ir':120})
        positions={s['slot_id']:i for i,s in enumerate(slots)}
        for i,s in enumerate(slots):
            payload=json.loads(s['input'])
            self.assertNotIn('evaluation',payload);self.assertNotIn('family',payload)
            self.assertEqual('supplied_candidates' in payload,s['condition']=='adversarial_refuter')
            for earlier in s.get('history_from',[]):self.assertLess(positions[earlier],i)
            self.assertNotIn('assistant',payload)

    def test_all_ten_draws_have_identical_public_prompts(self):
        slots=build(self.corpus,self.dossiers)
        case=slots[0]['case_id'];model=slots[0]['model']
        draws=[s for s in slots if s['case_id']==case and s['model']==model and s['condition']=='sample_graph']
        self.assertEqual(len(draws),10)
        self.assertEqual(len({s['input'] for s in draws}),1)
        self.assertEqual({s['temperature'] for s in draws},{1.0})

    def test_mismatched_duplicate_or_missing_dossier_rejected(self):
        for mutation in ('text','duplicate','missing','hash'):
            changed=deepcopy(self.dossiers)
            if mutation=='text':changed['cases'][0]['source_documents'][1]['text']='Different source'
            elif mutation=='duplicate':changed['cases'].append(deepcopy(changed['cases'][0]))
            elif mutation=='missing':changed['cases'].pop()
            else:changed['cases'][0]['measurement']['dossier_utf8_sha256']='0'*64
            with self.assertRaises(ValueError):build(self.corpus,changed)

    def test_short_and_long_original_documents_have_identical_metadata(self):
        packet=self.dossiers['cases'][0]
        case=next(c for c in self.corpus['cases'] if c['id']==packet['case_id'])
        short=public_source(case)['source_documents']
        long=public_source(case,packet['source_documents'])['source_documents']
        self.assertEqual(short,long[1:-1])
        self.assertTrue(all(set(d)=={'id','text'} for d in short+long))


if __name__=='__main__':unittest.main()
