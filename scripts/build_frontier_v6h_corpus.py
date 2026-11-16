"""Assemble and freeze-ready validate the60-case revision, exclusively additive.

Writing the corpus is not itself a paid-execution freeze. The final freeze also
binds sources, prompts, projections, runtime, scoring code and audit evidence.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.build_frontier_v6h_legacy import build as legacy_cases
from scripts.build_frontier_v6h_polar_cases import build_cases as polar_cases
from retrace.source_ir_v6h import compile_ir
from retrace.tiered_v6h import analyze,family_supervaluation
from retrace.graph_identity_v6h import family_score
from scripts.build_frontier_v6h_sessions import exclusions


def digest_file(path):return sha256(path.read_bytes()).hexdigest()


def build():
    from scripts.build_frontier_v6h_ecological import build_cases as ecological_cases
    old=ROOT/'data/frontier-v6c-staged.json'
    cases=legacy_cases(json.loads(old.read_text(encoding='utf-8')))+polar_cases()+ecological_cases()
    if len(cases)!=60 or len({case['id'] for case in cases})!=60:raise ValueError('Exactly60 unique cases')
    if Counter(c['family_id'] for c in cases if c['partition']=='synthetic')!=Counter({f'F{i}':8 for i in range(1,7)}):raise ValueError('Synthetic family counts')
    if {c['id'] for c in cases if c['partition']=='ecological'}!={f'ECO-{i:02}' for i in range(1,13)}:raise ValueError('Ecological case IDs')
    for case in cases:
        public=case['public'];gold=case['evaluation'];family=gold['source_family']
        compiled=compile_ir(gold['reference_ir'],public['source_documents'],public['registry'])
        if compiled['registry_coverage_gaps'] or not family_score(compiled['candidates'],family)['exact_family']:
            raise ValueError('Reference source proposition/family disagreement:'+case['id'])
        if 'state_gold' in gold:
            gold['inherited_state_gold']=deepcopy(gold['state_gold'])
        states={}
        for name,state in case['events']['states'].items():
            opts=exclusions(case,state)
            decisions=family_supervaluation([row['graph'] for row in family],**opts)['decisions']
            states[name]={'candidate_decisions':{row['id']:analyze(row['graph'],**opts)['decisions'] for row in family},
                          'family_decisions':decisions,
                          'verdict':{'decisions':{ident:{'box_supported':row['box_supported'],'diamond_supported':row['diamond_supported'],
                                     'states':sorted(set(row['states_by_candidate']))} for ident,row in decisions.items()}}}
        gold['state_gold']=states
        gold['identity_convention']='Direct lineage retained; per-claim positive/negative Boolean expression canonicalized with claim references as atoms. Equivalent assignments remain declared; distinct family scoring deduplicates canonical graphs.'
        if case['partition']=='synthetic':gold['independent_audit']='research/frontier-v6h-synthetic-audit.md'
        else:gold['independent_audit']='research/frontier-v6h-ecological-review.md'
    selected=[c['id'] for c in cases if c['partition']=='synthetic' and c['within_family_index'] in (1,4,5,8)]
    if len(selected)!=24:raise ValueError('Long subset count')
    return {'schema':'retrace.frontier-v6h-corpus.v1','created_at':datetime.now(timezone.utc).isoformat(),'cases':cases,
            'long_context_subset_ids':selected,'prior_primary_inference_calls':0,
            'legacy_source_corpus_sha256':digest_file(old),
            'ecological_source_manifest_sha256':digest_file(ROOT/'research/ecological-v6h-sources.json'),
            'provenance':'40 source packets inherited unchanged from an unissued primary design;8 new synthetic polar/undercutter cases;12 source-bound ecological operationalizations. AI-assisted authoring/audits, not independent human annotation or a natural-document random sample.',
            'exposure_status':'Prior development/canary outcomes are disclosed separately. No output from these60 primary cases was used to select instructions or cases.',
            'confidential_evaluation_fields':'evaluation and authored_seed_pool are never projected to ordinary source/extraction/commitment arms; seeds only to labeled refuter, oracle only to labeled oracle/assisted arms.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-reviewed-corpus',action='store_true',required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'data/frontier-v6h-corpus.json')
    args=parser.parse_args();value=build()
    with args.output.open('x',encoding='utf-8',newline='\n') as stream:json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps({'cases':len(value['cases']),'path':args.output.relative_to(ROOT).as_posix(),'sha256':digest_file(args.output)}))
