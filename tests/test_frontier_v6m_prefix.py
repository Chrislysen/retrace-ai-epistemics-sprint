"""Invented interrupted captures; no provider calls or empirical answer access."""
from copy import deepcopy
from hashlib import sha256
import unittest

from scripts import audit_frontier_v6m_prefix as a
from tests.test_frontier_v6k_runtime_audit import captured, seed
from tests.test_adaption_v6h import slot, emit, final


def prefix(slots=None, factory=None, **kwargs):
    v=captured(slots or [slot(0),slot(1),slot(2)],factory,**kwargs)
    orphan=v['requests'][-1]['attempt_id']
    v.pop('summary')
    v['responses']=v['responses'][:-1]
    v['finals']=[x for x in v['finals'] if x.get('attempt_id')!=orphan]
    n=next(i for i,r in enumerate(v['ledger']) if r['event']['kind']=='reserve' and r['event']['attempt_id']==orphan)
    v['ledger']=v['ledger'][:n+1]
    return v


def replay(v):
    return a.audit_evidence(**{k:x for k,x in v.items() if k!='streams'},read_stream=lambda name:v['streams'][name],allow_test_hooks=True)


class PrefixTests(unittest.TestCase):
    def test_only_unclosed_prefix_and_full_orphan_bound(self):
        v=prefix();before=deepcopy(v);r=replay(v)
        self.assertEqual(v,before)
        self.assertTrue(r['passed']);self.assertFalse(r['final_closed'])
        self.assertFalse(r['all_scheduled_outcomes_accounted'])
        self.assertEqual(r['schedule_status'],'interrupted_without_closure')
        self.assertEqual(r['counts']['orphan_requests'],1)
        self.assertEqual(r['orphan']['reserved_credits'],v['requests'][-1]['reserved_credits'])
        self.assertEqual(r['cumulative_inherited_unsettled_attempts'],65)
        self.assertFalse(r['orphan']['response_observed'])

    def test_completed_capture_is_not_an_interruption(self):
        v=captured([slot(0)]);v.pop('summary')
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
        v['streams'][name]+=b'wrong'
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
        calls=[0]
        async def transport(body):
            calls[0]+=1
            if calls[0]==1:
                yield {'http_status':200,'content_type':'text/event-stream','retry_after':None}
                raise ConnectionResetError()
            async for x in emit(final(body)):yield x
        r=replay(prefix(factory=transport))
        self.assertEqual(r['counts']['per_slot_operational_failures'],1)
        self.assertEqual(r['cumulative_inherited_unsettled_attempts'],66)

    def test_original_actual_history_preserved(self):
        slots=[slot(0),slot(1,history_from=['s-0']),slot(2)]
        c,q,r=seed(slots);v=prefix(slots,seeds=c,oldq=q,oldr=r)
        self.assertTrue(replay(v)['passed'])
        v['original_requests'][0]['request']['input'][-1]['content']='fake'
        with self.assertRaisesRegex(ValueError,'actual source'):replay(v)


if __name__=='__main__':unittest.main()
