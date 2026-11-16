# Direct answers against the pipeline on the 12 commitment cases

Produced by `post_sweep/zero_call_analyses.py`. Post hoc analyses fixed in `prereg/post_sweep_rules.md`; no model call.
Direct = the model's own verdict in that arm, classed from its box and diamond fields. Pipeline = the same model's strict-IR output run through the engine at the same state. Pairs are decisions (58 per phase). Intervals resample cases.

| Model | Arm and phase | Cases answered | Direct: unsafe of authored not-ASSERT | Direct: over-cautious of authored ASSERT | Direct: no answer (pairs) | Pipeline: unsafe | Pipeline: no verdict (pairs) |
|---|---|---|---|---|---|---|---|
| deepseek-v4-flash | commitment/hist_init | 11 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 0 of 41 (0.0%) [0.0, 0.0] | 5 | 0 | 15 |
| deepseek-v4-flash | commitment/hist_withdrawn | 11 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 5 | 0 | 15 |
| deepseek-v4-flash | commitment/hist_restored | 11 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 0 of 41 (0.0%) [0.0, 0.0] | 5 | 0 | 15 |
| deepseek-v4-flash | commitment/evt_no_commit | 9 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 15 | 0 | 15 |
| deepseek-v4-flash | commitment/fresh_withdrawn | 6 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 29 | 0 | 15 |
| deepseek-v4-flash | commitment/fresh_restored | 10 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 0 of 41 (0.0%) [0.0, 0.0] | 10 | 0 | 15 |
| deepseek-v4-flash | oracle_ir_consumption/fresh_withdrawn | 9 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 15 | 0 | 15 |
| deepseek-v4-flash | symbolic_assistance/fresh_withdrawn | 10 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 10 | 0 | 15 |
| gemma-4-31b-it | commitment/hist_init | 12 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 3 of 41 (7.3%) [4.8, 10.0] | 0 | 0 | 25 |
| gemma-4-31b-it | commitment/hist_withdrawn | 12 of 12 | 1 of 32 (3.1%) [0.0, 6.2] | 2 of 26 (7.7%) [0.0, 15.4] | 0 | 0 | 25 |
| gemma-4-31b-it | commitment/hist_restored | 12 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 4 of 41 (9.8%) [2.4, 17.5] | 0 | 0 | 25 |
| gemma-4-31b-it | commitment/evt_no_commit | 11 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 4 of 26 (15.4%) [7.7, 23.1] | 4 | 0 | 25 |
| gemma-4-31b-it | commitment/fresh_withdrawn | 11 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 6 of 26 (23.1%) [15.4, 30.8] | 5 | 0 | 25 |
| gemma-4-31b-it | commitment/fresh_restored | 11 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 7 of 41 (17.1%) [7.5, 26.2] | 5 | 0 | 25 |
| gemma-4-31b-it | oracle_ir_consumption/fresh_withdrawn | 12 of 12 | 4 of 32 (12.5%) [6.2, 18.8] | 7 of 26 (26.9%) [15.4, 38.5] | 0 | 0 | 25 |
| gemma-4-31b-it | symbolic_assistance/fresh_withdrawn | 12 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 2 of 26 (7.7%) [0.0, 15.4] | 0 | 0 | 25 |
| glm-5.2 | commitment/hist_init | 2 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 0 of 41 (0.0%) [0.0, 0.0] | 49 | 0 | 30 |
| glm-5.2 | commitment/hist_withdrawn | 1 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 53 | 0 | 30 |
| glm-5.2 | commitment/hist_restored | 1 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 0 of 41 (0.0%) [0.0, 0.0] | 53 | 0 | 30 |
| glm-5.2 | commitment/evt_no_commit | 0 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 58 | 0 | 30 |
| glm-5.2 | commitment/fresh_withdrawn | 2 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 48 | 0 | 30 |
| glm-5.2 | commitment/fresh_restored | 2 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 0 of 41 (0.0%) [0.0, 0.0] | 48 | 0 | 30 |
| glm-5.2 | oracle_ir_consumption/fresh_withdrawn | 1 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 53 | 0 | 30 |
| glm-5.2 | symbolic_assistance/fresh_withdrawn | 8 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 20 | 0 | 30 |
| glm-5.3-flash | commitment/hist_init | 10 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 0 of 41 (0.0%) [0.0, 0.0] | 9 | 0 | 39 |
| glm-5.3-flash | commitment/hist_withdrawn | 10 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 9 | 0 | 39 |
| glm-5.3-flash | commitment/hist_restored | 9 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 0 of 41 (0.0%) [0.0, 0.0] | 14 | 0 | 39 |
| glm-5.3-flash | commitment/evt_no_commit | 6 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 29 | 0 | 39 |
| glm-5.3-flash | commitment/fresh_withdrawn | 4 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 38 | 0 | 39 |
| glm-5.3-flash | commitment/fresh_restored | 7 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 0 of 41 (0.0%) [0.0, 0.0] | 24 | 0 | 39 |
| glm-5.3-flash | oracle_ir_consumption/fresh_withdrawn | 6 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 30 | 0 | 39 |
| glm-5.3-flash | symbolic_assistance/fresh_withdrawn | 6 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 30 | 0 | 39 |
| qwen3.8-27b | commitment/hist_init | 4 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 0 of 41 (0.0%) [0.0, 0.0] | 40 | 0 | 19 |
| qwen3.8-27b | commitment/hist_withdrawn | 3 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 44 | 0 | 19 |
| qwen3.8-27b | commitment/hist_restored | 3 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 0 of 41 (0.0%) [0.0, 0.0] | 44 | 0 | 19 |
| qwen3.8-27b | commitment/evt_no_commit | 4 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 39 | 0 | 19 |
| qwen3.8-27b | commitment/fresh_withdrawn | 1 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 53 | 0 | 19 |
| qwen3.8-27b | commitment/fresh_restored | 2 of 12 | 0 of 17 (0.0%) [0.0, 0.0] | 0 of 41 (0.0%) [0.0, 0.0] | 49 | 0 | 19 |
| qwen3.8-27b | oracle_ir_consumption/fresh_withdrawn | 7 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 25 | 0 | 19 |
| qwen3.8-27b | symbolic_assistance/fresh_withdrawn | 11 of 12 | 0 of 32 (0.0%) [0.0, 0.0] | 0 of 26 (0.0%) [0.0, 0.0] | 5 | 0 | 19 |
