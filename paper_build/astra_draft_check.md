# Check of Astra's final draft (r4) against the recomputation and the code

Written Monday 16 November 2026 by the second agent (Claude), with AI assistance throughout.
Draft checked: `report/v6n-study/revisions/r4/research-draft.md` and its Word file (13 pages, main text 7 pages).
Result in one line: **every number agrees; no number was changed; eight method sentences were made exact; one
sentence about the build was replaced.** The corrected paper is `paper_build/RETRACE_v1.pdf`. Section 5 covers the
chat reviewer's later notes, section 6 Gemini's review, and section 7 the scaling run and `paper_build/RETRACE_v2.pdf`.

## 1. Numbers

Checked against my own recomputation from the raw journals (`post_sweep/recompute_sweep.py`,
`post_sweep/check_astra_draft.py`, `post_sweep/zero_call_analyses.py`) or, where the draft quotes a saved file,
against that file. All agree.

| Where in the draft | What | Source of the check |
|---|---|---|
| Abstract, 4.1 | 300 slots, 210 completed, 181 admitted exact, 139 bare; 119 = 86 + 4 + 29 | `sweep_tables.json`, `astra_draft_check.json` |
| Table 2 | completed, admitted exact, bare exact per model; projection bare /30 | `sweep_tables.json` |
| 4.1 | synthetic and bridge bare counts per model | `astra_draft_check.json` (strict_ir_by_partition) |
| 4.1 | Qwen 23 against 7 of 30, Holm p .000641, interval [−.700, −.367]; 15 timeouts, 15 skips, 5 timeouts | recomputed test; interval from the rerun frozen scorer |
| Table 3, 4.2 | refuter 75/150 and 115/150, per model; 79 located objections, 0 on faithful seeds; 78 + 2 + 20 | `astra_draft_check.json` (refuter) |
| 4.3 | assisted against oracle 9→10, 4→11, 6→6, 7→11, 1→8; K10 0/12 (2 with fences); 17/24 quartets, 0 flips; long 7→1 | `sweep_tables.json`, `sweep_secondary.json` |
| 5, App. A | 1,703 requests, 1,701 responses, 2 unanswered; 224.692061361 credits; 1,271 + 529; 1.5040498 reservation | journals; `score.json`; `m-prefix-proof.json` |
| 3 | 214 readings, 50 single-reading cases, ten cases with 2 to 32 readings; 30 deficient and 30 faithful seeds, balanced | corpus (`astra_draft_check.json`) |
| Table 1, App. A | slot counts per component (sum 1,800); subsets (12 synthetic, 30 with six bridges, K10 eight F3, two F5, one F4, one F6) | design file |
| App. C | all 21 rows of the contrast table | recomputed tests |
| App. D | range −23/30 to 4/30 for the Qwen contrast | `astra_draft_check.json` (qwen_two_stage) |
| App. B | 520 comparisons | rerun in process (`post_sweep/rerun_separation_check.py`): 504 + 16, passed, identical to the saved certificate |
| 5 | 120 cases, 17 state transitions, 385 parses | read from `results/frontier-v6n/post-sweep/checks.json`; not rerun |

## 2. Method statements compared with the code

A read-only helper agent audited 17 groups of statements; I then read the cited lines myself for every point it flagged.
Twelve groups were supported as written. These were changed in v1:

| Draft said | Code does | Where | v1 says |
|---|---|---|---|
| The argumentation construction includes "scoped evidence-only undercutters" | Undercutters are Boolean guards on evidence (A unless U), evaluated before any argument exists | `retrace/tiered_v6h.py:101-102` | Exceptions are part of the Boolean dependencies |
| "restricted equal-priority grounded-argumentation construction" (no more) | The only attacks are rebuttals, and every attacker is attacked back, so nothing is ever labelled out: accepted means unattacked | `retrace/argumentation_v6h.py:78-82` | Says so, in Section 2 and Section 5 |
| Clarification stops "when the selected decision target agrees" | Stops when the readings agree on the status of every target decision | `retrace/workbench_v6h.py:52-55` | Reworded, also in Appendix B |
| "120 authored computational cases" | 120 generated cases, run on the earlier engine `retrace.core` | `scripts/check_frontier_v6n_post_sweep.py:263-265`, `retrace/benchmark.py:13` | "120 generated cases for the earlier Boolean support engine" |
| Certificate "checks 520 graph/state comparisons" | 504 for k = 1 to 6 plus 16 for the veto construction | `scripts/check_frontier_v6j_separation.py:58-70, 95-109, 143` | Adds the range of k |
| "Labels, row order and irrelevant metadata are ignored" | Order is ignored; graphs have no labels and extra fields are rejected | `retrace/tiered_v6h.py:36`, `retrace/graph_identity_v6h.py:22-24` | Reworded |
| "limits every certificate" | The engine issues no certificate | `retrace/source_ir_v6h.py` | "limits every symbolic result" |
| Consequential witness not defined | A withdrawal set (possibly empty), or one activation followed by one withdrawal | `retrace/frontier_v6h_eval.py:207-217`, `retrace/impact_v6h.py:83` | One sentence added in Appendix D |

