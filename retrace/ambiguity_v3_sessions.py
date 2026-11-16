"""Answer-free public projection and two deliberate interpretation prompts."""
import json
import random

CONDITIONS=('earlier_sparse','later_joint')
BASE='''Read the supplied source packet and return one defensible complete support graph in compact notation.
Use exactly the typed IDs in the registry. Do not output labels, commentary, probabilities or alternative graphs.
Evidence originals are usable when locally eligible. A copy additionally requires ALL direct parents usable.
A claim has OR between sufficient routes and AND within a route. Decisions require ALL named claims.
Preserve current local flags; inherited unavailability does not change a copy's own local flag.
Where the source is genuinely underdetermined, select one defensible reading. Never contradict an explicit source statement or invent an observation, route or parent.
Format one record per line:
E ID R 1 -              for an eligible original (0 means locally ineligible)
E ID C 1 PARENT1,PARENT2 for a copy with both direct parents
C ID ITEM1+ITEM2|ITEM3   for two sufficient alternatives
C ID -                 when no support route is admitted
D ID CLAIM1+CLAIM2      for a decision requiring both claims
Use the source IDs rather than these illustrative tokens. All records are mandatory. Finish with END on its own line. Bare ASCII output is preferred.'''
DIRECTIONS={
 'earlier_sparse':'Interpretation direction: if and only if the wording leaves multiple defensible readings, prefer an earlier-mentioned antecedent and avoid adding a joint requirement or inherited dependency that the wording does not require. Explicit dependencies always override this preference.',
 'later_joint':'Interpretation direction: actively consider the alternative defensible reading of unresolved scope, reference or production history. If the wording permits it, prefer a later-mentioned antecedent, joint scope or inherited dependence. Do not add any dependency that contradicts the source or is unsupported by its wording.',
}


def public_projection(packet):
    public=packet['public']
    return {key:public[key]for key in ('id','title','documents','registry')}


def build_sessions(packets,seed=2026111327):
    sessions=[]
    for packet in packets:
        public=public_projection(packet)
        for condition in CONDITIONS:
            sessions.append({'case_id':public['id'],'family':'ambiguity_v3','condition':condition,
                'response_kind':'graph','instructions':BASE+'\n\n'+DIRECTIONS[condition],
                'steps':[{'phase':'final','input':json.dumps(public,ensure_ascii=False,separators=(',',':'))}]})
    random.Random(seed).shuffle(sessions)
    return sessions
