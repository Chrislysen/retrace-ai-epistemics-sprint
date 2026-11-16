"""Location/schema gate for refuter proposals; never automatic semantic trust."""
from copy import deepcopy
from hashlib import sha256
import math
from .frontier_v6c_io import parse_object
from .source_ir_v6d import source_segments
from .source_ir_v6h import compile_ir


def validate_refuter(value, documents, registry):
    strict=True
    if isinstance(value,str):value,strict=parse_object(value)
    else:value=deepcopy(value)
    if not isinstance(value,dict) or set(value)!={'status','ir','objection_spans','warning_score'}:
        raise ValueError('Refuter envelope requires exact fields')
    score=value['warning_score']
    if type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=1:
        raise ValueError('Finite warning score in[0,1] required')
    spans=value['objection_spans']
    if value['status']=='no_counter_reading':
        if value['ir'] is not None or spans!=[]:raise ValueError('Abstention has no IR/objection spans')
        return {'status':'abstained','raw_warning_score':score,'strict_bare_json':strict,
                'proposal_applied':False,'semantic_entailment_verified':False,'compilation':None,'locations':[]}
    if value['status']!='objection':raise ValueError('Unknown refuter status')
    inventory={s['span_id']:s for s in source_segments(documents)}
    if (not isinstance(spans,list) or not 1<=len(spans)<=8 or
        any(not isinstance(s,str) or s not in inventory for s in spans) or len(set(spans))!=len(spans)):
        raise ValueError('An objection needs1..8 exact existing source spans')
    # Admission is atomic: no warning or graph is returned until every cite and
    # every branch has passed. Locations still do not prove the proposed reading.
    compiled=compile_ir(value['ir'],documents,registry)
    if compiled['registry_coverage_gaps']:
        raise ValueError('Refuter admission requires explicit dispositions for every registered identifier')
    locations=[{**inventory[s],'quote_sha256':sha256(inventory[s]['text'].encode()).hexdigest()} for s in spans]
    return {'status':'source_located_proposal','raw_warning_score':score,'strict_bare_json':strict,
            'compilation':compiled,'locations':locations,'proposal_applied':False,
            'semantic_entailment_verified':False,
            'scope':'Exact verbatim Unicode spans and complete formal declarations checked; whether the objection follows from those words remains reviewable and fallible.'}
