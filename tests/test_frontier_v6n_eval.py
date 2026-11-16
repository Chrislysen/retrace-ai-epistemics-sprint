"""Recovery scoring fixtures; no historical provider outputs are inspected."""
from copy import deepcopy
import unittest
from retrace import frontier_v6n_eval as v
from retrace import frontier_v6i_eval as frozen
from retrace.adaption_v6h import digest
from tests.test_recovery_v6n import fixture,encode,jsonl,CONDITIONS
from tests.test_frontier_v6i_eval import small_fixture,journals
from tests.test_frontier_v6k_eval import fixture as full_fixture,read
from retrace import frontier_v6k_eval as k
from retrace.recovery_v6n import orphan_disposition


def assembled_fixture():
    slots,receipt,contents=fixture()
    # Rebuild the identical source fixture solely to obtain its authored inputs.
    data=small_fixture(CONDITIONS)
    finals,responses,requests,_=journals(slots,data[4]);r=responses[-1];r['run_id']='invented-n'
    r.update(requested_model=r['model'],returned_model=r['model']);f=finals[-1];f.update(r)
    run={'run_id':'invented-n','slots':slots,'sessions_sha256':digest(slots)}
    summary={'schema':'retrace.adaption-v6n-summary.v1','run_id':'invented-n','planned':1,'original_planned':7,
        'carried_over_slots':6,'all_scheduled_outcomes_recorded':True,'issued_without_outcome_attempt_ids':[],
        'status':'completed','stop_reasons':[]}
    continuation={'paths':v.role_paths(),'manifest':run,'manifest_bytes':encode(run),'summary':summary,
        'summary_bytes':encode(summary),'requests':jsonl([requests[-1]]),'responses':jsonl([r]),'outcomes':jsonl([f])}
    return data,receipt,contents,continuation


class RecoveryScoringTests(unittest.TestCase):
    def test_full1800_diagnostic21null_and_separate_same21_sensitivity(self):
        slots,receipt,segments,audits=full_fixture()
        merged=k.assemble_views(slots,receipt,segments)
        targets=[s for s in slots if s['condition']=='commitment' and s['phase']=='fresh_withdrawn'
                    and any(r['slot_id']==s['slot_id'] for r in merged['responses'])][:2]
        self.assertEqual(len(targets),2)
        for target in targets:
            request=next(q for q in merged['requests'] if q['slot_id']==target['slot_id'])
            merged['responses']=[r for r in merged['responses'] if r['slot_id']!=target['slot_id']]
            overlay=orphan_disposition(target,request,origin_run_id='invented-m',recovery_id='invented-recovery',
                proof_path='invented/proof.json',proof_sha256='f'*64)
            merged['outcomes']=[overlay if r['slot_id']==target['slot_id'] else r for r in merged['outcomes']]
        diagnostic,sensitivity=v.score_views(read('data/frontier-v6h-corpus.json'),read('data/frontier-v6h-dossiers.json'),
            read('data/frontier-v6i-design.json'),slots,merged,{'status':'invented-recovery'},complete=True)
        self.assertTrue(v.diagnostic_only(diagnostic['summary']))
        self.assertEqual(sensitivity['summary']['primary_holm_family_size'],21)
        self.assertEqual(sensitivity['summary']['planned_slots'],1800)
        self.assertEqual(diagnostic['audits'],sensitivity['audits'])
        for target in targets:
            for view in ('first_attempt','eventual'):
                row=next(a for a in diagnostic['audits'] if a.get('slot_id')==target['slot_id'] and a.get('view')==view)
                self.assertFalse(row['correct']);self.assertFalse(row['provider_completed'])

    def test_lossless_five_actual_sources_and_two_separate_overlays(self):
        data,receipt,contents,cont=assembled_fixture();before=deepcopy(contents)
        got=v.assemble_views(data[3],receipt,contents,cont)
        self.assertEqual(len(got['outcomes']),7);self.assertEqual(len(got['requests']),7)
        self.assertEqual(len(got['responses']),5);self.assertEqual(contents,before)
        self.assertEqual([p['segment'] for p in got['source_provenance']['outcomes']],['i','j','k','recovery','m','recovery_m','n'])
        for row,p in zip(got['outcomes'],got['source_provenance']['outcomes']):
            raw=cont['outcomes'] if p['segment']=='n' else contents[p['source_path']]
            self.assertEqual(v._strict(raw.splitlines()[p['source_line_one_based']-1]),row)

    def test_new_segment_cannot_reissue_orphan(self):
        data,r,c,cont=assembled_fixture();q=v.rows(cont['requests'])[0]
        q['slot_id']=data[3][3]['slot_id'];cont['requests']=jsonl([q])
        with self.assertRaisesRegex(ValueError,'reissued'):v.assemble_views(data[3],r,c,cont)

    def test_third_unanswered_new_request_is_not_a_complete_recovery(self):
        data,r,c,cont=assembled_fixture();cont['responses']=b''
        with self.assertRaisesRegex(ValueError,'new n orphan'):v.assemble_views(data[3],r,c,cont)

    def test_unchanged_diagnostic_and_sensitivity_have_identical_grades(self):
        data,r,c,cont=assembled_fixture();merged=v.assemble_views(data[3],r,c,cont)
        operational={'schema':'invented-recovery','status':'derived','planned':7}
        original_func=frozen.closed_summary
        expected=frozen.evaluate(*data[:3],data[3],merged['outcomes'],merged['responses'],merged['requests'],operational,10,require_full_design=False)
        diagnostic,sensitivity=v.score_views(*data[:3],data[3],merged,operational,complete=True,bootstrap_repeats=10,require_full_design=False)
        self.assertEqual(diagnostic,expected);self.assertIs(frozen.closed_summary,original_func)
        self.assertEqual(diagnostic['audits'],sensitivity['audits'])
        self.assertFalse(diagnostic['summary']['schedule_complete']);self.assertTrue(sensitivity['summary']['schedule_complete'])
        self.assertEqual(sensitivity['summary']['status'],v.SENSITIVITY)
        self.assertEqual(sensitivity['summary']['confirmatory_status'],'explicitly_amended_not_untouched_confirmatory')

    def test_interrupted_recovery_has_no_sensitivity(self):
        data,r,c,cont=assembled_fixture();merged=v.assemble_views(data[3],r,c,cont)
        diagnostic,sensitivity=v.score_views(*data[:3],data[3],merged,{'status':'interrupted'},complete=False,
            bootstrap_repeats=10,require_full_design=False)
        self.assertIsNone(sensitivity);self.assertEqual(diagnostic['summary']['cluster_intervals'],[])

    def test_closed_proof_cannot_relabel_k_as_normally_closed(self):
        data,r,c,cont=assembled_fixture();merged=v.assemble_views(data[3],r,c,cont)
        with self.assertRaisesRegex(ValueError,'forensic proof'):
            v.validate_proofs(merged,r,{'passed':True,'final_closed':True,'schedule_status':'completed'}, {})

    def test_new_stopped_segment_cannot_borrow_complete_status(self):
        data,r,c,cont=assembled_fixture();merged=v.assemble_views(data[3],r,c,cont)
        prefix={'passed':True,'final_closed':False,'schedule_status':'interrupted_without_closure',
            'recovery_prefix_proof':{'passed':True,'final_closed':False,'schedule_status':'interrupted_without_closure'}}
        with self.assertRaisesRegex(ValueError,'closed branch'):
            v.validate_proofs(merged,r,prefix,{'passed':True,'final_closed':True,'all_scheduled_outcomes_accounted':True,'schedule_status':'stopped'})


if __name__=='__main__':unittest.main()
