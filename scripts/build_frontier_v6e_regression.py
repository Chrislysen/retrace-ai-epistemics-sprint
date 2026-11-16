"""Prespecified replay of eight already observed failures; not a fresh holdout."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.source_ir_v6d import model_source
from retrace.source_ir_v6e_prompt import IR_V6E_INSTRUCTIONS
from scripts.build_frontier_v6e_sessions import IR_PREAMBLE,REFUTER_INSTRUCTIONS
from scripts.build_frontier_v6c_canary import MODELS


def study(old):
    cases=[]
    for index,case in enumerate(old['cases'],1):
        public=case['public'];expected=deepcopy(public['candidates'])
        if index==1:
            for candidate in expected:
                for e in candidate['graph']['evidence']:
                    if e['id'] in ('YTDR9M4C','ARF9JNBM'):
                        e.update(kind='copy',parents=['9SBDYPWH'])
        elif index==2:
            for candidate in expected:
                for e in candidate['graph']['evidence']:
                    if e['id'] in ('ZS7FLMYP','TEUMNK5P'):
                        e['parents'].append('KT2S6PRM')
        elif index==3:
            for candidate in expected:
                for claim in candidate['graph']['claims']:
                    if claim['id']=='BWN7Y4TJ':
                        claim['supports']=[['WHHC3V5X','LQ6TR2TX'],['BCGQKF2B','LQ6TR2TX']]
        elif index==4:
            expected=[]
        cases.append({'id':case['id'],'public':{'source_documents':deepcopy(public['prose']),
                     'registry':deepcopy(public['registry']),'candidates':deepcopy(public['candidates'])},
                     'evaluation':{'positive':index<=4,'expected_family':expected,
                                   'unidentified_ancestor_targets':['TP62C5Q7','DN77UDK7'] if index==4 else [],
                                   'basis':'Manual graph-level annotation from already observed source; no expected graph passed to extractor.'}})
    return {'schema':'retrace.frontier-v6d-development-regression.v1','cases':cases,
            'scope':'Eight observed v6b failure/control packets, reused as development diagnostics, not primary or held-out evidence.'}


def sessions(data):
    slots=[]
    for model in MODELS:
        for case in data['cases']:
            for arm in ('source_ir','adversarial_refuter'):
                public=case['public'];payload=model_source(public['source_documents'],public['registry'])
                if arm=='adversarial_refuter':payload['supplied_candidates']=deepcopy(public['candidates'])
                slots.append({'slot_id':model+'::regression::'+case['id']+'::'+arm,'case_id':case['id'],
                              'model':model,'condition':arm,'phase':'development_regression',
                              'instructions':IR_PREAMBLE+IR_V6E_INSTRUCTIONS if arm=='source_ir' else REFUTER_INSTRUCTIONS,
                              'input':json.dumps(payload,ensure_ascii=False,separators=(',',':')),
                              'max_output_tokens':65536,'temperature':0.0})
    return slots


if __name__=='__main__':
    source=ROOT/'data/conservation-v6b-holdout-reviewed.json'
    data=study(json.loads(source.read_text(encoding='utf-8')))
    data['original_corpus_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    for filename,value in [('frontier-v6e-regression.json',data),('frontier-v6e-regression-sessions.json',sessions(data))]:
        with (ROOT/'data'/filename).open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
