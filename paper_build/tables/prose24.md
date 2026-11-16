# The 24-case prose experiment, recomputed from raw records

Produced by `post_sweep/recompute_prose24.py`. Inputs: `data/prose-holdout.json`, `results/prose-heldout/*/responses.jsonl`, `results/prose-continuation/gemma-4-31b-it/responses.jsonl`. Numbers are from the independent computation; the frozen scorer's are in `post_sweep/out/prose24_recompute.json`.

## Fully correct cases out of 24

| Condition | gemma-4-31b-it | glm-53-flash |
|---|---|---|
| Formal graph, final state | 21 | 24 |
| Prose, final state | 12 | 24 |
| Prose history, initial answer | 22 | 24 |
| Prose history, after withdrawal | 12 | 24 |
| Prose event, no prior answer | 10 | 24 |
| Extraction + recomputation | 22 | 20 |

## Decision labels wrong, out of all scheduled labels (an unusable answer counts every label wrong)

| Condition | gemma-4-31b-it | glm-53-flash |
|---|---|---|
| Formal graph, final state | 3 of 144 | 0 of 144 |
| Prose, final state | 18 of 144 | 0 of 144 |
| Prose history, initial answer | 3 of 144 | 0 of 144 |
| Prose history, after withdrawal | 19 of 144 | 0 of 144 |
| Prose event, no prior answer | 21 of 144 | 0 of 144 |
| Extraction + recomputation | 12 of 144 | 24 of 144 |

## Error classes among usable answers

| Condition | Model | Usable answers | Required withdrawals missed | Protected alternatives dropped | Unaffected dropped | Never-supported accepted |
|---|---|---|---|---|---|---|
| Formal graph, final state | gemma-4-31b-it | 24 of 24 | 2 of 48 | 1 of 42 | 0 of 30 | 0 of 24 |
| Formal graph, final state | glm-53-flash | 24 of 24 | 0 of 48 | 0 of 42 | 0 of 30 | 0 of 24 |
| Prose, final state | gemma-4-31b-it | 24 of 24 | 4 of 48 | 14 of 42 | 0 of 30 | 0 of 24 |
| Prose, final state | glm-53-flash | 24 of 24 | 0 of 48 | 0 of 42 | 0 of 30 | 0 of 24 |
| Prose history, after withdrawal | gemma-4-31b-it | 24 of 24 | 3 of 48 | 16 of 42 | 0 of 30 | 0 of 24 |
| Prose history, after withdrawal | glm-53-flash | 24 of 24 | 0 of 48 | 0 of 42 | 0 of 30 | 0 of 24 |
| Prose event, no prior answer | gemma-4-31b-it | 24 of 24 | 4 of 48 | 17 of 42 | 0 of 30 | 0 of 24 |
| Prose event, no prior answer | glm-53-flash | 24 of 24 | 0 of 48 | 0 of 42 | 0 of 30 | 0 of 24 |
| Extraction + recomputation | gemma-4-31b-it | 22 of 24 | 0 of 44 | 0 of 38 | 0 of 28 | 0 of 22 |
| Extraction + recomputation | glm-53-flash | 20 of 24 | 0 of 40 | 0 of 34 | 0 of 26 | 0 of 20 |

## Extraction

| Model | Accepted by the validator | Accepted and graph identical to the reference | Accepted with a wrong decision |
|---|---|---|---|
| gemma-4-31b-it | 22 of 24 | 22 | 0 |
| glm-53-flash | 20 of 24 | 20 | 0 |

## Paired contrasts from the frozen scorer (mean difference in decision accuracy, all scheduled labels)

| Contrast | Model | Mean difference | 95% resampling interval over the 24 cases |
|---|---|---|---|
| prose_fresh_minus_formal_fresh | gemma-4-31b-it | -10.42 points | [-16.67, -4.17] |
| prose_history_minus_prose_fresh | gemma-4-31b-it | -0.69 points | [-6.25, +5.56] |
| prose_history_minus_prose_no_commitment | gemma-4-31b-it | +1.39 points | [-3.47, +6.94] |
| prose_no_commitment_minus_prose_fresh | gemma-4-31b-it | -2.08 points | [-6.25, +1.39] |
| prose_extract_minus_prose_fresh | gemma-4-31b-it | +4.17 points | [-9.03, +14.58] |
| prose_fresh_minus_formal_fresh | glm-53-flash | +0.00 points | [+0.00, +0.00] |
| prose_history_minus_prose_fresh | glm-53-flash | +0.00 points | [+0.00, +0.00] |
| prose_history_minus_prose_no_commitment | glm-53-flash | +0.00 points | [+0.00, +0.00] |
| prose_no_commitment_minus_prose_fresh | glm-53-flash | +0.00 points | [+0.00, +0.00] |
| prose_extract_minus_prose_fresh | glm-53-flash | -16.67 points | [-33.33, -4.17] |

## Checks

- Frozen files that no longer match `data/prose-freeze.json`: 0.
- Reference decisions, project engine against the independent evaluator: 0 disagreements over 24 cases.
- gemma-4-31b-it: 144 records; frozen scorer and independent computation differ on 0 of them.
- glm-53-flash: 144 records; frozen scorer and independent computation differ on 0 of them.
