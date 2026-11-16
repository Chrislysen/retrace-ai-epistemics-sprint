"""Hash the prospective scientific pipeline before credential access/dispatch."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_frontier_v6h import integrity,verify_corpus,verify_canary
from scripts.build_frontier_v6h_sessions import build
from scripts.build_frontier_v6h_canary import build as build_canary

def digest(path):return sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))

def freeze(phase,*,per_model_concurrency=8,global_concurrency=40):
    auth_path=ROOT/'data/frontier-v6h-authorization.json';auth=read(auth_path)
    integrity(auth,read(ROOT/'data/frontier-v6c-model-availability.json'))
    corpus_path=ROOT/'data/frontier-v6h-corpus.json';corpus=read(corpus_path)
    verify_corpus(corpus_path,digest(corpus_path))
    dossiers=read(ROOT/'data/frontier-v6h-dossiers.json')
    if dossiers['source_corpus_sha256']!=digest(corpus_path):raise ValueError('Dossier source hash')
    if read(ROOT/'data/frontier-v6h-sessions.json')!=build(corpus,dossiers):raise ValueError('Main sessions differ from audited projection')
    if read(ROOT/'data/frontier-v6h-canary-sessions.json')!=build_canary():raise ValueError('Canary projection mismatch')
    required=[
        'retrace/frontier_v6h_eval.py','scripts/score_frontier_v6h.py',
        'scripts/score_frontier_v6h_canary.py','tests/test_frontier_v6h_eval.py',
        'tests/test_frontier_v6h_canary.py','tests/test_frontier_v6h_sessions.py',
        'research/frontier-v6h-protocol.md','research/frontier-v6h-session-audit.md',
        'research/frontier-v6h-ecological-review.md','research/frontier-v6h-synthetic-audit.md',
        'research/tiered-v6h-audit.md','research/frontier-v6h-scoring-audit.md',
        'research/frontier-v6h-canary-audit.md','results/frontier-v6h-synthetic-audit.json',
        'results/frontier-v6h-preflight.json']
    if any(not (ROOT/p).is_file() for p in required):raise ValueError('Scientific audit/scorer/preflight prerequisite missing')
    preflight=read(ROOT/'results/frontier-v6h-preflight.json')
    if preflight.get('passed') is not True or preflight.get('new_paid_calls')!=0:raise ValueError('Preflight not passed before inference')
    for relative,expected in preflight.get('checked_files',{}).items():
        if digest(ROOT/relative)!=expected:raise ValueError('Preflight inputs changed: '+relative)
    paths={ROOT/p for p in auth['protected']}
    paths.update(ROOT/p for p in required)
    # Freeze all currently present Python source/tests, including imported older
    # implementations. Future additive report/release files are not prerequisites.
    for folder in ('retrace','scripts','tests'):
        paths.update((ROOT/folder).rglob('*.py'))
    for pattern in ('data/frontier-v6h-*.json','research/*v6h*.md','research/*v6h*.json','requirements*.txt'):
        paths.update(ROOT.glob(pattern))
    source=read(ROOT/'research/ecological-v6h-sources.json')
    for row in source['snapshot_inventory']:
        path=ROOT/row['path']
        if digest(path)!=row['sha256']:raise ValueError('Source snapshot hash')
        paths.add(path)
    paths.add(ROOT/'data/frontier-v6c-model-availability.json')
    if phase=='canary':
        if (per_model_concurrency,global_concurrency)!=(8,40):raise ValueError('Fixed canary configuration')
    elif phase=='primary':
        run=ROOT/'results/frontier-v6h/canary';summary=read(run/'summary.json');verify_canary(summary)
        if not (run/'semantic-score.json').is_file():raise ValueError('Canary semantic audit missing')
        if not 1<=per_model_concurrency<=64 or not 1<=global_concurrency<=384:raise ValueError('Concurrency bounds')
        paths.update(p for p in run.rglob('*') if p.is_file())
        ledger=ROOT/'results/frontier-v6h/budget/ledger.jsonl'
        prefix=ROOT/'data/frontier-v6h-ledger-before-primary.jsonl'
        with prefix.open('xb') as f:f.write(ledger.read_bytes())
        paths.add(prefix)
    else:raise ValueError('Phase')
    entries=[]
    for path in sorted(paths,key=lambda p:p.as_posix()):
        path=path.resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file():raise ValueError('Freeze path outside workspace or missing')
        entries.append({'path':path.relative_to(ROOT).as_posix(),'sha256':digest(path),'bytes':path.stat().st_size})
    value={'schema':'retrace.frontier-v6h-freeze.v1','phase':phase,'created_at':datetime.now(timezone.utc).isoformat(),
        'files':entries,'runtime_config':{'model_interval_seconds':2.0,'per_model_concurrency':per_model_concurrency,
            'global_concurrency':global_concurrency,'timeout_seconds':180.0,'max_retries':2},
        'case_count':60,'synthetic':48,'ecological':12,'long_dossiers':24,'study_slots':8148,'canary_slots':10,
        'protected_historical_files':len(auth['protected']),'cumulative_cap_credits':'250',
        'historical_carry_credits':auth['historical_conservative_carry_credits'],
        'prospective_protocol':'research/frontier-v6h-protocol.md',
        'scope':'Scientific source/prompt/runtime/scoring freeze. A complete canary includes observed semantic failures; no output-selected repair/retry. Retry attempts remain separate.'}
    output=ROOT/f'data/frontier-v6h-{phase}-freeze.json'
    with output.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
    return {'phase':phase,'files':len(entries),'path':output.relative_to(ROOT).as_posix(),'sha256':digest(output)}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--phase',choices=('canary','primary'),required=True)
    p.add_argument('--per-model-concurrency',type=int,default=8);p.add_argument('--global-concurrency',type=int,default=40)
    a=p.parse_args();print(json.dumps(freeze(a.phase,per_model_concurrency=a.per_model_concurrency,global_concurrency=a.global_concurrency)))
