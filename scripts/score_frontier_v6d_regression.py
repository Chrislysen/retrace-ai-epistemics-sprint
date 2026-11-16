"""No repair, missing-outcome exclusion, or conversion of unknown lineage to roots."""
from pathlib import Path
from collections import Counter,defaultdict
from copy import deepcopy
import hashlib
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.source_ir_v6d import compile_cited_ir,audit_cited_ir
from retrace.frontier_v6c_io import parse_object,family_score
from retrace.source_ir_v6c import compile_source_ir


def unknown_case_recovery(compiled,public,gold):
    """Gold-side diagnostic of known structure, never an executable product repair."""
    expected=set(gold['unidentified_ancestor_targets'])
    current=[p for p in compiled['propositions'] if p['scope']=='current']
    unknown=[p for p in current if p['kind']=='unknown_ancestry']
    recognized={p['target'] for p in unknown}==expected
    if not recognized or len(unknown)!=len(expected) or compiled['choices'] or compiled['status']!='unresolved_structure' or compiled['candidates']:
        return recognized,False
    actual={(e['id'],e['type']) for e in compiled['entities'] if e['operational']}
    required={(i,{'evidence':'evidence','claims':'claim','decisions':'decision'}[cat]) for cat,ids in public['registry'].items() for i in ids}
    if actual!=required or any(p['kind']=='origin' and p['target'] in expected for p in current):return recognized,False
    if any(not any(c['document_id']=='holdout-04-section-2' for c in p['citations']) for p in unknown):return recognized,False
    # Neutral placeholders solely let the checker compare the otherwise known
    # clauses to this diagnostic's existing scaffold. They are not recovered roots.
    comparison=deepcopy(compiled['original_ir'])
    for p in comparison['propositions']:
        if p['kind']=='unknown_ancestry' and p['scope']=='current':
            p.update(kind='origin',body={'kind':'root','parents':[]})
    checked=compile_source_ir(comparison,public['source_documents'],public['registry'])
    return recognized,family_score(checked['candidates'],public['candidates'])['exact_family']


def evaluate(data,slots,records):
    cases={c['id']:c for c in data['cases']};by_slot={r['slot_id']:r for r in records}
    if len(by_slot)!=len(records) or set(by_slot)-{s['slot_id'] for s in slots}:raise ValueError('Duplicate or unknown results')
    outputs=[]
    for slot in slots:
        case=cases[slot['case_id']];gold=case['evaluation'];public=case['public'];row=by_slot.get(slot['slot_id'])
        out={k:slot[k] for k in ('slot_id','case_id','model','condition')}
        out.update(positive=gold['positive'],clean_success=False,grounded_recovery=False,strict_bare_json=False)
        if row is None:out['failure']='unissued_or_unreceived'
        elif row.get('error') or row.get('response_status')!='completed' or row.get('http_status')!=200:
            out['failure']='provider_transport_or_truncation_failure'
        elif any(row.get(k)!=slot[k] for k in ('model','case_id','condition')):
            out['failure']='response_identity_mismatch'
        else:
            try:
                parsed,strict=parse_object(row['output_text']);out['strict_bare_json']=strict
                if slot['condition']=='adversarial_refuter' and parsed=={'status':'no_counter_reading'}:
                    out.update(abstained=True,clean_success=not gold['positive'])
                else:
                    compiled=compile_cited_ir(parsed,public['source_documents'],public['registry'])
                    audit=audit_cited_ir(parsed,public['source_documents'],public['candidates'],public['registry'])
                    out.update(compilation_status=compiled['status'],audit_status=audit['status'],candidate_count=compiled['candidate_count'])
                    if gold['unidentified_ancestor_targets']:
                        recognized,recovered=unknown_case_recovery(compiled,public,gold)
                        out['unidentified_ancestor_targets_recognized']=recognized
                    else:
                        score=family_score(compiled['candidates'],gold['expected_family']);out['family_score']=score
                        recovered=score['exact_family'] and compiled['status']=='compiled'
                    out['grounded_recovery']=recovered
                    out['clean_success']=recovered and (slot['condition']=='source_ir' or gold['positive'])
                    if not gold['positive']:
                        out['unnecessary_counterproposal']=slot['condition']=='adversarial_refuter'
                        out['false_review_block']=audit['status']!='represented_declared_contract'
            except Exception as exc:out['failure']=f'{type(exc).__name__}: {exc}'
        outputs.append(out)
    groups=defaultdict(list)
    for out in outputs:groups[(out['model'],out['condition'])].append(out)
    summaries=[]
    for (model,arm),rows in groups.items():
        positives=[r for r in rows if r['positive']];controls=[r for r in rows if not r['positive']]
        summaries.append({'model':model,'condition':arm,'planned':len(rows),'positive_clean_success':sum(r['clean_success'] for r in positives),
                          'positive_denominator':len(positives),'control_clean_success':sum(r['clean_success'] for r in controls),
                          'control_denominator':len(controls),'control_false_review_blocks':sum(r.get('false_review_block',False) for r in controls),
                          'control_invalid_or_missing':sum('failure' in r for r in controls),
                          'control_unnecessary_counterproposals':sum(r.get('unnecessary_counterproposal',False) for r in controls)})
    return {'schema':'retrace.frontier-v6d-development-regression-score.v1','planned':len(slots),'received':len(records),'groups':summaries,'audits':outputs,
            'scope':data['scope'],'unknown_lineage_success':'Both named slips retain unidentified ancestry; no invented source ID or executable complete family.',
            'selectivity':'Invalid/missing controls do not count as clean. A faithful refuter must abstain; a correct but unnecessary full IR is separately recorded.'}


if __name__=='__main__':
    files=[ROOT/'data/frontier-v6d-regression.json',ROOT/'data/frontier-v6d-regression-sessions.json',ROOT/'results/frontier-v6d/regression/responses.jsonl']
    data,slots=[json.loads(p.read_text(encoding='utf-8')) for p in files[:2]]
    records=[json.loads(l) for l in files[2].read_text(encoding='utf-8').splitlines() if l.strip()]
    result=evaluate(data,slots,records);result['inputs_sha256']={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with (ROOT/'results/frontier-v6d/regression-evaluation.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,indent=2,ensure_ascii=False);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='audits'},indent=2))
