# RETRACE local source-review workbench

From the repository root, run:

```powershell
python -m retrace.server_v6d --port 8768
```

Open `http://127.0.0.1:8768`. This additive server does not replace the v5 or v6 servers. It uses the Python standard library and local RETRACE modules; there are no model calls, API keys, automatic saves or external dependencies. Export a bundle or analysis to keep a local copy.

The constructed demo has eight explicitly admitted interpretations. The current `LINEAGE` decision is disputed; answering its factual source question settles the current decision vector after one question, leaving four graphs. The unused decorative choice need not be resolved. The `RELEASE` decision is initially invariant-supported. Its smallest distinguishing withdrawal removes `A`, `B`, and `C`; breaking it in every interpretation requires four records. This is an artificial demonstration, not an observed model result.

1. Load the demo, or import a JSON bundle containing source documents, an optional typed registry, and an explicit `source_ir` in the `retrace.source-ir.v6d` citation-reference format.
2. Use **Prepare source spans & prompt** to prepare an exact source inventory for a human or external model. This exports the frozen `IR_V6E_INSTRUCTIONS`, including its generic example, against the same citation adapter. This action makes no inference request.
3. Review the proposed IR and analyze it. Source clauses show complete grouping, scope, conditions and linked source spans. An exact citation verifies its location, not the correctness of the interpretation.
4. Answer a relevant question only when you know the factual answer. Unknown retains the candidate family. Questions stop when the target decisions agree; the entire graph need not be identified.
5. Apply an explicit scenario witness or toggle document/passage exclusions. Original local eligibility, effective eligibility and inherited usability are displayed separately. Clearing one veto does not clear another.
6. Preview hypothetical eligibility changes or a separate counter-reading. These views do not alter the active source, state, answers or decision status. A graph can be unlicensed by the current declaration without the tool proving it false.

Editing source text, grouping, IR, clarification labels or any other declaration invalidates the old result. The interface hides stale analysis, and a new analysis starts with empty answers and exclusions. Backend clients can supply `expected_declaration_fingerprint` when reusing state; a mismatch is rejected. Exact source references also fail if their document, text or position changes.

## Bundle fields

Required: `source_documents` (`id`, `text`, optional `title`) and `source_ir`. Optional: `id`, `title`, `registry`, `documents` (explicit source document veto groups with `id`, `label`, `evidence_ids`), `clarifications`, `target_decisions`, `allowed_withdrawals`, `allowed_exposure_changes`. Other fields are rejected, including unverified model-result or reference labels.

Each clarification has `choice_id`, `label`, `true_option`, and positive integer `cost`. Its answer table is derived from compiled choice assignments, never supplied separately by a client. If omitted, all declared binary choices receive neutral reading-choice questions costing one unit. Labels remain supplied interpretations rather than verified source facts.

State contains `answers` (choice ID to true, false or null), `revoked_documents`, `revoked_passages`, and `scenario_withdrawals`. Document groups must name supplied source documents. The engine supports up to five binary choices and 32 branches, exact withdrawal witnesses over at most16 declared evidence variables, and exact hypothetical eligibility exposure over at most12 unlocked variables. Exposure requires common original local flags; unsupported or excessive scopes are reported unavailable, never truncated. Unknown ancestry withholds the whole executable family and all decision statuses.

The loopback endpoints are `/api/v6d/demo`, `/api/v6d/source`, `/api/v6d/analyze`, `/api/v6d/exposure-preview`, and `/api/v6d/refuter-preview`. POST requests carry `brief`, optional `state` and optional `expected_declaration_fingerprint`; the previews additionally carry `enable`/`withdraw` or `proposed_ir`. Requests are bounded, duplicate JSON fields are rejected, and cross-origin browser POSTs are rejected. The server performs no filesystem writes.

Known registry IDs must each have an explicit operational or nonoperational entity disposition. An omitted ID produces **Reference-Free Coverage Gap** and withholds the decision panel. This is an inventory warning, not a claim that an operational node or dependency was omitted. Declaring every ID does not establish semantic fidelity or source completeness. A cited, explicitly nonoperational identifier clears that identifier's inventory warning without certifying the interpretation.

The counter-reading preview also computes the exact effect of adding novel proposed graphs to the entire current family. It reports minimum-cardinality additional withdrawals that change unanimity to disagreement, with current and added per-graph outcomes. Existing vetoes and original inactive flags remain in force. No detected change means no change within the stated finite withdrawal scope; it does not prove semantic equivalence. Different operational inventories, unresolved structures, missing dispositions, or any answered Boolean clarification make this impact comparison unavailable. Unknown answers do not filter the family. Reset actual answers before comparing different choice structures; the tool never transfers them automatically. Neither the structural comparison nor the impact preview commits a proposal.

## Recorded outcomes

The catalog is separate from the constructed default demo. `/api/v6d/catalog` serves a small manifest, and `/api/v6d/catalog/<entry-id>` lazily serves only known entries whose path, size, hash, and source-bundle fingerprint match that manifest. Editing a loaded declaration removes its recorded-provenance match. Local hashes bind artifacts; they are not provider authentication.

`scripts/build_frontier_v6_catalog.py` takes the frozen 48-case source, 24 dossiers, and 4,560-slot **primary schedule view**, plus its response and request journal views. It publishes all 600 source-IR, refuter, and long-IR slots, including unissued, failed, truncated, abstaining, and missing outputs. The 80 regression slots in a combined 4,640-slot run and earlier canaries are not silently relabeled as primary outcomes. Feed the closure-generated primary views after the run closes; do not split or modify live journals. No actual catalog is created by tests.

The CLI requires `--responses`, `--freeze`, and a new `--output` directory; `--corpus`, `--dossiers`, and `--sessions` have current primary defaults. Supply every primary request view through `--requests`, then use **both** `--requests-complete --run-closed` only after closure. Without `--run-closed`, the manifest explicitly says `provisional_snapshot`, and every missing slot remains pending or uncertain. Any snapshot must use stable, hash-bound input files; changes during construction abort publication. The builder verifies the supplied freezes, source-span bindings and all schedule identities before writing, then publishes the manifest last. Existing output directories are never overwritten.

The server's default catalog directory is `results/catalog-v6`. Model/case/arm filters retain all statuses and show full scheduled denominators. Viewing raw or partial output never repairs it. Loading a formally admitted IR is an explicit action and starts a fresh unverified review; a refuter output is offered only as a nonmutating preview. Catalog entries contain public sources, registry, actual output and provenance, never hidden source-family gold, annotations, reference IR, or authored seed labels. Admission and inventory status are not accuracy scores.

Validation:

```powershell
python -m unittest tests.test_engine_v6d tests.test_frontier_v6_catalog tests.test_refuter_impact_v6 -v
node --check web/v6d/app.js
```

Tests include all32 branches, exact k-way minima, scalar eligibility enumeration, clarification stopping, stale source rejection, document/passage locks, separate refuter and exposure previews, unresolved ancestry, and HTTP admission. Successful formal checks do not establish source completeness, semantic entailment or real-world truth.
