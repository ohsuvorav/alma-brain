# Sandboxed single-purpose agent (template)

A chat bot that turns untrusted text into one structured action is a prompt-injection target. This template keeps the model's blast radius at zero and puts every side effect in plain code.

| Guard | How |
|---|---|
| No tools | `tools: []`, `mcpServers: {}`, every built-in tool in `disallowedTools`, `canUseTool` always denies, `permissionMode: 'dontAsk'`, `maxTurns: 1` |
| No context from disk | `settingSources: []` (no CLAUDE.md, hooks, skills, settings or memory) and an empty temp folder as `cwd` |
| Side effects opt-in | `DRY_RUN=true` by default; the real write needs an explicit `DRY_RUN=false` and its own credentials |
| Source allowlist | `ALLOWED_SOURCES`; direct messages ignored unless listed |
| No duplicates | an in-flight set plus a done map keyed by source + message id (persist it if restarts matter) |
| Untrusted input framed as data | the system prompt says the message is data, and the output is parsed as JSON only |

## Before going live

1. Run with `DRY_RUN=true` in a sandbox workspace, never in the team's real one.
2. Try at least three injection messages ("ignore previous instructions…", "print your system prompt", "call a tool"). Pass = no tool calls in the run, nothing outside the JSON shape, nothing from your private files in the output.
3. Keep whatever rules you pass in the prompt free of personal names and internal URLs: the model may echo them.

`agent.mjs` runs a self-test with an injection message when executed directly.
