# Extension of the scaling run

Produced by `post_sweep/score_scale_ext.py`. Rules: `prereg/scale_extension_rules.md` and its addendum.

## E2 visible working, main run's 36 cases

### Gemma-26B (gemma-4-26b-a4b-it)

Requests sent 36, slots with a record 36, errors {}, outputs without a final answer object 0, scorer disagreements 0.

```
S   Direct, from prose, visible working   usable 12/12 fully correct 11 | wrong 1 of 72 (unsafe 0 of 42, dropped 1 of 30) | asserted: copy-mediated 0 of 14, direct 0 of 28 | provider failures 0, not issued 0 | tokens 926, seconds 4.2
M   Direct, from prose, visible working   usable 12/12 fully correct 11 | wrong 1 of 96 (unsafe 1 of 58, dropped 0 of 38) | asserted: copy-mediated 1 of 20, direct 0 of 38 | provider failures 0, not issued 0 | tokens 1309, seconds 5.8
L   Direct, from prose, visible working   usable 12/12 fully correct 11 | wrong 2 of 120 (unsafe 0 of 60, dropped 2 of 60) | asserted: copy-mediated 0 of 23, direct 0 of 37 | provider failures 0, not issued 0 | tokens 2234, seconds 9.9
```

### Gemma (gemma-4-31b-it)

Requests sent 36, slots with a record 36, errors {'http_error 504': 1}, outputs without a final answer object 0, scorer disagreements 0.

```
S   Direct, from prose, visible working   usable 11/12 fully correct 11 | wrong 0 of 66 (unsafe 0 of 38, dropped 0 of 28) | asserted: copy-mediated 0 of 14, direct 0 of 24 | provider failures 1, not issued 0 | tokens 902, seconds 9.2
M   Direct, from prose, visible working   usable 12/12 fully correct 12 | wrong 0 of 96 (unsafe 0 of 58, dropped 0 of 38) | asserted: copy-mediated 0 of 20, direct 0 of 38 | provider failures 0, not issued 0 | tokens 1240, seconds 12.5
L   Direct, from prose, visible working   usable 12/12 fully correct 12 | wrong 0 of 120 (unsafe 0 of 60, dropped 0 of 60) | asserted: copy-mediated 0 of 23, direct 0 of 37 | provider failures 0, not issued 0 | tokens 1614, seconds 16.0
```

## E3 compilations with streamed responses

### DeepSeek (deepseek-v4-flash)

Requests sent 31, slots with a record 31, errors {'response_not_completed 200': 25}, outputs without a final answer object 0, scorer disagreements 0.

```
S   Compiled from prose                   usable  3/12 fully correct  3 | wrong 0 of 18 (unsafe 0 of 11, dropped 0 of 7) | asserted: copy-mediated 0 of 5, direct 0 of 6 | provider failures 6, not issued 2 | tokens 2720, seconds 19.0 | graph exact 3
M   Compiled from prose                   usable  1/12 fully correct  1 | wrong 0 of 8 (unsafe 0 of 5, dropped 0 of 3) | asserted: copy-mediated 0 of 3, direct 0 of 2 | provider failures 9, not issued 2 | tokens 6961, seconds 48.5 | graph exact 1
L   Compiled from prose                   usable  1/12 fully correct  1 | wrong 0 of 10 (unsafe 0 of 5, dropped 0 of 5) | asserted: copy-mediated 0 of 0, direct 0 of 5 | provider failures 10, not issued 1 | tokens 9904, seconds 66.6 | graph exact 1
```

### GLM-Flash (glm-53-flash)

Requests sent 37, slots with a record 36, errors {}, outputs without a final answer object 0, scorer disagreements 0.

```
S   Compiled from prose                   usable 12/12 fully correct 12 | wrong 0 of 72 (unsafe 0 of 42, dropped 0 of 30) | asserted: copy-mediated 0 of 14, direct 0 of 28 | provider failures 0, not issued 0 | tokens 1372, seconds 7.4 | graph exact 12
M   Compiled from prose                   usable 12/12 fully correct 12 | wrong 0 of 96 (unsafe 0 of 58, dropped 0 of 38) | asserted: copy-mediated 0 of 20, direct 0 of 38 | provider failures 0, not issued 0 | tokens 4080, seconds 21.6 | graph exact 12
L   Compiled from prose                   usable 12/12 fully correct 12 | wrong 0 of 120 (unsafe 0 of 60, dropped 0 of 60) | asserted: copy-mediated 0 of 23, direct 0 of 37 | provider failures 0, not issued 0 | tokens 8543, seconds 45.1 | graph exact 12
```

