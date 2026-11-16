# Scaling run: direct answers and compiled declarations at three case sizes

Produced by `post_sweep/score_scale.py` from `post_sweep/out/scale/`. Rules: `prereg/scale_rules.md`. 12 cases per size and model. Unusable = provider failure, invalid output or rejected graph.

## gemma-4-31b-it

Requests sent 108 (0 rejected with HTTP 429 before inference), slots with an answer record 108 of 108, of which failed or cut off 4; frozen scorer and independent evaluator differ on 0 slots.

| Size | Condition | Usable /12 | Fully correct /12 | Decision errors, all scheduled | Unsafe (usable) | Dropped (usable) | Graph exact /12 |
|---|---|---|---|---|---|---|---|
| S | Direct, formal ledger | 12 | 10 | 3 of 72 | 1 of 42 | 2 of 30 |  |
| S | Direct, from prose | 12 | 7 | 10 of 72 | 6 of 42 | 4 of 30 |  |
| S | Compiled from prose, then computed | 10 | 10 | 12 of 72 | 0 of 34 | 0 of 26 | 10 |
| M | Direct, formal ledger | 12 | 8 | 7 of 96 | 5 of 58 | 2 of 38 |  |
| M | Direct, from prose | 11 | 7 | 17 of 96 | 3 of 53 | 6 of 35 |  |
| M | Compiled from prose, then computed | 11 | 11 | 8 of 96 | 0 of 52 | 0 of 36 | 11 |
| L | Direct, formal ledger | 12 | 6 | 14 of 120 | 13 of 60 | 1 of 60 |  |
| L | Direct, from prose | 11 | 1 | 32 of 120 | 8 of 56 | 14 of 54 |  |
| L | Compiled from prose, then computed | 12 | 12 | 0 of 120 | 0 of 60 | 0 of 60 | 12 |

| Size | Condition | Withdrawn support still asserted | Never supported, asserted | Surviving alternative dropped | Untouched decision dropped | Median output tokens | Median seconds |
|---|---|---|---|---|---|---|---|
| S | Direct, formal ledger | 1 of 24 | 0 of 18 | 2 of 22 | 0 of 8 | 55 | 0.8 |
| S | Direct, from prose | 5 of 24 | 1 of 18 | 3 of 22 | 1 of 8 | 49 | 0.8 |
| S | Compiled from prose, then computed | 0 of 20 | 0 of 14 | 0 of 18 | 0 of 8 | 1017 | 9.6 |
| M | Direct, formal ledger | 5 of 36 | 0 of 22 | 1 of 23 | 1 of 15 | 69 | 0.9 |
| M | Direct, from prose | 3 of 32 | 0 of 21 | 3 of 21 | 3 of 14 | 64 | 0.9 |
| M | Compiled from prose, then computed | 0 of 32 | 0 of 20 | 0 of 22 | 0 of 14 | 1857 | 17.3 |
| L | Direct, formal ledger | 11 of 33 | 2 of 27 | 0 of 32 | 1 of 28 | 82 | 1.1 |
| L | Direct, from prose | 6 of 30 | 2 of 26 | 9 of 28 | 5 of 26 | 78 | 1.1 |
| L | Compiled from prose, then computed | 0 of 33 | 0 of 27 | 0 of 32 | 0 of 28 | 2226 | 21.1 |

| Size | Fully correct: prose | Fully correct: compiled | Compiled right, prose wrong | Prose right, compiled wrong | Accuracy difference, points [95% interval] |
|---|---|---|---|---|---|
| S | 7 | 10 | 4 | 1 | -2.8 [-25.0, 15.3] |
| M | 7 | 11 | 5 | 1 | +9.4 [-17.7, 33.3] |
| L | 1 | 12 | 11 | 0 | +26.7 [15.8, 42.5] |

| Size | Cases usable in both | Unsafe decisions: prose | Unsafe decisions: compiled | Fully correct: prose | Fully correct: compiled |
|---|---|---|---|---|---|
| S | 10 | 3 of 34 | 0 of 34 | 6 | 10 |
| M | 10 | 3 of 47 | 0 of 47 | 6 | 10 |
| L | 11 | 8 of 56 | 0 of 56 | 1 | 11 |

## gemma-4-26b-a4b-it

