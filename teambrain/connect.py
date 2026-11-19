"""Connect this brain to Claude Code: MCP server `brain mcp` and the prompt hook.

User-level files only. Cursor and Codex snippets are printed for copy-paste and
are never written.
"""
import json
import shutil
from pathlib import Path


def brain_bin():
    return str(Path(__file__).resolve().parent.parent / "bin" / "brain")


def claude_detected():
    """True when the Claude Code CLI or its user config is already on this machine."""
    if shutil.which("claude"):
        return True
    home = Path.home()
    return (home / ".claude").is_dir() or (home / ".claude.json").is_file()


def mcp_entry(cfg):
    return {
        "command": brain_bin(),
        "args": ["mcp"],
        "env": {"BRAIN_ROOT": str(cfg.root)},
    }


def hook_command(cfg):
    import shlex
    return f"BRAIN_ROOT={shlex.quote(str(cfg.root))} {shlex.quote(brain_bin())} hook-search"


def manual_line(cfg):
    brain = brain_bin()
    return (
        f"Claude Code was not found. Add MCP server alma (`{brain} mcp`, BRAIN_ROOT={cfg.root}) "
        f"and a UserPromptSubmit hook (`{hook_command(cfg)}`). See docs/agents/claude-code.md."
    )


def cursor_snippet(cfg):
    payload = {"mcpServers": {"alma": mcp_entry(cfg)}}
    return "Cursor (.cursor/mcp.json), not written:\n" + json.dumps(payload, indent=2)


def codex_snippet(cfg):
    entry = mcp_entry(cfg)
    return (
        "Codex (~/.codex/config.toml), not written:\n"
        "[mcp_servers.alma]\n"
        f"command = {json.dumps(entry['command'])}\n"
        'args = ["mcp"]\n'
        "\n"
        "[mcp_servers.alma.env]\n"
        f"BRAIN_ROOT = {json.dumps(entry['env']['BRAIN_ROOT'])}\n"
    )


def _load_json(path):
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text() or "{}")
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _backup(path):
    """Copy path aside before the first change. A later change gets the next numbered copy."""
    if not path.is_file():
        return
    bak = path.with_name(path.name + ".bak")
    n = 1
    while bak.exists():
        bak = path.with_name(f"{path.name}.bak.{n}")
        n += 1
    shutil.copy2(path, bak)


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _same_mcp(existing, entry):
    if not isinstance(existing, dict):
        return False
    env = existing.get("env") or {}
    return (existing.get("command") == entry["command"]
            and list(existing.get("args") or []) == entry["args"]
            and env.get("BRAIN_ROOT") == entry["env"]["BRAIN_ROOT"])


def _hook_commands(events):
    found = []
    if not isinstance(events, list):
        return found
    for group in events:
        hooks = group.get("hooks") if isinstance(group, dict) else None
        if not isinstance(hooks, list):
            continue
        for hook in hooks:
            if isinstance(hook, dict) and hook.get("command"):
                found.append(hook["command"])
    return found


def install(cfg):
    """Merge the Alma MCP server and UserPromptSubmit hook into the user Claude Code config.

    Returns True when the files are in place. Returns False when a file is not a JSON object
    and was left unchanged.
    """
    home = Path.home()
    entry = mcp_entry(cfg)
    command = hook_command(cfg)
    claude_json = home / ".claude.json"
    settings = home / ".claude" / "settings.json"

    data = _load_json(claude_json)
    if data is None:
        print(f"Left {claude_json} unchanged (not a JSON object).")
        return False
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    if not _same_mcp(servers.get("alma"), entry):
        _backup(claude_json)
        servers["alma"] = entry
        _write_json(claude_json, data)

    sdata = _load_json(settings)
    if sdata is None:
        print(f"Left {settings} unchanged (not a JSON object).")
        return False
    hooks = sdata.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        sdata["hooks"] = hooks
    events = hooks.get("UserPromptSubmit")
    if not isinstance(events, list):
        events = []
        hooks["UserPromptSubmit"] = events
    if command not in _hook_commands(events):
        _backup(settings)
        events.append({"hooks": [{"type": "command", "command": command}]})
        _write_json(settings, sdata)
    return True


def connected(cfg):
    """True when user or project Claude Code config points an MCP server at `brain mcp`."""
    paths = [Path.home() / ".claude.json"]
    if cfg is not None:
        paths.append(Path(cfg.root) / ".mcp.json")
    for path in paths:
        data = _load_json(path)
        servers = (data or {}).get("mcpServers") if isinstance(data, dict) else None
        if not isinstance(servers, dict):
            continue
        for spec in servers.values():
            if isinstance(spec, dict) and "mcp" in list(spec.get("args") or []):
                return True
    return False


def hook_installed(cfg=None):
    paths = [Path.home() / ".claude" / "settings.json"]
    if cfg is not None:
        paths.append(Path(cfg.root) / ".claude" / "settings.json")
    for path in paths:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if "hook-search" in text:
            return True
    return False
