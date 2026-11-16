"""Read-only status fixtures; no live run mutation or model calls."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from scripts import status_frontier_v6j as s


def ledger(events):
    rows=[];prev='0'*64
    for n,event in enumerate(events,1):
        row={'seq':n,'previous_sha256':prev,'event':event,'at':'2026-11-14T12:00:00+00:00'};row['sha256']=s.digest(row);rows.append(row);prev=row['sha256']
    return rows


def initial():return [{'kind':'initialize','historical_credits':s.BASELINE,'cap_credits':'250'},{'kind':'run_started','run_id':'x'}]


class StatusTests(unittest.TestCase):
    def test_only_complete_prefix_lines_and_unicode_are_read(self):
        rows=[{'slot_id':'s1','attempt_id':'a','output_text':'SECRET ANSWER 🦉','usage':{'input_tokens':4,'output_tokens':2,'unknown':'SECRET'}}]
        raw=(json.dumps(rows[0],ensure_ascii=False)+'\n').encode()+b'{"partial":'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'x';path.write_bytes(raw);before=path.read_bytes()
            actual,meta=s.read_prefix(path,'responses')
            self.assertEqual(meta['complete_lines'],1);self.assertGreater(meta['ignored_partial_bytes'],0)
            self.assertEqual(meta['complete_prefix_sha256'],sha256(raw[:meta['complete_bytes']]).hexdigest())
            self.assertNotIn('SECRET',json.dumps(actual));self.assertNotIn('output_text',actual[0]);self.assertEqual(path.read_bytes(),before)
    def test_absent_file_and_empty_file_are_different(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'x';self.assertFalse(s.read_prefix(p,'requests')[1]['present']);p.write_bytes(b'')
            self.assertTrue(s.read_prefix(p,'requests')[1]['present'])
    def test_malformed_complete_line_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'x'
            for raw in (b'{"a":1,"a":2}\n',b'{broken}\n',b'\n'):
                p.write_bytes(raw)
                with self.assertRaises(ValueError):s.read_prefix(p,'responses')
    def test_live_unknown_and_known_settlement_are_separate(self):
        e=initial()+[{'kind':'reserve','attempt_id':'a','bound_nanocredits':1000},{'kind':'settle','attempt_id':'a','accounted_nanocredits':100},{'kind':'reserve','attempt_id':'b','bound_nanocredits':2000},{'kind':'retain_429','attempt_id':'b'},{'kind':'reserve','attempt_id':'c','bound_nanocredits':3000},{'kind':'retain_unknown','attempt_id':'c'},{'kind':'reserve','attempt_id':'d','bound_nanocredits':4000}]
        value=s.accounting(ledger(e))
        self.assertEqual(value['live_reservation_count'],1);self.assertEqual(value['live_reserved_credits'],'0.000004')
        self.assertEqual(value['finalized_unknown_retained_credits'],'0.000005');self.assertEqual(value['known_new_settled_credits'],'0.0000001')
        self.assertEqual(s.nano(value['cumulative_conservative_credits']),s.nano(s.BASELINE)+9100);self.assertIsNone(value['actual_billed_credits'])
    def test_ledger_tamper_and_duplicate_settle_rejected(self):
        rows=ledger(initial());rows[-1]['event']['run_id']='changed'
        with self.assertRaisesRegex(ValueError,'chain'):s.accounting(rows)
        e=initial()+[{'kind':'reserve','attempt_id':'a','bound_nanocredits':10},{'kind':'settle','attempt_id':'a','accounted_nanocredits':1},{'kind':'settle','attempt_id':'a','accounted_nanocredits':1}]
        with self.assertRaisesRegex(ValueError,'duplicate'):s.accounting(ledger(e))
    def fixture(self):
        slots=[{'slot_id':'old','model':'m'},{'slot_id':'a','model':'m'},{'slot_id':'b','model':'n'}]
        receipt={'carryover_rows':[{'slot_id':'old','model_outcome':'operational_failure'}]}
        q=[{'slot_id':'a','attempt_id':'a1','attempt_number':1,'admitted_monotonic':0,'previous_attempt_finished_monotonic':None},{'slot_id':'b','attempt_id':'b1','attempt_number':1,'admitted_monotonic':70,'previous_attempt_finished_monotonic':5}]
        r=[{'slot_id':'a','attempt_id':'a1','first_attempt':True,'model_outcome':'http_429','http_status':429,'retry_cooldown_seconds':65,'settled_credits':None,'failure_category':'rate_limit','latency_ms':5000}]
        records={'requests':q,'responses':r,'outcomes':[],'ledger':ledger(initial())}
        return slots,receipt,records
    def test_all_denominators_live_inflight_and_429_pacing(self):
        a,b,c=self.fixture();value=s.summarize(a,b,c,active_lock=True)
        self.assertEqual(value['original_planned_slots'],3);self.assertEqual(value['continuation_planned_slots'],2)
        self.assertEqual(value['observed_requests_without_response'],1);self.assertEqual(value['per_model']['m']['carried_original_failed'],1)
        self.assertEqual(value['pacing']['observed_gap_violations'],0);self.assertEqual(value['pacing']['minimum_observed_429_margin_seconds'],0)
        self.assertTrue(value['provisional']);self.assertFalse(value['final_audit_performed'])
        c['requests'][1]['admitted_monotonic']=69
        self.assertEqual(s.summarize(a,b,c,active_lock=True)['pacing']['observed_gap_violations'],1)
    def test_cross_file_prefix_lag_is_reported_not_fabricated(self):
        a,b,c=self.fixture();c['requests']=[]
        value=s.summarize(a,b,c,active_lock=True)
        self.assertEqual(value['responses_not_yet_in_request_prefix'],1);self.assertEqual(value['continuation_finalized_slots'],0)
    def test_no_credential_or_source_body_projection(self):
        row={'slot_id':'a','attempt_id':'a1','request':{'instructions':'SECRET','input':'SECRET'},'raw_response':'SECRET','output_text':'SECRET','error':'SECRET'}
        projected=s.projection('requests',row)
        self.assertNotIn('SECRET',json.dumps(projected));self.assertNotIn('request',projected)
    def test_carried_reissue_or_duplicate_final_cannot_count_progress(self):
        a,b,c=self.fixture();c['requests'][0]['slot_id']='old'
        with self.assertRaisesRegex(ValueError,'carried'):s.summarize(a,b,c,active_lock=True)
        a,b,c=self.fixture();c['outcomes']=[{'slot_id':'a','model_outcome':'completed'}]*2
        with self.assertRaisesRegex(ValueError,'repeated'):s.summarize(a,b,c,active_lock=True)
    def test_closed_ledger_is_still_not_final_audit(self):
        a,b,c=self.fixture();c['ledger']=ledger(initial()+[{'kind':'run_closed'}])
        value=s.summarize(a,b,c,active_lock=False)
        self.assertTrue(value['accounting']['recorded_run_closed']);self.assertFalse(value['final_audit_performed']);self.assertTrue(value['provisional'])

if __name__=='__main__':unittest.main()
