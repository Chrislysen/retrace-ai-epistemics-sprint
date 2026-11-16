"""Invented crash-prefix tests; no real run or provider outputs are opened."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from retrace import recovery_v6m as v
from tests.test_frontier_v6i_eval import small_fixture,journals
from scripts import audit_frontier_v6m_prefix as prefix


def encode(x):return (json.dumps(x,ensure_ascii=False,allow_nan=False)+'\n').encode()
def jsonl(items):return b''.join(encode(x) for x in items)


def fixture():
    data=small_fixture([('strict_source_ir','extract','i'),('adversarial_refuter','counter_read','j'),
        ('commitment','initial','k'),('commitment','fresh_withdrawn','orphan'),('commitment','fresh_restored','pending')])
    slots=data[3];finals,responses,requests,_=journals(slots,data[4]);contents={};segments=[];bindings=[]
    for n,name in enumerate(('i','j','k')):
        rid='invented-'+name;prefix='invented/'+name+'/'
        paths={key:prefix+file for key,file in [('run_manifest','run.json'),('requests','requests.jsonl'),
            ('responses','responses.jsonl'),('outcomes','slot-outcomes.jsonl')]}
        if name!='k':paths['summary']=prefix+'summary.json'
        run={'run_id':rid,'slots':slots,'sessions_sha256':v.digest(slots)};contents[paths['run_manifest']]=encode(run)
        r=deepcopy(responses[n]);r['run_id']=rid;f=deepcopy(finals[n]);f.update(r)
        out=[f]
        if name!='k':
            for s in slots[n+1:]:
                out.append({**{key:s[key] for key in ('slot_id','case_id','model','condition','phase')},
                    'run_id':rid,'slot_final':True,'issued':False,'terminal_valid':False,'attempt_id':None,
                    'attempts_issued':0,'output_text':'','model_outcome':'not_issued_global_stop'})
            contents[paths['summary']]=encode({'run_id':rid,'status':'stopped',
                'stop_reasons':['response_model_mismatch' if name=='i' else 'network_or_transport_failure']})
        qs=[requests[n]]+([requests[3]] if name=='k' else [])
        contents[paths['requests']]=jsonl(qs);contents[paths['responses']]=jsonl([r]);contents[paths['outcomes']]=jsonl(out)
        segments.append({'segment':name,'run_id':rid,'paths':paths,'definitive_final_slots':1})
        bindings.append({'segment':name,'slot_id':f['slot_id'],'source_path':paths['outcomes'],
            'source_line_one_based':1,'row_sha256':v.digest(f),'attempt_id':f['attempt_id'],'model_outcome':f['model_outcome']})
    receipt={'full_planned_slots':5,'sessions_sha256':v.digest(slots),'source_segments':segments,
        'recovery_id':'invented-recovery','recovery_proof_path':'invented/proof.json','recovery_proof_sha256':'1'*64,
        'orphan_disposition_path':'invented/orphan.jsonl','orphan_attempt_ids':[requests[3]['attempt_id']],
        'carried_final_slots':4,'carried_issued_slots':4,'continuation_slots':1,
        'permanently_excluded_issued_slot_ids':[s['slot_id'] for s in slots[:4]],
        'permanently_excluded_final_slot_ids':[s['slot_id'] for s in slots[:4]],
        'continuation_slot_ids':[slots[4]['slot_id']],'failed_producer_descendant_slot_ids':[],
        'original_run_id':'invented-i','original_run_ids':['invented-'+x for x in ('i','j','k')],
        'recovery_observed_at_utc':'2026-11-15T14:40:00+00:00'}
    overlay=v.orphan_disposition(slots[3],requests[3],origin_run_id='invented-k',recovery_id=receipt['recovery_id'],
        proof_path=receipt['recovery_proof_path'],proof_sha256=receipt['recovery_proof_sha256'])
    contents[receipt['orphan_disposition_path']]=jsonl([overlay])
    bindings.append({'segment':'recovery','slot_id':overlay['slot_id'],'source_path':receipt['orphan_disposition_path'],
        'source_line_one_based':1,'row_sha256':v.digest(overlay),'attempt_id':None,'model_outcome':'issued_without_response'})
    receipt['carried_final_outcomes']=bindings
    return slots,receipt,contents


class RecoveryTests(unittest.TestCase):
    def derive(self,slots,receipt,contents):return v.derive_carry(slots,receipt,contents,continuation_sha256='a'*64)

    def test_actual_completed_only_and_orphan_permanently_excluded(self):
        slots,receipt,contents=fixture();original=deepcopy(contents);got=self.derive(slots,receipt,contents)
        self.assertEqual(len(got['completed']),3);self.assertEqual(got['actual_issued_attempts'],4)
        self.assertEqual(got['provider_response_records'],3);self.assertEqual(len(got['finals']),4)
        self.assertNotIn(slots[3]['slot_id'],got['completed']);self.assertNotIn(slots[3]['slot_id'],got['continuation_slot_ids'])
        self.assertEqual(got['earliest_next_admission_utc'],'2026-11-15T14:40:04+00:00')
        self.assertEqual(contents,original)

    def test_fabricated_k_summary_rejects(self):
        s,r,c=fixture();r['source_segments'][2]['paths']['summary']='invented/fake.json'
        with self.assertRaisesRegex(ValueError,'fabricated_k_closure'):self.derive(s,r,c)

    def test_orphan_cannot_reenter_pending_even_with_changed_counts(self):
        s,r,c=fixture();r['continuation_slot_ids'].insert(0,s[3]['slot_id']);r['continuation_slots']=2
        with self.assertRaisesRegex(ValueError,'carry_complement'):self.derive(s,r,c)

    def test_orphan_cannot_be_marked_success_or_have_partial_text(self):
        for change in ({'output_text':'invented completion'},{'usage':{'input_tokens':1}},
                       {'model_outcome':'completed'},{'actual_request_issued':False}):
            s,r,c=fixture();row=v.rows(c[r['orphan_disposition_path']])[0];row.update(change)
            c[r['orphan_disposition_path']]=jsonl([row])
            with self.assertRaisesRegex(ValueError,'orphan_disposition_changed'):self.derive(s,r,c)

    def test_omitted_observed_k_final_rejects(self):
        s,r,c=fixture();c[r['source_segments'][2]['paths']['outcomes']]=b''
        with self.assertRaisesRegex(ValueError,'prior_definitive_count'):self.derive(s,r,c)

    def test_orphan_request_body_tamper_rehashed_still_rejects(self):
        s,r,c=fixture();path=r['source_segments'][2]['paths']['requests'];q=v.rows(c[path])
        q[-1]['request']['instructions']='repair';q[-1]['request_sha256']=v.digest(q[-1]['request']);c[path]=jsonl(q)
        # Update overlay hash too: frozen request reconstruction must still reject.
        overlay=v.orphan_disposition(s[3],q[-1],origin_run_id='invented-k',recovery_id=r['recovery_id'],
            proof_path=r['recovery_proof_path'],proof_sha256=r['recovery_proof_sha256'])
        c[r['orphan_disposition_path']]=jsonl([overlay])
        with self.assertRaisesRegex(ValueError,'frozen request'):self.derive(s,r,c)

    def test_second_orphan_is_not_silently_adjudicated(self):
        s,r,c=fixture();path=r['source_segments'][2]['paths']['responses'];c[path]=b''
        with self.assertRaisesRegex(ValueError,'exact_orphan'):self.derive(s,r,c)

    def test_duplicate_json_and_partial_lines_fail_closed(self):
        with self.assertRaises(ValueError):v.rows(b'{"x":1,"x":2}\n')
        with self.assertRaises(ValueError):v.rows(b'{"x":1}')

    def test_path_escape_and_hash_change_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'one').write_bytes(b'x')
            for path in ('../one','C:/one','a\\b'):
                with self.assertRaises(ValueError):v.safe(root,path)
            with self.assertRaisesRegex(ValueError,'source_changed'):v.checked(root,'one','0'*64)
            self.assertEqual(v.checked(root,'one',sha256(b'x').hexdigest()),b'x')

    def proof_fixture(self,root):
        def write(name,raw):
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            return sha256(raw).hexdigest()
        ledger=b'{"invented_open_ledger":true}\n';ledger_sha=write(v.BASELINE_LEDGER,ledger)
        source='invented/requests.jsonl';source_raw=b'{"request_only":true}\n';source_sha=write(source,source_raw)
        auditor_sha=write(v.RECOVERY_AUDITOR,b'# invented auditor\n')
        overlay='invented/orphan.jsonl';overlay_sha=write(overlay,b'{"derived":true}\n')
        proof={'passed':True,'final_closed':False,'schedule_status':'interrupted_without_closure',
            'cumulative_accounted_credits':'218','cumulative_inherited_unsettled_attempts':268,
            'host_observation':{'observed_at_utc':'2026-11-15T15:00:00Z'},'orphan':{'attempt_id':'actual-orphan'},
            'input_bindings':{source:{'sha256':source_sha,'bytes':len(source_raw)},
                v.BASELINE_LEDGER:{'sha256':ledger_sha,'bytes':len(ledger)}}}
        proofpath='invented/proof.json';proof_sha=write(proofpath,encode(proof))
        receipt={'recovery_proof_path':proofpath,'recovery_proof_sha256':proof_sha,
            'recovery_auditor_path':v.RECOVERY_AUDITOR,'recovery_auditor_sha256':auditor_sha,
            'prior_freeze_sha256':v.K_FREEZE_SHA,'historical_conservative_carry_credits':'218',
            'inherited_unsettled_attempts':268,'recovery_observed_at_utc':'2026-11-15T15:00:00Z',
            'orphan_attempt_ids':['actual-orphan'],'prior_journal_files':{source:source_sha},
            'orphan_disposition_path':overlay,'orphan_disposition_sha256':overlay_sha,
            'baseline_snapshot_path':v.BASELINE_LEDGER,'baseline_snapshot_sha256':ledger_sha}
        return receipt,proof

    def test_common_loader_replays_pinned_proof_and_current_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);receipt,proof=self.proof_fixture(root)
            with patch.object(prefix,'audit',return_value=deepcopy(proof)):
                got,contents=v._load_proof(receipt,root=root)
            self.assertEqual(got,proof);self.assertIn(v.BASELINE_LEDGER,contents)
            (root/'invented/requests.jsonl').write_bytes(b'changed\n')
            with patch.object(prefix,'audit',return_value=deepcopy(proof)):
                with self.assertRaisesRegex(ValueError,'source_changed'):v._load_proof(receipt,root=root)

    def test_self_asserted_proof_without_identical_replay_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);receipt,proof=self.proof_fixture(root);proof['passed']=False
            with patch.object(prefix,'audit',return_value=proof):
                with self.assertRaisesRegex(ValueError,'does_not_reproduce'):v._load_proof(receipt,root=root)

    def test_receipt_cannot_change_proven_carry_or_observation_or_orphan(self):
        changes=({'historical_conservative_carry_credits':'217'},
            {'recovery_observed_at_utc':'2026-11-15T14:00:00Z'},{'orphan_attempt_ids':['invented-alternative']})
        for change in changes:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);receipt,proof=self.proof_fixture(root);receipt.update(change)
                with patch.object(prefix,'audit',return_value=proof):
                    with self.assertRaises(ValueError):v._load_proof(receipt,root=root)


if __name__=='__main__':unittest.main()