Also changed: Appendix E now carries the name the sprint requires ("Limitations and Dual-Use / Ethical
Considerations"); the sentence "Rendering receipts bind the manuscript..." now says that they bind the preceding build.

The draft does **not** claim an incremental cache, certificates on verdicts, priorities or full ASPIC+. None of
these is in the code, so nothing had to be removed.

## 3. What was added (the improvements)

1. Section 4.4 and Table 4: four simpler rules against the engine on the authored families.
2. Section 4.4: direct answers against compiled declarations in both experiments, including the unfavourable result.
3. Appendix G: procedure, recomputation, ranges for unavailable outcomes (Table G1, Figure G1), direct answers (Table G2), the first-day 24-case experiment (Table G3).
4. Section 1: closest 2026 work (references 9 to 13, re-fetched today) and who would use this (reference 14).
5. Code and Data section; disclosure of the second agent in Appendix F; a limits paragraph in Section 5.

Layout after all changes (including section 5 below): 20 pages, main text ends on page 8 (limit 8), abstract 247 words
(limit 250), PDF 0.5 MB (limit 25 MB).

## 4. Not checked

- Nothing was run against a model provider. The workbench server was not started. The unit tests were not rerun.
- Astra's post-sweep checks (120 / 17 / 385) were not rerun; the counts are read from its file.
- The reviewer's Linux run of the release verifier was not observed here; the paper says so.

## 5. The chat reviewer's notes (IMPROVEMENTS_FROM_CHAT.md), item by item

| Item | Checked how | Result |
|---|---|---|
| 1. Abstract | Every number against my tables | Applied, 247 words. Changed from the reviewer's draft: "lost to a crash" became "every failure stays in the denominators" (the record does not establish a crash); "finds the smallest change" became "searches for a smallest change" (typed releases are only pair-minimal); the recomputation and the direct-answer result were kept in |
| 1. Introduction | Against Figure 1's truth table | Applied: the example in plain words with the things named and still labelled constructed; propose-then-check paragraph; three contributions as a list |
| 1. Each caveat once | Each removed sentence located elsewhere in the paper first | Applied to six sentences in Sections 3 and 4 that Section 3, a caption or Appendix D also state. Distinct caveats were kept |
| 2. Proposition B.1 | Reduction re-derived; `check_theory_against_engine.py` run here: 400 of 400 instances | Holds. Applied |
| 2. Proposition B.2 | Proof re-derived; script: 292 silent families, 0 witnesses | Holds. Applied. The engine's own "Tier A" allows exceptions (`impact_v6h.py:14`), so the paper says "monotone family" |
| 2. Proposition B.3 | Derived independently before the notes arrived; script: 20,000 sets, no rejected argument | Holds. Applied |
| 2. Scope bounds 16 and 10 | `impact_v6h.py:54, 69` | Hold |
| 2. Karp (1972) | Crossref record | Verified; reference 15 |
| 3.1 Agreement depth | `post_sweep/agreement_depth.py`, calling the grader's own functions | Done, Appendix G. New finding: two deficient cases have no scored witness, so 10 of the 150 refuter slots cannot earn credit; the four exact objections without credit are on them |
| 3.2 Independent evaluator | `post_sweep/independent_evaluator.py` (136 lines, no import from `retrace/`) | Done: agrees on 3,072 reading-state decisions, 768 family pairs and 25,600 random-withdrawal decision states |
| 4. Second platform | Zip size and SHA-256 identical to the reviewer's; verifier rerun here from a clean extraction | Passed here (Windows 11, Python 3.12.10; 3,819 files, 1,800 slots, 0 provider calls). The Linux run is reported as the reviewer's, not observed here |
| 5. Human review, title, tracks | The author's decisions | Not changed |

Dung (1995) was re-fetched at Crossref after the earlier refusal and matches reference 8.

## 6. Gemini's review of v1 (received about 04:45), point by point

| Point | Holds? | What was done |
|---|---|---|
| 1. "Human manuscript review has not occurred" (Appendix F) | Yes | Replaced by "Automated and AI-assisted checks are not external peer review." The paper now asserts nothing about a review; the stronger sentence Gemini proposes is the author's to add after reading |
| 1. "approved the rules in advance without reading them" (Appendix G) | Yes | Now "The author authorised the rules in advance." |
| 1. "(read at abstract level)" (Section 1) | Yes | References 9 to 12 were read in full text today (PACMI, Shen et al., Metales et al., Gao et al.); none holds several readings of one source or searches for a separating intervention. Reference 13 has no readable full text on arXiv's page and is a measurement study by its abstract. The sentence now ends "a combination that, to our knowledge, none of these works provides." |
| 2. 49 against 50 cases | Yes | Both are right: 49 cases have a dropped pair, 50 change in all. The sentence now gives both |
| 3. Outcome chart into Section 4.1 | Yes | It is Figure 2 under Table 2. Page 8 was not half empty in the build Gemini read (about a fifth), so two captions and three sentences were shortened to stay within 8 pages |
| 4. Missing subscript on Diamond | No | Both Box and Diamond carry the subscript in the PDF (checked at 220 dpi); only the text layer flattens it |
| 4. Delta header in Table C1 | Partly | The delta was drawn, but from a fallback font. The header now reads "Diff. pp" |
| 4. Reversed rows in Table C1 | No | Every row is B minus A as labelled; GLM-5.2 "event − hist" is 0 − 1, and all 21 rows match the recomputation |
| 4. glm-53-flash against glm-5.3-flash | Deliberate | It is the ID recorded in the first-day run. Appendix G now says so; the main text no longer names it |
| 5. Tracks header | Author's choice | Not changed |
| 5. Archive hash | Yes | The zip was not touched; the PDF is not inside it |

Also removed in the same pass, as process notes of no use to a reader: the sentence about rendering receipts, "that run was
not observed here", "limits of this check", and the phrase "the preserved project record states". The minus sign, which the
template font draws as a long dash, is now drawn from a font with a real minus (the character is unchanged).

To keep the main text within 8 pages after these additions: Figure 1, Table 1, Table 3 and Table 4 now follow one or two
paragraphs of nearby text instead of standing directly under a heading; Figure 1 is shown at nine tenths of its size;
the per-stratum counts, the argument counts and the post-sweep software checks moved to Appendices G and F unchanged;
the accounting bound is given once, in Appendix A; the definition of graph identity is given once, in Appendix D; two
sentences of Section 3 that Appendices A and D repeat (prose has no grade of its own; histories hold actual predecessor
answers) were removed; "Code and data" is a run-in paragraph. Every one of these is listed with its reason in
`paper_build/v1_edits.json`.

## 7. Scaling run and paper v2 (16 November, from 05:15)

At about 05:15 the author asked for a stronger result and approved model calls: four models, at most 450 requests, a
reservation ceiling of 35 credits. The paper with this run is `paper_build/RETRACE_v2.pdf`. `RETRACE_v1.pdf` (commit
`4fbd54b`) is unchanged and remains the version without it.

### 7.1 What was run, and in what order

| Time (CET) | Event |
|---|---|
| 05:22:31 | `prereg/scale_rules.md` and the 36 generated cases committed (`9c7d17d`), hash in `prereg/HASHES` |
| 05:23:29 | four connection tests, one per model, on a first-day case |
| 05:24:31 | first scheduled request (Gemma under the rules as written; it finished at 05:34) |
| 05:27 | Qwen's first run stopped after 11 requests: two answers cut off at 8,192 output tokens, two requests in flight |
| 05:34:44 | Amendment 1 committed (`4001c34`): output limit 32,768 and a runner that does not stop at a failed request, for the three reasoning models |
| 05:35 | Qwen and DeepSeek started side by side; the provider rejected 13 requests with HTTP 429 before any inference |
| 05:38:56 | Amendment 2 committed (`5643fee`): one model at a time; a request rejected with 429 is issued again after 65 s, at most twice |
| 05:38:57 to 06:00:52 | Qwen |
| 06:02:02 to 06:31:18 | DeepSeek |
| 06:32:28 to 06:48:07 | GLM-Flash |

Each amendment was committed before the first request it governs. The case generator reproduces the committed cases
exactly from its seed (checked by capturing its output instead of writing it). The frozen first-day scorer and the
independent evaluator were both run on every slot; they disagree on no slot. The run sent 449 requests in all, four connection tests included (approved: at most 450); observed token cost about 0.66 credits.

### 7.2 Result

Fully correct cases / usable answers, of twelve scheduled per cell (from `paper_build/scale_paper_numbers.py`):

```
Model | Condition | 10 records | 20 records | 40 records | Wrong decisions in usable answers | Median seconds at 10, 20, 40
Gemma | Direct, formal ledger | 10 / 12 | 8 / 12 | 6 / 12 | 24 of 288 | 0.8, 0.9, 1.1
Gemma | Direct, from prose | 7 / 12 | 7 / 11 | 1 / 11 | 41 of 270 | 0.8, 0.9, 1.1
Gemma | Compiled from prose | 10 / 10 | 11 / 11 | 12 / 12 | 0 of 268 | 9.6, 17, 21
Qwen27B | Direct, formal ledger | 11 / 11 | 12 / 12 | 12 / 12 | 0 of 282 | 6.7, 10, 23
Qwen27B | Direct, from prose | 12 / 12 | 12 / 12 | 11 / 11 | 0 of 278 | 12, 28, 43
Qwen27B | Compiled from prose | 12 / 12 | 9 / 9 | 1 / 1 | 0 of 154 | 28, 43, 36
DeepSeek | Direct, formal ledger | 12 / 12 | 12 / 12 | 10 / 10 | 0 of 268 | 6.4, 13, 30
DeepSeek | Direct, from prose | 12 / 12 | 10 / 10 | 7 / 7 | 0 of 222 | 10, 17, 32
DeepSeek | Compiled from prose | 5 / 5 | 0 / 0 | 0 / 0 | 0 of 30 | 24, –, –
GLM-Flash | Direct, formal ledger | 12 / 12 | 12 / 12 | 12 / 12 | 0 of 288 | 4.6, 7.6, 15
GLM-Flash | Direct, from prose | 12 / 12 | 12 / 12 | 12 / 12 | 0 of 288 | 6.0, 15, 23
GLM-Flash | Compiled from prose | 11 / 11 | 11 / 11 | 9 / 9 | 0 of 244 | 9.3, 21, 43
```

- Gemma, the one model without a reasoning phase: 41 of 270 answered decisions wrong from prose (14, 10 and 20 percent at
  10, 20 and 40 records), 24 of 288 from the formal ledger (4, 7 and 12 percent), and 0 of 268 through compilation. All 33
  declarations that the validator accepted were identical to the reference graph.
- The three reasoning models: 
- Post hoc split (`post_sweep/scale_error_paths.py`): of the 160 unsupported decisions, 57 lack support only because a
  copy's source is unavailable. Gemma asserted 14 of those 57 and 5 of the other 103 from the ledger, and 12 of 54 and 5 of
  97 from prose. The first-day experiment of 13 November shows the same: 13 of 192 against 0 of 96 over its four direct
  conditions. The reasoning models asserted none.

### 7.3 What goes against the method or limits the result (all stated in the paper)

- For the reasoning models the prespecified comparison goes against compilation: their direct answers were right and
  their compilations often did not come back within the provider's 60-second limit (HTTP 504). No returned compilation
  was wrong. Requests were not streamed, so this run cannot say what those models would compile given more time.
- "7, 7 and 1 of 12 fully correct" also reflects that larger cases have more decisions (6, 8, 10). The paper therefore
  gives the per-decision rates next to it; from prose they are not monotone (14, 10, 20 percent).
- One model without a reasoning phase, twelve cases per cell, generated prose, the first-day engine.
- The direct prompt asks for the answer alone ("no explanation"). Visible step-by-step working was not tested.
- Four Qwen slots were lost to the procedure, not to the model: two cut off at the original output limit and two in flight
  when its first run was stopped. Under Amendment 1 they were not issued again and count as unusable.
- Gemma also lost four slots to HTTP 504, although it answers in about a second, so not every 504 is a slow model.
- The split by copies was made after the results had been seen.

### 7.4 Where the numbers in the paper come from

| In the paper | Produced by |
|---|---|
| Section 4.5, abstract, contribution 3, Appendix H "Gemma", "Reasoning models", "Requests and failures" | `paper_build/scale_paper_numbers.py` from `post_sweep/out/scale/score.json` (written by `post_sweep/score_scale.py`) |
| Table H1 | generated by the same script into `paper_build/tables/scale_table_h1.json` and spliced into the build by `paper_build/splice_scale_table.ps1`; nothing is retyped |
| Figure 2 | `paper_build/make_figure_scale.ps1` from `score.json` |
| The split by copies (Section 4.5, Appendix H) | `post_sweep/scale_error_paths.py` -> `post_sweep/out/scale/error_paths.json` |
| Long documents in the sweep (Appendix H) | `post_sweep/long_context_contrast.py` -> `post_sweep/out/long_context_contrast.json` |
| Prompt size (Appendix H, "Limits") | the largest `input_tokens` value in the response journals: 3,944 |

### 7.5 Other changes from v1 to v2, all to stay within eight pages

- The outcome chart of the 300 direct slots is Figure G1 in Appendix G again (it was Figure 2 in Section 4.1 after
  Gemini's review). The scaling figure is Figure 2. Table 2 carries the same counts as the chart.
- The table of simpler rules moved from Section 4.4 to Appendix G. The appendix tables are numbered in the order they
  appear: G1 unavailable outcomes, G2 simpler rules, G3 direct verdicts, G4 first-day experiment.
- The Gemma-only diagnostics (K10, preference probes, long documents) moved from Section 4.3 to Appendix D unchanged.
- Shorter, with the removed detail kept in an appendix: both paragraphs of Section 4.4 (the count 444 and "49 cases, 16
  shifts" are in Appendix G), the paragraph on the second session in Section 3, the limits in Section 5, the paragraph on
  code and data. The main text no longer repeats the accounting bound, which Appendix A gives.
- Table 3 now follows the two paragraphs of Section 4.3, and Section 4.2 refers to it by number. It did not fit under
  the text of Section 4.2 and had left a quarter of page 6 empty.
- New abstract (249 words as the build counts them) and a reworded third contribution.
- Section 4.5 ties the split by copies to references 11 and 12, which the introduction already cites for models that
  count copies as confirmations.

### 7.6 Not checked

- Whether the reasoning models' compilations would be correct with streaming or a longer time limit.
- Whether visible working would close Gemma's gap, and whether a second model without a reasoning phase shows it too.
- The unit tests and the workbench server, as before.

## 8. Extension of the scaling run, the second review round, and paper v3 (16 November, from 06:57)

At about 06:57 the author sent a second set of notes from the reviewing session (`IMPROVEMENTS_ROUND_2.md`, with
`long_context_check.py` and `check_clarification_against_engine.py`), asked for the second model to be added, and
approved whatever further tests were needed, with up to 1,000 credits. The result is `paper_build/RETRACE_v3.pdf`.
`RETRACE_v2.pdf` (commit `e6f5155`) and `RETRACE_v1.pdf` (commit `4fbd54b`) are unchanged.

### 8.1 The extension: what was run, and in what order

| Time (CET) | Event |
|---|---|
| 07:02:55 | `prereg/scale_extension_rules.md` committed (`b4c0669`), with the runner and the session files of parts E1 to E3 |
| 07:03:45 | first request of the extension (E1, `gemma-4-26b-a4b-it`) |
| 07:05:43 | addendum 1 committed (`2af0f60`): part E4, copy share, with its 24 cases |
| 07:09:32 | E1 complete (108 requests, all answered) |
| 07:14:18, 07:16:51 | E2 complete for Gemma and for Gemma-26B (36 requests each) |
| 07:17 | E3 starts for GLM-Flash with streamed responses; first HTTP 429 at 07:18 |
| 07:19:40 | addendum 2 committed (`553d74b`): E4 moves ahead of the streamed compilations of DeepSeek and Qwen |
| 07:28:44 | addendum 3 committed (`f2e3869`): part E5, the smallest further withdrawal |
| 07:31:15 | E3 complete for GLM-Flash (36 streamed compilations, one request rejected with HTTP 429 and issued again) |
| 07:31:24 to 07:51:02 | E4 for Gemma and Gemma-26B (96 requests each) |
| 07:51 to 07:58:46 | E5 for Gemma, answer only and working first (36 requests each) |
| 07:59:01 to 08:26:14 | E5 for GLM-Flash (36 streamed requests, 12 cut off at the output limit) |
| 08:26:29 to 09:17:59 | E3 for DeepSeek with streamed responses: 31 of its 36 compilations issued before the stop, the last at 09:14:10 |
| 08:39:37 | addendum 4 committed (`2ef703c`): part E6, the second model on the search task, with a stop of its own at 09:50 |
| 09:15:00 | stop for every part but E6. Qwen's streamed compilations were not issued: its runner started at 09:18:14 and sent nothing |
| 09:18:32 to 09:24:56 | E6 for Gemma-26B, answer only and working first (36 requests each). Last answer of the extension: 09:24:56 |

Every part was committed before its first call, and E6 started only after every other part had stopped. The streamed response format was checked against the sweep's own
decoder (`retrace/adaption_v6h.py`) and on a synthetic stream before the first streamed request.

### 8.2 What the extension showed

All numbers below are printed by `post_sweep/score_scale.py` (part E1), `post_sweep/score_scale_ext.py` (E2 to E4),
`post_sweep/score_withdrawal_task.py` (E5 and E6) and `paper_build/scale_paper_numbers.py`; the tables are in
`paper_build/tables/scale.md`, `scale_ext.md` and `scale_withdrawal.md`.

- **E1, second model (Gemma-26B).** It answers without a reasoning phase (median 49 output tokens for a direct answer at
  10 records) and is much weaker than Gemma: 102 of 288 decisions wrong from prose and 89 of 288 from the formal ledger,
  nearly all of them supported decisions that it withheld. The validator accepted 19 of its 36 declarations; 17 were
  identical to the reference graph, 18 gave fully correct decisions, and one declared an unavailable record available,
  which made one never-supported decision come out supported. The other 17 declarations were refused.
- **E2, visible working.** With the instruction to work first, Gemma got 0 of 282 decisions wrong on the main run's
  cases and Gemma-26B 4 of 288. On the copy-share cases: 0 of 230 and 8 of 240. Every output ended in exactly one
  answer object, at the end of the output, and none came near the output limit.
- **E3, streamed compilations.** All 36 of GLM-Flash's compilations arrived and all were identical to the reference
  graph (31 of 36 in the main run). For DeepSeek streaming changed little: 31 of its 36 compilations were issued before the stop; 25 spent the whole output limit of 32,768 tokens on reasoning and returned no text, one was refused by the validator (case `scale-S-10`: a route of a claim was not a list of identifiers), and five were accepted, all identical to the reference graph. Qwen's were not issued.
- **E4, copy share.** From the formal ledger the expectation written down in advance held for Gemma: unsupported
  decisions asserted 1 of 55 with no copies, 13 of 60 with 40 percent, 23 of 60 with 80 percent, all 23 copy-mediated.
  From prose it failed: 10 of 49, 8 of 56, 2 of 57, with more withheld decisions instead (10 of 61, 14 of 54, 25 of 53).
- **E5, the smallest further withdrawal.** Gemma answering alone: a valid set for 85 of 128 supported decisions, a
  smallest one for 38. With working first: valid 113 of 121, smallest 88; every set of a case smallest in 12, 6 and 2
  cases at 10, 20 and 40 records. Searching its own accepted declarations, with no call: smallest for all 122 decisions
  of its 33 accepted declarations. GLM-Flash, which reasons before it answers: 12 of 36 answers cut off at its output limit of 32,768 tokens; in the other 24, valid for all 81 supported decisions and smallest for 74; every set smallest in 20 cases. Searching its 31 accepted declarations: smallest for all 103. No valid set named by a model was smaller than the reference size, so the reference minimum was never undercut. Every valid but oversized set for a one-record decision (41, 25 and 7 for the three model runs) contained a record that would have sufficed alone: the models pad their sets; they do not miss the target. The paper says so and does not present this as a combinatorial failure.
- **E6, the second model on the search task.** Gemma-26B answering alone: a valid set for 44 of 128 supported decisions,
  a smallest one for 16, the empty set for only 30 of the 160 decisions without support, and no case with every set
  smallest. With working first: 29 usable answers (7 ran into the output limit of 8,192 tokens); valid 84 of 97,
  smallest 64; every set smallest in 5, 4 and 2 cases at 10, 20 and 40 records (of 12, 8 and 9 usable). All 22 and 18
  oversized sets for one-record decisions were padded. Search in its 19 accepted declarations: smallest for all 54
  supported decisions, and a set for one decision without support (the misread declaration). Both expectations written
  in addendum 4 before the calls held: working first gave more smallest sets than answering alone, and each gave a
  smaller share than the search in its accepted declarations. Against the search for this model: it covers 19 of the 36
  cases, where the model's own working gave 29 usable answers.
- Accepted declarations in the scaling run and its extension: 176, of which 174 are identical to the reference graph and
  175 give fully correct decisions (printed at the end of `paper_build/tables/scale_numbers.txt`). The two that are not
  identical are both Gemma-26B's, and one of those is the misread declaration.
- Requests and cost of the extension (`paper_build/tables/scale_ext_requests.txt`): 620 requests (Gemma 204, Gemma-26B 312, GLM-Flash 73, DeepSeek 31), every one with an answer record; 1 rejected with HTTP 429 and issued again; 7 failed with HTTP 504, all Gemma's; 44 cut off at the output limit (25 DeepSeek, 12 GLM-Flash, 7 Gemma-26B). Reservation 26.29 credits of at most 80; observed token cost 0.80 credits. First request 07:03:45, last answer 09:24:56 CET. With the main run (449 requests, 0.66 credits): 1,069 requests and about 1.46 credits of observed token cost.

### 8.3 What this does to the paper's claim

v2 said that compilation raised accuracy for the one model without a reasoning phase and that visible working was
untested. The control was then run, and it removes the errors as well (Gemma 0 of 282 decisions wrong, Gemma-26B 4 of
288). v3 therefore says that the errors come from answering without working, that any written-out structure removes
them, and that the declaration's advantage is that it can be refused and recomputed, not that it is more accurate. The
second model also produced the first accepted declaration that was wrong about its source (one record's availability),
which is the limit the paper has stated since the first draft. Both findings are in the abstract or Section 4.5.

### 8.4 The second review round, item by item

| Item | Holds on this copy? | What was done |
|---|---|---|
| 1. Long documents, direct against declaration | Yes: `long_context_check.py` passes here and prints the reviewer's table (7/4/1, 7/0/5, 1/9/2, 7/0/5; 46, 33, 36, 33 of 58) | The comparison was already in Appendix H from this session's own script. Added from the reviewer's check: per-decision counts, the kinds of refusal, the one admitted declaration with four of eight readings, the frozen bare-JSON endpoint being 0 of 12, and the fence sensitivity (3 and 2 more would be admitted, all exact). It is not in the abstract, because the scaling run and its controls answer the same question with prespecified cases |
| 2. Say what the checks did | Yes: 86 + 4 + 29 + 181 = 300; 139 bare | Abstract and Section 4.1 now open with "failed closed" and give the scope; Section 5 says that the engine checks a declaration's form and consequences, not its truth |
| 3. Link to the artifact | Needs the author | Not done: there is no share link yet |
| 4. Screenshot of the tool | Yes: header counts (78, 20, 79, 2) and the witness (decision `xfde4c8cb2`, k = 1, withdraw `x835e98113`) agree with slot `v6i::deepseek-v4-flash::ECO-01::refuter` | Figure G2 in Appendix G, pointed to from Section 4.2 |
| 5. Proposition B.4 | Yes: `check_clarification_against_engine.py` passes here with the reviewer's counts (3,000 instances, 1,803 and 1,197, no mismatch); the statement matches `retrace/workbench_v6h.py:28-67` (positive integer costs, at most five questions and 32 candidates) | Proposition, proof and remarks in Appendix B; "(Proposition B.4)" in Section 2; reference 16 (Hyafil and Rivest 1976) checked through Crossref |
| 6. End with what comes next | Yes | One sentence in Section 5; the paragraph on foundations in Section 1 is shorter, with all seven references kept |
| 7. "matched on every one" | Yes: GLM-5.3-Flash and Qwen each have one answer whose support fields match and whose state label differs (case `V6H-frontier-v6c-03-04`, decision `KFBB7VEC`); Gemma has three of the same kind | Section 4.4 says "support verdict" and names the two answers; Appendix G explains |
| 7. Seven of 30 | Yes | One sentence in Section 4.2 |
| 7. Page with two lines of references | Changed by the two new references | |
| 7. glm-53-flash and GLM-5.3-Flash | Yes: the sweep's own price table lists `glm-53-flash` as the alias of `glm-5.3-flash` | Appendix G says so once |
| 7. Zhou et al., EMNLP 2026 | Yes: title, authors and pages read on the ACL Anthology page | Reference 17, cited with 11 and 12 |
| 8. For the author | | Title, tracks and the share link are still the author's |

### 8.5 Other changes from v2 to v3

- The design table is Table A1 in Appendix A; the result tables are Tables 1 and 2. This freed about seventeen lines.
- The paragraph on assisted and oracle arms moved from Section 4.3 to Appendix D unchanged.
- Section 4.5 is rewritten in four paragraphs; Figure 2 has a fifth panel and two kinds of marker; Table H1 has the rows
  of the extension; Table H2 gives the copy-share part and Table H3 the search task.
- The abstract is new (249 words as the build counts them); contributions 2 and 3 are reworded. Its sentence on the
  refuter said "75 of 150 deficient cases"; the unit is slots (30 cases, five models), and it now says so.
- Two of Astra's sentences lost a few words to free two lines on page 6, so that Section 4.4 starts there and the main
  text keeps to eight pages: "Admitted outer fences are permitted for that endpoint." ends after "permitted" (the
  sentence before it names the endpoint), and "Appendix D gives the metric boundaries." became "(Appendix D)".
- Appendix B: the heading of the setting now reads "Setting for Propositions B.1 to B.3". Appendix F: the third session
  proposed four properties, the second ran the scaling run and its extension, and one sentence reports the rerun of the
  supplement in a fresh extraction. Appendix G: the tests of Propositions B.1 to B.4 were rerun.
- "Code and data" says that the supplement was rerun in a fresh extraction of the release archive.
- `paper_build/check_paper_numbers.py` builds 19 phrases of the abstract and Section 4.5 from the score files and looks
  for each in the built Word file; all 19 are found in the final build. `scan` of the built file for leftover markers
  and for the credential pattern: none.

### 8.6 Two checks added while the last runs were in flight

**The supplement, rerun in a fresh extraction of the release archive.** Until now the supplement had only been run
inside the working copy. The release archive (362,879,791 bytes) was extracted into an empty folder, the supplement
was unpacked into it, and the scripts of its README were run in the README's order.

- First attempt: `rerun_frozen_scorer.py` stopped at once. The project's frozen scorer checks three historical budget
  lock files that the execution freeze lists; the working copy has them, the archive carries them only under archived
  names (`provenance/frozen-locks/...`), and the scorer accepts exactly those names as aliases
  (`scripts/score_frontier_v6n.py`, `ALIASES`). My script did not pass them. Six later scripts read its output and
  failed with it. So the supplement, as built for v1 and v2, could not be rerun from the archive alone.
- Fix: the script passes the aliases when a lock is absent, as the project's own release verifier does, sets the one
  evidence field that names the aliases equal before it compares, and records that it did so. Nothing else changed.
- Second attempt, from the as-extracted state: every script ended with exit code 0. The frozen scorer (223 seconds)
  reproduced `score.json`, `score-audits.json` and the three journal views exactly (1,703 requests, 1,701 responses,
  1,800 slot outcomes).
- Final run, on the supplement as built at 09:27 with all data in (SHA-256 `d99e3ba78a32c91d09e362fd4df26c4ef82185383bf25c4bff67338a512a1159`,
  157 entries), again from the as-extracted state: all 22 scripts ended with exit code 0 and the frozen scorer again
  reproduced the five saved files exactly. Of the 114 result files, tables and journals that the supplement unpacks, 113
  were byte for byte unchanged after the rerun; the one that changed is `post_sweep/out/sweep_reproduction.json`, the
  record of the rerun (its duration and the note on the archived lock names). The printed output of
  `scale_error_paths.py` and `scale_paper_numbers.py` equalled the shipped `scale_error_paths.txt` and
  `scale_numbers.txt`. The supplement that ships differs from the tested one only in this report, which no script reads.

**The reference of the search task, recomputed with the project's own engine.** The addendum fixed the independent
evaluator as the support function for the reference and for scoring. `post_sweep/check_withdrawal_reference.py`
repeats both with `retrace.core.analyze`: the smallest size by exhaustive search for all 288 decisions, the 128
reference example sets, and every decision state after every set that a model named. They agree on all 288 sizes, all
128 example sets leave no support in the engine, and after the 547 sets named in the 160 usable answers the two give the
same state for all 4,532 decisions. It changes no score; `paper_build/refresh_scale.ps1` now stops if it finds a difference.

### 8.7 Not checked

- Whether the result of E5 and E6 holds for cases larger than 40 records, for other prompts, or for stronger models.
- The visible-working prompt and the search prompt were each tried in one wording.
- A second run at temperature 0 was not made, so run-to-run variation at the provider is not measured.
- Qwen's streamed compilations were not issued and five of DeepSeek's were not; the stop came first.
- Seven of Gemma-26B's answers with working ran into the output limit of 8,192 tokens. Whether a higher limit would
  have let them finish, and what they would have said, is not known.
- The unit tests and the workbench server, as before.

## 9. After the author read v3: a second run, 80-record cases, and paper v4 (16 November, from 10:15)

At about 10:15 the author read v3 and a list of its weaknesses and asked for work on them. Two could be tested today:
every request had been issued once, and the cases stopped at 40 records. The result is `paper_build/RETRACE_v4.pdf`.
`RETRACE_v3.pdf` (commit `3ec08da`) is unchanged.

### 9.1 What was run

`prereg/scale_extension_addendum_5.md` was committed at 10:24:09 (`8a3c1d9`); the first request went out at 10:24:10.
Part E8: twelve cases with 80 records for both Gemma models, in the three first-day conditions, with working shown
first and on the search task, all streamed. Part E7: the main run's 108 requests a second time for both Gemma models.
Stop for both parts: 11:15 CET. One request of part E8 was rejected with HTTP 429 and issued again.

### 9.2 What the 80-record cases showed (part E8)

For `gemma-4-31b-it`, against the four expectations written down before the calls:

1. Answering alone from prose: fully correct in 0 of 12 cases (expected: at most 1), 54 of 144 decisions wrong.
2. Working shown first: 119 of 120 decisions right in ten answers (expected: at least 95 percent); two answers ran into
   the output limit of 8,192 tokens.
3. Accepted declarations identical to the reference graph: **failed in one case.** Nine of twelve were accepted and all
   nine gave fully correct decisions, but one (`scale-XL-12`) marked the four withdrawn records as never available and
   one of them, a copy, as an original record. The decisions after the withdrawal are unchanged; the graph is not the
   one the source describes. Two declarations were refused (evidence identifiers did not match the task) and one ran
   into the output limit.
4. Search task: with working first, a smallest set for 21 of 62 supported decisions in eight usable answers (34 percent;
   expected: below 29 of 53), four answers cut off; answering alone 6 of 93. The search in its nine accepted
   declarations gave a smallest set for all 67 supported decisions. Over the four sizes the share with working is 100,
   76, 55 and 34 percent, and the search is at 100 percent wherever a declaration was accepted.

For `gemma-4-26b-a4b-it` no route held at this size. Answering alone: fully correct in no case, 76 of 144 decisions wrong
from the ledger and 78 of 132 from prose. Working shown first: fully correct in 5 of 11 usable answers, 20 of 132
decisions wrong, all supported decisions that it withheld (4 of 288 at 10 to 40 records). Compiled: none of twelve
declarations accepted (seven refused, five cut off at the output limit). Search task: a smallest set for 6 of 93 supported
decisions alone and 8 of 64 with working (four answers cut off); nothing to search. The paper says so in Section 4.5 and
in Appendix H.

### 9.3 What the second run showed (part E7)

Both models, 108 requests each, same sessions file and settings as the first run.

- `gemma-4-31b-it`: from the ledger all 288 decisions the same; from prose 3 of 246 decisions differ, in one answer (fully
  correct cases 7, 6 and 1 against 7, 7 and 1; 38 of 264 decisions wrong against 41 of 270); 33 declarations accepted in
  each run, 31 for the same cases, all 33 of the second run identical to the reference. Five requests failed with HTTP 504.
- `gemma-4-26b-a4b-it`: 283 of 288 decisions the same from the ledger and 283 of 288 from prose (86 and 103 wrong
  against 89 and 102); 17 declarations accepted against 19, 14 for the same cases. The declaration that was wrong in the
  first run (`scale-S-02`) was right in the second; one accepted only in the second run (`scale-M-10`) gave two unsafe
  decisions.
- Over both models 14 of 1,456 decisions in answers usable in both runs differ. Direct answers and Gemma's compilations
  repeat; which of Gemma-26B's declarations pass the validator does not repeat as well.
- All accepted declarations of the scaling run and its extension: 235, of which 230 identical to the reference graph and
  233 fully correct. The five that are not identical (`scale-S-02` and `scale-S-09` in E1, `scale-M-10` and `scale-S-09` in
  E7, `scale-XL-12` in E8) make one kind of mistake: withdrawn records marked as never available, never-available
  records marked as available, or both. Two of the five give unsafe decisions (one and two). The validator cannot see
  this, and the paper says so in Section 5 and Appendices E and H.
- Requests of the whole extension after these parts: 981, observed token cost about 1.06 credits; last answer 11:11:21.

### 9.4 What changed in the paper from v3 to v4

- Page 1: "Track 2 (primary); Tracks 1 and 3" (the author's decision).
- Section 3: the paragraph on the interrupted segments is five lines instead of eight, with the same statements; two
  sentences elsewhere lost a few words. All of this is page budget.
- Section 4.5: the 80-record results in three places (answering alone, working first, the search with its size trend),
  the second declaration that misdescribed its source, and one clause on the second run (14 of 1,456 decisions changed). The clause on DeepSeek's streamed compilations
  moved out of the main text; it is in Appendix H.
- Section 5: "two accepted declarations misdescribed their source"; the next step no longer lists larger cases.
- Appendix H: paragraphs on parts E7 and E8, Tables H4 and H5, the extension paragraph, the request totals.
- `paper_build/check_paper_numbers.py` checks the new sentences against the score files as well.
