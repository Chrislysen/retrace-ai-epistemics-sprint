"""Close the single v4 reservation without refunding any planned attempt."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from summarize_ambiguity_v4 import audit_run, digest, read, require

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / 'results/ambiguity-v4-budget-final.json'
    require(not output.exists(), 'Refusing to overwrite a closed credit ledger')
    responses, integrity = audit_run(ROOT, ROOT / 'data/ambiguity-v4-execution.json', ROOT / 'data/ambiguity-v4-scorer-checkpoint.json')
    old = read(ROOT / 'results/ambiguity-v3-budget-final.json')
    execution = integrity['execution']
    reserve = Decimal(execution['reserved_credits'])
    bound = Decimal(old['current_conservative_reserved_credits']) + reserve
    require(bound == Decimal('40.79280112') < Decimal('50'), 'Wrong cumulative reservation')
    known = Decimal(0)
    unknown = 0
    for response in responses:
        usage = response.get('usage') or {}
        if all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('input_tokens', 'output_tokens')):
            known += (Decimal(usage['input_tokens']) * Decimal('.09') + Decimal(usage['output_tokens']) * Decimal('.34')) / Decimal(1000000)
        else:
            unknown += 1
    ledger = {'schema': 'retrace.ambiguity-v4-budget-closed.v1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'previous_ledger_sha256': digest(ROOT / 'results/ambiguity-v3-budget-final.json'),
              'execution_sha256': integrity['execution_sha256'], 'scorer_checkpoint_sha256': integrity['checkpoint_sha256'],
              'raw_files_sha256': integrity['raw_files_sha256'], 'summary_sha256': digest(ROOT / 'results/ambiguity-v4-summary.json'),
              'reservation_id': execution['reservation_id'], 'run_status': integrity['run_status'],
              'status': 'closed_without_refunds', 'new_planned_requests': 10, 'new_issued_requests': len(responses),
              'new_unissued_requests': 10 - len(responses), 'total_issued_requests': old['total_issued_requests'] + len(responses),
              'historical_issued_bound_credits': old['current_conservative_reserved_credits'],
              'fresh_plan_bound_credits': str(reserve), 'current_conservative_reserved_credits': str(bound),
              'approved_cap_credits': '50', 'remaining_credits': str(Decimal(50) - bound),
              'new_observed_token_cost_credits_uncached': str(known),
              'cumulative_known_usage_estimate_credits': str(Decimal(old['cumulative_known_usage_estimate_credits']) + known),
              'historical_unknown_usage_attempts': old['historical_unknown_usage_attempts'] + unknown,
              'actual_billed_credits': None,
              'note': 'No retry or replacement. Every planned v4 slot remains conservatively reserved; all previous ledgers and raw logs are unchanged.'}
    with output.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(ledger, indent=2) + '\n')
    print(json.dumps({k: ledger[k] for k in ('new_issued_requests', 'total_issued_requests', 'current_conservative_reserved_credits', 'remaining_credits', 'new_observed_token_cost_credits_uncached')}))


if __name__ == '__main__':
    main()
