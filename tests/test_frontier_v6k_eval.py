"""Invented three-segment journals on frozen slot metadata; no model outputs."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import unittest
from retrace import frontier_v6k_eval as v
from retrace import frontier_v6i_eval as frozen
from retrace.adaption_v6h import build_body,slot_dependencies

ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
def raw(value):return (json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n').encode()
def lines(rows):return b''.join(raw(row) for row in rows)


def source(name,requests,responses,outcomes,summary):
    manifest={'run_id':summary['run_id']}
    return {'paths':v.role_paths(name),'requests':lines(requests),'responses':lines(responses),'outcomes':lines(outcomes),
        'summary_bytes':raw(summary),'manifest_bytes':raw(manifest),'summary':summary,'manifest':manifest}


def fixture():
    slots=read('data/frontier-v6i-sessions.json');receipt=read('data/frontier-v6k-continuation.json')
    oldrefs=receipt['carried_final_outcomes'];carried={r['slot_id']:r for r in oldrefs}
    jbad=next(r['slot_id'] for r in reversed(oldrefs) if r['segment']=='j' and r['attempt_id'] is not None)
    ibad=next(r['slot_id'] for r in oldrefs if r['segment']=='i' and r['model_outcome']!='completed')
    finals={};requests={};responses={};stage={};good={}
    def skip(slot,name,kind,blocked=()):
        return {**{key:slot[key] for key in ('slot_id','case_id','model','condition','phase')},'run_id':'run-'+name,
            'issued':False,'terminal_valid':False,'model_outcome':kind,'error':kind,'response_status':None,'output_text':'',
            'blocked_dependencies':list(blocked),'slot_final':True,'attempt_id':None,'attempts_issued':0,'first_attempt_id':None}
    for slot in slots:
        sid=slot['slot_id'];ref=carried.get(sid);name=ref['segment'] if ref else 'k';stage[sid]=name
        dependencies=slot_dependencies(slot);blocked=[d for d in dependencies if not good[d]]
        if (ref and ref['attempt_id'] is None) or (not ref and blocked):
            assert blocked
            finals[sid]=skip(slot,name,'not_issued_dependency_failed',blocked);good[sid]=False;continue
        assert not blocked,(sid,blocked)
        actual={d:{'actual_input':requests[d]['request']['input'][-1]['content'],'output_text':finals[d]['output_text']} for d in dependencies}
        body=build_body(slot,actual);aid=f'{name}:{sid}:attempt-1'
        requests[sid]={'slot_id':sid,'attempt_id':aid,'attempt_number':1,'first_attempt':True,'request':body,'request_sha256':v.digest(body),
            'dependency_bindings':[{'slot_id':d,'final_attempt_id':finals[d]['attempt_id'],'output_sha256':sha256(finals[d]['output_text'].encode()).hexdigest()} for d in dependencies]}
        outcome=ref['model_outcome'] if ref else 'completed'
        response={**{key:slot[key] for key in ('slot_id','case_id','model','condition','phase')},'run_id':'run-'+name,
            'attempt_id':aid,'attempt_number':1,'first_attempt':True,'issued':True,'http_status':200,'terminal_valid':True,
            'model_outcome':outcome,'response_status':'completed' if outcome=='completed' else 'incomplete','error':None,
            'failure_scope':None,'output_text':'{}','usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20}}
        if outcome=='operational_failure':response.update(terminal_valid=False,error='timeout',failure_scope='slot',output_text='',response_status=None,usage=None)
        if sid in (ibad,jbad):response.update(terminal_valid=False,model_outcome='operational_failure',error='response_model_mismatch' if sid==ibad else 'network_or_transport_failure',failure_scope='global',output_text='',response_status=None,usage=None)
        if name!='i':response.update(requested_model=slot['model'],returned_model=v.ROUTE.get(slot['model'],slot['model']),model_identity_policy='fixture')
        responses[sid]=response;finals[sid]={**response,'slot_final':True,'attempts_issued':1,'first_attempt_id':aid};good[sid]=frozen.h.completed(finals[sid])
    segments={};audits={};newrefs=[]
    for name in v.SEGMENTS:
        included=[s for s in slots if name=='i' or (name=='j' and stage[s['slot_id']]!='i') or (name=='k' and stage[s['slot_id']]=='k')]
        outcomes=[finals[s['slot_id']] if stage[s['slot_id']]==name else skip(s,name,'not_issued_global_stop') for s in included]
        req=[requests[s['slot_id']] for s in slots if stage[s['slot_id']]==name and s['slot_id'] in requests]
        res=[responses[s['slot_id']] for s in slots if stage[s['slot_id']]==name and s['slot_id'] in responses]
        summary={'schema':f'retrace.adaption-v6{name}-summary.v1','run_id':'run-'+name,'status':'completed' if name=='k' else 'stopped',
            'stop_reasons':[] if name=='k' else ['response_model_mismatch' if name=='i' else 'network_or_transport_failure'],
            'planned':v.PLANNED[name],'original_planned':1800,'carried_over_slots':0 if name=='i' else 6 if name=='j' else 224,
            'issued_attempts':len(req),'retries':0,'issued_without_outcome_attempt_ids':[],'all_scheduled_outcomes_recorded':True}
        segments[name]=source(name,req,res,outcomes,summary)
        bindings={path:{'sha256':sha256(segments[name][{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(role,role)]).hexdigest(),
            'bytes':len(segments[name][{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(role,role)])} for role,path in segments[name]['paths'].items()}
        audits[name]={'passed':True,'final_closed':True,'all_scheduled_outcomes_accounted':True,'schedule_status':summary['status'],
            'counts':{'planned':v.PLANNED[name]},'input_bindings':bindings,'cumulative_accounted_credits':v.CARRY_I if name=='i' else v.CARRY_J,
            'historical_carry_credits':v.CARRY_I if name=='j' else v.CARRY_J}
        if name!='k':
            for n,row in enumerate(outcomes,1):
                if v.is_definitive(row):newrefs.append({'segment':name,'slot_id':row['slot_id'],'source_path':segments[name]['paths']['outcomes'],
                    'source_line_one_based':n,'row_sha256':v.digest(row),'attempt_id':row.get('attempt_id'),'model_outcome':row['model_outcome']})
    receipt['carried_final_outcomes']=newrefs;receipt['original_run_id']='run-i';receipt['original_run_ids']=['run-i','run-j']
    receipt['permanently_excluded_final_slot_ids']=[r['slot_id'] for r in newrefs]
    receipt['permanently_excluded_issued_slot_ids']=[r['slot_id'] for r in newrefs if r['attempt_id']]
    receipt['prior_journal_files']={}
    for declaration in receipt['source_segments']:
        name=declaration['segment'];declaration['run_id']='run-'+name
        for role,path in segments[name]['paths'].items():
            declaration['paths'][role]=path;declaration['sha256'][role]=audits[name]['input_bindings'][path]['sha256'];receipt['prior_journal_files'][path]=declaration['sha256'][role]
    return slots,receipt,segments,audits


class ThreeSegmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.value=fixture()
    def fresh(self):return deepcopy(self.value)
    def test_lossless_three_segments_retains_all_old_definitive_rows(self):
        slots,receipt,segments,audits=self.fresh();merged=v.assemble_views(slots,receipt,segments);v.validate_segment_proofs(merged,receipt,audits)
        self.assertEqual(len(merged['outcomes']),1800);self.assertEqual(sum(p['segment']=='j' for p in merged['source_provenance']['outcomes']),218)
        self.assertEqual(sum(r['model_outcome']=='not_issued_dependency_failed' and p['segment']=='j' for r,p in zip(merged['outcomes'],merged['source_provenance']['outcomes'])),11)
        self.assertEqual(sum(r.get('failure_scope')=='global' for r in merged['responses']),2)
        for role in ('requests','responses','outcomes'):
            for row,pointer in zip(merged[role],merged['source_provenance'][role]):self.assertEqual(v.digest(row),pointer['row_sha256'])
    def test_altered_old_failure_or_skip_cannot_be_replaced(self):
        s,r,segs,p=self.fresh();segs['j']['responses']=segs['j']['responses'].replace(b'"global"',b'"slot"')
        with self.assertRaisesRegex(ValueError,'historical role'):v.assemble_views(s,r,segs)
        s,r,segs,p=self.fresh();oldskip=next(ref for ref in r['carried_final_outcomes'] if ref['attempt_id'] is None)
        r['carried_final_outcomes'].remove(oldskip)
        with self.assertRaisesRegex(ValueError,'line pointers'):v.assemble_views(s,r,segs)
    def test_reissue_any_definitive_old_slot_or_noncanonical_path_rejected(self):
        s,r,segs,p=self.fresh();segs['k']['requests']+=segs['i']['requests'].splitlines(keepends=True)[0]
        with self.assertRaisesRegex(ValueError,'reissued'):v.assemble_views(s,r,segs)
        s,r,segs,p=self.fresh();segs['k']['paths']['requests']='other/requests.jsonl'
        with self.assertRaisesRegex(ValueError,'canonical'):v.assemble_views(s,r,segs)
    def test_missing_k_outcome_or_wrong_segment_run_identity_rejected(self):
        s,r,segs,p=self.fresh();segs['k']['outcomes']=b''.join(segs['k']['outcomes'].splitlines(keepends=True)[:-1])
        with self.assertRaisesRegex(ValueError,'denominator'):v.assemble_views(s,r,segs)
        s,r,segs,p=self.fresh();segs['k']['responses']=segs['k']['responses'].replace(b'"run-k"',b'"other"',1)
        with self.assertRaisesRegex(ValueError,'run identity'):v.assemble_views(s,r,segs)
    def test_unrelated_proof_global_stop_or_changed_carry_rejected(self):
        for kind in ('proof','global','carry','stop'):
            s,r,segs,p=self.fresh();merged=v.assemble_views(s,r,segs)
            if kind=='proof':p['j']['input_bindings'][v.role_paths('j')['summary']]['sha256']='0'*64
            if kind=='global':next(row for row in merged['responses'] if row['run_id']=='run-k')['failure_scope']='global'
            if kind=='carry':p['k']['historical_carry_credits']='0'
            if kind=='stop':p['k']['schedule_status']='stopped'
            with self.assertRaises(ValueError):v.validate_segment_proofs(merged,r,p)
    def test_full_frozen21_scoring_no_module_mutation_and_old_failures_retained(self):
        s,r,segs,p=self.fresh();before=frozen.evaluate.__globals__.copy()
        result=v.evaluate_composite(read('data/frontier-v6h-corpus.json'),read('data/frontier-v6h-dossiers.json'),read('data/frontier-v6i-design.json'),s,r,segs,p)
        self.assertEqual(frozen.evaluate.__globals__,before);self.assertEqual(result['summary']['status'],'complete_amended_primary')
        self.assertEqual(result['summary']['primary_holm_family_size'],21);self.assertEqual(result['summary']['planned_slots'],1800)
        self.assertFalse(any(row['status']=='complete_primary' for row in result['summary']['paired_comparisons']))
        for name in ('i','j'):
            bad=next(row for row in v._rows(segs[name]['responses'],segs[name]['paths']['responses'])[0] if row.get('failure_scope')=='global')
            rows=[row for row in result['audits'] if row.get('slot_id')==bad['slot_id']]
            self.assertEqual(len(rows),2);self.assertTrue(all(not row['eligible_completed'] for row in rows))

if __name__=='__main__':unittest.main()
