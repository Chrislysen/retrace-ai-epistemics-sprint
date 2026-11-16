# Amendment 2 to the rules for the scaling run

Written Monday 16 November 2026, about 05:40 CET, by the second AI session (Claude) with AI assistance.

## What happened

At 05:35 the amended runs for qwen3.8-27b and deepseek-v4-flash started side by side. Within a minute the provider
rejected 13 requests (8 for Qwen, 5 for DeepSeek) with HTTP 429, "Inference rate limit reached for this user; retry after
60 seconds", and both runs stopped at their limit of five consecutive errors. A request rejected with HTTP 429 is refused
before any inference: no model saw it and no answer exists. One further DeepSeek request failed with HTTP 504.

What had been looked at when this was written: Gemma's complete scored result (its run finished at 05:34 under the
original rules and is not affected), and status codes, latencies and error messages of the Qwen and DeepSeek requests.
No Qwen or DeepSeek answer from the amended runs had been compared with a reference; two Qwen answers from the first,
stopped run (9 responses) had been scored together with Gemma's.

## Changes, for qwen3.8-27b, deepseek-v4-flash and glm-53-flash

1. One model at a time. Within a model, two requests at a time until the first HTTP 429, then one.
2. A request rejected with HTTP 429 is issued again after at least 65 seconds, at most twice. This is the rule of the
   sweep's own protocol. A slot whose attempts were all rejected with 429 counts as unusable.
3. The 13 slots rejected with 429 at 05:35 count as not issued and are issued under these settings.
4. Unchanged: every other failure (HTTP 5xx, timeout, cut-off, invalid answer) is not retried and counts as unusable;
   slots, prompts, scoring and outcomes are as before. The run stops at 08:30 CET.

## Requests and budget

Issued so far: 139 (4 smoke, 108 Gemma, 21 Qwen, 6 DeepSeek), of which 13 were rejected with 429 at no cost. Still to
issue: 95 Qwen, 107 DeepSeek, 108 GLM. That is 449 requests if no further 429 occurs, against the approved 450; the
author is asked whether requests rejected with 429 may exceed that count. The reservation total stays below the approved
35 credits (about 33.2 with every slot issued).
