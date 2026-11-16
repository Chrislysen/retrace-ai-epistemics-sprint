"""Independent eligibility-v5 raw audit; no production graph modules imported.

This supplemental audit preserves all frozen files and writes its report once.
Its parser intentionally covers the syntax observed in these eight raw outputs.
The manual source rules below are a second implementation, not a blind review.
"""

import copy, hashlib, itertools, json, re, sys
from collections import Counter
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
root=Path(__file__).resolve().parents[1]
checks=0
def check(value,label):
 global checks
 checks+=1
 if not value:raise AssertionError(label)
def unique(items):
 d={}
 for k,v in items:
  if k in d:raise ValueError('Duplicate JSON key '+k)
  d[k]=v
 return d
def load(path):return json.loads((root/path).read_text(encoding='utf-8'),object_pairs_hook=unique)
def digest(path):return hashlib.sha256((root/path).read_bytes()).hexdigest()
def journal(path):return [json.loads(x,object_pairs_hook=unique) for x in (root/path).read_text(encoding='utf-8').splitlines() if x.strip()]
def canonical(g,changed=None):
 return (
  tuple(sorted((r['id'],r['kind'],True if r['id']==changed else r['active'],tuple(sorted(r['parents']))) for r in g['evidence'])),
  tuple(sorted((r['id'],tuple(sorted(tuple(sorted(v)) for v in r['supports']))) for r in g['claims'])),
  tuple(sorted((r['id'],tuple(sorted(r['requires']))) for r in g['decisions'])))
def evaluate(g,withdraw=()):
 old={r['id']:False for cat in ('evidence','claims','decisions') for r in g[cat]}
 for _ in range(len(old)+2):
  new={}
  for r in g['evidence']:new[r['id']]=r['active'] and r['id'] not in withdraw and (r['kind']=='root' or all(old[x] for x in r['parents']))
  for r in g['claims']:new[r['id']]=any(all(old[x] for x in route) for route in r['supports'])
  for r in g['decisions']:new[r['id']]=all(old[x] for x in r['requires'])
  if new==old:return {r['id']:new[r['id']] for r in g['decisions']}
  old=new
 raise AssertionError('Nonconvergence')
def independent_parse(text,registry):
 lines=text.splitlines()
 check(lines[-1]=='END' and lines.count('END')==1,'END')
 base={'evidence':[],'claims':[],'decisions':[]};ops=[]
 for line in lines[:-1]:
  typ,ident,body=line.split(' ',2)
  if typ=='E':
   m=re.fullmatch(r'(R|C) ([01]) (-|[A-Za-z0-9]+(?:,[A-Za-z0-9]+)*)',body);check(m is not None,'evidence grammar')
   kind,flag,parents=m.groups();base['evidence'].append({'id':ident,'kind':'root' if kind=='R' else 'copy','active':flag=='1','parents':[] if parents=='-' else parents.split(',')})
  elif typ=='C':
   m=re.fullmatch(r'(UNSPECIFIED_CHOICE|AMBIGUOUS_QUALIFIER)\(([A-Za-z0-9, ]+)\)',body)
   if m:
    kind=m[1];a=[v.strip() for v in m[2].split(',')]
    if kind=='UNSPECIFIED_CHOICE':
     check(len(a)==2 and len(set(a))==2,'choice args');opts=[[[a[0]]],[[a[1]]]]
    else:
     check(len(a)==3 and len(set(a))==3,'qualifier args');x,y,z=a;opts=[[[x],[y,z]],[[x,z],[y,z]]]
    ops.append((ident,kind,opts));base['claims'].append({'id':ident,'supports':None})
   else:
    check(re.fullmatch(r'-|[A-Za-z0-9]+(?:[+|][A-Za-z0-9]+)*',body) is not None,'claim grammar')
    base['claims'].append({'id':ident,'supports':[] if body=='-' else [x.split('+') for x in body.split('|')]})
  else:
   check(typ=='D' and re.fullmatch(r'[A-Za-z0-9]+(?:\+[A-Za-z0-9]+)*',body) is not None,'decision grammar')
   base['decisions'].append({'id':ident,'requires':body.split('+')})
 for cat in registry:check(sorted(r['id'] for r in base[cat])==sorted(registry[cat]),'typed registry')
 ops.sort()
 result={}
 for bits in itertools.product([False,True],repeat=len(ops)):
  g=copy.deepcopy(base);byid={r['id']:r for r in g['claims']}
  for bit,(ident,_,options) in zip(bits,ops):byid[ident]['supports']=copy.deepcopy(options[int(bit)])
  cid='branch-'+''.join('1' if x else '0' for x in bits) if ops else 'branch-fixed'
  result[cid]={'graph':g,'assignment':{'resolve_'+op[0]:bit for op,bit in zip(ops,bits)}}
 return result,ops
