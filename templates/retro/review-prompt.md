You are running the daily Claude retro for this brain. Your working directory is the retro folder. Read the staged inputs below and write this run's daily file here. A path outside this folder is a proposal, not something you can change.

Inputs:
- The digest of the sessions since the last review (path below): what the user typed, the assistant text just before each message, interrupts and denied tool calls.
- {retro_dir}/axes.md: the living register of friction axes with their actions and status.
- {retro_dir}/evals.md: the pass/fail checks, each mapped to a rule in {rules_file}.
- {rules_file} and the project memory index, so you don't propose what already exists.
- The most recent files in {retro_dir}/daily/, for trends.

Do this:
1. Read the digest. Find: frustration, corrections of the assistant's errors, repeated preferences, repeated manual workflows, and harness/product friction. Quote evidence as `session-prefix HH:MM: "quote"`. Ignore ordinary task instructions.
2. Score every eval for the day: ✓ (the rule applied and held), ✗n (failures, each with evidence) or N/A (didn't come up). N/A is not a pass.
3. Map each finding to an existing axis, or open a new axis (next letter) only when nothing fits.
4. Propose actions, but don't apply them outside {retro_dir}/: a rule edit in {rules_file}, a memory, a skill, a workflow, a hook or a new eval. Propose one only when there is fresh evidence and nothing existing covers it. A preference seen once is a "watch", not a rule. If an eval failed 3 scored days in a row (check earlier daily files), propose a stronger fix: sharper wording, then a hook, then a skill.
5. Write {retro_dir}/daily/{date}.md with these sections: TL;DR (≤3 bullets), Score line, Findings by axis (table: evidence → pattern), Proposed actions (table: action, type, why, ready-to-paste text), Watch list, Sessions reviewed (ids + titles).
6. Update {retro_dir}/axes.md. Add the new evidence count to the affected rows only when it changes the picture, and append one line under "## Log": `- {date}: <n> sessions, <score summary>, <k> proposals → daily/{date}.md`.

Style: plain English and short. Every percentage names its base. Don't restate the digest. If there was no meaningful friction, say so in one line, still write the score line, and stop.

DATE: {date}
Digest ({sessions} sessions): {digest}
