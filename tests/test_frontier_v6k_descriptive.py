"""Three-segment descriptive wrappers; invented data and mocked final replay only."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import analyze_frontier_v6k_trajectory as trajectory
from scripts import analyze_frontier_v6k_refuter_partitions as refuter
from scripts.score_frontier_v6k import write_outputs
from tests.test_frontier_v6j_trajectory import fixture as trajectory_fixture,graph
from tests.test_frontier_v6j_refuter_partitions import fixture as refuter_fixture
from retrace.typed_interventions_v6h import restore_then_withdraw_impact


def saved(root,kind):
    corpus,study,audits=trajectory_fixture(count=12) if kind=='trajectory' else refuter_fixture(60,5)
    snapshot='data/fixture-k-ledger.jsonl'
    for name,value in ((trajectory.INPUTS['corpus'],corpus),(trajectory.INPUTS['study'],study),(snapshot,{'ledger':'fixture'})):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
    sources={name:trajectory.binding(root/name) for name in (trajectory.INPUTS['corpus'],trajectory.INPUTS['study'],snapshot)}
    evidence={'execution_freeze':{'path':'data/fixture-k-freeze.json','sha256':'fixture'},'source_files':sources,
        'runtime_audits_replayed':True,'runtime_input_bindings_rechecked_after_score':True,'frozen_aliases':{},
        'ledger_snapshot':{'path':snapshot,'sha256':sources[snapshot]['sha256']}}
    a=graph();a['evidence'].append({'id':'B','kind':'root','active':True,'parents':[]});b=deepcopy(a);b['claims'][0]['positive']={'all':[{'ref':'A'},{'ref':'B'}]}
    witness=restore_then_withdraw_impact([a],[b],document_groups=[{'id':'paper','evidence_ids':['A']}],revoked_documents=['paper'])
    result={'summary':{'status':'complete_amended_primary','operational_summary':{'status':'completed','fixture_witness':witness},'file_evidence':evidence},
        'audits':audits,'merged_evidence':{'source_provenance':{'fixture_witness':witness},'source_bindings':{'fixture':'three segments'}}}
    views={role:(' '+json.dumps({'fixture':role})+'\r\n').encode() for role in ('requests','responses','outcomes')}
    write_outputs(root,result,views);return result,views,snapshot


class DescriptiveKTests(unittest.TestCase):
    def test_both_wrappers_use_unchanged_full_denominators(self):
        for name,module in (('trajectory',trajectory),('refuter',refuter)):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);result,views,snapshot=saved(root,name)
                with patch.object(trajectory,'compute',return_value=(result,views)) as compute:
                    value=module.run(root,'f','i','j','k',snapshot,'s')
                compute.assert_called_once_with(root,'f','i','j','k',snapshot,'s',frozen_aliases={})
                self.assertIn('v6k',value['schema']);self.assertIn('v6j',value['pure_analysis_schema']);self.assertEqual(len(value['authenticated_input_bindings']),8)
                self.assertEqual(value['planned_cases'],12 if name=='trajectory' else 60)
                self.assertEqual(len(value['trajectories']) if name=='trajectory' else len(value['rows']),24 if name=='trajectory' else 600)
    def test_live_and_missing_final_refused_before_compute(self):
        for module in (trajectory,refuter):
            with tempfile.TemporaryDirectory() as temp,patch.object(trajectory,'compute') as compute:
                root=Path(temp);lock=root/'results/frontier-v6k/budget/active.lock';lock.parent.mkdir(parents=True);lock.write_text('live')
                with self.assertRaisesRegex(ValueError,'live'):module.run(root,'f','i','j','k','snapshot','s')
                lock.unlink()
                with self.assertRaisesRegex(ValueError,'saved authenticated'):module.run(root,'f','i','j','k','snapshot','s')
                compute.assert_not_called()
    def test_old_two_segment_manifest_cannot_authorize_new_wrappers(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);result,views,snapshot=saved(root,'trajectory');path=root/trajectory.OUTPUT/'composite-manifest.json'
            manifest=json.loads(path.read_text());manifest['schema']='retrace.frontier-v6j-composite-artifacts.v1';path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'final complete k'):trajectory.verify_saved(root,result,views,aliases={},ledger_snapshot=snapshot)
    def test_tuples_project_to_arrays_but_raw_bytes_do_not_normalize(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);result,views,snapshot=saved(root,'trajectory');self.assertIsInstance(result['summary']['operational_summary']['fixture_witness']['witnesses'][0]['baseline'],tuple)
            trajectory.verify_saved(root,result,views,aliases={},ledger_snapshot=snapshot)
            altered=dict(views);altered['requests']=json.dumps(json.loads(views['requests'])).encode()+b'\n'
            with self.assertRaisesRegex(ValueError,'raw-byte'):trajectory.verify_saved(root,result,altered,aliases={},ledger_snapshot=snapshot)
    def test_rehashed_audit_change_still_fails_exact_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);result,views,snapshot=saved(root,'refuter');path=root/trajectory.OUTPUT/'score-audits.json'
            changed=deepcopy(result['audits']);changed[0]['correct']=not changed[0]['correct'];path.write_text(json.dumps(changed))
            mp=root/trajectory.OUTPUT/'composite-manifest.json';manifest=json.loads(mp.read_text());manifest['files'][trajectory.OUTPUT+'/score-audits.json']=trajectory.binding(path);mp.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'differs from replay'):trajectory.verify_saved(root,result,views,aliases={},ledger_snapshot=snapshot)
    def test_post_analysis_source_mutation_cannot_emit_result(self):
        for name,module,function in (('trajectory',trajectory,'analyze_trajectories'),('refuter',refuter,'analyze_refuter_partitions')):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);result,views,snapshot=saved(root,name);real=getattr(module,function)
                def mutate(*args,**kwargs):
                    value=real(*args,**kwargs);(root/trajectory.INPUTS['study']).write_text('{}');return value
                with patch.object(trajectory,'compute',return_value=(result,views)),patch.object(module,function,side_effect=mutate):
                    with self.assertRaisesRegex(ValueError,'source evidence changed'):module.run(root,'f','i','j','k',snapshot,'s')

if __name__=='__main__':unittest.main()