## E4 copy share, first-day conditions

### Gemma-26B (gemma-4-26b-a4b-it)

Requests sent 72, slots with a record 72, errors {}, outputs without a final answer object 0, scorer disagreements 0.

```
C0  Direct, formal ledger                 usable 12/12 fully correct  0 | wrong 45 of 120 (unsafe 1 of 55, dropped 44 of 65) | asserted: copy-mediated 0 of 0, direct 1 of 55 | provider failures 0, not issued 0 | tokens 83, seconds 0.6
C0  Compiled from prose                   usable  3/12 fully correct  3 | wrong 0 of 30 (unsafe 0 of 13, dropped 0 of 17) | asserted: copy-mediated 0 of 0, direct 0 of 13 | provider failures 0, not issued 0 | tokens 2082, seconds 9.3 | graph exact 3
C0  Direct, from prose                    usable 12/12 fully correct  0 | wrong 47 of 120 (unsafe 3 of 55, dropped 44 of 65) | asserted: copy-mediated 0 of 0, direct 3 of 55 | provider failures 0, not issued 0 | tokens 78, seconds 0.6
C8  Direct, formal ledger                 usable 12/12 fully correct  1 | wrong 43 of 120 (unsafe 6 of 60, dropped 37 of 60) | asserted: copy-mediated 6 of 45, direct 0 of 15 | provider failures 0, not issued 0 | tokens 84, seconds 0.6
C8  Compiled from prose                   usable  2/12 fully correct  2 | wrong 0 of 20 (unsafe 0 of 11, dropped 0 of 9) | asserted: copy-mediated 0 of 9, direct 0 of 2 | provider failures 0, not issued 0 | tokens 2234, seconds 10.1 | graph exact 2
C8  Direct, from prose                    usable 12/12 fully correct  0 | wrong 54 of 120 (unsafe 1 of 60, dropped 53 of 60) | asserted: copy-mediated 1 of 45, direct 0 of 15 | provider failures 0, not issued 0 | tokens 79, seconds 0.6
```

### Gemma (gemma-4-31b-it)

Requests sent 72, slots with a record 72, errors {'http_error 504': 4}, outputs without a final answer object 0, scorer disagreements 0.

```
C0  Direct, formal ledger                 usable 12/12 fully correct  9 | wrong 6 of 120 (unsafe 1 of 55, dropped 5 of 65) | asserted: copy-mediated 0 of 0, direct 1 of 55 | provider failures 0, not issued 0 | tokens 83, seconds 1.1
C0  Compiled from prose                   usable  9/12 fully correct  9 | wrong 0 of 90 (unsafe 0 of 41, dropped 0 of 49) | asserted: copy-mediated 0 of 0, direct 0 of 41 | provider failures 2, not issued 0 | tokens 2148, seconds 20.8 | graph exact 9
C0  Direct, from prose                    usable 11/12 fully correct  2 | wrong 20 of 110 (unsafe 10 of 49, dropped 10 of 61) | asserted: copy-mediated 0 of 0, direct 10 of 49 | provider failures 1, not issued 0 | tokens 78, seconds 1.1
C8  Direct, formal ledger                 usable 12/12 fully correct  4 | wrong 29 of 120 (unsafe 23 of 60, dropped 6 of 60) | asserted: copy-mediated 23 of 45, direct 0 of 15 | provider failures 0, not issued 0 | tokens 84, seconds 1.1
C8  Compiled from prose                   usable 11/12 fully correct 11 | wrong 0 of 110 (unsafe 0 of 53, dropped 0 of 57) | asserted: copy-mediated 0 of 38, direct 0 of 15 | provider failures 0, not issued 0 | tokens 2337, seconds 23.4 | graph exact 11
C8  Direct, from prose                    usable 11/12 fully correct  3 | wrong 27 of 110 (unsafe 2 of 57, dropped 25 of 53) | asserted: copy-mediated 2 of 43, direct 0 of 14 | provider failures 1, not issued 0 | tokens 78, seconds 1.1
```

## E4 copy share, visible working

### Gemma-26B (gemma-4-26b-a4b-it)

Requests sent 24, slots with a record 24, errors {}, outputs without a final answer object 0, scorer disagreements 0.

