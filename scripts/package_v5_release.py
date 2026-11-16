"""Create an immutable, credential-screened offline release; never overwrites files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from datetime import datetime, timezone
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / 'data/v5-release-freeze.json'
ARCHIVE = ROOT / 'deliverables/retrace-v5-sprint-artifact.zip'
RECEIPT = ROOT / 'deliverables/retrace-v5-artifact-sha256.json'
DIRECTORIES = ('data', 'results', 'retrace', 'scripts', 'tests', 'web', 'research', 'report')
ROOT_FILES = ('README.md', 'REPRODUCE-V5.md', 'pyproject.toml', '.gitignore',
              'start-retrace.ps1', 'start-retrace-v5.ps1')
FORBIDDEN_PARTS = {'.git', '.retrace', 'private', 'node_modules', '__pycache__', '.venv'}
TEXT_SUFFIXES = {'.json', '.jsonl', '.py', '.mjs', '.js', '.html', '.css', '.md',
                 '.txt', '.ps1', '.toml', '.bib', '.log'}
LIVE_KEY = re.compile(rb'pt_live_[A-Za-z0-9]{20,}')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def members():
    found = {ROOT / name for name in ROOT_FILES}
    report_manifest = json.loads((ROOT / 'report/v4-cycle/render-manifest.json').read_text(encoding='utf-8'))
    final_render_name = Path(report_manifest['render_directory']).name
    for directory in DIRECTORIES:
        for path in (ROOT / directory).rglob('*'):
            rel = path.relative_to(ROOT)
            if not path.is_file() or any(part in FORBIDDEN_PARTS for part in rel.parts):
                continue
            if path.name.startswith(('.env', '~$')) or path.suffix in {'.pyc', '.pyo'}:
                continue
            if rel.parts[:2] == ('report', 'v4-cycle') and len(rel.parts) > 3:
                folder = rel.parts[2]
                if folder == 'canonical-render' or (folder.startswith('render-') and folder != final_render_name):
                    continue
            if path == FREEZE:
                continue
            found.add(path)
    return sorted(found, key=lambda p: p.relative_to(ROOT).as_posix())


def main():
    for output in (FREEZE, ARCHIVE, RECEIPT):
        if output.exists():
            raise SystemExit(f'Refusing to overwrite {output.relative_to(ROOT)}')
    validation_path = ROOT / 'results/retrace-v5-release-validation.json'
    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    if validation.get('status') != 'passed':
        raise SystemExit('A passed release-validation record is required')
    contents = {}
    for path in members():
        raw = path.read_bytes()
        if path.suffix.lower() in TEXT_SUFFIXES and LIVE_KEY.search(raw):
            raise SystemExit(f'Credential-like value detected in {path.relative_to(ROOT)}')
        contents[path.relative_to(ROOT).as_posix()] = raw
    manifest = {
        'schema': 'retrace.v5-release-freeze.v1',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'Offline research artifact, including unchanged historical evidence. No new model calls.',
        'files': [{'path': name, 'sha256': digest(raw), 'bytes': len(raw)}
                  for name, raw in contents.items()],
        'validation_sha256': digest(validation_path.read_bytes()),
        'archive': ARCHIVE.relative_to(ROOT).as_posix(),
        'archive_hash_location': RECEIPT.relative_to(ROOT).as_posix(),
        'credential_scan': 'No Adaption live-key-shaped strings in packaged text files.',
    }
    freeze_raw = json_bytes(manifest)
    with FREEZE.open('xb') as handle:
        handle.write(freeze_raw)
    contents[FREEZE.relative_to(ROOT).as_posix()] = freeze_raw
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ARCHIVE, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 14, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(ARCHIVE) as archive:
        if sorted(archive.namelist()) != sorted(contents):
            raise RuntimeError('Archive member inventory mismatch')
        for name, expected in contents.items():
            if archive.read(name) != expected:
                raise RuntimeError(f'Archive byte mismatch: {name}')
    receipt = {
        'schema': 'retrace.v5-release-archive.v1',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'archive': ARCHIVE.relative_to(ROOT).as_posix(),
        'sha256': digest(ARCHIVE.read_bytes()),
        'bytes': ARCHIVE.stat().st_size,
        'members_verified_byte_for_byte': len(contents),
        'release_freeze_sha256': digest(freeze_raw),
        'validation_sha256': digest(validation_path.read_bytes()),
    }
    with RECEIPT.open('xb') as handle:
        handle.write(json_bytes(receipt))
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
