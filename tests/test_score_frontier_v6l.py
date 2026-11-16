"""Synthetic authentication/publication fixtures; no empirical score inputs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import score_frontier_v6l as cli
from retrace.frontier_v6l_eval import ROUTE


class FourSegmentCliTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def write(self,name,value):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(value if isinstance(value,bytes) else (json.dumps(value)+'\n').encode());return path

    def fixture(self,diagnostic=False):
        receipt={'schema':'retrace.frontier-v6l-continuation.v1','full_planned_slots':1800,
            'previous_cumulative_cap_credits':'250','cumulative_cap_credits':'750',
            'carried_final_slots':241,'carried_issued_slots':230,'continuation_slots':1559,
            'historical_conservative_carry_credits':'249.25','observed_response_models':ROUTE,'prior_journal_files':{}}
        for name in cli.INPUTS.values():self.write(name,receipt if name==cli.INPUTS['receipt'] else {})
        starts=['scripts/score_frontier_v6l.py','retrace/frontier_v6l_eval.py','scripts/audit_frontier_v6l_runtime.py']
        for name in starts:self.write(name,b'# invented dependency\n')
        lock,alias=next(iter(cli.ALIASES.items()));self.write(alias,b'old inert bytes\n')
        files=[{'path':name,**cli.binding(self.root/name)} for name in set(cli.INPUTS.values())|set(starts)]
        files.append({'path':lock,**cli.binding(self.root/alias)})
        self.write(cli.FREEZE,{'schema':'retrace.frontier-v6l-freeze.v1','scheduled_slots':1800,
            'carried_final_slots':241,'carried_issued_slots':230,'continuation_slots':1559,'files':files})
        self.snapshot='data/invented-l-snapshot.jsonl';self.write(self.snapshot,b'{"invented_ledger":true}\n')
        merged={'requests':[],'responses':[],'outcomes':[],'source_provenance':{r:[] for r in ('requests','responses','outcomes')},'source_bindings':{}}
        bindings={};segments={}
        for name in cli.SEGMENTS:
            for role,path in cli.role_paths(name).items():
                if role in ('requests','responses','outcomes'):
                    row={'slot_id':name+'-slot','attempt_id':name+'-attempt','kind':role}
                    data=(' '+json.dumps(row)+' \r\n').encode();self.write(path,data)
                    merged[role].append(row);merged['source_provenance'][role].append({'segment':name,'source_path':path,
                        'source_line_one_based':1,'source_file_sha256':hashlib.sha256(data).hexdigest(),
                        'source_line_sha256':hashlib.sha256(data).hexdigest()})
                else:self.write(path,{'run_id':'invented-'+name,'role':role})
                bindings[path]=cli.binding(self.root/path);merged['source_bindings'][path]=bindings[path]
            segments[name]=cli.segment(self.root,name)
        bindings[cli.LEDGER]=cli.binding(self.root/self.snapshot)
        self.audits={n:{'fixture':n,'passed':True,'schedule_status':'stopped'} for n in cli.HISTORICAL}
        self.audits['l']={'passed':True,'final_closed':True,'all_scheduled_outcomes_accounted':True,
            'schedule_status':'stopped' if diagnostic else 'completed','budget_cap_credits':'750',
            'prior_segment_audits':deepcopy(self.audits),'input_bindings':bindings}
        for name,value in self.audits.items():self.write(cli.AUDITS[name],value)
        summary={'status':cli.PARTIAL if diagnostic else cli.COMPLETE,'schedule_complete':not diagnostic,
            'planned_slots':1800,'primary_holm_family_size':21,'cluster_intervals':[],
            'paired_comparisons':[{'primary_family_member':True,'view':'first_attempt',
                'p_two_sided_exact':None,'holm_adjusted_p':None} for _ in range(21)],
            'operational_summary':{'schema':'invented-closure','typed_tuple':(False,True)},
            'amendment':{'carried_final_slots':241,'carried_issued_slots':230,'carried_dependency_failed_slots':11,
                'retained_by_segment':{'i':6,'j':218,'k':17},'continuation_planned_slots':1559}}
        self.result={'summary':summary,'audits':[{'invented_only':True}],'merged_evidence':merged}
        self.args=(self.root,cli.sha(self.root/cli.FREEZE),*[cli.sha(self.root/cli.AUDITS[n]) for n in cli.SEGMENTS],
                   self.snapshot,cli.sha(self.root/self.snapshot))
        self.diagnostic=diagnostic;return segments

    def compute(self,**kwargs):
        with patch.object(cli,'audit_runtime',return_value=deepcopy(self.audits['l'])), \
             patch.object(cli,'evaluate_composite',return_value=deepcopy(self.result)):
            return cli.compute(*self.args,frozen_aliases=cli.ALIASES,diagnostic=kwargs.get('diagnostic',self.diagnostic))

    def test_four_audits_twenty_roles_raw_views_and_json_projection(self):
        segments=self.fixture();result,views=self.compute()
        self.assertEqual(result['summary']['operational_summary']['typed_tuple'],[False,True])
        for role in ('requests','responses','outcomes'):
            self.assertEqual(views[role],b''.join(segments[n][role] for n in cli.SEGMENTS))
        self.assertEqual(len(result['merged_evidence']['source_bindings']),20)
        self.assertFalse((self.root/cli.OUTPUT).exists())

    def test_every_saved_audit_hash_nested_proof_and_new_cap_required(self):
        self.fixture()
        for position in (2,3,4,5):
            args=list(self.args);args[position]='0'*64
            with self.assertRaisesRegex(ValueError,'saved_runtime_audit_hash'):cli.compute(*args,frozen_aliases=cli.ALIASES)
        changed=deepcopy(self.audits['l']);changed['prior_segment_audits']['k']['passed']=False
        with patch.object(cli,'audit_runtime',return_value=changed),self.assertRaisesRegex(ValueError,'do_not_reproduce'):
            cli.compute(*self.args,frozen_aliases=cli.ALIASES)
        self.audits['l']['budget_cap_credits']='250';self.write(cli.AUDITS['l'],self.audits['l'])
        args=list(self.args);args[5]=cli.sha(self.root/cli.AUDITS['l']);self.args=tuple(args)
        with self.assertRaisesRegex(ValueError,'750_audit'):self.compute()

    def test_active_and_wrong_branch_reject_before_scoring(self):
        self.fixture(diagnostic=True)
        with self.assertRaisesRegex(ValueError,'branch_required'):self.compute(diagnostic=False)
        self.write(cli.LOCK,b'live')
        with patch.object(cli,'audit_runtime') as audit,self.assertRaisesRegex(ValueError,'still_active'):
            cli.compute(*self.args,frozen_aliases=cli.ALIASES,diagnostic=True)
        audit.assert_not_called()

    def test_snapshot_changed_source_or_dependency_inventory_fail_closed(self):
        self.fixture();args=list(self.args);args[6]=cli.LEDGER
        with self.assertRaisesRegex(ValueError,'immutable_ledger'):cli.compute(*args,frozen_aliases=cli.ALIASES)
        self.write(cli.role_paths('k')['responses'],b'{"tampered":true}\n')
        with self.assertRaisesRegex(ValueError,'runtime_bindings_differ'):self.compute()
        with self.assertRaisesRegex(ValueError,'unsupported_frozen_alias'):
            cli.verify_inventory(self.root,self.args[1],{'unknown':'other'})

    def test_late_historical_sse_change_rejects(self):
        self.fixture();name='results/frontier-v6k/continuation/streams/invented.sse';self.write(name,b'original stream')
        self.audits['l']['input_bindings'][name]=cli.binding(self.root/name);self.write(cli.AUDITS['l'],self.audits['l'])
        args=list(self.args);args[5]=cli.sha(self.root/cli.AUDITS['l'])
        def evaluate(*_args,**_kwargs):self.write(name,b'changed stream');return deepcopy(self.result)
        with patch.object(cli,'audit_runtime',return_value=self.audits['l']),patch.object(cli,'evaluate_composite',side_effect=evaluate):
            with self.assertRaisesRegex(ValueError,'runtime_evidence_changed'):
                cli.compute(*args,frozen_aliases=cli.ALIASES)

    def test_separate_exclusive_complete_and_interrupted_publication(self):
        for diagnostic in (False,True):
            with self.subTest(diagnostic=diagnostic):
                self.fixture(diagnostic);result,views=self.compute()
                manifest=cli.write_outputs(self.root,result,views,diagnostic=diagnostic)
                self.assertEqual(len(manifest['files']),7)
                self.assertEqual(manifest['retained_by_segment'],{'i':6,'j':218,'k':17})
                self.assertEqual(manifest['inference_available'],not diagnostic)
                self.assertEqual(manifest['status'],cli.PARTIAL if diagnostic else cli.COMPLETE)
                for name,value in manifest['files'].items():self.assertEqual(cli.binding(self.root/name),value)
                with self.assertRaisesRegex(ValueError,'already_exists'):cli.write_outputs(self.root,result,views,diagnostic=diagnostic)
                with self.assertRaises(ValueError):cli.write_outputs(self.root,result,views,diagnostic=not diagnostic)

    def test_post_compute_evidence_mutation_prevents_publication(self):
        self.fixture();result,views=self.compute();self.write(cli.role_paths('i')['responses'],b'changed old bytes')
        with self.assertRaisesRegex(ValueError,'source_changed'):cli.write_outputs(self.root,result,views)
        self.assertFalse((self.root/cli.OUTPUT).exists())

    def test_partial_publication_never_accepts_pvalues_or_vacuous_primary_family(self):
        self.fixture(diagnostic=True);result,views=self.compute()
        for mode in ('pvalue','missing'):
            changed=deepcopy(result)
            if mode=='pvalue':changed['summary']['paired_comparisons'][0]['p_two_sided_exact']=0.01
            else:changed['summary']['paired_comparisons']=[]
            with self.subTest(mode=mode),self.assertRaisesRegex(ValueError,'diagnostic_only'):
                cli.write_outputs(self.root,changed,views,diagnostic=True)


if __name__=='__main__':unittest.main()
