# Addendum 4 to the rules for the extension of the scaling run: part E6, the second model on the search task

Written Monday 16 November 2026, about 08:40 CET, by the second AI session (Claude) with AI assistance, before any call
of part E6.

## What had been seen when this was written

Part E5, scored, for `gemma-4-31b-it` and `glm-53-flash` (`paper_build/tables/scale_withdrawal.md`): answering alone,
Gemma named a smallest set for 38 of 128 supported decisions; with its working shown first for 88 of 121; GLM-Flash for
74 of 81 in the 24 answers that arrived. The search in accepted declarations of the main run, which needs no call, is
scored for all five models. For `gemma-4-26b-a4b-it` it covers 19 of 36 cases: every set smallest in 18 of them, and
in one case a set for a decision that has no support (the declaration that misread its source). Of part E3, six
streamed responses of `deepseek-v4-flash` (status, token count and duration: four used the whole output limit).
No answer of `gemma-4-26b-a4b-it` to the question of part E5 exists.

## Question

Part E5 put the search task to one model without a reasoning phase. E6 puts it to the second one, so that the
comparison between naming a smallest withdrawal and searching for it does not rest on a single such model.

## Materials

The files of part E5, unchanged: `withdrawal_reference.json` (SHA-256 `ff8a3881...c937`),
`sessions_withdrawal_answer.json` (`66ecfcbf...70a0`) and `sessions_withdrawal_working.json` (`7b0876f7...4c09`), all
under `post_sweep/out/scale/ext/`.

## Model and conditions

`gemma-4-26b-a4b-it`: answer only, then working first; output limit 8,192 tokens, not streamed; 36 requests each, 72 in
all. These are the settings of part E5 for `gemma-4-31b-it`. The compiled route is the one already scored.

## Scoring

As in addendum 3, by the same script (`post_sweep/score_withdrawal_task.py`), with no change.

## Expectation, written before the calls

With its working shown first this model names more smallest sets than when it answers alone. In both conditions it
names a smallest set for a smaller share of the supported decisions than the search finds in its accepted declarations.
The result is reported whichever way it falls. Two facts that count against the compiled route for this model are
already known and stay in the paper: only 19 of its 36 declarations were accepted, and one of those was wrong.

## Order, stop and ceilings

E6 starts only after every other part has stopped, so that one model is called at a time as before. The stop of
09:15 CET stays for every other part. E6 alone has a stop of 09:50 CET: the user asked in this session for the second
model to be added and approved further tests, the earlier stop was set to leave time for the paper, and this part needs
about ten minutes. The ceilings of 900 requests and 80 credits of reservation for the whole extension are unchanged.
