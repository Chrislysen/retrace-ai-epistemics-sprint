# Other arms, per primary model

Produced by `post_sweep/recompute_sweep.py` from the launch journals and the per-slot grades in `post_sweep/out/sweep_frozen/`. First-attempt view. Counts are slots unless stated.
Each cell: correct of scheduled, then the range under the sensitivity coding.

| Arm | deepseek-v4-flash | gemma-4-31b-it | glm-5.2 | glm-5.3-flash | qwen3.8-27b |
|---|---|---|---|---|---|
| nl_projection/project | 24/30 [80.0%, 100.0%] | 0/30 [0.0%, 3.3%] | 7/30 [23.3%, 76.7%] | 10/30 [33.3%, 96.7%] | 7/30 [23.3%, 90.0%] |
| commitment/hist_init | 11/12 [91.7%, 91.7%] | 10/12 [83.3%, 83.3%] | 2/12 [16.7%, 41.7%] | 10/12 [83.3%, 91.7%] | 4/12 [33.3%, 33.3%] |
| commitment/hist_withdrawn | 11/12 [91.7%, 91.7%] | 8/12 [66.7%, 66.7%] | 1/12 [8.3%, 33.3%] | 10/12 [83.3%, 91.7%] | 3/12 [25.0%, 25.0%] |
| commitment/hist_restored | 11/12 [91.7%, 91.7%] | 8/12 [66.7%, 66.7%] | 1/12 [8.3%, 33.3%] | 9/12 [75.0%, 91.7%] | 3/12 [25.0%, 25.0%] |
| commitment/evt_no_commit | 9/12 [75.0%, 83.3%] | 7/12 [58.3%, 66.7%] | 0/12 [0.0%, 25.0%] | 5/12 [41.7%, 66.7%] | 3/12 [25.0%, 25.0%] |
| commitment/fresh_withdrawn | 6/12 [50.0%, 58.3%] | 7/12 [58.3%, 58.3%] | 2/12 [16.7%, 50.0%] | 4/12 [33.3%, 75.0%] | 1/12 [8.3%, 8.3%] |
| commitment/fresh_restored | 10/12 [83.3%, 91.7%] | 6/12 [50.0%, 50.0%] | 2/12 [16.7%, 25.0%] | 7/12 [58.3%, 100.0%] | 2/12 [16.7%, 16.7%] |
| oracle_ir_consumption/fresh_withdrawn | 9/12 [75.0%, 91.7%] | 4/12 [33.3%, 33.3%] | 1/12 [8.3%, 41.7%] | 6/12 [50.0%, 91.7%] | 7/12 [58.3%, 58.3%] |
| symbolic_assistance/fresh_withdrawn | 10/12 [83.3%, 100.0%] | 11/12 [91.7%, 91.7%] | 8/12 [66.7%, 83.3%] | 6/12 [50.0%, 100.0%] | 11/12 [91.7%, 91.7%] |
| adversarial_refuter/counter_read | 42/60 [70.0%, 93.3%] | 44/60 [73.3%, 73.3%] | 23/60 [38.3%, 88.3%] | 32/60 [53.3%, 96.7%] | 49/60 [81.7%, 95.0%] |

Decision labels right in the commitment, oracle and assisted arms (all scheduled labels):

| Arm | deepseek-v4-flash | gemma-4-31b-it | glm-5.2 | glm-5.3-flash | qwen3.8-27b |
|---|---|---|---|---|---|
| commitment/hist_init | 53/58 | 55/58 | 9/58 | 49/58 | 18/58 |
| commitment/hist_withdrawn | 53/58 | 53/58 | 5/58 | 49/58 | 14/58 |
| commitment/hist_restored | 53/58 | 53/58 | 5/58 | 44/58 | 14/58 |
| commitment/evt_no_commit | 43/58 | 47/58 | 0/58 | 28/58 | 18/58 |
| commitment/fresh_withdrawn | 29/58 | 46/58 | 10/58 | 20/58 | 5/58 |
| commitment/fresh_restored | 48/58 | 45/58 | 10/58 | 34/58 | 9/58 |
| oracle_ir_consumption/fresh_withdrawn | 43/58 | 47/58 | 5/58 | 28/58 | 33/58 |
| symbolic_assistance/fresh_withdrawn | 48/58 | 56/58 | 38/58 | 28/58 | 53/58 |
