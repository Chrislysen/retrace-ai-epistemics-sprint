"""Citation-reference transport for the unchanged, frozen Source-Proposition IR.

Segmentation supplies locations only. It never extracts dependencies or scope.
"""
from copy import deepcopy
import hashlib
import json

from .source_ir_v6c import compile_source_ir, audit_source_ir, IR_INSTRUCTIONS
from .frontier_v6c_io import parse_object

SCHEMA='retrace.source-ir.v6d'


def source_segments(documents):
    if not isinstance(documents,list) or not 1<=len(documents)<=64: raise ValueError('Invalid source document inventory')
    segments=[];seen=set();total=0
    for doc in documents:
        if not isinstance(doc,dict) or not isinstance(doc.get('id'),str) or not isinstance(doc.get('text'),str) or doc['id'] in seen:
            raise ValueError('Invalid source document')
        seen.add(doc['id']);text=doc['text'];total+=len(text)
        if total>524288: raise ValueError('Source bound exceeded')
        position=0
        while position<len(text):
            boundary=text.find('\n\n',position)
            end=len(text) if boundary<0 else boundary+2
            end=min(end,position+4096)
            # Preserve complete syntax-level identifiers at artificial chunk
            # boundaries. This assigns no entity type or dependency meaning.
            def identifier_char(char):
                return char.isascii() and (char.isalnum() or char in '_-')
            if end<len(text) and identifier_char(text[end-1]) and identifier_char(text[end]):
                cut=end
                while cut>position and identifier_char(text[cut-1]):cut-=1
                if cut>position:end=cut
            excerpt=text[position:end]
            sid='s'+hashlib.sha256((doc['id']+'\0'+str(position)+'\0'+str(end)+'\0'+excerpt).encode('utf-8')).hexdigest()[:16]
            segments.append({'span_id':sid,'document_id':doc['id'],'start':position,'end':end,'text':excerpt})
            position=end
    if len(segments)>4096: raise ValueError('Too many source segments')
    if len({s['span_id'] for s in segments})!=len(segments): raise ValueError('Span ID collision')
    return segments


def model_source(documents,registry):
    return {'source_segments':source_segments(documents),'registry':deepcopy(registry),
            'segment_semantics':'Ordered exact source slices; segmentation has no semantic force. Resolve grouping and references across slices. Cite span_id strings.'}


def expand_ir(value,documents):
    if isinstance(value,str): value,_=parse_object(value)
    if not isinstance(value,dict) or value.get('schema')!=SCHEMA: raise ValueError('Expected v6d source IR')
    output=deepcopy(value)
    spans={s['span_id']:s for s in source_segments(documents)}
    def citation(ref):
        if not isinstance(ref,str) or ref not in spans: raise ValueError('Unknown source span reference')
        s=spans[ref]
        return {'document_id':s['document_id'],'quote':s['text'],'start':s['start'],'end':s['end']}
    def citations(items):
        if not isinstance(items,list): raise ValueError('Citation references must be an array')
        return [citation(ref) for ref in items]
    for key in ('entities','choices','propositions'):
        if not isinstance(output.get(key),list): raise ValueError('Missing IR arrays')
        for row in output[key]:
            if not isinstance(row,dict) or 'citations' not in row: raise ValueError('Missing cited row')
            row['citations']=citations(row['citations'])
    if not isinstance(output.get('bindings'),list): raise ValueError('Missing binding array')
    for row in output['bindings']:
        if not isinstance(row,dict): raise ValueError('Invalid binding')
        row['mention']=citation(row.get('mention'))
        row['antecedent']=citation(row.get('antecedent'))
    if not isinstance(output.get('combination'),dict): raise ValueError('Missing combination policy')
    output['combination']['citations']=citations(output['combination'].get('citations'))
    output['schema']='retrace.source-ir.v6c'
    return output


def compile_cited_ir(value,documents,registry=None):
    result=compile_source_ir(expand_ir(value,documents),documents,registry)
    return {**result,'citation_transport':'source_span_references_v6d','source_segments':source_segments(documents),
            'source_packet_sha256':hashlib.sha256(json.dumps(documents,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()}


def audit_cited_ir(value,documents,candidates,registry=None):
    result=audit_source_ir(expand_ir(value,documents),documents,candidates,registry)
    return {**result,'citation_transport':'source_span_references_v6d'}


# The semantic contract is unchanged; only citation representation is adapted.
IR_V6D_INSTRUCTIONS=IR_INSTRUCTIONS.replace('retrace.source-ir.v6c',SCHEMA)
_start=IR_V6D_INSTRUCTIONS.index('CITATION:')
_end=IR_V6D_INSTRUCTIONS.index('Binding:',_start)
IR_V6D_INSTRUCTIONS=IR_V6D_INSTRUCTIONS[:_start]+'''CITATION is a single span_id STRING from source_segments, e.g. "s0123456789abcdef". Every citations field is an array of these strings. Never retype a quote, document ID, offset or hash. The deterministic adapter resolves each selected span to its exact source text and code-point offsets. A span's presence verifies location, not entailment. Read all segments as connected source text; segment boundaries do not decide scope or meaning.
'''+IR_V6D_INSTRUCTIONS[_end:]
IR_V6D_INSTRUCTIONS=IR_V6D_INSTRUCTIONS.replace('source_documents as data','source_segments as data')
