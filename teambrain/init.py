"""Create a brain from notes you already have. Does not invent a corpus.

    brain init <path>              copy a markdown folder or Obsidian vault (asks first)
    brain init <path> --yes        copy without asking
    brain init <path> --in-place --yes
                                   index the folder where it is
    brain init notes.txt --yes     a pasted Claude/ChatGPT memory export

With no path, ask for one and create nothing. Notion and Google Docs are not in this version.
"""
import argparse
import os
import re
import shutil
import sys
from pathlib import Path

from teambrain import config as cfgmod

SKIP_DIRS = {".git", ".obsidian", "node_modules", "__pycache__", ".brain", ".lancedb", ".private"}
NOTE_EXTS = {".md", ".txt"}


def default_brain_dir():
    return Path(os.environ.get("ALMA_HOME") or Path.home() / "Alma").expanduser().resolve()


def current_pointer():
    return Path(os.environ.get("TEAMBRAIN_CURRENT") or Path.home() / ".team-brain" / "current")


def slugify(name):
    text = re.sub(r"[^\w.-]+", "-", str(name).strip().lower(), flags=re.UNICODE).strip("-._")
    return text or "notes"


def _within(child, parent):
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def iter_source(src):
    """(path, relative) notes inside a folder. Skips hidden and vendored directories."""
    root = src.resolve()
    for path in sorted(src.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() not in NOTE_EXTS:
            continue
        try:
            rel = path.resolve().relative_to(root)
        except (ValueError, OSError):
            continue
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts):
            continue
        yield path, rel


def inspect_source(src):
    """Scope of an import, or None when the path is not a notes folder or a memory export."""
    src = Path(src)
    if src.is_file():
        if src.suffix.lower() not in NOTE_EXTS:
            return None
        return {
            "files": 1,
            "bytes": src.stat().st_size,
            "top_folders": [],
            "kind": "memory",
            "name": src.name,
            "items": [(src, Path(src.name))],
        }
    if not src.is_dir():
        return None
    items = list(iter_source(src))
    tops, seen, total = [], set(), 0
    for path, rel in items:
        total += path.stat().st_size
        if len(rel.parts) > 1 and rel.parts[0] not in seen:
            seen.add(rel.parts[0])
            tops.append(rel.parts[0])
    kind = "obsidian" if (src / ".obsidian").is_dir() else "folder"
    return {
        "files": len(items),
        "bytes": total,
        "top_folders": tops,
        "kind": kind,
        "name": src.name,
        "items": items,
    }


