"""Additive crash-prefix admission. No provider calls or old-artifact writes.

The orphan disposition is an explicitly derived final record, never a response.
It is compatible with the original scorer's existing issued_without_response
case. Actual issuance remains represented by the unchanged request journal.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from .adaption_v6h import digest, require, strict_event_json, slot_dependencies, nano
from . import frontier_v6i_eval as frozen
from .frontier_v6k_eval import is_definitive
from .recovery_v6m import orphan_disposition as historical_orphan_disposition

ROOT = Path(__file__).resolve().parents[1]
CONTINUATION = 'data/frontier-v6n-continuation.json'
BASELINE_LEDGER = 'data/frontier-v6m-ledger-after-interruption.jsonl'
RECOVERY_AUDITOR = 'scripts/audit_frontier_v6n_prefix.py'
OBSERVED_RESPONSE_MODELS = {'qwen3.5-397b':'qwen3.5-397b-a17b-nvfp4'}
DEADLINE = datetime(2026,11,16,6,56,tzinfo=timezone.utc)
M_FREEZE_SHA = 'd8820db0702d53169d4afac813756414e4d67fffd25d31ef312695181023da10'
OLD_OVERLAY = 'results/frontier-v6m-recovery/orphan-dispositions.jsonl'
NEW_OVERLAY = 'results/frontier-v6n-recovery/orphan-dispositions.jsonl'
OLD_PROOF = 'results/frontier-v6m-recovery/k-prefix-proof.json'
NEW_PROOF = 'results/frontier-v6n-recovery/m-prefix-proof.json'


def safe(root, name):
    require(isinstance(name,str) and name and '\\' not in name and ':' not in name
            and not Path(name).is_absolute() and '..' not in Path(name).parts,
            'recovery_relative_path_required')
    root=Path(root).resolve(); path=root/name
    require(path.resolve().is_relative_to(root),'recovery_path_escape')
    return path


def checked(root,name,expected):
    require(isinstance(expected,str) and len(expected)==64 and all(c in '0123456789abcdef' for c in expected),
            'recovery_invalid_hash')
    raw=safe(root,name).read_bytes()
    require(sha256(raw).hexdigest()==expected,'recovery_source_changed: '+name)
    return raw


def rows(raw):
    require(isinstance(raw,bytes) and (not raw or raw.endswith(b'\n')),'recovery_partial_jsonl')
    require(all(x.strip() for x in raw.splitlines()),'recovery_blank_jsonl')
    return [strict_event_json(x.decode('utf-8')) for x in raw.splitlines()]


def validate_receipt(receipt):
    require(receipt.get('schema')=='retrace.frontier-v6n-continuation.v1','recovery_receipt_schema')
    require(receipt.get('full_planned_slots')==1800 and receipt.get('sessions_path')=='data/frontier-v6i-sessions.json',
            'recovery_original_schedule')
    require(receipt.get('cumulative_cap_credits')=='750' and receipt.get('previous_cumulative_cap_credits')=='750'
            and receipt.get('observed_response_models')==OBSERVED_RESPONSE_MODELS,'recovery_execution_policy')
    require(receipt.get('prior_freeze_path')=='data/frontier-v6m-freeze.json'
            and receipt.get('prior_freeze_sha256')==M_FREEZE_SHA,'recovery_original_freeze')
    require(datetime.fromisoformat(receipt['deadline_utc'])==DEADLINE,'recovery_deadline')
    require(receipt.get('baseline_snapshot_path')==BASELINE_LEDGER
            and receipt.get('recovery_auditor_path')==RECOVERY_AUDITOR,'recovery_artifact_contract')
    require([s['segment'] for s in receipt['source_segments']]==['i','j','k','m'],'recovery_segment_order')
    specs=receipt.get('orphan_dispositions')
    require(isinstance(specs,list) and len(specs)==2 and [x.get('origin_segment') for x in specs]==['k','m'],
            'recovery_two_chronological_dispositions')
    require([x.get('path') for x in specs]==[OLD_OVERLAY,NEW_OVERLAY]
            and [x.get('proof_path') for x in specs]==[OLD_PROOF,NEW_PROOF]
            and receipt.get('recovery_proof_path')==NEW_PROOF,'recovery_overlay_paths')
    require(specs[1]['proof_sha256']==receipt['recovery_proof_sha256']
            and specs[1]['recovery_id']==receipt['recovery_id'],'recovery_current_overlay_proof')
    require(isinstance(receipt.get('orphan_attempt_ids'),list) and len(receipt['orphan_attempt_ids'])==2
            and len(set(receipt['orphan_attempt_ids']))==2,
            'recovery_two_distinct_orphans')
    for key in ('carried_final_slots','carried_issued_slots','continuation_slots','inherited_unsettled_attempts'):
        require(type(receipt.get(key)) is int and 0<=receipt[key]<=10000,'recovery_count_type')
    require(receipt['carried_final_slots']+receipt['continuation_slots']==1800
            and 224<receipt['carried_final_slots']<1800
            and 213<receipt['carried_issued_slots']<=receipt['carried_final_slots'],'recovery_count_partition')
    require(0<=nano(receipt['historical_conservative_carry_credits'])<=750_000_000_000,'recovery_prior_cap')
    stamp=datetime.fromisoformat(receipt['recovery_observed_at_utc'])
    require(stamp.tzinfo is not None and stamp<DEADLINE,'recovery_observation_time')
    return receipt


def read_receipt(path, expected_sha256):
    require(Path(path).resolve()==(ROOT/CONTINUATION).resolve(),'recovery_receipt_path')
    return validate_receipt(strict_event_json(checked(ROOT,CONTINUATION,expected_sha256).decode('utf-8')))


def orphan_disposition(slot,request,*,origin_run_id,recovery_id,proof_path,proof_sha256):
    """Make a new disposition only; never supplies terminal/output/usage data."""
    return {**{k:slot[k] for k in ('slot_id','case_id','model','condition','phase')},
        'run_id':recovery_id,'origin_run_id':origin_run_id,'record_origin':'derived_recovery_disposition',
        'actual_request_issued':True,'orphan_attempt_id':request['attempt_id'],
        'request_sha256':request['request_sha256'],'provider_response_observed':False,
        'provider_completion_unknown':True,'issued':False,'terminal_valid':False,
        'attempt_id':None,'attempts_issued':request['attempt_number'],
        'first_attempt_id':request['attempt_id'],'slot_final':True,
        'model_outcome':'issued_without_response','error':'process_interruption_orphan_request',
        'response_status':None,'output_text':'','usage':None,
        'recovery_proof_path':proof_path,'recovery_proof_sha256':proof_sha256,
        'scope':'Derived slot disposition only; no provider status, output, usage or original-run closure is asserted.'}


def derive_carry(slots,receipt,contents,*,continuation_sha256):
    """Pure checked reconstruction; caller must authenticate the forensic proof.

    ``contents`` contains exact receipt-bound journal and orphan-overlay bytes.
    All graph/answer interpretation is deferred to the unchanged frozen scorer.
    """
    require(len(slots)==receipt['full_planned_slots'] and digest(slots)==receipt['sessions_sha256'],
            'recovery_schedule_changed')
    index={s['slot_id']:s for s in slots};require(len(index)==len(slots),'recovery_duplicate_slot')
    finals={};requests=[];responses=[];bindings=[];run_ids=[];issued_ids=[]
    for seg in receipt['source_segments']:
        name=seg['segment'];paths=seg['paths'];run=strict_event_json(contents[paths['run_manifest']].decode('utf-8'))
        require(run['run_id']==seg['run_id'] and run['slots']==slots
                and run['sessions_sha256']==digest(slots),'recovery_prior_run')
        run_ids.append(run['run_id'])
        q=rows(contents[paths['requests']]);r=rows(contents[paths['responses']]);out=rows(contents[paths['outcomes']])
        require(all(x['run_id']==seg['run_id'] for x in r+out),'recovery_prior_row_run')
        require(not any(x['slot_id'] in finals for x in q),'recovery_prior_reissue')
        if name in ('i','j'):
            summary=strict_event_json(contents[paths['summary']].decode('utf-8'))
            error='response_model_mismatch' if name=='i' else 'network_or_transport_failure'
            require(summary['status']=='stopped' and summary['stop_reasons']==[error]
                    and summary['run_id']==seg['run_id'],'recovery_historical_stop_preserved')
            require(len(out)==len(slots)-len(finals),'recovery_historical_outcome_inventory')
        else:
            require('summary' not in paths and 'audit' not in paths,'recovery_no_fabricated_prefix_closure')
            require(all(is_definitive(x) for x in out),'recovery_prefix_only_observed_definitives')
        chosen=0
        for n,row in enumerate(out,1):
            sid=row['slot_id'];require(sid in index,'recovery_unknown_slot')
            if not is_definitive(row):
                require(name in ('i','j') and row['model_outcome']=='not_issued_global_stop'
                        and row['issued'] is False and row['attempts_issued']==0,'recovery_unlicensed_placeholder')
                continue
            require(sid not in finals,'recovery_duplicate_final');finals[sid]=deepcopy(row);chosen+=1
            bindings.append({'segment':name,'slot_id':sid,'source_path':paths['outcomes'],
                'source_line_one_based':n,'row_sha256':digest(row),'attempt_id':row.get('attempt_id'),
                'model_outcome':row['model_outcome']})
        require(chosen==seg['definitive_final_slots'],'recovery_prior_definitive_count')
        requests.extend(q);responses.extend(r)
        for row in q:
            if row['slot_id'] not in issued_ids:issued_ids.append(row['slot_id'])
    qmap={q['attempt_id']:q for q in requests};rmap={r['attempt_id']:r for r in responses}
    require(len(qmap)==len(requests) and len(rmap)==len(responses) and set(rmap)<=set(qmap),'recovery_attempt_inventory')
    orphan_ids=[q['attempt_id'] for q in requests if q['attempt_id'] not in rmap]
    require(len(orphan_ids)==2 and orphan_ids==receipt['orphan_attempt_ids'],'recovery_exact_orphans')
    specs=receipt['orphan_dispositions']
    require(len(specs)==2 and [s['origin_segment'] for s in specs]==['k','m'],'recovery_overlay_order')
    for aid,spec in zip(orphan_ids,specs):
        q=qmap[aid];sid=q['slot_id'];origin=spec['origin_segment']
        seg=next(s for s in receipt['source_segments'] if s['segment']==origin)
        require(any(x['attempt_id']==aid for x in rows(contents[seg['paths']['requests']])),
                'recovery_orphan_origin_mismatch')
        require(sid not in finals and q['attempt_number']==1,'recovery_orphan_already_final_or_retry')
        raw=contents[spec['path']]
        require(sha256(raw).hexdigest()==spec['sha256'],'recovery_overlay_bytes_changed')
        overlay=rows(raw);require(len(overlay)==1,'recovery_single_row_per_orphan')
        builder=historical_orphan_disposition if origin=='k' else orphan_disposition
        expected=builder(index[sid],q,origin_run_id=seg['run_id'],recovery_id=spec['recovery_id'],
            proof_path=spec['proof_path'],proof_sha256=spec['proof_sha256'])
        require(overlay[0]==expected,'recovery_orphan_disposition_changed');finals[sid]=deepcopy(overlay[0])
        bindings.append({'segment':'recovery' if origin=='k' else 'recovery_m','slot_id':sid,
            'source_path':spec['path'],'source_line_one_based':1,'row_sha256':digest(overlay[0]),
            'attempt_id':None,'model_outcome':'issued_without_response'})
    _,checked_finals,_,_=frozen.records(slots,list(finals.values()),responses,requests)
    completed={}
    for sid,row in checked_finals.items():
        if frozen.h.completed(row):
            body=qmap[row['attempt_id']]['request']
            completed[sid]={'actual_input':body['input'][-1]['content'],'output_text':row['output_text']}
    require(bindings==receipt['carried_final_outcomes'] and list(finals)==receipt['permanently_excluded_final_slot_ids']
            and issued_ids==receipt['permanently_excluded_issued_slot_ids'],'recovery_exact_carry_pointers')
    pending=[s['slot_id'] for s in slots if s['slot_id'] not in finals]
    require(pending==receipt['continuation_slot_ids'] and len(pending)==receipt['continuation_slots']
            and len(finals)==receipt['carried_final_slots'] and len(issued_ids)==receipt['carried_issued_slots'],
            'recovery_carry_complement')
    require(not set(pending)&{q['slot_id'] for q in requests},'recovery_issued_slot_cannot_repeat')
    unavailable=set(finals)-set(completed);descendants=[]
    for s in slots:
        if s['slot_id'] not in finals and any(d in unavailable for d in slot_dependencies(s)):
            unavailable.add(s['slot_id']);descendants.append(s['slot_id'])
    require(descendants==receipt['failed_producer_descendant_slot_ids'],'recovery_failed_descendant_scope')
    require(run_ids==receipt['original_run_ids'] and run_ids[0]==receipt['original_run_id'],'recovery_original_run_ids')
    return {'finals':finals,'completed':completed,'issued_slot_ids':issued_ids,'final_slot_ids':list(finals),
        'continuation_slot_ids':pending,'bindings':bindings,'failed_descendant_slot_ids':descendants,
        'last_issued_model':requests[-1]['request']['model'],'original_run_id':run_ids[0],'original_run_ids':run_ids,
        'earliest_next_admission_utc':(datetime.fromisoformat(receipt['recovery_observed_at_utc'])+timedelta(seconds=4)).isoformat(),
        'continuation_path':CONTINUATION,'continuation_sha256':continuation_sha256,
        'actual_issued_attempts':len(requests),'provider_response_records':len(responses),
        'orphan_attempt_ids':orphan_ids,'recovery_proof_sha256':receipt['recovery_proof_sha256']}


def _load_proof(receipt,*,root=None,frozen_aliases=None):
    root=Path(root or ROOT).resolve();aliases=dict(frozen_aliases or {})
    raw=checked(root,receipt['recovery_proof_path'],receipt['recovery_proof_sha256'])
    saved=strict_event_json(raw.decode('utf-8'))
    checked(root,receipt['recovery_auditor_path'],receipt['recovery_auditor_sha256'])
    from scripts.audit_frontier_v6n_prefix import audit
    actual=audit(root,receipt['prior_freeze_sha256'],frozen_aliases=aliases)
    require(actual==saved,'recovery_prefix_proof_does_not_reproduce')
    require(actual.get('passed') is True and actual.get('final_closed') is False
            and actual.get('schedule_status')=='interrupted_without_closure','recovery_proof_status')
    require(actual['cumulative_accounted_credits']==receipt['historical_conservative_carry_credits']
            and actual['cumulative_inherited_unsettled_attempts']==receipt['inherited_unsettled_attempts'],
            'recovery_budget_proof_changed')
    require(actual['host_observation']['observed_at_utc']==receipt['recovery_observed_at_utc'],
            'recovery_host_observation_binding')
    prior=actual['recovery_prefix_proof']
    require(prior.get('passed') is True and prior.get('final_closed') is False
            and prior.get('schedule_status')=='interrupted_without_closure','recovery_original_k_unclosed')
    require([prior['orphan']['attempt_id'],actual['orphan']['attempt_id']]==receipt['orphan_attempt_ids'],
            'recovery_exact_proven_orphans')
    contents={}
    for name,expected in receipt['prior_journal_files'].items():
        contents[name]=checked(root,aliases.get(name,name),expected)
        binding=actual['input_bindings'].get(name)
        require(binding=={'sha256':expected,'bytes':len(contents[name])},'recovery_prefix_binding_missing: '+name)
    for spec in receipt['orphan_dispositions']:
        name=spec['path'];contents[name]=checked(root,name,spec['sha256'])
        if spec['origin_segment']=='k':
            require(actual['input_bindings'].get(name)=={'sha256':spec['sha256'],'bytes':len(contents[name])},
                    'recovery_historical_overlay_not_in_prefix')
            oldraw=checked(root,spec['proof_path'],spec['proof_sha256'])
            require(strict_event_json(oldraw.decode('utf-8'))==prior,'recovery_original_k_proof_changed')
    name=receipt['baseline_snapshot_path'];contents[name]=checked(root,name,receipt['baseline_snapshot_sha256'])
    return actual,contents


def verify_continuation(slots,continuation_path,continuation_sha256):
    receipt=read_receipt(continuation_path,continuation_sha256);_,contents=_load_proof(receipt)
    return derive_carry(slots,receipt,contents,continuation_sha256=continuation_sha256)


def verify_prior_ledger(path,*,continuation_path,continuation_sha256):
    receipt=read_receipt(continuation_path,continuation_sha256)
    require(Path(path).resolve()==(ROOT/BASELINE_LEDGER).resolve(),'recovery_baseline_path')
    proof,contents=_load_proof(receipt)
    require(proof['input_bindings'].get(BASELINE_LEDGER)=={
        'sha256':receipt['baseline_snapshot_sha256'],'bytes':len(contents[BASELINE_LEDGER])},'recovery_snapshot_proof')
    return {'carry_credits':receipt['historical_conservative_carry_credits'],
        'file_sha256':receipt['baseline_snapshot_sha256'],
        'cumulative_inherited_unsettled_attempts':receipt['inherited_unsettled_attempts'],
        'continuation_path':CONTINUATION,'continuation_sha256':continuation_sha256,
        'recovery_proof_sha256':receipt['recovery_proof_sha256'],
        'orphan_attempt_ids':list(receipt['orphan_attempt_ids']),
        'authorization':'Interrupted-prefix recovery only. Every issued bound, including both unanswered orphans, is retained; no original k or m closure is asserted.'}
