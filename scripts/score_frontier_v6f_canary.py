"""Every planned fourth-canary outcome; no completion-conditioned headline."""
from pathlib import Path
import json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.frontier_v6c_io import parse_object,graph_signature,family_score
from retrace.compact_graph import validate_explicit_graph
from retrace.source_ir_v6d import compile_cited_ir
from scripts.build_frontier_v6f_canary import source_cases,expected_family


def evaluate(slots,records):
    rows={r['slot_id']:r for r in records}
    if len(rows)!=len(records) or set(rows)-{s['slot_id'] for s in slots}:raise ValueError('Duplicate or unexpected result')
    docs,registry=source_cases();expected=expected_family();signatures={graph_signature(g) for g in expected};audits=[]
    for slot in slots:
        row=rows.get(slot['slot_id']);out={k:slot[k] for k in ('slot_id','model','condition')}
        out.update(passed=False,strict_bare_json=False)
        if row is None:out['failure']='unissued_or_unreceived'
        elif row.get('error') or row.get('response_status')!='completed' or row.get('http_status')!=200:
            out['failure']='provider_transport_or_truncation_failure'
        elif any(row.get(k)!=slot[k] for k in ('model','case_id','condition')):out['failure']='response_identity_mismatch'
        else:
            try:
                parsed,strict=parse_object(row['output_text']);out['strict_bare_json']=strict
                if slot['condition']=='canary_sample_graph':
                    graph=validate_explicit_graph(parsed,registry)
                    out.update(passed=graph_signature(graph) in signatures,graph=graph)
                else:
                    compiled=compile_cited_ir(parsed,docs,registry);score=family_score(compiled['candidates'],expected)
                    out.update(passed=score['exact_family'],family_score=score,assignment_count=compiled['assignment_count'],
                               binding_count=len(compiled['bindings']),proposition_count=len(compiled['propositions']))
                out.update(usage=row.get('usage'),latency_ms=row.get('latency_ms'))
            except Exception as exc:out['failure']=f'{type(exc).__name__}: {exc}'
        audits.append(out)
    return {'schema':'retrace.frontier-v6f-canary-score.v1','planned':len(slots),'received':len(records),
            'passed_slots':sum(r['passed'] for r in audits),'passed':len(slots)==10 and all(r['passed'] for r in audits),'results':audits,
            'scope':'Fourth prospective diagnostic uses a renamed and recontextualized isomorphic source, new pacing, temperature1, sample16K and IR64K; no primary benchmark calls or pooled diagnostic success rate. Changes are not causally isolated.'}


if __name__=='__main__':
    files=[ROOT/'data/frontier-v6f-canary-sessions.json',ROOT/'results/frontier-v6f/canary/responses.jsonl']
    result=evaluate(json.loads(files[0].read_text(encoding='utf-8')),[json.loads(l) for l in files[1].read_text(encoding='utf-8').splitlines() if l.strip()])
    result['inputs_sha256']={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with (ROOT/'results/frontier-v6f/canary-evaluation.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
