"""All300 controlled-seed FIRST attempts, with public-only offline inspection."""
from copy import deepcopy
import json
from .evidence_catalog_v6l import (encode, require, text_hash, object_hash, public_source, _unique, _pointer)
from .adaption_v6h import PRIMARY_MODELS
from .frontier_v6h_eval import completed
from .frontier_v6c_io import parse_object
from .source_ir_v6d import model_source
from .refuter_inspector_v6l import inspect, seed_graphs, SCOPE

DIRECTORY = 'results/frontier-v6l/refuter-catalog'
STATUSES = ('source_located_proposal', 'abstained', 'rejected', 'provider_failure', 'truncated_output', 'not_issued')
META = {'key','slot_id','case_id','model','condition','phase','selection_view','status','provider_completed',
        'attempt_id','attempts_observed','model_outcome','error_code','requested_model','returned_model',
        'response_status','strict_bare_json','semantic_entailment_verified','source_completeness'}
PROVENANCE = {'selected_first_attempt','public_source_sha256','supplied_candidates_sha256','scheduled_input_sha256',
              'raw_output_text_sha256','partial_output_text_sha256','scope'}


def packet(slot, docs, registry):
    value, strict = parse_object(slot['input'])
    require(strict and set(value) == {'source_segments','registry','segment_semantics','supplied_candidates'}, 'Exact frozen refuter packet required')
    require({k:v for k,v in value.items() if k != 'supplied_candidates'} == model_source(docs, registry), 'Public source differs from model packet')
    require(not slot.get('history_from') and not slot.get('input_from'), 'Independent refuter cannot inherit another response')
    seed_graphs(value['supplied_candidates'])
    return value


def observation_status(first, final, inspection):
    if first is None: return 'not_issued'
    if completed(first): return inspection['status']
    return 'truncated_output' if first.get('model_outcome') == 'truncated_max_output_tokens' else 'provider_failure'


def build_catalog(corpus, study, slots, audits, merged_evidence, *, require_full_design=True):
    cases = _unique(corpus['cases'], 'id', 'case'); cids = study['all_case_ids']; models = study['primary_models']
    require(len(cids) == len(set(cids)) and len(models) == len(set(models)) and set(cases) == set(cids), 'Exact case and model inventory')
    if require_full_design: require(len(cids) == 60 and models == list(PRIMARY_MODELS), 'Exact60 by5 primary design')
    selected = [s for s in slots if s['condition'] == 'adversarial_refuter' and s['model'] in models]
    keyed = {}; pairs = [(c,m) for c in cids for m in models]
    for slot in selected:
        key = (slot['case_id'],slot['model'])
        require(key not in keyed and slot['phase'] == 'counter_read', 'Unique counter-reading slot')
        keyed[key] = slot
    require(set(keyed) == set(pairs), 'Complete refuter grid required')
    graded = _unique([a for a in audits if a.get('condition') == 'adversarial_refuter'
                     and a.get('model') in models and a.get('view') == 'first_attempt'], 'slot_id', 'first audit')
    require(set(graded) == {s['slot_id'] for s in selected}, 'Every scheduled first-attempt audit required')
    requests = _unique(merged_evidence['requests'], 'attempt_id', 'request')
    finals = _unique(merged_evidence['outcomes'], 'slot_id', 'final')
    _unique(merged_evidence['responses'], 'attempt_id', 'response'); by_slot = {}
    for row in merged_evidence['responses']: by_slot.setdefault(row['slot_id'], []).append(row)
    pointers = {role: _unique(merged_evidence['source_provenance'][role],
        'slot_id' if role == 'outcomes' else 'attempt_id', 'pointer') for role in ('requests','responses','outcomes')}
    bindings = merged_evidence['source_bindings']; entries = {}; rows = []
    for pair in pairs:
        slot = keyed[pair]; sid = slot['slot_id']; key = text_hash(sid); grade = graded[sid]; final = finals[sid]
        docs, registry = public_source(cases[pair[0]]); p = packet(slot,docs,registry)
        attempts = by_slot.get(sid, [])
        require([a['attempt_number'] for a in attempts] == list(range(1,len(attempts)+1)), 'Contiguous attempt order')
        first = attempts[0] if attempts else None; provider = completed(first)
        require(all(grade[k] == slot[k] for k in ('case_id','model','condition','phase'))
                and grade['record_observed'] is (first is not None)
                and grade['provider_completed'] is provider and grade['eligible_completed'] is provider, 'Audit first-attempt identity/completion')
        raw = first.get('output_text','') if first else ''; partial = first.get('partial_output_text','') if first else ''
        require(isinstance(raw,str) and isinstance(partial,str), 'Unchanged output strings required')
        inspection = inspect(raw,docs,registry,p['supplied_candidates']) if provider else None
        # Gate is reference-free, independent of later evaluation-only family scoring.
        if inspection and inspection['status'] != 'rejected':
            require(grade.get('schema_valid') is True and grade.get('refuter_gate') is not None, 'Saved admission must agree')
            saved_gate = grade['refuter_gate']
            for field in ('status','strict_bare_json','raw_warning_score','locations'):
                require(saved_gate[field] == inspection['gate'][field], 'Saved gate differs from raw replay')
        elif provider:
            require(grade.get('refuter_gate') is None and grade.get('schema_valid') is False, 'Rejected raw cannot retain admitted gate')
        pointer = {'request':None,'response':None,'final_outcome':_pointer(pointers['outcomes'][sid],final,bindings,'slot_id',sid)}
        if first:
            aid = first['attempt_id']; request = requests[aid]
            require(first.get('first_attempt') is True and first['slot_id']==sid and first['model']==slot['model'], 'Original first attempt required')
            require(request['slot_id']==sid and request['first_attempt'] is True and request['attempt_number']==1
                    and request['request']['input'][-1]['content']==slot['input'], 'Original request packet required')
            for role, row in (('request',request),('response',first)):
                pointer[role]=_pointer(pointers[role+'s'][aid],row,bindings,'attempt_id',aid)
        else: require(final.get('issued') is False and final.get('model_outcome')=='not_issued_global_stop', 'Unissued independent slot must stay stop-censored')
        status = observation_status(first,final,inspection)
        meta = {'key':key,'slot_id':sid,'case_id':pair[0],'model':pair[1],'condition':'adversarial_refuter',
            'phase':'counter_read','selection_view':'first_attempt','status':status,'provider_completed':provider,
            'attempt_id':first['attempt_id'] if first else None,'attempts_observed':len(attempts),
            'model_outcome':first.get('model_outcome') if first else final.get('model_outcome'),
            'error_code':first.get('error') if first else final.get('error'),
            'requested_model':first.get('requested_model',pair[1]) if first else pair[1],
            'returned_model':first.get('returned_model') if first else None,'response_status':first.get('response_status') if first else None,
            'strict_bare_json':inspection['gate'].get('strict_bare_json') if inspection else None,
            'semantic_entailment_verified':False,'source_completeness':'unknown'}
        value = {'schema':'retrace.controlled-refuter-entry.v6l.v1','metadata':meta,'source_documents':docs,'registry':registry,
            'supplied_candidates':deepcopy(p['supplied_candidates']),'raw_output_text':raw,'partial_output_text':partial,
            'inspection':inspection,'provenance':{'selected_first_attempt':pointer,
                'public_source_sha256':object_hash({'source_documents':docs,'registry':registry}),
                'supplied_candidates_sha256':object_hash(p['supplied_candidates']),'scheduled_input_sha256':text_hash(slot['input']),
                'raw_output_text_sha256':text_hash(raw),'partial_output_text_sha256':text_hash(partial),
                'scope':'Exact first-attempt pointers; final outcome never replaces the selected text.'},'scope':SCOPE}
        path = DIRECTORY+'/entries/'+key+'.json'; entries[path]=value
        rows.append({k:meta[k] for k in ('key','slot_id','case_id','model','status','provider_completed','strict_bare_json')} |
                    {'entry_path':path,'entry_sha256':text_hash(encode(value).decode('utf-8'))})
    return {'index':{'schema':'retrace.controlled-refuter-index.v6l.v1','scheduled_slots':len(pairs),
        'selection_view':'first_attempt','case_order':deepcopy(cids),'model_order':deepcopy(models),
        'counts':{s:sum(r['status']==s for r in rows) for s in STATUSES},'entries':rows,
        'scope':SCOPE,'test_fixture':not require_full_design},'entries':entries,'bundles':{}}


