"""Explicit diagnostic workbench for a closed, interrupted v6k study.

This entrypoint cannot admit a complete-study catalog and never starts inference.
"""
import argparse
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit
from .server_v6k import EvidenceCatalog,HandlerV6k,ROOT,require


class PartialEvidenceCatalog(EvidenceCatalog):
    directory='results/frontier-v6k/partial-catalog'
    manifest_schema='retrace.evidence-catalog.v6k-partial.v1'
    study_status='interrupted_amended_diagnostic'
    missing_message='No closed interrupted-study catalog has been exported. The constructed demo remains separate.'

    def _load(self):
        manifest,index=super()._load()
        if manifest is not None:
            require(manifest.get('schedule_complete') is False and manifest.get('inference_available') is False
                    and isinstance(index['scope'],str) and index['scope'].startswith('INTERRUPTED STUDY.'),
                    'Interrupted scope and unavailable inference must remain explicit')
        return manifest,index

    def index(self):
        value=super().index()
        return {**value,'study_status':self.study_status,'schedule_complete':False,'inference_available':False,
                'censoring_scope':'Unissued stop rows are censored, not observed model errors. No complete-study inference is available.'}


class HandlerPartial(HandlerV6k):
    def do_GET(self):
        if not self.local_host():return self.send(403,{'error':'Use the local workbench address'})
        if urlsplit(self.path).path in ('/','/lab'):
            return self.send(200,(ROOT/'web/v6k-partial/index.html').read_bytes(),'text/html; charset=utf-8')
        return super().do_GET()


def serve(port=8772,*,expected_manifest_sha256=None):
    server=ThreadingHTTPServer(('127.0.0.1',port),HandlerPartial)
    server.evidence_catalog=PartialEvidenceCatalog(expected_manifest_sha256=expected_manifest_sha256)
    print(f'RETRACE interrupted-study diagnostic workbench: http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8772)
    p.add_argument('--catalog-manifest-sha256');a=p.parse_args()
    serve(a.port,expected_manifest_sha256=a.catalog_manifest_sha256)
