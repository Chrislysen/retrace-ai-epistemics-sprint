"""Score all ten canary slots and every issued attempt without output repair."""
from pathlib import Path
from hashlib import sha256
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.build_frontier_v6h_canary import build,source,expected_family
from retrace.source_ir_v6h import compile_ir
from retrace.refuter_gate_v6h import validate_refuter
from retrace.graph_identity_v6h import family_score

def evaluate(slots,outcomes,attempts):
    if slots!=build():raise ValueError('Canary slots differ from reviewed projection')
    planned={s['slot_id']:s for s in slots};docs,registry=source()
    def score(record,slot):
        row={k:slot[k] for k in ('slot_id','model','condition')}
        row.update(exact_family=False,accepted=False,operational_completed=False)
        if record is None:row['failure']='missing_outcome';return row
        if any(record.get(k)!=slot[k] for k in ('slot_id','case_id','model','condition','phase')):raise ValueError('Identity mismatch')
        for k in ('attempt_id','attempt_number','latency_ms','model_outcome','error','usage','settled_credits','response_status','http_status'):
            row[k]=record.get(k)
        if not record.get('terminal_valid') or record.get('model_outcome')!='completed':
            row['failure']='provider_or_truncation_outcome';return row
        row['operational_completed']=True
        try:
            if slot['condition']=='canary_refuter':
                gate=validate_refuter(record['output_text'],docs,registry)
                row.update(gate_status=gate['status'],strict_bare_json=gate['strict_bare_json'],warning_score=gate['raw_warning_score'])
                if gate['compilation'] is None:row['failure']='abstention_on_controlled_deficient_seed';return row
                compiled=gate['compilation']
            else:compiled=compile_ir(record['output_text'],docs,registry)
            row.update(accepted=True,inventory_gaps=compiled['registry_coverage_gaps'],family=family_score(compiled['candidates'],expected_family()))
            row['exact_family']=row['family']['exact_family'] and not row['inventory_gaps']
            if not row['exact_family']:row['failure']='source_family_mismatch'
        except (ValueError,TypeError,KeyError,RecursionError) as exc:row['failure']=type(exc).__name__+': '+str(exc)
        return row
    indexed={}
    for row in outcomes:
        if row['slot_id'] in indexed or row['slot_id'] not in planned:raise ValueError('Duplicate/unplanned final outcome')
        indexed[row['slot_id']]=row
    seen=set();attempt_scores=[]
    per_slot={sid:[] for sid in planned}
    for row in attempts:
        if row['attempt_id'] in seen or row['slot_id'] not in planned:raise ValueError('Duplicate/unplanned attempt')
        number=row.get('attempt_number')
        if type(number) is not int or number!=len(per_slot[row['slot_id']])+1 or number>3:
            raise ValueError('Attempt numbers must be contiguous1..3 within each slot')
        if row.get('issued') is not True or row.get('first_attempt') is not (number==1):raise ValueError('Attempt flags disagree')
        previous=per_slot[row['slot_id']][-1] if per_slot[row['slot_id']] else None
        if previous and not (previous.get('model_outcome')=='http_429' and previous.get('http_status')==429 and previous.get('terminal_valid') is False and previous.get('error')=='http_429'):
            raise ValueError('Only explicit HTTP429 authorizes another attempt')
        if row.get('model_outcome')=='completed' and not (row.get('terminal_valid') is True and row.get('error') is None and row.get('http_status')==200 and row.get('response_status')=='completed'):
            raise ValueError('Completed attempt flags disagree')
        per_slot[row['slot_id']].append(row)
        seen.add(row['attempt_id']);attempt_scores.append(score(row,planned[row['slot_id']]))
    for sid,row in indexed.items():
        issued=per_slot[sid]
        if row.get('issued') is True:
            if not issued:raise ValueError('Final outcome has no issued attempt')
            last=issued[-1]
            if any(row.get(k)!=v for k,v in last.items()):raise ValueError('Final outcome differs from last attempt')
            if row.get('attempts_issued')!=len(issued) or row.get('first_attempt_id')!=issued[0]['attempt_id']:
                raise ValueError('Final attempt accounting differs')
        elif issued:raise ValueError('Issued attempts cannot end with an unissued outcome')
        elif not (row.get('issued') is False and row.get('terminal_valid') is False and row.get('output_text')==''
                  and str(row.get('model_outcome','')).startswith('not_issued_') and row.get('attempts_issued')==0 and row.get('first_attempt_id') is None):
            raise ValueError('Unissued outcome flags disagree')
    final=[score(indexed.get(s['slot_id']),s) for s in slots]
    return {'schema':'retrace.frontier-v6h-canary-score.v1','planned':10,'observed_attempts':len(attempts),
        'final_operational_completed':sum(r['operational_completed'] for r in final),
        'final_schema_accepted':sum(r['accepted'] for r in final),'final_exact_family':sum(r['exact_family'] for r in final),
        'first_attempt_exact_family':sum(r['exact_family'] for r in attempt_scores if r.get('attempt_number')==1),
        'final_slots':final,'all_attempts':attempt_scores,
        'gate_policy':'Operational closure is required. Schema/semantic failures remain outcomes, not a perfect-score requirement or a reason to retry. Any post-canary prompt change requires a separate prospective revision.',
        'scope':'Single constructed feasibility source outside60 primary cases; targeted after prior-revision failures. Exact citation locations do not establish entailment. No independent-population accuracy claim.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    paths={'sessions':ROOT/'data/frontier-v6h-canary-sessions.json','outcomes':args.run/'slot-outcomes.jsonl','attempts':args.run/'responses.jsonl'}
    raw={k:v.read_bytes() for k,v in paths.items()}
    result=evaluate(json.loads(raw['sessions']),*[ [json.loads(line) for line in raw[k].splitlines() if line.strip()] for k in ('outcomes','attempts')])
    result['input_sha256']={k:sha256(v).hexdigest() for k,v in raw.items()}
    with args.output.open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({k:result[k] for k in ('planned','observed_attempts','final_operational_completed','final_schema_accepted','final_exact_family')}))
if __name__=='__main__':main()
