"""Invented authentication boundary tests; no actual score/publication inputs."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import score_frontier_v6m as cli
from retrace import recovery_v6m as recovery


class RecoveryCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def write(self,name,obj):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(obj if isinstance(obj,bytes) else (json.dumps(obj)+'\n').encode());return path
    def fixture(self,diagnostic=False):
        prefix={'passed':True,'final_closed':False,'schedule_status':'interrupted_without_closure'}
        self.write(cli.PREFIX_PROOF,prefix)
        overlay='results/frontier-v6m-recovery/orphan-dispositions.jsonl';self.write(overlay,b'{"derived":true}\n')
        self.write(recovery.BASELINE_LEDGER,b'{"old_open_ledger":true}\n')
        receipt={'schema':'retrace.frontier-v6m-continuation.v1','full_planned_slots':1800,
            'sessions_path':'data/frontier-v6i-sessions.json','cumulative_cap_credits':'750',
            'previous_cumulative_cap_credits':'250','observed_response_models':recovery.OBSERVED_RESPONSE_MODELS,
            'prior_freeze_path':'data/frontier-v6k-freeze.json','prior_freeze_sha256':recovery.K_FREEZE_SHA,
            'deadline_utc':recovery.DEADLINE.isoformat(),'baseline_snapshot_path':recovery.BASELINE_LEDGER,
            'baseline_snapshot_sha256':cli.sha(self.root/recovery.BASELINE_LEDGER),
            'recovery_auditor_path':recovery.RECOVERY_AUDITOR,'source_segments':[{'segment':x} for x in ('i','j','k')],
            'carried_final_slots':1246,'carried_issued_slots':1167,'continuation_slots':554,'inherited_unsettled_attempts':66,
            'historical_conservative_carry_credits':'190.25','recovery_observed_at_utc':'2026-11-15T15:00:00+00:00',
            'recovery_proof_path':cli.PREFIX_PROOF,'recovery_proof_sha256':cli.sha(self.root/cli.PREFIX_PROOF),
            'orphan_disposition_path':overlay,'orphan_disposition_sha256':cli.sha(self.root/overlay),'prior_journal_files':{}}
        for key,name in cli.INPUTS.items():self.write(name,receipt if key=='receipt' else {})
        starts=['scripts/score_frontier_v6m.py','retrace/frontier_v6m_eval.py','retrace/recovery_v6m.py','scripts/audit_frontier_v6m_runtime.py']
        for name in starts:self.write(name,b'# invented dependency\n')
        files=[{'path':n,**cli.binding(self.root/n)} for n in set(cli.INPUTS.values())|set(starts)]
        self.write(cli.FREEZE,{'schema':'retrace.frontier-v6m-freeze.v1','scheduled_slots':1800,'carried_final_slots':1246,
            'carried_issued_slots':1167,'continuation_slots':554,'files':files})
        self.write(cli.SNAPSHOT,b'{"new_closed_ledger":true}\n')
        merged={'requests':[],'responses':[],'outcomes':[],'source_provenance':{r:[] for r in ('requests','responses','outcomes')}}
        bindings={}
        for role,path in cli.role_paths().items():
            if role in ('requests','responses','outcomes'):
                row={'slot_id':'invented','attempt_id':'invented-attempt','kind':role}
                raw=('  '+json.dumps(row)+' \r\n').encode();self.write(path,raw)
                merged[role].append(row);merged['source_provenance'][role].append({'source_path':path,
                    'source_line_one_based':1,'source_file_sha256':sha256(raw).hexdigest(),'source_line_sha256':sha256(raw).hexdigest()})
            else:self.write(path,{'role':role})
            bindings[path]=cli.binding(self.root/path)
        for path in (overlay,recovery.BASELINE_LEDGER):bindings[path]=cli.binding(self.root/path)
        bindings[cli.LEDGER]=cli.binding(self.root/cli.SNAPSHOT)
        self.audit={'passed':True,'final_closed':True,'schedule_status':'stopped' if diagnostic else 'completed',
            'budget_cap_credits':'750','recovery_prefix_proof':prefix,'input_bindings':bindings}
        self.write(cli.AUDIT,self.audit)
        self.result={'summary':{'status':cli.PARTIAL if diagnostic else cli.COMPLETE,'planned_slots':1800,
            'frozen_diagnostic':{'schedule_complete':False},'amended_recovered_complete':None if diagnostic else {'status':'sensitivity'},
            'operational_summary':{'status':'invented-only'}},'audits':[],'merged_evidence':merged}
        self.args=(self.root,cli.sha(self.root/cli.FREEZE),cli.sha(self.root/cli.PREFIX_PROOF),cli.sha(self.root/cli.AUDIT),
            cli.SNAPSHOT,cli.sha(self.root/cli.SNAPSHOT));self.diagnostic=diagnostic
    def compute(self,**kwargs):
        with patch.object(cli,'audit_runtime',return_value=deepcopy(self.audit)),patch.object(cli,'evaluate_recovered',return_value=deepcopy(self.result)):
            return cli.compute(*self.args,diagnostic=kwargs.get('diagnostic',self.diagnostic))

    def test_exact_raw_bytes_and_separate_overlay_bindings(self):
        self.fixture();result,views=self.compute()
        for role,path in cli.role_paths().items():
            if role in views:self.assertEqual(views[role],(self.root/path).read_bytes())
        self.assertIn('results/frontier-v6m-recovery/orphan-dispositions.jsonl',result['summary']['file_evidence']['source_files'])
        self.assertFalse((self.root/cli.OUTPUT).exists())

    def test_active_worker_blocks_before_runtime_replay(self):
        self.fixture();self.write(cli.LOCK,b'')
        with patch.object(cli,'audit_runtime') as run:
            with self.assertRaisesRegex(ValueError,'active'):self.compute()
            run.assert_not_called()

    def test_proof_and_audit_hashes_must_match(self):
        self.fixture()
        for position in (2,3):
            args=list(self.args);args[position]='0'*64
            with self.assertRaises(ValueError):cli.compute(*args)

    def test_saved_replayed_proof_cannot_differ(self):
        self.fixture();self.audit['recovery_prefix_proof']['final_closed']=True
        with self.assertRaisesRegex(ValueError,'replay equality'):self.compute()

    def test_stopped_cannot_use_complete_branch(self):
        self.fixture(diagnostic=True)
        with self.assertRaisesRegex(ValueError,'final branch'):self.compute(diagnostic=False)

    def test_late_source_mutation_detected(self):
        self.fixture();path=cli.role_paths()['requests']
        def mutate(*args,**kwargs):self.write(path,b'{"changed":true}\n');return deepcopy(self.result)
        with patch.object(cli,'audit_runtime',return_value=deepcopy(self.audit)),patch.object(cli,'evaluate_recovered',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'source file changed'):cli.compute(*self.args)

    def test_publication_exclusive_and_preserves_original_bytes(self):
        self.fixture();result,views=self.compute();before=(self.root/cli.role_paths()['responses']).read_bytes()
        cli.write_outputs(self.root,result,views)
        self.assertEqual((self.root/cli.OUTPUT/'responses.jsonl').read_bytes(),before)
        with self.assertRaisesRegex(ValueError,'exclusive'):cli.write_outputs(self.root,result,views)

    def test_wrong_alias_and_mutated_frozen_dependency_reject(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError,'alias'):cli.verify_inventory(self.root,self.args[1],{'wrong':'path'})
        self.write('retrace/recovery_v6m.py',b'changed')
        with self.assertRaisesRegex(ValueError,'frozen dependency'):self.compute()


if __name__=='__main__':unittest.main()
