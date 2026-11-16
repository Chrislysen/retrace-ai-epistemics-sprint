from copy import deepcopy
import unittest
from retrace.source_ir_v6h import compile_ir
from retrace.source_ir_v6d import source_segments
from retrace.prompts_v6h import example_ir, EXAMPLE_DOCUMENTS, EXAMPLE_REGISTRY
from retrace.graph_identity_v6h import family_score
from scripts.build_frontier_v6h_legacy import build
import json
from pathlib import Path


class SourceIRTests(unittest.TestCase):
    def test_exact_example_locations_and_no_entailment_claim(self):
        result=compile_ir(example_ir(),EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY)
        self.assertTrue(result['citations_verified']);self.assertFalse(result['semantic_entailment_verified'])
        self.assertEqual(result['candidate_count'],1)

    def test_unmatched_span_or_changed_source_rejects_entire_ir(self):
        ir=example_ir();ir['propositions'][0]['citations']=['invented']
        with self.assertRaises(ValueError):compile_ir(ir,EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY)
        docs=deepcopy(EXAMPLE_DOCUMENTS);docs[0]['text']+=' altered'
        with self.assertRaises(ValueError):compile_ir(example_ir(),docs,EXAMPLE_REGISTRY)

    def test_duplicate_json_and_unknown_fields_reject(self):
        raw=json.dumps(example_ir());raw=raw.replace('"schema":','"schema":"duplicate", "schema":',1)
        with self.assertRaises(ValueError):compile_ir(raw,EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY)
        ir=example_ir();ir['confidence']=.9
        with self.assertRaises(ValueError):compile_ir(ir,EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY)

    def test_historical_undercutter_is_still_typed(self):
        for scope in ('historical','hypothetical','proposed','current'):
            ir=example_ir();prop=next(p for p in ir['propositions'] if p['kind']=='support')
            # Same target remains a self reference too; use a separate declared claim.
            docs=deepcopy(EXAMPLE_DOCUMENTS);docs.append({'id':'extra','text':'Historical claim EXH is recorded only as a prior proposal.'})
            span=source_segments(docs)[-1]['span_id']
            ir['entities'].append({'id':'EXH','type':'claim','operational':scope=='current','citations':[span]})
            ir['propositions'].append({'id':'old','kind':'support','target':'EXH','body':{'positive':{'unless':{'support':{'ref':'EXA'},'undercutter':{'ref':'EXC'}}},'negative':{'const':False}},'scope':scope,'when':{},'citations':[span],'bindings':[]})
            with self.assertRaises(ValueError):compile_ir(ir,docs,EXAMPLE_REGISTRY)

    def test_one_incomplete_choice_branch_rejects_not_prunes(self):
        ir=example_ir();span=ir['entities'][0]['citations'][0]
        ir['choices']=[{'id':'u','options':['one','two'],'citations':[span]}]
        ir['propositions'][0]['when']={'u':'one'}
        with self.assertRaises(ValueError):compile_ir(ir,EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY)

    def test_registry_omission_is_explicit_but_never_invented(self):
        registry=deepcopy(EXAMPLE_REGISTRY);registry['evidence'].append('EXMISSING')
        result=compile_ir(example_ir(),EXAMPLE_DOCUMENTS,registry)
        self.assertEqual(result['status'],'reference_free_coverage_gap')
        self.assertEqual(result['registry_coverage_gaps'],['EXMISSING'])
        self.assertNotIn('EXMISSING',[r['id'] for r in result['candidates'][0]['graph']['evidence']])

    def test_bound_binding_decoy_does_not_fill_current_definition(self):
        ir=example_ir();prop=ir['propositions'][0];prop['scope']='historical'
        with self.assertRaises(ValueError):compile_ir(ir,EXAMPLE_DOCUMENTS,EXAMPLE_REGISTRY)

    def test_40_legacy_sources_compile_to192_unchanged_worlds(self):
        root=Path(__file__).resolve().parents[1]
        cases=build(json.loads((root/'data/frontier-v6c-staged.json').read_text(encoding='utf-8')))
        self.assertEqual(len(cases),40);self.assertEqual(sum(len(c['evaluation']['source_family']) for c in cases),192)
        for case in cases:
            result=compile_ir(case['evaluation']['reference_ir'],case['public']['source_documents'],case['public']['registry'])
            self.assertTrue(family_score(result['candidates'],case['evaluation']['source_family'])['exact_family'])


if __name__=='__main__':unittest.main()
