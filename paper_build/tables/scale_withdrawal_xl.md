# Extension, part E8: the smallest further withdrawal at 80 records

Produced by `post_sweep/score_withdrawal_task.py`. Rules: `prereg/scale_extension_addendum_5.md`. Per model, route and case size: usable answers of 12; of the supported decisions in usable answers, sets that are valid and sets that are smallest, for decisions whose smallest set has one record and for those that need more.

| Model | Route | Size | Usable answers | One record needed: valid / smallest of answered | More needed: valid / smallest of answered | No support: empty set given | Cases with every set smallest |
|---|---|---|---|---|---|---|---|
| Gemma-26B | Named by the model, answer only | XL | 12 of 12 | 12 / 6 of 71 | 2 / 0 of 22 | 5 of 51 | 0 |
| Gemma-26B | Named by the model, answer only | all | 12 of 12 | 12 / 6 of 71 | 2 / 0 of 22 | 5 of 51 | 0 |
| Gemma | Named by the model, answer only | XL | 12 of 12 | 23 / 4 of 71 | 2 / 2 of 22 | 32 of 51 | 0 |
| Gemma | Named by the model, answer only | all | 12 of 12 | 23 / 4 of 71 | 2 / 2 of 22 | 32 of 51 | 0 |
| Gemma-26B | Named by the model, working first | XL | 8 of 12 | 21 / 6 of 51 | 3 / 2 of 13 | 32 of 32 | 0 |
| Gemma-26B | Named by the model, working first | all | 8 of 12 | 21 / 6 of 51 | 3 / 2 of 13 | 32 of 32 | 0 |
| Gemma | Named by the model, working first | XL | 8 of 12 | 42 / 19 of 46 | 3 / 2 of 16 | 34 of 34 | 0 |
| Gemma | Named by the model, working first | all | 8 of 12 | 42 / 19 of 46 | 3 / 2 of 16 | 34 of 34 | 0 |
| Gemma | Searched in the model's accepted declaration (no call) | XL | 9 of 12 | 52 / 52 of 52 | 15 / 15 of 15 | 41 of 41 | 9 |
| Gemma | Searched in the model's accepted declaration (no call) | all | 9 of 12 | 52 / 52 of 52 | 15 / 15 of 15 | 41 of 41 | 9 |
| Gemma-26B | Searched in the model's accepted declaration (no call) | XL | 0 of 12 | 0 / 0 of 0 | 0 / 0 of 0 | 0 of 0 | 0 |
| Gemma-26B | Searched in the model's accepted declaration (no call) | all | 0 of 12 | 0 / 0 of 0 | 0 / 0 of 0 | 0 of 0 | 0 |

Requests of this part: {"sent": 49, "http_429": 1, "http_504": 0, "cost_x10000": 639}

