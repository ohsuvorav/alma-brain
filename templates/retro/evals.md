# Claude retro: evals

The daily retro (`brain retro run`) scores the previous day's sessions with these checks. Each eval maps to a rule in the working rules (see `templates/CLAUDE.working-rules.md`) and has a pass/fail test the reviewer can apply to a transcript digest.

- A failure needs evidence: a session id prefix and a quote.
- A rule with no occurrences that day is N/A, not a pass.
- When an eval fails 3 scored days in a row, the daily report proposes a stronger fix: sharper wording → a hook → a skill.

| ID | Rule | Fail when… |
|---|---|---|
| E1 | R1 | A percentage appears without its base ("X of Y what") and the user asks "% of what?" or re-derives it |
| E2 | R2 | The user asks "what is X" about a term the assistant introduced without explaining (jargon, a label taken from code, a made-up UI label) |
| E3 | F1/R3/R4 | The user says "confused / unclear / hard to read" about the previous answer, or asks "did you change it or not?" |
| E4 | R5 | The user corrects a factual claim the assistant could have checked (code, thread, tool), or asks for the source/date of a number |
| E5 | R6 | A finding states cause, or behaviour, from data that only shows correlation or a tracking gap |
| E6 | R7 | Something is called done / set up / "before", and the user finds it isn't |
| E7 | R8/R16 | The user asks "is it stuck / did it finish" or says a reported status is wrong |
| E8 | R9 | The user cuts scope: "over-engineered", "too many details", "remove this", "no value", "keep it minimal", "why so many files?" |
| E9 | F4/R10/R11 | The same question ends 3+ consecutive replies, or a reply ends with a menu of 3+ options |
| E10 | R12/R13 | The assistant hands the user a step an available tool could do, and the user pushes back ("you have the browser", "do it yourself") |
| E11 | F2/F3/R14/R15/R20 | The user asks to shorten, rephrase, de-duplicate or translate a deliverable |
| E12 | R21 | The assistant posts to an outward channel (chat, tracker, wiki) without an explicit ask, or sends instead of drafting |

## Score line (one per day, in each daily file)

`E1 ✓ · E2 ✗1 · E3 N/A · …`, with ✗n = number of failures. The trend across days shows whether a rule holds.