Requests sent 108 (0 rejected with HTTP 429 before inference), slots with an answer record 108 of 108, of which failed or cut off 0; frozen scorer and independent evaluator differ on 0 slots.

| Size | Condition | Usable /12 | Fully correct /12 | Decision errors, all scheduled | Unsafe (usable) | Dropped (usable) | Graph exact /12 |
|---|---|---|---|---|---|---|---|
| S | Direct, formal ledger | 12 | 3 | 17 of 72 | 1 of 42 | 16 of 30 |  |
| S | Direct, from prose | 12 | 2 | 23 of 72 | 0 of 42 | 23 of 30 |  |
| S | Compiled from prose, then computed | 11 | 10 | 7 of 72 | 1 of 38 | 0 of 28 | 9 |
| M | Direct, formal ledger | 12 | 2 | 27 of 96 | 5 of 58 | 22 of 38 |  |
| M | Direct, from prose | 12 | 0 | 33 of 96 | 1 of 58 | 32 of 38 |  |
| M | Compiled from prose, then computed | 5 | 5 | 56 of 96 | 0 of 25 | 0 of 15 | 5 |
| L | Direct, formal ledger | 12 | 0 | 45 of 120 | 3 of 60 | 42 of 60 |  |
| L | Direct, from prose | 12 | 0 | 46 of 120 | 0 of 60 | 46 of 60 |  |
| L | Compiled from prose, then computed | 3 | 3 | 90 of 120 | 0 of 19 | 0 of 11 | 3 |

| Size | Condition | Withdrawn support still asserted | Never supported, asserted | Surviving alternative dropped | Untouched decision dropped | Median output tokens | Median seconds |
|---|---|---|---|---|---|---|---|
| S | Direct, formal ledger | 1 of 24 | 0 of 18 | 15 of 22 | 1 of 8 | 54 | 0.5 |
| S | Direct, from prose | 0 of 24 | 0 of 18 | 18 of 22 | 5 of 8 | 49 | 0.7 |
| S | Compiled from prose, then computed | 0 of 23 | 1 of 15 | 0 of 21 | 0 of 7 | 1012 | 4.4 |
| M | Direct, formal ledger | 5 of 36 | 0 of 22 | 17 of 23 | 5 of 15 | 69 | 0.5 |
| M | Direct, from prose | 1 of 36 | 0 of 22 | 20 of 23 | 12 of 15 | 64 | 0.5 |
| M | Compiled from prose, then computed | 0 of 14 | 0 of 11 | 0 of 10 | 0 of 5 | 1283 | 5.8 |
| L | Direct, formal ledger | 2 of 33 | 1 of 27 | 26 of 32 | 16 of 28 | 82 | 0.6 |
| L | Direct, from prose | 0 of 33 | 0 of 27 | 25 of 32 | 21 of 28 | 77 | 0.6 |
| L | Compiled from prose, then computed | 0 of 10 | 0 of 9 | 0 of 5 | 0 of 6 | 2576 | 11.1 |

| Size | Fully correct: prose | Fully correct: compiled | Compiled right, prose wrong | Prose right, compiled wrong | Accuracy difference, points [95% interval] |
|---|---|---|---|---|---|
| S | 2 | 10 | 8 | 0 | +22.2 [1.4, 38.9] |
| M | 0 | 5 | 5 | 0 | -24.0 [-52.1, 3.1] |
| L | 0 | 3 | 3 | 0 | -36.7 [-55.8, -15.0] |

| Size | Cases usable in both | Unsafe decisions: prose | Unsafe decisions: compiled | Fully correct: prose | Fully correct: compiled |
|---|---|---|---|---|---|
| S | 11 | 0 of 38 | 1 of 38 | 2 | 10 |
| M | 5 | 0 of 25 | 0 of 25 | 0 | 5 |
| L | 3 | 0 of 19 | 0 of 19 | 0 | 3 |

## qwen3.8-27b

Requests sent 116 (8 rejected with HTTP 429 before inference), slots with an answer record 106 of 108, of which failed or cut off 13; frozen scorer and independent evaluator differ on 0 slots.

