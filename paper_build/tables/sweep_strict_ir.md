# Strict source-IR arm (60 cases per primary model)

Produced by `post_sweep/recompute_sweep.py` from the launch journals and the per-slot grades in `post_sweep/out/sweep_frozen/`. First-attempt view. Counts are slots unless stated.
Correct = the compiled family equals the authored family, no registry gap, bare JSON. The range treats provider failures and host interruptions as missing and everything else as scored.

| Model | Completed by provider | Admitted by the compiler | Exact family, bare JSON (correct) | Exact family incl. fenced output | Missing | Range if missing slots are unknown |
|---|---|---|---|---|---|---|
| deepseek-v4-flash | 40 of 60 | 40 | 40 of 60 (66.7%) | 40 | 20 | [66.7%, 100.0%] |
| gemma-4-31b-it | 60 of 60 | 34 | 0 of 60 (0.0%) | 34 | 0 | [0.0%, 0.0%] |
| glm-5.2 | 29 of 60 | 28 | 20 of 60 (33.3%) | 28 | 27 | [33.3%, 78.3%] |
| glm-5.3-flash | 35 of 60 | 33 | 33 of 60 (55.0%) | 33 | 25 | [55.0%, 96.7%] |
| qwen3.8-27b | 46 of 60 | 46 | 46 of 60 (76.7%) | 46 | 14 | [76.7%, 100.0%] |
| qwen3.5-397b | 10 of 12 | 10 | 10 of 12 (83.3%) | 10 | 2 | [83.3%, 100.0%] |

Independent regrade of the three IR arms (474 slots): family exactness agrees with the project's grade on 270 of 270 compiled families; final grades differ on 0 slots.
