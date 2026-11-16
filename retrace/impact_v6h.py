"""Exact minimum withdrawal witnessing loss of family unanimity.

Fast ROBDD optimization for known-provenance Tier A, bounded enumeration for
polar/unknown Tier B. No gold or source parser; a proposed reading is never
automatically accepted as true or substituted for the current family.
"""
from itertools import combinations
from .boolean_v6h import BDD
from .tiered_v6h import FALSE, validate, family_supervaluation, require


def _compile(graph, manager, locked):
    _, index, categories, order, unknown = validate(graph)
    require(not unknown and all(r['negative']==FALSE for r in graph['claims']), 'Tier A compilation only')
    roots={}
    for ident in order:
        row=index[ident]; kind=categories[ident]
        if kind=='evidence':
            root=(manager.variable(ident) if ident in manager.order else 1) if row['active'] and ident not in locked else 0
            for parent in row['parents']:root=manager.apply('and',root,roots[parent])
        elif kind=='claims':root=manager.compile(row['positive'],roots)
        else:
            root=1
            for parent in row['requires']:root=manager.apply('and',root,roots[parent])
        roots[ident]=root
    return roots


def _min_withdraw(manager, root, allowed):
    memo={0:None,1:()}
    def visit(ident):
        if ident in memo:return memo[ident]
        level,low,high=manager.nodes[ident]; var=manager.variables[level]
        options=[]; same=visit(high)
        if same is not None:options.append(same)
        if var in allowed:
            changed=visit(low)
            if changed is not None:options.append(tuple(sorted((var,)+changed)))
        memo[ident]=min(options,key=lambda x:(len(x),x)) if options else None
        return memo[ident]
    value=visit(root)
    return list(value) if value is not None else None


def compare_families(current, proposed, *, locked=None, allowed=None, decisions=None):
    require(isinstance(current,list) and isinstance(proposed,list) and 1<=len(current)<=32 and 1<=len(proposed)<=32,'Bounded families')
    prepared=[validate(g) for g in current+proposed]
    typed=[{kind:{r['id'] for r in g[kind]} for kind in ('evidence','claims','decisions')} for g in current+proposed]
    require(all(t==typed[0] for t in typed),'Fixed typed inventory')
    known=typed[0]['evidence']; targets=sorted(typed[0]['decisions'] if decisions is None else decisions)
    require(set(targets)<=typed[0]['decisions'] and len(set(targets))==len(targets),'Known unique targets')
    locked=set() if locked is None else set(locked)
    allowed=known-locked if allowed is None else set(allowed)
    require(locked<=known and allowed<=known and not locked&allowed and len(allowed)<=16,'Withdrawal scope')
    simple=all(not p[-1] and all(r['negative']==FALSE for r in p[0]['claims']) for p in prepared)
    results=[]
    if simple:
        manager=BDD(sorted(allowed)); roots=[_compile(g,manager,locked) for g in current+proposed]
        for target in targets:
            old_all=1;old_any=0;new_all=1;new_any=0
            for i,row in enumerate(roots):
                value=row[target];new_all=manager.apply('and',new_all,value);new_any=manager.apply('or',new_any,value)
                if i<len(current):old_all=manager.apply('and',old_all,value);old_any=manager.apply('or',old_any,value)
            loss=manager.apply('or',manager.apply('monus',old_all,new_all),manager.apply('monus',new_any,old_any))
            withdraw=_min_withdraw(manager,loss,allowed)
            results.append({'decision':target,'minimum_k':len(withdraw) if withdraw is not None else None,'withdraw':withdraw})
        method='ROBDD minimum-weight satisfying assignment; no monotonicity assumption'
    else:
        require(len(allowed)<=10,'Tier B exact withdrawal limit10; explicitly narrow scope')
        require((1<<len(allowed))*sum(1<<len(p[-1]) for p in prepared)<=100000,'Tier B concrete-evaluation bound; explicitly narrow scope')
        remaining=set(targets); found={}
        for size in range(len(allowed)+1):
            for subset in combinations(sorted(allowed),size):
                veto=list(locked|set(subset))
                a=family_supervaluation(current,scenario_withdrawals=veto)['decisions']
                b=family_supervaluation(current+proposed,scenario_withdrawals=veto)['decisions'] if len(current)+len(proposed)<=32 else None
                # Avoid the UI family32 bound when comparing two full32 families.
                if b is None:
                    p=family_supervaluation(proposed,scenario_withdrawals=veto)['decisions']
                    b={d:{'box_supported':a[d]['box_supported'] and p[d]['box_supported'],
                          'diamond_supported':a[d]['diamond_supported'] or p[d]['diamond_supported']} for d in targets}
                for target in sorted(remaining):
                    if (a[target]['box_supported'] and not b[target]['box_supported']) or (not a[target]['diamond_supported'] and b[target]['diamond_supported']):
                        found[target]=list(subset)
                remaining-=set(found)
                if not remaining:break
            if not remaining:break
        results=[{'decision':target,'minimum_k':len(found[target]) if target in found else None,'withdraw':found.get(target)} for target in targets]
        method='Exact bounded Tier B/unknown-gate enumeration; at most10withdrawal IDs'
    for row in results:
        if row['withdraw'] is not None:
            veto=sorted(locked|set(row['withdraw']))
            a=family_supervaluation(current,scenario_withdrawals=veto)['decisions'][row['decision']]
            p=family_supervaluation(proposed,scenario_withdrawals=veto)['decisions'][row['decision']]
            row['current']={k:a[k] for k in ('box_supported','diamond_supported')}
            row['augmented']={'box_supported':a['box_supported'] and p['box_supported'],
                              'diamond_supported':a['diamond_supported'] or p['diamond_supported']}
    return {'method':method,'decisions':results,'locked_vetoes':sorted(locked),'allowed_withdrawals':sorted(allowed),
            'source_entailment_verified':False,'proposal_applied':False}


