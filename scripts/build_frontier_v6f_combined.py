"""Slot-preserving concatenation: diagnostics first in each model queue, no adaptation."""
from pathlib import Path
from collections import Counter
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.adaption_v6f import validate_slots


def combine(primary,regression):
    if len(primary)!=4560 or len(regression)!=80:raise ValueError('Unexpected fixed study sizes')
    joined=regression+primary
    validate_slots(joined)
    if set(Counter(s['model'] for s in joined).values())!={928}:raise ValueError('Expected928 slots per model')
    if any(s['phase']!='development_regression' for s in regression):raise ValueError('Diagnostic phase mismatch')
    return joined


if __name__=='__main__':
    primary=ROOT/'data/frontier-v6f-sessions.json';regression=ROOT/'data/frontier-v6f-regression-sessions.json'
    joined=combine(json.loads(primary.read_text(encoding='utf-8')),json.loads(regression.read_text(encoding='utf-8')))
    destination=ROOT/'data/frontier-v6f-combined-sessions.json'
    with destination.open('x',encoding='utf-8',newline='\n') as f:json.dump(joined,f,ensure_ascii=False,indent=2);f.write('\n')
    design={'schema':'retrace.frontier-v6f-combined-design.v1','planned':4640,'primary':4560,'development_regression':80,
            'model_queue_order':'For each model,16 already-observed regression requests then912 primary requests. Models progress independently under one global pacing/budget ledger.',
            'adaptation_after_regression':False,'primary_frozen_before_any_combined_call':True,
            'sources':[{'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (primary,regression)],
            'combined_sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
            'journal_views':'scripts/split_frontier_v6f.py creates exact line-preserving views with complete source-line hash mapping; full raw journals stay intact.'}
    with (ROOT/'data/frontier-v6f-combined-design.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(design,f,indent=2);f.write('\n')
    print('Created4640 immutable planned slots; no model calls.')
