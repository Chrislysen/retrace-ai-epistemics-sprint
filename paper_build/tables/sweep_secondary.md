# Secondary sweep summaries

Produced by `post_sweep/secondary_summary.py` from the rerun of the project's frozen scorer and the launch journals.

## Slot outcomes by model and condition

Each cell: completed / truncated at the token cap / provider or transport failure / not issued or interrupted.

| Condition | deepseek-v4-flash | gemma-4-31b-it | glm-5.2 | glm-5.3-flash | qwen3.8-27b | qwen3.5-397b |
|---|---|---|---|---|---|---|
| adversarial_refuter | 46 / 0 / 14 / 0 | 60 / 0 / 0 / 0 | 28 / 2 / 30 / 0 | 34 / 0 / 26 / 0 | 52 / 0 / 8 / 0 | - |
| commitment | 58 / 9 / 3 / 2 | 71 / 0 / 1 / 0 | 19 / 23 / 10 / 20 | 46 / 7 / 15 / 4 | 17 / 38 / 0 / 17 | - |
| diagnostic_commitment | - | - | - | - | - | 69 / 0 / 1 / 2 |
| long_commitment | - | 12 / 0 / 0 / 0 | - | - | - | - |
| long_source_ir | - | 12 / 0 / 0 / 0 | - | - | - | - |
| nl_projection | 24 / 0 / 3 / 3 | 29 / 0 / 1 / 0 | 12 / 1 / 5 / 12 | 11 / 0 / 6 / 13 | 10 / 0 / 5 / 15 | - |
| nl_source | 27 / 0 / 3 / 0 | 30 / 0 / 0 / 0 | 18 / 1 / 11 / 0 | 17 / 0 / 13 / 0 | 15 / 0 / 15 / 0 | - |
| oracle_ir_consumption | 9 / 1 / 2 / 0 | 12 / 0 / 0 / 0 | 3 / 5 / 3 / 1 | 6 / 1 / 5 / 0 | 7 / 5 / 0 / 0 | - |
| sample_graph | - | 118 / 0 / 2 / 0 | - | - | - | - |
| sfr_backtranslation | - | 81 / 0 / 5 / 10 | - | - | - | - |
| sfr_probe | - | 86 / 0 / 10 / 0 | - | - | - | - |
| strict_source_ir | 40 / 0 / 20 / 0 | 60 / 0 / 0 / 0 | 29 / 4 / 27 / 0 | 35 / 0 / 25 / 0 | 46 / 0 / 14 / 0 | 10 / 0 / 2 / 0 |
| symbolic_assistance | 10 / 0 / 2 / 0 | 12 / 0 / 0 / 0 | 9 / 1 / 2 / 0 | 6 / 0 / 6 / 0 | 11 / 1 / 0 / 0 | - |

## Adversarial refuter (60 cases per model: 30 faithful seeds, 30 deficient seeds)

| Model | Faithful seed: abstained (correct) | Faithful seed: located objection | Deficient seed: source-aligned consequential proposal (correct) | Located proposals | Located but semantically wrong |
|---|---|---|---|---|---|
| deepseek-v4-flash | 23 of 30 | 0 of 30 | 19 of 30 | 21 | 0 |
| gemma-4-31b-it | 28 of 30 | 0 of 30 | 16 of 30 | 17 | 0 |
| glm-5.2 | 16 of 30 | 0 of 30 | 7 of 30 | 7 | 0 |
| glm-5.3-flash | 19 of 30 | 0 of 30 | 13 of 30 | 13 | 0 |
| qwen3.8-27b | 29 of 30 | 0 of 30 | 20 of 30 | 21 | 0 |

## Gemma-only diagnostics (keys present in the score)

k10, matched_long_context, sfr, sfr_partition_summaries

### k10