def withdrawal_robustness(candidates, *, locked=None, allowed=None, decisions=None):
    """Minimum additional withdrawal destroying current unanimous support."""
    require(isinstance(candidates,list) and 1<=len(candidates)<=32,'Bounded family')
    prepared=[validate(g) for g in candidates]
    known={r['id'] for r in candidates[0]['evidence']}
    locked=set() if locked is None else set(locked)
    allowed=known-locked if allowed is None else set(allowed)
    require(locked<=known and allowed<=known and not locked&allowed and len(allowed)<=16,'Withdrawal scope')
    baseline=family_supervaluation(candidates,scenario_withdrawals=sorted(locked))['decisions']
    targets=sorted(baseline if decisions is None else decisions)
    require(set(targets)<=set(baseline),'Unknown target')
    simple=all(not p[-1] and all(r['negative']==FALSE for r in p[0]['claims']) for p in prepared)
    if simple:
        manager=BDD(sorted(allowed));roots=[_compile(g,manager,locked) for g in candidates]
    else:
        require(len(allowed)<=10 and (1<<len(allowed))*sum(1<<len(p[-1]) for p in prepared)<=100000,'Exact Tier B scope bound')
    results=[]
    for target in targets:
        applicable=baseline[target]['box_supported'];withdraw=None
        if applicable and simple:
            root=1
            for row in roots:root=manager.apply('and',root,row[target])
            withdraw=_min_withdraw(manager,manager.apply('monus',1,root),allowed)
        elif applicable:
            for size in range(1,len(allowed)+1):
                for subset in combinations(sorted(allowed),size):
                    if not family_supervaluation(candidates,scenario_withdrawals=sorted(locked|set(subset)))['decisions'][target]['box_supported']:
                        withdraw=list(subset);break
                if withdraw is not None:break
        results.append({'decision':target,'applicable':applicable,'minimum_k':len(withdraw) if withdraw is not None else None,
            'withdraw':withdraw,'survives_all_k1':applicable and (withdraw is None or len(withdraw)>1),
            'survives_all_k2':applicable and (withdraw is None or len(withdraw)>2)})
    return {'decisions':results,'allowed_withdrawals':sorted(allowed),'locked_vetoes':sorted(locked),
            'exact_within_scope':True,'monotonicity_assumed':False}


