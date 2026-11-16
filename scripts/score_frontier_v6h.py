"""Read frozen v6h journals and write NEW exclusive offline evaluation artifacts."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.frontier_v6h_eval import evaluate


def pairs(items):
    result={}
    for k,v in items:
        if k in result:raise ValueError('Duplicate JSON key')
        result[k]=v
    return result


def load(text):
    def reject(_):raise ValueError('Nonfinite JSON')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=reject)


def jsonl(path):
    with Path(path).open(encoding='utf-8') as stream:return [load(line) for line in stream if line.strip()]


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def local_dependencies(starts):
    """Static local import closure; external libraries are not copied or run."""
    pending=[Path(p).resolve() for p in starts];seen=set()
    while pending:
        path=pending.pop()
        if path in seen:continue
        if not path.is_relative_to(ROOT) or not path.is_file():raise ValueError('Local dependency path')
        seen.add(path);package=list(path.relative_to(ROOT).parts[:-1])
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            modules=[]
            if isinstance(node,ast.Import):modules=[a.name.split('.') for a in node.names]
            elif isinstance(node,ast.ImportFrom):
                base=package[:len(package)-node.level+1] if node.level else []
                if node.module:modules=[base+node.module.split('.')]
                else:modules=[base+a.name.split('.') for a in node.names]
            for parts in modules:
                if parts and parts[0] in ('retrace','scripts'):
                    target=ROOT.joinpath(*parts).with_suffix('.py')
                    if target.is_file():pending.append(target.resolve())
    return seen


def authenticate(freeze_path,expected_hash,required_paths,raw_inputs):
    if file_hash(freeze_path)!=expected_hash:raise ValueError('Freeze hash mismatch')
    freeze=load(Path(freeze_path).read_text(encoding='utf-8'));seen=set()
    if not isinstance(freeze.get('files'),list) or not freeze['files']:raise ValueError('Freeze files required')
    for row in freeze['files']:
        target=(ROOT/row['path']).resolve()
        if not target.is_relative_to(ROOT) or target in seen:raise ValueError('Invalid freeze path')
        if file_hash(target)!=row['sha256']:raise ValueError('Frozen dependency changed')
        seen.add(target)
    required={Path(p).resolve() for p in required_paths}
    required|=local_dependencies([Path(__file__).resolve(),ROOT/'retrace/frontier_v6h_eval.py'])
    if not required<=seen:raise ValueError('Scoring inputs/code absent from freeze')
    bindings={}
    for name,(path,expected) in raw_inputs.items():
        path=Path(path).resolve()
        actual=file_hash(path)
        if actual!=expected:raise ValueError('Raw journal hash mismatch')
        bindings[name]={'path':str(path),'sha256':actual}
    return {'freeze':{'path':str(Path(freeze_path).resolve()),'sha256':expected_hash},'raw_files':bindings}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('corpus','dossiers','sessions','outcomes','attempts','requests','run-summary','output','audits'):p.add_argument('--'+name,required=True)
    p.add_argument('--freeze',required=True);p.add_argument('--freeze-sha256',required=True)
    for name in ('outcomes','attempts','requests','run-summary'):p.add_argument('--'+name+'-sha256',required=True)
    p.add_argument('--bootstrap-repeats',type=int,default=10000)
    a=p.parse_args();output=Path(a.output);audits=Path(a.audits)
    if a.bootstrap_repeats!=10000:raise ValueError('Frozen analysis requires10000 bootstrap replicates')
    if output.resolve()==audits.resolve() or output.exists() or audits.exists():raise ValueError('New distinct output files required')
    evidence=authenticate(a.freeze,a.freeze_sha256,(a.corpus,a.dossiers,a.sessions),{
        name:(getattr(a,name),getattr(a,name+'_sha256')) for name in ('outcomes','attempts','requests','run_summary')})
    read=lambda name:load(Path(name).read_text(encoding='utf-8'))
    result=evaluate(read(a.corpus),read(a.dossiers),read(a.sessions),jsonl(a.outcomes),jsonl(a.attempts),jsonl(a.requests),read(a.run_summary),a.bootstrap_repeats)
    for binding in evidence['raw_files'].values():
        if file_hash(binding['path'])!=binding['sha256']:raise ValueError('Raw journal changed during scoring')
    result['summary']['file_evidence']=evidence
    for path,value in ((output,result['summary']),(audits,result['audits'])):
        with path.open('x',encoding='utf-8',newline='\n') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'status':result['summary']['status'],'planned':result['summary']['planned_slots'],'issued_attempts':result['summary']['issued_attempts_observed']}))


if __name__=='__main__':main()
