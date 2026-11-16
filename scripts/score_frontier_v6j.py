"""Authenticate two closed segments and write an exclusive amended composite.

Offline only. Original source journals are never altered. Exported JSONL views
retain each selected source line's exact bytes and have a separate provenance map.
"""
from __future__ import annotations
import argparse
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PureWindowsPath
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retrace.frontier_v6j_eval import evaluate_composite, json_value
from scripts.audit_frontier_v6j_runtime import audit as audit_runtime

FREEZE = 'data/frontier-v6j-freeze.json'
OUTPUT = 'results/frontier-v6j/composite'
ALIASES = {'results/frontier-v6f/budget/active.lock':
           'provenance/frozen-locks/results/frontier-v6f/budget/active.lock.txt'}
INPUTS = {'corpus': 'data/frontier-v6h-corpus.json', 'dossiers': 'data/frontier-v6h-dossiers.json',
          'study': 'data/frontier-v6i-design.json', 'sessions': 'data/frontier-v6i-sessions.json',
          'receipt': 'data/frontier-v6j-continuation.json'}
AUDITS = {'original': 'results/frontier-v6i/primary/runtime-audit.json',
          'continuation': 'results/frontier-v6j/continuation/runtime-audit.json'}
PREFIXES = {'original': 'results/frontier-v6i/primary/', 'continuation': 'results/frontier-v6j/continuation/'}
NAMES = {'requests': 'requests.jsonl', 'responses': 'responses.jsonl', 'outcomes': 'slot-outcomes.jsonl',
         'summary': 'summary.json', 'run_manifest': 'run.json'}


def require(ok, why):
    if not ok: raise ValueError(why)


