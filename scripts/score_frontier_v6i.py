"""Authenticate frozen inputs and write NEW v6i offline scores; no inference."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.frontier_v6i_eval import evaluate
from scripts.score_frontier_v6h import authenticate,file_hash,load,jsonl,local_dependencies


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('corpus','dossiers','study','sessions','outcomes','attempts','requests','run-summary','output','audits','freeze','freeze-sha256'):
        p.add_argument('--'+name,required=True)
    for name in ('outcomes','attempts','requests','run-summary'):p.add_argument('--'+name+'-sha256',required=True)
    a=p.parse_args();output=Path(a.output);audits=Path(a.audits)
    if output.resolve()==audits.resolve() or output.exists() or audits.exists():raise ValueError('New distinct output files required')
    required={Path(x) for x in (a.corpus,a.dossiers,a.study,a.sessions)}
    required|=local_dependencies([Path(__file__).resolve(),ROOT/'retrace/frontier_v6i_eval.py'])
    evidence=authenticate(a.freeze,a.freeze_sha256,required,{name:(getattr(a,name),getattr(a,name+'_sha256')) for name in ('outcomes','attempts','requests','run_summary')})
    read=lambda path:load(Path(path).read_text(encoding='utf-8'))
    result=evaluate(read(a.corpus),read(a.dossiers),read(a.study),read(a.sessions),jsonl(a.outcomes),jsonl(a.attempts),jsonl(a.requests),read(a.run_summary),10000)
    for row in evidence['raw_files'].values():
        if file_hash(row['path'])!=row['sha256']:raise ValueError('Raw journals changed during scoring')
    result['summary']['file_evidence']=evidence
    for path,value in ((output,result['summary']),(audits,result['audits'])):
        with path.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'status':result['summary']['status'],'planned':result['summary']['planned_slots'],'issued_attempts':result['summary']['issued_attempts_observed'],'holm_family':result['summary']['primary_holm_family_size']}))


if __name__=='__main__':main()