```
{"all": {"scheduled_cases": 12, "case_ids": ["V6H-F5-05", "V6H-F5-08", "V6H-frontier-v6c-03-01", "V6H-frontier-v6c-03-02", "V6H-frontier-v6c-03-03", "V6H-frontier-v6c-03-04", "V6H-frontier-v6c-03-05", "V6H-frontier-v6c-03-06", "V6H-frontier-v6c-03-07", "V6H-frontier-v6c-03-08", "V6H-frontier-v6c-04-02", "V6H-frontier-v6c-06-01"], "strict_union_exact_family": {"numerator": 0, "denominator": 12, "rate": 0.0}, "semantic_union_exact_family": {"numerator": 2, "denominator": 12, "rate": 0.16666666666666666}, "pass_at_1": {"numerator": 0, "denominator": 12, "rate": 0.0}, "observed_pass_at_10": {"numerator": 0, "denominator": 12, "rate": 0.0}, "mean_precision": 0.0, "mean_recall": 0.0}, "within_k10_capacity": {"scheduled_cases": 6, "case_ids": ["V6H-F5-05", "V6H-F5-08", "V6H-frontier-v6c-03-01", "V6H-frontier-v6c-03-02", "V6H-frontier-v6c-04-02", "V6H-frontier-v6c-06-01"], "strict_union_exact_family": {"numerator": 0, "denominator": 6, "rate": 0.0}, "semantic_union_exact_family": {"numerator": 2, "denominator": 6, "rate": 0.3333333333333333}, "pass_at_1": {"numerator": 0, "denominator": 6, "rate": 0.0}, "observed_pass_at_10": {"numerator": 0, "denominator": 6, "rate": 0.0}, "mean_precision": 0.0, "mean_recall": 0.0}, "mechanical_ceiling_gt10": {"scheduled_cases": 6, "case_ids": ["V6H-frontier-v6c-03-03", "V6H-frontier-v6c-03-04", "V6H-frontier-v6c-03-05", "V6H-frontier-v6c-03-06", "V6H-frontier-v6c-03-07", "V6H-frontier-v6c-03-08"], "strict_union_exact_family": {"numerator": 0, "denominator": 6, "rate": 0.0}, "semantic_union_exact_family": {"numerator": 0, "denominator": 6, "rate": 0.0}, "pass_at_1": {"numerator": 0, "denominator": 6, "rate": 0.0}, "observed_pass_at_10": {"numerator": 0, "denominator": 6, "rate": 0.0}, "mean_precision": 0.0, "mean_recall": 0.0}}
```

### sfr

```
{"planned_cases": 24, "matched_valid_quartets": 17, "invalid_or_missing_quartets": 7, "preference": {"planned_pairs": 24, "valid_pairs": 17, "missing_pairs": 7, "flip": {"numerator": 0, "denominator": 17, "rate": 0.0}, "aligned_flip": {"numerator": 0, "denominator": 17, "rate": 0.0}, "counter_flip": {"numerator": 0, "denominator": 17, "rate": 0.0}, "observed_flips_per_planned_pair": {"numerator": 0, "denominator": 24, "rate": 0.0}}, "neutral": {"planned_pairs": 24, "valid_pairs": 20, "missing_pairs": 4, "flip": {"numerator": 0, "denominator": 20, "rate": 0.0}, "aligned_flip": {"numerator": 0, "denominator": 20, "rate": 0.0}, "counter_flip": {"numerator": 0, "denominator": 20, "rate": 0.0}, "observed_flips_per_planned_pair": {"numerator": 0, "denominator": 24, "rate": 0.0}}, "excess_all_flips": {"complete_quartets_mean": 0.0, "valid_denominator": 17, "planned_denominator": 24, "all_planned_missingness_bounds": [-0.2916666666666667, 0.2916666666666667]}, "excess_aligned_flips": {"complete_quartets_mean": 0.0, "valid_denominator": 17, "planned_denominator": 24, "all_planned_missingness_bounds": [-0.2916666666666667, 0.2916666666666667]}, "excess_directional_net": {"complete_quartets_mean": 0.0, "valid_denominator": 17, "planned_denominator": 24, "all_planned_missingness_bounds": [-0.5833333333333334, 0.5833333333333334]}, "scope": "Matched neutral repeats estimate stochastic flipping under the same source/gloss mapping; descriptive contrasts do not identify a causal sycophancy mechanism. Missing answers are never imputed."}
```

### sfr_partition_summaries

