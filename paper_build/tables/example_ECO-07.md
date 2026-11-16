# Worked example: ECO-07, SciFact49: two alternative excerpts from the same abstract

Produced by `post_sweep/example_case.py`. Classes: ASSERT (supported in every reading), SPLIT, WITHHOLD.

| State | Withdrawn records | Engine x0493558bc | Engine x3c5158cad | No lineage x0493558bc | No lineage x3c5158cad | Withdraw downstream x0493558bc | Withdraw downstream x3c5158cad |
|---|---|---|---|---|---|---|---|
| initial | none | ASSERT | ASSERT | ASSERT | ASSERT | ASSERT | ASSERT |
| withdrawn | x7123e83b8, x1bfc5bc10 | WITHHOLD | WITHHOLD | ASSERT | WITHHOLD | WITHHOLD | WITHHOLD |
| restored | x1bfc5bc10 | ASSERT | WITHHOLD | ASSERT | WITHHOLD | WITHHOLD | WITHHOLD |
