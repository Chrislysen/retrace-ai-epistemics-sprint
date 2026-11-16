"""Canonical identity under local Boolean regrouping; explicit lineage retained.

Claim references remain atoms, preserving the structured argument graph. This
does not collapse an intermediate claim into its upstream evidence or certify
that either formulation is entailed by source prose.
"""
from hashlib import sha256
import json
from .boolean_v6h import BDD
from .tiered_v6h import validate


def canonical_graph(graph):
    graph, index, category, _, _ = validate(graph)
    manager = BDD(sorted(ident for ident in index if category[ident] != 'decisions'))
    signatures = {0:'false',1:'true'}
    def signature(root):
        if root not in signatures:
            level, low, high = manager.nodes[root]
            signatures[root] = sha256(json.dumps([manager.variables[level],signature(low),signature(high)],separators=(',',':')).encode()).hexdigest()
        return signatures[root]
    return {'evidence': sorted([{'id':row['id'],'kind':row['kind'],'active':row['active'],'parents':sorted(row['parents'])} for row in graph['evidence']],key=lambda r:r['id']),
            'claims': sorted([{'id':row['id'],'positive':signature(manager.compile(row['positive'])),'negative':signature(manager.compile(row['negative']))} for row in graph['claims']],key=lambda r:r['id']),
            'decisions': sorted([{'id':row['id'],'requires':sorted(row['requires'])} for row in graph['decisions']],key=lambda r:r['id'])}


def graph_key(graph):
    return sha256(json.dumps(canonical_graph(graph),sort_keys=True,separators=(',',':')).encode()).hexdigest()


def family_score(predicted, reference):
    wanted = {graph_key(row.get('graph',row)) for row in reference}
    got = {graph_key(row.get('graph',row)) for row in predicted}
    overlap = wanted & got
    return {'exact_family':got==wanted,'expected_distinct':len(wanted),'predicted_distinct':len(got),
            'correct_distinct':len(overlap),'missing_distinct':len(wanted-got),'spurious_distinct':len(got-wanted),
            'precision':len(overlap)/len(got) if got else 0.,'recall':len(overlap)/len(wanted) if wanted else None}