def strict(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    def bad(_): raise ValueError('nonfinite_json')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def safe(root, name):
    require(isinstance(name, str) and name and not Path(name).is_absolute()
            and not PureWindowsPath(name).is_absolute() and ':' not in name
            and all(p not in ('', '.', '..') for p in name.replace('\\', '/').split('/')), 'relative_member_required')
    path = (Path(root)/name).resolve()
    require(path.is_relative_to(Path(root).resolve()), 'member_escapes_root')
    return path


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def binding(path):
    return {'sha256': sha(path), 'bytes': Path(path).stat().st_size}


def import_closure(root, starts):
    """Root-relative local static import closure, without importing target files."""
    pending = list(starts); seen = set()
    while pending:
        name = pending.pop()
        if name in seen: continue
        path = safe(root, name); require(path.is_file(), 'missing_scoring_dependency')
        seen.add(name); package = list(Path(name).parts[:-1])
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            modules = []
            if isinstance(node, ast.Import): modules = [a.name.split('.') for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = package[:len(package)-node.level+1] if node.level else []
                modules = [base+node.module.split('.')] if node.module else [base+a.name.split('.') for a in node.names]
            for parts in modules:
                if parts and parts[0] in ('retrace', 'scripts'):
                    target = '/'.join(parts)+'.py'
                    if safe(root, target).is_file(): pending.append(target)
    return seen


def verify_inventory(root, expected_sha, aliases):
    require(aliases in ({}, ALIASES), 'unsupported_frozen_alias')
    path = safe(root, FREEZE)
    require(sha(path) == expected_sha, 'execution_freeze_hash')
    freeze = strict(path.read_bytes())
    require(freeze.get('schema') == 'retrace.frontier-v6j-freeze.v1', 'execution_freeze_schema')
    require(freeze.get('scheduled_slots') == 1800 and freeze.get('continuation_slots') == 1794
            and freeze.get('carried_issued_slots') == 6, 'amended_schedule_counts')
    inventory = {}
    for row in freeze['files']:
        name = row['path']; require(name not in inventory, 'duplicate_frozen_path')
        target = safe(root, aliases.get(name, name))
        require(binding(target) == {'sha256': row['sha256'], 'bytes': row['bytes']}, 'frozen_dependency_changed: '+name)
        inventory[name] = {'sha256': row['sha256'], 'bytes': row['bytes']}
    required = set(INPUTS.values()) | import_closure(root,
        ['scripts/score_frontier_v6j.py', 'retrace/frontier_v6j_eval.py', 'scripts/audit_frontier_v6j_runtime.py'])
    require(required <= set(inventory), 'missing_scientific_dependency')
    require(set(aliases) <= set(inventory), 'alias_not_in_freeze')
    return freeze, inventory


def segment(root, which):
    paths = {key: PREFIXES[which]+name for key, name in NAMES.items()}
    raw = {key: safe(root, name).read_bytes() for key, name in paths.items()}
    return {'paths': paths, **{k: raw[k] for k in ('requests', 'responses', 'outcomes')},
            'summary_bytes': raw['summary'], 'manifest_bytes': raw['run_manifest'],
            'summary': strict(raw['summary']), 'manifest': strict(raw['run_manifest'])}


def selected_source_lines(merged, segments, role):
    """Export selected original bytes, not a normalization of source records."""
    pointers = merged['source_provenance'][role]
    result = []
    cached = {name: (source[role].splitlines(keepends=True), hashlib.sha256(source[role]).hexdigest())
              for name, source in segments.items()}
    for pointer, row in zip(pointers, merged[role]):
        source = segments[pointer['segment']]
        lines, file_sha = cached[pointer['segment']]
        n = pointer['source_line_one_based']
        require(type(n) is int and 1 <= n <= len(lines), 'source_line_index')
        line = lines[n-1]
        require(source['paths'][role] == pointer['source_path'] and
                file_sha == pointer['source_file_sha256'] and
                hashlib.sha256(line).hexdigest() == pointer['source_line_sha256'], 'source_line_hash')
        require(strict(line) == row, 'selected_view_changed_source_row')
        result.append(line)
    require(len(result) == len(merged[role]) == len(pointers), 'view_provenance_count')
    return b''.join(result)


def compute(root, freeze_sha256, original_audit_sha256, continuation_audit_sha256,
            ledger_snapshot, ledger_snapshot_sha256, *, frozen_aliases=None):
    """Return authenticated objects only; no writes and no provider access."""
    root = Path(root).resolve(); aliases = dict(frozen_aliases or {})
    freeze, inventory = verify_inventory(root, freeze_sha256, aliases)
    require(ledger_snapshot != 'results/frontier-v6j/budget/ledger.jsonl', 'immutable_ledger_snapshot_required')
    snap = safe(root, ledger_snapshot)
    require(sha(snap) == ledger_snapshot_sha256, 'ledger_snapshot_hash')
    expected_audits = {'original': original_audit_sha256, 'continuation': continuation_audit_sha256}
    before = {name: binding(safe(root, name)) for name in set(INPUTS.values()) | set(AUDITS.values()) | {ledger_snapshot, FREEZE}}
    saved = {}
    for key, name in AUDITS.items():
        require(before[name]['sha256'] == expected_audits[key], 'saved_runtime_audit_hash')
        saved[key] = strict(safe(root, name).read_bytes())
    actual = json_value(audit_runtime(root, freeze_sha256, frozen_aliases=aliases, ledger_snapshot=ledger_snapshot))
    require(actual == saved['continuation'] and actual['original_audit'] == saved['original'], 'runtime_audits_do_not_reproduce')
    require(actual.get('passed') is True and actual.get('final_closed') is True and
            actual.get('schedule_status') == 'completed' and actual.get('all_scheduled_outcomes_accounted') is True,
            'continuation_not_complete')
    originals = segment(root, 'original'); continued = segment(root, 'continuation')
    for which, s in (('original', originals), ('continuation', continued)):
        for role, name in s['paths'].items():
            raw = s['summary_bytes'] if role == 'summary' else s['manifest_bytes'] if role == 'run_manifest' else s[role]
            value = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
            require(actual['input_bindings'].get(name) == value, 'runtime_bindings_differ_from_composite_source')
            before[name] = value
    require(actual['input_bindings'].get('results/frontier-v6j/budget/ledger.jsonl') == binding(snap), 'runtime_ledger_binding')
    data = {key: strict(safe(root, name).read_bytes()) for key, name in INPUTS.items()}
    result = json_value(evaluate_composite(data['corpus'], data['dossiers'], data['study'], data['sessions'], data['receipt'],
                                           originals, continued, saved))
    require(result['summary']['status'] == 'complete_amended_primary' and result['summary']['primary_holm_family_size'] == 21,
            'incomplete_amended_scientific_result')
    views = {role: selected_source_lines(result['merged_evidence'], {'original': originals, 'continuation': continued}, role)
             for role in ('requests', 'responses', 'outcomes')}
    for name, value in before.items(): require(binding(safe(root, name)) == value, 'source_changed_during_scoring')
    for name, value in actual['input_bindings'].items():
        target = ledger_snapshot if name == 'results/frontier-v6j/budget/ledger.jsonl' else aliases.get(name, name)
        require(binding(safe(root, target)) == value, 'runtime_evidence_changed_during_scoring')
    verify_inventory(root, freeze_sha256, aliases)
    result['summary']['file_evidence'] = {
        'execution_freeze': {'path': FREEZE, 'sha256': freeze_sha256}, 'source_files': before,
        'runtime_audits_replayed': True, 'runtime_input_bindings_rechecked_after_score': True, 'frozen_aliases': aliases,
        'ledger_snapshot': {'path': ledger_snapshot, 'sha256': ledger_snapshot_sha256},
        'scope': 'Amended composite only; original interrupted segment and rejected route remain unchanged.'}
    return result, views


def write_outputs(root, result, views):
    directory = safe(root, OUTPUT)
    require(not directory.exists(), 'composite_output_already_exists')
    # All serialization and evidence checks finish before the exclusive directory.
    encode = lambda obj: (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')
    payloads = {'score.json': encode(result['summary']), 'score-audits.json': encode(result['audits']),
        'requests.jsonl': views['requests'], 'responses.jsonl': views['responses'], 'slot-outcomes.jsonl': views['outcomes'],
        'source-provenance.json': encode(result['merged_evidence']['source_provenance']),
        'derived-closure.json': encode(result['summary']['operational_summary'])}
    directory.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        with (directory/name).open('xb') as stream: stream.write(raw)
    files = {OUTPUT+'/'+name: {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)} for name, raw in payloads.items()}
    manifest = {'schema': 'retrace.frontier-v6j-composite-artifacts.v1', 'status': 'complete_amended_primary',
        'planned_slots': 1800, 'carried_original_issued_slots': 6, 'continuation_slots': 1794,
        'source_rows_changed': False, 'selected_jsonl_source_bytes_preserved': True,
        'files': files, 'source_bindings': result['merged_evidence']['source_bindings'],
        'file_evidence': result['summary']['file_evidence'], 'writer_sha256': sha(Path(__file__)),
        'scope': 'Derived views and statistical analysis. No original runtime summary or journal is rewritten.'}
    with (directory/'composite-manifest.json').open('xb') as stream: stream.write(encode(manifest))
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=ROOT)
    for name in ('freeze-sha256', 'original-audit-sha256', 'continuation-audit-sha256', 'ledger-snapshot', 'ledger-snapshot-sha256'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--aliases', type=Path)
    a = p.parse_args()
    require(not safe(a.root, OUTPUT).exists(), 'composite_output_already_exists')
    aliases = strict(a.aliases.read_bytes()) if a.aliases else {}
    result, views = compute(a.root, a.freeze_sha256, a.original_audit_sha256, a.continuation_audit_sha256,
                            a.ledger_snapshot, a.ledger_snapshot_sha256, frozen_aliases=aliases)
    manifest = write_outputs(a.root, result, views)
    print(json.dumps({'status': manifest['status'], 'planned_slots': 1800,
                      'issued_attempts': result['summary']['issued_attempts_observed'], 'output': OUTPUT,
                      'holm_family': result['summary']['primary_holm_family_size'], 'source_rows_changed': False}))


if __name__ == '__main__':
    main()
