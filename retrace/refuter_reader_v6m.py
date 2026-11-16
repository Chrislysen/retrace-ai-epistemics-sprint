"""Pinned, bounded reader for the separate controlled-seed catalog."""
from hashlib import sha256
import re
from .server_v6m import EvidenceCatalog, strict, require, ROOT, PRIMARY_MODELS
from .refuter_catalog_v6m import validate_entry, STATUSES, DIRECTORY


class RefuterCatalog(EvidenceCatalog):
    def __init__(self, root=ROOT, *, expected_manifest_sha256=None, expected_freeze_sha256=None, diagnostic=False):
        super().__init__(root, expected_manifest_sha256=expected_manifest_sha256,
                         expected_freeze_sha256=expected_freeze_sha256, diagnostic=diagnostic)
        self.directory = 'results/frontier-v6m/partial-refuter-catalog' if diagnostic else DIRECTORY
        self.manifest_schema = 'retrace.controlled-refuter-catalog.v6m-partial.v1' if diagnostic else 'retrace.controlled-refuter-catalog.v6m.v1'
        self.missing_message = 'No closed controlled-seed refuter export. No empirical counter-reading is inferred from the demo.'

    def _load(self):
        if not (self.root/self.directory/'manifest.json').exists():
            require(self.expected is None, 'Pinned refuter catalog is missing')
            return None,None
        require(self.expected_freeze is not None,'Explicit execution freeze required')
        raw=self._read(self.directory+'/manifest.json'); digest=sha256(raw).hexdigest()
        require(self.expected is None or self.expected==digest,'Refuter manifest changed')
        m=strict(raw)
        require(m.get('schema')==self.manifest_schema and m.get('status')==self.study_status
                and m.get('source_freeze_sha256')==self.expected_freeze and m.get('scheduled_slots')==300
                and m.get('selection_view')=='first_attempt' and m.get('schedule_complete') is (not self.diagnostic)
                and m.get('inference_available') is False
                and m.get('amended_sensitivity_available') is (not self.diagnostic)
                and m.get('index_path')==self.directory+'/index.json','Refuter branch/freeze identity')
        require(isinstance(m.get('files'),dict) and len(m['files'])==301,'Exact301-member refuter inventory')
        index=strict(self._member(m,m['index_path'],bound=2_097_152))
        require(set(index)=={'schema','scheduled_slots','selection_view','case_order','model_order','counts','entries','scope','test_fixture'}
                and index['schema']=='retrace.controlled-refuter-index.v6l.v1' and index['scheduled_slots']==300
                and index['selection_view']=='first_attempt' and index['test_fixture'] is False,'Refuter index fields')
        rows=index['entries']; cids=index['case_order']
        require(len(cids)==len(set(cids))==60 and index['model_order']==list(PRIMARY_MODELS)
                and len(rows)==300 and [(r['case_id'],r['model']) for r in rows]==[(c,mo) for c in cids for mo in PRIMARY_MODELS], 'All300 ordered first attempts')
        required={m['index_path']}; seen=set()
        for row in rows:
            require(set(row)=={'key','slot_id','case_id','model','status','provider_completed','strict_bare_json','entry_path','entry_sha256'},'Public index fields')
            key=row['key'];require(isinstance(key,str) and re.fullmatch(r'[a-f0-9]{64}',key) and key not in seen
                and key==sha256(row['slot_id'].encode()).hexdigest() and row['status'] in STATUSES,'Unique observation key')
            seen.add(key);name=self.directory+'/entries/'+key+'.json'
            require(row['entry_path']==name and m['files'].get(name,{}).get('sha256')==row['entry_sha256'],'Refuter entry binding')
            required.add(name)
        require(set(m['files'])==required and index['counts']=={s:sum(r['status']==s for r in rows) for s in STATUSES},'Exact members/counts')
        if self.diagnostic:require(index['scope'].startswith('INTERRUPTED STUDY.'),'Interrupted scope required')
        self.expected=digest
        return m,index

    def entry(self,key,*,bundle=False):
        require(not bundle,'Controlled seed cannot be silently loaded as source IR')
        require(isinstance(key,str) and re.fullmatch(r'[a-f0-9]{64}',key),'Invalid observation key')
        with self.lock:
            m,index=self._load()
            if m is None:raise FileNotFoundError('No closed refuter catalog')
            row=next((r for r in index['entries'] if r['key']==key),None)
            if row is None:raise FileNotFoundError('Unknown refuter observation')
            raw=self._member(m,row['entry_path']);value=validate_entry(strict(raw))
            require(all(value['metadata'][k]==row[k] for k in ('key','slot_id','case_id','model','status','provider_completed','strict_bare_json')),'Indexed observation differs')
            return raw
