"""Prospective response parsing and graph-set scoring; never repairs model output."""
from __future__ import annotations

from copy import deepcopy
import json
import math

from .compact_graph import validate_explicit_graph
from .stress_v6c import _basis, _table


def parse_object(text):
    if not isinstance(text,str) or len(text)>524288: raise ValueError('Invalid output text length')
    source=text.strip(); fenced=False
    lines=source.splitlines()
    if len(lines)>=3 and lines[0].strip() in ('```','```json') and lines[-1].strip()=='```':
        source='\n'.join(lines[1:-1]).strip();fenced=True
    def pairs(values):
        obj={}
        for key,value in values:
            if key in obj: raise ValueError('Duplicate JSON key')
            obj[key]=value
        return obj
    def invalid(value): raise ValueError('Nonfinite JSON value')
    obj=json.loads(source,object_pairs_hook=pairs,parse_constant=invalid)
    if not isinstance(obj,dict): raise ValueError('Expected one JSON object')
    return obj,not fenced


def verdict(text,decision_ids):
    obj,strict=parse_object(text)
    if set(obj)!=set(decision_ids) or any(v not in ('supported','unsupported','disputed') for v in obj.values()):
        raise ValueError('Invalid decision vector')
    return obj,strict


def graph_value(value):
    graph=deepcopy(value)
    if not isinstance(graph,dict): raise ValueError('Graph must be an object')
    # Labels carry no formal semantics; sampling contract omits them. Their
    # absence in a copied authored comparison does not alter the source graph.
    for category in ('evidence','claims','decisions'):
        if isinstance(graph.get(category),list):
            for row in graph[category]:
                if isinstance(row,dict): row.pop('label',None)
    return validate_explicit_graph(graph)


def graph_signature(graph):
    return json.dumps(graph_value(graph),sort_keys=True,separators=(',',':'))


def family_score(predicted,expected):
    """Full scheduled family score. Empty predictions are failures, not dropped."""
    predicted_graphs=[graph_value(c.get('graph',c)) for c in predicted]
    expected_graphs=[graph_value(c.get('graph',c)) for c in expected]
    if not expected_graphs: raise ValueError('Missing authored family')
    p={graph_signature(g) for g in predicted_graphs};g={graph_signature(x) for x in expected_graphs}
    intersection=len(p&g)
    result={'predicted_distinct_graphs':len(p),'source_distinct_graphs':len(g),
            'correct_distinct_graphs':intersection,'exact_family':bool(p) and p==g,
            'precision':intersection/len(p) if p else 0.0,'recall':intersection/len(g),
            'missing_graphs':len(g-p),'spurious_graphs':len(p-g),
            'sampling_k10_capacity_can_cover':len(g)<=10}
    return result


def counterfactual_consensus_score(predicted,expected):
    """All local eligibility combinations, preserving candidate structure.

    This is explicitly a hypothetical eligibility audit, not ordinary restoration.
    Three-valued consensus per decision is compared over every bounded assignment.
    """
    gold=[graph_value(c.get('graph',c)) for c in expected]
    guessed=[graph_value(c.get('graph',c)) for c in predicted]
    if not gold: raise ValueError('No intended family')
    ids={k:{r['id'] for r in gold[0][k]} for k in ('evidence','claims','decisions')}
    if len(ids['evidence'])>12: raise ValueError('Eligibility audit exceeds12 variables')
    if any({r['id'] for r in graph[k]}!=ids[k] for graph in gold+guessed for k in ids):
        return {'status':'registry_mismatch','exact':False,'state_decision_accuracy':0.0}
    states,universe,available,_=_basis(sorted(ids['evidence']))
    def masks(graphs):
        arrays={did:[] for did in sorted(ids['decisions'])}
        for graph in graphs:
            amended=deepcopy(graph)
            for row in amended['evidence']: row['active']=True
            for did,mask in _table(amended,available,universe).items(): arrays[did].append(mask)
        out={}
        for did,values in arrays.items():
            every=universe;any_support=0
            for value in values: every &= value;any_support |= value
            out[did]=(every,universe ^ any_support)
        return out
    total=states*len(ids['decisions'])
    if not guessed:
        return {'status':'no_prediction','exact':False,'states':states,'decision_states':total,'state_decision_accuracy':0.0}
    wanted,actual=masks(gold),masks(guessed)
    failures=sum(((wanted[d][0]^actual[d][0]) | (wanted[d][1]^actual[d][1])).bit_count() for d in wanted)
    return {'status':'evaluated','exact':failures==0,'states':states,'decision_states':total,
            'incorrect_state_decisions':failures,'state_decision_accuracy':1-failures/total if total else None,
            'scope':'Exhaustive hypothetical local-eligibility assignments, not factual source truth or an ordinary withdrawal-only claim.'}
