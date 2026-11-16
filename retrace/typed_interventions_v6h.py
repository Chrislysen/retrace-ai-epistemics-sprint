"""Typed two-operation exposure without rewriting original eligibility.

Restoring one named veto and withdrawing one record are two different actions,
not a Hamming distance in evidence bits. Every other veto remains independent.
"""
from .tiered_v6h import validate,require,family_supervaluation

def restore_then_withdraw_impact(current,proposed=None,*,document_groups,revoked_documents=(),
                                revoked_passages=(),scenario_withdrawals=(),allowed=None,decisions=None):
    families=[current] if proposed is None else [current,proposed]
    require(all(isinstance(f,list) and 1<=len(f)<=32 for f in families),'Bounded families')
    graphs=[g for family in families for g in family];prepared=[validate(g) for g in graphs]
    typed=[{k:{r['id'] for r in g[k]} for k in ('evidence','claims','decisions')} for g in graphs]
    require(all(t==typed[0] for t in typed),'Fixed typed inventory')
    known=typed[0]['evidence'];groups={}
    require(isinstance(document_groups,list),'Document group list')
    for group in document_groups:
        require(isinstance(group,dict) and isinstance(group.get('id'),str) and group['id'] not in groups,'Unique named document groups')
        ids=group.get('evidence_ids');require(isinstance(ids,list) and all(isinstance(i,str) for i in ids) and len(set(ids))==len(ids) and set(ids)<=known,'Known unique document records')
        groups[group['id']]=set(ids)
    def ids(value,vocabulary,label):
        require(isinstance(value,(list,tuple,set)) and all(isinstance(i,str) for i in value),'Explicit '+label+' collection')
        result=set(value);require(len(result)==len(value) and result<=vocabulary,'Known unique '+label);return result
    documents=ids(revoked_documents,set(groups),'document vetoes')
    passages=ids(revoked_passages,known,'passage vetoes')
    scenarios=ids(scenario_withdrawals,known,'scenario vetoes')
    allowed=known-scenarios if allowed is None else ids(allowed,known,'withdrawal records')
    require(not allowed&scenarios and len(allowed)<=16,'Bounded withdrawal scope')
    actions=[('document',d) for d in sorted(documents)]+[('passage',p) for p in sorted(passages)]
    result_base={'exact_within_declared_scope':True,'proposal_applied':False,'state_mutated':False,
        'scope':'Hypothetical release of ONE currently active named document/passage veto, followed by one record withdrawal. All other document, passage and scenario vetoes persist. Two typed actions, not two evidence bits or permission to restore. Pair-local irreducibility does not establish a global minimum across other interventions.',
        'source_entailment_verified':False}
    evaluations=(1+len(actions)+len(allowed)+len(actions)*len(allowed))*sum(1<<len(p[-1]) for p in prepared)
    require(evaluations<=100000,'Typed intervention concrete-evaluation bound')
    targets=sorted(typed[0]['decisions'] if decisions is None else decisions)
    require(len(set(targets))==len(targets) and set(targets)<=typed[0]['decisions'],'Known unique targets')
    if not actions:return {**result_base,'witnesses':[]}
    def status(family,release=None,withdraw=None):
        docs=documents-({release[1]} if release and release[0]=='document' else set())
        ps=passages-({release[1]} if release and release[0]=='passage' else set())
        dv=sorted(set().union(*(groups[d] for d in docs))) if docs else []
        return family_supervaluation(family,document_vetoes=dv,passage_vetoes=sorted(ps),
            scenario_withdrawals=sorted(scenarios|({withdraw} if withdraw else set())))['decisions']
    def sig(row):return row['box_supported'],row['diamond_supported']
    def loss(a,b):return (a['box_supported'] and not b['box_supported']) or (not a['diamond_supported'] and b['diamond_supported'])
    baseline=status(current);pb=status(proposed) if proposed else None
    singles={w:status(current,withdraw=w) for w in allowed}
    psingles={w:status(proposed,withdraw=w) for w in allowed} if proposed else {}
    witnesses=[]
    for action in actions:
        released=status(current,release=action);pr=status(proposed,release=action) if proposed else None
        for withdraw in sorted(allowed):
            joint=status(current,release=action,withdraw=withdraw)
            pj=status(proposed,release=action,withdraw=withdraw) if proposed else None
            for target in targets:
                if proposed:
                    hit=(not loss(baseline[target],pb[target]) and not loss(released[target],pr[target])
                         and not loss(singles[withdraw][target],psingles[withdraw][target]) and loss(joint[target],pj[target]))
                else:
                    hit=(not baseline[target]['box_supported'] and released[target]['box_supported']
                         and sig(singles[withdraw][target])==sig(baseline[target]) and sig(joint[target])==sig(baseline[target]))
                if hit:
                    row={'decision':target,'release':{'kind':action[0],'id':action[1]},'withdraw':withdraw,'typed_action_count':2,
                        'baseline':sig(baseline[target]),'release_only':sig(released[target]),
                        'withdraw_only':sig(singles[withdraw][target]),'joint':sig(joint[target]),
                        'hypothetical':True,'original_local_flags_unchanged':True}
                    if proposed:row['proposed_joint']=sig(pj[target])
                    if proposed:row['proper_subsets_of_this_pair_silent']=True
                    witnesses.append(row)
    return {**result_base,'witnesses':witnesses}
