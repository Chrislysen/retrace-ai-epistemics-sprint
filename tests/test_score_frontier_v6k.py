"""Isolated CLI authentication fixtures; runtime and scientific replay are mocked."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import score_frontier_v6k as cli


class ThreeSegmentCliTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def write(self,name,value):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value if isinstance(value,bytes) else (json.dumps(value)+'\n').encode());return path
    def fixture(self):
        for name in cli.INPUTS.values():self.write(name,{'prior_journal_files':{}} if name==cli.INPUTS['receipt'] else {})
        starts=['scripts/score_frontier_v6k.py','retrace/frontier_v6k_eval.py','scripts/audit_frontier_v6k_runtime.py']
        for name in starts:self.write(name,b'# isolated dependency fixture\n')
        lock,alias=next(iter(cli.ALIASES.items()));self.write(alias,b'old inert original bytes\n')
        files=[{'path':name,**cli.binding(self.root/name)} for name in set(cli.INPUTS.values())|set(starts)]+[{'path':lock,**cli.binding(self.root/alias)}]
        self.write(cli.FREEZE,{'schema':'retrace.frontier-v6k-freeze.v1','scheduled_slots':1800,'continuation_slots':1576,'carried_final_slots':224,'carried_issued_slots':213,'files':files})
        self.snapshot='data/immutable-k-ledger.jsonl';self.write(self.snapshot,b'{"fixture_ledger":true}\n')
        bindings={};segments={};merged={'requests':[],'responses':[],'outcomes':[],'source_provenance':{role:[] for role in ('requests','responses','outcomes')},'source_bindings':{}}
        for name in cli.SEGMENTS:
            for role,path in cli.role_paths(name).items():
                if role in ('requests','responses','outcomes'):
                    row={'slot_id':name+'-slot','attempt_id':name+'-attempt','kind':role};line=(' '+json.dumps(row)+' \r\n').encode();self.write(path,line)
                    merged[role].append(row);merged['source_provenance'][role].append({'segment':name,'source_path':path,'source_line_one_based':1,
                        'source_file_sha256':hashlib.sha256(line).hexdigest(),'source_line_sha256':hashlib.sha256(line).hexdigest()})
                else:self.write(path,{'run_id':name,'role':role})
                bindings[path]=cli.binding(self.root/path);merged['source_bindings'][path]=bindings[path]
            segments[name]=cli.segment(self.root,name)
        bindings[cli.LEDGER]=cli.binding(self.root/self.snapshot)
        self.audits={'i':{'fixture':'i','passed':True,'schedule_status':'stopped'},'j':{'fixture':'j','passed':True,'schedule_status':'stopped'}}
        self.audits['k']={'passed':True,'final_closed':True,'all_scheduled_outcomes_accounted':True,'schedule_status':'completed','prior_segment_audits':deepcopy(self.audits),'input_bindings':bindings}
        for name,value in self.audits.items():self.write(cli.AUDITS[name],value)
        self.result={'summary':{'status':'complete_amended_primary','primary_holm_family_size':21,'operational_summary':{'schema':'derived-fixture','tuple':(False,True)}},
            'audits':[{'fixture_only':True}],'merged_evidence':merged}
        self.args=(self.root,cli.sha(self.root/cli.FREEZE),*[cli.sha(self.root/cli.AUDITS[name]) for name in cli.SEGMENTS],self.snapshot,cli.sha(self.root/self.snapshot))
        return segments
    def compute(self):
        with patch.object(cli,'audit_runtime',return_value=deepcopy(self.audits['k'])),patch.object(cli,'evaluate_composite',return_value=deepcopy(self.result)):
            return cli.compute(*self.args,frozen_aliases=cli.ALIASES)
    def test_three_closed_proofs_exact_bytes_and_json_projection(self):
        segments=self.fixture();result,views=self.compute()
        for role in ('requests','responses','outcomes'):self.assertEqual(views[role],b''.join(segments[name][role] for name in cli.SEGMENTS))
        self.assertEqual(result['summary']['operational_summary']['tuple'],[False,True]);self.assertTrue(result['summary']['file_evidence']['runtime_audits_replayed'])
        self.assertFalse((self.root/'results/frontier-v6f/budget/active.lock').exists());self.assertFalse((self.root/cli.OUTPUT).exists())
    def test_all_three_audit_hashes_and_replayed_nested_proofs_required(self):
        self.fixture()
        for number in (2,3,4):
            args=list(self.args);args[number]='f'*64
            with self.assertRaisesRegex(ValueError,'saved_runtime_audit_hash'):cli.compute(*args,frozen_aliases=cli.ALIASES)
        bad=deepcopy(self.audits['k']);bad['prior_segment_audits']['j']['passed']=False
        with patch.object(cli,'audit_runtime',return_value=bad):
            with self.assertRaisesRegex(ValueError,'do_not_reproduce'):cli.compute(*self.args,frozen_aliases=cli.ALIASES)
    def test_stopped_k_and_live_lock_refused(self):
        self.fixture();self.audits['k']['schedule_status']='stopped';self.write(cli.AUDITS['k'],self.audits['k']);args=list(self.args);args[4]=cli.sha(self.root/cli.AUDITS['k'])
        with patch.object(cli,'audit_runtime',return_value=self.audits['k']):
            with self.assertRaisesRegex(ValueError,'continuation_not_complete'):cli.compute(*args,frozen_aliases=cli.ALIASES)
        self.write('results/frontier-v6k/budget/active.lock',b'live')
        with patch.object(cli,'audit_runtime') as call:
            with self.assertRaisesRegex(ValueError,'still_active'):cli.compute(*args,frozen_aliases=cli.ALIASES)
            call.assert_not_called()
    def test_changed_any_segment_source_rejected_before_scoring(self):
        self.fixture();self.write(cli.role_paths('j')['responses'],b'{"changed":true}\n')
        with patch.object(cli,'audit_runtime',return_value=self.audits['k']),patch.object(cli,'evaluate_composite') as evaluate:
            with self.assertRaisesRegex(ValueError,'runtime_bindings_differ'):cli.compute(*self.args,frozen_aliases=cli.ALIASES)
            evaluate.assert_not_called()
    def test_late_old_stream_mutation_detected(self):
        self.fixture();name='results/frontier-v6j/continuation/streams/fixture.sse';self.write(name,b'old stream')
        self.audits['k']['input_bindings'][name]=cli.binding(self.root/name);self.write(cli.AUDITS['k'],self.audits['k']);args=list(self.args);args[4]=cli.sha(self.root/cli.AUDITS['k'])
        def evaluate(*_):self.write(name,b'changed');return deepcopy(self.result)
        with patch.object(cli,'audit_runtime',return_value=self.audits['k']),patch.object(cli,'evaluate_composite',side_effect=evaluate):
            with self.assertRaisesRegex(ValueError,'runtime_evidence_changed'):cli.compute(*args,frozen_aliases=cli.ALIASES)
        self.assertFalse((self.root/cli.OUTPUT).exists())
    def test_canonical_live_ledger_and_wrong_snapshot_hash_rejected(self):
        self.fixture();args=list(self.args);args[5]=cli.LEDGER
        with self.assertRaisesRegex(ValueError,'immutable_ledger'):cli.compute(*args,frozen_aliases=cli.ALIASES)
        args=list(self.args);args[6]='f'*64
        with self.assertRaisesRegex(ValueError,'snapshot_hash'):cli.compute(*args,frozen_aliases=cli.ALIASES)
    def test_missing_import_dependency_or_unknown_alias_rejected(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError,'unsupported_frozen_alias'):cli.verify_inventory(self.root,self.args[1],{'bad':'alias'})
        self.write('scripts/helper.py',b'pass\n');self.write('scripts/score_frontier_v6k.py',b'import scripts.helper\n')
        value=cli.strict((self.root/cli.FREEZE).read_bytes())
        for row in value['files']:
            if row['path']=='scripts/score_frontier_v6k.py':row.update(cli.binding(self.root/row['path']))
        self.write(cli.FREEZE,value)
        with self.assertRaisesRegex(ValueError,'missing_scientific_dependency'):cli.verify_inventory(self.root,cli.sha(self.root/cli.FREEZE),cli.ALIASES)
    def test_writer_manifest_exclusive_and_old_bytes_preserved(self):
        self.fixture();result,views=self.compute();old={name:(self.root/cli.role_paths(name)['responses']).read_bytes() for name in ('i','j')}
        manifest=cli.write_outputs(self.root,result,views)
        self.assertEqual(manifest['retained_by_segment'],{'i':6,'j':218});self.assertEqual(len(manifest['files']),7)
        for path,expected in manifest['files'].items():self.assertEqual(cli.binding(self.root/path),expected)
        for name,expected in old.items():self.assertEqual((self.root/cli.role_paths(name)['responses']).read_bytes(),expected)
        with self.assertRaisesRegex(ValueError,'already_exists'):cli.write_outputs(self.root,result,views)
    def test_changed_row_or_source_line_pointer_rejected(self):
        segments=self.fixture();merged=deepcopy(self.result['merged_evidence']);merged['outcomes'][1]['slot_id']='wrong'
        with self.assertRaisesRegex(ValueError,'changed_source_row'):cli.selected_source_lines(merged,segments,'outcomes')
        merged=deepcopy(self.result['merged_evidence']);merged['source_provenance']['outcomes'][1]['source_line_one_based']=0
        with self.assertRaisesRegex(ValueError,'source_line_index'):cli.selected_source_lines(merged,segments,'outcomes')

if __name__=='__main__':unittest.main()
