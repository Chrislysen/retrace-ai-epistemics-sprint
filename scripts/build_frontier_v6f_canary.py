"""New pacing/sampling feasibility diagnostic, before primary inference."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.build_frontier_v6e_canary import source_cases as prior_sources,expected_family as prior_family
from scripts.build_frontier_v6e_sessions import SAMPLE_INSTRUCTIONS
from scripts.build_frontier_v6c_canary import MODELS
from retrace.source_ir_v6d import model_source
from retrace.source_ir_v6e_prompt import IR_V6E_INSTRUCTIONS


def rename(value):
    text=json.dumps(value,ensure_ascii=False)
    for before,after in [('A21','U41'),('B22','V42'),('C23','W43'),('D24','X44'),('R25','J45'),('T26','K46'),('Y27','L47'),('Z28','M48'),
                         ('toy theatre','miniature harbour'),('assembly certificate','mooring certificate'),('assembly entry','mooring entry'),
                         ('"counts"','"observations"'),('"assembly"','"mooring"'),('"readings"','"harbour-policy"')]:
        text=text.replace(before,after)
    return json.loads(text)


def source_cases():
    _,docs,registry=prior_sources()
    return rename(docs),rename(registry)


def expected_family():return rename(prior_family())


def build():
    docs,registry=source_cases();slots=[]
    for index,model in enumerate(MODELS):
        for suffix,condition,payload,instructions,limit in [
            ('sample','canary_sample_graph',{'source_documents':docs,'registry':registry},SAMPLE_INSTRUCTIONS,16384),
            ('ir','canary_source_ir',model_source(docs,registry),IR_V6E_INSTRUCTIONS,65536)]:
            slots.append({'slot_id':f'canary-v6f-{index+1}-{suffix}','case_id':'canary-v6f-harbour',
                          'model':model,'condition':condition,'phase':'probe','instructions':instructions,
                          'input':json.dumps(payload,ensure_ascii=False,separators=(',',':')),
                          'max_output_tokens':limit,'temperature':1.0})
    return slots


if __name__=='__main__':
    with (ROOT/'data/frontier-v6f-canary-sessions.json').open('x',encoding='utf-8',newline='\n') as f:
        json.dump(build(),f,ensure_ascii=False,indent=2);f.write('\n')