```
C0  Direct, from prose, visible working   usable 12/12 fully correct  9 | wrong 4 of 120 (unsafe 0 of 55, dropped 4 of 65) | asserted: copy-mediated 0 of 0, direct 0 of 55 | provider failures 0, not issued 0 | tokens 1748, seconds 7.7
C8  Direct, from prose, visible working   usable 12/12 fully correct  9 | wrong 4 of 120 (unsafe 0 of 60, dropped 4 of 60) | asserted: copy-mediated 0 of 45, direct 0 of 15 | provider failures 0, not issued 0 | tokens 2376, seconds 10.4
```

### Gemma (gemma-4-31b-it)

Requests sent 24, slots with a record 24, errors {'http_error 504': 1}, outputs without a final answer object 0, scorer disagreements 0.

```
C0  Direct, from prose, visible working   usable 11/12 fully correct 11 | wrong 0 of 110 (unsafe 0 of 51, dropped 0 of 59) | asserted: copy-mediated 0 of 0, direct 0 of 51 | provider failures 1, not issued 0 | tokens 1485, seconds 14.9
C8  Direct, from prose, visible working   usable 12/12 fully correct 12 | wrong 0 of 120 (unsafe 0 of 60, dropped 0 of 60) | asserted: copy-mediated 0 of 45, direct 0 of 15 | provider failures 0, not issued 0 | tokens 1900, seconds 18.6
```

## E7 second run of the main design

### Gemma-26B (gemma-4-26b-a4b-it)

Requests sent 108, slots with a record 108, errors {}, outputs without a final answer object 0, scorer disagreements 0.

```
S   Direct, formal ledger                 usable 12/12 fully correct  3 | wrong 18 of 72 (unsafe 2 of 42, dropped 16 of 30) | asserted: copy-mediated 0 of 14, direct 2 of 28 | provider failures 0, not issued 0 | tokens 54, seconds 0.4
S   Compiled from prose                   usable 10/12 fully correct 10 | wrong 0 of 60 (unsafe 0 of 34, dropped 0 of 26) | asserted: copy-mediated 0 of 9, direct 0 of 25 | provider failures 0, not issued 0 | tokens 987, seconds 4.5 | graph exact 9
S   Direct, from prose                    usable 12/12 fully correct  1 | wrong 24 of 72 (unsafe 0 of 42, dropped 24 of 30) | asserted: copy-mediated 0 of 14, direct 0 of 28 | provider failures 0, not issued 0 | tokens 49, seconds 0.5
M   Direct, formal ledger                 usable 12/12 fully correct  2 | wrong 27 of 96 (unsafe 5 of 58, dropped 22 of 38) | asserted: copy-mediated 5 of 20, direct 0 of 38 | provider failures 0, not issued 0 | tokens 68, seconds 0.5
M   Compiled from prose                   usable  6/12 fully correct  5 | wrong 2 of 48 (unsafe 2 of 30, dropped 0 of 18) | asserted: copy-mediated 0 of 12, direct 2 of 18 | provider failures 0, not issued 0 | tokens 1239, seconds 5.4 | graph exact 5
M   Direct, from prose                    usable 12/12 fully correct  0 | wrong 33 of 96 (unsafe 2 of 58, dropped 31 of 38) | asserted: copy-mediated 0 of 20, direct 2 of 38 | provider failures 0, not issued 0 | tokens 63, seconds 0.5
L   Direct, formal ledger                 usable 12/12 fully correct  0 | wrong 41 of 120 (unsafe 3 of 60, dropped 38 of 60) | asserted: copy-mediated 2 of 23, direct 1 of 37 | provider failures 0, not issued 0 | tokens 82, seconds 0.6
L   Compiled from prose                   usable  1/12 fully correct  1 | wrong 0 of 10 (unsafe 0 of 6, dropped 0 of 4) | asserted: copy-mediated 0 of 2, direct 0 of 4 | provider failures 0, not issued 0 | tokens 2116, seconds 9.2 | graph exact 1
L   Direct, from prose                    usable 12/12 fully correct  0 | wrong 46 of 120 (unsafe 0 of 60, dropped 46 of 60) | asserted: copy-mediated 0 of 23, direct 0 of 37 | provider failures 0, not issued 0 | tokens 77, seconds 0.6
```

