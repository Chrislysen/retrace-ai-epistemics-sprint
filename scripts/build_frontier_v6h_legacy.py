"""Lossless source projection of40 unissued legacy synthetic packets into v6h.

The eight old family5 packets remain untouched and are superseded by new scoped
undercutter/rebuttal cases in the new corpus. Prior primary inference count=0.
"""
from copy import deepcopy
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.source_ir_v6d import source_segments
from retrace.source_ir_v6h import SCHEMA, compile_ir
from retrace.tiered_v6h import from_positive_graph
from retrace.graph_identity_v6h import family_score


def expression(old):
    if 'none' in old:return {'const':False}
    if 'ref' in old:return deepcopy(old)
    op=next(iter(old));return {op:[expression(child) for child in old[op]]}


def source_ir(old,documents):
    spans=source_segments(documents)
    def citation(cite):
        matches=[s for s in spans if s['document_id']==cite['document_id'] and cite['quote'] in s['text']]
        if 'start' in cite:matches=[s for s in matches if s['start']<=cite['start'] and s['end']>=cite['end']]
        if len(matches)!=1:raise ValueError('Legacy quote needs unique exact segment')
        return matches[0]['span_id']
    result=deepcopy(old);result['schema']=SCHEMA
    for row in result['entities']+result['choices']:
        row['citations']=list(dict.fromkeys(citation(c) for c in row['citations']))
    for row in result['bindings']:
        row['mention']=citation(row['mention']);row['antecedent']=citation(row['antecedent'])
    result['combination']['citations']=list(dict.fromkeys(citation(c) for c in result['combination']['citations']))
    props=[]
    for prop in result['propositions']:
        if prop['kind']=='dependency':continue
        if prop.pop('polarity')!='assert':raise ValueError('Only positive definitions can be projected')
        if prop['kind']=='support':prop['body']={'positive':expression(prop['body']['expr']),'negative':{'const':False}}
        prop['citations']=list(dict.fromkeys(citation(c) for c in prop['citations']))
        props.append(prop)
    result['propositions']=props
    return result


def build(corpus):
    result=[]
    for old in corpus['cases']:
        # Canonical family labels are read, not guessed from free prose.
        if old['id'].split('-')[-2]=='05':continue
        case=deepcopy(old)
        case['partition']='synthetic';case['family_id']='F'+str(int(old['id'].split('-')[-2]))
        case['id']='V6H-'+old['id'];case['source_revision']={'original_case_id':old['id'],'public_prose_changed':False,
            'previous_primary_calls':0,'projection':'Positive rules retained; explicit negative warrant=false; Boolean-equivalent groupings normalized for scoring.'}
        docs=case['public']['source_documents']
        case['evaluation']['reference_ir']=source_ir(old['evaluation']['reference_ir'],docs)
        for location in (case['evaluation']['source_family'],case['authored_seed_pool']['candidates']):
            for candidate in location:candidate['graph']=from_positive_graph(candidate['graph'])
        compiled=compile_ir(case['evaluation']['reference_ir'],docs,case['public']['registry'])
        if not family_score(compiled['candidates'],case['evaluation']['source_family'])['exact_family']:
            raise ValueError('Legacy IR conversion changed family')
        case['evaluation']['legacy_dependency_constraints']=deepcopy([p for p in old['evaluation']['reference_ir']['propositions'] if p['kind']=='dependency'])
        case['evaluation']['legacy_constraints_note']='Previously validated structural constraints remain audit annotations; complete typed definitions carry their graph content. The new model contract does not request redundant dependency predicates.'
        result.append(case)
    if len(result)!=40:raise ValueError('Expected40 legacy non-family5 cases')
    return result


if __name__=='__main__':
    cases=build(json.loads((ROOT/'data/frontier-v6c-staged.json').read_text(encoding='utf-8')))
    print(json.dumps({'cases':len(cases),'source_worlds':sum(len(c['evaluation']['source_family']) for c in cases)}))