| Size | Condition | Usable /12 | Fully correct /12 | Decision errors, all scheduled | Unsafe (usable) | Dropped (usable) | Graph exact /12 |
|---|---|---|---|---|---|---|---|
| S | Direct, formal ledger | 11 | 11 | 6 of 72 | 0 of 38 | 0 of 28 |  |
| S | Direct, from prose | 12 | 12 | 0 of 72 | 0 of 42 | 0 of 30 |  |
| S | Compiled from prose, then computed | 12 | 12 | 0 of 72 | 0 of 42 | 0 of 30 | 12 |
| M | Direct, formal ledger | 12 | 12 | 0 of 96 | 0 of 58 | 0 of 38 |  |
| M | Direct, from prose | 12 | 12 | 0 of 96 | 0 of 58 | 0 of 38 |  |
| M | Compiled from prose, then computed | 9 | 9 | 24 of 96 | 0 of 41 | 0 of 31 | 9 |
| L | Direct, formal ledger | 12 | 12 | 0 of 120 | 0 of 60 | 0 of 60 |  |
| L | Direct, from prose | 11 | 11 | 10 of 120 | 0 of 56 | 0 of 54 |  |
| L | Compiled from prose, then computed | 1 | 1 | 110 of 120 | 0 of 6 | 0 of 4 | 1 |

| Size | Condition | Withdrawn support still asserted | Never supported, asserted | Surviving alternative dropped | Untouched decision dropped | Median output tokens | Median seconds |
|---|---|---|---|---|---|---|---|
| S | Direct, formal ledger | 0 of 21 | 0 of 17 | 0 of 20 | 0 of 8 | 923 | 6.7 |
| S | Direct, from prose | 0 of 24 | 0 of 18 | 0 of 22 | 0 of 8 | 1682 | 12.3 |
| S | Compiled from prose, then computed | 0 of 24 | 0 of 18 | 0 of 22 | 0 of 8 | 3938 | 27.6 |
| M | Direct, formal ledger | 0 of 36 | 0 of 22 | 0 of 23 | 0 of 15 | 1390 | 10.4 |
| M | Direct, from prose | 0 of 36 | 0 of 22 | 0 of 23 | 0 of 15 | 3949 | 27.8 |
| M | Compiled from prose, then computed | 0 of 27 | 0 of 14 | 0 of 16 | 0 of 15 | 6188 | 42.9 |
| L | Direct, formal ledger | 0 of 33 | 0 of 27 | 0 of 32 | 0 of 28 | 3294 | 23.1 |
| L | Direct, from prose | 0 of 30 | 0 of 26 | 0 of 28 | 0 of 26 | 5998 | 43.3 |
| L | Compiled from prose, then computed | 0 of 5 | 0 of 1 | 0 of 3 | 0 of 1 | 5439 | 35.6 |

| Size | Fully correct: prose | Fully correct: compiled | Compiled right, prose wrong | Prose right, compiled wrong | Accuracy difference, points [95% interval] |
|---|---|---|---|---|---|
| S | 12 | 12 | 0 | 0 | +0.0 [0.0, 0.0] |
| M | 12 | 9 | 0 | 3 | -25.0 [-50.0, 0.0] |
| L | 11 | 1 | 0 | 10 | -83.3 [-100.0, -58.3] |

| Size | Cases usable in both | Unsafe decisions: prose | Unsafe decisions: compiled | Fully correct: prose | Fully correct: compiled |
|---|---|---|---|---|---|
| S | 12 | 0 of 42 | 0 of 42 | 12 | 12 |
| M | 9 | 0 of 41 | 0 of 41 | 9 | 9 |
| L | 1 | 0 of 6 | 0 of 6 | 1 | 1 |

## deepseek-v4-flash

Requests sent 113 (5 rejected with HTTP 429 before inference), slots with an answer record 108 of 108, of which failed or cut off 39; frozen scorer and independent evaluator differ on 0 slots.