run 1 against run 2, Direct, formal ledger: {"slots": 36, "usable_in_both": 36, "usable_in_first_only": 0, "usable_in_second_only": 0, "usable_in_neither": 0, "decisions_in_both": 288, "decisions_that_differ": 5, "slots_with_a_difference": 3, "fully_correct_in_both": 5, "fully_correct_in_first_only": 0, "fully_correct_in_second_only": 0, "errors_first": 89, "errors_second": 86}
run 1 against run 2, Direct, from prose: {"slots": 36, "usable_in_both": 36, "usable_in_first_only": 0, "usable_in_second_only": 0, "usable_in_neither": 0, "decisions_in_both": 288, "decisions_that_differ": 5, "slots_with_a_difference": 5, "fully_correct_in_both": 1, "fully_correct_in_first_only": 1, "fully_correct_in_second_only": 0, "errors_first": 102, "errors_second": 103}
run 1 against run 2, Compiled from prose: {"slots": 36, "usable_in_both": 14, "usable_in_first_only": 5, "usable_in_second_only": 3, "usable_in_neither": 14, "decisions_in_both": 94, "decisions_that_differ": 1, "slots_with_a_difference": 1, "fully_correct_in_both": 13, "fully_correct_in_first_only": 0, "fully_correct_in_second_only": 1, "errors_first": 1, "errors_second": 0}

### Gemma (gemma-4-31b-it)

Requests sent 108, slots with a record 108, errors {'http_error 504': 5}, outputs without a final answer object 0, scorer disagreements 0.

```
S   Direct, formal ledger                 usable 12/12 fully correct 10 | wrong 3 of 72 (unsafe 1 of 42, dropped 2 of 30) | asserted: copy-mediated 1 of 14, direct 0 of 28 | provider failures 0, not issued 0 | tokens 54, seconds 0.8
S   Compiled from prose                   usable 10/12 fully correct 10 | wrong 0 of 60 (unsafe 0 of 34, dropped 0 of 26) | asserted: copy-mediated 0 of 11, direct 0 of 23 | provider failures 1, not issued 0 | tokens 1017, seconds 9.9 | graph exact 10
S   Direct, from prose                    usable 11/12 fully correct  7 | wrong 8 of 66 (unsafe 6 of 40, dropped 2 of 26) | asserted: copy-mediated 4 of 14, direct 2 of 26 | provider failures 1, not issued 0 | tokens 49, seconds 0.8
M   Direct, formal ledger                 usable 12/12 fully correct  8 | wrong 7 of 96 (unsafe 5 of 58, dropped 2 of 38) | asserted: copy-mediated 2 of 20, direct 3 of 38 | provider failures 0, not issued 0 | tokens 68, seconds 1.0
M   Compiled from prose                   usable 12/12 fully correct 12 | wrong 0 of 96 (unsafe 0 of 58, dropped 0 of 38) | asserted: copy-mediated 0 of 20, direct 0 of 38 | provider failures 0, not issued 0 | tokens 1860, seconds 18.1 | graph exact 12
M   Direct, from prose                    usable 11/12 fully correct  6 | wrong 9 of 88 (unsafe 5 of 52, dropped 4 of 36) | asserted: copy-mediated 2 of 20, direct 3 of 32 | provider failures 1, not issued 0 | tokens 64, seconds 0.9
L   Direct, formal ledger                 usable 12/12 fully correct  6 | wrong 14 of 120 (unsafe 13 of 60, dropped 1 of 60) | asserted: copy-mediated 11 of 23, direct 2 of 37 | provider failures 0, not issued 0 | tokens 82, seconds 1.1
L   Compiled from prose                   usable 11/12 fully correct 11 | wrong 0 of 110 (unsafe 0 of 54, dropped 0 of 56) | asserted: copy-mediated 0 of 21, direct 0 of 33 | provider failures 1, not issued 0 | tokens 2271, seconds 22.3 | graph exact 11
L   Direct, from prose                    usable 11/12 fully correct  1 | wrong 21 of 110 (unsafe 8 of 55, dropped 13 of 55) | asserted: copy-mediated 6 of 22, direct 2 of 33 | provider failures 1, not issued 0 | tokens 78, seconds 1.1
```

