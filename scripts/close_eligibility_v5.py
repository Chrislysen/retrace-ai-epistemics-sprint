"""Close the eight-call plan; no historical reservation or journal is rewritten."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from summarize_eligibility_v5 import audit_run
from summarize_ambiguity_v4 import digest, read, require

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / 'results/eligibility-v5-budget-final.json'
    require(not destination.exists(), 'Refusing to overwrite a closed ledger')
    responses, integrity = audit_run(ROOT, ROOT / 'data/eligibility-v5-execution.json', ROOT / 'data/eligibility-v5-freeze.json')
    old = read(ROOT / 'results/ambiguity-v4-budget-final.json')
    extra = Decimal('0.19546112')
    total = Decimal(old['current_conservative_reserved_credits']) + extra
    require(total == Decimal('40.98826224') < 50, 'Cumulative budget mismatch')
    known = Decimal(0)
    missing = 0
    for row in responses:
        usage = row.get('usage') or {}
        if all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('input_tokens', 'output_tokens')):
            known += (Decimal(usage['input_tokens']) * Decimal('.09') + Decimal(usage['output_tokens']) * Decimal('.34')) / 1000000
        else:
            missing += 1
    ledger = {'schema': 'retrace.eligibility-v5-budget-closed.v1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'previous_ledger_sha256': digest(ROOT / 'results/ambiguity-v4-budget-final.json'),
              'execution_sha256': integrity['execution_sha256'], 'freeze_sha256': integrity['freeze_sha256'],
              'raw_files_sha256': integrity['raw_files_sha256'], 'summary_sha256': digest(ROOT / 'results/eligibility-v5-summary.json'),
              'status': 'closed_without_refunds', 'run_status': integrity['run_status'],
              'new_planned_requests': 8, 'new_issued_requests': len(responses), 'new_unissued_requests': 8-len(responses),
              'total_issued_requests': old['total_issued_requests'] + len(responses),
              'fresh_plan_bound_credits': str(extra), 'current_conservative_reserved_credits': str(total),
              'approved_cap_credits': '50', 'remaining_credits': str(Decimal(50)-total),
              'new_observed_token_cost_credits_uncached': str(known),
              'cumulative_known_usage_estimate_credits': str(Decimal(old['cumulative_known_usage_estimate_credits'])+known),
              'historical_unknown_usage_attempts': old['historical_unknown_usage_attempts']+missing,
              'actual_billed_credits': None, 'note': 'All18 calls this cycle completed once. No retries, replacements or issued-attempt refunds.'}
    with destination.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(ledger, indent=2)+'\n')
    print(json.dumps({k:ledger[k] for k in ('total_issued_requests','current_conservative_reserved_credits','remaining_credits','cumulative_known_usage_estimate_credits')}))


if __name__ == '__main__':
    main()
