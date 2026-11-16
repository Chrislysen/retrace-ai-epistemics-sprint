# Sweep accounting

Produced by `post_sweep/recompute_sweep.py` from the launch journals and the per-slot grades in `post_sweep/out/sweep_frozen/`. First-attempt view. Counts are slots unless stated.

| Model | Scheduled | Completed | Truncated at token cap | Provider or transport failure | Not issued (producer failed) | Interrupted by host | Missing under the sensitivity coding |
|---|---|---|---|---|---|---|---|
| deepseek-v4-flash | 276 | 214 | 10 | 47 | 5 | 0 | 50 |
| gemma-4-31b-it | 612 | 583 | 0 | 19 | 10 | 0 | 29 |
| glm-5.2 | 276 | 118 | 37 | 88 | 31 | 2 | 107 |
| glm-5.3-flash | 276 | 155 | 8 | 96 | 17 | 0 | 111 |
| qwen3.8-27b | 276 | 158 | 44 | 42 | 32 | 0 | 57 |
| qwen3.5-397b | 84 | 79 | 0 | 3 | 2 | 0 | 5 |
| ALL | 1800 | 1307 | 99 | 295 | 97 | 2 | 359 |

Provider and transport failures by recorded error: `http_502` 39; `http_504` 119; `network_or_transport_failure` 1; `post_headers_transport_read_failure` 3; `response_model_mismatch` 1; `timeout` 132.

Slots with more than one attempt: 0. Rows identical to the project's merged table: 1800 of 1800. Merge problems found: 0.
