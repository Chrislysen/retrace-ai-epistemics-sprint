"""Invented outputs only: no provider calls or empirical journal reads."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from retrace import evidence_catalog_v6k as catalog
from retrace.adaption_v6h import PRIMARY_MODELS, digest
from retrace.prompts_v6h import example_ir, EXAMPLE_DOCUMENTS, EXAMPLE_REGISTRY
from retrace.source_ir_v6d import model_source
from retrace.source_ir_v6h import compile_ir
from scripts import export_frontier_v6k_catalog as exporter
from scripts import analyze_frontier_v6k_trajectory as auth


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
        path = 'results/frontier-v6k/continuation/'+role+'.jsonl'
        lines = [(json.dumps(row, sort_keys=True, ensure_ascii=False)+'\n').encode() for row in merged[role]]
        raw = b''.join(lines); file_hash = sha256(raw).hexdigest()
        merged['source_bindings'][path] = {'sha256': file_hash, 'bytes': len(raw)}
        identity = 'slot_id' if role == 'outcomes' else 'attempt_id'
        merged['source_provenance'][role] = [{identity: row[identity], 'segment': 'k', 'source_path': path,
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


class CatalogCLITests(unittest.TestCase):
    def prepared(self, root):
        data = fixture(full=True); corpus, study, slots, audits, merged = data
        for name, value in ((exporter.INPUTS['corpus'], corpus), (exporter.INPUTS['study'], study), (exporter.INPUTS['sessions'], slots)):
            path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value), encoding='utf-8')
        for name in exporter.SOURCES:
            path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'# fixture source only\n')
        sources = {name: exporter.binding(root/name) for name in exporter.INPUTS.values() if (root/name).is_file()}
        result = {'audits': audits, 'merged_evidence': merged}
        return result, {}, sources, corpus, study

    def run_mock(self, root, prepared):
        with patch.object(exporter, 'authenticated_inputs', return_value=prepared) as gate:
            value = exporter.run(root, catalog.FREEZE_SHA256, 'i', 'j', 'k', 'snapshot', 's')
        gate.assert_called_once_with(root.resolve(), catalog.FREEZE_SHA256, 'i', 'j', 'k', 'snapshot', 's', frozen_aliases={})
        return value

    def test_exclusive_manifest_binds_all300_entries_and_bundles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); value = self.run_mock(root, self.prepared(root))
            manifest = exporter.write_catalog(root, value)
            self.assertEqual(manifest['schema'], 'retrace.evidence-catalog.v6k.v1')
            self.assertEqual(len(manifest['files']), 601)
            self.assertEqual(manifest['source_freeze_sha256'], catalog.FREEZE_SHA256)
            for name, bound in manifest['files'].items(): self.assertEqual(exporter.binding(root/name), bound)
            self.assertNotIn(catalog.DIRECTORY+'/manifest.json', manifest['files'])
            before = (root/catalog.DIRECTORY/'manifest.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'Exclusive'): exporter.write_catalog(root, value)
            self.assertEqual((root/catalog.DIRECTORY/'manifest.json').read_bytes(), before)

    def test_live_and_missing_closure_refuse_before_compute_or_writes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(auth, 'compute') as compute:
            root = Path(tmp); lock = root/'results/frontier-v6k/budget/active.lock'; lock.parent.mkdir(parents=True); lock.write_text('active')
            for name in exporter.SOURCES:
                path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'# fixture\n')
            with self.assertRaisesRegex(ValueError, 'live'): exporter.run(root, catalog.FREEZE_SHA256, 'i', 'j', 'k', 'snapshot', 's')
            lock.unlink()
            with self.assertRaisesRegex(ValueError, 'saved authenticated'): exporter.run(root, catalog.FREEZE_SHA256, 'i', 'j', 'k', 'snapshot', 's')
            compute.assert_not_called(); self.assertFalse((root/catalog.DIRECTORY).exists())

    def test_source_change_during_projection_cannot_authorize_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); prepared = self.prepared(root); real = exporter.build_catalog
            def mutate(*args, **kwargs):
                value = real(*args, **kwargs); (root/exporter.INPUTS['sessions']).write_text('[]'); return value
            with patch.object(exporter, 'authenticated_inputs', return_value=prepared), patch.object(exporter, 'build_catalog', side_effect=mutate):
                with self.assertRaisesRegex(ValueError, 'Source changed'): exporter.run(root, catalog.FREEZE_SHA256, 'i', 'j', 'k', 'snapshot', 's')
            self.assertFalse((root/catalog.DIRECTORY).exists())

    def test_between_plan_and_write_source_or_code_changes_reject_before_creation(self):
        for changed in (exporter.INPUTS['sessions'], exporter.SOURCES[0]):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); value = self.run_mock(root, self.prepared(root))
                (root/changed).write_bytes(b'changed after plan\n')
                with self.assertRaisesRegex(ValueError, 'changed before'): exporter.write_catalog(root, value)
                self.assertFalse((root/catalog.DIRECTORY).exists())

    def test_exporter_code_change_during_projection_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); prepared = self.prepared(root); real = exporter.build_catalog
            def mutate(*args, **kwargs):
                value = real(*args, **kwargs); (root/exporter.SOURCES[0]).write_text('# changed'); return value
            with patch.object(exporter, 'authenticated_inputs', return_value=prepared), patch.object(exporter, 'build_catalog', side_effect=mutate):
                with self.assertRaisesRegex(ValueError, 'Exporter source changed'): exporter.run(root, catalog.FREEZE_SHA256, 'i', 'j', 'k', 'snapshot', 's')


if __name__ == '__main__': unittest.main()
