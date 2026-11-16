# Casebook: the twelve bridge cases

Produced by `post_sweep/zero_call_analyses.py`. Post hoc analyses fixed in `prereg/post_sweep_rules.md`; no model call.
Each case wraps excerpts of a real published source in authored administrative records and rules.

| Case | Title | Docs | Roots / copies | Authored classes at initial, withdrawn, restored | Baselines that change a verdict | deepseek-v4-flash | gemma-4-31b-it | glm-5.2 | glm-5.3-flash | qwen3.8-27b |
|---|---|---|---|---|---|---|---|---|---|---|
| ECO-01 | VITALITY I: separately licensed direction and significance summaries | 8 | 1 / 2 | ASSERT:2; WITHHOLD:2; ASSERT:1,WITHHOLD:1 | no_lineage | admitted_bare | admitted_fenced | missing | admitted_bare | admitted_bare |
| ECO-02 | VITALITY I: reconstruction denominator and an unissued replication memo | 9 | 2 / 2 | ASSERT:1,WITHHOLD:1; WITHHOLD:2; WITHHOLD:2 | none | admitted_bare | admitted_fenced | missing | missing | admitted_bare |
| ECO-03 | VITALITY II: a published plan and no completed patient-burden result | 8 | 2 / 1 | ASSERT:1,WITHHOLD:1; WITHHOLD:2; ASSERT:1,WITHHOLD:1 | no_lineage | admitted_bare | admitted_fenced | admitted_bare | admitted_bare | admitted_bare |
| ECO-04 | Cochrane IHCA: current-version citation versus historical audit | 10 | 3 / 0 | ASSERT:2; WITHHOLD:2; ASSERT:1,WITHHOLD:1 | none | admitted_bare | admitted_fenced | admitted_fenced | admitted_bare | admitted_bare |
| ECO-05 | INSPECT-SR: preserve the replacement exception in a review card | 10 | 1 / 2 | ASSERT:2; WITHHOLD:2; ASSERT:1,WITHHOLD:1 | none | missing | admitted_fenced | admitted_bare | admitted_bare | admitted_bare |
| ECO-06 | Citation persistence: counted citations and their possible purposes | 8 | 1 / 2 | ASSERT:2; WITHHOLD:2; ASSERT:1,WITHHOLD:1 | none | admitted_bare | admitted_fenced | admitted_bare | admitted_bare | admitted_bare |
| ECO-07 | SciFact49: two alternative excerpts from the same abstract | 8 | 1 / 2 | ASSERT:2; WITHHOLD:2; ASSERT:1,WITHHOLD:1 | no_lineage, withdraw_downstream | admitted_bare | admitted_fenced | missing | admitted_bare | admitted_bare |
| ECO-08 | SciFact452: retain the source of each variation excerpt | 10 | 2 / 2 | ASSERT:2; WITHHOLD:2; ASSERT:1,WITHHOLD:1 | no_lineage, withdraw_downstream | admitted_bare | admitted_fenced | missing | admitted_bare | missing |
| ECO-09 | HoVer: two building-location excerpts without current-geography assumptions | 10 | 2 / 2 | ASSERT:2; WITHHOLD:2; WITHHOLD:2 | none | admitted_bare | rejected | missing | admitted_bare | admitted_bare |
| ECO-10 | HoVer: a redevelopment identity bridge and two locations | 11 | 3 / 1 | ASSERT:2; WITHHOLD:2; ASSERT:1,WITHHOLD:1 | no_lineage | admitted_bare | admitted_fenced | admitted_bare | admitted_bare | admitted_bare |
| ECO-11 | AVeriTeC136: an as-of claim date and a narrower generation measure | 9 | 2 / 1 | ASSERT:1,WITHHOLD:1; WITHHOLD:2; WITHHOLD:2 | none | missing | admitted_fenced | missing | admitted_bare | missing |
| ECO-12 | AVeriTeC283: a dated scenario model and separately discussed pumped hydro | 10 | 2 / 2 | ASSERT:1,WITHHOLD:1; WITHHOLD:2; WITHHOLD:2 | none | admitted_bare | admitted_fenced | admitted_bare | missing | admitted_bare |