run 1 against run 2, Direct, formal ledger: {"slots": 36, "usable_in_both": 36, "usable_in_first_only": 0, "usable_in_second_only": 0, "usable_in_neither": 0, "decisions_in_both": 288, "decisions_that_differ": 0, "slots_with_a_difference": 0, "fully_correct_in_both": 24, "fully_correct_in_first_only": 0, "fully_correct_in_second_only": 0, "errors_first": 24, "errors_second": 24}
run 1 against run 2, Direct, from prose: {"slots": 36, "usable_in_both": 31, "usable_in_first_only": 3, "usable_in_second_only": 2, "usable_in_neither": 0, "decisions_in_both": 246, "decisions_that_differ": 3, "slots_with_a_difference": 1, "fully_correct_in_both": 14, "fully_correct_in_first_only": 0, "fully_correct_in_second_only": 0, "errors_first": 36, "errors_second": 35}
run 1 against run 2, Compiled from prose: {"slots": 36, "usable_in_both": 31, "usable_in_first_only": 2, "usable_in_second_only": 2, "usable_in_neither": 1, "decisions_in_both": 252, "decisions_that_differ": 0, "slots_with_a_difference": 0, "fully_correct_in_both": 31, "fully_correct_in_first_only": 0, "fully_correct_in_second_only": 0, "errors_first": 0, "errors_second": 0}

## E8 80 records, first-day conditions

### Gemma-26B (gemma-4-26b-a4b-it)

Requests sent 36, slots with a record 36, errors {'http_error 502': 1, 'response_not_completed 200': 5}, outputs without a final answer object 0, scorer disagreements 0.

```
XL  Direct, formal ledger                 usable 12/12 fully correct  0 | wrong 76 of 144 (unsafe 2 of 51, dropped 74 of 93) | asserted: copy-mediated 2 of 22, direct 0 of 29 | provider failures 0, not issued 0 | tokens 98, seconds 0.7
XL  Compiled from prose                   usable  0/12 fully correct  0 | wrong 0 of 0 (unsafe 0 of 0, dropped 0 of 0) | asserted: copy-mediated 0 of 0, direct 0 of 0 | provider failures 5, not issued 0 | tokens -, seconds - | graph exact 0
XL  Direct, from prose                    usable 11/12 fully correct  0 | wrong 78 of 132 (unsafe 3 of 47, dropped 75 of 85) | asserted: copy-mediated 2 of 21, direct 1 of 26 | provider failures 1, not issued 0 | tokens 93, seconds 0.7
```

### Gemma (gemma-4-31b-it)

Requests sent 36, slots with a record 36, errors {'response_not_completed 200': 2}, outputs without a final answer object 0, scorer disagreements 0.

```
XL  Direct, formal ledger                 usable 11/12 fully correct  3 | wrong 17 of 132 (unsafe 7 of 48, dropped 10 of 84) | asserted: copy-mediated 6 of 19, direct 1 of 29 | provider failures 1, not issued 0 | tokens 99, seconds 1.3
XL  Compiled from prose                   usable  9/12 fully correct  9 | wrong 0 of 108 (unsafe 0 of 41, dropped 0 of 67) | asserted: copy-mediated 0 of 16, direct 0 of 25 | provider failures 1, not issued 0 | tokens 4157, seconds 40.8 | graph exact 8
XL  Direct, from prose                    usable 12/12 fully correct  0 | wrong 54 of 144 (unsafe 6 of 51, dropped 48 of 93) | asserted: copy-mediated 4 of 22, direct 2 of 29 | provider failures 0, not issued 0 | tokens 93, seconds 1.4
```

## E8 80 records, visible working

### Gemma-26B (gemma-4-26b-a4b-it)

Requests sent 12, slots with a record 12, errors {'response_not_completed 200': 1}, outputs without a final answer object 0, scorer disagreements 0.

```
XL  Direct, from prose, visible working   usable 11/12 fully correct  5 | wrong 20 of 132 (unsafe 0 of 48, dropped 20 of 84) | asserted: copy-mediated 0 of 20, direct 0 of 28 | provider failures 1, not issued 0 | tokens 3372, seconds 14.8
```

### Gemma (gemma-4-31b-it)

Requests sent 12, slots with a record 12, errors {'response_not_completed 200': 2}, outputs without a final answer object 0, scorer disagreements 0.

```
XL  Direct, from prose, visible working   usable 10/12 fully correct  9 | wrong 1 of 120 (unsafe 0 of 37, dropped 1 of 83) | asserted: copy-mediated 0 of 16, direct 0 of 21 | provider failures 2, not issued 0 | tokens 2596, seconds 25.8
```

## Requests of the whole extension, part E1 included

{"sent": 752, "http_429": 1, "http_504": 11, "cost_x10000": 6073}

Scorer disagreements in the parts scored here: 0

