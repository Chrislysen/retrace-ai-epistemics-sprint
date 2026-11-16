"""Additive offline release guards; no calls, frozen-file writes, or model data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts.assemble_frontier_v6h_release import write_zip
from scripts.reproduce_frontier_v6h_release import canonical, safe_path, scan_credentials, sha, load, verify_inventory
import scripts.reproduce_frontier_v6h_release as verifier


class ReleaseV6hTests(unittest.TestCase):
    def inventory_fixture(self, root):
        """Full-size artificial freeze exercises the original-path lock mapping."""
        aliases={'results/old/budget/active.lock':'provenance/frozen-locks/results/old/budget/active.lock.txt'}
        frozen=[]
        for i in range(842):
            name='data/frozen-%04d.txt'%i
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(str(i).encode())
            frozen.append({'path':name,'sha256':sha(path)})
        name='data/frontier-v6h-canary-sessions.json';path=root/name
        path.write_text(json.dumps([{'slot_id':'canary-'+str(i),'condition':'canary_source_ir'} for i in range(10)]),encoding='utf-8')
        frozen.append({'path':name,'sha256':sha(path)})
        path=root/next(iter(aliases.values()));path.parent.mkdir(parents=True);path.write_bytes(b'old lock bytes')
        frozen.append({'path':next(iter(aliases)),'sha256':sha(path)})
        path=root/verifier.FREEZE;path.write_text(json.dumps({'files':frozen}),encoding='utf-8')
        required=set(verifier.ADDITIONS)|{verifier.LEDGER}|{verifier.RUN+'/'+n for n in
            ('run.json','requests.jsonl','responses.jsonl','slot-outcomes.jsonl','summary.json','semantic-score.json')}
        for name in required:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'')
        entries=[{'path':p.relative_to(root).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(root.rglob('*')) if p.is_file()]
        manifest={'schema':verifier.SCHEMA,'status':'diagnostic_primary_unissued','primary_study_complete':False,'primary_calls':0,
            'freeze':{'path':verifier.FREEZE,'sha256':sha(root/verifier.FREEZE)},'files':entries,'frozen_aliases':aliases,
            'symbolic_test_modules':list(verifier.SYMBOLIC_TESTS),'file_set_sha256':hashlib.sha256(canonical(entries).encode()).hexdigest()}
        return manifest

    def test_full_inventory_portable_lock_alias_and_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=self.inventory_fixture(root)
            with patch.object(verifier,'FREEZE_SHA',manifest['freeze']['sha256']):
                result=verify_inventory(root,manifest)
                self.assertEqual(result['frozen_files_verified'],844)
                (root/'data/frozen-0003.txt').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'changed'):verify_inventory(root,manifest)

    def test_missing_freeze_binding_even_with_rehashed_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=self.inventory_fixture(root)
            with patch.object(verifier,'FREEZE_SHA',manifest['freeze']['sha256']):
                manifest['files']=[r for r in manifest['files'] if r['path']!='data/frozen-0003.txt']
                manifest['file_set_sha256']=hashlib.sha256(canonical(manifest['files']).encode()).hexdigest()
                with self.assertRaisesRegex(ValueError,'Frozen dependency'):verify_inventory(root,manifest)

    def test_unknown_request_journal_and_illicit_alias_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=self.inventory_fixture(root)
            with patch.object(verifier,'FREEZE_SHA',manifest['freeze']['sha256']):
                bad=deepcopy(manifest);bad['frozen_aliases']['data/frozen-0003.txt']='data/frozen-0003.txt'
                with self.assertRaisesRegex(ValueError,'historical lock'):verify_inventory(root,bad)
                p=root/'results/frontier-v6h/new/requests.jsonl';p.parent.mkdir();p.write_bytes(b'')
                with self.assertRaisesRegex(ValueError,'Uninventoried request'):verify_inventory(root,manifest)

    def test_request_condition_is_resolved_from_frozen_slot_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=self.inventory_fixture(root)
            p=root/verifier.RUN/'requests.jsonl'
            p.write_text(json.dumps({'slot_id':'canary-0','request':{}})+'\n',encoding='utf-8')
            row=next(r for r in manifest['files'] if r['path']==p.relative_to(root).as_posix())
            row.update(sha256=sha(p),bytes=p.stat().st_size)
            manifest['file_set_sha256']=hashlib.sha256(canonical(manifest['files']).encode()).hexdigest()
            with patch.object(verifier,'FREEZE_SHA',manifest['freeze']['sha256']):
                self.assertEqual(verify_inventory(root,manifest)['frozen_files_verified'],844)
                p.write_text(json.dumps({'slot_id':'unknown-primary','request':{}})+'\n',encoding='utf-8')
                row.update(sha256=sha(p),bytes=p.stat().st_size)
                manifest['file_set_sha256']=hashlib.sha256(canonical(manifest['files']).encode()).hexdigest()
                with self.assertRaisesRegex(ValueError,'Primary or unknown'):verify_inventory(root,manifest)

    def test_paths_reject_traversal_private_caches_and_locks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('../outside', '/absolute', 'C:/absolute', 'a\\b', '.venv/x', '.env', 'x/__pycache__/x.pyc', 'x/active.lock'):
                with self.subTest(name=name), self.assertRaises(ValueError): safe_path(root, name, exists=False)
            safe_path(root, 'provenance/frozen-locks/x/active.lock.txt', exists=False)

    def test_duplicate_and_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'x.json'
            for text in ('{"x":1,"x":2}', '{"x":NaN}'):
                path.write_text(text, encoding='utf-8')
                with self.assertRaises(ValueError): load(path)

    def test_credential_scan_including_chunk_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'x.txt'
            path.write_bytes(b'x' * (1024 * 1024 - 3) + b'pt_' + b'live_' + b'Z' * 20)
            with self.assertRaises(ValueError): scan_credentials(path)

    def test_zip_preserves_bytes_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'a.txt'; source.write_text('Unicode: ø', encoding='utf-8')
            item = {'path':'data/a.txt','sha256':sha(source),'bytes':source.stat().st_size}
            manifest = {'files':[item]}; output = root / 'new.zip'
            result = write_zip(output, manifest, {'data/a.txt':source})
            self.assertEqual(result['sha256'], sha(output))
            with ZipFile(output) as archive:
                self.assertEqual(archive.read('data/a.txt'), source.read_bytes())
            with self.assertRaises(ValueError): write_zip(output, manifest, {'data/a.txt':source})

    def test_changed_packaging_input_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'a'; source.write_bytes(b'old')
            manifest = {'files':[{'path':'a','sha256':sha(source),'bytes':3}]}
            source.write_bytes(b'new')
            with self.assertRaises(ValueError): write_zip(root/'new.zip',manifest,{'a':source})

    def test_primary_completion_claim_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            for fields in ({'status':'complete_primary'}, {'status':'diagnostic_primary_unissued','primary_study_complete':True}):
                value={'schema':'retrace.frontier-v6h-diagnostic-release.v1',**fields}
                with self.assertRaises(ValueError): verify_inventory(Path(folder),value)


if __name__ == '__main__': unittest.main()
