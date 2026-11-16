# Rules for the extension of the scaling run (written before any of its model calls)

Written Monday 16 November 2026, about 07:05 CET, by the second AI session (Claude) with AI assistance. At about 06:57 CET
the author approved further model calls in this session: a second model without a reasoning phase, and whatever further
tests are needed, with up to 1,000 credits. This file is committed, and its SHA-256 recorded in `prereg/HASHES`, before the
first call of the extension.

## 1. What had been seen when this was written

The complete main run under `prereg/scale_rules.md` and its two amendments, as paper v2 reports it: Gemma, the one model
without a reasoning phase, got 41 of 270 decisions wrong when answering from prose and none of 268 through compiled
declarations; the three reasoning models made no wrong decision in any usable answer, but 50 of their 108 compilations
were unusable, 46 of them requests cut by the provider after 60 seconds; Gemma's unsafe answers fell mostly on decisions
that lack support only through a copy of an unavailable source (a split made after the results were seen). No output of
the extension exists yet.

## 2. Parts

**E1. A second model without a reasoning phase.** Model `gemma-4-26b-a4b-it`, the only model on the provider's list that
is neither in the main run nor a larger reasoning model. The same 36 cases and three conditions as the main run
(`post_sweep/out/scale/sessions.json`, SHA-256 `07c56c77...69e`), Gemma's settings (output limit 8,192 tokens, temperature
0, not streamed). 108 requests. Whether the model has a reasoning phase is decided from its own answers: it counts as
without one when the median output of its direct answers at 10 records is under 200 tokens; otherwise it is reported with
the reasoning models.

**E2. Visible working.** The direct prompt of the main run asks for the answer alone. E2 gives the same 36 prose packets
with an instruction that asks for step-by-step working in plain text first and the answer on a final line
(`post_sweep/out/scale/ext/sessions_working.json`, SHA-256 `102e6b0e...cd3`, written by `post_sweep/scale_ext_sessions.py`;
only the last two lines of the first-day instruction are replaced). Models: `gemma-4-31b-it`, then `gemma-4-26b-a4b-it`.
36 requests each, output limit 8,192, not streamed. Scoring: the answer is the last JSON object in the output whose only
key is `decisions`; it is scored exactly as a direct answer. An output without such an object is unusable.

**E3. The reasoning models' compilations with streamed responses.** The main run's requests were not streamed, and the
provider cut each at 60 seconds. The sweep's own transport streamed its responses. E3 issues the 36 compilation sessions
again (`post_sweep/out/scale/ext/sessions_stream_extract.json`, SHA-256 `faaa2f4f...9be`) for `glm-53-flash`,
`qwen3.8-27b` and `deepseek-v4-flash`, in that order, with `"stream": true`, output limit 32,768 and a client timeout of
300 s. Everything else in the request is unchanged. The main run's results stand as they are; E3 is reported beside them.

**E4. Copy share.** New cases with 40 records and a different share of copies. Its cases, conditions and outcomes are
fixed in an addendum that is committed before its first call.

## 3. Runner, failures, ceilings, stopping

- Runner: `post_sweep/run_scale_ext.mjs`, a copy of the main run's second runner with the sessions file and output folder
  as arguments and an optional streamed response. Journals go to `post_sweep/out/scale/ext/<part>/<model>/`.
- One model at a time, two requests at a time. Nothing is retried except a request rejected with HTTP 429 (after 65 s, at
  most twice). A failed, cut-off, invalid or rejected answer is unusable and counts as in the main run.
- At most 900 requests and 80 credits of reservation for the whole extension.
- All calls stop at 09:15 CET. Slots not issued by then are reported as not issued. Order: E1; E2 for both models; E3 for
  `glm-53-flash` and `qwen3.8-27b`; E4; E3 for `deepseek-v4-flash`.

## 4. Outcomes

- E1: as in `prereg/scale_rules.md`, section 6, for the new model.
- E2: usable answers, fully correct cases and wrong decisions (unsafe and dropped), set beside the same model's direct
  answers from prose and its compiled route on the same cases; median output tokens and seconds.
- E3: accepted declarations, declarations identical to the reference graph, fully correct cases per size, seconds per
  answer, set beside the main run's non-streamed result.
- The split by copies (`post_sweep/scale_error_paths.py`, definition unchanged) is applied to every new direct answer.

Scoring is done with the frozen first-day scorer and with the independent evaluator, as in the main run. No significance
threshold is set. Every outcome is reported whichever way it falls, including a second model that does not show Gemma's
pattern, working that closes the gap, and compilations that are wrong when they arrive.

## 5. Labels

The extension is post hoc relative to the main run and prespecified relative to its own outputs. It uses the same
generated cases, first-day engine and prompts as the main run, except where a part says otherwise.
