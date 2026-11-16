"""Offline additive-overlay guards; no live accounting or provider calls."""
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from scripts.assemble_frontier_v6h_transport import write_zip
from scripts.reproduce_frontier_v6h_release import sha
from scripts.reproduce_frontier_v6h_transport import base_manifest_from_zip,verify_new_inventory,SCHEMA,SUPPLEMENT_MANIFEST


class TransportOverlayTests(unittest.TestCase):
    def test_base_collision_case_insensitive_rejected_without_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'new';source.write_bytes(b'new')
            m={'files':[{'path':'README.md','sha256':sha(source),'bytes':3}]}
            with self.assertRaisesRegex(ValueError,'base collision'):write_zip(root/'new.zip',m,{'README.md':source},{'readme.md'})
            self.assertFalse((root/'new.zip').exists())

    def test_reserved_base_manifest_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'new';source.write_bytes(b'new')
            for name in ('release-manifest-v6h.json',SUPPLEMENT_MANIFEST):
                m={'files':[{'path':name,'sha256':sha(source),'bytes':3}]}
                with self.assertRaisesRegex(ValueError,'manifest collision'):write_zip(root/'new.zip',m,{name:source},set())

    def test_new_only_archive_is_exact_and_exclusive(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'new';source.write_bytes('source ø'.encode())
            m={'files':[{'path':'new/path.txt','sha256':sha(source),'bytes':source.stat().st_size}]}
            archive=root/'new.zip';write_zip(archive,m,{'new/path.txt':source},{'README.md'})
            with ZipFile(archive) as z:
                self.assertEqual(set(z.namelist()),{'new/path.txt',SUPPLEMENT_MANIFEST})
                self.assertEqual(z.read('new/path.txt'),source.read_bytes())
            with self.assertRaisesRegex(ValueError,'overwrite'):write_zip(archive,m,{'new/path.txt':source},set())

    def test_changed_source_is_never_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'new';source.write_bytes(b'old')
            m={'files':[{'path':'new.txt','sha256':sha(source),'bytes':3}]};source.write_bytes(b'new')
            with self.assertRaisesRegex(ValueError,'changed'):write_zip(root/'new.zip',m,{'new.txt':source},set())

    def test_wrong_base_zip_rejected_before_contents_are_trusted(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'fake.zip';p.write_bytes(b'not the pinned base')
            with self.assertRaisesRegex(ValueError,'Wrong base ZIP'):base_manifest_from_zip(p)

    def test_complete_primary_claim_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'scope'):verify_new_inventory(Path(folder),{'schema':SCHEMA,'status':'complete_primary'},{'files':[]})


if __name__=='__main__':unittest.main()
