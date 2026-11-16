"""Invented base archives only. No real study/report/ZIP is read or assembled."""
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from scripts import assemble_frontier_v6k_inspector as assembly
from scripts import reproduce_frontier_v6k_inspector as repro
from scripts.reproduce_frontier_v6h_release import canonical


def raw(value):return (json.dumps(value,sort_keys=True)+'\n').encode()
def binding(value):return {'sha256':sha256(value).hexdigest(),'bytes':len(value)}
def write(root,name,value):
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value);return path


def base_fixture(root):
    content=b'Original scientific evidence\n';rows=[{'path':'original/evidence.txt',**binding(content)}]
    manifest={'schema':'retrace.frontier-v6k-amended-release.v1','status':'complete_amended_primary',
        'planned_slots':1800,'freeze':{'path':'data/frontier-v6k-freeze.json','sha256':repro.FREEZE_SHA},
        'files':rows,'file_set_sha256':sha256(canonical(rows).encode()).hexdigest()}
    payloads={'original/evidence.txt':content,repro.BASE_MANIFEST:raw(manifest)}
    for name,value in payloads.items():write(root,name,value)
    return manifest,payloads


def composed_fixture(root):
    m,payloads=base_fixture(root);base=repro.base_inventory(m,binding(payloads[repro.BASE_MANIFEST]))
    product={'scientific_segments':['i','j','k'],'status':'complete_amended_primary','diagnostic':False,
        'files':{'results/frontier-v6k/refuter-product/index.json':binding(b'invented payload')}}
    write(root,repro.PRODUCT,raw(product));write(root,next(iter(product['files'])),b'invented payload')
    write(root,'new/product.txt',b'new only')
    names=set(base)|{repro.PRODUCT,*product['files'],'new/product.txt'}
    rows=[{'path':n,**binding((root/n).read_bytes())} for n in sorted(names)]
    proof={'status':'verified_complete_amended_primary','files_verified':1,'frozen_files_verified':1,
        'symbolic_tests':{'tests_run':1,'passed':True},'model_calls_made':0}
    return {'schema':repro.SCHEMA,'status':'complete_amended_primary','scientific_segments':['i','j','k'],
        'source_freeze_sha256':repro.FREEZE_SHA,'files':rows,'file_set_sha256':sha256(canonical(rows).encode()).hexdigest(),
        'base':{'manifest_path':repro.BASE_MANIFEST,'manifest_sha256':base[repro.BASE_MANIFEST]['sha256'],
            'member_paths':sorted(base),'verified_reproduction':proof},
        'new_member_paths':sorted(names-set(base)),
        'product':{'manifest_path':repro.PRODUCT,'manifest_sha256':binding(raw(product))['sha256'],'verified_reproduction':{'fixture':True}}}


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def zip_base(self,extra=None,mutate=None):
        _,payloads=base_fixture(self.root/'source')
        if extra:payloads.update(extra)
        if mutate:mutate(payloads)
        path=self.root/'base.zip'
        with ZipFile(path,'x') as archive:
            for name,value in payloads.items():archive.writestr(name,value)
        return path,sha256(path.read_bytes()).hexdigest()

    def test_extract_exact_original_bytes_and_retain_zip(self):
        archive,pin=self.zip_base();before=archive.read_bytes();destination=self.root/'isolated'
        inventory=assembly.extract_base(archive,pin,destination)
        self.assertEqual((destination/'original/evidence.txt').read_bytes(),b'Original scientific evidence\n')
        self.assertEqual(archive.read_bytes(),before);self.assertEqual(len(inventory),2)

    def test_wrong_pin_and_extra_member_never_pass(self):
        archive,pin=self.zip_base({'extra.txt':b'unlisted'})
        with self.assertRaisesRegex(ValueError,'pinned'):assembly.extract_base(archive,'0'*64,self.root/'wrong')
        with self.assertRaisesRegex(ValueError,'inventory'):assembly.extract_base(archive,pin,self.root/'extra')

    def test_diagnostic_base_is_not_fabricated_as_complete(self):
        def change(values):
            m=json.loads(values[repro.BASE_MANIFEST]);m['status']='interrupted_amended_diagnostic';values[repro.BASE_MANIFEST]=raw(m)
        archive,pin=self.zip_base(mutate=change)
        with self.assertRaisesRegex(ValueError,'complete k base'):assembly.extract_base(archive,pin,self.root/'reject')

    def test_changed_member_even_with_matching_zip_pin_rejects(self):
        archive,pin=self.zip_base(mutate=lambda values:values.update({'original/evidence.txt':b'Modified scientific evidence\n'}))
        with self.assertRaisesRegex(ValueError,'member (size|hash)'):assembly.extract_base(archive,pin,self.root/'reject')

    def test_path_traversal_and_case_folded_collision_reject(self):
        for names in (['../escape.txt'],['file.txt','FILE.txt']):
            rows=[{'path':n,**binding(b'x')} for n in names]
            with self.subTest(names=names),self.assertRaises(ValueError):repro.indexed(rows)

    def test_existing_base_path_cannot_be_overwritten_by_product(self):
        source=self.root/'source';target=self.root/'target';write(source,'original.txt',b'new');write(target,'original.txt',b'old')
        base={'original.txt':{'path':'original.txt',**binding(b'old')}}
        with patch('scripts.score_frontier_v6h.local_dependencies',return_value=set()):
            with self.assertRaisesRegex(ValueError,'replace'):assembly.add_product_files(source,target,base,{'original.txt'})
        self.assertEqual((target/'original.txt').read_bytes(),b'old')

    def test_identical_shared_dependencies_plus_new_paths_are_allowed(self):
        source=self.root/'source';target=self.root/'target';write(source,'shared.txt',b'old');write(target,'shared.txt',b'old');write(source,'new.txt',b'new')
        base={'shared.txt':{'path':'shared.txt',**binding(b'old')}}
        with patch('scripts.score_frontier_v6h.local_dependencies',return_value=set()):
            names=assembly.add_product_files(source,target,base,{'shared.txt','new.txt'})
        self.assertEqual(names,{'shared.txt','new.txt'});self.assertEqual((target/'new.txt').read_bytes(),b'new')

    def test_outer_inventory_preserves_base_and_isolated_verification_omits_new_paths(self):
        m=composed_fixture(self.root)
        def base_verifier(isolated,pin):
            self.assertEqual({p.relative_to(isolated).as_posix() for p in isolated.rglob('*') if p.is_file()},set(m['base']['member_paths']))
            self.assertNotEqual(isolated,self.root);return m['base']['verified_reproduction']
        with patch.object(repro,'ADDITIONS',()),patch.object(repro,'run_base_verifier',side_effect=base_verifier),patch.object(repro,'verify_product',return_value={'fixture':True}) as product:
            result=repro.verify(self.root,m,run_tests=False)
            self.assertTrue(result['passed']);self.assertEqual(result['model_calls_made'],0)
            product.assert_called_once_with(self.root,m['product']['manifest_sha256'],frozen_aliases=repro.ALIASES)

    def test_changed_base_or_unlisted_study_file_rejects(self):
        m=composed_fixture(self.root)
        with patch.object(repro,'ADDITIONS',()):
            write(self.root,'results/frontier-v6k/unlisted.txt',b'unlisted')
            with self.assertRaisesRegex(ValueError,'Uninventoried'):repro.verify_inventory(self.root,m)
        # Separate fixture avoids deleting any existing workspace path.
        fresh=self.root/'other';m=composed_fixture(fresh);write(fresh,'original/evidence.txt',b'changed')
        with patch.object(repro,'ADDITIONS',()):
            with self.assertRaisesRegex(ValueError,'member changed'):repro.verify_inventory(fresh,m)

    def test_new_zip_contains_original_member_bytes_and_refuses_overwrite(self):
        m=composed_fixture(self.root);out=self.root/'composed.zip'
        with patch.object(repro,'ADDITIONS',()):
            assembly.write_zip(out,self.root,m)
            with ZipFile(out) as archive:
                self.assertEqual(archive.read('original/evidence.txt'),b'Original scientific evidence\n')
                self.assertEqual(json.loads(archive.read(repro.MANIFEST)),m)
            with self.assertRaisesRegex(ValueError,'overwrite'):assembly.write_zip(out,self.root,m)

    def test_no_base_archive_no_new_artifacts_or_report_claim(self):
        with self.assertRaisesRegex(ValueError,'Existing verified complete'):assembly.assemble(self.root,self.root/'absent.zip','0'*64)
        self.assertFalse((self.root/'deliverables').exists())


if __name__=='__main__':unittest.main()
