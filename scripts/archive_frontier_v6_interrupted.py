"""Archive interrupted diagnostics without rewriting any original artifact."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = ROOT / 'results/frontier-v6-interrupted'
    output.mkdir(exist_ok=False)
    baseline = json.loads((ROOT / 'data/v6-baseline-preservation.json').read_text(encoding='utf-8'))['protected']
    for relative, expected in baseline.items():
        if sha(ROOT / relative) != expected:
            raise ValueError('Protected v5 file changed: ' + relative)
    closure = json.loads((ROOT / 'data/frontier-v6f-manual-closure.json').read_text(encoding='utf-8'))
    for value in closure['preserved'].values():
        if sha(ROOT / value['path']) != value['sha256']:
            raise ValueError('Stopped journal changed')
    paths = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'results/frontier-v6f').rglob('*') if p.is_file()}
    paths.update(p.relative_to(ROOT).as_posix() for folder in ('data', 'retrace', 'scripts', 'tests', 'research')
                 for p in (ROOT / folder).glob('*v6g*') if p.is_file())
    paths.update(['data/frontier-v6f-manual-closure.json', 'data/frontier-v6f-primary-freeze.json',
                  'data/frontier-v6f-authorization.json', 'scripts/close_idle_frontier-v6f.py'.replace('frontier-v6f', 'frontier_v6f')])
    entries = [{'path': p, 'sha256': sha(ROOT / p), 'bytes': (ROOT / p).stat().st_size} for p in sorted(paths)]
    manifest = {'schema': 'retrace.interrupted-diagnostic.v1', 'archived_at': datetime.now(timezone.utc).isoformat(),
                'status': 'interrupted_diagnostic', 'paid_runner_active_at_archive': False,
                'process_check': 'Get-CimInstance Win32_Process found no Python run_frontier or hold_runner process before archive.',
                'original_closure': closure, 'v5_files_verified': len(baseline),
                'new_g_paid_calls': 0, 'conservative_cumulative_credits': '43.633207445',
                'cap_credits': '250', 'files': entries,
                'interpretation': '38 f development-regression responses are retained; zero f primary calls. The unfinished g runtime is archival development code, not certified runnable. No result repaired, deleted, pooled or replaced. New unified semantics require new prospective manifests.'}
    with (output / 'manifest.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2); stream.write('\n')
    archive = output / 'frontier-v6-interrupted.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as package:
        package.write(output / 'manifest.json', 'manifest.json')
        for entry in entries:
            package.write(ROOT / entry['path'], 'originals/' + entry['path'])
    with zipfile.ZipFile(archive) as package:
        if package.testzip() is not None:
            raise ValueError('Archive CRC failure')
        for entry in entries:
            if hashlib.sha256(package.read('originals/' + entry['path'])).hexdigest() != entry['sha256']:
                raise ValueError('Archive hash mismatch')
    result = {'archive': archive.relative_to(ROOT).as_posix(), 'sha256': sha(archive),
              'files_verified': len(entries), 'v5_verified': len(baseline), 'new_api_calls': 0}
    with (output / 'archive-verification.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
