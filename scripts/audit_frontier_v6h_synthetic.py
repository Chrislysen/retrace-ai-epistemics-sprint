"""Independent, offline synthetic projection and phase audit. No provider calls.

Uses scalar truth tables rather than the BDD normalizer under audit. Legacy
source text is checked exactly against its prior audited frozen bytes. New F5
phase expectations were hand reconstructed from the source narratives.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from itertools import product
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.build_frontier_v6h_legacy import build as legacy_build
from scripts.build_frontier_v6h_polar_cases import build_cases
from retrace.source_ir_v6h import compile_ir
from retrace.source_ir_v6d import source_segments
from retrace.tiered_v6h import analyze,family_supervaluation
from retrace.graph_identity_v6h import graph_key,family_score


def check(ok,label):
    if not ok:raise AssertionError(label)


def encode(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(v):return sha256(encode(v).encode()).hexdigest()


def refs(expr):
    op,arg=next(iter(expr.items()))
    if op=='ref':return {arg}
    if op in ('const','none'):return set()
    return set().union(*(refs(x) for x in (arg.values() if op=='unless' else arg)))


def truth(expr,values):
    op,arg=next(iter(expr.items()))
    if op=='ref':return values[arg]
    if op=='const':return arg
    if op=='none':return False
    if op=='all':return all(truth(x,values) for x in arg)
    if op=='any':return any(truth(x,values) for x in arg)
    if op=='unless':return truth(arg['support'],values) and not truth(arg['undercutter'],values)
    raise AssertionError('unknown scalar constructor')


def local_signature(expr):
    """Truth-function signature with irrelevant atoms removed, no BDD import."""
    variables=sorted(refs(expr));check(len(variables)<=12,'local truth-table bound')
    table={bits:truth(expr,dict(zip(variables,bits))) for bits in product((False,True),repeat=len(variables))}
    essential=[]
    for i,v in enumerate(variables):
        if any(value!=table[bits[:i]+(not bits[i],)+bits[i+1:]] for bits,value in table.items()):essential.append(v)
    vector=[]
    for bits in product((False,True),repeat=len(essential)):
        values={v:False for v in variables};values.update(zip(essential,bits));vector.append(truth(expr,values))
    return essential,vector


def independent_graph_key(graph):
    result={'evidence':sorted([{'id':r['id'],'kind':r['kind'],'active':r['active'],'parents':sorted(r['parents'])} for r in graph['evidence']],key=lambda x:x['id']),
        'claims':sorted([{'id':r['id'],'positive':local_signature(r['positive']),'negative':local_signature(r['negative'])} for r in graph['claims']],key=lambda x:x['id']),
        'decisions':sorted([{'id':r['id'],'requires':sorted(r['requires'])} for r in graph['decisions']],key=lambda x:x['id'])}
    return digest(result)


def convert_scalar(old):
    def dnf(routes):
        if not routes:return {'const':False}
        cs=[{'ref':c[0]} if len(c)==1 else {'all':[{'ref':x} for x in c]} for c in routes]
        return cs[0] if len(cs)==1 else {'any':cs}
    return {'schema':'retrace.tiered-graph.v6h','evidence':deepcopy(old['evidence']),
        'claims':[{'id':r['id'],'positive':dnf(r['supports']),'negative':{'const':False}} for r in old['claims']],
        'decisions':deepcopy(old['decisions'])}


def legacy_scalar(old,excluded):
    values={};pending={r['id']:('evidence',r) for r in old['evidence']}
    pending.update({r['id']:('claim',r) for r in old['claims']})
    pending.update({r['id']:('decision',r) for r in old['decisions']})
    while pending:
        count=len(pending)
        for ident,(kind,row) in list(pending.items()):
            deps=row['parents'] if kind=='evidence' else [x for c in row['supports'] for x in c] if kind=='claim' else row['requires']
            if any(x not in values for x in deps):continue
            values[ident]=(row['active'] and ident not in excluded and all(values[x] for x in deps)) if kind=='evidence' else (any(all(values[x] for x in c) for c in row['supports']) if kind=='claim' else all(values[x] for x in deps))
            del pending[ident]
        check(len(pending)<count,'scalar DAG cycle')
    return {r['id']:values[r['id']] for r in old['decisions']}


def vetoes(case,state):
    groups={d['id']:d['evidence_ids'] for d in case['events']['document_groups']}
    docs=sorted({e for d in state['revoked_documents'] for e in groups[d]})
    return {'document_vetoes':docs,'passage_vetoes':state['revoked_passages']}


# Hand-derived ordered (D,J) per-world states for initial/withdrawn/restored.
S='supported';N='not_supported';C='contested';U='insufficient_provenance'
F5_EXPECTED=[
    [[(S,S)],[(S,S)],[(N,N)]],
    [[(N,N)],[(S,S)],[(N,N)]],
    [[(C,C)],[(S,N)],[(C,N)]],
    [[(S,C)],[(S,S)],[(S,S)]],
    [[(S,S),(S,S)],[(N,S),(N,S)],[(S,S),(N,S)]],
    [[(N,S)],[(U,U)],[(N,N)]],
    [[(S,S)],[(C,C)],[(S,S)]],
    [[(S,S),(N,N)],[(S,S),(S,S)],[(N,N),(N,N)]]]


def audit():
    old_raw=(ROOT/'data/frontier-v6c-staged.json').read_bytes();old=json.loads(old_raw)
    check(sha256(old_raw).hexdigest()=='0dd2d6d05a27049db7f5050d2f5b768c9dc6b0492161df594942b1e82a6d0c8a','prior source hash')
    originals={c['id']:c for c in old['cases']};legacy=legacy_build(old);polar=build_cases();cases=legacy+polar
    check(Counter(c['family_id'] for c in cases)==Counter({f'F{i}':8 for i in range(1,7)}),'six families eight each')
    check(len({c['id'] for c in cases})==48,'unique IDs')
    counts=Counter();by_case=[];normalizer_map={};independent_map={}
    def audit_identity(graph):
        independent=independent_graph_key(graph);production=graph_key(graph)
        check(normalizer_map.get(production,independent)==independent,'BDD false identity collision')
        check(independent_map.get(independent,production)==production,'BDD failed equivalent identity')
        normalizer_map[production]=independent;independent_map[independent]=production
        counts['identity_graph_checks']+=1
        return independent
    for case in cases:
        compiled=compile_ir(case['evaluation']['reference_ir'],case['public']['source_documents'],case['public']['registry'])
        wanted={audit_identity(c['graph']) for c in case['evaluation']['source_family']}
        got={audit_identity(c['graph']) for c in compiled['candidates']}
        check(wanted==got and not compiled['registry_coverage_gaps'],'IR family/source inventory')
        check(family_score(compiled['candidates'],case['evaluation']['source_family'])['expected_distinct']==len(wanted),'normalizer family count')
        seeds={audit_identity(c['graph']) for c in case['authored_seed_pool']['candidates']}
        check((seeds==wanted)==(case['evaluation']['seed_kind']=='faithful_complete'),'independent seed status')
        phases={'hist_init':'initial','hist_withdrawn':'withdrawn','hist_restored':'restored','evt_no_commit':'withdrawn','fresh_withdrawn':'withdrawn','fresh_restored':'restored'}
        for phase,state_name in phases.items():
            check(case['phases'][phase]['state_name']==state_name and case['phases'][phase]['state']==case['events']['states'][state_name],'phase alias state')
            counts['phase_mapping_checks']+=1
        if case in legacy:
            before=originals[case['source_revision']['original_case_id']]
            check(case['public']==before['public'],'legacy public changed')
            check(case['events']==before['events'] and case['phases']==before['phases'],'legacy event/phase changed')
            check(case['evaluation']['legacy_dependency_constraints']==[p for p in before['evaluation']['reference_ir']['propositions'] if p['kind']=='dependency'],'legacy dependency audit annotations changed')
            counts['legacy_public_packets_exact']+=1
            old_by_id={r['id']:r['graph'] for r in before['evaluation']['source_family']}
            for candidate in case['evaluation']['source_family']:
                old_graph=old_by_id[candidate['id']]
                check(audit_identity(convert_scalar(old_graph))==audit_identity(candidate['graph']),'scalar local graph conversion')
                for state_name,state in case['events']['states'].items():
                    options=vetoes(case,state);excluded=set(options['document_vetoes']+options['passage_vetoes'])
                    wanted_truth=legacy_scalar(old_graph,excluded)
                    actual=analyze(candidate['graph'],**options)['decisions']
                    check({d:r['box_supported'] for d,r in actual.items()}==wanted_truth,'legacy modal truth mismatch')
                    check(all(r['box_supported']==r['diamond_supported'] and r['state']==(S if wanted_truth[d] else N) for d,r in actual.items()),'legacy spurious four-state outcome')
                    counts['legacy_graph_state_checks']+=1;counts['legacy_decision_checks']+=len(actual)
                counts['legacy_worlds']+=1
            # Check every converted quote points inside the corresponding exact
            # paragraph and codepoint interval, without using builder citation().
            spans={s['span_id']:s for s in source_segments(case['public']['source_documents'])}
            new_ir=case['evaluation']['reference_ir'];old_ir=before['evaluation']['reference_ir']
            pairs=[]
            for category in ('entities','choices'):
                index={r['id']:r for r in old_ir[category]}
                pairs.extend((index[r['id']]['citations'],r['citations']) for r in new_ir[category])
            pi={r['id']:r for r in old_ir['propositions']}
            pairs.extend((pi[r['id']]['citations'],r['citations']) for r in new_ir['propositions'])
            pairs.append((old_ir['combination']['citations'],new_ir['combination']['citations']))
            bi={r['id']:r for r in old_ir['bindings']}
            for row in new_ir['bindings']:
                for key in ('mention','antecedent'):pairs.append(([bi[row['id']][key]],[row[key]]))
            for quotes,ids in pairs:
                for q in quotes:
                    matches=[s for s in spans.values() if s['document_id']==q['document_id'] and q['quote'] in s['text'] and ('start' not in q or s['start']<=q['start']<=q['end']<=s['end'])]
                    check(len(matches)==1 and matches[0]['span_id'] in ids,'citation conversion')
                    counts['exact_quote_segment_checks']+=1
        else:
            n=case['within_family_index']-1;keys=case['evaluation']['semantic_key_ids']
            for state_index,state_name in enumerate(('initial','withdrawn','restored')):
                opts=vetoes(case,case['events']['states'][state_name]);gold=case['evaluation']['state_gold'][state_name]
                for i,candidate in enumerate(case['evaluation']['source_family']):
                    d,j=F5_EXPECTED[n][state_index][i]
                    expected={keys['D']:d,keys['J']:j,keys['K']:S,keys['H']:N}
                    actual=analyze(candidate['graph'],**opts)['decisions']
                    check({key:row['state'] for key,row in actual.items()}==expected,'hand reconstructed F5 state')
                    check(gold['candidate_decisions'][candidate['id']]==actual,'stored F5 state gold')
                    for key,state in expected.items():
                        check(actual[key]['box_supported']==(state==S),'F5 box')
                        check(actual[key]['diamond_supported']==(state in (S,U)),'F5 diamond')
                    counts['polar_graph_state_checks']+=1;counts['polar_decision_checks']+=4
                fresh=family_supervaluation([r['graph'] for r in case['evaluation']['source_family']],**opts)['decisions']
                check(fresh==gold['family_decisions'],'stored F5 modal family gold')
        by_case.append({'id':case['id'],'public_sha256':digest(case['public']),'family_worlds':len(case['evaluation']['source_family']),
                        'distinct_normalized_graphs':len(wanted),'independent_seed_exact':seeds==wanted})
    counts['synthetic_cases']=48;counts['new_polar_cases']=8
    return {'schema':'retrace.frontier-v6h-synthetic-independent-audit.v1','status':'passed',
        'counts':dict(counts),'families':dict(Counter(c['family_id'] for c in cases)),
        'legacy_source_sha256':sha256(old_raw).hexdigest(),'generated_48_cases_sha256':digest(cases),
        'case_records':by_case,'review_scope':'40 unchanged source packets preserve prior AI prose audit; new8F5 narratives independently checked against hand phase expectations. Computational checks are independent scalar truth tables, not human annotation.',
        'no_provider_calls':True,'input_hashes':{p:sha256((ROOT/p).read_bytes()).hexdigest() for p in (
            'scripts/build_frontier_v6h_legacy.py','scripts/build_frontier_v6h_polar_cases.py','retrace/source_ir_v6h.py',
            'retrace/tiered_v6h.py','retrace/boolean_v6h.py','retrace/argumentation_v6h.py','retrace/graph_identity_v6h.py',
            'research/frontier-v6c-case-audit.md','scripts/audit_frontier_v6h_synthetic.py')}}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output');a=p.parse_args();result=audit()
    if a.output:
        with Path(a.output).open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,ensure_ascii=False);f.write('\n')
    print(json.dumps({'status':result['status'],'counts':result['counts']},indent=2))
