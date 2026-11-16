"""Invented interrupted captures; no provider calls or empirical answer access."""
from copy import deepcopy
from hashlib import sha256
import unittest

from scripts import audit_frontier_v6n_prefix as a
from tests.test_frontier_v6m_runtime_audit import capture as captured, carried_seed as seed
from tests.test_adaption_v6h import slot, emit, final


def prefix(slots=None, factory=None, **kwargs):
    v=captured(slots or [slot(0),slot(1),slot(2)],factory,**kwargs)
    v['finals']=v.pop('outcomes')
    orphan=v['requests'][-1]['attempt_id']
    v.pop('summary')
    v['responses']=v['responses'][:-1]
    v['finals']=[x for x in v['finals'] if x.get('attempt_id')!=orphan]
    n=next(i for i,r in enumerate(v['ledger']) if r['event']['kind']=='reserve' and r['event']['attempt_id']==orphan)
    v['ledger']=v['ledger'][:n+1]
    return v


def replay(v):
    return a.audit_evidence(v['slots'],v['manifest'],v['requests'],v['responses'],v['finals'],v['ledger'],
        lambda name:v['streams'][name].encode('utf-8'),historical={'carry_credits':'249','ledger_sha256':'b'*64,'inherited_unsettled_attempts':73},
        carryover=v['carryover'],original_requests=v['original_requests'],original_responses=v['original_responses'],allow_test_hooks=True)


class PrefixTests(unittest.TestCase):
    def test_only_unclosed_prefix_and_full_orphan_bound(self):
        v=prefix();before=deepcopy(v);r=replay(v)
        self.assertEqual(v,before)
        self.assertTrue(r['passed']);self.assertFalse(r['final_closed'])
        self.assertFalse(r['all_scheduled_outcomes_accounted'])
        self.assertEqual(r['schedule_status'],'interrupted_without_closure')
        self.assertEqual(r['counts']['orphan_requests'],1)
        self.assertEqual(r['orphan']['reserved_credits'],v['requests'][-1]['reserved_credits'])
        self.assertEqual(r['cumulative_inherited_unsettled_attempts'],74)
        self.assertEqual(r['budget_cap_credits'],'750')
        self.assertFalse(r['orphan']['response_observed'])

    def test_completed_capture_is_not_an_interruption(self):
        v=captured([slot(0)]);v.pop('summary');v['finals']=v.pop('outcomes')
        with self.assertRaisesRegex(ValueError,'exactly one'):replay(v)

    def test_missing_two_responses_is_not_accepted(self):
        v=prefix();v['responses'].pop()
        with self.assertRaisesRegex(ValueError,'exactly one'):replay(v)

    def test_no_orphan_final_or_provider_response_is_invented(self):
        v=prefix();bad=deepcopy(v['finals'][-1]);bad['slot_id']=v['requests'][-1]['slot_id'];v['finals'].append(bad)
        with self.assertRaisesRegex(ValueError,'orphan has no'):replay(v)

    def test_unaccounted_prior_attempt_and_rehashed_ledger_rejected(self):
        v=prefix();v['ledger']=[r for r in v['ledger'] if r['event']['kind']!='settle']
        chain='0'*64
        for n,row in enumerate(v['ledger'],1):
            row.update(seq=n,previous_sha256=chain);row['sha256']=a.digest({k:x for k,x in row.items() if k!='sha256'});chain=row['sha256']
        with self.assertRaisesRegex(ValueError,'serial prior attempt'):replay(v)

    def test_known_sse_and_usage_still_replayed(self):
        v=prefix();name=sha256(v['responses'][0]['attempt_id'].encode()).hexdigest()+'.sse'
        v['streams'][name]+='wrong'
        with self.assertRaisesRegex(ValueError,'capture length'):replay(v)

    def test_orphan_body_and_admission_gap_are_checked(self):
        v=prefix();q=v['requests'][-1];q['request']['input'][0]['content']='invented';q['request_sha256']=a.digest(q['request'])
        with self.assertRaisesRegex(ValueError,'actual source'):replay(v)
        v=prefix();q=v['requests'][-1];q['admitted_monotonic']=q['previous_attempt_finished_monotonic']+3
        with self.assertRaisesRegex(ValueError,'gap/cooldown'):replay(v)

    def test_definitive_response_cannot_be_dropped(self):
        v=prefix();v['finals'].pop()
        with self.assertRaisesRegex(ValueError,'definitive final'):replay(v)

    def test_retained_postheader_failure_and_orphan_both_carried(self):
        def factory(clock,starts,ends):
            async def transport(body):
                if len(starts)==1:
                    yield {'http_status':200,'content_type':'text/event-stream','retry_after':None}
                    raise ConnectionResetError()
                async for x in emit(final(body)):yield x
            return transport
        r=replay(prefix(factory=factory))
        self.assertEqual(r['counts']['per_slot_operational_failures'],1)
        self.assertEqual(r['cumulative_inherited_unsettled_attempts'],75)

    def test_original_actual_history_preserved(self):
        slots=[slot(0),slot(1,history_from=['s-0']),slot(2)]
        c,q,r=seed(slots);v=prefix(slots,carried=c,oldq=q,oldr=r)
        self.assertTrue(replay(v)['passed'])
        v['original_requests'][0]['request']['input'][-1]['content']='fake'
        with self.assertRaisesRegex(ValueError,'actual source'):replay(v)

    def test_prior_orphan_controls_cursor_and_still_blocks_dependencies(self):
        slots=[slot(0,'glm-5.2'),slot(1,'glm-5.2',history_from=['s-0']),slot(2),slot(3,'glm-5.2')]
        c,q,r=seed(slots,False)
        c['s-0'].update(issued=False,actual_request_issued=True,model_outcome='issued_without_response',
            error='host_interruption_orphan_request',attempt_id=None,first_attempt_id=q[0]['attempt_id'])
        v=prefix(slots,carried=c,oldq=q,oldr=[])
        result=replay(v)
        self.assertEqual(result['counts']['dependency_skips'],1)
        self.assertEqual([x['slot_id'] for x in v['requests']],['s-2','s-3'])
        self.assertFalse(result['final_closed'])
        self.assertEqual(len(v['original_responses']),0)

    def test_no_changed_original_cap_or_new_deadline(self):
        v=prefix()
        v['manifest']['deadline_utc']='2026-11-16T06:56:00+00:00'
        with self.assertRaisesRegex(ValueError,'runtime policy'):replay(v)
        v=prefix();v['manifest']['budget_before']['cumulative_cap_credits']='250'
        with self.assertRaisesRegex(ValueError,'earlier unknowns'):replay(v)


if __name__=='__main__':unittest.main()