def manual_family(p):
 e,c,d=[p['public']['registry'][k] for k in ('evidence','claims','decisions')];on=re.search(r'Evidence [A-Za-z0-9]+ is currently locally (ineligible|eligible)\.', p['public']['documents'][0]['text'])[1]=='eligible'
 base={'evidence':[{'id':x,'kind':'root','active':True,'parents':[]} for x in e],'claims':[],'decisions':[]}
 def claim(cid,s):base['claims'].append({'id':cid,'supports':s})
 def decision(did,cid):base['decisions'].append({'id':did,'requires':[cid]})
 typ=p['pair_id'][-1]
 if typ=='a':
  base['evidence'][0]['active']=on
  for i,parent in ((3,1),(4,2)):base['evidence'][i].update(kind='copy',parents=[e[0],e[parent]])
  claim(c[0],[[e[3]],[e[4]]]);decision(d[0],c[0]);return [base]
 if typ=='b':
  base['evidence'][0]['active']=on
  for i in (1,2):base['evidence'][i].update(kind='copy',parents=[e[0]])
  claim(c[0],[[e[1]],[e[2]]]);claim(c[1],[[e[1]],[e[2]],[e[3]]])
  for di,ci in zip(d,c):decision(di,ci)
  return [base]
 if typ=='c':
  base['evidence'][0]['active']=on;claim(c[0],[[e[0],e[2]]]);claim(c[1],[[e[1]]]);claim(c[2],[]);decision(d[0],c[2])
  result=[]
  for selected in c[:2]:
   g=copy.deepcopy(base);g['claims'][2]['supports']=[[selected]];result.append(g)
  return result
 base['evidence'][2]['active']=on;base['evidence'][3]['active']=False
 claim(c[0],[]);claim(c[1],[])
 for di,ci in zip(d,c):decision(di,ci)
 result=[]
 for global_scope in (False,True):
  for selected in e[3:]:
   g=copy.deepcopy(base);g['claims'][0]['supports']=[[e[0],e[2]],[e[1],e[2]]] if global_scope else [[e[0]],[e[1],e[2]]]
   g['claims'][1]['supports']=[[selected]];result.append(g)
 return result
