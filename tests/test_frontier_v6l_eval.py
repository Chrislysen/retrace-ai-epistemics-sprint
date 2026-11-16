"""Invented four-segment journals on frozen schedule metadata; no live answers."""
from copy import deepcopy
from hashlib import sha256
import json
import unittest

from retrace import frontier_v6l_eval as v
from retrace import frontier_v6i_eval as frozen
from tests.test_frontier_v6k_eval import fixture as prior_fixture, read, raw, lines


def source(name, requests, responses, outcomes, summary):
    manifest = {'run_id':summary['run_id']}
    return {'paths':v.role_paths(name),'requests':lines(requests),'responses':lines(responses),'outcomes':lines(outcomes),
            'summary_bytes':raw(summary),'manifest_bytes':raw(manifest),'summary':summary,'manifest':manifest}


def stop_row(row, name):
    return {**{key:row[key] for key in ('slot_id','case_id','model','condition','phase')},'run_id':'run-'+name,
            'issued':False,'terminal_valid':False,'model_outcome':'not_issued_global_stop','error':'not_issued_global_stop',
            'response_status':None,'output_text':'','slot_final':True,'attempt_id':None,'attempts_issued':0,'first_attempt_id':None}


def rebind(slots, receipt, segments, audits):
    """Update invented authentication metadata after an intentional fixture edit."""
    refs = []; excluded = set(); receipt['prior_journal_files'] = {}
    declarations = []
    for name in v.SEGMENTS:
        s = segments[name]
        bindings = {path:{'sha256':sha256(s[{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(role,role)]).hexdigest(),
                          'bytes':len(s[{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(role,role)])}
                    for role,path in s['paths'].items()}
        audits[name]['input_bindings'] = bindings
        if name == 'l': continue
        rows,pointers = v._rows(s['outcomes'],s['paths']['outcomes'])
        selected = [r for r in rows if v.is_definitive(r)]
        issued = {r['slot_id'] for r in selected if r['issued']}; excluded |= issued
        declarations.append({'segment':name,'run_id':'run-'+name,'paths':s['paths'],
            'sha256':{role:bindings[path]['sha256'] for role,path in s['paths'].items()},
            'definitive_final_slots':len(selected),'issued_slots':len(issued)})
        receipt['prior_journal_files'].update({path:b['sha256'] for path,b in bindings.items()})
        for row,pointer in zip(rows,pointers):
            if v.is_definitive(row):
                refs.append({'segment':name,'slot_id':row['slot_id'],**{key:pointer[key] for key in ('source_path','source_line_one_based','row_sha256')},
                             'attempt_id':row.get('attempt_id'),'model_outcome':row['model_outcome']})
    receipt.update(source_segments=declarations,carried_final_outcomes=refs,
        permanently_excluded_final_slot_ids=[r['slot_id'] for r in refs],
        permanently_excluded_issued_slot_ids=[r['slot_id'] for r in refs if r['attempt_id']],
        carried_final_slots=len(refs),carried_issued_slots=len(excluded),continuation_slots=1800-len(refs))
    carried = {r['slot_id'] for r in refs}
    receipt['continuation_slot_ids'] = [s['slot_id'] for s in slots if s['slot_id'] not in carried]
    audits['l']['prior_segment_audits'] = {n:deepcopy(audits[n]) for n in v.HISTORICAL}


def fixture(k_final_count=17, *, diagnostic=False):
    slots,receipt,segments,audits = prior_fixture()
    original = segments['k']; old_rows = [json.loads(x) for x in original['outcomes'].splitlines()]
    kept = {r['slot_id'] for r in old_rows[:k_final_count]}
    moved = {r['slot_id'] for r in old_rows[k_final_count:]}
    requests = [json.loads(x) for x in original['requests'].splitlines()]
    responses = [json.loads(x) for x in original['responses'].splitlines()]
    aid_map = {r['attempt_id']:'l:'+r['attempt_id'] for r in responses if r['slot_id'] in moved}
    def relocated(row, response=False):
        row = deepcopy(row)
        for key in ('attempt_id','first_attempt_id'):
            if row.get(key) in aid_map:row[key] = aid_map[row[key]]
        for binding in row.get('dependency_bindings',[]):
            if binding['final_attempt_id'] in aid_map:binding['final_attempt_id'] = aid_map[binding['final_attempt_id']]
        if response:row['run_id'] = 'run-l'
        return row
    krows = [r if r['slot_id'] in kept else stop_row(r,'k') for r in old_rows]
    lrows = [relocated(r,True) for r in old_rows if r['slot_id'] in moved]
    kreq = [r for r in requests if r['slot_id'] in kept]; kres = [r for r in responses if r['slot_id'] in kept]
    lreq = [relocated(r) for r in requests if r['slot_id'] in moved]
    lres = [relocated(r,True) for r in responses if r['slot_id'] in moved]
    if diagnostic:
        active = {r['slot_id'] for r in lrows[:5]}
        lrows = [r if r['slot_id'] in active else stop_row(r,'l') for r in lrows]
        lreq = [r for r in lreq if r['slot_id'] in active]; lres = [r for r in lres if r['slot_id'] in active]
    ksummary = {**original['summary'],'status':'stopped','stop_reasons':['cumulative_budget_stop'],'issued_attempts':len(kreq)}
    lsummary = {**original['summary'],'schema':'retrace.adaption-v6l-summary.v1','run_id':'run-l',
        'status':'stopped' if diagnostic else 'completed','stop_reasons':['cumulative_budget_stop'] if diagnostic else [],
        'planned':len(lrows),'carried_over_slots':224+len(kept),'issued_attempts':len(lreq)}
    segments['k'] = source('k',kreq,kres,krows,ksummary)
    segments['l'] = source('l',lreq,lres,lrows,lsummary)
    audits['k'].update(schedule_status='stopped',cumulative_accounted_credits='249.25')
    audits['l'] = {'passed':True,'final_closed':True,'all_scheduled_outcomes_accounted':True,
        'schedule_status':lsummary['status'],'counts':{'planned':len(lrows)},'historical_carry_credits':'249.25',
        'cumulative_accounted_credits':'260','budget_cap_credits':'750'}
    receipt.update(schema='retrace.frontier-v6l-continuation.v1',full_planned_slots=1800,
        previous_cumulative_cap_credits='250',cumulative_cap_credits='750',historical_conservative_carry_credits='249.25',
        original_run_ids=['run-i','run-j','run-k'])
    rebind(slots,receipt,segments,audits)
    return slots,receipt,segments,audits


class FourSegmentTests(unittest.TestCase):
    def test_dynamic_lossless_counts_and_all_three_old_segments_preserved(self):
        for count in (3,17,300):
            with self.subTest(count=count):
                s,r,segs,a=fixture(count);merged=v.assemble_views(s,r,segs);v.validate_segment_proofs(merged,r,a)
                self.assertEqual(len(merged['outcomes']),1800)
                self.assertEqual(r['carried_final_slots'],224+count)
                self.assertEqual(r['continuation_slots'],1576-count)
                self.assertEqual(sum(p['segment']=='k' for p in merged['source_provenance']['outcomes']),count)
                self.assertEqual(sum(x.get('failure_scope')=='global' for x in merged['responses']),2)
                for role in ('requests','responses','outcomes'):
                    for row,pointer in zip(merged[role],merged['source_provenance'][role]):self.assertEqual(v.digest(row),pointer['row_sha256'])

    def test_only_original_k_budget_stop_can_authorize_new_segment(self):
        for reason,status in (('network_or_transport_failure','stopped'),('administrative_deadline','stopped'),('','completed')):
            s,r,segs,a=fixture();segs['k']['summary'].update(status=status,stop_reasons=[reason] if reason else [])
            segs['k']['summary_bytes']=raw(segs['k']['summary']);rebind(s,r,segs,a)
            with self.assertRaisesRegex(ValueError,'specified historical interruption'):v.assemble_views(s,r,segs)
        s,r,segs,a=fixture();rows=[json.loads(x) for x in segs['k']['responses'].splitlines()];rows[0]['failure_scope']='global'
        segs['k']['responses']=lines(rows);rebind(s,r,segs,a)
        with self.assertRaisesRegex(ValueError,'cannot hide'):v.assemble_views(s,r,segs)

    def test_changed_historical_skip_and_reissue_reject(self):
        s,r,segs,a=fixture();oldskip=next(x for x in r['carried_final_outcomes'] if x['attempt_id'] is None)
        r['carried_final_outcomes'].remove(oldskip)
        with self.assertRaisesRegex(ValueError,'source-line pointers'):v.assemble_views(s,r,segs)
        s,r,segs,a=fixture();segs['l']['requests']+=segs['k']['requests'].splitlines(keepends=True)[0]
        with self.assertRaisesRegex(ValueError,'reissued'):v.assemble_views(s,r,segs)

    def test_paths_missing_outcomes_run_identity_and_receipt_counts_reject(self):
        for mode in ('path','missing','run','counts'):
            s,r,segs,a=fixture()
            if mode=='path':segs['l']['paths']['responses']='unrelated/responses.jsonl'
            if mode=='missing':segs['l']['outcomes']=b''.join(segs['l']['outcomes'].splitlines(keepends=True)[:-1])
            if mode=='run':segs['l']['responses']=segs['l']['responses'].replace(b'"run-l"',b'"other"',1)
            if mode=='counts':r['continuation_slots']-=1
            with self.subTest(mode=mode),self.assertRaises(ValueError):v.assemble_views(s,r,segs)

    def test_four_proofs_dynamic_carry_cap_and_completion_gate(self):
        for mode in ('binding','nested','carry','cap','global','stopped'):
            s,r,segs,a=fixture();merged=v.assemble_views(s,r,segs)
            if mode=='binding':a['k']['input_bindings'][v.role_paths('k')['summary']]['sha256']='0'*64
            if mode=='nested':a['l']['prior_segment_audits']['i']['passed']=False
            if mode=='carry':a['l']['historical_carry_credits']='249.24'
            if mode=='cap':a['l']['budget_cap_credits']='250'
            if mode=='global':next(x for x in merged['responses'] if x['run_id']=='run-l')['failure_scope']='global'
            if mode=='stopped':a['l']['schedule_status']='stopped'
            with self.subTest(mode=mode),self.assertRaises(ValueError):v.validate_segment_proofs(merged,r,a)

    def test_diagnostic_keeps_censored_rows_without_inventing_dependency_skips(self):
        s,r,segs,a=fixture(diagnostic=True)
        merged=v.assemble_views(s,r,segs,diagnostic=True);v.validate_segment_proofs(merged,r,a,diagnostic=True)
        self.assertTrue(any(x['model_outcome']=='not_issued_global_stop' for x in merged['outcomes']))
        for sid in r['failed_producer_descendant_slot_ids']:
            original=next(x for x in v._rows(segs['l']['outcomes'],v.role_paths('l')['outcomes'])[0] if x['slot_id']==sid)
            self.assertEqual(next(x for x in merged['outcomes'] if x['slot_id']==sid),original)
        with self.assertRaises(ValueError):v.validate_segment_proofs(merged,r,a)

    def test_full1800_frozen21_complete_and_interrupted_no_module_mutation(self):
        corpus=read('data/frontier-v6h-corpus.json');dossiers=read('data/frontier-v6h-dossiers.json');study=read('data/frontier-v6i-design.json')
        before=frozen.evaluate.__globals__.copy()
        for diagnostic in (False,True):
            s,r,segs,a=fixture(diagnostic=diagnostic)
            result=v.evaluate_composite(corpus,dossiers,study,s,r,segs,a,diagnostic=diagnostic)
            summary=result['summary']
            self.assertEqual(summary['status'],v.PARTIAL if diagnostic else v.COMPLETE)
            self.assertEqual(summary['primary_holm_family_size'],21);self.assertEqual(summary['planned_slots'],1800)
            self.assertEqual(summary['amendment']['retained_by_segment'],{'i':6,'j':218,'k':17})
            if diagnostic:
                self.assertTrue(v.diagnostic_only(summary));self.assertIs(summary['amendment']['closure_override'],False)
                self.assertEqual(sum(summary['coverage']['slot_categories'].values()),1800)
            else:self.assertTrue(summary['schedule_complete'])
            for name in ('i','j'):
                failed=next(x for x in v._rows(segs[name]['responses'],v.role_paths(name)['responses'])[0] if x.get('failure_scope')=='global')
                selected=[x for x in result['audits'] if x.get('slot_id')==failed['slot_id']]
                self.assertEqual(len(selected),2);self.assertTrue(all(not x['eligible_completed'] for x in selected))
        self.assertEqual(frozen.evaluate.__globals__,before)


if __name__ == '__main__':unittest.main()
