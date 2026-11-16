"""Offline authenticated crash recovery scoring. Never edits source journals."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from retrace.frontier_v6n_eval import evaluate_recovered,role_paths,COMPLETE,PARTIAL
from retrace.frontier_v6j_eval import json_value,require,_strict
from retrace.recovery_v6n import validate_receipt
from scripts.score_frontier_v6j import safe,sha,binding,import_closure

FREEZE='data/frontier-v6n-freeze.json'
OUTPUT='results/frontier-v6n/composite'
PARTIAL_OUTPUT='results/frontier-v6n/partial-diagnostic'
INPUTS={'corpus':'data/frontier-v6h-corpus.json','dossiers':'data/frontier-v6h-dossiers.json',
    'study':'data/frontier-v6i-design.json','sessions':'data/frontier-v6i-sessions.json',
    'receipt':'data/frontier-v6n-continuation.json'}
PREFIX_PROOF='results/frontier-v6n-recovery/m-prefix-proof.json'
AUDIT='results/frontier-v6n/continuation/runtime-audit.json'
LEDGER='results/frontier-v6n/budget/ledger.jsonl'
LOCK='results/frontier-v6n/budget/active.lock'
SNAPSHOT='data/frontier-v6n-ledger-after-continuation.jsonl'
ALIASES={'results/frontier-v6f/budget/active.lock':'provenance/frozen-locks/results/frontier-v6f/budget/active.lock.txt',
         'results/frontier-v6k/budget/active.lock':'provenance/frozen-locks/results/frontier-v6k/budget/active.lock.txt',
         'results/frontier-v6m/budget/active.lock':'provenance/frozen-locks/results/frontier-v6m/budget/active.lock.txt'}


def audit_runtime(*args,**kwargs):
    from scripts.audit_frontier_v6n_runtime import audit
    return audit(*args,**kwargs)


def verify_inventory(root,expected_sha,aliases):
    require(all(ALIASES.get(k)==v for k,v in aliases.items()),'unsupported frozen alias')
    path=safe(root,FREEZE);require(sha(path)==expected_sha,'execution freeze hash')
    freeze=_strict(path.read_bytes())
    require(freeze.get('schema')=='retrace.frontier-v6n-freeze.v1' and freeze.get('scheduled_slots')==1800,
            'prospective m freeze and unchanged plan')
    inventory={}
    for row in freeze['files']:
        name=row['path'];require(name not in inventory,'duplicate frozen path')
        value={'sha256':row['sha256'],'bytes':row['bytes']}
        require(binding(safe(root,aliases.get(name,name)))==value,'frozen dependency changed: '+name)
        inventory[name]=value
    required=set(INPUTS.values())|import_closure(root,['scripts/score_frontier_v6n.py',
        'retrace/frontier_v6n_eval.py','retrace/recovery_v6n.py','scripts/audit_frontier_v6n_runtime.py'])
    require(required<=set(inventory) and set(aliases)<=set(inventory),'unfrozen scoring dependency')
    return freeze,inventory


def segment(root):
    paths=role_paths();raw={role:safe(root,path).read_bytes() for role,path in paths.items()}
    return {'paths':paths,**{r:raw[r] for r in ('requests','responses','outcomes')},
        'summary_bytes':raw['summary'],'manifest_bytes':raw['run_manifest'],
        'summary':_strict(raw['summary']),'manifest':_strict(raw['run_manifest'])}


def selected_views(root,result,aliases):
    views={}
    for role in ('requests','responses','outcomes'):
        lines=[]
        for row,point in zip(result['merged_evidence'][role],result['merged_evidence']['source_provenance'][role]):
            raw=safe(root,aliases.get(point['source_path'],point['source_path'])).read_bytes()
            require(hashlib.sha256(raw).hexdigest()==point['source_file_sha256'],'source file changed during view selection')
            source=raw.splitlines(keepends=True);n=point['source_line_one_based']
            require(type(n) is int and 1<=n<=len(source),'source line outside journal')
            line=source[n-1]
            require(hashlib.sha256(line).hexdigest()==point['source_line_sha256'] and _strict(line)==row,
                    'lossless source line changed')
            lines.append(line)
        require(len(lines)==len(result['merged_evidence'][role]),'source pointer denominator')
        views[role]=b''.join(lines)
    return views


def compute(root,freeze_sha256,prefix_proof_sha256,n_audit_sha256,ledger_snapshot,ledger_snapshot_sha256,
            *,frozen_aliases=None,diagnostic=False):
    require(type(diagnostic) is bool,'explicit diagnostic branch')
    root=Path(root).resolve();aliases=dict(frozen_aliases or {})
    require(not safe(root,LOCK).exists(),'n continuation remains active')
    freeze,_=verify_inventory(root,freeze_sha256,aliases)
    require(ledger_snapshot==SNAPSHOT,'canonical immutable n ledger snapshot required')
    require(sha(safe(root,ledger_snapshot))==ledger_snapshot_sha256,'n snapshot hash')
    data={key:_strict(safe(root,name).read_bytes()) for key,name in INPUTS.items()}
    receipt=validate_receipt(data['receipt'])
    require(receipt['recovery_proof_path']==PREFIX_PROOF and receipt['recovery_proof_sha256']==prefix_proof_sha256,
            'exact original prefix proof pin')
    before={name:binding(safe(root,aliases.get(name,name))) for name in set(INPUTS.values())|{FREEZE,PREFIX_PROOF,AUDIT,ledger_snapshot}}
    require(before[PREFIX_PROOF]['sha256']==prefix_proof_sha256 and before[AUDIT]['sha256']==n_audit_sha256,
            'saved independent proof hash')
    prefix=_strict(safe(root,PREFIX_PROOF).read_bytes());saved=_strict(safe(root,AUDIT).read_bytes())
    actual=json_value(audit_runtime(root,freeze_sha256,frozen_aliases=aliases,ledger_snapshot=ledger_snapshot))
    require(actual==saved and actual['recovery_prefix_proof']==prefix,'independent runtime/prefix replay equality')
    require(actual.get('passed') is True and actual.get('final_closed') is True
            and actual.get('schedule_status')==('stopped' if diagnostic else 'completed'),'explicit final branch')
    require(actual.get('budget_cap_credits')=='750','prospective750 budget')
    contents={}
    names=dict(receipt['prior_journal_files'])
    for spec in receipt['orphan_dispositions']:names[spec['path']]=spec['sha256']
    names[receipt['baseline_snapshot_path']]=receipt['baseline_snapshot_sha256']
    for name,expected in names.items():
        raw=safe(root,aliases.get(name,name)).read_bytes();value={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
        require(value['sha256']==expected and actual['input_bindings'].get(name)==value,'historical source not authenticated: '+name)
        contents[name]=raw;before[name]=value
    continuation=segment(root)
    for role,name in role_paths().items():
        raw=continuation[{'summary':'summary_bytes','run_manifest':'manifest_bytes'}.get(role,role)]
        value={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
        require(actual['input_bindings'].get(name)==value,'n source binding mismatch');before[name]=value
    for key in ('carried_final_slots','carried_issued_slots','continuation_slots'):
        require(freeze[key]==receipt[key],'freeze receipt count mismatch')
    result=evaluate_recovered(data['corpus'],data['dossiers'],data['study'],data['sessions'],receipt,contents,
        continuation,prefix,actual,diagnostic=diagnostic)
    require(result['summary']['status']==(PARTIAL if diagnostic else COMPLETE),'wrong recovery result branch')
    views=selected_views(root,result,aliases)
    for name,value in before.items():require(binding(safe(root,aliases.get(name,name)))==value,'source changed during scoring')
    for name,value in actual['input_bindings'].items():
        target=ledger_snapshot if name==LEDGER else aliases.get(name,name)
        require(binding(safe(root,target))==value,'runtime input changed during scoring')
    verify_inventory(root,freeze_sha256,aliases)
    result['summary']['file_evidence']={'execution_freeze':{'path':FREEZE,'sha256':freeze_sha256},
        'source_files':before,'runtime_input_bindings':actual['input_bindings'],'frozen_aliases':aliases,
        'ledger_snapshot':{'path':ledger_snapshot,'sha256':ledger_snapshot_sha256},
        'runtime_and_prefix_replayed':True,'all_input_bindings_rechecked_after_scoring':True}
    return result,views


def write_outputs(root,result,views,*,diagnostic=False):
    root=Path(root).resolve();summary=result['summary'];target=PARTIAL_OUTPUT if diagnostic else OUTPUT
    require(summary['status']==(PARTIAL if diagnostic else COMPLETE),'publication branch')
    require(summary['planned_slots']==1800 and summary['frozen_diagnostic']['schedule_complete'] is False,
            'preserved diagnostic denominator')
    require((summary['amended_recovered_complete'] is None)==diagnostic,'explicit separate sensitivity')
    evidence=summary['file_evidence'];aliases=evidence['frozen_aliases'];directory=safe(root,target)
    require(not directory.exists(),'exclusive new result directory required')
    def recheck():
        require(not safe(root,LOCK).exists(),'n continuation remains active')
        for name,value in evidence['source_files'].items():
            require(binding(safe(root,aliases.get(name,name)))==value,'source changed before publication')
        for name,value in evidence['runtime_input_bindings'].items():
            target=evidence['ledger_snapshot']['path'] if name==LEDGER else aliases.get(name,name)
            require(binding(safe(root,target))==value,'runtime evidence changed before publication')
        verify_inventory(root,evidence['execution_freeze']['sha256'],aliases)
    encode=lambda x:(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    payloads={'score.json':encode(summary),'score-audits.json':encode(result['audits']),
        'requests.jsonl':views['requests'],'responses.jsonl':views['responses'],'slot-outcomes.jsonl':views['outcomes'],
        'source-provenance.json':encode(result['merged_evidence']['source_provenance']),
        'recovered-closure.json':encode(summary['operational_summary'])}
    recheck();directory.mkdir(parents=True,exist_ok=False)
    for name,raw in payloads.items():
        with (directory/name).open('xb') as stream:stream.write(raw)
    recheck()
    manifest={'schema':'retrace.frontier-v6n-composite-artifacts.v1','status':summary['status'],
        'writer_sha256':sha(Path(__file__)),'files':[{'path':target+'/'+name,'sha256':hashlib.sha256(raw).hexdigest(),
            'bytes':len(raw)} for name,raw in payloads.items()],
        'source_bindings':evidence['source_files'],'runtime_input_bindings':evidence['runtime_input_bindings'],
        'scope':'Original source lines are selected byte-for-byte. Both derived recovery dispositions are explicitly identified; no provider response is synthesized.'}
    with (directory/'composite-manifest.json').open('xb') as stream:stream.write(encode(manifest))
    return manifest


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--freeze-sha256',required=True)
    p.add_argument('--prefix-proof-sha256',required=True);p.add_argument('--n-audit-sha256',required=True)
    p.add_argument('--ledger-snapshot',default=SNAPSHOT);p.add_argument('--ledger-snapshot-sha256',required=True)
    p.add_argument('--aliases',type=Path);p.add_argument('--diagnostic',action='store_true');a=p.parse_args()
    aliases=_strict(a.aliases.read_bytes()) if a.aliases else {}
    result,views=compute(a.root,a.freeze_sha256,a.prefix_proof_sha256,a.n_audit_sha256,a.ledger_snapshot,
        a.ledger_snapshot_sha256,frozen_aliases=aliases,diagnostic=a.diagnostic)
    write_outputs(a.root,result,views,diagnostic=a.diagnostic)
    print(json.dumps({'status':result['summary']['status'],'planned_slots':1800,
        'actual_issued_attempts':result['summary']['request_accounting']['actual_issued_attempts']}))


if __name__=='__main__':main()
