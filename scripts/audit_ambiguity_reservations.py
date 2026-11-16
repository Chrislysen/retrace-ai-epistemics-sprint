"""Read-only reconciliation of closed plan reservations for a possible new pilot.

Never refunds any journaled attempt and never changes the original budget ledger.
The reconciled allowance is conditional on retiring all listed unissued slots.
"""
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
NANO=1_000_000_000


def no_duplicates(pairs):
    result={}
    for k,v in pairs:
        if k in result:
            raise ValueError(f'Duplicate JSON key {k}')
        result[k]=v
    return result


def read(path):
    return json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=no_duplicates)


def lines(path):
    data=path.read_bytes()
    assert not data or data.endswith(b'\n'),f'Partial journal: {path}'
    return [json.loads(line,object_pairs_hook=no_duplicates)for line in data.decode('utf-8').splitlines()if line.strip()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def credit(n):
    return format(Decimal(n)/Decimal(NANO),'f')


def identity(model,x):
    return model,x['case_id'],x['condition'],x['phase']


def main():
    target=ROOT/'results/ambiguity-reservation-audit.json'
    if '--check-only' in sys.argv:
        prior=read(target)
        for name,wanted in prior['original_budget_evidence_sha256'].items():
            assert digest(ROOT/name)==wanted,name
        for row in prior['runs']:
            for name,wanted in row['evidence_sha256'].items():
                assert digest(ROOT/name)==wanted,name
        arithmetic=prior['arithmetic_nanocredits']
        assert arithmetic['retained_issued']+arithmetic['unissued']==arithmetic['original']
        print('Existing immutable reconciliation evidence and arithmetic verified; no files written.')
        return
    if target.exists():
        raise FileExistsError('Immutable reconciliation already exists; use --check-only to verify its original evidence.')
    old=read(ROOT/'results/budget-audit.json')
    sources={p:digest(ROOT/p)for p in ['results/budget-audit.json','scripts/audit_budget.py','scripts/run_adaption.mjs']}
    rows=[]
    all_issued=defaultdict(list)
    all_unissued=[]
    run_ids=set()
    for path in sorted((ROOT/'results').rglob('run.json')):
        folder=path.parent
        files=[path,folder/'summary.json',folder/'requests.jsonl',folder/'responses.jsonl']
        assert all(f.is_file()for f in files),f'Incomplete run folder: {folder}'
        m,s=map(read,files[:2]);requests,responses=map(lines,files[2:])
        assert m['run_id'] not in run_ids,'Duplicated run ID requires manual reconciliation'
        run_ids.add(m['run_id'])
        assert m['run_id']==s['run_id']
        assert s['status'] in ('completed','halted') and s.get('finished_at')
        planned=[{'case_id':session['case_id'],'condition':session['condition'],'phase':phase}
                 for session in m['sessions']for phase in session['phases']]
        plan_keys=[identity(m['model'],x)for x in planned]
        assert len(plan_keys)==len(set(plan_keys))==m['planned_requests']==s['planned_requests']
        bynumber={q['request_number']:q for q in requests}
        assert len(bynumber)==len(requests)==s['issued_requests']
        assert sorted(bynumber)==list(range(1,len(requests)+1))
        assert len(responses)==s['recorded_responses']==len(requests)
        assert {r['request_number']for r in responses}==set(bynumber)
        assert len({r['request_number']for r in responses})==len(responses)
        per=m['reserve_nanocredits_per_request']
        assert type(per)is int and per>0
        assert Decimal(str(m['max_reserved_credits']))==Decimal(per*m['planned_requests'])/NANO
        issued_keys=[]
        for q in requests:
            assert q['run_id']==m['run_id'] and q['model']==m['model']
            key=identity(m['model'],q);issued_keys.append(key)
            assert key in plan_keys
            assert Decimal(str(q['reserved_credits']))==Decimal(per)/NANO
            encoded=json.dumps(q['request'],ensure_ascii=False,separators=(',',':')).encode('utf-8')
            assert hashlib.sha256(encoded).hexdigest()==q['request_sha256'],f'Request digest {folder}'
            all_issued[key].append({'run':str(folder.relative_to(ROOT)).replace('\\','/'),'request_number':q['request_number'],'reserved_nanocredits':per})
        assert len(issued_keys)==len(set(issued_keys))
        for r in responses:
            q=bynumber[r['request_number']]
            assert r['run_id']==m['run_id'] and r['request_sha256']==q['request_sha256']
            assert r['request']==q['request'] and identity(m['model'],r)==identity(m['model'],q)
        unused=[p for p,key in zip(planned,plan_keys)if key not in set(issued_keys)]
        assert len(unused)==s['unissued_requests']==m['planned_requests']-len(requests)
        rel=str(folder.relative_to(ROOT)).replace('\\','/')
        for x in unused:
            all_unissued.append((rel,identity(m['model'],x)))
        failures=[{'request_number':r['request_number'],'error':r.get('error'),'usage_known':r.get('usage')is not None}
                  for r in responses if r.get('error')]
        rows.append({'run':rel,'run_id':m['run_id'],'model':m['model'],'status':s['status'],'finished_at':s['finished_at'],
                     'planned':len(planned),'journaled_attempts_retained':len(requests),'responses':len(responses),'provably_unissued':len(unused),
                     'per_request_nanocredits':per,'original_plan_reserved_credits':credit(per*len(planned)),
                     'retained_issued_bound_credits':credit(per*len(requests)),'unissued_plan_allowance_credits':credit(per*len(unused)),
                     'issued_failures_retained':failures,'unissued_slots':unused,
                     'evidence_sha256':{str(f.relative_to(ROOT)).replace('\\','/'):digest(f)for f in files}})
    total_plan=sum(int(Decimal(r['original_plan_reserved_credits'])*NANO)for r in rows)
    retained=sum(int(Decimal(r['retained_issued_bound_credits'])*NANO)for r in rows)
    unused=total_plan-retained
    assert sum(r['journaled_attempts_retained']for r in rows)==old['issued_requests']
    assert abs(Decimal(str(old['conservative_reserved_credits']))-Decimal(total_plan)/NANO)<Decimal('0.00000000001')
    overlaps=[{'unissued_plan_run':run,'identity':list(key),'separate_issued_attempts':all_issued[key]}
              for run,key in all_unissued if key in all_issued]
    repeated=[{'identity':list(key),'attempts_retained':values}for key,values in all_issued.items()if len(values)>1]
    gemma_per=25_825_280 # 256000*.09 + 8192*.34, as nanocredits
    assert gemma_per==int(Decimal(256000)*Decimal('.09')*1000+Decimal(8192)*Decimal('.34')*1000)
    report={'schema':'retrace.ambiguity-reservation-reconciliation.v1','created_at':datetime.now(timezone.utc).isoformat(),
        'status':'passed_conditional_on_retiring_unissued_plan_slots','original_budget_evidence_sha256':sources,
        'approved_cap_credits':'50','original_plan_reserved_credits':credit(total_plan),
        'all_issued_attempts_retained_credits':credit(retained),'provably_unissued_plan_allowance_credits':credit(unused),
        'available_without_reconciliation_credits':credit(50*NANO-total_plan),
        'safe_available_if_listed_unissued_slots_retired_credits':credit(50*NANO-retained),
        'arithmetic_nanocredits':{'original':total_plan,'retained_issued':retained,'unissued':unused,'cap':50*NANO},
        'journaled_attempts':sum(r['journaled_attempts_retained']for r in rows),'provably_unissued_slots':sum(r['provably_unissued']for r in rows),
        'runs':rows,'unissued_slots_also_reserved_and_issued_in_another_run':overlaps,
        'repeated_issued_identities_all_retained':repeated,
        'recommended_pilot':{'model':'gemma-4-31b-it','requests':20,'max_output_tokens':4096,'per_request_credits':'0.02443264','reserve_credits':'0.48865280',
           'fits_original_unreconciled_allowance':20*24432640<=50*NANO-total_plan,'cumulative_after_reconciliation_credits':credit(retained+20*24432640),
           'note':'Two separately issued deterministic prompt variants per case; not unbiased stochastic samples. No calls issued by this audit.'},
        'scope':['Every request journal entry is charged the full plan bound even if it failed, timed out or was repeated. No issued-attempt discount uses observed token usage.',
                 'Journal append and sync precede fetch in the inspected runner; closed summaries and complete request/response journals support identifying unissued plan slots.',
                 'Retirement is a new accounting decision, not a refund from Adaption and not a change to old manifests, summaries or the original budget audit.',
                 'The conditional available allowance requires permanently retiring these unissued slots. Any later continuation must receive a fresh reservation; no older worker may resume independently.',
                 'Overlap identities describe repeated plan slots. Separately issued attempts remain separately reserved; issued duplicates are never deduplicated.',
                 'Account debits and provider-side transport are not independently authenticated; this is a conservative local-journal bound. Prices are the preserved official snapshot, not a new price verification.']}
    with target.open('x',encoding='utf-8')as output:
        output.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items()if k not in ['runs','unissued_slots_also_reserved_and_issued_in_another_run','repeated_issued_identities_all_retained','scope']},indent=2))


if __name__=='__main__':
    main()