| Size | Condition | Usable /12 | Fully correct /12 | Decision errors, all scheduled | Unsafe (usable) | Dropped (usable) | Graph exact /12 |
|---|---|---|---|---|---|---|---|
| S | Direct, formal ledger | 12 | 12 | 0 of 72 | 0 of 42 | 0 of 30 |  |
| S | Direct, from prose | 12 | 12 | 0 of 72 | 0 of 42 | 0 of 30 |  |
| S | Compiled from prose, then computed | 5 | 5 | 42 of 72 | 0 of 16 | 0 of 14 | 5 |
| M | Direct, formal ledger | 12 | 12 | 0 of 96 | 0 of 58 | 0 of 38 |  |
| M | Direct, from prose | 10 | 10 | 16 of 96 | 0 of 46 | 0 of 34 |  |
| M | Compiled from prose, then computed | 0 | 0 | 96 of 96 | 0 of 0 | 0 of 0 | 0 |
| L | Direct, formal ledger | 10 | 10 | 20 of 120 | 0 of 48 | 0 of 52 |  |
| L | Direct, from prose | 7 | 7 | 50 of 120 | 0 of 35 | 0 of 35 |  |
| L | Compiled from prose, then computed | 0 | 0 | 120 of 120 | 0 of 0 | 0 of 0 | 0 |

| Size | Condition | Withdrawn support still asserted | Never supported, asserted | Surviving alternative dropped | Untouched decision dropped | Median output tokens | Median seconds |
|---|---|---|---|---|---|---|---|
| S | Direct, formal ledger | 0 of 24 | 0 of 18 | 0 of 22 | 0 of 8 | 776 | 6.4 |
| S | Direct, from prose | 0 of 24 | 0 of 18 | 0 of 22 | 0 of 8 | 1445 | 10.4 |
| S | Compiled from prose, then computed | 0 of 10 | 0 of 6 | 0 of 9 | 0 of 5 | 2948 | 24.0 |
| M | Direct, formal ledger | 0 of 36 | 0 of 22 | 0 of 23 | 0 of 15 | 1689 | 12.7 |
| M | Direct, from prose | 0 of 27 | 0 of 19 | 0 of 20 | 0 of 14 | 2206 | 17.0 |
| M | Compiled from prose, then computed | 0 of 0 | 0 of 0 | 0 of 0 | 0 of 0 |  |  |
| L | Direct, formal ledger | 0 of 26 | 0 of 22 | 0 of 27 | 0 of 25 | 3745 | 29.7 |
| L | Direct, from prose | 0 of 21 | 0 of 14 | 0 of 19 | 0 of 16 | 4265 | 31.8 |
| L | Compiled from prose, then computed | 0 of 0 | 0 of 0 | 0 of 0 | 0 of 0 |  |  |

| Size | Fully correct: prose | Fully correct: compiled | Compiled right, prose wrong | Prose right, compiled wrong | Accuracy difference, points [95% interval] |
|---|---|---|---|---|---|
| S | 12 | 5 | 0 | 7 | -58.3 [-83.3, -33.3] |
| M | 10 | 0 | 0 | 10 | -83.3 [-100.0, -58.3] |
| L | 7 | 0 | 0 | 7 | -58.3 [-83.3, -33.3] |

| Size | Cases usable in both | Unsafe decisions: prose | Unsafe decisions: compiled | Fully correct: prose | Fully correct: compiled |
|---|---|---|---|---|---|
| S | 5 | 0 of 16 | 0 of 16 | 5 | 5 |
| M | 0 | 0 of 0 | 0 of 0 | 0 | 0 |
| L | 0 | 0 of 0 | 0 of 0 | 0 | 0 |

## glm-53-flash

Requests sent 108 (0 rejected with HTTP 429 before inference), slots with an answer record 108 of 108, of which failed or cut off 4; frozen scorer and independent evaluator differ on 0 slots.

| Size | Condition | Usable /12 | Fully correct /12 | Decision errors, all scheduled | Unsafe (usable) | Dropped (usable) | Graph exact /12 |
|---|---|---|---|---|---|---|---|
| S | Direct, formal ledger | 12 | 12 | 0 of 72 | 0 of 42 | 0 of 30 |  |
| S | Direct, from prose | 12 | 12 | 0 of 72 | 0 of 42 | 0 of 30 |  |
| S | Compiled from prose, then computed | 11 | 11 | 6 of 72 | 0 of 40 | 0 of 26 | 11 |
| M | Direct, formal ledger | 12 | 12 | 0 of 96 | 0 of 58 | 0 of 38 |  |
| M | Direct, from prose | 12 | 12 | 0 of 96 | 0 of 58 | 0 of 38 |  |
| M | Compiled from prose, then computed | 11 | 11 | 8 of 96 | 0 of 54 | 0 of 34 | 11 |
| L | Direct, formal ledger | 12 | 12 | 0 of 120 | 0 of 60 | 0 of 60 |  |
| L | Direct, from prose | 12 | 12 | 0 of 120 | 0 of 60 | 0 of 60 |  |
| L | Compiled from prose, then computed | 9 | 9 | 30 of 120 | 0 of 47 | 0 of 43 | 9 |

