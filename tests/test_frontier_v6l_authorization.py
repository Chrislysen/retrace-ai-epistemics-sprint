"""Invented closed journals exercise the unissued-only receipt boundary."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import authorize_frontier_v6l as a


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        p=patch.object(a,'ROOT',self.root); p.start(); self.addCleanup(p.stop)
        self.slots=[{'slot_id':str(i),'history_from':[]} for i in range(1800)]
        self.slots[6]['history_from']=['3']
        self.specs=[('i','results/frontier-v6i/primary','response_model_mismatch'),
            ('j','results/frontier-v6j/continuation','network_or_transport_failure'),
            ('k','results/frontier-v6k/continuation','cumulative_budget_stop')]

    def put(self,name,obj,lines=False):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text((''.join(json.dumps(r)+'\n' for r in obj) if lines else json.dumps(obj)),encoding='utf-8')

    def fixture(self):
        finalized=set()
        for version,directory,reason in self.specs:
            chosen={'i':['0'],'j':['1','2'],'k':['3','4','5']}[version]
            issued=[sid for sid in chosen if sid not in ('2','5')]
            requests=[{'attempt_id':version+sid,'slot_id':sid} for sid in issued]
            if version=='k':requests.append({'attempt_id':'k4retry','slot_id':'4'})
            outcomes=[]
            for s in self.slots:
                sid=s['slot_id']
                if sid in finalized:continue
                active=sid in chosen; sent=sid in issued
                outcomes.append({'slot_id':sid,'issued':sent,'attempts_issued':2 if sid=='4' and active else int(sent),
                    'attempt_id':version+sid if sent else None,'terminal_valid':active and sid=='0',
                    'model_outcome':('completed' if sid=='0' else 'operational_failure') if sent else
                        'not_issued_dependency_failed' if active else 'not_issued_global_stop'})
            self.put(directory+'/run.json',{})
            self.put(directory+'/summary.json',{'run_id':version,'status':'stopped','stop_reasons':[reason],
                'issued_attempts':len(requests),'issued_slots':len(issued),'retries':len(requests)-len(issued)})
            self.put(directory+'/runtime-audit.json',{'passed':True,'final_closed':True,'schedule_status':'stopped'})
            self.put(directory+'/requests.jsonl',requests,True);self.put(directory+'/responses.jsonl',requests,True)
            self.put(directory+'/slot-outcomes.jsonl',outcomes,True)
            self.put(f'results/frontier-v6{version}/budget/ledger.jsonl',[],True)
            self.put(f'data/frontier-v6{version}-freeze.json',{})
            finalized.update(chosen)

    def test_dynamic_complement_preserves_failures_skips_and_explicit_retry(self):
        self.fixture();seg,bindings,issued,finals,remaining,desc,_=a.collect_segments(self.slots,self.specs)
        self.assertEqual(issued,['0','1','3','4']);self.assertEqual(list(finals),list('012345'))
        self.assertEqual(len(remaining),1794);self.assertEqual(desc,['6'])
        self.assertEqual(seg[-1]['issued_slots'],2);self.assertEqual(seg[-1]['definitive_final_slots'],3)
        self.assertEqual(len(bindings),6)
        self.assertEqual(bindings[-1]['row_sha256'],a.digest(finals['5']))

    def test_other_k_stop_does_not_authorize_cap_change(self):
        self.fixture();name=self.specs[-1][1]+'/summary.json'
        obj=a.read(name);obj['stop_reasons']=['delivery_buffer_reached'];self.put(name,obj)
        with self.assertRaisesRegex(ValueError,'unauthorized prior stop'):a.collect_segments(self.slots,self.specs)

    def test_issued_placeholder_is_not_recoverable(self):
        self.fixture();name=self.specs[-1][1]+'/slot-outcomes.jsonl'
        rs=a.rows(name);r=next(x for x in rs if x['slot_id']=='4');r.update(model_outcome='not_issued_global_stop',issued=False,attempts_issued=0)
        self.put(name,rs,True)
        with self.assertRaisesRegex(ValueError,'issued placeholder forbidden'):a.collect_segments(self.slots,self.specs)

    def test_duplicate_missing_outcomes_or_attempts_rejected(self):
        self.fixture();name=self.specs[-1][1]+'/slot-outcomes.jsonl';rs=a.rows(name)
        self.put(name,rs[:-1]+[deepcopy(rs[0])],True)
        with self.assertRaisesRegex(ValueError,'old outcome inventory'):a.collect_segments(self.slots,self.specs)
        self.put(name,rs,True);q=self.specs[-1][1]+'/responses.jsonl';rr=a.rows(q);self.put(q,rr[:-1],True)
        with self.assertRaisesRegex(ValueError,'closed request response pairing'):a.collect_segments(self.slots,self.specs)

    def test_active_k_blocks_before_reading_snapshot_or_audit(self):
        p=self.root/'results/frontier-v6k/budget/active.lock';p.parent.mkdir(parents=True);p.write_text('active')
        with patch.object(a,'replay_k') as replay:
            with self.assertRaisesRegex(ValueError,'prior worker still active'):a.build(snapshot_sha256='a'*64,audit_sha256='b'*64)
            replay.assert_not_called()

    def test_path_escape_and_partial_journal_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'invalid protected path'):a.path('../escape')
        self.put('data/partial.jsonl',{'line':1})
        with self.assertRaisesRegex(ValueError,'partial journal'):a.rows('data/partial.jsonl')

    def test_late_source_mutation_or_unprotected_journal_blocks_publication(self):
        self.put('data/old.json',{'value':1});h=a.hash_file('data/old.json')
        protected={'data/old.json':h};proof={'input_bindings':{'data/old.json':
            {'sha256':h,'bytes':a.path('data/old.json').stat().st_size}}}
        a.verify_preservation(protected,protected,proof)
        with self.assertRaisesRegex(ValueError,'journal not preserved'):
            a.verify_preservation({},protected,proof)
        self.put('data/old.json',{'value':2})
        with self.assertRaisesRegex(ValueError,'protected changed before publication'):
            a.verify_preservation(protected,protected,proof)


if __name__=='__main__':unittest.main()
