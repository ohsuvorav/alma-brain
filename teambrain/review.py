"""One card at a time for stale or idle notes and pending backlog suggestions.

    keep     leave it, and don't show it again until the text changes
    fix      open $EDITOR
    archive  move to wiki/_archive or raw/archive (never delete)
    skip     next card, show it again next time
    undo     reverse the last action

Nothing is committed unless you are at a terminal and answer yes.
Nothing is pushed.
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from teambrain import config as cfgmod
from teambrain import lint
from teambrain.wip import git_env

ALIASES = {
    "k": "keep", "keep": "keep",
    "f": "fix", "fix": "fix",
    "a": "archive", "archive": "archive",
    "s": "skip", "skip": "skip",
    "u": "undo", "undo": "undo",
    "q": "quit", "quit": "quit",
}
EXCLUDED = {"resolved", "duplicate", "rejected", "parked", "routed"}


def _isatty(stream):
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def kept_path(cfg):
    return cfg.state_dir / "review-kept.json"


def load_kept(cfg):
    try:
        data = json.loads(kept_path(cfg).read_text())
    except (OSError, ValueError):
        return {}
    kept = data.get("kept") if isinstance(data, dict) else None
    return kept if isinstance(kept, dict) else {}


def save_kept(cfg, kept):
    path = kept_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kept": kept}, indent=2) + "\n")


def content_sha(path):
    path = Path(path)
    if path.is_file() and not path.is_symlink():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if path.is_dir() and not path.is_symlink():
        digest = hashlib.sha256()
        for child in sorted(path.rglob("*")):
            if child.is_file() and not child.is_symlink():
                digest.update(str(child.relative_to(path)).encode())
                digest.update(child.read_bytes())
        return digest.hexdigest()
    return ""


def _heading(path):
    path = Path(path)
    if path.is_file():
        try:
            text = path.read_text(errors="replace")
        except OSError:
            text = ""
        match = re.search(r"^#\s+(.+)$", text, re.M)
        if match:
            return match.group(1).strip()
    return path.stem or path.name


def _excerpt(path, limit=500):
    path = Path(path)
    if path.is_dir():
        readme = path / "README.md"
        if readme.is_file():
            path = readme
        else:
            found = sorted(p for p in path.rglob("*.md") if p.is_file())
            path = found[0] if found else path
    if not path.is_file():
        return ""
    text = path.read_text(errors="replace").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _idle_folder(cfg, rel):
    path = cfg.root / rel
    if path.name == "README.md":
        return path.parent
    return path


def pending_suggestions(cfg):
    from teambrain.backlog import entries
    out = []
    for target in cfg["backlogs"]:
        path = cfg.root / target
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for entry in entries(text, target):
            if entry.get("status") not in EXCLUDED:
                out.append(entry)
    return out


def load_cards(cfg):
    kept = load_kept(cfg)
    cards = []
    for finding in lint.check(cfg):
        if finding["rule"] not in ("DOC-SELF-STALE", "TEMP-IDLE"):
            continue
        rel = finding["file"]
        if "wiki/_archive/" in rel or "raw/archive/" in rel:
            continue
        target = _idle_folder(cfg, rel) if finding["rule"] == "TEMP-IDLE" else cfg.root / rel
        sha = content_sha(target if target.exists() else cfg.root / rel)
        card_id = f"lint:{rel}:{finding['rule']}"
        if kept.get(card_id) == sha and sha:
            continue
        title_path = cfg.root / rel
        cards.append({
            "id": card_id,
            "kind": "lint",
            "rule": finding["rule"],
            "title": _heading(title_path if title_path.is_file() else target),
            "file": rel,
            "why": finding["message"],
            "excerpt": _excerpt(target if target.exists() else title_path),
            "sha": sha,
        })
    for entry in pending_suggestions(cfg):
        sha = hashlib.sha256(entry["body"].encode()).hexdigest()
        card_id = f"suggestion:{entry['id']}"
        if kept.get(card_id) == sha:
            continue
        cards.append({
            "id": card_id,
            "kind": "suggestion",
            "title": entry["title"],
            "file": entry["target"],
            "why": f"Pending suggestion ({entry.get('status', 'inbox')}) in {entry['target']}",
            "excerpt": entry["body"].strip()[:500],
            "sha": sha,
            "entry_id": entry["id"],
            "target": entry["target"],
        })
    return cards


def show(card, remaining):
    print(f"[1/{remaining}] {card['title']}")
    print(f"file: {card['file']}")
    print(f"why: {card['why']}")
    print()
    print(card["excerpt"].rstrip())
    print("---")
    print("keep / fix / archive / skip / undo")


def read_cmd(stdin):
    line = stdin.readline()
    if line == "":
        return "quit"
    return ALIASES.get(line.strip().lower(), "")


def _unique(dest):
    if not dest.exists():
        return dest
    for n in range(2, 100):
        cand = dest.with_name(dest.name + f"-{n}")
        if not cand.exists():
            return cand
    raise RuntimeError(f"archive destination already exists: {dest}")


def archive_lint(cfg, card):
    root = cfg.root.resolve()
    src = _idle_folder(cfg, card["file"]) if card.get("rule") == "TEMP-IDLE" else cfg.root / card["file"]
    if not src.exists():
        raise RuntimeError(f"missing {card['file']}")
    src = src.resolve()
    if src.is_symlink() or src == root or not src.is_relative_to(root):
        raise RuntimeError("refusing to archive outside the brain")
    rel = src.relative_to(root)
    if rel.parts[0] == "wiki":
        dest = root / "wiki" / "_archive" / Path(*rel.parts[1:])
    elif rel.parts[0] == "raw":
        dest = root / "raw" / "archive" / Path(*rel.parts[1:])
    else:
        dest = root / "raw" / "archive" / rel
    dest = _unique(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    print(f"Archived to {dest.relative_to(root)}")
    return {"op": "move", "src": str(src), "dest": str(dest)}


def archive_suggestion(cfg, card):
    from teambrain.backlog import Backlog, entries
    path = cfg.root / card["target"]
    old = path.read_text()
    matches = [e for e in entries(old, card["target"]) if e["id"] == card["entry_id"]]
    if len(matches) != 1:
        print("Suggestion changed; skip it and run review again.")
        return None
    entry = matches[0]
    dest = cfg.root / "raw" / "archive" / "suggestions.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    previous = dest.read_text() if dest.is_file() else None
    header = "" if previous is not None else "# Archived suggestions\n\n"
    dest.write_text((previous or "") + header + entry["body"].strip() + "\n\n")
    try:
        Backlog(cfg.root, cfg).write(path, old, old[:entry["start"]] + old[entry["end"]:])
    except ValueError as exc:
        if previous is None:
            dest.unlink(missing_ok=True)
        else:
            dest.write_text(previous)
        print(exc)
        return None
    print("Archived suggestion to raw/archive/suggestions.md")
    return {
        "op": "suggestion-archive",
        "backlog": str(path),
        "previous_backlog": old,
        "archive": str(dest),
        "previous_archive": previous,
    }


def editable(cfg, card):
    if card["kind"] == "suggestion":
        path = cfg.root / card["file"]
        return path if path.is_file() else None
    path = cfg.root / card["file"]
    if card.get("rule") == "TEMP-IDLE":
        folder = path.parent if path.name == "README.md" else path
        if (folder / "README.md").is_file():
            return folder / "README.md"
        if folder.is_dir():
            found = sorted(p for p in folder.rglob("*.md") if p.is_file())
            return found[0] if found else None
        return None
    return path if path.is_file() else None


def edit(path):
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    try:
        result = subprocess.run(shlex.split(editor) + [str(path)])
    except OSError as exc:
        print(f"Could not open editor ({exc}). Set EDITOR.")
        return False
    return result.returncode == 0


def do_fix(cfg, card):
    path = editable(cfg, card)
    if path is None:
        print("Nothing to edit.")
        return None
    previous = path.read_text(errors="replace") if path.is_file() else ""
    if not edit(path):
        return None
    current = path.read_text(errors="replace") if path.is_file() else ""
    if current == previous:
        print("No change.")
        return None
    print(f"Updated {path.relative_to(cfg.root)}")
    return {"op": "write", "path": str(path), "previous": previous}


def remember(cfg, card):
    kept = load_kept(cfg)
    kept[card["id"]] = card["sha"]
    save_kept(cfg, kept)
    print("Kept.")
    return card["id"]


def revert(cfg, action):
    op = action["op"]
    if op == "move":
        src, dest = Path(action["src"]), Path(action["dest"])
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dest), str(src))
        print(f"Restored {src.relative_to(cfg.root)}")
    elif op == "keep":
        kept = load_kept(cfg)
        kept.pop(action["key"], None)
        save_kept(cfg, kept)
        print("Undid keep.")
    elif op == "write":
        Path(action["path"]).write_text(action["previous"])
        print("Undid edit.")
    elif op == "suggestion-archive":
        Path(action["backlog"]).write_text(action["previous_backlog"])
        archive = Path(action["archive"])
        if action["previous_archive"] is None:
            archive.unlink(missing_ok=True)
        else:
            archive.write_text(action["previous_archive"])
        print("Restored suggestion.")


def maybe_commit(cfg, message, stdin, isatty):
    """Commit the brain on an explicit yes at a terminal. Never pushes."""
    if not isatty:
        return
    root = str(cfg.root)
    env = git_env()
    probe = subprocess.run(
        ["git", "-C", root, "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True, env=env,
    )
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return
    print("Commit this change? [y/N]")
    try:
        ans = stdin.readline()
    except Exception:
        return
    if ans.strip().lower() not in {"y", "yes"}:
        print("Not committed.")
        return
    add = subprocess.run(["git", "-C", root, "add", "-A"], capture_output=True, text=True, env=env)
    if add.returncode != 0:
        print(add.stderr.strip() or "git add failed")
        return
    commit = subprocess.run(
        ["git", "-C", root, "commit", "-m", message],
        capture_output=True, text=True, env=env,
    )
    if commit.returncode != 0:
        print(commit.stderr.strip() or commit.stdout.strip() or "Nothing committed.")
        return
    print("Committed. Not pushed.")


def run(cfg, stdin=None, isatty=None):
    stdin = stdin or sys.stdin
    if isatty is None:
        isatty = _isatty(stdin)
    skipped = set()
    history = []
    seen = False
    while True:
        cards = [c for c in load_cards(cfg) if c["id"] not in skipped]
        if not cards:
            if not history:
                print("Nothing to review." if not seen else "Done.")
                return 0
            print("No cards left. undo / quit")
            cmd = read_cmd(stdin)
            if cmd in {"quit", "skip"}:
                print("Done.")
                return 0
            if cmd == "undo":
                action = history.pop()
                if action["op"] == "skip":
                    skipped.discard(action["id"])
                    print("Undid skip.")
                else:
                    revert(cfg, action)
            elif cmd:
                print("No cards left. undo or quit.")
            continue
        seen = True
        card = cards[0]
        show(card, len(cards))
        cmd = read_cmd(stdin)
        if cmd == "quit":
            print("Done.")
            return 0
        if not cmd:
            print("Type keep, fix, archive, skip, or undo.")
            continue
        if cmd == "undo":
            if not history:
                print("Nothing to undo.")
                continue
            action = history.pop()
            if action["op"] == "skip":
                skipped.discard(action["id"])
                print("Undid skip.")
            else:
                revert(cfg, action)
            continue
        if cmd == "skip":
            skipped.add(card["id"])
            history.append({"op": "skip", "id": card["id"]})
            print("Skipped.")
            continue
        if cmd == "keep":
            history.append({"op": "keep", "key": remember(cfg, card)})
            continue
        try:
            if cmd == "archive":
                action = archive_suggestion(cfg, card) if card["kind"] == "suggestion" else archive_lint(cfg, card)
                if action:
                    history.append(action)
                    maybe_commit(cfg, f"review: archive {card['file']}", stdin, isatty)
            elif cmd == "fix":
                action = do_fix(cfg, card)
                if action:
                    history.append(action)
                    maybe_commit(cfg, f"review: edit {card['file']}", stdin, isatty)
        except (OSError, RuntimeError) as exc:
            print(f"Could not {cmd}: {exc}")
    return 0


def main(argv=None, stdin=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    cfg = cfgmod.load()
    if cfg is None:
        print("Not inside a brain (no teambrain.yaml).\nfix: brain init <path-to-notes>")
        return 1
    if cfgmod.is_engine_tree(cfg.root):
        print("This folder is the Alma engine, not a brain.\nfix: brain init <path-to-notes>")
        return 1
    return run(cfg, stdin=stdin)


if __name__ == "__main__":
    sys.exit(main())
