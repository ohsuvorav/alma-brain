# Claude retro (template)

A daily review of Claude Code sessions that turns friction (confusion, corrections, repeated asks, manual workflows) into rules, skills and evals that carry over to future sessions.

## Set up in a brain

```sh
mkdir -p wiki/claude-retro/daily            # or set retro.dir in teambrain.yaml
cp <engine>/templates/retro/{axes,evals}.md wiki/claude-retro/
# teambrain.yaml: retro.enabled: true
# retro.transcripts: ~/.claude/projects/<one-project>/*.jsonl
brain retro digest --until 2026-01-05 | head # check what the reviewer will see
brain retro run                              # review yesterday (needs the `claude` CLI)
```

Nightly: add `{name: retro, run: "retro run", at: "01:00"}` under `schedule.jobs` in teambrain.yaml, then `brain schedule install`. By hand: `cd <brain> && <engine>/bin/brain retro run`.
Transcripts stay unread until `retro.enabled` is true and `retro.transcripts` names one project directory.

## How the loop works

1. `brain retro run` builds a digest of session events not yet reviewed, up to the end of yesterday, from that one directory: typed messages, the assistant text just before each one, interrupts and denied tools. Subagents are skipped.
2. `claude` is started in `retro.dir` with `--restricted` and a file-tool list that does not include Bash. It writes `daily/<date>.md` and can update `axes.md` there.
3. Sessions are marked reviewed only after this run replaces or creates a regular `daily/<date>.md` inside that directory. An existing or symlinked file is not enough. A missed night is picked up by the next run.
4. A human reads the daily file and approves proposals. The job never edits rules, memory or skills itself.
