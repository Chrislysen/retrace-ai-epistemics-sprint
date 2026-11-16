"""Bounded constructed-only UI-mechanics probes, not an empirical benchmark.

Each isolated child is stopped after30seconds by this parent. No HTTP, provider,
live study journal, credential, or scientific mutation is involved.
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
CASES=('workbench_32_readings','minimax_32_five_questions','tier_a_32_minimum16',
       'family_32_unknown8','typed_32_unknown3_near_bound','typed_32_unknown4_over_bound',
       'tier_b_equal_32_plus32_full1024_masks','proof1024_one_graph','proof1024_32_graphs',
       'reader_validation_32_plus32','invalid_33_candidates','explicit_small_bdd_bound')
SOURCE_FILES=('retrace/workbench_v6h.py','retrace/server_v6h.py','retrace/tiered_v6h.py',
    'retrace/argumentation_v6h.py','retrace/boolean_v6h.py','retrace/impact_v6h.py',
    'retrace/typed_interventions_v6h.py','retrace/refuter_inspector_v6l.py',
    'retrace/refuter_catalog_v6l.py','retrace/refuter_reader_v6l.py','web/v6h/app.js',
    'web/v6l/refuters.js')


def graph(n=16,unknown=0,proof_pairs=None,polar=False):
    ids=['E'+str(i).zfill(2) for i in range(n)]
    evidence=[{'id':eid,'kind':'unknown' if i<unknown else 'root','active':True,'parents':[]} for i,eid in enumerate(ids)]
    expr={'ref':ids[-1]}
    if proof_pairs is not None:
        expr={'all':[{'any':[{'ref':ids[2*i]},{'ref':ids[2*i+1]}]} for i in range(proof_pairs)]}
    return {'schema':'retrace.tiered-graph.v6h','evidence':evidence,
        'claims':[{'id':'C','positive':expr,'negative':{'const':polar}}],
        'decisions':[{'id':'D','requires':['C']}]}


def call_case(name):
    from retrace.workbench_v6h import analyze_workbench,demo_brief,minimax_clarification,_bounded
    from retrace.source_ir_v6d import source_segments
    from retrace.tiered_v6h import family_supervaluation
    from retrace.impact_v6h import compare_families,withdrawal_robustness
    from retrace.typed_interventions_v6h import restore_then_withdraw_impact
    if name=='workbench_32_readings':
        brief=demo_brief();brief['source_documents'].append({'id':'latency-only','text':'Constructed latency probe: two additional declared binary distinctions are intentionally decision-irrelevant.'})
        span=source_segments(brief['source_documents'])[-1]['span_id']
        for i in range(2):brief['source_ir']['choices'].append({'id':'unused'+str(i),'options':['one','two'],'citations':[span]})
        brief.pop('clarifications');value=analyze_workbench(brief)
        return {'candidates':len(value['candidate_ids']),'planner_states':value['planner']['states_evaluated'],
            'mechanisms':{k:value[k]['status'] for k in ('robustness','hamming2','typed_veto_release')}}
    if name=='minimax_32_five_questions':
        ids=[str(i).zfill(2) for i in range(32)]
        vectors={cid:{'D'+str(bit):'supported' if int(cid)&(1<<bit) else 'not_supported' for bit in range(5)} for cid in ids}
        qs=[{'id':'q'+str(bit),'label':'Constructed binary partition','cost':1,
            'answers':{cid:bool(int(cid)&(1<<bit)) for cid in ids}} for bit in range(5)]
        value=minimax_clarification(vectors,qs)
        assert value['possible'] and value['worst_case_cost']==5
        return {'candidates':32,'questions':5,'worst_case_cost':5,'states_evaluated':value['states_evaluated']}
    if name=='tier_a_32_minimum16':
        g=graph();g['claims'][0]['positive']={'any':[{'ref':r['id']} for r in g['evidence']]}
        value=withdrawal_robustness([deepcopy(g) for _ in range(32)])
        assert value['decisions'][0]['minimum_k']==16
        return {'candidate_count':32,'minimum_k':16,'method':'exact known-ancestry ROBDD'}
    if name=='family_32_unknown8':
        g=graph(8,8);value=family_supervaluation([deepcopy(g) for _ in range(32)])
        return {'candidates':value['candidate_count'],'aligned_ancestry_completions':value['aligned_ancestry_completions'],
            'concrete_candidate_completions':8192,'state':value['decisions']['D']}
    if name.startswith('typed_32_unknown'):
        unknown=4 if 'over_bound' in name else 3;g=graph(16,unknown)
        groups=[{'id':'doc-'+r['id'],'evidence_ids':[r['id']]} for r in g['evidence']]
        value=_bounded(restore_then_withdraw_impact,[deepcopy(g) for _ in range(32)],document_groups=groups,
            revoked_documents=[r['id'] for r in groups])
        if unknown==4:assert value['status']=='unavailable' and 'witnesses' not in value
        else:assert value['status']=='evaluated' and len(value['witnesses'])==1
        return {'mechanism_status':value['status'],'witnesses':len(value['witnesses']) if 'witnesses' in value else None,
            'reason':value.get('reason'),'declared_concrete_evaluation_bound':289*32*(1<<unknown)}
    if name=='tier_b_equal_32_plus32_full1024_masks':
        g=graph(10,polar=True);family=[deepcopy(g) for _ in range(32)]
        value=compare_families(family,deepcopy(family))
        assert value['decisions'][0]['minimum_k'] is None
        return {'seed_candidates':32,'proposal_candidates':32,'withdrawal_masks':1024,
            'declared_concrete_evaluations':65536,'minimum_k':None,'method':value['method'],
            'no_witness_scope':'Full declared enumeration completed, not timeout/exhaustion'}
    if name.startswith('proof1024_'):
        n=32 if name=='proof1024_32_graphs' else 1;g=graph(20,proof_pairs=10)
        value=family_supervaluation([deepcopy(g) for _ in range(n)])
        assert value['decisions']['D']['box_supported']
        return {'candidates':n,'proofs_per_candidate':1024,'state':'supported'}
    if name=='reader_validation_32_plus32':
        from retrace.refuter_catalog_v6l import build_catalog,validate_entry
        from retrace.refuter_gate_v6h import validate_refuter
        from tests.test_refuter_catalog_v6l import fixture
        from tests.test_frontier_v6l_catalog import bind
        from tests.test_refuter_inspector_v6l import envelope,DOCS,REG
        data=fixture();packet=json.loads(data[2][0]['input']);seed=packet['supplied_candidates'][0]['graph']
        packet['supplied_candidates']=[{'id':'seed'+str(i),'graph':deepcopy(seed)} for i in range(32)]
        data[2][0]['input']=json.dumps(packet);data[4]['requests'][0]['request']['input'][-1]['content']=data[2][0]['input']
        proposed=envelope();span=proposed['objection_spans'][0]
        proposed['ir']['choices']=[{'id':'unused'+str(i),'options':['one','two'],'citations':[span]} for i in range(5)]
        raw=json.dumps(proposed)
        for row in data[4]['responses']+data[4]['outcomes']:row['output_text']=raw
        data[3][0]['refuter_gate']=validate_refuter(raw,DOCS,REG);bind(data[4])
        before=perf_counter();value=build_catalog(*data,require_full_design=False)
        setup=perf_counter()-before;entry=next(iter(value['entries'].values()))
        before=perf_counter();validate_entry(entry);elapsed=perf_counter()-before
        assert entry['inspection']['gate']['candidate_count']==32
        return {'seed_candidates':32,'proposal_candidates':32,'validate_entry_seconds':elapsed,
            'catalog_projection_setup_seconds':setup,'preview_status':entry['inspection']['preview']['status'],
            'scope':'Exact per-entry raw/gate/mechanism replay used inside reader lock; no catalog or HTTP server was created'}
    if name=='invalid_33_candidates':
        value=_bounded(family_supervaluation,[graph(2) for _ in range(33)])
        assert value['status']=='unavailable' and 'decisions' not in value
        return value
    if name=='explicit_small_bdd_bound':
        from retrace.boolean_v6h import BDD
        def bounded_bdd():
            manager=BDD(['a','b'],max_nodes=3);manager.variable('a');manager.variable('b')
        value=_bounded(bounded_bdd)
        assert value['status']=='unavailable' and 'no partial result' in value['reason']
        return {**value,'scope':'Explicit tiny-manager guard regression; not a timing test at the production100000-node ceiling'}
    raise ValueError('Unknown constructed probe')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',choices=CASES);p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.case:
        before=perf_counter()
        try:out={'outcome':'completed','result':call_case(a.case)}
        except Exception as exc:out={'outcome':'rejected_or_failed','error_type':type(exc).__name__,'reason':str(exc)}
        print(json.dumps({'case':a.case,'seconds':perf_counter()-before,**out},allow_nan=False));return
    if not a.output or a.output.exists():raise ValueError('Exclusive new diagnostic output required')
    rows=[]
    for name in CASES:
        before=perf_counter()
        try:
            child=subprocess.run([sys.executable,'-X','utf8','-B','-S',str(Path(__file__).resolve()),'--case',name],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
            row={'case':name,'wall_seconds':perf_counter()-before,'exit_code':child.returncode,
                'raw_stdout':child.stdout,'raw_stderr':child.stderr,'parsed':json.loads(child.stdout) if child.returncode==0 else None}
        except subprocess.TimeoutExpired as exc:
            row={'case':name,'wall_seconds':perf_counter()-before,'outcome':'own_probe_timeout_30s',
                'raw_stdout':(exc.stdout or b'').decode() if isinstance(exc.stdout,bytes) else exc.stdout or '',
                'raw_stderr':(exc.stderr or b'').decode() if isinstance(exc.stderr,bytes) else exc.stderr or '',
                'conclusion':'No engine verdict returned. This is not a no-witness result.'}
        rows.append(row);print(json.dumps({'case':name,'wall_seconds':row['wall_seconds'],'outcome':row.get('outcome') or (row.get('parsed') or {}).get('outcome')}),flush=True)
    result={'schema':'retrace.constructed-ui-latency-audit.v1','constructed_only':True,'model_calls':0,'live_answers_read':False,
        'probe_timeout_seconds':30,'source_hashes':{name:sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCE_FILES},
        'probe_script_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'rows':rows,
        'scope':'Single local timing samples under concurrent system load; not latency guarantees, empirical model results, or exhaustive worst-case bounds. Child timeout stops only this owned offline probe.'}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8',newline='\n') as stream:json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')


if __name__=='__main__':main()
