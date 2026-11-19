---
name: tinder-review
description: Use whenever the user should decide on items one at a time ("tinder style", "go one by one", "card by card"): backlog triage, ticket edits, message drafts, spec/acceptance changes, data fixes, any list of proposed actions. Shows one card per native multiple-choice question (1 approve · 2 adjust · 3 skip) with a before/after preview of the consequence, executes on approve, then moves to the next card. Other skills can reference this for their one-by-one mode.
---

# Tinder review (one decision per card)

The user clicks 1 / 2 / 3. They never have to type a verdict.

## The card = one `AskUserQuestion` call

**Up to 4 cards per call** (one question each). The user must never wait for research or writes between cards.

- `header`: the item key, e.g. `PROJ-2945` (≤12 chars).
- `question`: `[n/N] <full URL> · <title>`, newline, `Proposed: <action as a plain sentence>?`
  e.g. "[3/107] https://tracker.example.com/browse/PROJ-2945 · Renewal expires a day early\nProposed: close it as Won't Fix?"
  Keep the `[n/N]` counter. The URL is the click shortcut. Say the action in words ("move it to the Ongoing lane and set the due date to Nov 27"), never shorthand like "Ongoing, due Nov 27, linked to 3477?".
- `options` (always these three, in this order):

| # | label | description | preview |
|---|---|---|---|
| 1 | `Approve (Recommended)` | The exact action, e.g. "Close as Won't Fix + comment" | **Before / After** block (below) |
| 2 | `Adjust` | "Tell me what to change; I'll add it as a comment / redo the action" | The proposed comment text |
| 3 | `Skip` | "Leave as is, go to next" | **Before** only: "Nothing changes" |

Mark `(Recommended)` on Approve only when the evidence supports it. If the evidence is weak, still offer Approve but say "guess" in its description.

The user may pick "Other" and type, e.g. "keep, move to backlog". Treat it as an Adjust instruction.

### Preview: before / after (monospace, ≤15 lines)

```
Type      Bug
Reporter  <reporter>
Created   2024-03-11
Asks      Renewed licence expires ~23h early
Evidence  No commits, no links
          Feature is legacy

          BEFORE              AFTER
Status   In Triage          Done (Won't Fix)
Board    To Do column       hidden (Done)
Owner    <owner>            <owner>
Notify   —                  reporter + watchers (2)
Comment  —                  "Closing as won't fix: <1 day
                            offset on a legacy feature, no
                            activity since 2024-03."
Undo     —                  reopen
```

Header part: no key in the preview (it's in the question), one attribute per line, values aligned in one column, wrapped lines indented to that column.

Always fill these rows: what changes (status/field), **where it shows** (board column, backlog, release), **who gets notified**, and **how to undo**. These rows are the consequence; that's what the user decides on.

## Loop

1. Before the first card: one line with the queue, e.g. "107 cards, oldest first. 1 approve · 2 adjust · 3 skip."
2. **Pre-research the whole queue up front** with a background subagent (reads only). It writes ready cards (key, asks, evidence, proposed action, transition id, comment) to `<scratchpad>/cards.jsonl` in queue order. Start showing cards as soon as the first 4 are in the file. Never research between cards in the foreground.
3. **Writes go in bulk, in the background.** Collect the decisions from each 4-card batch. Hand the approved/adjusted ones to a background subagent (one write per approved card, then verify each). In the same message, show the next 4-card batch. Report the write results in one line when they land ("✓ 4 of 4 applied: …"). A write only ever follows its own card's approval.
4. On **Adjust**: apply the user's text (as a comment, or change the action), show the card again only if the action itself changed, then move on.
5. On **Skip**: change nothing, go to the next card.
6. Text between cards is at most one line: "✓ PROJ-2945 closed (verified)".
7. If a write is blocked (permission or workflow), say so in one line, keep the card in a "blocked" list, and continue.
8. At the end (or when the user stops): a table of approved / adjusted / skipped / blocked with keys, and the calling skill's log step.

## Rules

- Comments only where the reason matters later: closing (declined / released / duplicate). Parking in the backlog, status or priority changes: no comment.
- Evidence before verdict. The calling skill defines what counts as evidence (commits, code path, links).
- One write per approval. Approval of card N never carries over to card N+1.
- Deliverable text (comments, tickets) in the team's working language. The question and labels follow the user's chat language.