| Size | Condition | Withdrawn support still asserted | Never supported, asserted | Surviving alternative dropped | Untouched decision dropped | Median output tokens | Median seconds |
|---|---|---|---|---|---|---|---|
| S | Direct, formal ledger | 0 of 24 | 0 of 18 | 0 of 22 | 0 of 8 | 673 | 4.6 |
| S | Direct, from prose | 0 of 24 | 0 of 18 | 0 of 22 | 0 of 8 | 1006 | 6.0 |
| S | Compiled from prose, then computed | 0 of 23 | 0 of 17 | 0 of 19 | 0 of 7 | 1589 | 9.3 |
| M | Direct, formal ledger | 0 of 36 | 0 of 22 | 0 of 23 | 0 of 15 | 1208 | 7.6 |
| M | Direct, from prose | 0 of 36 | 0 of 22 | 0 of 23 | 0 of 15 | 2397 | 15.2 |
| M | Compiled from prose, then computed | 0 of 33 | 0 of 21 | 0 of 19 | 0 of 15 | 3424 | 21.0 |
| L | Direct, formal ledger | 0 of 33 | 0 of 27 | 0 of 32 | 0 of 28 | 2413 | 14.8 |
| L | Direct, from prose | 0 of 33 | 0 of 27 | 0 of 32 | 0 of 28 | 3904 | 23.2 |
| L | Compiled from prose, then computed | 0 of 27 | 0 of 20 | 0 of 20 | 0 of 23 | 7018 | 42.9 |

| Size | Fully correct: prose | Fully correct: compiled | Compiled right, prose wrong | Prose right, compiled wrong | Accuracy difference, points [95% interval] |
|---|---|---|---|---|---|
| S | 12 | 11 | 0 | 1 | -8.3 [-25.0, 0.0] |
| M | 12 | 11 | 0 | 1 | -8.3 [-25.0, 0.0] |
| L | 12 | 9 | 0 | 3 | -25.0 [-50.0, 0.0] |

| Size | Cases usable in both | Unsafe decisions: prose | Unsafe decisions: compiled | Fully correct: prose | Fully correct: compiled |
|---|---|---|---|---|---|
| S | 11 | 0 of 40 | 0 of 40 | 11 | 11 |
| M | 11 | 0 of 54 | 0 of 54 | 11 | 11 |
| L | 9 | 0 of 47 | 0 of 47 | 9 | 9 |

## Requests

Scheduled runs: 445 requests written to the journals, 443 answer records (13 HTTP 429, 58 HTTP 504, 2 other errors). Connection tests: 4 requests. Observed token cost 0.6550 credits.

## All models pooled (5 models)

| Size | Condition | Slots | Usable | Fully correct | Decision errors, all scheduled | Unsafe (usable) | Dropped (usable) | Graph exact |
|---|---|---|---|---|---|---|---|---|
| S | Direct, formal ledger | 60 | 59 | 48 | 26 of 360 | 2 of 206 | 18 of 148 |  |
| S | Direct, from prose | 60 | 60 | 45 | 33 of 360 | 6 of 210 | 27 of 150 |  |
| S | Compiled from prose, then computed | 60 | 49 | 48 | 67 of 360 | 1 of 170 | 0 of 124 | 47 |
| M | Direct, formal ledger | 60 | 60 | 46 | 34 of 480 | 10 of 290 | 24 of 190 |  |
| M | Direct, from prose | 60 | 57 | 41 | 66 of 480 | 4 of 273 | 38 of 183 |  |
| M | Compiled from prose, then computed | 60 | 36 | 36 | 192 of 480 | 0 of 172 | 0 of 116 | 36 |
| L | Direct, formal ledger | 60 | 58 | 40 | 79 of 600 | 16 of 288 | 43 of 292 |  |
| L | Direct, from prose | 60 | 53 | 31 | 138 of 600 | 8 of 267 | 60 of 263 |  |
| L | Compiled from prose, then computed | 60 | 25 | 25 | 350 of 600 | 0 of 132 | 0 of 118 | 25 |