def format_size(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    return f"{n / 1000:.1f} KB"


def format_preview(scan):
    noun = "file" if scan["files"] == 1 else "files"
    if scan["kind"] == "memory":
        where = scan["name"]
    elif scan["top_folders"]:
        shown = scan["top_folders"][:8]
        where = ", ".join(shown)
        extra = len(scan["top_folders"]) - len(shown)
        if extra:
            where += f", +{extra} more"
    else:
        where = "no subfolders"
    prefix = "Obsidian vault: " if scan["kind"] == "obsidian" else ""
    return f"{prefix}{scan['files']} {noun}, {where}, {format_size(scan['bytes'])}"


def _isatty(stream):
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def choose_mode(scan, dest, slug, args, stdin):
    """"copy", "in-place", or None when the person declines. Memory exports always copy."""
    print(format_preview(scan))
    if scan["kind"] == "memory":
        target = dest / "raw" / "imports" / "memory"
        if args.yes:
            return "copy"
        if not _isatty(stdin):
            print(f"Copy into {target}/")
            print("Re-run with --yes to copy.")
            return None
        print(f"Copy into {target}/? Press Enter to copy [y]")
        return "copy" if stdin.readline().strip().lower() in {"", "y", "yes"} else None

    folder = dest / "raw" / "imports" / slug
    if args.yes and args.in_place:
        return "in-place"
    if args.yes:
        return "copy"
    if args.in_place:
        if not _isatty(stdin):
            print(f"Index in place: {scan['name']}")
            print("Re-run with --in-place --yes to index in place.")
            return None
        print(f"Index in place ({scan['name']})? [y/N]")
        return "in-place" if stdin.readline().strip().lower() in {"y", "yes"} else None
    if not _isatty(stdin):
        print(f"Copy into {folder}/  or index in place ({scan['name']})")
        print("Re-run with --yes to copy, or --in-place --yes to index in place.")
        return None
    print(f"Copy into {folder}/ [c], index in place [i], or cancel [n]? Press Enter to copy [c]")
    ans = stdin.readline().strip().lower()
    if ans in {"", "c", "copy", "y", "yes"}:
        return "copy"
    if ans in {"i", "in-place", "inplace"}:
        return "in-place"
    return None


def claude_project_pattern():
    """Glob for the only Claude Code project with transcripts, when `claude` can run a retro.

    Zero projects, or more than one, returns None. Codex transcripts are not detected.
    """
    import shutil
    from teambrain.transcripts import project_transcript_pattern
    if shutil.which("claude") is None:
        return None
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return None
    found = []
    try:
        children = list(root.iterdir())
    except OSError:
        return None
    for child in children:
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            has_transcript = any(child.glob("*.jsonl"))
        except OSError:
            continue
        if has_transcript:
            found.append(child)
    if len(found) != 1:
        return None
    pattern = str(found[0] / "*.jsonl")
    if project_transcript_pattern(pattern) is None:
        return None
    return pattern


def default_jobs(pattern):
    jobs = [
        {"name": "index", "run": "index --incremental", "at": "03:15"},
        {"name": "lint", "run": "lint", "at": "02:30"},
        {"name": "snapshot", "run": "snapshot raw", "at": "02:45"},
    ]
    if pattern:
        jobs.append({"name": "retro", "run": "retro run", "at": "01:00"})
    return jobs


def ensure_schedule(cfg_path, pattern=None):
    """Write nightly jobs when this brain does not have any yet. Returns True if it wrote them."""
    import yaml
    data = yaml.safe_load(cfg_path.read_text()) or {}
    if not isinstance(data, dict):
        data = {}
    schedule = data.get("schedule")
    if not isinstance(schedule, dict):
        schedule = {}
    existing = schedule.get("jobs")
    if isinstance(existing, list) and existing:
        return False
    schedule["jobs"] = default_jobs(pattern)
    data["schedule"] = schedule
    if pattern:
        index = data.get("index")
        if not isinstance(index, dict):
            index = {}
        chats = index.get("chats")
        if not isinstance(chats, dict):
            chats = {}
        chats["enabled"] = True
        chats["glob"] = pattern
        index["chats"] = chats
        data["index"] = index
        retro = data.get("retro")
        if not isinstance(retro, dict):
            retro = {}
        retro["enabled"] = True
        retro["transcripts"] = pattern
        data["retro"] = retro
    _write_yaml(cfg_path, data)
    if not pattern:
        cfg_path.write_text(
            cfg_path.read_text().rstrip() + "\n"
            "# retro stays off until one Claude Code project has transcripts and `claude` is installed.\n"
            "# Codex chat import is not in this version.\n"
            '#   - {name: retro, run: "retro run", at: "01:00"}\n'
        )
    return True


def maybe_install_schedule(cfg, args, stdin):
    """Install nightly jobs. A missing scheduler prints one fix line and does not fail init."""
    if args.no_schedule:
        print("Nightly jobs not installed (--no-schedule).")
        print("Install later: brain schedule install")
        return
    if not args.yes:
        if not _isatty(stdin):
            print("Nightly jobs not installed.")
            print("Re-run with --yes to install them, or run brain schedule install")
            return
        print("Install nightly jobs (index, stale-doc check, ...) via launchd/cron? [Y/n]")
        if stdin.readline().strip().lower() not in {"", "y", "yes"}:
            print("Nightly jobs not installed.")
            print("Install later: brain schedule install")
            return
    from teambrain.schedule import SchedulerMissing, install
    try:
        install(cfg)
    except SchedulerMissing as exc:
        print(exc)
        return
    print("brain schedule status")
    print("brain schedule uninstall")


def maybe_connect(cfg, args, stdin):
    """Connect Claude Code. A missing install prints one line and does not fail init."""
    from teambrain import connect
    if getattr(args, "no_connect", False):
        print("Claude Code not connected (--no-connect).")
        return
    if not args.yes:
        if not _isatty(stdin):
            print("Claude Code not connected.")
            print("Re-run with --yes to connect, or pass --no-connect to skip.")
            return
        print("Connect Alma to Claude Code (MCP + prompt hook)? [Y/n]")
        if stdin.readline().strip().lower() not in {"", "y", "yes"}:
            print("Claude Code not connected.")
            return
    if not connect.claude_detected():
        print(connect.manual_line(cfg))
    elif connect.install(cfg):
        print("Connected Claude Code: MCP server alma and the UserPromptSubmit hook.")
    else:
        print(connect.manual_line(cfg))
    print(connect.cursor_snippet(cfg))
    print(connect.codex_snippet(cfg))


def ensure_layout(dest, name):
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "wiki").mkdir(exist_ok=True)
    (dest / "raw").mkdir(exist_ok=True)
    ignore = dest / ".gitignore"
    if not ignore.exists():
        ignore.write_text(".brain/\n.private/\n")
    cfg_path = dest / "teambrain.yaml"
    if not cfg_path.exists():
        cfg_path.write_text(
            "# Alma brain. Omitted keys use engine defaults (multilingual search included).\n"
            f"name: {slugify(name)}\n"
        )
    return cfg_path


