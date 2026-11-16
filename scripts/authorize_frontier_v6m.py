"""Exclusive admission of untouched slots after a verified unclosed k prefix.

Never edits the historical lock, ledger, responses, outcomes or missing summary.
No credential or provider operation. A new orphan disposition is not a response.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace import recovery_v6m as recovery
from retrace.adaption_v6h import digest, encoded, require, slot_dependencies
from retrace.frontier_v6k_eval import is_definitive
from retrace.frontier_v6h_eval import completed
from scripts.audit_frontier_v6m_prefix import audit

PROOF='results/frontier-v6m-recovery/k-prefix-proof.json'
ORPHAN='results/frontier-v6m-recovery/orphan-dispositions.jsonl'
AUTH='data/frontier-v6m-authorization.json'
RECEIPT=recovery.CONTINUATION
SNAPSHOT=recovery.BASELINE_LEDGER
FREEZE='data/frontier-v6k-freeze.json'
SESSIONS='data/frontier-v6i-sessions.json'


def read(name):return json.loads(recovery.safe(ROOT,name).read_bytes())
def file_sha(name):return sha256(recovery.safe(ROOT,name).read_bytes()).hexdigest()
def rows(name):return recovery.rows(recovery.safe(ROOT,name).read_bytes())
def json_bytes(value):return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')


def build(*,proof_sha256):
    require(datetime.now(timezone.utc)<recovery.DEADLINE,'delivery_buffer_reached')
    require(file_sha(PROOF)==proof_sha256,'recovery_proof_changed')
    proof=read(PROOF)
    require(proof==audit(ROOT,recovery.K_FREEZE_SHA),'prefix_replay_differs')
    require(proof['passed'] is True and proof['final_closed'] is False
            and proof['schedule_status']=='interrupted_without_closure','unclosed_prefix_required')
    require(file_sha(FREEZE)==recovery.K_FREEZE_SHA,'k_freeze_changed')
    frozen=read(FREEZE);require(len(frozen['files'])==1320,'full_k_freeze_required')
    slots=read(SESSIONS);index={s['slot_id']:s for s in slots}
    require(len(index)==len(slots)==1800,'original_schedule_required')
    segments=deepcopy(read('data/frontier-v6k-continuation.json')['source_segments'])
    require([s['segment'] for s in segments]==['i','j'],'original_segments_required')
    kpaths={role:'results/frontier-v6k/continuation/'+name for role,name in
            {'run_manifest':'run.json','requests':'requests.jsonl','responses':'responses.jsonl','outcomes':'slot-outcomes.jsonl'}.items()}
    kpaths['ledger']='results/frontier-v6k/budget/ledger.jsonl'
    kout=rows(kpaths['outcomes']);krun=read(kpaths['run_manifest']);kq=rows(kpaths['requests'])
    require(all(is_definitive(r) for r in kout),'only_observed_k_definitives')
    segments.append({'segment':'k','run_id':krun['run_id'],'freeze_path':FREEZE,
        'freeze_sha256':recovery.K_FREEZE_SHA,'paths':kpaths,
        'sha256':{role:file_sha(name) for role,name in kpaths.items()},
        'definitive_final_slots':len(kout),'issued_slots':len({q['slot_id'] for q in kq})})
    prior={};finals={};bindings=[];requests=[];responses=[];issued=[];run_ids=[]
    for seg in segments:
        run_ids.append(seg['run_id'])
        for role,name in seg['paths'].items():
            require(file_sha(name)==seg['sha256'][role],'historical_segment_changed')
            prior[name]=seg['sha256'][role]
        qs=rows(seg['paths']['requests']);rs=rows(seg['paths']['responses'])
        requests.extend(qs);responses.extend(rs)
        for q in qs:
            if q['slot_id'] not in issued:issued.append(q['slot_id'])
        for n,row in enumerate(rows(seg['paths']['outcomes']),1):
            if not is_definitive(row):continue
            sid=row['slot_id'];require(sid not in finals,'duplicate_definitive')
            finals[sid]=row
            bindings.append({'segment':seg['segment'],'slot_id':sid,'source_path':seg['paths']['outcomes'],
                'source_line_one_based':n,'row_sha256':digest(row),'attempt_id':row.get('attempt_id'),
                'model_outcome':row['model_outcome']})
    responded={r['attempt_id'] for r in responses};orphans=[q for q in requests if q['attempt_id'] not in responded]
    require(len(orphans)==1 and orphans[0]['attempt_id']==proof['orphan']['attempt_id'],'exact_orphan_required')
    q=orphans[0];sid=q['slot_id'];require(sid not in finals,'orphan_already_final')
    rid='host-loss-'+uuid.uuid4().hex
    annotation=recovery.orphan_disposition(index[sid],q,origin_run_id=krun['run_id'],
        recovery_id=rid,proof_path=PROOF,proof_sha256=proof_sha256)
    orphan_raw=(encoded(annotation)+'\n').encode('utf-8');finals[sid]=annotation
    bindings.append({'segment':'recovery','slot_id':sid,'source_path':ORPHAN,
        'source_line_one_based':1,'row_sha256':digest(annotation),'attempt_id':None,'model_outcome':'issued_without_response'})
    pending=[s['slot_id'] for s in slots if s['slot_id'] not in finals]
    require(not set(pending)&set(issued),'issued_slot_cannot_repeat')
    unavailable={sid for sid,r in finals.items() if not completed(r)};descendants=[]
    for s in slots:
        if s['slot_id'] not in finals and any(d in unavailable for d in slot_dependencies(s)):
            unavailable.add(s['slot_id']);descendants.append(s['slot_id'])
    prior[SNAPSHOT]=file_sha(SNAPSHOT)
    for name,h in prior.items():
        require(proof['input_bindings'].get(name)=={'sha256':h,'bytes':recovery.safe(ROOT,name).stat().st_size},
                'source_missing_from_prefix_proof: '+name)
    observed=proof['host_observation']['observed_at_utc']
    receipt={'schema':'retrace.frontier-v6m-continuation.v1','created_at':datetime.now(timezone.utc).isoformat(),
        'recovery_id':rid,'recovery_observed_at_utc':observed,
        'prior_freeze_path':FREEZE,'prior_freeze_sha256':recovery.K_FREEZE_SHA,
        'baseline_snapshot_path':SNAPSHOT,'baseline_snapshot_sha256':prior[SNAPSHOT],
        'historical_conservative_carry_credits':proof['cumulative_accounted_credits'],
        'inherited_unsettled_attempts':proof['cumulative_inherited_unsettled_attempts'],
        'cumulative_cap_credits':'750','previous_cumulative_cap_credits':'250',
        'deadline_utc':recovery.DEADLINE.isoformat(),'sessions_path':SESSIONS,'sessions_sha256':digest(slots),
        'original_run_id':run_ids[0],'original_run_ids':run_ids,'full_planned_slots':1800,
        'carried_issued_slots':len(issued),'carried_final_slots':len(finals),'continuation_slots':len(pending),
        'source_segments':segments,'carried_final_outcomes':bindings,
        'permanently_excluded_issued_slot_ids':issued,'permanently_excluded_final_slot_ids':list(finals),
        'continuation_slot_ids':pending,'failed_producer_descendant_slot_ids':descendants,
        'prior_journal_files':prior,'observed_response_models':recovery.OBSERVED_RESPONSE_MODELS,
        'recovery_proof_path':PROOF,'recovery_proof_sha256':proof_sha256,
        'recovery_auditor_path':recovery.RECOVERY_AUDITOR,'recovery_auditor_sha256':file_sha(recovery.RECOVERY_AUDITOR),
        'orphan_disposition_path':ORPHAN,'orphan_disposition_sha256':sha256(orphan_raw).hexdigest(),
        'orphan_attempt_ids':[q['attempt_id']],
        'actual_prior_requests':len(requests),'observed_prior_responses':len(responses),
        'scope':'Untouched original slots only. Original k remains unclosed; one separately derived host-loss disposition is a pipeline failure, not an observed provider response. No historical request is retried.'}
    recovery.validate_receipt(receipt)
    contents={name:recovery.safe(ROOT,name).read_bytes() for name in prior};contents[ORPHAN]=orphan_raw
    recovery.derive_carry(slots,receipt,contents,continuation_sha256=sha256(json_bytes(receipt)).hexdigest())
    protected={r['path']:r['sha256'] for r in frozen['files']};protected[FREEZE]=recovery.K_FREEZE_SHA
    protected.update({name:b['sha256'] for name,b in proof['input_bindings'].items()})
    protected[PROOF]=proof_sha256;protected[recovery.RECOVERY_AUDITOR]=file_sha(recovery.RECOVERY_AUDITOR)
    protected[ORPHAN]=sha256(orphan_raw).hexdigest();protected[RECEIPT]=sha256(json_bytes(receipt)).hexdigest()
    auth={'schema':'retrace.frontier-v6m-authorization.v1','created_at':datetime.now(timezone.utc).isoformat(),
        'authority':'User authorizes completion of the original1800 slots, preserving all old artifacts, with the new hard cutoff Monday08:00CET; no extra API study or upload. Expanded credit authority retains a substantial buffer from approximately2000 available.',
        'protected_v5_file_count':402,'prior_status':'interrupted_without_closure','prior_stop_reason':'host_session_loss',
        'prior_freeze_path':FREEZE,'prior_freeze_sha256':recovery.K_FREEZE_SHA,
        'baseline_snapshot_path':SNAPSHOT,'baseline_snapshot_sha256':prior[SNAPSHOT],
        'previous_cumulative_cap_credits':'250','cumulative_cap_credits':'750',
        'historical_conservative_carry_credits':receipt['historical_conservative_carry_credits'],
        'inherited_unsettled_attempts':receipt['inherited_unsettled_attempts'],
        'deadline_utc':recovery.DEADLINE.isoformat(),'protected':protected,
        'original_rows_changed':False,'old_k_closure_asserted':False,'orphan_retried':False,
        'frozen_inference':'Original diagnostic gate retained; recovered-complete sensitivity is an explicitly prospective closure amendment, not untouched confirmatory inference.'}
    return auth,receipt,orphan_raw


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--proof-sha256',required=True);a=p.parse_args()
    require(all(not (ROOT/n).exists() for n in (AUTH,RECEIPT,ORPHAN)),'recovery_outputs_must_be_new')
    auth,receipt,orphan=build(proof_sha256=a.proof_sha256)
    for name,h in auth['protected'].items():
        if name not in (RECEIPT,ORPHAN):require(file_sha(name)==h,'source_changed_before_publication: '+name)
    for name,raw in ((ORPHAN,orphan),(RECEIPT,json_bytes(receipt)),(AUTH,json_bytes(auth))):
        with (ROOT/name).open('xb') as f:f.write(raw);f.flush();__import__('os').fsync(f.fileno())
    recovery.verify_continuation(read(SESSIONS),ROOT/RECEIPT,file_sha(RECEIPT))
    print(json.dumps({'paid_calls':0,'actual_prior_requests':receipt['actual_prior_requests'],
        'observed_prior_responses':receipt['observed_prior_responses'],'carried_final_slots':receipt['carried_final_slots'],
        'continuation_slots':receipt['continuation_slots'],'carry_credits':receipt['historical_conservative_carry_credits'],
        'authorization_sha256':file_sha(AUTH),'continuation_sha256':file_sha(RECEIPT),'orphan_disposition_sha256':file_sha(ORPHAN)}))


if __name__=='__main__':main()
