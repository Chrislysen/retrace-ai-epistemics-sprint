"""Record the authorized retirement once; never edit an old reservation ledger."""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
audit_path=ROOT/'results/ambiguity-reservation-audit.json'
audit=json.loads(audit_path.read_text(encoding='utf-8'))
assert audit['status']=='passed_conditional_on_retiring_unissued_plan_slots'
for row in audit['runs']:
    for name,wanted in row['evidence_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==wanted,name
for name,wanted in audit['original_budget_evidence_sha256'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==wanted,name
retained=Decimal(audit['all_issued_attempts_retained_credits'])
reserved=Decimal('0.48865280')
total=retained+reserved
assert total<=50
ledger={
    'schema':'retrace.ambiguity-reservation-retirement.v1',
    'created_at':datetime.now(timezone.utc).isoformat(),
    'authorization':'Root explicitly authorized retirement in the user-authorized reconciliation phase; no model calls are performed by this ledger.',
    'audit_sha256':hashlib.sha256(audit_path.read_bytes()).hexdigest(),
    'original_budget_sha256':audit['original_budget_evidence_sha256']['results/budget-audit.json'],
    'historical_booked_plan_credits':audit['original_plan_reserved_credits'],
    'retired_unissued_plan_credits':audit['provably_unissued_plan_allowance_credits'],
    'retained_issued_attempt_credits':str(retained),
    'retained_issued_attempts':audit['journaled_attempts'],
    'retired_slot_count':audit['provably_unissued_slots'],
    'retired_slots':[{'run':row['run'],'run_id':row['run_id'],'model':row['model'],'per_request_nanocredits':row['per_request_nanocredits'],**slot}
                     for row in audit['runs']for slot in row['unissued_slots']],
    'fresh_reservations':[{'reservation_id':'ambiguity-v3-gemma-20-v1','status':'reserved_not_issued','model':'gemma-4-31b-it','request_limit':20,'max_output_tokens':4096,'credits':str(reserved)}],
    'current_conservative_reserved_credits':str(total),
    'approved_cap_credits':'50','available_after_fresh_reservation_credits':str(Decimal(50)-total),
    'rules':['The historical 48.58050288 ledger is retained unchanged and is not the current committed total after retirement.',
             'Every issued attempt, including HTTP errors, incomplete generations, timeouts and repeated requests, retains its entire original bound.',
             'No retired slot may resume. Any continuation or new experiment must obtain a separate fresh reservation.',
             'The fresh reservation permits at most 20 Gemma requests with a 4096-token ceiling after protocol review/freeze. This ledger is not evidence those calls occurred.',
             'Do not overwrite this ledger or rerun the old full-plan audit as the current balance. Any later changes require a new immutable ledger referencing this hash.',
             'Actual account debits are not verified; no provider refund is asserted.']
}
assert len(ledger['retired_slots'])==167
target=ROOT/'results/ambiguity-reservation-retirement.json'
with target.open('x',encoding='utf-8')as f:
    f.write(json.dumps(ledger,indent=2)+'\n')
print(json.dumps({k:ledger[k]for k in ['retired_slot_count','retained_issued_attempts','current_conservative_reserved_credits','available_after_fresh_reservation_credits']},indent=2))
