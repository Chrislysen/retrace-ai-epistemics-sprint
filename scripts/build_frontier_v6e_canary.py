"""Third distinct feasibility diagnostic: explicit example and larger output allowance."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.source_ir_v6d import model_source
from retrace.source_ir_v6e_prompt import IR_V6E_INSTRUCTIONS
from scripts.build_frontier_v6c_canary import MODELS,VERDICT_INSTRUCTIONS


def source_cases():
    verdict={'source_documents':[{'id':'assembly-note','text':'For a model boat exhibit, evidence K31 and L32 are locally eligible originals with no parents. Evidence M33 is locally eligible and is a copy that requires only K31. Claim Q34 requires M33 and L32 together as its sole sufficient bundle. Decision R35 requires only Q34. These are the complete current rules.'}],
             'registry':{'evidence':['K31','L32','M33'],'claims':['Q34'],'decisions':['R35']},
             'document_groups':[{'id':'register-sheet','evidence_ids':['K31']}],
             'current_exclusions':{'revoked_documents':[],'revoked_passages':['L32']},'requested_decisions':['R35'],
             'task':'Evaluate this final snapshot: the register-sheet document veto has been cleared, but the separate passage veto on L32 remains.'}
    docs=[{'id':'counts','text':'At a toy theatre, evidence A21 and evidence B22 are locally eligible original observations without parents. Evidence C23 is an original observation without parents and is locally ineligible. Evidence D24 is a locally eligible assembly certificate.'},
          {'id':'assembly','text':'The assembly entry identifies A21 and B22 together as the complete required inputs to D24. That certificate contains no independent observation: it is a copy and requires both originals in addition to its own eligibility. C23 is not a parent of D24. A historical proposal would have used C23 as its sole parent; that proposal was rejected.'},
          {'id':'readings','text':'Claim R25 has exactly two admitted unresolved policy readings: the first accepts D24 alone or C23 alone as alternative sufficient routes; the second requires D24 and C23 together as its sole sufficient bundle. Claim T26 accepts B22 alone. Decision Y27 requires only R25; decision Z28 requires only T26. These are the complete current rules and there are no other choices.'}]
    registry={'evidence':['A21','B22','C23','D24'],'claims':['R25','T26'],'decisions':['Y27','Z28']}
    return verdict,docs,registry


def expected_family():
    from copy import deepcopy
    graph={'evidence':[{'id':i,'kind':'root','parents':[],'active':i!='C23'} for i in ['A21','B22','C23']]+
                       [{'id':'D24','kind':'copy','parents':['A21','B22'],'active':True}],
           'claims':[{'id':'R25','supports':[['D24'],['C23']]},{'id':'T26','supports':[['B22']]}],
           'decisions':[{'id':'Y27','requires':['R25']},{'id':'Z28','requires':['T26']}]}
    other=deepcopy(graph);other['claims'][0]['supports']=[['D24','C23']]
    return [graph,other]


def build():
    verdict,docs,registry=source_cases();slots=[]
    for index,model in enumerate(MODELS):
        for suffix,condition,payload,instructions,limit in [
            ('verdict','canary_verdict',verdict,VERDICT_INSTRUCTIONS,8192),
            ('ir','canary_source_ir',model_source(docs,registry),IR_V6E_INSTRUCTIONS,65536)]:
            slots.append({'slot_id':f'canary-v6e-{index+1}-{suffix}','case_id':'canary-v6e-new-'+suffix,
                          'model':model,'condition':condition,'phase':'probe','instructions':instructions,
                          'input':json.dumps(payload,ensure_ascii=False,separators=(',',':')),
                          'max_output_tokens':limit,'temperature':0.0})
    return slots


if __name__=='__main__':
    with (ROOT/'data/frontier-v6e-canary-sessions.json').open('x',encoding='utf-8',newline='\n') as f:
        json.dump(build(),f,ensure_ascii=False,indent=2);f.write('\n')
