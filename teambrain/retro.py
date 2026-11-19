"""Daily retro over Claude Code sessions: friction → proposed rules, skills and evals.

    brain retro digest [--until YYYY-MM-DD] [--out FILE] [--exclude ID ...]
    brain retro mark   [--until YYYY-MM-DD]      mark sessions reviewed through that day
    brain retro status
    brain retro run    [--until YYYY-MM-DD]      digest → `claude -p` review → mark on success

The ledger (state_dir/retro-ledger.json) stores, per session, the timestamp it was reviewed
through, so a session spanning several days is reviewed day by day and a missed night is picked
up by the next run. Transcripts are read only when retro is enabled for one project directory.
The reviewer process is started with its working directory set to retro.dir and a Claude CLI
tool list that has no Bash; a prompt is not what enforces that. Managed CLI policy can still
add tools, and a CLI without ``--restricted`` fails the run so sessions stay unmarked.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from teambrain import config as cfgmod
from teambrain import transcripts as tr

ENGINE = Path(__file__).resolve().parent.parent


def ledger_path(cfg):
    return cfg.state_dir / "retro-ledger.json"


def load_ledger(cfg):
    try:
        return json.loads(ledger_path(cfg).read_text())
    except (OSError, ValueError):
        return {}


def save_ledger(cfg, led):
    p = ledger_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(led, indent=1, sort_keys=True))
    tmp.replace(p)


def cutoff_for(until):
    """End of the given local day (default: yesterday), as an aware datetime."""
    day = datetime.strptime(until, "%Y-%m-%d") if until else datetime.now() - timedelta(days=1)
    return day, day.replace(hour=0, minute=0, second=0, microsecond=0).astimezone() + timedelta(days=1)


def transcript_access(cfg):
    """(pattern, None) or (None, status) when transcripts must not be read."""
    r = cfg["retro"]
    if not r.get("enabled"):
        return None, "transcripts disabled"
    pattern = tr.project_transcript_pattern(r.get("transcripts") or "")
    if pattern is None:
        return None, "refused: transcript scope is not a single project directory"
    return pattern, None


def pending(cfg, cutoff, exclude=()):
    """[(session, new_events)] with at least one typed message not yet reviewed and before cutoff."""
    led = load_ledger(cfg)
    out = []
    pattern, _err = transcript_access(cfg)
    if not pattern:
        return []
    import glob
    for p in sorted(glob.glob(pattern), key=os.path.getmtime):
        s = tr.parse(p)
        if s["id"] in exclude:
            continue
        done = led.get(s["id"], {}).get("processed_through")
        evs = [e for e in s["events"]
               if tr.parse_ts(e[0]) < cutoff and (not done or tr.parse_ts(e[0]) > tr.parse_ts(done))]
        if any(e[1] == "USER" for e in evs):
            out.append((s, evs))
    return out


def digest(s, evs, label="USER"):
    loc = lambda ts: tr.parse_ts(ts).astimezone()
    out = [f"## {tr.title(s)} — `{s['id']}`",
           f"cwd: {s['cwd']} | {loc(evs[0][0]):%Y-%m-%d %H:%M} → {loc(evs[-1][0]):%Y-%m-%d %H:%M}"
           f" | user msgs: {sum(e[1] == 'USER' for e in evs)}", ""]
    for ts, kind, txt, ctx in evs:
        if kind == "USER":
            if ctx:
                out.append(f"> _assistant before:_ …{' '.join(ctx.split())}")
            body = txt if len(txt) < 2500 else txt[:2500] + " …[truncated]"
            out.append(f"**[{loc(ts):%m-%d %H:%M}] {label}:** {body}\n")
        else:
            out.append(f"*[{loc(ts):%m-%d %H:%M}] {kind}* {txt}\n")
    return "\n".join(out)


def build_digest(cfg, until=None, exclude=()):
    day, cutoff = cutoff_for(until)
    items = pending(cfg, cutoff, exclude)
    label = cfg["retro"]["label"]
    text = (f"# Session digests — through {day:%Y-%m-%d} ({len(items)} sessions with new activity)\n\n"
            + "\n\n---\n\n".join(digest(s, evs, label) for s, evs in items))
    return text, len(items)


def mark(cfg, until=None, exclude=()):
    _, cutoff = cutoff_for(until)
    led = load_ledger(cfg)
    items = pending(cfg, cutoff, exclude)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for s, evs in items:
        led[s["id"]] = {"processed_through": evs[-1][0], "title": tr.title(s), "reviewed_at": now}
    save_ledger(cfg, led)
    return len(items)


def prompt_for(cfg, day, digest_path, n):
    r = cfg["retro"]
    template = Path(r["prompt_file"]) if r.get("prompt_file") else ENGINE / "templates" / "retro" / "review-prompt.md"
    if not template.is_absolute():
        template = cfg.root / template
    return template.read_text().format(retro_dir=".", rules_file=digest_path and ".review-input/rules.md",
                                       date=day, digest=".review-input/digest.md", sessions=n)


FILE_TOOLS = "Read,Grep,Glob,Edit,Write"


def claude_argv(cfg, prompt, settings_path):
    """CLI flags that remove command tools and skip user/project settings.

    ``--allowedTools`` is intentionally absent: it adds permissions and does not
    define the tool set. ``--restricted`` plus ``--tools`` does.
    """
    r = cfg["retro"]
    return [
        r["claude_bin"], "--restricted", "--permission-mode", "dontAsk",
        "--tools", FILE_TOOLS,
        "--disallowedTools", "Bash", "--disallowedTools", "mcp__*",
        "--settings", str(settings_path),
        "--no-session-persistence", "--output-format", "text", "-p", prompt,
    ]


def _bounded_dir(root, rel):
    """Real directory inside root. Symlinks and ``..`` are refused."""
    root = Path(root).resolve()
    raw = Path(rel)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError(rel)
    cur = root
    for part in raw.parts:
        if part in ("", ".", ".."):
            raise ValueError(rel)
        nxt = cur / part
        if nxt.is_symlink():
            raise ValueError(rel)
        if not nxt.exists():
            nxt.mkdir()
        elif not nxt.is_dir():
            raise ValueError(rel)
        cur = nxt
    if not cur.resolve().is_relative_to(root):
        raise ValueError(rel)
    return cur


def _settings_file(cfg):
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.state_dir / "retro-claude.settings.json"
    if path.is_symlink():
        raise ValueError("settings path is a symlink")
    path.write_text(json.dumps({
        "permissions": {
            "defaultMode": "dontAsk",
            "allow": ["Read(./**)", "Grep(./**)", "Glob(./**)", "Edit(./**)", "Write(./**)"],
            "deny": ["Bash", "Agent", "Skill", "WebFetch", "WebSearch", "mcp__*"],
        }
    }, indent=1) + "\n")
    return path


def _stamp(path):
    if path.is_symlink() or not path.is_file():
        return None
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest() if data else ""


def _safe_output(retro_dir, daily, before):
    """True only for a regular nonempty file inside retro_dir whose bytes changed this run."""
    if daily.is_symlink() or not daily.is_file():
        return False
    try:
        daily.resolve().relative_to(retro_dir.resolve())
    except ValueError:
        return False
    cur = retro_dir
    for part in daily.resolve().relative_to(retro_dir.resolve()).parts:
        cur = cur / part
        if cur.is_symlink():
            return False
    data = daily.read_bytes()
    if not data:
        return False
    return hashlib.sha256(data).hexdigest() != before


def _stage_rules(cfg, inbox):
    dest = inbox / "rules.md"
    rel = cfg["retro"].get("rules_file") or ""
    src = None
    try:
        if rel and ".." not in Path(rel).parts and not Path(rel).is_absolute():
            src = cfg.root / rel
    except ValueError:
        src = None
    if src is not None and src.is_file() and not src.is_symlink() and src.resolve().is_relative_to(cfg.root.resolve()):
        dest.write_bytes(src.read_bytes())
    else:
        dest.write_text("(rules file was not staged)\n")


def run(cfg, until=None, runner=subprocess.run):
    """One unattended review. Sessions are marked only when this run writes a regular daily file."""
    _pattern, err = transcript_access(cfg)
    if err:
        return {"sessions": 0, "status": err}
    day, _ = cutoff_for(until)
    day = f"{day:%Y-%m-%d}"
    try:
        retro_dir = _bounded_dir(cfg.root, cfg["retro"]["dir"])
        daily_parent = retro_dir / "daily"
        if daily_parent.is_symlink():
            return {"sessions": 0, "status": "refused: daily path is a symlink"}
        if not daily_parent.exists():
            daily_parent.mkdir()
        elif not daily_parent.is_dir():
            return {"sessions": 0, "status": "refused: daily path is not a directory"}
    except ValueError:
        return {"sessions": 0, "status": "refused: retro dir escapes the brain"}
    daily = daily_parent / f"{day}.md"
    if daily.is_symlink():
        return {"sessions": 0, "status": "refused: daily report is a symlink"}
    text, n = build_digest(cfg, day)
    if n == 0:
        return {"sessions": 0, "status": "nothing to review"}
    before = _stamp(daily)
    inbox = retro_dir / ".review-input"
    if inbox.is_symlink() or (inbox.exists() and not inbox.is_dir()):
        return {"sessions": n, "status": "refused: review input path is a symlink"}
    created_inbox = not inbox.exists()
    inbox.mkdir(exist_ok=True)
    try:
        (inbox / "digest.md").write_text(text)
        _stage_rules(cfg, inbox)
        settings = _settings_file(cfg)
        cmd = claude_argv(cfg, prompt_for(cfg, day, ".review-input/digest.md", n), settings)
        result = runner(cmd, cwd=str(retro_dir), capture_output=True, text=True)
        if getattr(result, "returncode", 1) != 0 or not _safe_output(retro_dir, daily, before):
            return {"sessions": n, "status": "failed; sessions left for the next run",
                    "returncode": getattr(result, "returncode", 1)}
        mark(cfg, day)
        return {"sessions": n, "status": "written", "file": str(daily.relative_to(cfg.root))}
    finally:
        for name in ("digest.md", "rules.md"):
            child = inbox / name
            if child.is_file() and not child.is_symlink():
                child.unlink()
        if created_inbox and inbox.is_dir() and not inbox.is_symlink():
            try:
                inbox.rmdir()
            except OSError:
                pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["digest", "mark", "status", "run"])
    ap.add_argument("--until", help="local date, inclusive (default: yesterday)")
    ap.add_argument("--exclude", nargs="*", default=[], help="session ids to skip (e.g. the running one)")
    ap.add_argument("--out", default="-")
    a = ap.parse_args(argv)
    cfg = cfgmod.load()
    if cfg is None:
        sys.exit("Not inside a brain (no teambrain.yaml found; set BRAIN_ROOT).")
    if a.command == "status":
        led = load_ledger(cfg)
        print(f"{len(led)} sessions in ledger; latest processed_through: "
              f"{max((v['processed_through'] for v in led.values()), default='-')}")
    elif a.command == "digest":
        text, _ = build_digest(cfg, a.until, a.exclude)
        (sys.stdout if a.out == "-" else open(a.out, "w")).write(text)
    elif a.command == "mark":
        print(f"marked {mark(cfg, a.until, a.exclude)} sessions")
    else:
        print(json.dumps(run(cfg, a.until), ensure_ascii=False))


if __name__ == "__main__":
    main()
