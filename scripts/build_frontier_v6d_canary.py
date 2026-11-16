"""New off-benchmark canary for streaming and source-span references."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.build_frontier_v6c_canary import MODELS,VERDICT_INSTRUCTIONS
from retrace.source_ir_v6d import IR_V6D_INSTRUCTIONS,model_source


def source_cases():
    verdict={'source_documents':[{'id':'new-brief','text':'For a small print exhibition, records M7 and N8 are eligible independent observations. Record P9 is an eligible transcription of M7 and needs M7 as its sole parent. Review J4 accepts P9 alone or N8 alone; either route suffices. Decision Z6 requires only J4.'}],
             'registry':{'evidence':['M7','N8','P9'],'claims':['J4'],'decisions':['Z6']},
             'current_exclusions':{'revoked_documents':[],'revoked_passages':['M7']},'requested_decisions':['Z6']}
    docs=[
        {'id':'register','text':'In a volunteer sign-making register, evidence F2 and evidence G3 are locally eligible originals with no parents. Evidence H4 is an original with no parents but is locally ineligible. Evidence T5, the short transcript, remains locally eligible.'},
        {'id':'production','text':'The production entry identifies F2 as the sole source from which T5 was transcribed. That transcript needs its original in addition to its own eligibility. G3 is not a parent of T5. An obsolete draft proposed making T5 a copy of G3; the proposal is not adopted.'},
        {'id':'policy','text':'Claim V6 has exactly two unresolved policy readings: one requires T5 and H4 together as its sole sufficient bundle; the other accepts T5 alone as its sole sufficient bundle. Both readings remain admissible. Claim W7 requires H4 alone. Decision Y8 requires only V6. Decision Z9 requires only W7. These are the complete current rules; there are no other unresolved choices.'}]
    registry={'evidence':['F2','G3','H4','T5'],'claims':['V6','W7'],'decisions':['Y8','Z9']}
    return verdict,docs,registry


def build():
    verdict,docs,registry=source_cases();slots=[]
    for index,model in enumerate(MODELS):
        for suffix,condition,payload,instructions,limit in [
            ('verdict','canary_verdict',verdict,VERDICT_INSTRUCTIONS,8192),
            ('ir','canary_source_ir',model_source(docs,registry),IR_V6D_INSTRUCTIONS,16384)]:
            slots.append({'slot_id':f'canary-v6d-{index+1}-{suffix}','case_id':'canary-v6d-new-'+suffix,
                          'model':model,'condition':condition,'phase':'probe','instructions':instructions,
                          'input':json.dumps(payload,ensure_ascii=False,separators=(',',':')),
                          'max_output_tokens':limit,'temperature':0.0})
    return slots


if __name__=='__main__':
    with (ROOT/'data/frontier-v6d-canary-sessions.json').open('x',encoding='utf-8',newline='\n') as f:
        json.dump(build(),f,ensure_ascii=False,indent=2);f.write('\n')
