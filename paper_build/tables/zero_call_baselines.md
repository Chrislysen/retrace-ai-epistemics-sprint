# Baselines on the authored families (mechanism checks)

Produced by `post_sweep/zero_call_analyses.py`. Post hoc analyses fixed in `prereg/post_sweep_rules.md`; no model call.
These hold by construction of the cases; they show which mechanism each family of cases needs, not an effect size.

| Baseline | Pairs | Agree with the engine | Unsafe | Over-cautious | Other difference | Cases changed |
|---|---|---|---|---|---|---|
| no_lineage | 768 | 729 | 39 | 0 | 0 | 24 |
| withdraw_downstream | 768 | 629 | 0 | 123 | 16 | 50 |
| single_reading | 768 | 752 | 6 | 0 | 10 | 10 |
| naive_gate | 768 | 762 | 6 | 0 | 0 | 3 |

By case family (unsafe / over-cautious pairs):

| Baseline | ECO | F1 | F2 | F3 | F4 | F5 | F6 |
|---|---|---|---|---|---|---|---|
| no_lineage | 5 / 0 of 72 | 1 / 0 of 120 | 8 / 0 of 120 | 0 / 0 of 120 | 4 / 0 of 120 | 2 / 0 of 96 | 19 / 0 of 120 |
| withdraw_downstream | 0 / 2 of 72 | 0 / 22 of 120 | 0 / 17 of 120 | 0 / 19 of 120 | 0 / 32 of 120 | 0 / 14 of 96 | 0 / 17 of 120 |
| single_reading | 0 / 0 of 72 | 0 / 0 of 120 | 0 / 0 of 120 | 3 / 0 of 120 | 0 / 0 of 120 | 3 / 0 of 96 | 0 / 0 of 120 |
| naive_gate | 0 / 0 of 72 | 0 / 0 of 120 | 0 / 0 of 120 | 0 / 0 of 120 | 0 / 0 of 120 | 6 / 0 of 96 | 0 / 0 of 120 |

Structure of the 60 authored cases: cases 60; cases_with_copies 36; cases_with_multi_parent_copy 17; cases_with_negative_warrant 4; cases_with_several_readings 10; cases_with_undercutter 6; cases_with_unknown_ancestry 1; decision_state_pairs 768; gold_pairs_ASSERT 444; gold_pairs_SPLIT 18; gold_pairs_WITHHOLD 306; multi_reading_cases_where_readings_never_differ_in_class 0.

Engine checks on the authored families: accepted_but_attacked 0; arguments 5051; attacks 11; cases 60; evaluations 180; evaluations_identical_twice 180; labels_out 0; labels_undecided 11; restored_state_reached_by_events 60; unattacked_not_accepted 0; withdrawn_state_reached_by_events 60; worlds 645.