def add_extra_dir(cfg_path, source):
    import yaml
    data = yaml.safe_load(cfg_path.read_text()) or {}
    if not isinstance(data, dict):
        data = {}
    index = data.get("index")
    if not isinstance(index, dict):
        index = {}
        data["index"] = index
    extras = index.get("extra_dirs")
    if not isinstance(extras, list):
        extras = []
    resolved = str(Path(source).resolve())
    for item in extras:
        if isinstance(item, dict) and str(Path(str(item.get("path", ""))).expanduser().resolve()) == resolved:
            index["extra_dirs"] = extras
            data["index"] = index
            _write_yaml(cfg_path, data)
            return False
    extras.append({"path": resolved, "type": "notes"})
    index["extra_dirs"] = extras
    data["index"] = index
    _write_yaml(cfg_path, data)
    return True


def _write_yaml(path, data):
    import yaml

    class Dumper(yaml.SafeDumper):
        pass

    def _str(dumper, value):
        # Quote times and other colon-bearing strings so "03:15" stays a string.
        style = '"' if (":" in value or value.startswith("0")) else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)

    Dumper.add_representer(str, _str)
    body = yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True)
    path.write_text("# Alma brain. Omitted keys use engine defaults (multilingual search included).\n" + body)


def copy_items(items, dest_dir):
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src, rel in items:
        target = dest_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            continue
        shutil.copy2(src, target)
        copied += 1
    return copied


def write_current(dest):
    path = current_pointer()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(Path(dest).resolve()) + "\n")


def resolve_dest(args):
    if args.brain:
        dest = Path(args.brain).expanduser().resolve()
        if cfgmod.is_engine_tree(dest):
            print("Refusing to store a brain inside the engine checkout. Pick another --brain directory.")
            return None
        return dest
    found = cfgmod.find_root()
    if found and not cfgmod.is_engine_tree(found) and (found / "teambrain.yaml").is_file():
        return found
    return default_brain_dir()


def main(argv=None, stdin=None):
    ap = argparse.ArgumentParser(prog="brain init", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", help="markdown folder, Obsidian vault, or a .md/.txt memory export")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="copy, install nightly jobs, and connect Claude Code without asking")
    ap.add_argument("--no-schedule", action="store_true", help="do not install nightly jobs")
    ap.add_argument("--no-connect", action="store_true", help="do not connect Claude Code")
    ap.add_argument("--in-place", action="store_true", help="index the folder where it is; do not copy")
    ap.add_argument("--brain", help="brain directory (default: ~/Alma, or the brain you are already in)")
    ap.add_argument("--name", default="alma", help="name written to a new teambrain.yaml")
    args = ap.parse_args(argv)
    stdin = stdin or sys.stdin

    source = args.source
    if not source:
        print("Path to a markdown folder, Obsidian vault, or a memory export (.md/.txt):")
        source = stdin.readline().strip()
        if not source:
            print("brain init <path>")
            return 2
    src = Path(source).expanduser().resolve()
    if cfgmod.is_engine_tree(src):
        print("That path is the Alma engine, not a notes folder.")
        return 2
    if not src.exists():
        print(f"No such path: {src}")
        return 2
    scan = inspect_source(src)
    if scan is None:
        print("Expected a markdown folder, an Obsidian vault, or a .md/.txt memory export.")
        return 2
    if scan["files"] == 0:
        print(f"No markdown or text notes in {src}.")
        print("brain init <path>")
        return 2

    dest = resolve_dest(args)
    if dest is None:
        return 2
    if scan["kind"] != "memory" and (_within(dest, src) or _within(src, dest)):
        print("Refusing to copy a folder into itself. Use --in-place with a separate --brain directory,")
        print(f"or run brain init {src} to copy into {default_brain_dir()}.")
        return 2

    slug = slugify(src.stem if scan["kind"] == "memory" else src.name)
    mode = choose_mode(scan, dest, slug, args, stdin)
    if mode is None:
        return 2
    if scan["kind"] == "memory":
        mode = "copy"

    cfg_path = ensure_layout(dest, args.name)
    if mode == "copy":
        if scan["kind"] == "memory":
            folder = dest / "raw" / "imports" / "memory"
        else:
            folder = dest / "raw" / "imports" / slug
        print(f"Copying into {folder}")
        copy_items(scan["items"], folder)
    else:
        print(f"Indexing in place: {src}")
        add_extra_dir(cfg_path, src)

    write_current(dest)
    ensure_schedule(cfg_path, claude_project_pattern())
    cfg = cfgmod.Config(dest)
    try:
        from teambrain.index import build_index
        build_index(cfg)
    except Exception as exc:
        print(f"Import saved, but the index failed: {exc}")
        print("fix: brain index")
        return 1
    maybe_install_schedule(cfg, args, stdin)
    maybe_connect(cfg, args, stdin)
    print("Next: open Claude Code and ask normally.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
