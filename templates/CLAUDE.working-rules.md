# Working rules (template)

Rules distilled from daily session retros (`brain retro run`); each one maps to a pass/fail check in `templates/retro/evals.md`. Copy this section into a brain's `CLAUDE.md` (shared rules) or `CLAUDE.local.md` (personal ones), then let the retro tune them: a rule that fails 3 scored days in a row gets sharper wording, then a hook, then a skill.

## Focus: what the reader sees first

- **F1. Lead with the answer.** The first line says what changed or what the answer is ("Changed X in Y", "No: Z"). Context follows only if it changes what the reader does.
- **F2. One thing once.** Don't restate what a title, table, list or screenshot already shows. No recap of the thread, no "as discussed".
- **F3. Short by default.** Message = what we do → impact → ask. Cut words that add no meaning; prefer concrete steps over prose.
- **F4. One ending.** End with at most one question or one recommended next step, never a menu.

## Clarity

- **R1. Every percentage names its base:** "X of Y (what)", e.g. "18 of 40 trial teams (45%)". Never a bare "%".
- **R2. Explain a term the first time it is used,** in plain words with a concrete example (p90, cohort, NRR…). This includes labels taken from code or invented for the UI. Prefer the everyday word.
- **R3. Comparisons, options and states go in a table.** Each chart or table gets one line on how to read it and what it means for us.
- **R4. When the user says they are confused, reset in three lines:** what exists today → what the problem is → the one next step. No new options.

## Verification

- **R5. Check before claiming.** Code or commits for "is it done", the latest thread over the spec for numbers and decisions, the live tool for "no access" / "no data". Give the source and date for every borrowed fact or number. Label anything unchecked as a guess.
- **R6. "Not tracked" ≠ "didn't happen", and correlation ≠ cause.** Say which one, and name survivorship when only survivors are counted.
- **R7. Before/after evidence comes from a real baseline.** Take the "before" from the unchanged code (`git stash`, the main branch, or production), never from the already-changed state, and state how each capture was made. "Done" or "set up" means checked end to end, the way the user will use it.
- **R8. Re-check subagent or background status before reporting it.**
- **R18. Name a data group by what the rule measures,** not by what we assume it means ("opened the setup guide, install method unknown", not "installed from the guide"). State the rule next to the label and grade inferred groups certain / strong / weak.

## Scope

- **R9. Smallest change that solves the ask.** Reuse existing states and components; don't add plans, charts, files or sections nobody asked for. New options that came only from our own analysis are listed as "needs approval", not built.
- **R10. Ask a pending question once.** If it is still open, keep it in the topic's "Open" list instead of repeating it at the end of every reply. After approval, don't re-ask.
- **R11. End with at most one question or one recommended next step** (see F4).

## Autonomy

- **R12. Tool ladder before handing work back:** MCP/API → browser automation → computer use. If production lacks permissions, try the test environment. If access is missing, draft the access request. Only credentials and sign-ins stay with the user.
- **R13. Build the real thing** (the ticket, the board, the slide, the dashboard cell) rather than a mock of it, unless a mock was asked for.

## Writing

- **R14. Chat follows the user's language.** Deliverables (specs, tickets, reports, docs) use the team's working language.
- **R15. The tracker is the source of truth for a ticket's scope.** No parallel spec doc that drifts from it.
- **R20. Say each thing once, everywhere:** chat messages, ticket descriptions, UI copy. A subtitle that repeats the list below it is noise.

## Outward actions

- **R21. Nothing outward without an explicit ask.** Don't post to chat, the tracker or the wiki unless the user asked for that message; prefer drafts over sending.

## Retrieved context

- **R17. Injected context (the brain hook, memory) is a lead, not a fact.** Use it to connect threads, then open the source before relying on a detail (R5): it can be stale.

## Long runs

- **R16. When subagents or long jobs run, say what is running and roughly how long,** and report finished/failed from an actual check.
- **R19. If a session stops with work pending** (queued prompts, subagents, sign-in blocks), write the pending items into the topic's living README "Open" list, and pick them up from there next time. No new hand-off files.

## Working folders: update, don't duplicate

- Research lives in one folder per topic (e.g. `raw/temp/<topic>/`) with one living `README.md`: question → current answer → open → next → links. Rewrite it in place; don't append.
- At most 2–3 topic docs beside it. A new finding edits an existing doc: no `v2`, `-new` or parallel drafts.
- Don't copy sources reachable by link. If a frozen copy is needed, put it in `sources/` and don't read it without a reason.
- When the research ends, fold the conclusion into the wiki or the tracker and delete the folder. `brain lint` flags folders idle for 21+ days and docs that call themselves stale.