packets=load('data/eligibility-v5-paired-staged.json');sessions=load('data/eligibility-v5-paired-sessions.json')
summary=load('results/eligibility-v5-summary.json');scored={r['case_id']:r for r in summary['outcomes']}
folder='results/eligibility-v5/gemma-4-31b-it/'
responses=journal(folder+'responses.jsonl');requests=journal(folder+'requests.jsonl')
bycase={r['case_id']:r for r in responses}
parsed={};casefacts=[];answered=wrong=disputedcases=branches=questioncases=questionsasked=0
for p in packets:
 cid=p['id'];r=bycase[cid];out=scored[cid];candidates,ops=independent_parse(r['output_text'],p['public']['registry']);parsed[cid]=candidates
 refs=manual_family(p);gold=p['hidden']['allowed_interpretations']
 check([canonical(g) for g in refs]==[canonical(g) for g in gold],cid+' manual family vs author')
 check({canonical(v['graph']) for v in candidates.values()}=={canonical(g) for g in refs},cid+' raw exactfamily')
 primary={v['id']:v for v in out['compilation']['candidates']}
 check(set(primary)==set(candidates),cid+' candidate IDs')
 for bid,v in candidates.items():check(canonical(v['graph'])==canonical(primary[bid]['graph']) and v['assignment']==primary[bid]['assignment'],cid+' exact compiled graph')
 actual=refs[p['hidden']['author_actual_interpretation_index']]
 actualstates=evaluate(actual);vectors={bid:evaluate(v['graph']) for bid,v in candidates.items()}
 cur=out['evaluation']['current']
 check(vectors==cur['candidate_decision_vectors'],cid+' independent current decisions')
 check(actualstates==cur['reference_labels_scoring_only'],cid+' actual decisions')
 disputed=[did for did in actualstates if len({v[did] for v in vectors.values()})>1]
 unanimous={did:next(iter(vectors.values()))[did] for did in actualstates if did not in disputed}
 w=sum(v!=actualstates[d] for d,v in unanimous.items());answered+=len(unanimous);wrong+=w;disputedcases+=bool(disputed);branches+=len(candidates)
 check(len(disputed)==cur['agreement']['disputed'] and w==cur['agreement']['unanimous_wrong'],cid+' agreement')
 variable=sorted(p['public']['registry']['evidence'])
 for did in actualstates:
  witness=None
  for k in range(len(variable)+1):
   for withdraw in itertools.combinations(variable,k):
    vals={bid:evaluate(v['graph'],withdraw)[did] for bid,v in candidates.items()}
    if len(set(vals.values()))>1:witness=(list(withdraw),vals);break
   if witness is not None:break
  got=cur['minimum_distinguishing'][did]
  check((got is None)==(witness is None),cid+' witness exists')
  if witness is not None:check(got['withdraw']==witness[0] and got['outcomes']==witness[1],cid+' minimum lex witness')
 grounds={}
 for target,kind,options in ops:
  body=next(row['supports'] for row in actual['claims'] if row['id']==target)
  norm=lambda x:sorted(sorted(y) for y in x)
  matches=[norm(opt)==norm(body) for opt in options];check(sum(matches)==1,cid+' unique sourcefact')
  grounds['resolve_'+target]=matches[1]
 check(grounds=={q['id']:q['grounded_answer'] for q in out['evaluation']['question_grounding']},cid+' sourcefacts')
 bids=tuple(sorted(candidates));qids=tuple(sorted(grounds))
 def vector(bid):return tuple(vectors[bid][did] for did in sorted(actualstates))
 @lru_cache(None)
 def best(pool):
  if len({vector(bid) for bid in pool})==1:return (0,None)
  opts=[]
  for q in qids:
   no=tuple(b for b in pool if not candidates[b]['assignment'][q]);yes=tuple(b for b in pool if candidates[b]['assignment'][q])
   if no and yes:opts.append((1+max(best(no)[0],best(yes)[0]),q))
  return min(opts) if opts else (float('inf'),None)
 check(best(bids)[0]==cur['planner_initial_worst_case_cost'],cid+' minimax cost')
 pool=bids;steps=[]
 while best(pool)[0]:
  q=best(pool)[1];pool=tuple(b for b in pool if candidates[b]['assignment'][q]==grounds[q]);steps.append(q)
 gotsteps=cur['clarification']['steps']
 check(steps==[x['question_id'] for x in gotsteps],cid+' requested-only questions')
 check(list(pool)==cur['clarification']['retained_candidate_ids'],cid+' retained candidates')
 check(all(vector(b)==tuple(actualstates[d] for d in sorted(actualstates)) for b in pool),cid+' resolution correct')
 questionsasked+=len(steps);questioncases+=bool(steps)
 casefacts.append({'case_id':cid,'request_number':r['request_number'],'branches':len(candidates),'vectors':vectors,'disputed':disputed,'questions_requested':len(steps),'retained_after_oracle':list(pool)})
pairs=[]
for letter in 'abcd':
 members=[p for p in packets if p['pair_id'].endswith(letter)];a,b=members
 check(a['hidden']['changed_local_active'] is False and b['hidden']['changed_local_active'] is True,'pair ordering')
 pa=copy.deepcopy(a['public']);pb=copy.deepcopy(b['public'])
 pa['documents'][0]['text']=pa['documents'][0]['text'].replace(a['hidden']['eligibility_sentence'],b['hidden']['eligibility_sentence'])
 check(pa==pb,'exact one eligibility sentence public difference')
 changed=a['hidden']['changed_evidence_id']
 check({canonical(v['graph'],changed) for v in parsed[a['id']].values()}=={canonical(v['graph'],changed) for v in parsed[b['id']].values()},'primary specification invariance')
 pairs.append(a['pair_id'])
