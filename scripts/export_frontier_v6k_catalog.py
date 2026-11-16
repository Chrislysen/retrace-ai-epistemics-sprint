"""Export ALL300 primary first-attempt IR observations after authenticated closure."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from retrace.evidence_catalog_v6k import build_catalog, encode, require, DIRECTORY, FREEZE_SHA256
from scripts.analyze_frontier_v6k_trajectory import authenticated_inputs
from scripts.score_frontier_v6k import safe, strict, binding, sha, INPUTS

SOURCES = ('retrace/evidence_catalog_v6k.py', 'scripts/export_frontier_v6k_catalog.py',
           'scripts/analyze_frontier_v6k_trajectory.py', 'retrace/source_ir_v6h.py')


def run(root, freeze_sha256, i_audit_sha256, j_audit_sha256, k_audit_sha256,
        ledger_snapshot, ledger_snapshot_sha256, *, frozen_aliases=None):
    """Authenticated, in-memory export plan; never reads live output before gate."""
    root = Path(root).resolve(); aliases = dict(frozen_aliases or {})
    require(freeze_sha256 == FREEZE_SHA256, 'Pinned k execution freeze required')
    require(not safe(root, DIRECTORY).exists(), 'Exclusive new catalog output required')
    code_before = {name: sha(safe(root, name)) for name in SOURCES}
    result, artifacts, sources, corpus, study = authenticated_inputs(root, freeze_sha256,
        i_audit_sha256, j_audit_sha256, k_audit_sha256, ledger_snapshot, ledger_snapshot_sha256,
        frozen_aliases=aliases)
    require(INPUTS['sessions'] in sources and binding(safe(root, INPUTS['sessions'])) == sources[INPUTS['sessions']],
            'Frozen session source binding required')
    slots = strict(safe(root, INPUTS['sessions']).read_bytes())
    catalog = build_catalog(corpus, study, slots, result['audits'], result['merged_evidence'])
    require(catalog['index']['scheduled_slots'] == 300 and not catalog['index']['test_fixture'], 'Full planned catalog only')
    for name, expected in artifacts.items():
        require(binding(safe(root, name)) == expected, 'Final artifact changed during catalog projection')
    for name, expected in sources.items():
        require(binding(safe(root, aliases.get(name, name))) == expected, 'Source changed during catalog projection')
    require(code_before == {name: sha(safe(root, name)) for name in SOURCES}, 'Exporter source changed during catalog projection')
    catalog['authentication'] = {'source_freeze_sha256': freeze_sha256, 'authenticated_input_bindings': artifacts,
        'authenticated_source_bindings': sources, 'exporter_source_sha256': code_before, 'frozen_aliases': aliases}
    return catalog


def verify_plan(root, authentication):
    """Rebind a prepared plan at the write boundary; no stale closure receipt."""
    aliases = authentication['frozen_aliases']
    for name, expected in authentication['authenticated_input_bindings'].items():
        require(binding(safe(root, name)) == expected, 'Final artifact changed before catalog publication')
    for name, expected in authentication['authenticated_source_bindings'].items():
        require(binding(safe(root, aliases.get(name, name))) == expected, 'Source changed before catalog publication')
    require(set(authentication['exporter_source_sha256']) == set(SOURCES), 'Exact exporter source inventory required')
    for name, expected in authentication['exporter_source_sha256'].items():
        require(sha(safe(root, name)) == expected, 'Exporter source changed before catalog publication')


def write_catalog(root, catalog):
    """Exclusive, content-bound files. The manifest is written last."""
    root = Path(root).resolve(); directory = safe(root, DIRECTORY)
    require(not directory.exists(), 'Exclusive new catalog output required')
    auth = catalog['authentication']; index = catalog['index']
    require(auth['source_freeze_sha256'] == FREEZE_SHA256 and index['scheduled_slots'] == 300
            and index['selection_view'] == 'first_attempt' and index['test_fixture'] is False, 'Authenticated full catalog required')
    payloads = {DIRECTORY+'/index.json': encode(index)}
    payloads.update({name: encode(value) for name, value in catalog['entries'].items()})
    payloads.update({name: encode(value) for name, value in catalog['bundles'].items()})
    require(len(index['entries']) == 300 and len(catalog['entries']) == 300, 'All300 rows required')
    for row in index['entries']:
        require(row['entry_path'] == DIRECTORY+'/entries/'+row['key']+'.json'
                and row['entry_sha256'] == sha256(payloads[row['entry_path']]).hexdigest(), 'Entry/index binding')
        if row['bundle_path'] is not None:
            require(row['bundle_path'] == DIRECTORY+'/bundles/'+row['key']+'.json'
                    and row['bundle_sha256'] == sha256(payloads[row['bundle_path']]).hexdigest(), 'Bundle/index binding')
    manifest = {'schema': 'retrace.evidence-catalog.v6k.v1', 'status': 'complete_amended_primary',
        'scheduled_slots': 300, 'selection_view': 'first_attempt', 'index_path': DIRECTORY+'/index.json',
        'files': {name: {'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)} for name, raw in payloads.items()},
        **auth, 'scope': index['scope']}
    # Everything is encoded and validated before creating the exclusive folder.
    for name in payloads:
        require(safe(root, name).is_relative_to(directory), 'Catalog path escapes exclusive folder')
    verify_plan(root, auth)
    directory.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        target = safe(root, name); target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream: stream.write(raw)
    verify_plan(root, auth)
    with (directory/'manifest.json').open('xb') as stream: stream.write(encode(manifest))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--root', type=Path, default=ROOT)
    for name in ('freeze-sha256', 'i-audit-sha256', 'j-audit-sha256', 'k-audit-sha256', 'ledger-snapshot', 'ledger-snapshot-sha256'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--aliases', type=Path); args = parser.parse_args()
    aliases = strict(args.aliases.read_bytes()) if args.aliases else {}
    catalog = run(args.root, args.freeze_sha256, args.i_audit_sha256, args.j_audit_sha256,
                  args.k_audit_sha256, args.ledger_snapshot, args.ledger_snapshot_sha256, frozen_aliases=aliases)
    manifest = write_catalog(args.root, catalog)
    print(json.dumps({'status': manifest['status'], 'scheduled_slots': 300, 'selection_view': 'first_attempt',
                      'output': DIRECTORY, 'counts': catalog['index']['counts']}))


if __name__ == '__main__': main()
