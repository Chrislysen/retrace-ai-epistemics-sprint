"""New k-only reader; shared v6l product format does not imply l execution."""
from .refuter_reader_v6l import RefuterCatalog
from .server_v6l import ROOT,require

FREEZE_SHA='274d3101ed47e3ca918ee1e2273c0cdd269b43c60567e3fa4e121f6a7b9efa40'


class KRefuterCatalog(RefuterCatalog):
    def __init__(self,root=ROOT,*,expected_manifest_sha256=None,diagnostic=False):
        super().__init__(root,expected_manifest_sha256=expected_manifest_sha256,expected_freeze_sha256=FREEZE_SHA,diagnostic=diagnostic)
        self.directory='results/frontier-v6k/'+('partial-refuter-product' if diagnostic else 'refuter-product')
        self.manifest_schema='retrace.controlled-refuter-product.v6k-partial.v1' if diagnostic else 'retrace.controlled-refuter-product.v6k.v1'

    def _load(self):
        manifest,index=super()._load()
        if manifest is not None:
            require(manifest.get('scientific_execution')=='v6k' and manifest.get('scientific_segments')==['i','j','k'], 'Actual three-segment scientific execution required')
        return manifest,index

    def index(self):
        return {**super().index(),'scientific_execution':'v6k','scientific_segments':['i','j','k'],
                'format_scope':'Shared product format only; no fourth inference segment.'}
