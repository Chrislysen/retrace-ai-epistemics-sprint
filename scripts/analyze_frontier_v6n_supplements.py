"""Post-closure descriptive analyses of unchanged recovered evidence; zero API calls.

Reuses the independently reviewed pure helpers. Their outputs are separate from
both the original diagnostic and the explicitly amended recovery sensitivity.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import frontier_v6n_products as products
from retrace.frontier_v6j_trajectory import analyze_trajectories
from retrace.frontier_v6j_refuter_partitions import analyze_refuter_partitions
from retrace.frontier_v6l_missingness import analyze as analyze_missingness

score = products.score
require = score.require
SELF = 'scripts/analyze_frontier_v6n_supplements.py'
TEST = 'tests/test_frontier_v6n_supplements.py'


def project(result, data):
    """Pure adapter: never substitute amended inference for frozen observations."""
    summary = result['summary']
    require(summary['status'] in (score.COMPLETE, score.PARTIAL), 'Explicit n result branch')
    frozen = summary['frozen_diagnostic']
    primary = [r for r in frozen['paired_comparisons']
               if r.get('view') == 'first_attempt' and r.get('primary_family_member') is True]
    require(len(primary) == 21 and all('p_two_sided_exact' in r and 'holm_adjusted_p' in r
            and r['p_two_sided_exact'] is None and r['holm_adjusted_p'] is None for r in primary)
            and frozen.get('cluster_intervals') == [],
            'Original diagnostic tests must remain unavailable')
    legacy = {'summary': frozen, 'audits': result['audits'], 'merged_evidence': result['merged_evidence']}
    before = score.json_value(result)
    outputs = {
        'k10-trajectory.json': analyze_trajectories(data['corpus'], data['study'], result['audits']),
        'refuter-partitions.json': analyze_refuter_partitions(data['corpus'], data['study'], result['audits']),
        'operational-missingness.json': analyze_missingness(data['study'], data['sessions'], legacy),
    }
    require(score.json_value(result) == before, 'Descriptive helper changed original evidence')
    return outputs


def directory(diagnostic):
    require(type(diagnostic) is bool, 'Explicit branch')
    return 'results/frontier-v6n/' + ('partial-' if diagnostic else '') + 'supplements'


def recheck(root, plan):
    require(not score.safe(root, score.LOCK).exists(), 'Recovery worker remains active')
    for role in ('authenticated_input_bindings', 'authenticated_source_bindings', 'analysis_source_bindings'):
        for name, wanted in plan[role].items():
            target = plan['frozen_aliases'].get(name, name)
            require(score.binding(score.safe(root, target)) == wanted, 'Supplement input changed: ' + name)


def run(root, freeze_sha256, prefix_proof_sha256, n_audit_sha256, ledger_snapshot, ledger_snapshot_sha256,
        *, frozen_aliases=None, diagnostic=False):
    root = Path(root).resolve()
    aliases = dict(frozen_aliases or {})
    require(not score.safe(root, directory(diagnostic)).exists(), 'Exclusive supplement destination required')
    starts = [SELF, 'scripts/frontier_v6n_products.py', 'scripts/score_frontier_v6n.py',
              'retrace/frontier_v6j_trajectory.py', 'retrace/frontier_v6j_refuter_partitions.py',
              'retrace/frontier_v6l_missingness.py']
    source_names = score.import_closure(root, starts) | {SELF, TEST}
    code = {name: score.binding(score.safe(root, name)) for name in sorted(source_names)}
    result, artifacts, sources, data = products.authenticated(root, freeze_sha256, prefix_proof_sha256,
        n_audit_sha256, ledger_snapshot, ledger_snapshot_sha256, frozen_aliases=aliases, diagnostic=diagnostic)
    outputs = project(result, data)
    plan = {
        'schema': 'retrace.frontier-v6n-descriptive-supplements-plan.v1',
        'diagnostic': diagnostic, 'study_status': result['summary']['status'],
        'authenticated_input_bindings': artifacts, 'authenticated_source_bindings': sources,
        'analysis_source_bindings': code, 'frozen_aliases': aliases, 'outputs': outputs,
        'replay_arguments': {'freeze_sha256': freeze_sha256, 'prefix_proof_sha256': prefix_proof_sha256,
            'n_audit_sha256': n_audit_sha256, 'ledger_snapshot': ledger_snapshot,
            'ledger_snapshot_sha256': ledger_snapshot_sha256},
    }
    recheck(root, plan)
    return plan


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def publish(root, plan):
    root = Path(root).resolve()
    require(plan['schema'] == 'retrace.frontier-v6n-descriptive-supplements-plan.v1', 'Validated plan required')
    names = {'k10-trajectory.json', 'refuter-partitions.json', 'operational-missingness.json'}
    require(set(plan['outputs']) == names, 'Exact descriptive output inventory')
    base = directory(plan['diagnostic'])
    target = score.safe(root, base)
    require(not target.exists(), 'Exclusive supplement destination required')
    recheck(root, plan)
    target.mkdir(parents=True, exist_ok=False)
    files = {}
    for name, value in plan['outputs'].items():
        path = score.safe(root, base + '/' + name)
        with path.open('xb') as stream:
            stream.write(encode(value))
        files[base + '/' + name] = score.binding(path)
    recheck(root, plan)
    receipt = {k: deepcopy(v) for k, v in plan.items() if k not in ('outputs', 'schema')}
    receipt.update({
        'schema': 'retrace.frontier-v6n-descriptive-supplements.v1',
        'created_at': datetime.now(timezone.utc).isoformat(), 'files': files,
        'provider_calls': 0, 'new_inferential_tests': 0, 'source_observations_changed': False,
        'scope': [
            'Post-freeze descriptive outputs, not new confirmatory endpoints or repaired observations.',
            'Original frozen diagnostic and separately amended recovery sensitivity remain unchanged.',
            'Operational missingness reports outer logical ranges, not confidence intervals, capability estimates or jointly attainable counterfactuals.',
            'Missingness excludes the nonmonotone K10 union endpoint. Truncation remains a fixed pipeline failure.',
            'Refuter partitions use controlled authored seed pools, not naturally unanimous extracted ensembles.',
        ],
    })
    with (target / 'manifest.json').open('xb') as stream:
        stream.write(encode(receipt))
    recheck(root, plan)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    for name in ('freeze-sha256', 'prefix-proof-sha256', 'n-audit-sha256', 'ledger-snapshot', 'ledger-snapshot-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--aliases', type=Path)
    parser.add_argument('--diagnostic', action='store_true')
    args = parser.parse_args()
    aliases = score._strict(args.aliases.read_bytes()) if args.aliases else {}
    plan = run(args.root, args.freeze_sha256, args.prefix_proof_sha256, args.n_audit_sha256,
        args.ledger_snapshot, args.ledger_snapshot_sha256, frozen_aliases=aliases, diagnostic=args.diagnostic)
    receipt = publish(args.root, plan)
    print(json.dumps({'schema': receipt['schema'], 'outputs': len(receipt['files']), 'provider_calls': 0}))


if __name__ == '__main__':
    main()
