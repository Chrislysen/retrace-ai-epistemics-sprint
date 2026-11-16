"""Invented outputs only: no provider calls or empirical journal reads."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from retrace import evidence_catalog_v6l as catalog
from retrace.adaption_v6h import PRIMARY_MODELS, digest
from retrace.prompts_v6h import example_ir, EXAMPLE_DOCUMENTS, EXAMPLE_REGISTRY
from retrace.source_ir_v6d import model_source
from retrace.source_ir_v6h import compile_ir


def fixture(count=1, full=False):
    models = list(PRIMARY_MODELS) if full else ['invented-model']
    count = 60 if full else count
    cases = [{'id': 'fixture-'+str(i), 'public': {'source_documents': deepcopy(EXAMPLE_DOCUMENTS),
               'registry': deepcopy(EXAMPLE_REGISTRY)}, 'evaluation': {'DO_NOT_EXPORT': 'HIDDEN_GOLD'},
               'authored_seed_pool': {'HIDDEN_SEED': True}} for i in range(count)]
    slots = []; audits = []; requests = []; responses = []; outcomes = []
    text = json.dumps(example_ir(), ensure_ascii=False)
    compilation = compile_ir(text, EXAMPLE_DOCUMENTS, EXAMPLE_REGISTRY)
    for case in cases:
        for model in models:
            sid = case['id']+'::'+model; aid = sid+'::attempt-1'
            payload = json.dumps(model_source(case['public']['source_documents'], case['public']['registry']))
            slot = {'slot_id': sid, 'case_id': case['id'], 'model': model, 'condition': 'strict_source_ir',
                    'phase': 'extract', 'input': payload}
            slots.append(slot)
            request = {'slot_id': sid, 'attempt_id': aid, 'first_attempt': True, 'attempt_number': 1,
                       'request': {'input': [{'role': 'user', 'content': payload}], 'instructions': 'Invented fixture contract'}}
            row = {**{k: slot[k] for k in ('slot_id', 'case_id', 'model', 'condition', 'phase')},
                   'attempt_id': aid, 'first_attempt': True, 'attempt_number': 1, 'issued': True,
                   'terminal_valid': True, 'model_outcome': 'completed', 'response_status': 'completed',
                   'error': None, 'output_text': text, 'partial_output_text': '', 'raw_response': '{"fixture":true}'}
            requests.append(request); responses.append(row); outcomes.append(deepcopy(row))
            audits.append({**{k: slot[k] for k in ('slot_id', 'case_id', 'model', 'condition', 'phase')},
                'view': 'first_attempt', 'record_observed': True, 'provider_completed': True, 'eligible_completed': True,
                'schema_valid': True, 'strict_bare_json': True, 'compilation': deepcopy(compilation),
                'correct': True, 'family': {'DO_NOT_EXPORT': 'HIDDEN_FAMILY'}, 'error': None})
    merged = {'requests': requests, 'responses': responses, 'outcomes': outcomes}
    bind(merged)
    return {'cases': cases}, {'all_case_ids': [c['id'] for c in cases], 'primary_models': models}, slots, audits, merged


def bind(merged):
    merged['source_bindings'] = {}; merged['source_provenance'] = {}
    for role in ('requests', 'responses', 'outcomes'):
        path = 'results/frontier-v6l/continuation/'+role+'.jsonl'
        lines = [(json.dumps(row, sort_keys=True, ensure_ascii=False)+'\n').encode() for row in merged[role]]
        raw = b''.join(lines); file_hash = sha256(raw).hexdigest()
        merged['source_bindings'][path] = {'sha256': file_hash, 'bytes': len(raw)}
        identity = 'slot_id' if role == 'outcomes' else 'attempt_id'
        merged['source_provenance'][role] = [{identity: row[identity], 'segment': 'l', 'source_path': path,
            'source_line_one_based': i+1, 'source_file_sha256': file_hash,
            'source_line_sha256': sha256(line).hexdigest(), 'row_sha256': digest(row)}
            for i, (row, line) in enumerate(zip(merged[role], lines))]


def build(data, full=False):
    return catalog.build_catalog(*data, require_full_design=full)


def entry(value, position=0):
    return value['entries'][value['index']['entries'][position]['entry_path']]


def changed_output(data, text):
    corpus, study, slots, audits, merged = data
    merged['responses'][0]['output_text'] = text; merged['outcomes'][0]['output_text'] = text
    try:
        comp = compile_ir(text, corpus['cases'][0]['public']['source_documents'], corpus['cases'][0]['public']['registry'])
        audits[0].update(compilation=comp, schema_valid=True, strict_bare_json=comp['strict_bare_json'], error=None)
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        audits[0].update(compilation=None, schema_valid=False, strict_bare_json=False, error='invalid_'+type(exc).__name__)
    bind(merged)


class CatalogTests(unittest.TestCase):
    def test_all300_in_fixed_case_then_model_order_and_no_mutation(self):
        data = fixture(full=True); before = deepcopy(data); result = build(data, full=True)
        self.assertEqual(data, before)
        self.assertEqual(result['index']['scheduled_slots'], 300)
        self.assertEqual(result['index']['counts']['admitted'], 300)
        self.assertEqual([(r['case_id'], r['model']) for r in result['index']['entries']],
                         [(c, m) for c in data[1]['all_case_ids'] for m in data[1]['primary_models']])
        self.assertFalse(result['index']['test_fixture'])
        with self.assertRaises(ValueError): build(fixture(), full=True)

    def test_restrictive_projection_excludes_hidden_and_unrecognized_fields(self):
        data = fixture(); case = data[0]['cases'][0]
        case['public']['oracle_answers'] = 'HIDDEN_ORACLE'
        case['public']['source_documents'][0]['private_annotation'] = 'HIDDEN_DOCUMENT'
        case['public']['registry']['private_annotation'] = 'HIDDEN_REGISTRY'
        data[3][0]['expected_decision'] = 'HIDDEN_DECISION'
        value = build(data); encoded = json.dumps(value)
        for forbidden in ('HIDDEN_', 'correct', 'family', 'oracle_answers', 'private_annotation', 'expected_decision'):
            self.assertNotIn(forbidden, encoded)
        brief = entry(value)['brief']
        self.assertEqual(set(brief), {'id', 'title', 'source_documents', 'registry', 'source_ir'})
        self.assertEqual(brief['source_ir'], example_ir())
        self.assertTrue(all(set(row) == {'id', 'text'} for row in brief['source_documents']))

    def test_fenced_admission_stays_non_strict_without_changing_raw(self):
        data = fixture(); text = '```json\n'+data[4]['responses'][0]['output_text']+'\n```'
        # Frozen parser admits a whole json fence under its existing contract.
        changed_output(data, text); result = entry(build(data))
        self.assertEqual(result['metadata']['status'], 'admitted')
        self.assertFalse(result['metadata']['strict_bare_json'])
        self.assertEqual(result['raw_output_text'], text)
        self.assertEqual(result['brief']['source_ir'], example_ir())

    def test_duplicate_key_and_invalid_ir_remain_visible_and_unloadable(self):
        for raw in ('{"schema":"x","schema":"y"}', 'I decline to produce a graph.', '{"unfinished":'):
            data = fixture(); changed_output(data, raw); result = entry(build(data))
            self.assertEqual(result['metadata']['status'], 'invalid_ir')
            self.assertTrue(result['metadata']['provider_completed'])
            self.assertIsNone(result['brief']); self.assertEqual(result['raw_output_text'], raw)
            self.assertIsNone(result['metadata']['registry_coverage_gaps'])

    def test_registry_gap_remains_loadable_with_explicit_warning(self):
        data = fixture(); public = data[0]['cases'][0]['public']; public['registry']['evidence'].append('EXMISSING')
        raw = data[4]['responses'][0]['output_text']
        source = json.dumps(model_source(public['source_documents'], public['registry']))
        data[2][0]['input'] = source; data[4]['requests'][0]['request']['input'][0]['content'] = source
        changed_output(data, raw); result = entry(build(data))
        self.assertEqual(result['metadata']['status'], 'admitted_registry_gap')
        self.assertEqual(result['metadata']['registry_coverage_gaps'], ['EXMISSING'])
        self.assertEqual(result['metadata']['warning_label'], 'Reference-Free Coverage Gap')
        self.assertIsNotNone(result['brief']); self.assertNotIn('EXMISSING', [x['id'] for x in result['brief']['source_ir']['entities']])

    def test_failed_first_attempt_is_never_replaced_by_successful_retry(self):
        data = fixture(); merged = data[4]; successful = deepcopy(merged['responses'][0]); request2 = deepcopy(merged['requests'][0])
        for row in (successful, request2): row.update(attempt_id=row['attempt_id']+'-retry', attempt_number=2, first_attempt=False)
        merged['responses'][0].update(terminal_valid=False, model_outcome='http_429', response_status=None, error='http_429', output_text='')
        merged['responses'].append(successful); merged['requests'].append(request2); merged['outcomes'][0] = successful
        data[3][0].update(provider_completed=False, eligible_completed=False, schema_valid=False,
                           strict_bare_json=False, compilation=None, error='http_429')
        bind(merged); result = entry(build(data))
        self.assertEqual(result['metadata']['status'], 'provider_failure'); self.assertEqual(result['metadata']['attempts_observed'], 2)
        self.assertEqual(result['raw_output_text'], ''); self.assertIsNone(result['brief'])
        self.assertNotIn('-retry', result['metadata']['attempt_id'])
        self.assertNotEqual(result['provenance']['selected_first_attempt']['response']['row_sha256'],
                            result['provenance']['selected_first_attempt']['final_outcome']['row_sha256'])

    def test_truncation_partial_is_preserved_without_loadable_repair(self):
        data = fixture(); row = data[4]['responses'][0]
        row.update(model_outcome='truncated_max_output_tokens', response_status='incomplete', output_text='', partial_output_text='{"schema":')
        data[4]['outcomes'][0] = deepcopy(row)
        data[3][0].update(provider_completed=False, eligible_completed=False, schema_valid=False,
                         strict_bare_json=False, compilation=None, error='truncated_max_output_tokens')
        bind(data[4]); result = entry(build(data))
        self.assertEqual(result['metadata']['status'], 'truncated_output'); self.assertEqual(result['partial_output_text'], '{"schema":')
        self.assertIsNone(result['brief'])

    def test_unissued_and_missing_first_cannot_borrow_later_output(self):
        data = fixture(); data[4]['requests'] = []; data[4]['responses'] = []
        data[4]['outcomes'][0].update(issued=False, attempt_id=None, model_outcome='not_issued_dependency_failed', output_text='')
        data[3][0].update(record_observed=False, provider_completed=False, eligible_completed=False, schema_valid=False,
                         strict_bare_json=False, compilation=None, error='missing_record')
        bind(data[4]); self.assertEqual(entry(build(data))['metadata']['status'], 'not_issued')
        data = fixture(); data[4]['responses'][0].update(first_attempt=False, attempt_number=2); bind(data[4])
        with self.assertRaisesRegex(ValueError, 'Contiguous'): build(data)

    def test_post_compile_scoring_failure_is_unavailable_not_repaired_admission(self):
        data = fixture(); data[3][0].update(schema_valid=False, strict_bare_json=False, compilation=None, error='invalid_ValueError')
        result = entry(build(data))
        self.assertEqual(result['metadata']['status'], 'scoring_unavailable')
        self.assertTrue(result['metadata']['compiler_admitted']); self.assertFalse(result['metadata']['schema_valid'])
        self.assertIsNone(result['brief']); self.assertEqual(result['raw_output_text'], data[4]['responses'][0]['output_text'])

    def test_saved_compiler_or_source_binding_disagreement_rejects(self):
        data = fixture(); data[3][0]['compilation']['candidate_count'] = 99
        with self.assertRaisesRegex(ValueError, 'Stored compiler'): build(data)
        data = fixture(); data[4]['source_provenance']['responses'][0]['row_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'row hash'): build(data)
        data = fixture(); data[4]['requests'][0]['request']['input'][0]['content'] = '{}'; bind(data[4])
        with self.assertRaisesRegex(ValueError, 'content differs'): build(data)

    def test_grid_duplicate_missing_and_wrong_phase_reject(self):
        for mutate in (lambda d: d[2].append(deepcopy(d[2][0])), lambda d: d[2].clear(), lambda d: d[2][0].update(phase='hist_init')):
            data = fixture(); mutate(data)
            with self.assertRaises(ValueError): build(data)


class FourSegmentProjectionTests(unittest.TestCase):
    def test_only_source_segment_and_output_directory_differ_from_frozen_builder(self):
        import ast
        root=Path(__file__).resolve().parents[1]
        def f(path):return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(path.read_text())) if isinstance(n,ast.FunctionDef)}
        old=f(root/'retrace/evidence_catalog_v6k.py');new=f(root/'retrace/evidence_catalog_v6l.py')
        for name in old:
            if name!='_pointer':self.assertEqual(new[name],old[name],name)
        old_text=(root/'retrace/evidence_catalog_v6k.py').read_text();new_text=(root/'retrace/evidence_catalog_v6l.py').read_text()
        old_pointer=ast.dump(next(n for n in ast.walk(ast.parse(old_text.replace("('i', 'j', 'k')","('i', 'j', 'k', 'l')"))) if isinstance(n,ast.FunctionDef) and n.name=='_pointer'),include_attributes=False)
        self.assertEqual(old_pointer,new['_pointer'])

    def test_l_source_pointer_is_preserved_and_unknown_segment_rejected(self):
        data=fixture();value=entry(build(data))
        self.assertEqual(value['provenance']['selected_first_attempt']['response']['segment'],'l')
        data[4]['source_provenance']['responses'][0]['segment']='invented-fifth'
        with self.assertRaisesRegex(ValueError,'Segment'):build(data)




from scripts import export_frontier_v6l_catalog as exporter
from retrace import server_v6l as reader
FREEZE_SHA='a'*64


class ExportGateTests(unittest.TestCase):
    def prepared(self,root,*,diagnostic=False):
        data=fixture(full=True);corpus,study,slots,audits,merged=data
        if diagnostic:
            sid=slots[0]['slot_id'];merged['requests']=[r for r in merged['requests'] if r['slot_id']!=sid]
            merged['responses']=[r for r in merged['responses'] if r['slot_id']!=sid]
            merged['outcomes'][0].update(issued=False,attempt_id=None,model_outcome='not_issued_global_stop',output_text='')
            audits[0].update(record_observed=False,provider_completed=False,eligible_completed=False,schema_valid=False,
                strict_bare_json=False,compilation=None,error='missing_record');bind(merged)
        for name,value in ((exporter.INPUTS['corpus'],corpus),(exporter.INPUTS['study'],study),(exporter.INPUTS['sessions'],slots)):
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value),encoding='utf-8')
        for name in exporter.SOURCES:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# invented source file\n')
        base=exporter.PARTIAL_OUTPUT if diagnostic else exporter.OUTPUT
        saved=base+('/partial-manifest.json' if diagnostic else '/composite-manifest.json')
        p=root/saved;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
        sources={name:exporter.binding(root/name) for name in exporter.INPUTS.values() if (root/name).exists()}
        stream='results/frontier-v6l/continuation/streams/invented.sse';p=root/stream;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'invented stream only')
        sources[stream]=exporter.binding(p)
        result={'summary':{'status':exporter.branch(diagnostic)[1],
                          'file_evidence':{'source_files':sources,'runtime_input_bindings':{}}},
                'audits':audits,'merged_evidence':merged}
        return result,{saved:exporter.binding(root/saved)},sources,corpus,study

    def run_mock(self,root,prepared,*,diagnostic=False):
        with patch.object(exporter,'authenticated_inputs',return_value=prepared) as gate, \
             patch.object(exporter,'compute',return_value=(prepared[0],{})) as partial, \
             patch.object(exporter,'verify_saved',return_value=prepared[1]), \
             patch.object(exporter,'verify_inventory',return_value=({},{})):
            value=exporter.run(root,FREEZE_SHA,'i','j','k','l','snapshot','snapshot-sha',diagnostic=diagnostic)
        self.assertEqual(partial.call_count,1 if diagnostic else 0)
        self.assertEqual(gate.call_count,0 if diagnostic else 1)
        return value

    def test_complete_and_interrupted_catalogs_have_no_fallback_and_replay_reader(self):
        for diagnostic in (False,True):
            with self.subTest(diagnostic=diagnostic),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);value=self.run_mock(root,self.prepared(root,diagnostic=diagnostic),diagnostic=diagnostic)
                with patch.object(exporter,'verify_inventory',return_value=({},{})):
                    manifest=exporter.write_catalog(root,value,diagnostic=diagnostic)
                self.assertEqual(manifest['status'],exporter.branch(diagnostic)[1])
                self.assertIs(manifest['inference_available'],not diagnostic)
                self.assertEqual(len(manifest['files']),600 if diagnostic else 601)
                for name,found in manifest['files'].items():self.assertEqual(exporter.binding(root/name),found)
                index=reader.EvidenceCatalog(root,expected_freeze_sha256=FREEZE_SHA,diagnostic=diagnostic).index()
                self.assertEqual(len(index['entries']),300)
                self.assertEqual(index['counts']['not_issued'],int(diagnostic))
                if diagnostic:
                    entry_value=next(iter(value['entries'].values()))
                    self.assertIsNone(entry_value['brief']);self.assertTrue(index['scope'].startswith(exporter.NOTICE))
                with self.assertRaisesRegex(ValueError,'Exclusive'):exporter.write_catalog(root,value,diagnostic=diagnostic)
                with self.assertRaisesRegex(ValueError,'Authenticated all300'):exporter.write_catalog(root,value,diagnostic=not diagnostic)

    def test_live_or_missing_saved_closure_prevents_any_scorer_or_modeltext_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);lock=root/exporter.LOCK;lock.parent.mkdir(parents=True);lock.write_text('active')
            with patch.object(exporter,'compute') as compute,patch.object(exporter,'authenticated_inputs') as gate:
                with self.assertRaisesRegex(ValueError,'Live'):exporter.run(root,FREEZE_SHA,'i','j','k','l','snapshot','sha')
                lock.unlink()
                with self.assertRaisesRegex(ValueError,'Saved authenticated'):exporter.run(root,FREEZE_SHA,'i','j','k','l','snapshot','sha')
                compute.assert_not_called();gate.assert_not_called()

    def test_runtime_stream_source_and_export_code_stay_bound_until_publication(self):
        for changed in ('results/frontier-v6l/continuation/streams/invented.sse',exporter.SOURCES[0]):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);value=self.run_mock(root,self.prepared(root));(root/changed).write_bytes(b'changed after plan')
                with patch.object(exporter,'verify_inventory',return_value=({},{})):
                    with self.assertRaisesRegex(ValueError,'changed before'):exporter.write_catalog(root,value)
                self.assertFalse((root/exporter.DIRECTORY).exists())

    def test_source_changed_during_projection_and_extra_payload_member_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepared=self.prepared(root);real=exporter.project
            def mutate(*args,**kw):
                value=real(*args,**kw);(root/exporter.INPUTS['sessions']).write_bytes(b'[]');return value
            with patch.object(exporter,'authenticated_inputs',return_value=prepared),patch.object(exporter,'project',side_effect=mutate),patch.object(exporter,'verify_inventory',return_value=({},{})):
                with self.assertRaisesRegex(ValueError,'changed before'):exporter.run(root,FREEZE_SHA,'i','j','k','l','snapshot','sha')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);value=self.run_mock(root,self.prepared(root))
            value['bundles'][exporter.DIRECTORY+'/bundles/unlisted.json']={'hidden':'unlisted'}
            with self.assertRaisesRegex(ValueError,'Exact catalog'):exporter.write_catalog(root,value)


if __name__=='__main__':unittest.main()
