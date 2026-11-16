# Extension, parts E5 and E6: the smallest further withdrawal

Produced by `post_sweep/score_withdrawal_task.py`. Rules: `prereg/scale_extension_addendum_3.md and _4.md`. Per model, route and case size: usable answers of 12; of the supported decisions in usable answers, sets that are valid and sets that are smallest, for decisions whose smallest set has one record and for those that need more.

| Model | Route | Size | Usable answers | One record needed: valid / smallest of answered | More needed: valid / smallest of answered | No support: empty set given | Cases with every set smallest |
|---|---|---|---|---|---|---|---|
| Gemma-26B | Named by the model, answer only | S | 12 of 12 | 13 / 8 of 27 | 1 / 1 of 3 | 16 of 42 | 0 |
| Gemma-26B | Named by the model, answer only | M | 12 of 12 | 13 / 2 of 34 | 1 / 0 of 4 | 9 of 58 | 0 |
| Gemma-26B | Named by the model, answer only | L | 12 of 12 | 11 / 5 of 42 | 5 / 0 of 18 | 5 of 60 | 0 |
| Gemma-26B | Named by the model, answer only | all | 36 of 36 | 37 / 15 of 103 | 7 / 1 of 25 | 30 of 160 | 0 |
| Gemma | Named by the model, answer only | S | 12 of 12 | 24 / 14 of 27 | 3 / 1 of 3 | 33 of 42 | 1 |
| Gemma | Named by the model, answer only | M | 12 of 12 | 23 / 9 of 34 | 2 / 1 of 4 | 49 of 58 | 0 |
| Gemma | Named by the model, answer only | L | 12 of 12 | 30 / 13 of 42 | 3 / 0 of 18 | 40 of 60 | 0 |
| Gemma | Named by the model, answer only | all | 36 of 36 | 77 / 36 of 103 | 8 / 2 of 25 | 122 of 160 | 1 |
| GLM-Flash | Named by the model, answer only | S | 11 of 12 | 25 / 20 of 25 | 3 / 3 of 3 | 38 of 38 | 9 |
| GLM-Flash | Named by the model, answer only | M | 5 of 12 | 13 / 12 of 13 | 3 / 3 of 3 | 24 of 24 | 4 |
| GLM-Flash | Named by the model, answer only | L | 8 of 12 | 28 / 27 of 28 | 9 / 9 of 9 | 43 of 43 | 7 |
| GLM-Flash | Named by the model, answer only | all | 24 of 36 | 66 / 59 of 66 | 15 / 15 of 15 | 105 of 105 | 20 |
| Gemma-26B | Named by the model, working first | S | 12 of 12 | 27 / 23 of 27 | 2 / 2 of 3 | 24 of 42 | 5 |
| Gemma-26B | Named by the model, working first | M | 8 of 12 | 20 / 18 of 23 | 2 / 2 of 2 | 39 of 39 | 4 |
| Gemma-26B | Named by the model, working first | L | 9 of 12 | 29 / 17 of 34 | 4 / 2 of 8 | 31 of 48 | 2 |
| Gemma-26B | Named by the model, working first | all | 29 of 36 | 76 / 58 of 84 | 8 / 6 of 13 | 94 of 129 | 11 |
| Gemma | Named by the model, working first | S | 12 of 12 | 27 / 27 of 27 | 3 / 3 of 3 | 42 of 42 | 12 |
| Gemma | Named by the model, working first | M | 12 of 12 | 33 / 25 of 34 | 4 / 4 of 4 | 58 of 58 | 6 |
| Gemma | Named by the model, working first | L | 11 of 12 | 37 / 20 of 38 | 9 / 9 of 15 | 57 of 57 | 2 |
| Gemma | Named by the model, working first | all | 35 of 36 | 97 / 72 of 99 | 16 / 16 of 22 | 157 of 157 | 20 |
| Gemma | Searched in the model's accepted declaration (no call) | S | 10 of 12 | 23 / 23 of 23 | 3 / 3 of 3 | 34 of 34 | 10 |
| Gemma | Searched in the model's accepted declaration (no call) | M | 11 of 12 | 33 / 33 of 33 | 3 / 3 of 3 | 52 of 52 | 11 |
| Gemma | Searched in the model's accepted declaration (no call) | L | 12 of 12 | 42 / 42 of 42 | 18 / 18 of 18 | 60 of 60 | 12 |
| Gemma | Searched in the model's accepted declaration (no call) | all | 33 of 36 | 98 / 98 of 98 | 24 / 24 of 24 | 146 of 146 | 33 |
| Gemma-26B | Searched in the model's accepted declaration (no call) | S | 11 of 12 | 25 / 25 of 25 | 3 / 3 of 3 | 37 of 38 | 10 |
| Gemma-26B | Searched in the model's accepted declaration (no call) | M | 5 of 12 | 14 / 14 of 14 | 1 / 1 of 1 | 25 of 25 | 5 |
| Gemma-26B | Searched in the model's accepted declaration (no call) | L | 3 of 12 | 8 / 8 of 8 | 3 / 3 of 3 | 19 of 19 | 3 |
| Gemma-26B | Searched in the model's accepted declaration (no call) | all | 19 of 36 | 47 / 47 of 47 | 7 / 7 of 7 | 81 of 82 | 18 |
| Qwen27B | Searched in the model's accepted declaration (no call) | S | 12 of 12 | 27 / 27 of 27 | 3 / 3 of 3 | 42 of 42 | 12 |
| Qwen27B | Searched in the model's accepted declaration (no call) | M | 9 of 12 | 27 / 27 of 27 | 4 / 4 of 4 | 41 of 41 | 9 |
| Qwen27B | Searched in the model's accepted declaration (no call) | L | 1 of 12 | 4 / 4 of 4 | 0 / 0 of 0 | 6 of 6 | 1 |
| Qwen27B | Searched in the model's accepted declaration (no call) | all | 22 of 36 | 58 / 58 of 58 | 7 / 7 of 7 | 89 of 89 | 22 |
| DeepSeek | Searched in the model's accepted declaration (no call) | S | 5 of 12 | 12 / 12 of 12 | 2 / 2 of 2 | 16 of 16 | 5 |
| DeepSeek | Searched in the model's accepted declaration (no call) | M | 0 of 12 | 0 / 0 of 0 | 0 / 0 of 0 | 0 of 0 | 0 |
| DeepSeek | Searched in the model's accepted declaration (no call) | L | 0 of 12 | 0 / 0 of 0 | 0 / 0 of 0 | 0 of 0 | 0 |
| DeepSeek | Searched in the model's accepted declaration (no call) | all | 5 of 36 | 12 / 12 of 12 | 2 / 2 of 2 | 16 of 16 | 5 |
| GLM-Flash | Searched in the model's accepted declaration (no call) | S | 11 of 12 | 23 / 23 of 23 | 3 / 3 of 3 | 40 of 40 | 11 |
| GLM-Flash | Searched in the model's accepted declaration (no call) | M | 11 of 12 | 31 / 31 of 31 | 3 / 3 of 3 | 54 of 54 | 11 |
| GLM-Flash | Searched in the model's accepted declaration (no call) | L | 9 of 12 | 30 / 30 of 30 | 13 / 13 of 13 | 47 of 47 | 9 |
| GLM-Flash | Searched in the model's accepted declaration (no call) | all | 31 of 36 | 84 / 84 of 84 | 19 / 19 of 19 | 141 of 141 | 31 |

Requests of this part: {"sent": 180, "http_429": 0, "http_504": 1, "cost_x10000": 3878}

