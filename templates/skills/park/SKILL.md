---
name: park
description: Use when the user wants to pause a thread and come back later: "log it", "log current progress", "I'll circle back", "save this as context", "log as action item / insight", "what is left", "where were we", "resume X". Writes a Done / Open / Next / Links snapshot to the right home in the brain, and on resume reads it back as a 5-line "where we are".
---

# Park and resume

People run many threads at once and park them with "log it, I'll circle back". Parking must be cheap for them and complete enough that a fresh session can resume without re-asking.

## Park

1. **Pick the home.** Don't create a new file when one exists:

   | Thread | Home |
   |---|---|
   | Ticket / feature work | `raw/temp/<TICKET>/README.md` (create the folder if missing) |
   | Topic already in the wiki | that wiki page, a dated `## Status <date>` block at the end |
   | Idea for the team's own tooling/workflow | the brain's roadmap or backlog file |
   | Analysis findings | the analysis page's `## Insights` and `## Action items` lists |
   | Nothing fits | `wiki/parked/<YYYY-MM-DD>-<slug>.md` |

   Search the brain (`search_brain`, or grep the wiki and `raw/temp/`) for the topic before choosing.

2. **Write the snapshot**, with facts only and every claim linked:

   ```
   ## Status <YYYY-MM-DD>: <one-line state>
   **Done:** bullets with links (tickets, dashboards, files, chat permalinks)
   **Open questions:** each with an owner. These are the only place a pending question lives.
   **Next:** the single next step, then up to 2 more
   **Verify:** links the user can click to check the work (saved filters, dashboards, PRs)
   **Insights / Action items:** only when asked to "log as insight / action item": their meaning, one line each
   ```

3. **Keep the user's wording** for insights and decisions. Rephrase only for clarity, never to soften.
4. Reply in 2 lines: where it's parked (path) and the next step. No recap of the thread.

## Resume ("what is left", "where were we", "resume X")

1. Find the latest `## Status` block for the thread, plus anything newer: git log on the file, the ticket, the chat thread.
2. **Check live state before reporting.** Ticket status, dashboard, PR, agent run. Never report from the note alone.
3. Answer in at most 5 lines: state → what changed since parking → open questions → the one next step.

## Don'ts

- Don't dump the conversation. A snapshot over ~25 lines belongs in its own wiki page.
- Don't leave screenshots in temp paths. Copy them next to the note.
- Don't post anything to chat or the tracker as part of parking.
