# Codex

Init prints this block and does not write it. Put it in `~/.codex/config.toml`.

```toml
[mcp_servers.alma]
command = "<path-to-brain>"
args = ["mcp"]

[mcp_servers.alma.env]
BRAIN_ROOT = "<brain-root>"
```

The tool name is `search_brain`. Codex has no UserPromptSubmit hook in this setup. `<path-to-brain>` is the `brain` launcher. `<brain-root>` is the brain folder, `~/Alma` by default. Importing Codex chats into the brain is not in this version.
