# Addendum 3 to the rules for the extension of the scaling run: part E5, the smallest further withdrawal

Written Monday 16 November 2026, about 07:30 CET, by the second AI session (Claude) with AI assistance, before any call
of part E5.

## What had been seen when this was written

Parts E1 and E2, scored: with working shown first the two Gemma models got 0 of 282 and 4 of 288 decisions wrong, against
41 of 270 and 102 of 288 when answering alone. So the question "is this decision supported?" does not need the engine
once a model may work before it answers. Of part E3, twenty-four streamed GLM-Flash answers (status and duration only).
Nothing of part E4. No answer to the question of part E5 exists.

## Question

The engine's own task is a search: find a smallest change of the evidence with a given effect. Proposition B.1 says
that finding a smallest withdrawal is hard while checking a named one is cheap. E5 puts that search to the models
directly, on the main run's 36 cases in the state after the withdrawal: for each decision, name a smallest set of
further records whose withdrawal would leave the decision without support.

## Materials

Written by `post_sweep/scale_withdrawal_task.py`, under `post_sweep/out/scale/ext/`:

- `withdrawal_reference.json`, SHA-256 `ff8a3881...c937`: the smallest size for every decision, by exhaustive search over
  subsets of the records available in that state. Of the 128 decisions that are supported, 103 need one record, 23 need
  two and 2 need three.
- `sessions_withdrawal_answer.json`, SHA-256 `66ecfcbf...70a0`: the 36 prose packets with an instruction that asks for
  the answer only.
- `sessions_withdrawal_working.json`, SHA-256 `7b0876f7...4c09`: the same packets with an instruction that asks for the
  working first.

Both instructions keep the first seven lines of the first-day instruction and replace its return format.

## Models and conditions

- `gemma-4-31b-it`: answer only, then working first (output limit 8,192, not streamed), 36 requests each.
- `glm-53-flash`: answer only, streamed, output limit 32,768, 36 requests.
- The compiled route needs no call: each model's own accepted declarations from the main run are searched exhaustively
  by the same program that produced the reference, and the set it finds is scored like an answer. A case without an
  accepted declaration has no answer.

## Scoring

The answer is the last JSON object in the output whose only key is `withdrawals`. For a decision that is supported in
the reference state, the named set is valid when it consists of records of the case and the decision has no support
after their withdrawal, and smallest when it is valid and has the reference size. For a decision without support the
empty set is correct. A missing decision counts as not valid. Outcomes per model, condition and case size: usable
answers; of the supported decisions in usable answers, how many sets are valid and how many are smallest, split by the
reference size (one record, or more); cases in which every decision is answered with a smallest set. An output without
the object is unusable. The frozen first-day scorer has no part here; the reference and the scoring use the independent
evaluator's support function.

## Order and stop

After part E4: E5 for Gemma (both instructions), E5 for GLM-Flash, then the streamed compilations of part E3 for
`deepseek-v4-flash` and `qwen3.8-27b` as far as the stop at 09:15 CET allows. Ceilings as before. The result is
reported whichever way it falls, including one in which the models name smallest sets as reliably as the search does.
