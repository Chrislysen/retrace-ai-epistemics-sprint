"""Offline validation gate; preserve archived unfinished g rather than repair it."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import io,json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_frontier_v6h import integrity
from retrace.adaption_v6h import verify_prior_ledger,BASELINE_LEDGER

def sha(path):return sha256(path.read_bytes()).hexdigest()
def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item

def main():
    output=ROOT/'results/frontier-v6h-preflight.json';logpath=ROOT/'results/frontier-v6h-preflight.log'
    if output.exists() or logpath.exists():raise ValueError('Preflight artifacts already exist')
    if any((ROOT/'results/frontier-v6h').rglob('requests.jsonl')):raise ValueError('Pre-dispatch validation must precede paid h requests')
    auth=json.loads((ROOT/'data/frontier-v6h-authorization.json').read_text(encoding='utf-8'))
    models=json.loads((ROOT/'data/frontier-v6c-model-availability.json').read_text(encoding='utf-8'))
    protected=integrity(auth,models);prior=verify_prior_ledger(ROOT/BASELINE_LEDGER)
    modules=['tests.'+p.stem for p in sorted((ROOT/'tests').glob('test_*.py'))]
    found=list(flatten(unittest.defaultTestLoader.loadTestsFromNames(modules)))
    archived=[test.id() for test in found if test.id().startswith('tests.test_adaption_v6g.')]
    active=[test for test in found if test.id() not in set(archived)]
    capture=io.StringIO();result=unittest.TextTestRunner(stream=capture,verbosity=1).run(unittest.TestSuite(active))
    integrity(auth,models)
    files=set()
    for folder in ('retrace','scripts','tests'):files.update((ROOT/folder).rglob('*.py'))
    for pattern in ('data/frontier-v6h-*.json','research/*v6h*.md','research/*v6h*.json','requirements*.txt'):
        files.update(ROOT.glob(pattern))
    checked={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files)}
    report={'schema':'retrace.frontier-v6h-preflight.v1','created_at':datetime.now(timezone.utc).isoformat(),
        'passed':result.wasSuccessful(),'tests_run':result.testsRun,'failures':[t.id() for t,_ in result.failures],
        'errors':[t.id() for t,_ in result.errors],'skipped':[(t.id(),why) for t,why in result.skipped],
        'archived_module_excluded':'tests.test_adaption_v6g','archived_tests':archived,
        'exclusion_reason':'Unfinished unissued g transport was preserved byte-for-byte in the requested interrupted archive. Unfiltered discovery before this gate ran967 tests with23 errors in its stale ledger/auth code. New h does not import g. This gate does not conceal those historical failures or claim unfiltered discovery passes.',
        'protected_files_verified_before_and_after':protected,'new_paid_calls':0,
        'prior_ledger':prior,'checked_files':checked,'raw_test_log':logpath.relative_to(ROOT).as_posix()}
    with logpath.open('x',encoding='utf-8',newline='\n') as f:f.write(capture.getvalue())
    report['raw_test_log_sha256']=sha(logpath)
    with output.open('x',encoding='utf-8',newline='\n') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({k:report[k] for k in ('passed','tests_run','failures','errors','protected_files_verified_before_and_after','new_paid_calls')}))
    if not result.wasSuccessful():sys.exit(1)

if __name__=='__main__':main()
