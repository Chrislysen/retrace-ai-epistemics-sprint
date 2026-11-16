"""Invented two-prefix recovery fixtures; no empirical outputs or provider calls."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from retrace import recovery_v6n as v
from tests.test_frontier_v6i_eval import small_fixture,journals
from scripts import audit_frontier_v6n_prefix as prefix

CONDITIONS=[('strict_source_ir','extract','i'),('adversarial_refuter','counter_read','j'),
    ('commitment','hist_init','k'),('commitment','fresh_withdrawn','k_orphan'),
    ('commitment','evt_no_commit','m'),('commitment','fresh_restored','m_orphan'),
    ('commitment','hist_restored','pending')]
def encode(x):return (json.dumps(x,ensure_ascii=False,allow_nan=False)+'\n').encode()
def jsonl(items):return b''.join(encode(x) for x in items)

def fixture():
    data=small_fixture(CONDITIONS);slots=data[3]
    finals,responses,requests,_=journals(slots,data[4]);contents={};segments=[];bindings=[]
    for name,n in [('i',0),('j',1),('k',2),('m',4)]:
        rid='invented-'+name;base='invented/'+name+'/'
        paths={key:base+file for key,file in [('run_manifest','run.json'),('requests','requests.jsonl'),
            ('responses','responses.jsonl'),('outcomes','slot-outcomes.jsonl')]}
        if name in ('i','j'):paths['summary']=base+'summary.json'
        run={'run_id':rid,'slots':slots,'sessions_sha256':v.digest(slots)};contents[paths['run_manifest']]=encode(run)
        r=deepcopy(responses[n]);r['run_id']=rid;f=deepcopy(finals[n]);f.update(r);out=[f]
        if name in ('i','j'):
            for s in slots[n+1:]:out.append({**{k:s[k] for k in ('slot_id','case_id','model','condition','phase')},
                'run_id':rid,'slot_final':True,'issued':False,'terminal_valid':False,'attempt_id':None,
                'attempts_issued':0,'output_text':'','model_outcome':'not_issued_global_stop'})
            contents[paths['summary']]=encode({'run_id':rid,'status':'stopped',
                'stop_reasons':['response_model_mismatch' if name=='i' else 'network_or_transport_failure']})
        qs=[requests[n]]+([requests[n+1]] if name in ('k','m') else [])
        contents[paths['requests']]=jsonl(qs);contents[paths['responses']]=jsonl([r]);contents[paths['outcomes']]=jsonl(out)
        segments.append({'segment':name,'run_id':rid,'paths':paths,'definitive_final_slots':1})
        bindings.append({'segment':name,'slot_id':f['slot_id'],'source_path':paths['outcomes'],
            'source_line_one_based':1,'row_sha256':v.digest(f),'attempt_id':f['attempt_id'],'model_outcome':f['model_outcome']})
    specs=[]
    for name,n,path,proof,h,builder in [('k',3,v.OLD_OVERLAY,v.OLD_PROOF,'1'*64,v.historical_orphan_disposition),
                                      ('m',5,v.NEW_OVERLAY,v.NEW_PROOF,'2'*64,v.orphan_disposition)]:
        rid='invented-recovery-'+name
        overlay=builder(slots[n],requests[n],origin_run_id='invented-'+name,recovery_id=rid,proof_path=proof,proof_sha256=h)
        raw=jsonl([overlay]);contents[path]=raw
        specs.append({'origin_segment':name,'path':path,'sha256':sha256(raw).hexdigest(),
            'proof_path':proof,'proof_sha256':h,'recovery_id':rid})
        bindings.append({'segment':'recovery' if name=='k' else 'recovery_m','slot_id':slots[n]['slot_id'],
            'source_path':path,'source_line_one_based':1,'row_sha256':v.digest(overlay),'attempt_id':None,'model_outcome':'issued_without_response'})
    order=[0,1,2,4,3,5]
    receipt={'full_planned_slots':7,'sessions_sha256':v.digest(slots),'source_segments':segments,
        'recovery_id':'invented-recovery-m','recovery_proof_path':v.NEW_PROOF,'recovery_proof_sha256':'2'*64,
        'orphan_dispositions':specs,'orphan_attempt_ids':[requests[n]['attempt_id'] for n in (3,5)],
        'carried_final_slots':6,'carried_issued_slots':6,'continuation_slots':1,
        'permanently_excluded_issued_slot_ids':[s['slot_id'] for s in slots[:6]],
        'permanently_excluded_final_slot_ids':[slots[n]['slot_id'] for n in order],
        'continuation_slot_ids':[slots[6]['slot_id']],'failed_producer_descendant_slot_ids':[],
        'original_run_id':'invented-i','original_run_ids':['invented-'+x for x in ('i','j','k','m')],
        'recovery_observed_at_utc':'2026-11-15T16:15:31.8614811Z','carried_final_outcomes':bindings}
    return slots,receipt,contents

class RecoveryTests(unittest.TestCase):
    def derive(self,s,r,c):return v.derive_carry(s,r,c,continuation_sha256='a'*64)
    def test_two_orphans_never_become_responses_or_history(self):
        s,r,c=fixture();before=deepcopy(c);got=self.derive(s,r,c)
        self.assertEqual(len(got['completed']),4);self.assertEqual(got['actual_issued_attempts'],6)
        self.assertEqual(got['provider_response_records'],4);self.assertEqual(len(got['finals']),6)
        self.assertEqual(got['continuation_slot_ids'],[s[6]['slot_id']]);self.assertEqual(c,before)
        for n in (3,5):self.assertNotIn(s[n]['slot_id'],got['completed'])
        self.assertEqual(got['earliest_next_admission_utc'],'2026-11-15T16:15:35.861481+00:00')
    def test_either_fabricated_prefix_closure_rejects(self):
        for n in (2,3):
            s,r,c=fixture();r['source_segments'][n]['paths']['summary']='invented/fake.json'
            with self.assertRaisesRegex(ValueError,'fabricated_prefix_closure'):self.derive(s,r,c)
    def test_old_overlay_byte_identity_even_if_semantically_same(self):
        s,r,c=fixture();c[v.OLD_OVERLAY]=b' '+c[v.OLD_OVERLAY]
        with self.assertRaisesRegex(ValueError,'overlay_bytes_changed'):self.derive(s,r,c)
    def test_both_overlays_reject_invented_completion_after_rehash(self):
        for spec_index in (0,1):
            s,r,c=fixture();spec=r['orphan_dispositions'][spec_index];row=v.rows(c[spec['path']])[0]
            row['output_text']='invented';c[spec['path']]=jsonl([row]);spec['sha256']=sha256(c[spec['path']]).hexdigest()
            with self.assertRaisesRegex(ValueError,'disposition_changed'):self.derive(s,r,c)
    def test_swapped_orphan_origin_or_third_orphan_rejects(self):
        s,r,c=fixture();r['orphan_attempt_ids'].reverse()
        with self.assertRaisesRegex(ValueError,'exact_orphans'):self.derive(s,r,c)
        s,r,c=fixture();c[r['source_segments'][3]['paths']['responses']]=b''
        with self.assertRaisesRegex(ValueError,'exact_orphans'):self.derive(s,r,c)
    def test_orphan_cannot_reenter_pending(self):
        s,r,c=fixture();r['continuation_slot_ids'].insert(0,s[5]['slot_id']);r['continuation_slots']=2
        with self.assertRaisesRegex(ValueError,'carry_complement'):self.derive(s,r,c)
    def test_omitted_observed_m_final_rejects(self):
        s,r,c=fixture();c[r['source_segments'][3]['paths']['outcomes']]=b''
        with self.assertRaisesRegex(ValueError,'definitive_count'):self.derive(s,r,c)
    def test_orphan_request_repair_rehashed_still_rejects(self):
        s,r,c=fixture();path=r['source_segments'][3]['paths']['requests'];qs=v.rows(c[path]);q=qs[-1]
        q['request']['instructions']='repair';q['request_sha256']=v.digest(q['request']);c[path]=jsonl(qs)
        spec=r['orphan_dispositions'][1];row=v.orphan_disposition(s[5],q,origin_run_id='invented-m',
            recovery_id=spec['recovery_id'],proof_path=spec['proof_path'],proof_sha256=spec['proof_sha256'])
        c[spec['path']]=jsonl([row]);spec['sha256']=sha256(c[spec['path']]).hexdigest()
        with self.assertRaisesRegex(ValueError,'frozen request'):self.derive(s,r,c)
    def test_strict_json_and_paths(self):
        for raw in (b'{"x":1,"x":2}\n',b'{"x":1}'):
            with self.assertRaises(ValueError):v.rows(raw)
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('../x','C:/x','a\\b'):
                with self.assertRaises(ValueError):v.safe(tmp,name)

    def full_receipt(self):
        _,r,_=fixture();r.update(schema='retrace.frontier-v6n-continuation.v1',full_planned_slots=1800,
            sessions_path='data/frontier-v6i-sessions.json',cumulative_cap_credits='750',previous_cumulative_cap_credits='750',
            observed_response_models=v.OBSERVED_RESPONSE_MODELS,prior_freeze_path='data/frontier-v6m-freeze.json',
            prior_freeze_sha256=v.M_FREEZE_SHA,deadline_utc=v.DEADLINE.isoformat(),baseline_snapshot_path=v.BASELINE_LEDGER,
            recovery_auditor_path=v.RECOVERY_AUDITOR,carried_final_slots=1271,carried_issued_slots=1192,
            continuation_slots=529,inherited_unsettled_attempts=269,historical_conservative_carry_credits='300')
        return r
    def test_new_cap_accepts_prior_above250_but_never_above750(self):
        r=self.full_receipt();self.assertIs(v.validate_receipt(r),r)
        for change in ({'historical_conservative_carry_credits':'750.000000001'},
                       {'previous_cumulative_cap_credits':'250'},{'cumulative_cap_credits':'1000'}):
            bad=deepcopy(r);bad.update(change)
            with self.assertRaises(ValueError):v.validate_receipt(bad)
    def test_admission_deadline_and_two_overlay_inventory_are_explicit(self):
        r=self.full_receipt()
        self.assertEqual(v.DEADLINE.isoformat(),'2026-11-16T06:56:00+00:00')
        for change in ({'deadline_utc':'2026-11-16T07:00:00+00:00'},
                       {'orphan_attempt_ids':r['orphan_attempt_ids']+[r['orphan_attempt_ids'][0]]},
                       {'orphan_dispositions':r['orphan_dispositions'][:1]}):
            bad=deepcopy(r);bad.update(change)
            with self.assertRaises(ValueError):v.validate_receipt(bad)

    def proof_fixture(self,root):
        def write(name,raw):
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);return sha256(raw).hexdigest()
        prior={'passed':True,'final_closed':False,'schedule_status':'interrupted_without_closure','orphan':{'attempt_id':'old-orphan'}}
        prior_sha=write(v.OLD_PROOF,encode(prior));ledger=b'invented full retained ledger\n';ledger_sha=write(v.BASELINE_LEDGER,ledger)
        oldraw=b'{"old_overlay":"unchanged"}\n';oldsha=write(v.OLD_OVERLAY,oldraw)
        newsha=write(v.NEW_OVERLAY,b'{"new_overlay":"derived"}\n');audsha=write(v.RECOVERY_AUDITOR,b'# invented\n')
        source='invented/requests.jsonl';raw=b'{"request_only":true}\n';ssha=write(source,raw)
        proof={'passed':True,'final_closed':False,'schedule_status':'interrupted_without_closure',
            'cumulative_accounted_credits':'300','cumulative_inherited_unsettled_attempts':270,
            'host_observation':{'observed_at_utc':'2026-11-15T16:15:00Z'},'orphan':{'attempt_id':'new-orphan'},
            'recovery_prefix_proof':prior,'input_bindings':{source:{'sha256':ssha,'bytes':len(raw)},
                v.BASELINE_LEDGER:{'sha256':ledger_sha,'bytes':len(ledger)},v.OLD_OVERLAY:{'sha256':oldsha,'bytes':len(oldraw)}}}
        psha=write(v.NEW_PROOF,encode(proof))
        receipt={'recovery_proof_path':v.NEW_PROOF,'recovery_proof_sha256':psha,'recovery_auditor_path':v.RECOVERY_AUDITOR,
            'recovery_auditor_sha256':audsha,'prior_freeze_sha256':v.M_FREEZE_SHA,
            'historical_conservative_carry_credits':'300','inherited_unsettled_attempts':270,
            'recovery_observed_at_utc':'2026-11-15T16:15:00Z','orphan_attempt_ids':['old-orphan','new-orphan'],
            'prior_journal_files':{source:ssha},'baseline_snapshot_path':v.BASELINE_LEDGER,'baseline_snapshot_sha256':ledger_sha,
            'orphan_dispositions':[{'origin_segment':'k','path':v.OLD_OVERLAY,'sha256':oldsha,'proof_path':v.OLD_PROOF,'proof_sha256':prior_sha},
                {'origin_segment':'m','path':v.NEW_OVERLAY,'sha256':newsha,'proof_path':v.NEW_PROOF,'proof_sha256':psha}]}
        return receipt,proof
    def test_loader_replays_both_prefixes_and_retains_cost_above250(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);r,p=self.proof_fixture(root)
            with patch.object(prefix,'audit',return_value=deepcopy(p)):got,contents=v._load_proof(r,root=root)
            self.assertEqual(got,p);self.assertEqual(got['cumulative_accounted_credits'],'300')
            self.assertIn(v.OLD_OVERLAY,contents);self.assertIn(v.NEW_OVERLAY,contents)
    def test_false_proof_or_reduced_carry_or_old_overlay_unbound_rejects(self):
        for change in ('replay','carry','binding','oldproof'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);r,p=self.proof_fixture(root)
                if change=='replay':p['passed']=False
                elif change=='carry':r['historical_conservative_carry_credits']='299'
                elif change=='binding':p['input_bindings'].pop(v.OLD_OVERLAY)
                else:(root/v.OLD_PROOF).write_bytes(encode({'invented':True}))
                with patch.object(prefix,'audit',return_value=p):
                    with self.assertRaises(ValueError):v._load_proof(r,root=root)

if __name__=='__main__':unittest.main()
