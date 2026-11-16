"""Freeze or execute the isolated 750-credit host-loss recovery; no implicit calls.

Only --execute-sha256 sends requests. New outputs are exclusive, credentials
arrive on stdin, and the entire immutable 1800-slot scientific schedule is reused.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import os
import json
from pathlib import Path
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.adaption_v6n import (AiohttpTransport, BASELINE_LEDGER, DEADLINE,
    RUNTIME_CONFIG, RollingLedger, digest, require, run_slots,
    verify_execution_manifest, verify_prior_ledger, verify_continuation)
from retrace.frontier_v6i_eval import design as validate_design
from scripts.build_frontier_v6i_sessions import build, SOURCE_PATHS
from scripts.run_frontier_v6h import verify_corpus
from scripts.score_frontier_v6h import local_dependencies
from scripts.host_guard_v6n import keep_system_awake

AUTH = 'data/frontier-v6n-authorization.json'
FREEZE = 'data/frontier-v6n-freeze.json'
SESSIONS = 'data/frontier-v6i-sessions.json'
DESIGN = 'data/frontier-v6i-design.json'
CONTINUATION = 'data/frontier-v6n-continuation.json'
PRIOR_FREEZE = 'data/frontier-v6m-freeze.json'
PRIOR_FREEZE_SHA = 'd8820db0702d53169d4afac813756414e4d67fffd25d31ef312695181023da10'
OBSERVED_ROUTES = {'qwen3.5-397b':'qwen3.5-397b-a17b-nvfp4'}
BASE = 'results/frontier-v6n'
OUTPUT = BASE+'/continuation'
LEDGER = BASE+'/budget'
TESTS = ('tests.test_adaption_v6n','tests.test_host_guard_v6n',
    'tests.test_recovery_v6n',
    'tests.test_frontier_v6n_prefix','tests.test_frontier_v6n_runtime_audit',
    'tests.test_frontier_v6n_driver','tests.test_frontier_v6n_eval','tests.test_score_frontier_v6n',
    'tests.test_frontier_v6i_sessions','tests.test_frontier_v6i_eval')
NEW_FILES = (AUTH,CONTINUATION,SESSIONS,DESIGN,
    'scripts/run_frontier_v6n.py','scripts/authorize_frontier_v6n.py',
    'scripts/audit_frontier_v6n_prefix.py','scripts/audit_frontier_v6n_runtime.py',
    'scripts/score_frontier_v6n.py','scripts/host_guard_v6n.py','scripts/launch_frontier_v6n.py',
    'results/frontier-v6n-recovery/console-probe.json',
    'results/frontier-v6n-recovery/console-io-proof.txt',
    'results/frontier-v6n-recovery/console-probe-v2.json',
    'results/frontier-v6n-recovery/console-io-proof-v2.txt',
    'results/frontier-v6n-recovery/launch-source-before-optimization-fix.py.txt',
    'retrace/adaption_v6n.py','retrace/recovery_v6n.py','retrace/frontier_v6n_eval.py',
    'tests/test_adaption_v6n.py','tests/test_host_guard_v6n.py','tests/test_recovery_v6n.py',
    'tests/test_frontier_v6n_prefix.py',
    'tests/test_frontier_v6n_runtime_audit.py','tests/test_frontier_v6n_driver.py',
    'tests/test_frontier_v6n_eval.py','tests/test_score_frontier_v6n.py',
    'research/frontier-v6n-recovery-interface.md','research/frontier-v6n-recovery-protocol.txt')


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))


def write_new(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False); f.write('\n')


def checked_path(relative):
    p=(ROOT/relative).resolve()
    require(p.is_relative_to(ROOT.resolve()) and p.is_file(),'invalid_frozen_path')
    return p


def historical_integrity(expected_auth=None):
    if expected_auth is not None: require(sha(ROOT/AUTH)==expected_auth,'authorization_changed')
    auth=read(ROOT/AUTH)
    require(auth['schema']=='retrace.frontier-v6n-authorization.v1' and auth['protected_v5_file_count']==402,'authorization_schema')
    require(auth['cumulative_cap_credits']=='750' and auth['previous_cumulative_cap_credits']=='750'
        and auth['prior_status']=='interrupted_without_closure' and auth['prior_stop_reason']=='process_exit_without_closure','authorization_budget')
    require(auth['deadline_utc']==DEADLINE.isoformat(),'authorization_deadline')
    require(auth['prior_freeze_path']==PRIOR_FREEZE and auth['prior_freeze_sha256']==PRIOR_FREEZE_SHA
        and sha(ROOT/PRIOR_FREEZE)==PRIOR_FREEZE_SHA,'prior_freeze_changed')
    old={r['path']:r['sha256'] for r in read(ROOT/PRIOR_FREEZE)['files']}
    require(all(auth['protected'].get(p)==h for p,h in old.items()) and
        auth['protected'].get(PRIOR_FREEZE)==PRIOR_FREEZE_SHA,'historical_inventory_incomplete')
    for name,expected in auth['protected'].items():
        require(sha(checked_path(name))==expected,'historical_dependency_changed: '+name)
    for version in ('h','i','j'):
        require(not (ROOT/f'results/frontier-v6{version}/budget/active.lock').exists(),'prior_worker_still_active')
    prior=verify_prior_ledger(ROOT/BASELINE_LEDGER,continuation_path=ROOT/CONTINUATION,
        continuation_sha256=sha(ROOT/CONTINUATION))
    require(prior['carry_credits']==auth['historical_conservative_carry_credits'] and
        prior['cumulative_inherited_unsettled_attempts']==auth['inherited_unsettled_attempts'],'authorization_carry')
    return auth


def fresh_destination():
    for name in ('results',BASE,OUTPUT,LEDGER,BASE+'/STOP'):
        p=(ROOT/name).resolve()
        require(p.is_relative_to(ROOT.resolve()) and p==ROOT.resolve()/name,'noncanonical_destination')
    require(not (ROOT/OUTPUT).exists(),'study_already_exists')
    require(not (ROOT/LEDGER).exists(),'ledger_already_exists')
    require(not (ROOT/BASE/'STOP').exists(),'stop_file_present')


def scientific_integrity():
    corpus,dossiers,old=[read(ROOT/name) for name in SOURCE_PATHS[:3]]
    study,slots=build(corpus,old,source_hashes={name:sha(ROOT/name) for name in SOURCE_PATHS})
    require(study==read(ROOT/DESIGN),'design_not_reproducible')
    require(slots==read(ROOT/SESSIONS),'sessions_not_reproducible')
    validate_design(corpus,dossiers,study,slots,True)
    verify_corpus(ROOT/SOURCE_PATHS[0],sha(ROOT/SOURCE_PATHS[0]))
    return slots


def continuation_integrity(slots,expected=None):
    actual=sha(ROOT/CONTINUATION)
    if expected is not None: require(actual==expected,'continuation_receipt_changed')
    r=read(ROOT/CONTINUATION)
    require(r['sessions_sha256']==digest(slots) and r['full_planned_slots']==1800,'continuation_scientific_schedule_changed')
    require(r['observed_response_models']==OBSERVED_ROUTES,'observed_route_changed')
    carry=verify_continuation(slots,ROOT/CONTINUATION,actual)
    require(len(carry['finals'])==r['carried_final_slots'] and len(carry['issued_slot_ids'])==r['carried_issued_slots'],'exact_prior_definitive_outcomes_required')
    require(carry['continuation_slot_ids']==r['continuation_slot_ids'] and
        len(carry['continuation_slot_ids'])==r['continuation_slots'] and
        0<r['continuation_slots']==1800-r['carried_final_slots'],'unissued_only_continuation')
    require(set(carry['finals']).isdisjoint(carry['continuation_slot_ids']),'no_reissued_final')
    return r


def fixed_contract(auth,receipt):
    return {'sessions_path':SESSIONS,'study_path':DESIGN,'output_path':OUTPUT,
        'ledger_path':LEDGER,'baseline_path':BASELINE_LEDGER,'scheduled_slots':1800,
        'continuation_path':CONTINUATION,'continuation_sha256':sha(ROOT/CONTINUATION),
        'observed_response_models':OBSERVED_ROUTES,'continuation_slots':receipt['continuation_slots'],
        'carried_issued_slots':receipt['carried_issued_slots'],'carried_final_slots':receipt['carried_final_slots'],
        'authorization_path':AUTH,'authorization_sha256':sha(ROOT/AUTH),
        'previous_cumulative_cap_credits':'750','cumulative_cap_credits':'750',
        'historical_conservative_carry_credits':auth['historical_conservative_carry_credits']}


def freeze():
    require(not (ROOT/FREEZE).exists(),'freeze_already_exists')
    require(datetime.now(timezone.utc)<DEADLINE,'delivery_buffer_reached')
    fresh_destination(); auth=historical_integrity(); slots=scientific_integrity()
    receipt=continuation_integrity(slots)
    paths={checked_path(name) for name in (*auth['protected'],*NEW_FILES)}
    paths|=local_dependencies([ROOT/'scripts/run_frontier_v6n.py',ROOT/'scripts/score_frontier_v6n.py'])
    before={p:sha(p) for p in paths}; capture=io.StringIO()
    result=unittest.TextTestRunner(stream=capture,verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(TESTS))
    preflight=ROOT/f'results/frontier-v6n-preflight-{uuid.uuid4().hex}.json'
    write_new(preflight,{'schema':'retrace.frontier-v6n-preflight.v1','created_at':datetime.now(timezone.utc).isoformat(),
        'passed':result.wasSuccessful(),'tests_run':result.testsRun,'tests':list(TESTS),'paid_calls':0,
        'python':sys.version,'aiohttp':importlib.metadata.version('aiohttp'),'log':capture.getvalue(),
        'scope':'Authenticated unclosed k/m prefixes and two separate derived orphan failures;750-credit ledger; unchanged request/transport algorithms; separate amended recovery inference.'})
    require(result.wasSuccessful(),'preflight_failed: '+str(preflight))
    for p,expected in before.items(): require(sha(p)==expected,'dependency_changed_during_preflight')
    historical_integrity(); fresh_destination(); paths.add(preflight)
    manifest={'schema':'retrace.frontier-v6n-freeze.v1','created_at':datetime.now(timezone.utc).isoformat(),
        **fixed_contract(auth,receipt),'files':[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(paths)],
        'sessions_sha256':digest(slots),'sessions_file_sha256':sha(ROOT/SESSIONS),
        'runtime_config':RUNTIME_CONFIG,'deadline_utc':DEADLINE.isoformat(),
        'baseline_sha256':sha(ROOT/BASELINE_LEDGER),'preflight_path':preflight.relative_to(ROOT).as_posix(),
        'scope':'Only untouched original slots continue after host interruption. The original k and m runs remain unclosed. All observed outcomes, raw bytes, orphan requests and full unknown bounds are preserved. The frozen diagnostic inference gate remains separate from the explicit amended recovered-complete sensitivity.'}
    write_new(ROOT/FREEZE,manifest)
    verify_execution_manifest(ROOT/FREEZE,sha(ROOT/FREEZE),slots)
    return {'path':FREEZE,'sha256':sha(ROOT/FREEZE),'files':len(manifest['files']),
        'offline_tests':result.testsRun,'planned_slots':1800,'continuation_slots':receipt['continuation_slots'],'paid_calls':0}


def verify_frozen(expected):
    require(sha(ROOT/FREEZE)==expected,'freeze_changed')
    f=read(ROOT/FREEZE); require(f['schema']=='retrace.frontier-v6n-freeze.v1','freeze_schema')
    auth=historical_integrity(f['authorization_sha256'])
    slots=read(ROOT/SESSIONS); receipt=continuation_integrity(slots,f['continuation_sha256'])
    require(all(f.get(k)==v for k,v in fixed_contract(auth,receipt).items()),'freeze_fixed_contract')
    inventory={r['path']:r for r in f['files']}
    require(len(inventory)==len(f['files']),'duplicate_frozen_file')
    require(set(auth['protected'])|set(NEW_FILES)<=set(inventory),'incomplete_freeze_inventory')
    needed=local_dependencies([ROOT/'scripts/run_frontier_v6n.py',ROOT/'scripts/score_frontier_v6n.py'])
    require({p.relative_to(ROOT).as_posix() for p in needed}<=set(inventory),'missing_execution_dependency')
    require(f['preflight_path'] in inventory and read(checked_path(f['preflight_path']))['passed'] is True,'passed_preflight_required')
    for r in f['files']:
        p=checked_path(r['path'])
        require(p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],'frozen_dependency_changed: '+r['path'])
    require(len(slots)==1800 and sha(ROOT/SESSIONS)==f['sessions_file_sha256'],'sessions_changed')
    require(sha(ROOT/BASELINE_LEDGER)==f['baseline_sha256'],'baseline_changed')
    verify_execution_manifest(ROOT/FREEZE,expected,slots)
    return slots


async def execute(expected):
    require(datetime.now(timezone.utc)<DEADLINE,'delivery_buffer_reached')
    slots=verify_frozen(expected); fresh_destination()
    key=sys.stdin.readline().strip()
    require(len(key)>=8 and not any(c.isspace() for c in key),'invalid_credential')
    require(datetime.now(timezone.utc)<DEADLINE,'delivery_buffer_reached')
    verify_frozen(expected); fresh_destination()
    ledger=None
    try:
        with keep_system_awake() as host_guard:
            (ROOT/BASE).mkdir(parents=True,exist_ok=True)
            write_new(ROOT/BASE/'host-guard.json',{'schema':'retrace.frontier-v6n-host-guard.v1',
                'created_at':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),
                'deadline_utc':DEADLINE.isoformat(),**host_guard})
            (ROOT/LEDGER).mkdir(parents=True,exist_ok=False)
            ledger=RollingLedger(ROOT/LEDGER,baseline_path=ROOT/BASELINE_LEDGER,
                continuation_path=ROOT/CONTINUATION,continuation_sha256=sha(ROOT/CONTINUATION))
            async with AiohttpTransport(key,180,1) as transport:
                return await run_slots(slots,api_key=key,output_dir=ROOT/OUTPUT,ledger=ledger,
                    transport=transport,execution_manifest_path=ROOT/FREEZE,
                    execution_manifest_sha256=expected,timeout_seconds=180,stop_file=ROOT/BASE/'STOP')
    finally:
        if ledger is not None: ledger.close()
        key=None



if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(); action.add_argument('--freeze',action='store_true'); action.add_argument('--execute-sha256')
    args=parser.parse_args()
    output=freeze() if args.freeze else asyncio.run(execute(args.execute_sha256)) if args.execute_sha256 else {'planned_slots':1800,'runtime':RUNTIME_CONFIG,'paid_calls':0}
    print(json.dumps(output,ensure_ascii=False,indent=2))
