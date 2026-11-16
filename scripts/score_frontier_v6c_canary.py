"""Score all ten frozen off-benchmark canary slots; no provider calls or repair."""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.frontier_v6c_io import parse_object,verdict,family_score
from retrace.source_ir_v6c import compile_source_ir


def evaluate(slots,records):
    indexed={}
    for row in records:
        if row['slot_id'] in indexed: raise ValueError('Duplicate canary output')
        indexed[row['slot_id']]=row
    if set(indexed)-{s['slot_id'] for s in slots}: raise ValueError('Unexpected canary output')
    expected={'evidence':[{'id':'A','kind':'root','active':True,'parents':[]},
                          {'id':'B','kind':'root','active':True,'parents':[]},
                          {'id':'X','kind':'copy','active':True,'parents':['A']}],
              'claims':[{'id':'C','supports':[['X'],['B']]}],
              'decisions':[{'id':'D','requires':['C']}]}
    results=[]
    for slot in slots:
        response=indexed.get(slot['slot_id'])
        outcome={'slot_id':slot['slot_id'],'model':slot['model'],'condition':slot['condition'],
                 'passed':False,'strict_bare_json':False}
        if response is None: outcome['failure']='not_received'
        elif response.get('error'): outcome['failure']='provider_or_transport_failure'
        else:
            try:
                source=json.loads(slot['input'])
                if slot['condition']=='canary_verdict':
                    parsed,strict=verdict(response['output_text'],['D'])
                    outcome.update(strict_bare_json=strict,passed=parsed=={'D':'unsupported'},prediction=parsed)
                else:
                    parsed,strict=parse_object(response['output_text'])
                    compilation=compile_source_ir(parsed,source['source_documents'],source['registry'])
                    score=family_score(compilation['candidates'],[expected])
                    outcome.update(strict_bare_json=strict,passed=score['exact_family'],compilation_status=compilation['status'],
                                   family_score=score,proposition_count=len(compilation['propositions']),
                                   binding_count=len(compilation['bindings']),
                                   noncurrent_propositions=sum(p['scope']!='current' for p in compilation['propositions']),
                                   denied_propositions=sum(p['polarity']=='deny' for p in compilation['propositions']))
                outcome['usage']=response.get('usage')
                outcome['latency_ms']=response.get('latency_ms')
            except (ValueError,KeyError,TypeError) as exc:
                outcome['failure']=str(exc)
        results.append(outcome)
    return {'schema':'retrace.frontier-v6c-canary-score.v1','passed':len(results)==10 and all(r['passed'] for r in results),
            'planned':len(slots),'received':len(records),'passed_slots':sum(r['passed'] for r in results),
            'results':results,'scope':'Off-benchmark formatting and elementary graph check. Not a benchmark result or evidence of general extraction fidelity.'}


if __name__=='__main__':
    sessions=ROOT/'data/frontier-v6c-canary-sessions.json'
    responses=ROOT/'results/frontier-v6c/canary/responses.jsonl'
    slots=json.loads(sessions.read_text(encoding='utf-8'))
    records=[json.loads(line) for line in responses.read_text(encoding='utf-8').splitlines() if line.strip()]
    result=evaluate(slots,records)
    result['inputs_sha256']={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in [sessions,responses]}
    target=ROOT/'results/frontier-v6c/canary-evaluation.json'
    with target.open('x',encoding='utf-8',newline='\n') as f: json.dump(result,f,indent=2,ensure_ascii=False);f.write('\n')
    print(json.dumps(result,indent=2,ensure_ascii=False))