def validate_entry(value, *, replay=True):
    require(isinstance(value,dict) and set(value)=={'schema','metadata','source_documents','registry','supplied_candidates',
        'raw_output_text','partial_output_text','inspection','provenance','scope'}, 'Exact public refuter entry fields')
    require(value['schema']=='retrace.controlled-refuter-entry.v6l.v1' and value['scope']==SCOPE, 'Refuter scope/schema')
    m=value['metadata']; p=value['provenance']
    require(set(m)==META and set(p)==PROVENANCE and m['condition']=='adversarial_refuter' and m['phase']=='counter_read'
        and m['selection_view']=='first_attempt' and m['semantic_entailment_verified'] is False
        and m['source_completeness']=='unknown' and m['status'] in STATUSES, 'Exact public metadata')
    docs=value['source_documents']; registry=value['registry']
    require(isinstance(docs,list) and all(set(d)=={'id','text'} for d in docs) and set(registry)=={'evidence','claims','decisions'}, 'Public source fields only')
    model_source(docs,registry); seed_graphs(value['supplied_candidates'])
    require(p['public_source_sha256']==object_hash({'source_documents':docs,'registry':registry})
        and p['supplied_candidates_sha256']==object_hash(value['supplied_candidates'])
        and p['raw_output_text_sha256']==text_hash(value['raw_output_text'])
        and p['partial_output_text_sha256']==text_hash(value['partial_output_text']), 'Source/seed/raw hashes changed')
    selected=p['selected_first_attempt'];require(set(selected)=={'request','response','final_outcome'},'Source pointer roles')
    for pointer in selected.values():
        if pointer is not None:require(set(pointer)=={'segment','source_path','source_line_one_based','source_file_sha256','source_line_sha256','row_sha256'},'Public pointer fields')
    if m['provider_completed']:
        require(m['status'] in ('source_located_proposal','abstained','rejected') and value['inspection'] is not None, 'Completed inspection required')
        if replay:require(value['inspection']==inspect(value['raw_output_text'],docs,registry,value['supplied_candidates']), 'Inspection differs from unchanged raw replay')
        require(value['inspection']['status']==m['status'] and value['inspection']['gate'].get('strict_bare_json')==m['strict_bare_json'], 'Inspection status differs')
    else:require(value['inspection'] is None and m['status'] in ('provider_failure','truncated_output','not_issued'), 'Failed output cannot become a proposal')
    return value
