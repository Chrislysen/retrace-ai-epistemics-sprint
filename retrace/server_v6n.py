"""Read-only recorded-extraction catalog beside the unchanged offline workbench.

No provider connection, credentials, gold reference graphs or output repair.
The catalog is created separately only after authenticated study closure.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import RLock
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from .server_v6h import HandlerV6h, ROOT
from .server import unique_object, reject_constant
from .source_ir_v6h import compile_ir

BASE = 'results/frontier-v6n/catalog'
PARTIAL_BASE = 'results/frontier-v6n/partial-catalog'
PRIMARY_MODELS = ('deepseek-v4-flash', 'gemma-4-31b-it', 'glm-5.3-flash', 'qwen3.8-27b', 'glm-5.2')
STATUSES = {'admitted', 'admitted_registry_gap', 'invalid_ir', 'scoring_unavailable',
            'provider_failure', 'truncated_output', 'not_issued'}
META_FIELDS = {'key','slot_id','case_id','model','condition','phase','selection_view','status',
    'provider_completed','schema_valid','strict_bare_json','compiler_admitted','candidate_count',
    'registry_coverage_gaps','loadable','attempt_id','attempts_observed','model_outcome','failure_scope',
    'error_code','requested_model','returned_model','response_status','warning_label',
    'source_entailment_verified','source_completeness'}
PROVENANCE_FIELDS = {'selected_first_attempt','public_source_sha256','scheduled_input_sha256',
    'raw_output_text_sha256','partial_output_text_sha256','raw_provider_response_sha256','original_ir_sha256','scope'}
INDEX_FIELDS = {'schema','scheduled_slots','selection_view','case_order','model_order','counts','entries','scope','test_fixture'}
ROW_FIELDS = {'key','slot_id','case_id','model','status','provider_completed','strict_bare_json',
    'candidate_count','registry_coverage_gaps','entry_path','entry_sha256','bundle_path','bundle_sha256'}


def require(ok, why):
    if not ok: raise ValueError(why)


def strict(raw): return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)


def object_hash(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def public_entry(value):
    """Do not serve hidden annotations even inside a consistently hashed file."""
    require(isinstance(value,dict) and set(value)=={'schema','metadata','source_documents','registry',
        'raw_output_text','partial_output_text','brief','provenance','scope'}, 'Invalid public catalog entry schema')
    meta=value['metadata']; provenance=value['provenance'];docs=value['source_documents'];registry=value['registry']
    require(isinstance(meta,dict) and set(meta)==META_FIELDS and meta['source_entailment_verified'] is False
            and meta['source_completeness']=='unknown', 'Public metadata fields and uncertainty labels required')
    require(isinstance(docs,list) and all(isinstance(d,dict) and set(d)=={'id','text'}
            and isinstance(d['id'],str) and isinstance(d['text'],str) for d in docs), 'Only public document IDs and text may be served')
    require(isinstance(registry,dict) and set(registry)=={'evidence','claims','decisions'}
            and all(isinstance(ids,list) and all(isinstance(i,str) for i in ids) for ids in registry.values()),
            'Only the public typed registry may be served')
    require(isinstance(provenance,dict) and set(provenance)==PROVENANCE_FIELDS, 'Public provenance fields required')
    selected=provenance['selected_first_attempt']
    require(isinstance(selected,dict) and set(selected)=={'request','response','final_outcome'}, 'First-attempt source pointer roles required')
    for pointer in selected.values():
        if pointer is None: continue
        require(isinstance(pointer,dict) and set(pointer)=={'segment','source_path','source_line_one_based',
                'source_file_sha256','source_line_sha256','row_sha256'}, 'Public source pointer fields required')
    require(isinstance(value['raw_output_text'],str) and isinstance(value['partial_output_text'],str), 'Raw outputs must remain strings')
    require(provenance['public_source_sha256']==object_hash({'source_documents':docs,'registry':registry})
            and provenance['raw_output_text_sha256']==sha256(value['raw_output_text'].encode()).hexdigest()
            and provenance['partial_output_text_sha256']==sha256(value['partial_output_text'].encode()).hexdigest(),
            'Public source or output hash differs from the recorded provenance')


class EvidenceCatalog:
    """Pin the manifest on first load, then authenticate each served member.

    This is a bounded local-file integrity check, not a substitute for the
    independent scientific reproduction command or a provider signature.
    """
    directory = BASE
    manifest_schema = 'retrace.evidence-catalog.v6n.v1'
    study_status = 'complete_host_recovered_schedule'
    missing_message = 'No completed study catalog has been exported. The constructed demo remains available.'

    def __init__(self, root=ROOT, *, expected_manifest_sha256=None, expected_freeze_sha256=None, diagnostic=False):
        require(type(diagnostic) is bool, 'Explicit diagnostic selector required')
        self.diagnostic = diagnostic
        self.directory = PARTIAL_BASE if diagnostic else BASE
        self.manifest_schema = 'retrace.evidence-catalog.v6n-partial.v1' if diagnostic else 'retrace.evidence-catalog.v6n.v1'
        self.study_status = 'interrupted_recovery_diagnostic' if diagnostic else 'complete_host_recovered_schedule'
        self.missing_message = ('No closed interrupted-study catalog has been exported. Unissued rows remain censored; the constructed demo is separate.'
            if diagnostic else 'No completed study catalog has been exported. The constructed demo remains available.')
        self.expected_freeze = expected_freeze_sha256
        require(self.expected_freeze is None or re.fullmatch(r'[a-f0-9]{64}',self.expected_freeze), 'Invalid execution freeze digest')
        self.root = Path(root).resolve()
        self.expected = expected_manifest_sha256
        require(self.expected is None or re.fullmatch(r'[a-f0-9]{64}', self.expected), 'Invalid catalog manifest digest')
        self.lock = RLock()

    def _path(self, name):
        require(isinstance(name, str) and name.startswith(self.directory+'/') and '\\' not in name,
                'Catalog path must be a declared local member')
        p = Path(name)
        require(not p.is_absolute() and all(part not in ('..','.') for part in p.parts), 'Invalid catalog member path')
        target = (self.root/p).resolve()
        require(target.is_relative_to(self.root/self.directory), 'Catalog member escapes its directory')
        return target

    def _read(self, name, *, bound=4_194_304):
        path = self._path(name)
        require(path.is_file() and path.stat().st_size <= bound, 'Catalog member is absent or exceeds its size bound')
        with path.open('rb') as f: raw = f.read(bound+1)
        require(len(raw) <= bound, 'Catalog member grew beyond its size bound')
        return raw

    def _member(self, manifest, name, *, bound=4_194_304):
        require(name in manifest['files'], 'Catalog member is not inventoried')
        record = manifest['files'][name]
        require(isinstance(record, dict) and set(record) == {'sha256','bytes'} and type(record['bytes']) is int,
                'Invalid catalog member binding')
        raw = self._read(name, bound=bound)
        require(len(raw) == record['bytes'] and sha256(raw).hexdigest() == record['sha256'], 'Catalog member hash changed')
        return raw

    def _load(self):
        manifest_path = self.root/self.directory/'manifest.json'
        if not manifest_path.exists():
            require(self.expected is None, 'Pinned catalog manifest is missing')
            return None, None
        require(self.expected_freeze is not None, 'Explicit execution freeze digest required for recorded catalog')
        raw = self._read(self.directory+'/manifest.json')
        digest = sha256(raw).hexdigest()
        require(self.expected is None or digest == self.expected, 'Catalog manifest changed after it was pinned')
        manifest = strict(raw)
        require(isinstance(manifest,dict) and manifest.get('schema') == self.manifest_schema
                and manifest.get('status') == self.study_status
                and manifest.get('scheduled_slots') == 300
                and manifest.get('selection_view') == 'first_attempt'
                and manifest.get('source_freeze_sha256') == self.expected_freeze
                and manifest.get('schedule_complete') is (not self.diagnostic)
                and manifest.get('inference_available') is False
                and manifest.get('amended_sensitivity_available') is (not self.diagnostic)
                and manifest.get('scientific_segments') == ['i','j','k-prefix','m-prefix','n']
                and manifest.get('index_path') == self.directory+'/index.json', 'Catalog study status, schema or first-attempt binding differs from this reader')
        require(isinstance(manifest.get('files'), dict) and 301 <= len(manifest['files']) <= 601,
                'Catalog inventory must cover every observation and optional bundles')
        for name in manifest['files']: self._path(name)
        index = strict(self._member(manifest, manifest['index_path'], bound=2_097_152))
        require(isinstance(index,dict) and set(index)==INDEX_FIELDS and index.get('schema') == 'retrace.evidence-index.v6k.v1'
                and index.get('scheduled_slots') == 300 and index.get('selection_view') == 'first_attempt'
                and index.get('test_fixture') is False, 'Invalid catalog index or invented fixture')
        rows = index.get('entries')
        require(isinstance(rows, list) and len(rows) == 300, 'All300 observations must remain visible')
        keys = set(); slots = set(); cases = {}
        required = {manifest['index_path']}
        for row in rows:
            require(isinstance(row,dict) and set(row)==ROW_FIELDS, 'Only public index fields may be served')
            key = row.get('key'); sid = row.get('slot_id')
            require(isinstance(sid,str) and isinstance(key,str) and re.fullmatch(r'[a-f0-9]{64}',key)
                    and sha256(sid.encode()).hexdigest() == key and key not in keys and sid not in slots,
                    'Unique slot-derived catalog keys required')
            require(row.get('model') in PRIMARY_MODELS and row.get('status') in STATUSES, 'Unknown catalog model or status')
            keys.add(key); slots.add(sid); cases.setdefault(row['case_id'], []).append(row['model'])
            path = self.directory+'/entries/'+key+'.json'
            require(row.get('entry_path') == path and manifest['files'].get(path,{}).get('sha256') == row.get('entry_sha256'),
                    'Entry binding is not canonical')
            required.add(path)
            bundle_path = row.get('bundle_path')
            if row['status'] in ('admitted','admitted_registry_gap'):
                expected = self.directory+'/bundles/'+key+'.json'
                require(bundle_path == expected and manifest['files'].get(expected,{}).get('sha256') == row.get('bundle_sha256'),
                        'Admitted interpretation must have a bound bundle')
                required.add(expected)
            else:
                require(bundle_path is None and row.get('bundle_sha256') is None,
                        'Unavailable interpretation cannot acquire a repaired bundle')
        require(len(cases) == 60 and all(len(ms)==5 and set(ms)==set(PRIMARY_MODELS) for ms in cases.values()),
                'Catalog must retain60 cases across all5 primary models')
        require(isinstance(index['case_order'],list) and len(index['case_order'])==60 and index['model_order']==list(PRIMARY_MODELS)
                and [(r['case_id'],r['model']) for r in rows]==[(c,m) for c in index['case_order'] for m in PRIMARY_MODELS],
                'Fixed case-major and model order required')
        require(index.get('counts') == {status:sum(r['status']==status for r in rows) for status in STATUSES},
                'Displayed counts must include every scheduled observation')
        require(set(manifest['files']) == required, 'Undeclared or missing catalog member')
        if self.diagnostic:
            require(isinstance(index['scope'],str) and index['scope'].startswith('INTERRUPTED STUDY.'), 'Interrupted scope must be explicit')
        self.expected = digest
        return manifest, index

    def index(self):
        with self.lock:
            _, index = self._load()
            if index is None:
                return {'available':False, 'entries':[], 'scope':self.missing_message}
            return {**index, 'available':True, 'manifest_sha256':self.expected,
                    'study_status':self.study_status, 'schedule_complete':not self.diagnostic, 'inference_available':False, 'amended_sensitivity_available':not self.diagnostic,
                    'integrity_scope':'Local catalog bytes checked against their pinned manifest. Run offline reproduction to verify scientific provenance; this is not a provider signature.'}

    def entry(self, key, *, bundle=False):
        require(isinstance(key,str) and re.fullmatch(r'[a-f0-9]{64}',key), 'Invalid catalog key')
        with self.lock:
            manifest,index = self._load()
            if manifest is None: raise FileNotFoundError('No completed catalog')
            row = next((r for r in index['entries'] if r['key']==key),None)
            if row is None: raise FileNotFoundError('Observation is not in this catalog')
            raw = self._member(manifest,row['entry_path']); value = strict(raw)
            public_entry(value)
            require(value.get('schema') == 'retrace.evidence-entry.v6k.v1', 'Invalid public catalog entry schema')
            meta = value['metadata']
            require(all(meta.get(k)==row[k] for k in ('key','slot_id','case_id','model','status','provider_completed',
                        'strict_bare_json','candidate_count','registry_coverage_gaps'))
                    and meta.get('condition')=='strict_source_ir' and meta.get('phase')=='extract'
                    and meta.get('selection_view')=='first_attempt', 'Entry differs from its indexed observation')
            loadable = row['status'] in ('admitted','admitted_registry_gap')
            require((value['brief'] is not None) == loadable and meta.get('loadable') is loadable,
                    'Unavailable observation cannot supply a declaration')
            if loadable:
                brief = value['brief']
                require(isinstance(brief,dict) and set(brief)=={'id','title','source_documents','registry','source_ir'}
                        and brief['source_documents']==value['source_documents'] and brief['registry']==value['registry'],
                        'Workbench import must contain only the matching public source and interpretation')
                compiled=compile_ir(value['raw_output_text'],value['source_documents'],value['registry'])
                require(compiled['original_ir']==brief['source_ir'] and compiled['candidate_count']==row['candidate_count']
                        and compiled['registry_coverage_gaps']==row['registry_coverage_gaps']
                        and compiled['strict_bare_json'] is row['strict_bare_json']
                        and object_hash(brief['source_ir'])==value['provenance']['original_ir_sha256'],
                        'Imported declaration must match the original unrepaired model text')
            if bundle:
                if not loadable: raise FileNotFoundError('This observation has no admitted interpretation')
                bundle_raw = self._member(manifest,row['bundle_path'])
                require(strict(bundle_raw)==value['brief'], 'Bundle differs from its recorded entry')
                return bundle_raw
            return raw


class HandlerV6m(HandlerV6h):
    def do_GET(self):
        if not self.local_host(): return self.send(403, {'error':'Use the local workbench address'})
        path = urlsplit(self.path).path
        if path in ('/','/lab'):
            return self.send(200,(ROOT/'web/v6n'/('diagnostic.html' if self.server.evidence_catalog.diagnostic else 'index.html')).read_bytes(),'text/html; charset=utf-8')
        if path == '/evidence.js':
            return self.send(200,(ROOT/'web/v6n/evidence.js').read_bytes(),'text/javascript; charset=utf-8')
        if path == '/refuters.js':
            return self.send(200,(ROOT/'web/v6n/refuters.js').read_bytes(),'text/javascript; charset=utf-8')
        if path == '/api/v6n/refuters' or path.startswith('/api/v6n/refuters/'):
            try:
                catalog = self.server.refuter_catalog
                result = catalog.index() if path == '/api/v6n/refuters' else catalog.entry(path.removeprefix('/api/v6n/refuters/'))
                return self.send(200,result)
            except FileNotFoundError: return self.send(404,{'error':'No such controlled-seed observation'})
            except (ValueError,KeyError,TypeError,OSError,AttributeError,RecursionError,OverflowError):
                return self.send(409,{'error':'Controlled-seed catalog integrity check failed; no proposal was applied'})
        if path == '/api/v6n/catalog':
            try: return self.send(200,self.server.evidence_catalog.index())
            except (ValueError,KeyError,TypeError,OSError,AttributeError,RecursionError,OverflowError):
                return self.send(409,{'error':'Catalog integrity check failed. Run offline reproduction before using these observations.'})
        if path.startswith('/api/v6n/catalog/'):
            parts = path.removeprefix('/api/v6n/catalog/').split('/')
            if len(parts) not in (1,2) or (len(parts)==2 and parts[1] not in ('bundle','diagnosis')):
                return self.send(404,{'error':'Not found'})
            try:
                if len(parts)==2 and parts[1]=='diagnosis':
                    from .source_diagnostics_v6k import diagnose
                    value=strict(self.server.evidence_catalog.entry(parts[0]))
                    require(value['metadata']['status']=='invalid_ir' and value['metadata']['provider_completed'] is True,
                            'Only a completed, rejected source-IR observation can receive this local review')
                    result=diagnose(value['raw_output_text'],value['source_documents'],value['registry'])
                    require(result['compile_admitted'] is False
                            and result['raw_text_sha256']==value['provenance']['raw_output_text_sha256']
                            and result['source_packet_sha256']==value['provenance']['public_source_sha256'],
                            'Diagnostic must refer to the unchanged rejected observation')
                    return self.send(200,{**result,'slot_id':value['metadata']['slot_id'],
                        'catalog_manifest_sha256':self.server.evidence_catalog.expected})
                return self.send(200,self.server.evidence_catalog.entry(parts[0],bundle=len(parts)==2))
            except FileNotFoundError: return self.send(404,{'error':'No admitted observation at this address'})
            except (ValueError,KeyError,TypeError,OSError,AttributeError,RecursionError,OverflowError):
                return self.send(409,{'error':'Catalog entry integrity check failed; no interpretation was loaded'})
        # Analysis, demonstration, JS and styles retain their original bytes and
        # endpoints. The existing same-origin and body-size checks still apply.
        return super().do_GET()


def serve(port=8778, *, expected_manifest_sha256=None, expected_freeze_sha256=None, diagnostic=False,
          expected_refuter_manifest_sha256=None):
    from .refuter_reader_v6n import RefuterCatalog
    server = ThreadingHTTPServer(('127.0.0.1',port),HandlerV6m)
    server.evidence_catalog = EvidenceCatalog(expected_manifest_sha256=expected_manifest_sha256,
        expected_freeze_sha256=expected_freeze_sha256, diagnostic=diagnostic)
    server.refuter_catalog = RefuterCatalog(expected_manifest_sha256=expected_refuter_manifest_sha256,
        expected_freeze_sha256=expected_freeze_sha256, diagnostic=diagnostic)
    print(f'RETRACE recorded extractions and offline workbench: http://127.0.0.1:{server.server_port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8778)
    parser.add_argument('--catalog-manifest-sha256')
    parser.add_argument('--refuter-manifest-sha256')
    parser.add_argument('--freeze-sha256');parser.add_argument('--diagnostic',action='store_true')
    args=parser.parse_args();serve(args.port,expected_manifest_sha256=args.catalog_manifest_sha256,
        expected_freeze_sha256=args.freeze_sha256, diagnostic=args.diagnostic,
        expected_refuter_manifest_sha256=args.refuter_manifest_sha256)
