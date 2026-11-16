# The 21 pre-specified paired comparisons (first attempt)

Produced by `post_sweep/recompute_sweep.py` from the launch journals and the per-slot grades in `post_sweep/out/sweep_frozen/`. First-attempt view. Counts are slots unless stated.
Under the frozen protocol these tests are null because the run was interrupted; the numbers below are the recovery-closure sensitivity declared before the last recovery launch. Exact two-sided McNemar, Holm over 21.

| Contrast (B minus A) | Model | Cases | A correct | B correct | A only | B only | p | Holm p |
|---|---|---|---|---|---|---|---|---|
| nl_projection_minus_strict_ir | deepseek-v4-flash | 30 | 23 | 24 | 1 | 2 | 1.0000 | 1.0000 |
| assisted_minus_oracle | deepseek-v4-flash | 12 | 9 | 10 | 0 | 1 | 1.0000 | 1.0000 |
| no_commit_minus_history_withdrawn | deepseek-v4-flash | 12 | 11 | 9 | 2 | 0 | 0.5000 | 1.0000 |
| fresh_withdrawn_minus_no_commit | deepseek-v4-flash | 12 | 9 | 6 | 3 | 0 | 0.2500 | 1.0000 |
| nl_projection_minus_strict_ir | gemma-4-31b-it | 30 | 0 | 0 | 0 | 0 | 1.0000 | 1.0000 |
| assisted_minus_oracle | gemma-4-31b-it | 12 | 4 | 11 | 0 | 7 | 0.0156 | 0.3125 |
| no_commit_minus_history_withdrawn | gemma-4-31b-it | 12 | 8 | 7 | 2 | 1 | 1.0000 | 1.0000 |
| fresh_withdrawn_minus_no_commit | gemma-4-31b-it | 12 | 7 | 7 | 1 | 1 | 1.0000 | 1.0000 |
| nl_projection_minus_strict_ir | glm-5.2 | 30 | 12 | 7 | 8 | 3 | 0.2266 | 1.0000 |
| assisted_minus_oracle | glm-5.2 | 12 | 1 | 8 | 0 | 7 | 0.0156 | 0.3125 |
| no_commit_minus_history_withdrawn | glm-5.2 | 12 | 1 | 0 | 1 | 0 | 1.0000 | 1.0000 |
| fresh_withdrawn_minus_no_commit | glm-5.2 | 12 | 0 | 2 | 0 | 2 | 0.5000 | 1.0000 |
| nl_projection_minus_strict_ir | glm-5.3-flash | 30 | 14 | 10 | 5 | 1 | 0.2188 | 1.0000 |
| assisted_minus_oracle | glm-5.3-flash | 12 | 6 | 6 | 0 | 0 | 1.0000 | 1.0000 |
| no_commit_minus_history_withdrawn | glm-5.3-flash | 12 | 10 | 5 | 5 | 0 | 0.0625 | 1.0000 |
| fresh_withdrawn_minus_no_commit | glm-5.3-flash | 12 | 5 | 4 | 2 | 1 | 1.0000 | 1.0000 |
| nl_projection_minus_strict_ir | qwen3.8-27b | 30 | 23 | 7 | 16 | 0 | 0.0000 | 0.0006 |
| assisted_minus_oracle | qwen3.8-27b | 12 | 7 | 11 | 0 | 4 | 0.1250 | 1.0000 |
| no_commit_minus_history_withdrawn | qwen3.8-27b | 12 | 3 | 3 | 3 | 3 | 1.0000 | 1.0000 |
| fresh_withdrawn_minus_no_commit | qwen3.8-27b | 12 | 3 | 1 | 3 | 1 | 0.6250 | 1.0000 |
| strict_ir_minus_k10_union | gemma-4-31b-it | 12 | 0 | 0 | 0 | 0 | 1.0000 | 1.0000 |

Tests recomputed here: 21. In the project's primary family: 21. Differences from the project's values: 0.
