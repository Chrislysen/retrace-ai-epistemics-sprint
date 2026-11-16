# Amendment 1 to the rules for the scaling run

Written Monday 16 November 2026, about 05:30 CET, by the second AI session (Claude) with AI assistance, before any answer
of the scaling run was scored.

## What happened

- Gemma's run started at 05:24 under the rules as written and is not affected by this amendment.
- Qwen's first two requests were extractions. One, for a 40-record case, was cut off at 8,192 output tokens after 56 s
  (status "incomplete"); the other, for a 20-record case, used 6,924 output tokens. The first-day runner counts a cut-off
  answer as an error and stops the segment, and it does not accept an output limit above 8,192.
- Qwen, DeepSeek and GLM spend output tokens on reasoning before they answer (about 1,000 to 1,250 for a first-day case
  in the smoke requests). Under the rules as written most of their large extractions would be cut off, and each cut-off
  would use up one of the six segments, so their schedules could not finish.

What had been looked at when this was written: status, latency and token counts of the first 14 Gemma and 5 Qwen responses.
No answer had been parsed or compared with a reference.

## Changes, for qwen3.8-27b, deepseek-v4-flash and glm-53-flash only

1. Runner: `post_sweep/run_scale_v2.mjs`, which sends the same request body as the first-day runner (same instructions,
   input, temperature 0, no tools) and writes journals in the same format, but does not stop at a failed request.
2. Maximum output: 32,768 tokens, the sweep's limit for declarations, instead of 8,192. Timeout 300 s instead of 180 s.
3. No segment limit. The run stops early only after five consecutive provider or network errors, or at 08:30 CET.
4. Unchanged: nothing is retried; a cut-off, failed or invalid answer counts as unusable; slots, prompts, order, scoring
   and outcomes are as in `prereg/scale_rules.md`.

The old Qwen run was stopped at 05:27 after 11 requests in three segments. Those requests are kept as they are and are not
issued again; answers that were cut off count as unusable, and so do the two requests that were in flight at the stop.

## Budget under the amendment

Reservation per request at the new limit: qwen 0.0512, deepseek 0.0510, glm-53-flash 0.1737 credits; gemma 0.0258 at the
old limit. With every slot issued once the total is about 32.4 credits, below the approved ceiling of 35. Requests: at most
432 plus 4 smoke requests, below the approved 450.

## Reporting

Gemma's numbers are under the original settings; the other three models' under the amended ones. The paper states this.
