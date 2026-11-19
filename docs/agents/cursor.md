# Cursor

Init prints this block and does not write it. Put it in `.cursor/mcp.json` in the project, or in `~/.cursor/mcp.json` for every project.

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

The tool name is `search_brain`. Cursor has no UserPromptSubmit hook in this setup, so the agent calls the tool when it needs context. `<path-to-brain>` is the `brain` launcher. `<brain-root>` is the brain folder, `~/Alma` by default.
