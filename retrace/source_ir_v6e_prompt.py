"""Prospective formatting example; semantic compiler and citation adapter unchanged."""
import json
from .source_ir_v6d import IR_V6D_INSTRUCTIONS,model_source,source_segments,compile_cited_ir


def example():
    docs=[{'id':'example-doc','text':'Example record EXA is a locally eligible original with no parents. Example record EXB is locally eligible and is a copy whose sole required parent is EXA. Claim EXC accepts EXB alone. Decision EXD requires only EXC. These are the complete rules and there is no interpretive uncertainty.'}]
    registry={'evidence':['EXA','EXB'],'claims':['EXC'],'decisions':['EXD']}
    span=source_segments(docs)[0]['span_id']
    ir={'schema':'retrace.source-ir.v6d','entities':[
        {'id':ident,'type':kind,'operational':True,'citations':[span]}
        for ident,kind in [('EXA','evidence'),('EXB','evidence'),('EXC','claim'),('EXD','decision')]],
        'bindings':[],'choices':[],'combination':{'mode':'cartesian','assignments':[],'citations':[]},'propositions':[]}
    for target,kind,body in [('EXA','eligibility',{'active':True}),('EXA','origin',{'kind':'root','parents':[]}),
                             ('EXB','eligibility',{'active':True}),('EXB','origin',{'kind':'copy','parents':['EXA']}),
                             ('EXC','support',{'expr':{'ref':'EXB'}}),('EXD','requirement',{'requires':['EXC']})]:
        ir['propositions'].append({'id':'example_p'+str(len(ir['propositions'])),'kind':kind,'target':target,'body':body,
                                  'scope':'current','polarity':'assert','when':{},'citations':[span],'bindings':[]})
    return docs,registry,ir


_docs,_registry,_ir=example()
IR_V6E_INSTRUCTIONS=(IR_V6D_INSTRUCTIONS+
    '\n\nFORMATTING EXAMPLE ONLY. Its EX-prefixed IDs and source spans are not part of your task. '
    'This is a complete valid example; do not copy its facts into the supplied source.\nExample input:\n'+
    json.dumps(model_source(_docs,_registry),ensure_ascii=False,separators=(',',':'))+
    '\nExample output:\n'+json.dumps(_ir,ensure_ascii=False,separators=(',',':'))+
    '\n\nFor the actual source, use its own IDs and span references. Every origin body has BOTH kind and parents, '
    'including {"kind":"root","parents":[]}. Every proposition has all nine fields shown in the contract; '
    'do not omit empty arrays or empty when objects. Preserve each explicitly admitted interpretation. '
    'Emit the complete JSON directly once the source reading is determined; do not explain the schema in the answer.')
