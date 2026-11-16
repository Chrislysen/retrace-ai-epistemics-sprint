"""Final corrected declared-choice reader probe; prior diagnostics remain unchanged.

The initial probes correctly rejected UNUSED axes. These now explicitly bind
every axis to an unused record's origin. No scientific inputs or engines change.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def workbench():
    from retrace.workbench_v6h import analyze_workbench,demo_brief
    from retrace.source_ir_v6d import source_segments
    brief=demo_brief();brief['source_documents'].append({'id':'latency-only','text':'Constructed latency probe. EXTRA0 and EXTRA1 are unused active records; each is independently declared either an original or copied from A. These distinctions have no decision role.'})
    span=source_segments(brief['source_documents'])[-1]['span_id'];ir=brief['source_ir']
    for i in range(2):
        eid='EXTRA'+str(i);axis='extra'+str(i);brief['registry']['evidence'].append(eid)
        ir['entities'].append({'id':eid,'type':'evidence','operational':True,'citations':[span]})
        ir['choices'].append({'id':axis,'options':['root','copy'],'citations':[span]})
        def add(kind,body,when):
            ir['propositions'].append({'id':kind+'-extra'+str(i)+'-'+str(len(ir['propositions'])),
                'kind':kind,'target':eid,'body':body,'scope':'current','when':when,'citations':[span],'bindings':[]})
        add('eligibility',{'active':True},{})
        add('origin',{'kind':'root','parents':[]},{axis:'root'})
        add('origin',{'kind':'copy','parents':['A']},{axis:'copy'})
    brief.pop('clarifications');brief['allowed_withdrawals']=['A','B','C','D','Z']
    value=analyze_workbench(brief);assert len(value['candidate_ids'])==32
    return {'candidate_count':32,'question_count':len(value['question_catalog']),
        'planner_states':value['planner']['states_evaluated'],'planner_worst_cost':value['planner']['worst_case_cost'],
        'mechanisms':{k:value[k]['status'] for k in ('robustness','hamming2','typed_veto_release')}}


def reader():
    from retrace.refuter_catalog_v6l import build_catalog,validate_entry
    from retrace.refuter_gate_v6h import validate_refuter
    from retrace.source_ir_v6d import source_segments,model_source
    from tests.test_refuter_catalog_v6l import fixture
    from tests.test_frontier_v6l_catalog import bind
    from tests.test_refuter_inspector_v6l import envelope,graph
    data=fixture();g=graph()
    for i in range(5):g['evidence'].append({'id':'EXTRA'+str(i),'kind':'root','active':True,'parents':[]})
    docs=[{'id':'constructed-probe','text':'A and B are active originals. C uses A and D requires C. EXTRA0, EXTRA1, EXTRA2, EXTRA3 and EXTRA4 are unused active records, each independently either an original or a copy of A. This is a constructed mechanics probe, not external evidence.'}]
    reg={'evidence':[r['id'] for r in g['evidence']],'claims':['C'],'decisions':['D']}
    seed=[]
    for bits in range(32):
        new=deepcopy(g)
        for i,row in enumerate(new['evidence'][2:]):
            if bits&(1<<i):row.update(kind='copy',parents=['A'])
        seed.append({'id':'seed'+str(bits),'graph':new})
    data[0]['cases'][0]['public']={'source_documents':docs,'registry':reg}
    packet={**model_source(docs,reg),'supplied_candidates':seed}
    data[2][0]['input']=json.dumps(packet);data[4]['requests'][0]['request']['input'][-1]['content']=data[2][0]['input']
    proposed=envelope(g);span=source_segments(docs)[0]['span_id'];ir=proposed['ir'];proposed['objection_spans']=[span];ir['combination']['citations']=[span]
    for row in ir['entities']+ir['propositions']:row['citations']=[span]
    ir['propositions']=[p for p in ir['propositions'] if not(p['kind']=='origin' and p['target'].startswith('EXTRA'))]
    for i in range(5):
        axis='axis'+str(i);ir['choices'].append({'id':axis,'options':['root','copy'],'citations':[span]})
        for option in ('root','copy'):
            ir['propositions'].append({'id':axis+'-'+option,'kind':'origin','target':'EXTRA'+str(i),
                'body':{'kind':option,'parents':['A'] if option=='copy' else []},
                'scope':'current','when':{axis:option},'citations':[span],'bindings':[]})
    raw=json.dumps(proposed)
    for row in data[4]['responses']+data[4]['outcomes']:row['output_text']=raw
    data[3][0]['refuter_gate']=validate_refuter(raw,docs,reg);bind(data[4])
    before=perf_counter();built=build_catalog(*data,require_full_design=False);setup=perf_counter()-before
    value=next(iter(built['entries'].values()));before=perf_counter();validate_entry(value);elapsed=perf_counter()-before
    assert value['inspection']['gate']['candidate_count']==32
    return {'seed_candidates':32,'proposal_candidates':32,'validate_entry_seconds':elapsed,
        'catalog_projection_setup_seconds':setup,'mechanisms':{k:value['inspection']['preview'][k]['status'] for k in ('modal_summary','decision_impact','hamming2')},
        'scope':'This is the raw/gate/preview revalidation invoked by each reader entry GET under its lock. No catalog or HTTP server created.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',choices=('workbench32','reader32'));p.add_argument('--output',type=Path);a=p.parse_args()
    if a.case:
        before=perf_counter()
        try:value={'outcome':'completed','result':workbench() if a.case=='workbench32' else reader()}
        except Exception as e:value={'outcome':'rejected_or_failed','error_type':type(e).__name__,'reason':str(e)}
        print(json.dumps({'case':a.case,'seconds':perf_counter()-before,**value}));return
    if not a.output or a.output.exists():raise ValueError('New exclusive output required')
    rows=[]
    for name in ('reader32',):
        before=perf_counter()
        try:
            child=subprocess.run([sys.executable,'-X','utf8','-B','-S',str(Path(__file__).resolve()),'--case',name],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
            row={'case':name,'wall_seconds':perf_counter()-before,'exit_code':child.returncode,
                'raw_stdout':child.stdout,'raw_stderr':child.stderr,'parsed':json.loads(child.stdout) if child.returncode==0 else None}
        except subprocess.TimeoutExpired:
            row={'case':name,'wall_seconds':perf_counter()-before,'outcome':'own_probe_timeout_30s','conclusion':'No engine result; not a no-witness verdict.'}
        rows.append(row);print(json.dumps(row),flush=True)
    from scripts.audit_frontier_v6k_ui_latency import SOURCE_FILES
    value={'schema':'retrace.constructed-ui-latency-corrected-probes.v1','constructed_only':True,'model_calls':0,'live_answers_read':False,
        'supersedes_only_invalid_setup_cases':['reader32_missing_combination_citation'],
        'prior_result_path':'results/frontier-v6k-offline/ui-latency-corrected-check.json',
        'prior_result_sha256':sha256((ROOT/'results/frontier-v6k-offline/ui-latency-corrected-check.json').read_bytes()).hexdigest(),
        'source_hashes':{n:sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCE_FILES},
        'probe_script_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'rows':rows,
        'scope':'One local sample per constructed probe; no empirical model result, timing guarantee or engine modification.'}
    with a.output.open('x',encoding='utf-8',newline='\n') as stream:json.dump(value,stream,indent=2,ensure_ascii=False);stream.write('\n')


if __name__=='__main__':main()
