"""Ten prospective contract probes outside the sixty-case study. No API access.

Constructed after observing earlier revisions' formatting failures, so this is
a feasibility diagnostic and must not be described as independent validation.
"""
from copy import deepcopy
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.adaption_v6h import PRIMARY_MODELS,validate_slots
from retrace.source_ir_v6d import source_segments,model_source
from retrace.source_ir_v6h import compile_ir
from retrace.prompts_v6h import IR_INSTRUCTIONS,REFUTER_INSTRUCTIONS
from retrace.graph_identity_v6h import family_score

CASE_ID='canary-v6h-origami'

def source():
    docs=[
        {'id':'catalog','text':'This fictional origami exhibition has evidence records H71, I72, J73, K74, L75, M76 and N77. All seven are locally eligible. H71, L75, M76 and N77 are original root records with no required parents.'},
        {'id':'first-copy','text':'I72 is a copy of H71, its only required parent. J73 is a second copy of that same original, H71; it has that original as its only required parent, rather than I72.'},
        {'id':'assembly','text':'K74 is a copy assembled jointly from I72 and J73. Those two records are its entire direct parent list; neither one alone suffices. Local eligibility remains required for every record.'},
        {'id':'reading','text':'Claim P78 has exactly two unresolved positive readings. In reading narrow, the complete positive warrant is K74 unless M76 is usable, OR the protected alternative L75. M76 blocks only the K74 route. In reading wide, the complete positive warrant is (K74 OR L75) unless M76 is usable; M76 blocks the whole disjunction. Both readings are admitted, neither preferred, and no other readings exist.'},
        {'id':'polarity','text':'In both readings, N77 is the complete explicit warrant for the opposite conclusion of P78. This is a polar rebuttal, not a statement that P78 lacks positive evidence. Claim Q79 accepts L75 alone, with no negative warrant. Decision R80 requires P78 alone, and decision S81 requires Q79 alone. These statements are the exhaustive current rules, with equal-standing defeasible warrants.'}]
    return docs,{'evidence':['H71','I72','J73','K74','L75','M76','N77'],'claims':['P78','Q79'],'decisions':['R80','S81']}

def ref(i):return {'ref':i}
def unless(a,u):return {'unless':{'support':a,'undercutter':u}}
def positive(reading):
    return {'any':[unless(ref('K74'),ref('M76')),ref('L75')]} if reading=='narrow' else unless({'any':[ref('K74'),ref('L75')]},ref('M76'))

def expected_family():
    family=[]
    for reading in ('narrow','wide'):
        evidence=[{'id':i,'kind':'root','parents':[],'active':True} for i in ('H71','L75','M76','N77')]
        evidence += [{'id':i,'kind':'copy','parents':parents,'active':True} for i,parents in [('I72',['H71']),('J73',['H71']),('K74',['I72','J73'])]]
        family.append({'id':reading,'graph':{'schema':'retrace.tiered-graph.v6h','evidence':evidence,
            'claims':[{'id':'P78','positive':positive(reading),'negative':ref('N77')},
                      {'id':'Q79','positive':ref('L75'),'negative':{'const':False}}],
            'decisions':[{'id':'R80','requires':['P78']},{'id':'S81','requires':['Q79']}]}})
    return family

def seeds():
    value=deepcopy(expected_family())
    for row in value:
        next(e for e in row['graph']['evidence'] if e['id']=='K74')['parents']=['I72']
        row['graph']['claims'][0]['negative']={'const':False}
    return value

def reference_ir():
    docs,registry=source();spans={r['document_id']:r['span_id'] for r in source_segments(docs)}
    ir={'schema':'retrace.source-ir.v6h','entities':[], 'bindings':[],
        'choices':[{'id':'scope','options':['narrow','wide'],'citations':[spans['reading']]}],
        'combination':{'mode':'cartesian','assignments':[],'citations':[]},'propositions':[]}
    for category,kind in [('evidence','evidence'),('claims','claim'),('decisions','decision')]:
        for ident in registry[category]:
            doc='catalog' if category=='evidence' else 'reading' if ident=='P78' else 'polarity'
            ir['entities'].append({'id':ident,'type':kind,'operational':True,'citations':[spans[doc]]})
    def add(kind,target,body,doc,when=None):
        ir['propositions'].append({'id':'p'+str(len(ir['propositions'])),'kind':kind,'target':target,'body':body,
            'scope':'current','when':when or {},'citations':[spans[doc]],'bindings':[]})
    for row in expected_family()[0]['graph']['evidence']:
        add('eligibility',row['id'],{'active':True},'catalog')
        add('origin',row['id'],{'kind':row['kind'],'parents':row['parents']},'catalog' if row['kind']=='root' else 'assembly' if row['id']=='K74' else 'first-copy')
    for reading in ('narrow','wide'):
        add('support','P78',{'positive':positive(reading),'negative':ref('N77')},'reading',{'scope':reading})
        ir['propositions'][-1]['citations'].append(spans['polarity'])
    add('support','Q79',{'positive':ref('L75'),'negative':{'const':False}},'polarity')
    for ident,claim in [('R80','P78'),('S81','Q79')]:add('requirement',ident,{'requires':[claim]},'polarity')
    if not family_score(compile_ir(ir,docs,registry)['candidates'],expected_family())['exact_family']:raise AssertionError('Canary reference mismatch')
    return ir

def build():
    reference_ir();docs,registry=source();slots=[]
    for model in PRIMARY_MODELS:
        for arm,prompt in [('source_ir',IR_INSTRUCTIONS),('refuter',REFUTER_INSTRUCTIONS)]:
            packet=model_source(docs,registry)
            if arm=='refuter':packet['supplied_candidates']=seeds()
            slots.append({'slot_id':'canary-v6h::'+model+'::'+arm,'case_id':CASE_ID,'model':model,
                'condition':'canary_'+arm,'phase':'probe','instructions':prompt,'input':json.dumps(packet,ensure_ascii=False,separators=(',',':')),
                'max_output_tokens':32768,'temperature':1.0})
    validate_slots(slots,canary=True)
    return slots

if __name__=='__main__':
    path=ROOT/'data/frontier-v6h-canary-sessions.json'
    with path.open('x',encoding='utf-8',newline='\n') as f:json.dump(build(),f,ensure_ascii=False,indent=2);f.write('\n')
    print('Wrote10 canary slots outside the60-case corpus.')
