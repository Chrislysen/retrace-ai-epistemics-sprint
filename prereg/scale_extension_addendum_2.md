# Addendum 2 to the rules for the extension of the scaling run: order of the remaining parts

Written Monday 16 November 2026, about 07:20 CET, by the second AI session (Claude) with AI assistance.

## What happened

Parts E1 and E2 are complete and scored. Part E3 started for `glm-53-flash` at 07:17 with streamed responses; the first
streamed answer arrived complete after 22 seconds. At 07:18 the provider rejected one streamed request with HTTP 429, and
the runner went down to one request at a time, as the rules say. With one request at a time the streamed compilations of
the three reasoning models take longer than the time left before the stop at 09:15 CET.

What had been seen of the parts affected by this addendum: one streamed GLM-Flash answer (status, token count and
duration, not its content). No answer of part E4 exists.

## Change

The order of the remaining parts becomes: E3 for `glm-53-flash` (running); E4 for both models; E3 for
`deepseek-v4-flash`; E3 for `qwen3.8-27b`. Part E4 moves ahead because its requests are short and it tests a question
fixed in advance; the streamed compilations are long, and whichever of them is not issued by 09:15 CET is reported as not
issued. Nothing else changes: slots, prompts, settings, scoring, ceilings and the stop time are as before.
