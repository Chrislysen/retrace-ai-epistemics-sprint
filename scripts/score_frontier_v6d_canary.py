"""Separate ten-slot source-reference/streaming diagnostic; no old result repair."""
from pathlib import Path
from copy import deepcopy
import json
import hashlib
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.frontier_v6c_io import parse_object,verdict,family_score
from retrace.source_ir_v6d import compile_cited_ir
from scripts.build_frontier_v6d_canary import source_cases


def evaluate(slots,records):
    indexed={}
    for row in records:
        if row['slot_id'] in indexed:raise ValueError('Duplicate canary result')
        indexed[row['slot_id']]=row
    if set(indexed)-{s['slot_id'] for s in slots}:raise ValueError('Unexpected result')
    _,docs,registry=source_cases()
    common={'evidence':[{'id':i,'kind':'root','parents':[],'active':i!='H4'} for i in ['F2','G3','H4']]+[{'id':'T5','kind':'copy','parents':['F2'],'active':True}],
            'claims':[{'id':'V6','supports':[['T5','H4']]},{'id':'W7','supports':[['H4']]}],
            'decisions':[{'id':'Y8','requires':['V6']},{'id':'Z9','requires':['W7']}]}
    alternate=deepcopy(common);alternate['claims'][0]['supports']=[['T5']]
    results=[]
    for slot in slots:
        row=indexed.get(slot['slot_id']);result={'slot_id':slot['slot_id'],'model':slot['model'],
                                               'condition':slot['condition'],'passed':False,'strict_bare_json':False}
        if row is None:result['failure']='unissued_or_unreceived'
        elif row.get('error'):result['failure']='provider_or_transport_failure'
        else:
            try:
                if slot['condition']=='canary_verdict':
                    parsed,strict=verdict(row['output_text'],['Z6']);result.update(prediction=parsed,strict_bare_json=strict,passed=parsed=={'Z6':'supported'})
                else:
                    parsed,strict=parse_object(row['output_text']);result['strict_bare_json']=strict
                    compiled=compile_cited_ir(parsed,docs,registry);score=family_score(compiled['candidates'],[common,alternate])
                    result.update(passed=score['exact_family'],family_score=score,assignment_count=compiled['assignment_count'],
                                  binding_count=len(compiled['bindings']),proposition_count=len(compiled['propositions']))
                result.update(usage=row.get('usage'),latency_ms=row.get('latency_ms'))
            except Exception as exc:result['failure']=f'{type(exc).__name__}: {exc}'
        results.append(result)
    return {'schema':'retrace.frontier-v6d-canary-score.v1','passed':len(results)==10 and all(r['passed'] for r in results),
            'planned':len(slots),'received':len(records),'passed_slots':sum(r['passed'] for r in results),'results':results,
            'scope':'Distinct off-benchmark diagnostic after the preserved v6c failures. No primary benchmark result, no pooled success denominator, no isolated transport/representation causal claim.'}


if __name__=='__main__':
    files=[ROOT/'data/frontier-v6d-canary-sessions.json',ROOT/'results/frontier-v6d/canary/responses.jsonl']
    slots=json.loads(files[0].read_text(encoding='utf-8'));records=[json.loads(l) for l in files[1].read_text(encoding='utf-8').splitlines() if l.strip()]
    result=evaluate(slots,records)
    result['inputs_sha256']={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with (ROOT/'results/frontier-v6d/canary-evaluation.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,indent=2,ensure_ascii=False);f.write('\n')
    print(json.dumps(result,indent=2,ensure_ascii=False))
