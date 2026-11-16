"""Invented stopped outcomes on frozen metadata; no empirical answers or API."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from retrace import frontier_v6k_partial as p
from scripts import score_frontier_v6k_partial as cli
from tests.test_frontier_v6k_eval import fixture, source, read
from tests import test_score_frontier_v6k as full_cli_tests


def stopped_fixture(keep=25):
    slots, receipt, segments, audits = fixture(); old = segments['k']
    rows = {role:p.k._rows(old[role],old['paths'][role])[0] for role in ('requests','responses','outcomes')}
    retained = {r['slot_id'] for r in rows['outcomes'][:keep]}
    finals=[]
    for row in rows['outcomes']:
        if row['slot_id'] in retained: finals.append(row); continue
        finals.append({**{k:row[k] for k in ('slot_id','case_id','model','condition','phase','run_id')},
            'issued':False,'terminal_valid':False,'model_outcome':'not_issued_global_stop','error':'not_issued_global_stop',
            'response_status':None,'output_text':'','blocked_dependencies':[],'slot_final':True,'attempt_id':None,
            'attempts_issued':0,'first_attempt_id':None})
    requests=[r for r in rows['requests'] if r['slot_id'] in retained]
    responses=[r for r in rows['responses'] if r['slot_id'] in retained]
    summary={**old['summary'],'status':'stopped','stop_reasons':['cumulative_budget_stop'],'issued_attempts':len(requests),'slot_outcomes':1576}
    segments['k']=source('k',requests,responses,finals,summary)
    audits['k'].update(schedule_status='stopped',prior_segment_audits=deepcopy({n:audits[n] for n in ('i','j')}))
    audits['k']['input_bindings']={path:{'sha256':sha256(segments['k'][{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(role,role)]).hexdigest(),
        'bytes':len(segments['k'][{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(role,role)])} for role,path in segments['k']['paths'].items()}
    return slots,receipt,segments,audits


class PartialPureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.data=stopped_fixture()
    def fresh(self): return deepcopy(self.data)

    def test_lossless_stopped_projection_has_all1800_and_original_failures(self):
        slots,receipt,segments,audits=self.fresh();before=deepcopy(segments)
        merged=p.assemble_closed_partial(slots,receipt,segments,audits)
        self.assertEqual(segments,before);self.assertEqual(len(merged['outcomes']),1800)
        self.assertEqual(sum(r['model_outcome']=='not_issued_global_stop' for r in merged['outcomes']),1576-25)
        self.assertEqual(sum(r.get('failure_scope')=='global' for r in merged['responses']),2)
        for role in ('requests','responses','outcomes'):
            for row,pointer in zip(merged[role],merged['source_provenance'][role]):
                self.assertEqual(p.k.digest(row),pointer['row_sha256'])
        self.assertEqual(sum(ptr['segment']=='j' and row['model_outcome']=='not_issued_dependency_failed'
            for row,ptr in zip(merged['outcomes'],merged['source_provenance']['outcomes'])),11)

    def test_stop_before_known_failed_descendant_does_not_invent_skip(self):
        slots,receipt,segments,audits=stopped_fixture(0)
        merged=p.assemble_closed_partial(slots,receipt,segments,audits)
        byid={r['slot_id']:r for r in merged['outcomes']}
        for sid in receipt['failed_producer_descendant_slot_ids']:
            self.assertEqual(byid[sid]['model_outcome'],'not_issued_global_stop')

    def test_completed_k_wrong_source_missing_outcome_or_audit_rejects(self):
        for kind in ('complete','source','missing','nested','carry'):
            s,r,segs,a=self.fresh()
            if kind=='complete':a['k']['schedule_status']='completed'
            if kind=='source':segs['j']['responses']+=b'{}\n'
            if kind=='missing':segs['k']['outcomes']=b''.join(segs['k']['outcomes'].splitlines(keepends=True)[:-1])
            if kind=='nested':a['k']['prior_segment_audits']['j']['passed']=False
            if kind=='carry':a['k']['historical_carry_credits']='0'
            with self.subTest(kind=kind),self.assertRaises(ValueError):p.assemble_closed_partial(s,r,segs,a)

    def test_full_diagnostic_evaluator_has_no_override_pvalues_or_intervals(self):
        s,r,segs,a=self.fresh();before=p.frozen.evaluate.__globals__.copy()
        result=p.evaluate_partial(read('data/frontier-v6h-corpus.json'),read('data/frontier-v6h-dossiers.json'),
            read('data/frontier-v6i-design.json'),s,r,segs,a)
        self.assertEqual(p.frozen.evaluate.__globals__,before)
        summary=result['summary'];self.assertEqual(summary['status'],p.STATUS)
        self.assertFalse(summary['schedule_complete']);self.assertFalse(summary['test_design'])
        self.assertFalse(summary['amendment']['closure_override']);self.assertEqual(summary['planned_slots'],1800)
        self.assertEqual(summary['cluster_intervals'],[])
        primary=[x for x in summary['paired_comparisons'] if x['primary_family_member'] and x['view']=='first_attempt']
        self.assertEqual(len(primary),21)
        self.assertTrue(all(x['p_two_sided_exact'] is None and x['holm_adjusted_p'] is None for x in summary['paired_comparisons']))
        self.assertEqual(summary['coverage']['slot_categories']['unissued_censored_by_stop'],1551)
        self.assertEqual(sum(summary['coverage']['slot_categories'].values()),1800)
        self.assertTrue(all(x['views']['first_attempt']['observed_successes'] is None
            for x in summary['coverage']['arms'] if x['condition']=='nl_source'))

    def test_censoring_yield_bounds_separate_invalid_and_transport(self):
        slots=[{'slot_id':str(i),'case_id':'c','model':'m','condition':'strict_source_ir','phase':'extract'} for i in range(5)]
        finals=[{'slot_id':str(i),'issued':i<3,'model_outcome':kind,'terminal_valid':i!=2,'response_status':'completed',
                 'output_text':'{}','error':None if i!=2 else 'timeout'} for i,kind in enumerate(
                 ('completed','completed','operational_failure','not_issued_dependency_failed','not_issued_global_stop'))]
        grades=[{'slot_id':str(i),'view':view,'correct':i==0,'provider_completed':i<2,
                 'eligible_completed':i<2,'schema_valid':i==0} for view in ('first_attempt','eventual') for i in range(5)]
        out=p.coverage(slots,{'cases':[{'id':'c','partition':'synthetic'}]},
            {'outcomes':finals,'responses':[r for r in finals if r['issued']]},grades)
        arm=next(r for r in out['arms'] if r['partition']=='all');v=arm['views']['first_attempt']
        self.assertEqual((arm['issued'],arm['definitive_dependency_skip'],arm['unissued_censored_by_stop']),(3,1,1))
        self.assertEqual(v['unissued_censoring_bounds'],[.2,.4]);self.assertEqual(v['eligible_invalid_output'],1)
        self.assertEqual(v['issued_provider_failure'],1);self.assertEqual(v['admitted_response_conditional']['rate'],1)

    def test_valid_sfr_stages_have_schema_coverage_not_fabricated_zero_accuracy(self):
        conditions=('sfr_probe','sfr_backtranslation','nl_source')
        slots=[{'slot_id':kind,'case_id':'c','model':'m','condition':kind,'phase':'a'} for kind in conditions]
        finals=[{'slot_id':kind,'issued':True,'model_outcome':'completed','terminal_valid':True,
                 'response_status':'completed','output_text':'{}','error':None} for kind in conditions]
        grades=[{'slot_id':kind,'view':view,'correct':False if kind!='nl_source' else None,
                 'provider_completed':True,'eligible_completed':True,'schema_valid':kind!='nl_source'}
                for kind in conditions for view in ('first_attempt','eventual')]
        out=p.coverage(slots,{'cases':[{'id':'c','partition':'synthetic'}]},
            {'outcomes':finals,'responses':finals},grades)
        for arm in out['arms']:
            for v in arm['views'].values():
                self.assertEqual(v['provider_completed'],1);self.assertFalse(v['standalone_success_assessed'])
                for key in ('observed_successes','observed_successes_per_planned_slot','unissued_censoring_bounds','admitted_response_conditional'):
                    self.assertIsNone(v[key])
                if arm['condition']=='nl_source':
                    self.assertFalse(v['schema_assessed']);self.assertIsNone(v['schema_admitted']);self.assertIsNone(v['eligible_invalid_output'])
                else:
                    self.assertTrue(v['schema_assessed']);self.assertEqual(v['schema_admitted'],1);self.assertEqual(v['eligible_invalid_output'],0)


class PartialCliTests(unittest.TestCase):
    # Reuse only fixture helpers; the complete-study tests remain separate.
    setUp = full_cli_tests.ThreeSegmentCliTests.setUp
    write = full_cli_tests.ThreeSegmentCliTests.write
    def fixture(self):
        segments=full_cli_tests.ThreeSegmentCliTests.fixture(self)
        self.audits['k']['schedule_status']='stopped';self.write(cli.full.AUDITS['k'],self.audits['k'])
        self.args=list(self.args);self.args[4]=cli.full.sha(self.root/cli.full.AUDITS['k']);self.args=tuple(self.args)
        for name in cli.NEW_SOURCES:self.write(name,b'# invented new diagnostic code\n')
        summary=self.result['summary'];summary.update(status=p.STATUS,schedule_complete=False,planned_slots=1800,cluster_intervals=[],
            paired_comparisons=[{'primary_family_member':True,'view':'first_attempt','p_two_sided_exact':None,'holm_adjusted_p':None} for _ in range(21)],
            issued_attempts_observed=3,coverage={'slot_categories':{'issued':3,'definitive_dependency_skip':11,'unissued_censored_by_stop':1786}},
            operational_summary={'stop_reasons':['administrative_deadline']})
        return segments
    def compute(self):
        with patch.object(cli,'FREEZE_SHA',self.args[1]),patch.object(cli.full,'audit_runtime',return_value=deepcopy(self.audits['k'])),\
             patch.object(cli,'evaluate_partial',return_value=deepcopy(self.result)):
            return cli.compute(*self.args,frozen_aliases=cli.full.ALIASES)

    def test_partial_closure_exact_bytes_and_exclusive_writer(self):
        segments=self.fixture();result,views=self.compute()
        for role in ('requests','responses','outcomes'):
            self.assertEqual(views[role],b''.join(segments[n][role] for n in cli.full.SEGMENTS))
        manifest=cli.write_outputs(self.root,result,views)
        self.assertEqual(manifest['status'],p.STATUS);self.assertFalse(manifest['inference_available'])
        self.assertEqual(len(manifest['files']),8)
        self.assertIn('censored, not observed wrong reasoning',(self.root/cli.OUTPUT/'report-facts.md').read_text())
        with self.assertRaisesRegex(ValueError,'already_exists'):cli.write_outputs(self.root,result,views)

    def test_partial_cli_rejects_active_and_completed_branch(self):
        self.fixture();self.write('results/frontier-v6k/budget/active.lock',b'active')
        with patch.object(cli.full,'audit_runtime') as call:
            with self.assertRaisesRegex(ValueError,'still_active'):cli.compute(*self.args)
            call.assert_not_called()
        (self.root/'results/frontier-v6k/budget/active.lock').unlink()
        self.audits['k']['schedule_status']='completed';self.write(cli.full.AUDITS['k'],self.audits['k'])
        args=list(self.args);args[4]=cli.full.sha(self.root/cli.full.AUDITS['k'])
        with patch.object(cli,'FREEZE_SHA',self.args[1]),patch.object(cli.full,'audit_runtime',return_value=self.audits['k']):
            with self.assertRaisesRegex(ValueError,'closed_stopped'):cli.compute(*args,frozen_aliases=cli.full.ALIASES)

    def test_post_freeze_code_and_saved_source_changes_reject(self):
        self.fixture();result,views=self.compute()
        self.write('retrace/frontier_v6k_partial.py',b'# changed diagnostic code\n')
        with self.assertRaisesRegex(ValueError,'source_changed_before'):cli.write_outputs(self.root,result,views)
        self.assertFalse((self.root/cli.OUTPUT).exists())

    def test_each_saved_audit_and_nested_replay_is_required(self):
        self.fixture()
        for number in (2,3,4):
            args=list(self.args);args[number]='f'*64
            with patch.object(cli,'FREEZE_SHA',self.args[1]),self.subTest(number=number):
                with self.assertRaisesRegex(ValueError,'saved_runtime_audit_hash'):
                    cli.compute(*args,frozen_aliases=cli.full.ALIASES)
        bad=deepcopy(self.audits['k']);bad['prior_segment_audits']['j']['passed']=False
        with patch.object(cli,'FREEZE_SHA',self.args[1]),patch.object(cli.full,'audit_runtime',return_value=bad):
            with self.assertRaisesRegex(ValueError,'do_not_reproduce'):
                cli.compute(*self.args,frozen_aliases=cli.full.ALIASES)

    def test_late_diagnostic_code_change_rejects_without_output(self):
        self.fixture()
        def changed(*args):
            self.write('retrace/frontier_v6k_partial.py',b'# changed during scoring\n');return deepcopy(self.result)
        with patch.object(cli,'FREEZE_SHA',self.args[1]),patch.object(cli.full,'audit_runtime',return_value=self.audits['k']),\
             patch.object(cli,'evaluate_partial',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'partial_code_changed'):
                cli.compute(*self.args,frozen_aliases=cli.full.ALIASES)
        self.assertFalse((self.root/cli.OUTPUT).exists())

    def test_any_inferential_claim_prevents_partial_publication(self):
        self.fixture();result,views=self.compute()
        result['summary']['paired_comparisons']=[{'p_two_sided_exact':.03,'holm_adjusted_p':None}]
        with self.assertRaisesRegex(ValueError,'diagnostic_only'):
            cli.write_outputs(self.root,result,views)
        self.assertFalse((self.root/cli.OUTPUT).exists())

    def test_audited_side_evidence_change_blocks_publication(self):
        self.fixture();path='results/frontier-v6k/continuation/streams/invented.sse'
        self.write(path,b'original synthetic SSE bytes')
        self.audits['k']['input_bindings'][path]=cli.full.binding(self.root/path)
        self.write(cli.full.AUDITS['k'],self.audits['k'])
        args=list(self.args);args[4]=cli.full.sha(self.root/cli.full.AUDITS['k']);self.args=tuple(args)
        result,views=self.compute();self.write(path,b'changed synthetic SSE bytes')
        with self.assertRaisesRegex(ValueError,'runtime_evidence_changed_before'):
            cli.write_outputs(self.root,result,views)
        self.assertFalse((self.root/cli.OUTPUT).exists())

    def test_empty_or_missing_primary_family_cannot_pass_vacuously(self):
        self.fixture();result,views=self.compute()
        for rows in ([],result['summary']['paired_comparisons'][:20]):
            bad=deepcopy(result);bad['summary']['paired_comparisons']=rows
            with self.assertRaisesRegex(ValueError,'diagnostic_only'):
                cli.write_outputs(self.root,bad,views)
        self.assertFalse((self.root/cli.OUTPUT).exists())


if __name__=='__main__':unittest.main()
