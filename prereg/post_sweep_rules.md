# RETRACE post-sweep rules (pre-registration of the Claude Code session's analyses)

Written on Sunday 15 November 2026, about 23:00 CET, by the Claude Code session (Fable 5.2) working in a file copy of the
project. It fixes, before any outcome of the 1,800-slot sweep was opened by this session, how the session will recompute the
sweep's numbers and which additional analyses it will run. It is a local, hashed file, not an external registration.

Signature status: the author pre-authorised this file unread before going to sleep ("I sign the pre-registration as you draft
it: hash it, commit it and continue without stopping", 15 November, about 22:55 CET). He signs or amends it in the morning.
Anything computed before an amendment is labelled that way in the paper.

## 1. What had been seen when this was written

Seen by the session:
- Status counts in Astra's log and the user's messages: 1,245 outcomes recorded and one request in flight at the crash; 1,246
  carried and 554 left; 24 new outcomes and one unanswered request before the second stop; 1,271 carried and 529 left; then
  1,301, 1,371 and 1,676 of 1,800; then "all 1,800 slots are accounted for". Conservative credit totals 218.05, 219.86 and
  224.48. "All five primary models have returned completed responses"; no rate-limit error; truncated and failed responses kept.
- Operational counts in `research/frontier-v6n-recovery-protocol.txt` (1,192 logged requests, 1,190 recorded responses) and the
  header fields of the two freeze files.
- The sweep's design, protocol and report plan (`data/frontier-v6i-design.json`, `research/frontier-v6i-protocol.md`,
  `research/frontier-v6i-report-plan.md`), the gold corpus (`data/frontier-v6h-corpus.json`) and the engine and scorer code.
  None of these contains an outcome of the 1,800 slots.
- The 24-case prose experiment of Friday 13 November: its table and raw records, recomputed (`paper_build/tables/prose24.md`),
  and the Friday pilot results as described in the handoffs.
- Names, sizes, timestamps and SHA-256 hashes of outcome files. Not their contents.

Not seen: any per-slot outcome, grade, accuracy figure or table of the 1,800-slot sweep; Astra's draft text; the interim
studies. The paths kept sealed are listed in `paper_build/STATUS.md`. Two read-only helper agents audited code and protocol
files; they were told not to open outcome files and to report no outcome numbers, and their reports contain none. A third
helper is summarising older review documents from 13 to 15 November; its report had not arrived when this file was hashed.

## 2. Data cut and stop rule

- No model call is made. Nothing here needs one.
- Data cut: the records as copied into the working copy by the user at 22:31 on 15 November (hashes in
  `post_sweep/baseline_hashes.txt`). One later one-way copy from the original folder is authorised; if any record differs
  after it, both versions are reported.
- The sweep's own stop rule was an admission cutoff (03:55 UTC in the original protocol, 06:56 UTC for the last recovery
  launch). It is recorded, not applied, if all 1,800 slots finished before it.

## 3. The project's frozen policy, adopted unchanged

From `research/frontier-v6i-protocol.md` (written before the first slot) and `research/frontier-v6n-recovery-protocol.txt`:
- Outage rule: a provider failure or 180-second timeout finalises that slot as failed; all 1,800 planned slots stay in their
  declared denominators; first-attempt pipeline outcomes are primary.
- Retry policy: only an explicit HTTP 429 is retried, at most twice. No retry of an invalid answer, truncation or timeout.
- Host-interruption rule: the two requests that were in flight when the host stopped are never reissued and score zero.
- Inference gate: after a global interruption the frozen evaluator reports a diagnostic with its 21 tests left null; the
  recovery protocol declares a separate "recovery-closure sensitivity" that recomputes them if the recovery closes. The paper
  reports the 21 tests only as that amended sensitivity.

## 4. Recomputation of the sweep

R1. Rebuild the 1,800-slot table from the launch journals (i, j, k, m, n and the two overlay rows) with a script written
    here, and compare it slot by slot with the project's merged table.
R2. Accounting per model and arm: scheduled, issued, completed, truncated, operational failures by error class, dependency
    skips, host interruptions.
R3. Run the project's frozen evaluator in process on the raw records, write the result under `post_sweep/out/`, and compare
    it with the project's saved score.
R4. From the per-slot grades, recompute with independent code every table cell and the 21 exact McNemar tests with Holm
    correction.
R5. Regrade the strict-IR arm independently: two graphs are the same if evidence rows match and every claim's positive and
    negative expressions are equal as Boolean functions (by truth table); a family is exact if its set of distinct graphs
    equals the authored set.
"Agree" means: integer counts identical; rates equal at the printed precision; p-values within 1e-9; seeded intervals
identical when the frozen evaluator is rerun. Every disagreement is reported with both numbers and the reason.

