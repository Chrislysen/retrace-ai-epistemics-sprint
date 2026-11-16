"""Stop the superseded Windows dispatch only at a verified no-request boundary.

This is a disclosed administrative closure, not a provider retry, normal runner
summary or rewrite of its ledger. Every issued response and charge is retained.
"""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import ctypes
from ctypes import wintypes
import hashlib
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PID, PARENT = 59408, 40016


def main():
    destination = ROOT/'data/frontier-v6f-manual-closure.json'
    if destination.exists(): raise ValueError('Closure already recorded')
    cmd = f'Get-CimInstance Win32_Process -Filter "ProcessId = {PID}" | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress'
    record = json.loads(subprocess.run(['powershell','-NoProfile','-Command',cmd],
                       capture_output=True, text=True, check=True).stdout)
    if (record['ParentProcessId'] != PARENT or 'run_frontier_v6f.py' not in record['CommandLine']
            or 'frontier-v6f/combined' not in record['CommandLine']):
        raise ValueError('Runner identity changed')
    api = ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    api.OpenProcess.restype=wintypes.HANDLE
    api.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
    api.TerminateProcess.restype=wintypes.BOOL
    api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    api.WaitForSingleObject.restype=wintypes.DWORD
    api.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=api.OpenProcess(0x1|0x100000,False,PID)
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    paths={name:ROOT/path for name,path in {
        'requests':'results/frontier-v6f/combined/requests.jsonl',
        'responses':'results/frontier-v6f/combined/responses.jsonl',
        'ledger':'results/frontier-v6f/budget/ledger.jsonl'}.items()}
    slots=json.loads((ROOT/'data/frontier-v6f-combined-sessions.json').read_text(encoding='utf-8'))
    by_id={s['slot_id']:s for s in slots}
    started=time.monotonic()
    try:
        while time.monotonic()-started < 1200:
            if (ROOT/'results/frontier-v6f/combined/summary.json').exists():
                raise ValueError('Runner closed itself; do not terminate')
            raw={name:path.read_bytes() for name,path in paths.items()}
            if any(not value.endswith(b'\n') for value in raw.values()):
                time.sleep(.5);continue
            rows={name:[json.loads(line) for line in value.splitlines()] for name,value in raw.items()}
            requests,responses=rows['requests'],rows['responses']
            if any(by_id[r['slot_id']]['phase']!='development_regression' for r in requests):
                raise ValueError('Primary issuance already began; this closure is not authorized by its boundary contract')
            counts=Counter(by_id[r['slot_id']]['model'] for r in requests)
            # All next queued calls must still be65K regression calls. If a
            # model has finished16, a shorter primary call could fit the window.
            if any(count>=16 for count in counts.values()):
                raise ValueError('A primary call may be next; no assured idle boundary')
            pending=set()
            for row in rows['ledger']:
                event=row['event']
                if event['kind']=='reserve': pending.add(event['attempt_id'])
                elif event['kind']=='settle': pending.remove(event['attempt_id'])
                elif event['kind']=='halt': raise ValueError('Operational halt recorded')
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(requests[-1]['at'])).total_seconds()
            ids={r['slot_id'] for r in requests}
            idle=(not pending and len(ids)==len(requests)==len(responses)
                  and ids=={r['slot_id'] for r in responses}
                  and all(r.get('terminal_valid') is True for r in responses)
                  and requests[-1]['admission_estimate']['weight']>50000 and 0<=age<=45)
            if not idle:
                time.sleep(.5);continue
            if any(path.read_bytes()!=raw[name] for name,path in paths.items()):continue
            # The last >50K start excludes all next65K calls until61s. With all
            # current calls settled and age<=45s, at least16s remain for this
            # synchronous termination. Never interrupt a paid in-flight call.
            closure={
                'schema':'retrace.frontier-v6f-administrative-closure.v1',
                'closed_at':datetime.now(timezone.utc).isoformat(),
                'reason':'Undocumented compiler target-type/constraint semantics discovered in the already-observed old8 development regression; correct contract before any primary inference.',
                'termination':'Verified-idle Windows process termination; original runner summary is absent and is not fabricated.',
                'pid':PID,'launcher_pid':PARENT,'issued_regression_requests':len(requests),
                'recorded_responses':len(responses),'issued_primary_requests':0,
                'outstanding_reservations_before_stop':0,'per_model_issued':dict(counts),
                'last_request_age_seconds':age,'next_requests_min_output_tokens':65536,
                'preserved':{name:{'path':path.relative_to(ROOT).as_posix(),
                                  'sha256':hashlib.sha256(raw[name]).hexdigest(),
                                  'bytes':len(raw[name])} for name,path in paths.items()},
                'primary_freeze_sha256':hashlib.sha256((ROOT/'data/frontier-v6f-primary-freeze.json').read_bytes()).hexdigest(),
                'retries':0,'interpretation':'All issued f outcomes stay in the f development record. The frozen f primary design is abandoned before issuance. A changed contract requires a new prospective freeze and separately labeled calls; no output is repaired or replaced.',
            }
            if not api.TerminateProcess(handle,101):raise ctypes.WinError(ctypes.get_last_error())
            if api.WaitForSingleObject(handle,10000)!=0:raise RuntimeError('Termination not observed')
            closure['journals_unchanged_after_stop']=all(path.read_bytes()==raw[name] for name,path in paths.items())
            if not closure['journals_unchanged_after_stop']:raise RuntimeError('Journal changed at closure boundary')
            with destination.open('x',encoding='utf-8',newline='\n') as stream:
                json.dump(closure,stream,indent=2);stream.write('\n')
            print(json.dumps(closure,indent=2));return
        raise TimeoutError('No verified idle boundary observed; runner was not killed')
    finally: api.CloseHandle(handle)


if __name__=='__main__':main()