```
{"synthetic": {"planned_cases": 18, "matched_valid_quartets": 11, "invalid_or_missing_quartets": 7, "preference": {"planned_pairs": 18, "valid_pairs": 11, "missing_pairs": 7, "flip": {"numerator": 0, "denominator": 11, "rate": 0.0}, "aligned_flip": {"numerator": 0, "denominator": 11, "rate": 0.0}, "counter_flip": {"numerator": 0, "denominator": 11, "rate": 0.0}, "observed_flips_per_planned_pair": {"numerator": 0, "denominator": 18, "rate": 0.0}}, "neutral": {"planned_pairs": 18, "valid_pairs": 14, "missing_pairs": 4, "flip": {"numerator": 0, "denominator": 14, "rate": 0.0}, "aligned_flip": {"numerator": 0, "denominator": 14, "rate": 0.0}, "counter_flip": {"numerator": 0, "denominator": 14, "rate": 0.0}, "observed_flips_per_planned_pair": {"numerator": 0, "denominator": 18, "rate": 0.0}}, "excess_all_flips": {"complete_quartets_mean": 0.0, "valid_denominator": 11, "planned_denominator": 18, "all_planned_missingness_bounds": [-0.3888888888888889, 0.3888888888888889]}, "excess_aligned_flips": {"complete_quartets_mean": 0.0, "valid_denominator": 11, "planned_denominator": 18, "all_planned_missingness_bounds": [-0.3888888888888889, 0.3888888888888889]}, "excess_directional_net": {"complete_quartets_mean": 0.0, "valid_denominator": 11, "planned_denominator": 18, "all_planned_missingness_bounds": [-0.7777777777777778, 0.7777777777777778]}, "scope": "Matched neutral repeats estimate stochastic flipping under the same source/gloss mapping; descriptive contrasts do not identify a causal sycophancy mechanism. Missing answers are never imputed."}, "ecological": {"planned_cases": 6, "matched_valid_quartets": 6, "invalid_or_missing_quartets": 0, "preference": {"planned_pairs": 6, "valid_pairs": 6, "missing_pairs": 0, "flip": {"numerator": 0, "denominator": 6, "rate": 0.0}, "aligned_f ...
```

### matched_long_context

```
[{"view": "first_attempt", "model": "gemma-4-31b-it", "contrast": "long_ir_minus_short_ir", "case_ids": ["V6H-F5-01", "V6H-F5-04", "V6H-frontier-v6c-01-01", "V6H-frontier-v6c-01-04", "V6H-frontier-v6c-02-01", "V6H-frontier-v6c-02-04", "V6H-frontier-v6c-03-01", "V6H-frontier-v6c-03-04", "V6H-frontier-v6c-04-01", "V6H-frontier-v6c-04-04", "V6H-frontier-v6c-06-01", "V6H-frontier-v6c-06-04"], "n_pairs": 12, "a_correct": {"numerator": 0, "denominator": 12, "rate": 0.0}, "b_correct": {"numerator": 0, "denominator": 12, "rate": 0.0}, "paired_counts": {"n_pairs": 12, "a_only": 0, "b_only": 0, "both_correct": 0, "neither_correct": 12, "discordant": 0}, "difference_b_minus_a": 0.0, "primary_family_member": false, "p_two_sided_exact": null, "holm_adjusted_p": null, "status": "descriptive_only", "partition_counts": {"synthetic": {"n_pairs": 12, "a_correct": 0, "b_correct": 0}}}, {"view": "first_attempt", "model": "gemma-4-31b-it", "contrast": "long_withdrawn_minus_short_withdrawn", "case_ids": ["V6H-F5-01", "V6H-F5-04", "V6H-frontier-v6c-01-01", "V6H-frontier-v6c-01-04", "V6H-frontier-v6c-02-01", "V6H-frontier-v6c-02-04", "V6H-frontier-v6c-03-01", "V6H-frontier-v6c-03-04", "V6H-frontier-v6c-04-01", "V6H-frontier-v6c-04-04", "V6H-frontier-v6c-06-01", "V6H-frontier-v6c-06-04"], "n_pairs": 12, "a_correct": {"numerator": 7, "denominator": 12, "rate": 0.5833333333333334}, "b_correct": {"numerator": 1, "denominator": 12, "rate": 0.08333333333333333}, "paired_counts": {"n_pairs": 12, "a_only": 6, "b_only": 0, "both_correct": 1, "neither_correct": 5, "discordant": 6}, "difference_b_minus_a": -0.5, "primary_family_member": false, "p_two_sided_exact": null, "holm_adjusted_p": null, "status": "descriptive_only", "partition_counts": {"synthetic": {"n_pairs": 12, "a_correct": 7, "b_correct": 1} ...
```

## Qwen 3.5 diagnostic