## 5. Missing outcomes

Two codings are always shown.
- Frozen (primary): every slot without an eligible completed answer counts as a failure.
- Sensitivity: an invalid or truncated answer is a model failure. A timeout, an HTTP or transport error, a slot not issued
  because its producer failed operationally, and the two host interruptions are *missing*. For n scheduled, c correct and o
  missing, the range is [c/n, (c+o)/n]. The two host interruptions get their own row.
Decision rules per model and arm, with q = o/n: q <= 5%: report the rate with its range. 5% < q <= 20%: the range goes in the
headline table, with the mean of per-case rates among observed slots beside it. q > 20%: that model's results for that arm go
to a diagnostic table and no cross-model statement uses them. If half or more of a model's missing slots fall in one family,
results are given per family and no cross-family statement is made for that model.

## 6. Additional zero-call analyses

Common definitions. For a case, the states are those named in `events.states` (initial, withdrawn, restored); excluded
evidence is computed as the scorer does. For a family of candidate graphs and a decision at a state, the class is ASSERT if
`box_supported`, WITHHOLD if not `diamond_supported`, SPLIT otherwise (`tiered_v6h.family_supervaluation`). Gold classes use
the authored family. A pair (decision, state) is *unsafe* if the method says ASSERT and gold does not, *over-cautious* if gold
says ASSERT and the method does not.

A1. Pipeline table, strict-IR arm, first attempts. Each slot is *missing* (section 5), *rejected* (output not admitted by
    the unchanged compiler, or admitted with a registry gap: no verdict is given), or *admitted*. For admitted slots every
    pair is classed against gold. Reported per model: slots by status; unsafe and over-cautious pairs over all scheduled pairs
    (a rejected or missing slot asserts nothing) and over admitted slots only.
A2. Direct answer against pipeline, on the 12 cases of the commitment arm. The model's own answer in each commitment phase
    is classed the same way from its `box_supported` and `diamond_supported` fields and compared with the pipeline class from
    that model's strict-IR slot at the same state. Paired counts per model; no significance test.
A3. Copy-link capture. For a family, a copy link (item, parent) is *certain* if present in every candidate and *possible* if
    present in some. Recall = authored-certain links that are certain in the model's family; precision = model-certain links
    that are authored-possible. Kind confusion (root, copy, unknown) is tabulated. For each missed link, the parent is withdrawn
    alone on top of the initial state; the miss is *consequential* if the model's family then asserts a decision the authored
    family does not.
A4. Four baselines, on authored families (mechanism checks, true by construction) and on admitted model families:
    (i) status filter without lineage: all parent links removed, copies become roots;
    (ii) withdraw everything downstream: a decision is withheld if any evidence item in its dependency closure is excluded;
    (iii) single reading: only the first candidate is evaluated;
    (iv) naive gate: an argument is accepted unless one of its attackers is labelled IN.
    Each is compared with the engine on the same family and with gold, by unsafe and over-cautious pairs.
A5. Static checks that this IR can express: multi-parent copies; forks that change no class at any case state; candidate
    count against the authored count; capture of negative warrants; alternative routes that share an ancestor. The other
    checks proposed in the handoff (priorities, strict rules, output scope, attacks on sources) do not apply to this engine
    and are reported as not applicable.
A6. Casebook of the 12 bridge cases: source, structure, which baselines change a verdict, and each model's result. Descriptive.
A7. Engine checks on authored and admitted families: verdicts at the state reached by applying the case's events in order
    equal verdicts at the declared state; two evaluations are identical; and the count of OUT labels and of accepted
    arguments that are attacked, to test whether acceptance reduces to "unattacked" in this fragment.

## 7. Statistics

Counts are always given with their denominators. Intervals for the analyses of section 6 are percentile intervals from 5,000
resamples of cases within the seven strata (F1 to F6 and the bridge cases), seed 20261116. They describe this authored case
set. No p-value is computed for section 6. The 21 pre-specified tests are reported only as in section 3.

## 8. Labels

- Pre-specified by the project before the sweep: the schedule, grading, the 21 tests, the bootstrap.
- Declared by the project before the recovery calls: the recovery-closure sensitivity.
- Fixed in this file before this session opened any sweep outcome, but designed after the sweep started and with knowledge
  of section 1: sections 4 to 7. The paper calls them post hoc.
- Exploratory: anything not listed here, including the casebook's wording and any breakdown added later.

## 9. Not done without the author's approval

Any provider call (the 24-case protocol on further models, a compacted-memory arm, a missed-copy net that needs calls); a
video; an HTML replay; any submission.
