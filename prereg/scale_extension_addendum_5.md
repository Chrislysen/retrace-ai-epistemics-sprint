# Addendum 5 to the rules for the extension of the scaling run: parts E7 (a second run) and E8 (80 records)

Written Monday 16 November 2026, about 10:25 CET, by the second AI session (Claude) with AI assistance, before any call
of parts E7 and E8.

## What had been seen when this was written

Parts E1 to E6, scored, and paper v3 built from them. No request of E7 or E8 exists. The author read v3 and a list of
its weaknesses at about 10:15 and asked for work on them. Two of them can be tested today: every request was issued
once, and the cases stop at 40 records. Both parts are post hoc relative to everything before them and fixed here
before their own outputs exist.

## Part E7: a second run

Question: the main run and part E1 issued each request once at temperature 0. Does a second run give the same picture?

- Models: `gemma-4-31b-it` and `gemma-4-26b-a4b-it`, the two whose direct answers fail.
- Requests: the main run's 108 sessions per model (`post_sweep/out/scale/sessions.json`, SHA-256 `07c56c77...969e`),
  with the main run's settings: output limit 8,192 tokens, not streamed.
- Outcomes, per model and condition: fully correct cases and wrong decisions in usable answers in the second run, beside
  the first; among slots usable in both runs, the number whose answers differ in at least one decision and the number of
  decisions that differ; for compilations, accepted in both, in one, in neither.
- No expectation is stated beyond this: if the two runs differ in more than a few decisions, the paper says that single
  runs at temperature 0 are not repeatable at this provider and gives both.

## Part E8: 80 records

Question: do the results of the scaling run and of the search task hold at the next step of the size ladder?

- Cases: twelve, written by `post_sweep/scale_cases_xl.py` with the main run's generator (80 records, 40 claims,
  12 decisions, 4 records withdrawn, 40 percent copies, seed 2026111603). `corpus_xl.json` SHA-256 `f5e02544...87e7`.
  The list of claim topics is doubled with a "phase two" variant of each, because 40 claims need 40 topics. Of the 144
  decisions, 93 are supported after the withdrawal; a smallest further withdrawal has one record for 71 of them, two for
  20 and three for 2 (`withdrawal_reference_xl.json`, SHA-256 `099965e3...2318`).
- Models: `gemma-4-31b-it`, then `gemma-4-26b-a4b-it`.
- Conditions: the three first-day conditions (`sessions_xl.json`, `2127ac77...d817`); working shown first, the
  instruction of part E2 (`sessions_xl_working.json`, `5cb5ab8e...71ce`); the search task with the two instructions of
  part E5 (`sessions_xl_withdrawal_answer.json`, `23b6b49f...817f`; `sessions_xl_withdrawal_working.json`,
  `d9112c2c...ce64`). 72 requests per model.
- Settings: output limit 8,192 tokens as before. All requests of this part are streamed, as in the sweep's own
  transport, because a compilation of 80 records can be expected to take longer than the 60 seconds that requests
  without streaming are given.
- The compiled route of the search task uses each model's own accepted declarations from this part.
- Scoring: the scripts of parts E1 to E5, changed only so that they also read these files.

Expectations, written before the calls, for `gemma-4-31b-it`:

1. Answering alone from prose it is fully correct in at most 1 of 12 cases (1 of 11 at 40 records).
2. With its working shown first it still gets at least 95 percent of decisions right. I hold this one loosely: if it
   fails, working stops being enough at this size, and that is the more interesting outcome.
3. Every declaration the validator accepts is identical to the reference graph.
4. With working shown first, the share of supported decisions for which it names a smallest set is below the share at
   40 records (29 of 53), and the search in its accepted declarations gives a smallest set for every supported decision.

The results are reported whichever way they fall, including an outcome in which nothing changes at 80 records.

## Order, stop and ceilings

E8 for `gemma-4-31b-it`, E8 for `gemma-4-26b-a4b-it`, E7 for `gemma-4-31b-it`, E7 for `gemma-4-26b-a4b-it`; one model at
a time. Both parts stop at 11:15 CET; what has not been issued by then is reported as not issued. The request ceiling
of the whole extension is raised from 900 to 1,000 (620 used; 360 more if everything is issued); the ceiling of 80
credits of reservation is unchanged. Nothing is retried except a request rejected with HTTP 429.