agg=summary['aggregates']
for k,v in {'admitted':8,'exact_family_recovery_cases':8,'actual_graph_covered_cases':8,'assignment_branches':branches,'cases_with_current_disagreement':disputedcases,'planner_requested_case_count':questioncases,'correct_resolution_after_requested_case_count':questioncases,'specification_invariant_pairs':len(pairs)}.items():check(agg[k]==v,'aggregate '+k)
check(agg['selective']=={'scheduled_decisions':12,'answered_decisions':answered,'wrong_answered_decisions':wrong,'coverage':answered/12,'risk':wrong/answered},'selective aggregate')
freeze=load('data/eligibility-v5-freeze.json');pres=load('data/eligibility-v5-preservation.json');execution=load('data/eligibility-v5-execution.json');run=load(folder+'run.json');rs=load(folder+'summary.json')
for f in freeze['files']:check(digest(f['path'])==f['sha256'],'frozen '+f['path'])
for path,h in {**pres['protected'],**pres['all_prior_results']}.items():check(digest(path)==h,'preserved '+path)
check(datetime.fromisoformat(run['started_at'].replace('Z','+00:00'))>datetime.fromisoformat(freeze['created_at'])>datetime.fromisoformat(execution['created_at']),'prospective chronology')
check(len(requests)==len(responses)==len(sessions)==8,'eight once')
check(pres['previous_request_count']==495 and sum(len([x for x in p.read_bytes().splitlines() if x.strip()]) for p in (root/'results').rglob('requests.jsonl'))==503,'global accounting')
providerids=[];times=[];token_in=token_out=0
for i,(req,resp,session) in enumerate(zip(requests,responses,sessions),1):
 check(req['request_number']==resp['request_number']==i and req['session_index']==resp['session_index']==i-1,'ordinal/session order')
 check(req['case_id']==resp['case_id']==session['case_id'],'case order')
 check(req['run_id']==resp['run_id']==run['run_id'],'run nonce')
 body={'model':'gemma-4-31b-it','instructions':session['instructions'],'input':[{'role':'user','content':session['steps'][0]['input']}],'max_output_tokens':4096,'temperature':0,'store':False,'agentic_memory':False,'tools':[],'tool_choice':'none'}
 check(req['request']==resp['request']==body,'exact frozen provider payload')
 check(hashlib.sha256(json.dumps(body,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()==req['request_sha256']==resp['request_sha256'],'request digest')
 packet=next(p for p in packets if p['id']==req['case_id'])
 check(json.loads(body['input'][0]['content'])==packet['public'],'public only payload')
 raw=json.loads(resp['raw_response'],object_pairs_hook=unique)
 text=''.join(part['text'] for output in raw['output'] for part in output.get('content',[]) if part.get('type')=='output_text')
 check(text==resp['output_text'],'raw original text')
 check(raw['status']==resp['response_status']=='completed' and resp['http_status']==200 and resp['error'] is None and not resp['raw_response_redacted'],'completed intact')
 check(raw.get('previous_response_id') is None and raw['model']=='gemma-4-31b-it','fresh model response')
 providerids.append(raw['id']);times.append(datetime.fromisoformat(req['started_at'].replace('Z','+00:00')))
 token_in+=resp['usage']['input_tokens'];token_out+=resp['usage']['output_tokens']
check(len(set(providerids))==8,'unique provider response IDs')
intervals=[(b-a).total_seconds() for a,b in zip(times,times[1:])]
check(min(intervals)>=3.1,'global pacing')
cost=Decimal(token_in)*Decimal('.09')/1000000+Decimal(token_out)*Decimal('.34')/1000000
check(cost==Decimal(str(rs['observed_token_cost_credits_uncached'])),'uncached token estimate')
reserve=Decimal(24432640)*8/1000000000
check(reserve==Decimal(execution['reserved_credits'])==Decimal('.19546112'),'reservation math')
check(Decimal(execution['prior_conservative_credits'])+reserve==Decimal(execution['cumulative_conservative_credits'])==Decimal('40.98826224'),'cumulative math')
output={'checks_passed':checks,'frozen_files':len(freeze['files']),'preserved_files':len({**pres['protected'],**pres['all_prior_results']}),'run_id':run['run_id'],'freeze_time':freeze['created_at'],'start':run['started_at'],'finish':rs['finished_at'],'request_count':8,'global_requests':503,'min_dispatch_interval_seconds':min(intervals),'input_tokens':token_in,'output_tokens':token_out,'uncached_token_estimate_credits':str(cost),'reserved_credits':str(reserve),'cumulative_reservation_credits':execution['cumulative_conservative_credits'],'summary_sha256':digest('results/eligibility-v5-summary.json'),'freeze_sha256':digest('data/eligibility-v5-freeze.json'),'raw_response_sha256':digest(folder+'responses.jsonl'),'casefacts':casefacts,'summary':{'admitted':8,'exact_families':8,'invariant_pairs':4,'branches':branches,'cases_with_disagreement':disputedcases,'requested_question_cases':questioncases,'requested_questions_total':questionsasked,'answered_decisions':answered,'wrong_answered_decisions':wrong}}
output['scope'] = [
 'Computationally independent: no production compiler, scorer, core, stress, or test-helper imports.',
 'The same agent authored the corpus and primary scorer; this is not a blind independent reviewer.',
 'Four targeted authored structures paired under one eligibility change; not eight independent natural samples.',
 'Three cases resolved after four requested authored-oracle answers; no human answer observations.',
 'Token cost is an uncached estimate; conservative reservations are retained and billing is unverified.'
]
destination=root/'results/eligibility-v5-independent-audit.json'
with destination.open('x',encoding='utf-8') as handle:
 handle.write(json.dumps(output,indent=2)+'\n')
print(json.dumps({'output':str(destination),'sha256':digest(destination),'checks_passed':checks,'summary':output['summary']},indent=2))

