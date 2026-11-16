"""Public-only, first-attempt extraction catalog. No truth labels or repairs.

The pure builder accepts authenticated composite data from its caller.
The public entry/index v6k format is deliberately reused without reinterpretation. The CLI
performs the required final crash-recovery replay before invoking it.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re

from .adaption_v6h import PRIMARY_MODELS, digest
from .frontier_v6h_eval import completed
from .source_ir_v6h import compile_ir
from .source_ir_v6d import model_source

DIRECTORY = 'results/frontier-v6m/catalog'
STATUSES = ('admitted', 'admitted_registry_gap', 'invalid_ir', 'scoring_unavailable',
            'provider_failure', 'truncated_output', 'not_issued')
SCOPE = ('Recorded first-attempt model interpretation, not verified textual entailment or source completeness. '
         'All scheduled primary strict-IR slots remain visible. Imports start from the recorded local eligibility '
         'with no event vetoes, answers, document groups or gold-derived questions; this is not a scored temporal phase.')


def require(ok, why):
    if not ok:
        raise ValueError(why)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode('utf-8')


def text_hash(value):
    return sha256(value.encode('utf-8')).hexdigest()


def object_hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def public_source(case):
    """An allowlist projection: never copy arbitrary case/public/document fields."""
    public = case['public']
    docs = [{'id': row['id'], 'text': row['text']} for row in public['source_documents']]
    registry = {kind: deepcopy(public['registry'][kind]) for kind in ('evidence', 'claims', 'decisions')}
    # Reuse the frozen public source validation and span inventory, not gold.
    model_source(docs, registry)
    return docs, registry


def _unique(rows, key, description):
    result = {}
    for row in rows:
        value = row[key]
        require(value not in result, 'Duplicate '+description)
        result[value] = row
    return result


def _pointer(pointer, row, bindings, identity_key, identity):
    fields = ('segment', 'source_path', 'source_line_one_based', 'source_file_sha256', 'source_line_sha256', 'row_sha256')
    require(pointer.get(identity_key) == identity, 'Provenance identity mismatch')
    result = {key: pointer[key] for key in fields}
    name = result['source_path']
    require(isinstance(name, str) and not PurePosixPath(name).is_absolute() and '\\' not in name
            and ':' not in name and all(p not in ('', '.', '..') for p in name.split('/')), 'Safe relative provenance path')
    require(result['segment'] in ('i', 'j', 'k', 'm') and type(result['source_line_one_based']) is int
            and result['source_line_one_based'] > 0, 'Segment and source line required')
    require(all(isinstance(result[k], str) and re.fullmatch(r'[0-9a-f]{64}', result[k])
                for k in ('source_file_sha256', 'source_line_sha256', 'row_sha256')), 'Source hashes required')
    require(result['row_sha256'] == digest(row), 'Source row hash mismatch')
    require(name in bindings and bindings[name]['sha256'] == result['source_file_sha256'], 'Source file hash mismatch')
    return result


def _entry(slot, case, graded, attempts, requests, final, provenance, bindings):
    sid = slot['slot_id']; key = text_hash(sid)
    docs, registry = public_source(case)
    require(json.loads(slot['input']) == model_source(docs, registry), 'Scheduled public source differs from projected source')
    require(not slot.get('history_from') and not slot.get('input_from'), 'Strict extraction cannot inherit a history')
    require(graded['case_id'] == slot['case_id'] and graded['model'] == slot['model']
            and graded['condition'] == 'strict_source_ir' and graded['phase'] == 'extract', 'Graded slot identity mismatch')
    require([r['attempt_number'] for r in attempts] == list(range(1, len(attempts)+1)), 'Contiguous attempt order required')
    first = attempts[0] if attempts else None
    if first:
        require(first.get('first_attempt') is True and first['slot_id'] == sid and first['model'] == slot['model'], 'First attempt identity')
    require(graded['record_observed'] is (first is not None), 'Graded first-attempt presence mismatch')
    provider = completed(first)
    require(graded['provider_completed'] is provider and graded['eligible_completed'] is provider,
            'Graded first-attempt completion mismatch')
    raw = first.get('output_text', '') if first else ''
    partial = first.get('partial_output_text', '') if first else ''
    require(isinstance(raw, str) and isinstance(partial, str), 'Recorded output strings required')
    compilation = None; compiler_error = None
    if provider:
        try:
            compilation = compile_ir(raw, docs, registry)
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
            compiler_error = 'invalid_'+type(exc).__name__
    stored = graded.get('compilation')
    if stored is not None:
        require(provider and graded['schema_valid'] is True and compilation is not None,
                'Stored compiler admission cannot be reproduced')
        for field in ('original_ir', 'strict_bare_json', 'candidate_count', 'registry_coverage_gaps', 'source_sha256'):
            require(compilation[field] == stored[field], 'Stored compiler field differs: '+field)
        require(graded['strict_bare_json'] is compilation['strict_bare_json'], 'Saved format admission differs')
        status = 'admitted_registry_gap' if compilation['registry_coverage_gaps'] else 'admitted'
    elif provider and compilation is not None:
        # Frozen grading can fail in canonical-family scoring after compilation,
        # before it stores any compilation. Do not promote that row to admitted.
        require(graded['schema_valid'] is False and graded.get('error') in
                ('invalid_ValueError', 'invalid_TypeError', 'invalid_KeyError', 'invalid_RecursionError', 'invalid_OverflowError'),
                'Unexplained absent saved compilation')
        status = 'scoring_unavailable'
    elif provider:
        require(graded['schema_valid'] is False and graded.get('error') == compiler_error,
                'Saved rejection differs from frozen compiler')
        status = 'invalid_ir'
    elif first is None:
        require(final.get('issued') is False and not graded['schema_valid'], 'Unissued extraction cannot be admitted')
        status = 'not_issued'
    else:
        require(not graded['schema_valid'] and stored is None, 'Provider failure cannot be admitted')
        status = 'truncated_output' if first.get('model_outcome') == 'truncated_max_output_tokens' else 'provider_failure'
    loadable = status in ('admitted', 'admitted_registry_gap')
    gaps = deepcopy(compilation['registry_coverage_gaps']) if loadable else None
    count = compilation['candidate_count'] if loadable else 0
    metadata = {'key': key, 'slot_id': sid, 'case_id': slot['case_id'], 'model': slot['model'],
        'condition': 'strict_source_ir', 'phase': 'extract', 'selection_view': 'first_attempt',
        'status': status, 'provider_completed': provider, 'schema_valid': graded['schema_valid'],
        'strict_bare_json': graded['strict_bare_json'], 'compiler_admitted': compilation is not None,
        'candidate_count': count, 'registry_coverage_gaps': gaps, 'loadable': loadable,
        'attempt_id': first['attempt_id'] if first else None, 'attempts_observed': len(attempts),
        'model_outcome': first.get('model_outcome') if first else final.get('model_outcome'),
        'failure_scope': first.get('failure_scope') if first else None,
        'error_code': first.get('error') if first and first.get('error') else graded.get('error'),
        'requested_model': first.get('requested_model', slot['model']) if first else slot['model'],
        'returned_model': first.get('returned_model') if first else None,
        'response_status': first.get('response_status') if first else None,
        'warning_label': 'Reference-Free Coverage Gap' if gaps else None,
        'source_entailment_verified': False, 'source_completeness': 'unknown'}
    selected = {'request': None, 'response': None,
        'final_outcome': _pointer(provenance['outcomes'][sid], final, bindings, 'slot_id', sid)}
    if first:
        aid = first['attempt_id']; request = requests[aid]
        require(request['slot_id'] == sid and request['first_attempt'] is True and request['attempt_number'] == 1,
                'First request identity mismatch')
        require(request['request']['input'][-1]['content'] == slot['input'], 'Recorded request content differs')
        selected['request'] = _pointer(provenance['requests'][aid], request, bindings, 'attempt_id', aid)
        selected['response'] = _pointer(provenance['responses'][aid], first, bindings, 'attempt_id', aid)
    source_hash = object_hash({'source_documents': docs, 'registry': registry})
    provider_raw = first.get('raw_response') if first else None
    provenance_out = {'selected_first_attempt': selected, 'public_source_sha256': source_hash,
        'scheduled_input_sha256': text_hash(slot['input']), 'raw_output_text_sha256': text_hash(raw),
        'partial_output_text_sha256': text_hash(partial),
        'raw_provider_response_sha256': text_hash(provider_raw) if isinstance(provider_raw, str) else None,
        'original_ir_sha256': object_hash(compilation['original_ir']) if loadable else None,
        'scope': 'Request/response pointers bind the FIRST attempt; final_outcome is a separate audit link and never supplies replacement text.'}
    brief = {'id': 'recorded-'+key, 'title': 'Recorded first-attempt interpretation — '+slot['model'],
             'source_documents': deepcopy(docs), 'registry': deepcopy(registry),
             'source_ir': deepcopy(compilation['original_ir'])} if loadable else None
    return {'schema': 'retrace.evidence-entry.v6k.v1', 'metadata': metadata,
            'source_documents': docs, 'registry': registry, 'raw_output_text': raw,
            'partial_output_text': partial, 'brief': brief, 'provenance': provenance_out, 'scope': SCOPE}


def build_catalog(corpus, study, slots, audits, merged_evidence, *, require_full_design=True):
    """Pure public projection. Full-design mode is mandatory in the real CLI."""
    case_ids = study['all_case_ids']; models = study['primary_models']
    require(len(case_ids) == len(set(case_ids)) and len(models) == len(set(models)), 'Unique planned cohort')
    if require_full_design:
        require(len(case_ids) == 60 and models == list(PRIMARY_MODELS), 'Exactly60 cases and5 fixed primary models required')
    cases = _unique(corpus['cases'], 'id', 'case')
    require(set(cases) == set(case_ids), 'Corpus/study case inventory mismatch')
    chosen = [s for s in slots if s['condition'] == 'strict_source_ir' and s['model'] in models]
    keyed = {}
    for s in chosen:
        pair = (s['case_id'], s['model'])
        require(pair not in keyed and s['phase'] == 'extract', 'Duplicate or wrong-phase extraction')
        keyed[pair] = s
    pairs = [(cid, model) for cid in case_ids for model in models]
    require(set(keyed) == set(pairs), 'Complete planned primary extraction grid required')
    graded = _unique([r for r in audits if r.get('condition') == 'strict_source_ir'
                      and r.get('model') in models and r.get('view') == 'first_attempt'], 'slot_id', 'first-attempt grade')
    require(set(graded) == {keyed[p]['slot_id'] for p in pairs}, 'Complete first-attempt graded grid required')
    requests = _unique(merged_evidence['requests'], 'attempt_id', 'request')
    finals = _unique(merged_evidence['outcomes'], 'slot_id', 'final outcome')
    _unique(merged_evidence['responses'], 'attempt_id', 'response')
    by_slot = {}
    for row in merged_evidence['responses']:
        by_slot.setdefault(row['slot_id'], []).append(row)
    pointers = {role: _unique(merged_evidence['source_provenance'][role],
                  'slot_id' if role == 'outcomes' else 'attempt_id', 'source pointer')
                for role in ('requests', 'responses', 'outcomes')}
    entries = {}; bundles = {}; rows = []
    for pair in pairs:
        slot = keyed[pair]; sid = slot['slot_id']
        entry = _entry(slot, cases[pair[0]], graded[sid], by_slot.get(sid, []), requests,
                       finals[sid], pointers, merged_evidence['source_bindings'])
        meta = entry['metadata']; key = meta['key']; path = DIRECTORY+'/entries/'+key+'.json'
        entries[path] = entry
        bundle_path = DIRECTORY+'/bundles/'+key+'.json' if entry['brief'] is not None else None
        if bundle_path:
            bundles[bundle_path] = entry['brief']
        rows.append({k: meta[k] for k in ('key', 'slot_id', 'case_id', 'model', 'status', 'provider_completed',
                    'strict_bare_json', 'candidate_count', 'registry_coverage_gaps')} |
                    {'entry_path': path, 'entry_sha256': sha256(encode(entry)).hexdigest(), 'bundle_path': bundle_path,
                     'bundle_sha256': sha256(encode(entry['brief'])).hexdigest() if bundle_path else None})
    index = {'schema': 'retrace.evidence-index.v6k.v1', 'scheduled_slots': len(pairs),
             'selection_view': 'first_attempt', 'case_order': deepcopy(case_ids), 'model_order': deepcopy(models),
             'counts': {status: sum(r['status'] == status for r in rows) for status in STATUSES},
             'entries': rows, 'scope': SCOPE, 'test_fixture': not require_full_design}
    return {'index': index, 'entries': entries, 'bundles': bundles}
