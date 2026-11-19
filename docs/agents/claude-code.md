# Claude Code

`brain init` writes these two user-level files when Claude Code is already on the machine. It backs up each file it changes. Running init again does not add a second copy.

If Claude Code is not installed yet, init prints one line and still exits 0. The same blocks are below, with your paths filled in when init prints them.

MCP server, in `~/.claude.json`:

```json
{
  "mcpServers": {
    "alma": {
      "command": "<path-to-brain>",
      "args": ["mcp"],
      "env": {"BRAIN_ROOT": "<brain-root>"}
    }
  }
}
```

UserPromptSubmit hook, in `~/.claude/settings.json`. The hook reads the user's message and adds the top passages as context. It does not answer.

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "BRAIN_ROOT=<brain-root> <path-to-brain> hook-search"
          }
        ]
      }
    ]
  }
}
```

`<path-to-brain>` is the `brain` launcher (`bin/brain` in this checkout, or `brain` on `PATH` in a new terminal). `<brain-root>` is the brain folder, `~/Alma` unless you set `ALMA_HOME` or `--brain`.

Then open Claude Code and ask normally. `brain ask` only prints the context the hook would inject.