def enable_withdraw_impact(current, proposed=None, *, locked=None, allowed=None, decisions=None):
    """Exact Hamming2 diagnostic, clearly separated from actual restoration.

With no proposal, expose a dormant prerequisite then a disabling withdrawal.
With a proposal, find a previously silent family discrepancy exposed only after
enabling one originally inactive record and withdrawing one active record.
"""
    families=[current] if proposed is None else [current,proposed]
    require(all(isinstance(f,list) and 1<=len(f)<=32 for f in families),'Bounded families')
    prepared=[validate(g) for family in families for g in family]
    graphs=[g for family in families for g in family]
    typed=[{kind:{r['id'] for r in g[kind]} for kind in ('evidence','claims','decisions')} for g in graphs]
    require(all(t==typed[0] for t in typed),'Fixed typed inventory')
    known=typed[0]['evidence']
    locked=set() if locked is None else set(locked)
    allowed=known-locked if allowed is None else set(allowed)
    require(locked<=known and allowed<=known and not locked&allowed and len(allowed)<=16,'Diagnostic scope')
    flags={ident:[next(r['active'] for r in g['evidence'] if r['id']==ident) for g in graphs] for ident in known}
    enable_ids=sorted(ident for ident in allowed if not any(flags[ident]))
    withdraw_ids=sorted(ident for ident in allowed if any(flags[ident]))
    evaluations=(1+len(enable_ids)*(1+len(withdraw_ids)))*sum(1<<len(p[-1]) for p in prepared)
    require(evaluations<=100000,'Hamming2 concrete-evaluation bound; narrow scope')
    def family_status(family, overrides=None, withdrawal=None):
        return family_supervaluation(family,local_overrides=overrides,scenario_withdrawals=sorted(locked|set(withdrawal or [])))['decisions']
    def signature(row):return row['box_supported'],row['diamond_supported']
    def loses(a,p):
        return (a['box_supported'] and not p['box_supported']) or (not a['diamond_supported'] and p['diamond_supported'])
    initial=family_status(current); initial_p=family_status(proposed) if proposed is not None else None
    targets=sorted(initial if decisions is None else decisions);require(set(targets)<=set(initial),'Unknown target')
    witnesses=[]
    for enable in enable_ids:
        activated=family_status(current,{enable:True}); activated_p=family_status(proposed,{enable:True}) if proposed is not None else None
        for withdraw in withdraw_ids:
            changed=family_status(current,{enable:True},[withdraw]);changed_p=family_status(proposed,{enable:True},[withdraw]) if proposed is not None else None
            for target in targets:
                if proposed is None:
                    hit=(not initial[target]['box_supported'] and activated[target]['box_supported']
                         and signature(changed[target])==signature(initial[target]))
                else:
                    hit=(not loses(initial[target],initial_p[target]) and not loses(activated[target],activated_p[target])
                         and loses(changed[target],changed_p[target]))
                if hit:
                    row={'decision':target,'enable':enable,'withdraw':withdraw,'hamming_distance':2,
                         'hypothetical_activation':True,'baseline':signature(initial[target]),
                         'enabled':signature(activated[target]),'enabled_and_withdrawn':signature(changed[target])}
                    if proposed is not None:
                        row['proposed_enabled_and_withdrawn']=signature(changed_p[target])
                    witnesses.append(row)
    return {'witnesses':witnesses,'scope':'Hypothetical activation of an originally false local flag, then one withdrawal; locked document/passage vetoes remain. Not permission to restore or change the source.',
            'proposal_applied':False,'source_entailment_verified':False}
