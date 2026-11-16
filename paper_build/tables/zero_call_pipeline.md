# Pipeline table: strict source-IR output run through the engine at the three case states

Produced by `post_sweep/zero_call_analyses.py`. Post hoc analyses fixed in `prereg/post_sweep_rules.md`; no model call.
A pair is one decision at one state. ASSERT means supported under every reading. Unsafe = the pipeline asserts a decision the authored family does not.

| Model | Slots | Admitted, bare JSON | Admitted, fenced | Rejected | Missing | Admitted and exact | Admitted, not exact | Unsafe pairs | Authored-ASSERT pairs the pipeline asserts [95% interval] |
|---|---|---|---|---|---|---|---|---|---|
| deepseek-v4-flash | 60 | 40 | 0 | 0 | 20 | 40 | 0 | 0 of 324 | 280 of 444 (63.1%) [49.7, 75.6] |
| gemma-4-31b-it | 60 | 0 | 34 | 26 | 0 | 34 | 0 | 0 of 324 | 209 of 444 (47.1%) [35.7, 58.7] |
| glm-5.2 | 60 | 20 | 8 | 5 | 27 | 28 | 0 | 0 of 324 | 191 of 444 (43.0%) [32.1, 54.3] |
| glm-5.3-flash | 60 | 33 | 0 | 2 | 25 | 33 | 0 | 0 of 324 | 209 of 444 (47.1%) [35.4, 59.6] |
| qwen3.8-27b | 60 | 46 | 0 | 0 | 14 | 46 | 0 | 0 of 324 | 330 of 444 (74.3%) [63.0, 85.1] |
| qwen3.5-397b | 12 | 10 | 0 | 0 | 2 | 10 | 0 | 0 of 66 | 90 of 108 (83.3%) [66.4, 100.0] |

Compiled families by arm (all models): long_source_ir: 7 compiled, 6 exact; nl_projection: 72 compiled, 71 exact; strict_source_ir: 191 compiled, 191 exact.
