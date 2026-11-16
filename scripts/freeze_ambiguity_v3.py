"""Freeze the reviewed v3 corpus and tested scoring path before any inference."""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.ambiguity_v3_sessions import build_sessions, public_projection
from retrace.ambiguity_v3_eval import validate_packets

PATHS = [
    'data/ambiguity-v3-staged.json', 'data/ambiguity-v3-sessions.json', 'data/ambiguity-v3-plan.json',
    'retrace/ambiguity_v3_sessions.py', 'retrace/ambiguity_v3_eval.py', 'retrace/stress.py',
    'retrace/core.py', 'retrace/uncertainty.py', 'retrace/compact_graph.py', 'retrace/__init__.py',
    'scripts/run_adaption.mjs', 'scripts/prepare_ambiguity_v3.py', 'scripts/build_ambiguity_v3.py',
    'scripts/freeze_ambiguity_v3.py', 'scripts/summarize_ambiguity_v3.py',
    'tests/test_ambiguity_v3_oracle.py', 'tests/test_ambiguity_v3_pipeline.py', 'tests/test_stress.py', 'tests/test_stress_oracle.py',
    'tests/test_runner.mjs', 'research/ambiguity-v3-protocol.md',
    'research/ambiguity-v3-independent-review.md', 'research/unified-stress-engine.md',
    'results/ambiguity-reservation-audit.json', 'results/ambiguity-reservation-retirement.json',
    'results/ambiguity-v3-constructed-controls.json',
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_old_freezes():
    for filename in ['data/prose-freeze.json', 'data/extraction-v2-freeze.json']:
        for row in json.loads((ROOT / filename).read_text(encoding='utf-8'))['files']:
            if digest(ROOT / row['path']) != row['sha256']:
                raise RuntimeError('Original frozen file changed: ' + row['path'])


def main():
    destination = ROOT / 'data/ambiguity-v3-freeze.json'
    if destination.exists() or (ROOT / 'results/ambiguity-v3/gemma-4-31b-it/run.json').exists():
        raise RuntimeError('Refusing to refreeze an existing or started experiment')
    for name in PATHS:
        if not (ROOT / name).is_file():
            raise RuntimeError('Missing freeze dependency: ' + name)
    check_old_freezes()
    packets = json.loads((ROOT / PATHS[0]).read_text(encoding='utf-8'))
    sessions = json.loads((ROOT / PATHS[1]).read_text(encoding='utf-8'))
    plan = json.loads((ROOT / PATHS[2]).read_text(encoding='utf-8'))
    validate_packets(packets)
    if sessions != build_sessions(packets):
        raise RuntimeError('Provider sessions differ from the prospective public projection')
    encoded = json.dumps(sessions, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if hashlib.sha256(encoded).hexdigest() != plan['sessions_sha256']:
        raise RuntimeError('Plan/session digest mismatch')
    for session in sessions:
        packet = next(p for p in packets if p['public']['id'] == session['case_id'])
        if json.loads(session['steps'][0]['input']) != public_projection(packet):
            raise RuntimeError('Nonpublic fields leaked into provider input')
    retirement = json.loads((ROOT / 'results/ambiguity-reservation-retirement.json').read_text(encoding='utf-8'))
    if digest(ROOT / 'results/ambiguity-reservation-audit.json') != retirement['audit_sha256']:
        raise RuntimeError('Reservation audit changed after retirement')
    reservation = retirement['fresh_reservations'][0]
    bound = plan['reserve_nanocredits_per_request'] * plan['planned_requests']
    if bound != 488652800 or plan['planned_requests'] != 20 or reservation['request_limit'] != 20:
        raise RuntimeError('Pilot exceeds its exact fresh reservation')
    before = {name: digest(ROOT / name) for name in PATHS}
    checks = []
    for command in [[sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                    ['node', '--test', 'tests/test_runner.mjs']]:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
        checks.append({'command': command, 'exit_code': completed.returncode,
                       'stdout': completed.stdout, 'stderr': completed.stderr})
        if completed.returncode:
            print(completed.stdout + completed.stderr)
            raise RuntimeError('Preflight test failed; no freeze or API calls permitted')
    if before != {name: digest(ROOT / name) for name in PATHS}:
        raise RuntimeError('A freeze dependency changed during preflight')
    freeze = {'schema': 'retrace.ambiguity-v3-freeze.v1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'files': [{'path': name, 'sha256': before[name]} for name in PATHS],
              'settings': plan, 'preflight_checks': checks,
              'source': '10 authored synthetic packets; two directed temperature-zero prompts each',
              'review': 'Independent AI public-first source reconstruction; not human annotation',
              'scope': 'Local integrity freeze, not external timestamping or a claim of natural-document generalization.'}
    with destination.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(freeze, indent=2) + '\n')
    print(json.dumps({'freeze': str(destination), 'sha256': digest(destination),
                      'files': len(PATHS), 'preflight': 'passed', 'planned_requests': 20}))


if __name__ == '__main__':
    main()
