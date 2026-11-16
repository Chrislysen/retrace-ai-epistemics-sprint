"""Invented four-segment final artifacts, with no live study data or API."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import analyze_frontier_v6l_trajectory as t
from scripts import analyze_frontier_v6l_refuter_partitions as r
from tests.test_frontier_v6j_trajectory import fixture as tf,graph
from tests.test_frontier_v6j_refuter_partitions import fixture as rf
from retrace.typed_interventions_v6h import restore_then_withdraw_impact


def saved(root,kind='trajectory',diagnostic=False):
    corpus,study,audits=tf(count=12) if kind=='trajectory' else rf(60,5)
    snapshot='data/fixture-l-ledger.jsonl';stream='results/frontier-v6l/continuation/streams/fixture.jsonl'
    writer='scripts/score_frontier_v6l.py'
    for name,obj in ((t.INPUTS['corpus'],corpus),(t.INPUTS['study'],study),(snapshot,{'ledger':'fixture'}),(stream,{'SSE':'fixture'}),(writer,{'writer':'fixture'})):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj),encoding='utf-8')
    sources={n:t.binding(root/n) for n in (t.INPUTS['corpus'],t.INPUTS['study'],snapshot)}
    runtime={stream:t.binding(root/stream),'results/frontier-v6l/budget/ledger.jsonl':sources[snapshot],writer:t.binding(root/writer)}
    evidence={'execution_freeze':{'path':'data/fixture-l-freeze.json','sha256':'fixture'},'source_files':sources,
        'runtime_input_bindings':runtime,'runtime_audits_replayed':True,'runtime_input_bindings_rechecked_after_score':True,
        'frozen_aliases':{},'ledger_snapshot':{'path':snapshot,'sha256':sources[snapshot]['sha256']},'scope':'inventedfixture'}
    a=graph();a['evidence'].append({'id':'B','kind':'root','active':True,'parents':[]});b=deepcopy(a)
    b['claims'][0]['positive']={'all':[{'ref':'A'},{'ref':'B'}]}
    witness=restore_then_withdraw_impact([a],[b],document_groups=[{'id':'paper','evidence_ids':['A']}],revoked_documents=['paper'])
    amendment={'carried_final_slots':700,'carried_issued_slots':600,'carried_dependency_failed_slots':100,
        'retained_by_segment':{'i':6,'j':218,'k':476},'continuation_planned_slots':1100}
    status='interrupted_amended_diagnostic' if diagnostic else 'complete_amended_primary'
    result={'summary':{'status':status,'operational_summary':{'status':'stopped' if diagnostic else 'completed','fixture_witness':witness},
        'file_evidence':evidence,'amendment':amendment},'audits':audits,
        'merged_evidence':{'source_provenance':{'fixture_witness':witness},'source_bindings':{'fixture':'four segments'}}}
    views={role:(' '+json.dumps({'fixture':role})+'\r\n').encode() for role in ('requests','responses','outcomes')}
    output=t.PARTIAL_OUTPUT if diagnostic else t.OUTPUT;directory=root/output;directory.mkdir(parents=True)
    encode=lambda obj:(json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode()
    closure='interrupted-closure.json' if diagnostic else 'derived-closure.json'
    payloads={'score.json':encode(result['summary']),'score-audits.json':encode(audits),
        'source-provenance.json':encode(result['merged_evidence']['source_provenance']),closure:encode(result['summary']['operational_summary']),
        **{name:views[role] for role,name in (('requests','requests.jsonl'),('responses','responses.jsonl'),('outcomes','slot-outcomes.jsonl'))}}
    for name,raw in payloads.items():(directory/name).write_bytes(raw)
    manifest={'schema':'retrace.frontier-v6l-'+('partial' if diagnostic else 'composite')+'-artifacts.v1',
        'status':status,'planned_slots':1800,'schedule_complete':not diagnostic,'inference_available':not diagnostic,
        **{k:v for k,v in amendment.items() if k!='continuation_planned_slots'},'continuation_slots':1100,
        'files':{output+'/'+n:t.binding(directory/n) for n in payloads},'file_evidence':evidence,
        'source_bindings':result['merged_evidence']['source_bindings'],'source_rows_changed':False,
        'selected_jsonl_source_bytes_preserved':True}
    manifest['writer_sha256']=runtime[writer]['sha256']
    (directory/('partial-manifest.json' if diagnostic else 'composite-manifest.json')).write_bytes(encode(manifest))
    return result,views,snapshot,stream


class DescriptiveTests(unittest.TestCase):
    def test_full_denominators_and_all_four_audits_propagate(self):
        for kind,module in (('trajectory',t),('refuter',r)):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);result,views,snapshot,stream=saved(root,kind)
                with patch.object(t,'compute',return_value=(result,views)) as compute:
                    value=module.run(root,'f','i','j','k','l',snapshot,'s')
                compute.assert_called_once_with(root,'f','i','j','k','l',snapshot,'s',frozen_aliases={})
                self.assertEqual(len(value['authenticated_input_bindings']),8)
                self.assertIn(stream,value['authenticated_source_bindings'])
                self.assertEqual(value['planned_cases'],12 if kind=='trajectory' else 60)
                self.assertEqual(len(value['trajectories']) if kind=='trajectory' else len(value['rows']),24 if kind=='trajectory' else 600)

    def test_live_and_missing_final_fail_before_compute(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(t,'compute') as compute:
            root=Path(temp);p=root/'results/frontier-v6l/budget/active.lock';p.parent.mkdir(parents=True);p.write_text('active')
            with self.assertRaisesRegex(ValueError,'live'):t.authenticated_inputs(root,'f','i','j','k','l','s','s')
            p.unlink()
            with self.assertRaisesRegex(ValueError,'saved authenticated'):t.authenticated_inputs(root,'f','i','j','k','l','s','s')
            compute.assert_not_called()

    def test_explicit_partial_branch_cannot_be_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);result,views,snapshot,_=saved(root,diagnostic=True)
            self.assertEqual(len(t.verify_saved(root,result,views,aliases={},ledger_snapshot=snapshot,diagnostic=True)),8)
            with self.assertRaises(FileNotFoundError):t.verify_saved(root,result,views,aliases={},ledger_snapshot=snapshot)
            mp=root/t.PARTIAL_OUTPUT/'partial-manifest.json';m=json.loads(mp.read_text());m['inference_available']=True;mp.write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'four-segment cohort'):t.verify_saved(root,result,views,aliases={},ledger_snapshot=snapshot,diagnostic=True)

    def test_tuple_projection_does_not_normalize_raw_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);result,views,snapshot,_=saved(root)
            self.assertIsInstance(result['summary']['operational_summary']['fixture_witness']['witnesses'][0]['baseline'],tuple)
            t.verify_saved(root,result,views,aliases={},ledger_snapshot=snapshot)
            bad=dict(views);bad['requests']=json.dumps(json.loads(views['requests'])).encode()+b'\n'
            with self.assertRaisesRegex(ValueError,'raw-byte'):t.verify_saved(root,result,bad,aliases={},ledger_snapshot=snapshot)

    def test_rehashed_score_or_proof_mutation_does_not_pass_replay(self):
        for field in ('audit','evidence'):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);result,views,snapshot,_=saved(root,'refuter')
                filename='score-audits.json' if field=='audit' else 'score.json';p=root/t.OUTPUT/filename
                obj=json.loads(p.read_text())
                if field=='audit':obj[0]['correct']=not obj[0]['correct']
                else:obj['file_evidence']['scope']='alteredclaim'
                p.write_text(json.dumps(obj));mp=root/t.OUTPUT/'composite-manifest.json';m=json.loads(mp.read_text())
                m['files'][t.OUTPUT+'/'+filename]=t.binding(p)
                if field=='evidence':m['file_evidence']=obj['file_evidence']
                mp.write_text(json.dumps(m))
                with self.assertRaisesRegex(ValueError,'differs from replay|full evidence differ'):t.verify_saved(root,result,views,aliases={},ledger_snapshot=snapshot)

    def test_changed_raw_stream_blocks_after_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);result,views,snapshot,stream=saved(root);real=t.analyze_trajectories
            def mutate(*args):
                value=real(*args);(root/stream).write_text('{}');return value
            with patch.object(t,'compute',return_value=(result,views)),patch.object(t,'analyze_trajectories',side_effect=mutate):
                with self.assertRaisesRegex(ValueError,'source evidence changed'):t.run(root,'f','i','j','k','l',snapshot,'s')

    def test_relocated_identical_snapshot_normalization_is_only_path_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);result,views,snapshot,_=saved(root);new='data/relocated-identical-ledger.jsonl'
            (root/new).write_bytes((root/snapshot).read_bytes());replay=deepcopy(result);ev=replay['summary']['file_evidence']
            ev['source_files'][new]=ev['source_files'].pop(snapshot);ev['ledger_snapshot']['path']=new
            t.verify_saved(root,replay,views,aliases={},ledger_snapshot=new)
            ev['runtime_input_bindings']={}
            with self.assertRaisesRegex(ValueError,'writer differs|full evidence differ'):t.verify_saved(root,replay,views,aliases={},ledger_snapshot=new)

    def test_rehashed_manifest_writer_or_replay_branch_cannot_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);result,views,snapshot,_=saved(root)
            mp=root/t.OUTPUT/'composite-manifest.json';m=json.loads(mp.read_text());m['writer_sha256']='a'*64;mp.write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'writer differs'):t.verify_saved(root,result,views,aliases={},ledger_snapshot=snapshot)
            result['summary']['status']='interrupted_amended_diagnostic'
            with self.assertRaisesRegex(ValueError,'explicit final l branch'):t.verify_saved(root,result,views,aliases={},ledger_snapshot=snapshot)


if __name__=='__main__':unittest.main()
