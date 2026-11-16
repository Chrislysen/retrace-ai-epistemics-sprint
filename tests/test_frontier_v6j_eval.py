"""Prospective segmented scorer fixtures; no empirical continuation output."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import unittest
from retrace import frontier_v6j_eval as v
from retrace import frontier_v6i_eval as frozen
from tests.test_frontier_v6i_eval import journals
ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8'))
def raw(value):return (json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n').encode()
def lines(rows):return b''.join(raw(r) for r in rows)

def segment(name,requests,responses,outcomes,summary):
    prefix='results/frontier-v6i/primary/' if name=='original' else 'results/frontier-v6j/continuation/'
    manifest={'run_id':summary['run_id']}
    return {'paths':{key:prefix+file for key,file in [('requests','requests.jsonl'),('responses','responses.jsonl'),('outcomes','slot-outcomes.jsonl'),('summary','summary.json'),('run_manifest','run.json')]},'requests':lines(requests),'responses':lines(responses),'outcomes':lines(outcomes),'summary_bytes':raw(summary),'manifest_bytes':raw(manifest),'summary':summary,'manifest':manifest}

def fixture():
    slots=read('data/frontier-v6i-sessions.json');receipt=read('data/frontier-v6j-continuation.json')
    carried=set(receipt['permanently_excluded_issued_slot_ids']);desc=set(receipt['failed_producer_descendant_slot_ids'])
    fs,rs,qs,sm=journals(slots,{})
    fmap={r['slot_id']:r for r in fs}
    bad=next(sid for sid in carried if 'qwen3.5-397b::' in sid)
    for r in rs:
        r['run_id']='old' if r['slot_id'] in carried else 'new'
        if r['slot_id']==bad:r.update(terminal_valid=False,model_outcome='operational_failure',error='response_model_mismatch',failure_scope='global',response_status=None,output_text='')
        if r['slot_id'] not in carried:r.update(requested_model=r['model'],returned_model=v.ROUTE.get(r['model'],r['model']),model_identity_policy='exact_model_id' if r['model'] not in v.ROUTE else 'prospectively_pinned_observed_route_not_verified_alias')
        fmap[r['slot_id']].update(r)
    def skip(s,reason,runid,blocked=None):return {**{k:s[k] for k in ('slot_id','case_id','model','condition','phase')},'run_id':runid,'issued':False,'terminal_valid':False,'model_outcome':reason,'error':reason,'response_status':None,'output_text':'','blocked_dependencies':blocked or [],'slot_final':True,'attempts_issued':0,'first_attempt_id':None}
    oldfinals=[fmap[s['slot_id']] if s['slot_id'] in carried else skip(s,'not_issued_global_stop','old') for s in slots]
    newfinals=[skip(s,'not_issued_dependency_failed','new',[d for d in s.get('history_from',[]) if d==bad or d in desc]) if s['slot_id'] in desc else fmap[s['slot_id']] for s in slots if s['slot_id'] not in carried]
    oldsummary={'schema':'retrace.adaption-v6i-summary.v1','run_id':'old','status':'stopped','stop_reasons':['response_model_mismatch'],'issued_attempts':6,'retries':0}
    newsummary={'schema':'retrace.adaption-v6j-summary.v1','run_id':'new','status':'completed','stop_reasons':[],'planned':1794,'original_planned':1800,'carried_over_slots':6,'issued_without_outcome_attempt_ids':[],'all_scheduled_outcomes_recorded':True}
    a=segment('original',[q for q in qs if q['slot_id'] in carried],[r for r in rs if r['slot_id'] in carried],oldfinals,oldsummary)
    b=segment('continuation',[q for q in qs if q['slot_id'] not in carried|desc],[r for r in rs if r['slot_id'] not in carried|desc],newfinals,newsummary)
    receipt['original_run_id']='old';receipt['prior_journal_files']={a['paths'][k]:sha256(a[{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(k,k)]).hexdigest() for k in a['paths']}
    receipt['carryover_rows']=[{'slot_id':r['slot_id'],'source_path':a['paths']['outcomes'],'source_line_one_based':n,'row_sha256':v.digest(r),'attempt_id':r['attempt_id'],'model_outcome':r['model_outcome']} for n,r in enumerate(oldfinals,1) if r['issued']]
    failure=next(r for r in rs if r['slot_id']==bad)
    receipt['route_evidence']['original_attempt_id']=failure['attempt_id'];receipt['route_evidence']['original_response_row_sha256']=v.digest(failure)
    audits={}
    for name,s in [('original',a),('continuation',b)]:
        bindings={s['paths'][k]:{'sha256':sha256(s[{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(k,k)]).hexdigest(),'bytes':len(s[{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(k,k)])} for k in s['paths']}
        audits[name]={'passed':True,'final_closed':True,'all_scheduled_outcomes_accounted':True,'schedule_status':'stopped' if name=='original' else 'completed','counts':{'planned':1800 if name=='original' else 1794},'input_bindings':bindings,'cumulative_accounted_credits':'47.653269434','historical_carry_credits':'47.653269434'}
    return slots,receipt,a,b,audits


class CompositeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.value=fixture()
    def fresh(self):return deepcopy(self.value)
    def test_lossless1800_with_original_global_failure_and_two_skips(self):
        s,r,a,b,proof=self.fresh();m=v.assemble_views(s,r,a,b);v.validate_segment_proofs(m,r,proof)
        self.assertEqual(len(m['outcomes']),1800);self.assertEqual(len(m['requests']),1798)
        bad=[x for x in m['responses'] if x.get('failure_scope')=='global'];self.assertEqual(len(bad),1);self.assertFalse(bad[0]['terminal_valid'])
        self.assertEqual(sum(x['model_outcome']=='not_issued_dependency_failed' for x in m['outcomes']),2)
        self.assertFalse(m['source_rows_changed'])
        for key in ('outcomes','responses','requests'):
            for row,p in zip(m[key],m['source_provenance'][key]):self.assertEqual(v.digest(row),p['row_sha256'])
    def test_noncanonical_paths_cannot_bypass_audit(self):
        s,r,a,b,p=self.fresh();b['paths']={k:'other/'+v for k,v in b['paths'].items()}
        with self.assertRaisesRegex(ValueError,'canonical'):v.assemble_views(s,r,a,b)
    def test_original_bytes_and_scope_are_not_reclassified(self):
        s,r,a,b,p=self.fresh();a['responses']=a['responses'].replace(b'"global"',b'"slot"')
        with self.assertRaisesRegex(ValueError,'original journal changed'):v.assemble_views(s,r,a,b)
    def test_missing_or_reissued_original_slot_rejected(self):
        s,r,a,b,p=self.fresh();b['requests']+=a['requests'].splitlines(keepends=True)[0]
        with self.assertRaisesRegex(ValueError,'reissued'):v.assemble_views(s,r,a,b)
        s,r,a,b,p=self.fresh();b['outcomes']=b''.join(b['outcomes'].splitlines(keepends=True)[:-1])
        with self.assertRaisesRegex(ValueError,'1794'):v.assemble_views(s,r,a,b)
    def test_unrelated_audit_and_changed_summary_rejected(self):
        s,r,a,b,p=self.fresh();m=v.assemble_views(s,r,a,b)
        p['continuation']['input_bindings'][b['paths']['summary']]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'different source bytes'):v.validate_segment_proofs(m,r,p)
    def test_continuation_global_failure_cannot_be_waived(self):
        s,r,a,b,p=self.fresh();m=v.assemble_views(s,r,a,b);m['responses'][-1]['failure_scope']='global'
        with self.assertRaisesRegex(ValueError,'global failure'):v.validate_segment_proofs(m,r,p)
    def test_segment_run_id_cannot_hide_global_failure(self):
        s,r,a,b,p=self.fresh();rows=v._rows(b['responses'],b['paths']['responses'])[0];rows[-1]['run_id']='unrelated';b['responses']=lines(rows)
        with self.assertRaisesRegex(ValueError,'run identity'):v.assemble_views(s,r,a,b)
    def test_full_frozen21_scoring_is_isolated_and_amended(self):
        s,r,a,b,p=self.fresh();before=frozen.closed_summary;globals_before=frozen.evaluate.__globals__.copy()
        result=v.evaluate_composite(read('data/frontier-v6h-corpus.json'),read('data/frontier-v6h-dossiers.json'),read('data/frontier-v6i-design.json'),s,r,a,b,p)
        self.assertIs(frozen.closed_summary,before);self.assertEqual(frozen.evaluate.__globals__,globals_before)
        self.assertEqual(result['summary']['status'],'complete_amended_primary');self.assertEqual(result['summary']['primary_holm_family_size'],21)
        self.assertFalse(any(x['status']=='complete_primary' for x in result['summary']['paired_comparisons']))
        self.assertEqual(result['summary']['planned_slots'],1800)
        badrow=next(row for row in v._rows(a['responses'],a['paths']['responses'])[0] if row.get('failure_scope')=='global')
        badsid=badrow['slot_id']
        chosen=[x for x in result['audits'] if x.get('slot_id')==badsid]
        self.assertEqual(len(chosen),2);self.assertEqual({x['view'] for x in chosen},{'first_attempt','eventual'})
        self.assertTrue(all(not x['eligible_completed'] for x in chosen))
        for sid in r['failed_producer_descendant_slot_ids']:
            rows=[x for x in result['audits'] if x.get('slot_id')==sid]
            self.assertEqual(len(rows),2);self.assertTrue(all(not x['eligible_completed'] for x in rows))

if __name__=='__main__':unittest.main()
