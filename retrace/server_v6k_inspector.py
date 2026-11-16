"""Standalone product-only k viewer; no l run, network inference or mutations."""
import argparse
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit
from .server_v6l import HandlerV6l,ROOT
from .server_v6k import EvidenceCatalog
from .server_v6k_partial import PartialEvidenceCatalog
from .refuter_product_v6k import KRefuterCatalog


class Handler(HandlerV6l):
    def do_GET(self):
        if not self.local_host():return self.send(403,{'error':'Use the local address'})
        if urlsplit(self.path).path in ('/','/lab'):
            return self.send(200,(ROOT/'web/v6k-inspector'/('diagnostic.html' if self.server.diagnostic else 'index.html')).read_bytes(),'text/html; charset=utf-8')
        # Existing /api/v6l/* paths identify the shared product UI contract.
        # Both reader instances below are explicitly pinned to k artifacts.
        return super().do_GET()


def serve(port=8775,*,catalog_manifest_sha256=None,refuter_manifest_sha256=None,diagnostic=False):
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.diagnostic=diagnostic
    cls=PartialEvidenceCatalog if diagnostic else EvidenceCatalog
    server.evidence_catalog=cls(expected_manifest_sha256=catalog_manifest_sha256)
    server.refuter_catalog=KRefuterCatalog(expected_manifest_sha256=refuter_manifest_sha256,diagnostic=diagnostic)
    print(f'RETRACE three-segment k product: http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8775)
    p.add_argument('--catalog-manifest-sha256');p.add_argument('--refuter-manifest-sha256');p.add_argument('--diagnostic',action='store_true');a=p.parse_args()
    serve(a.port,catalog_manifest_sha256=a.catalog_manifest_sha256,refuter_manifest_sha256=a.refuter_manifest_sha256,diagnostic=a.diagnostic)