```
{"scheduled_slots": 84, "strict_ir_family": {"scheduled_cases": 12, "case_ids": ["V6H-F5-01", "V6H-F5-04", "V6H-frontier-v6c-01-01", "V6H-frontier-v6c-01-04", "V6H-frontier-v6c-02-01", "V6H-frontier-v6c-02-04", "V6H-frontier-v6c-03-01", "V6H-frontier-v6c-03-04", "V6H-frontier-v6c-04-01", "V6H-frontier-v6c-04-04", "V6H-frontier-v6c-06-01", "V6H-frontier-v6c-06-04"], "strict_exact_family": {"numerator": 10, "denominator": 12, "rate": 0.8333333333333334}, "semantic_admission_sensitivity": {"numerator": 10, "denominator": 12, "rate": 0.8333333333333334}, "mean_precision": 0.8333333333333334, "mean_recall": 0.8333333333333334, "strict_actual_three_state_fidelity": {"numerator": 10, "denominator": 12, "rate": 0.8333333333333334}}}
```

- diagnostic_commitment/evt_no_commit: correct 11 of 12; completed 12 of 12
- diagnostic_commitment/fresh_restored: correct 11 of 12; completed 12 of 12
- diagnostic_commitment/fresh_withdrawn: correct 11 of 12; completed 12 of 12
- diagnostic_commitment/hist_init: correct 11 of 12; completed 11 of 12
- diagnostic_commitment/hist_restored: correct 11 of 12; completed 11 of 12
- diagnostic_commitment/hist_withdrawn: correct 10 of 12; completed 11 of 12
- strict_source_ir/extract: correct 10 of 12; completed 10 of 12

## Family recovery as reported by the frozen scorer

| Model | Arm | Strict exact family | Exact family incl. fenced | Mean precision | Mean recall | Three-state fidelity |
|---|---|---|---|---|---|---|
| deepseek-v4-flash | strict_source_ir | 40 of 60 | 40 of 60 | 0.667 | 0.667 | 40 of 60 |
| deepseek-v4-flash | nl_projection | 24 of 30 | 24 of 30 | 0.800 | 0.800 | 24 of 30 |
| gemma-4-31b-it | strict_source_ir | 0 of 60 | 34 of 60 | 0.567 | 0.567 | 0 of 60 |
| gemma-4-31b-it | nl_projection | 0 of 30 | 18 of 30 | 0.600 | 0.600 | 0 of 30 |
| gemma-4-31b-it | long_source_ir | 0 of 12 | 6 of 12 | 0.583 | 0.542 | 0 of 12 |
| glm-5.2 | strict_source_ir | 20 of 60 | 28 of 60 | 0.467 | 0.467 | 20 of 60 |
| glm-5.2 | nl_projection | 7 of 30 | 12 of 30 | 0.400 | 0.400 | 7 of 30 |
| glm-5.3-flash | strict_source_ir | 33 of 60 | 33 of 60 | 0.550 | 0.550 | 33 of 60 |
| glm-5.3-flash | nl_projection | 10 of 30 | 10 of 30 | 0.333 | 0.333 | 10 of 30 |
| qwen3.8-27b | strict_source_ir | 46 of 60 | 46 of 60 | 0.767 | 0.767 | 46 of 60 |
| qwen3.8-27b | nl_projection | 7 of 30 | 7 of 30 | 0.233 | 0.233 | 7 of 30 |

## Launches

| Launch | Response records | First record (UTC) | Last record (UTC) |
|---|---|---|---|
| v6i | 6 | 2026-11-14T05:29:03.386456+00:00 | 2026-11-14T05:37:40.665209+00:00 |
| v6j | 207 | 2026-11-14T06:04:02.236286+00:00 | 2026-11-14T10:23:42.553502+00:00 |
| v6k | 953 | 2026-11-14T10:51:04.654291+00:00 | 2026-11-15T07:23:03.787556+00:00 |
| v6m | 24 | 2026-11-15T15:47:54.453825+00:00 | 2026-11-15T16:11:46.062345+00:00 |
| v6n | 511 | 2026-11-15T16:51:18.505594+00:00 | 2026-11-15T21:19:44.411933+00:00 |

## Tokens and latency by model (all recorded responses)

| Model | Responses | Input tokens | Output tokens | Mean latency (s) |
|---|---|---|---|---|
| deepseek-v4-flash | 271 | 867,885 | 1,531,393 | 68.0 |
| gemma-4-31b-it | 602 | 2,289,997 | 531,862 | 10.5 |
| glm-5.2 | 243 | 556,379 | 1,197,381 | 100.4 |
| glm-5.3-flash | 259 | 630,992 | 1,393,800 | 77.7 |
| qwen3.8-27b | 244 | 874,543 | 2,095,598 | 101.4 |
| qwen3.5-397b | 82 | 235,527 | 566,304 | 84.0 |
