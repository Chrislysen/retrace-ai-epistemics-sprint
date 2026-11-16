"""Offline constructed stress timing; no extraction or population claim."""
from pathlib import Path
from datetime import datetime, timezone
from time import perf_counter
import argparse
import hashlib
import json
import platform
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.refuter_impact_v6 import compare_readings


def fixture():
    ids = list('ABCDEFGHIJKLMNOP')
    def family(extra_route):
        rows = []
        for assignment in range(32):
            evidence = []
            for position, ident in enumerate(ids):
                parent = ['K'] if 4 <= position <= 8 and assignment & (1 << (position - 4)) else []
                evidence.append({'id': ident, 'kind': 'copy' if parent else 'root',
                                 'active': True, 'parents': parent})
            rows.append({'id': f'world-{assignment:02d}', 'graph': {
                'evidence': evidence,
                'claims': [{'id': 'warrant', 'supports': [[x] for x in ('ABCD' if extra_route else 'ABC')]}],
                'decisions': [{'id': 'release', 'requires': ['warrant']}],
            }})
        return rows
    return family(True), family(False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=20)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.repeats <= 1000:
        raise ValueError('Use a fresh output and1..1000 repetitions')
    current, proposed = fixture()
    durations = []
    result = None
    for _ in range(args.repeats + 1):
        started = perf_counter()
        result = compare_readings(current, proposed)
        durations.append((perf_counter() - started) * 1000)
        witness = result['decisions']['release']['minimum_consensus_loss']
        if witness['withdraw'] != list('ABC') or result['augmented_distinct_graphs'] != 64:
            raise AssertionError('Constructed exact result changed')
    cold, warm = durations[0], durations[1:]
    files = [Path(__file__).resolve(), ROOT/'retrace/refuter_impact_v6.py',
             ROOT/'retrace/stress_v6c.py', ROOT/'retrace/uncertainty_v6c.py', ROOT/'retrace/core.py']
    output = {
        'schema': 'retrace.constructed-refuter-impact-timing.v6',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(), 'system': platform.system(), 'architecture': platform.machine(),
        'input': {'current_graphs': 32, 'proposal_graphs': 32, 'evidence_ids': 16,
                  'withdrawal_subsets': 65536, 'nodes_per_graph': 18,
                  'independent_branch_choices': 5, 'branch_changes_decision_irrelevant': True,
                  'description': 'Constructed three-route versus four-route families; five unused copy/root choices create32 distinct graphs each. All baseline flags true, no vetoes. This is a stress fixture, not prose extraction or a worst-case DAG distribution.'},
        'cold_ms': cold, 'warm_repetitions': args.repeats,
        'warm_ms': warm, 'warm_median_ms': statistics.median(warm),
        'warm_min_ms': min(warm), 'warm_max_ms': max(warm),
        'result': result,
        'files': [{'path': p.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],
        'scope': 'Wall time on this host while the provider study is running. Includes graph validation, basis creation and full conditional-impact computation, without persistent caching. Warm means process/runtime warm only. Not a universal latency bound, clinical/real-world validation, model benchmark, or comparison against another solver.'
    }
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(output, stream, indent=2); stream.write('\n')
    print(json.dumps({k: output[k] for k in ('cold_ms','warm_repetitions','warm_median_ms','warm_min_ms','warm_max_ms')}))


if __name__ == '__main__':
    main()
