"""Read-only invented ledger prefixes; no current process or provider calls."""
from copy import deepcopy
import unittest
from scripts import status_frontier_v6l as s


def ledger(events):
    chain='0'*64;rows=[]
    for n,e in enumerate(events,1):
        row={'seq':n,'previous_sha256':chain,'event':e};row['sha256']=s.digest(row);chain=row['sha256'];rows.append(row)
    return rows


class StatusTests(unittest.TestCase):
    def init(self):return [{'kind':'initialize','historical_credits':'249','historical_sha256':'a'*64,'cap_credits':'750'},{'kind':'run_started'}]

    def test_unknowns_and_live_reservations_remain_separate_above250(self):
        rows=ledger(self.init()+[{'kind':'reserve','attempt_id':'x','bound_nanocredits':s.nano('2')},
            {'kind':'retain_unknown','attempt_id':'x'},{'kind':'reserve','attempt_id':'y','bound_nanocredits':s.nano('3')}])
        out=s.accounting(rows,'249','a'*64)
        self.assertEqual(out['cumulative_conservative_credits'],'254')
        self.assertEqual(out['finalized_unknown_retained_credits'],'2');self.assertEqual(out['live_reserved_credits'],'3')
        self.assertIsNone(out['actual_billed_credits']);self.assertFalse(out['recorded_run_closed'])

    def test_chain_wrong_cap_double_settlement_and_over750_rejected(self):
        base=self.init();bad=deepcopy(base);bad[0]['cap_credits']='250'
        with self.assertRaisesRegex(ValueError,'carry changed'):s.accounting(ledger(bad),'249','a'*64)
        bad=ledger(base);bad[-1]['previous_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'chain mismatch'):s.accounting(bad,'249','a'*64)
        with self.assertRaisesRegex(ValueError,'cap exceeded'):s.accounting(ledger(base+[{'kind':'reserve','attempt_id':'x','bound_nanocredits':s.nano('502')}]),'249','a'*64)
        ev=base+[{'kind':'reserve','attempt_id':'x','bound_nanocredits':s.nano('2')},
            {'kind':'settle','attempt_id':'x','accounted_nanocredits':s.nano('.1')},
            {'kind':'settle','attempt_id':'x','accounted_nanocredits':s.nano('.1')}]
        with self.assertRaisesRegex(ValueError,'duplicate accounting'):s.accounting(ledger(ev),'249','a'*64)

    def test_settlement_and_closed_record_are_metadata_not_completion_claim(self):
        out=s.accounting(ledger(self.init()+[{'kind':'reserve','attempt_id':'x','bound_nanocredits':s.nano('2')},
            {'kind':'settle','attempt_id':'x','accounted_nanocredits':s.nano('.1')},
            {'kind':'halt'},{'kind':'run_closed'}]),'249','a'*64)
        self.assertEqual(out['cumulative_conservative_credits'],'249.1');self.assertEqual(out['known_new_settled_credits'],'0.1')
        self.assertTrue(out['recorded_run_closed']);self.assertTrue(out['recorded_halt'])
        self.assertNotIn('schedule_complete',out)


if __name__=='__main__':unittest.main()
