"""Deterministic hygiene checks for the brain's markdown. No network, no model, never edits.

    brain lint [--json]

Rules
  DOC-SELF-STALE   medium  a doc's own title/status lines call it stale / superseded / "kept for history":
                           delete it or fold what's still true into a living page
  TEMP-IDLE        low     a working folder (lint.temp_glob) with no file edited for lint.idle_days:
                           fold the conclusion into the wiki, then delete the folder
  DUP-FILE         medium  identical markdown files, or two docs with the same H1 title
  BROKEN-DOC-LINK  low     a relative markdown link to a file that no longer exists
"""
import argparse
import fnmatch
import glob
import hashlib
import json
import os
import re
import sys
import time

from teambrain import config as cfgmod

SELF_STALE = re.compile(r"\b(stale|superseded by|kept (only )?for history|delete this (folder|file|doc))\b", re.I)
STATUS_LINE = re.compile(r"^(#|>|\*\*(status|state|history)|(status|state|what this (was|is))\b)", re.I)
LINK = re.compile(r"\]\((?!https?:|#|mailto:)([^)\s#]+)")
GENERIC_TITLES = {"README.md", "SKILL.md", "notes.md"}


def _read(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def docs(cfg):
    skip = cfg["index"]["skip"] + cfg["lint"]["skip"]
    out = []
    for folder, forced in cfg.index_dirs():
        if forced is not None or not folder.exists():
            continue  # extra dirs live outside the brain
        for p in sorted(folder.rglob("*.md")):
            if not any(s in str(p) for s in skip):
                out.append(str(p))
    return out


def check(cfg, now=None):
    now = now or time.time()
    lc = cfg["lint"]
    root = str(cfg.root)
    rel = lambda p: os.path.relpath(p, root)
    findings = []

    def add(rule, severity, path, line, message):
        findings.append({"rule": rule, "severity": severity, "file": rel(path), "line": line, "message": message})

    by_hash, by_title = {}, {}
    for p in docs(cfg):
        t = _read(p)
        by_hash.setdefault(hashlib.sha256(t.encode()).hexdigest(), []).append(p)
        h1 = re.search(r"^# (.+)$", t, re.M)
        if h1 and os.path.basename(p) not in GENERIC_TITLES:
            by_title.setdefault(h1.group(1).strip().lower(), []).append(p)

        if not any(fnmatch.fnmatch(rel(p), g) for g in lc["no_link_check"]):
            for m in LINK.finditer(t):
                target = os.path.normpath(os.path.join(os.path.dirname(p), m.group(1)))
                if not os.path.exists(target):
                    add("BROKEN-DOC-LINK", "low", p, t[: m.start()].count("\n") + 1,
                        f"Links to missing `{m.group(1)}`")

        # Only the doc's own title/status lines near the top, not quotes of or links to other docs.
        for i, line in enumerate(t.splitlines()[:15], 1):
            hit = STATUS_LINE.match(line.strip()) and SELF_STALE.search(line)
            if hit:
                add("DOC-SELF-STALE", "medium", p, i,
                    f"Doc marks itself \"{hit.group(0)}\": delete it or fold what's still true into a living page")
                break

    # File dates, not git: working folders are often git-ignored.
    for d in sorted(glob.glob(os.path.join(root, lc["temp_glob"]))):
        if not os.path.isdir(d):
            continue
        mtimes = [os.path.getmtime(f) for f in glob.glob(os.path.join(d, "**", "*"), recursive=True)
                  if os.path.isfile(f) and "/node_modules/" not in f]
        idle = (now - max(mtimes)) / 86400 if mtimes else 0
        if idle >= lc["idle_days"]:
            add("TEMP-IDLE", "low", os.path.join(d, "README.md"), None,
                f"No edits for {int(idle)} days: fold the answer into the wiki and delete the folder")

    for group in by_hash.values():
        if len(group) > 1:
            add("DUP-FILE", "medium", group[0], None,
                "Identical content: " + ", ".join(f"`{rel(x)}`" for x in group[1:]))
    for title, group in by_title.items():
        if len(group) > 1:
            add("DUP-FILE", "medium", group[0], None,
                f"Same title \"{title}\" as " + ", ".join(f"`{rel(x)}`" for x in group[1:]) + ": merge or rename")
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(findings, key=lambda f: (order[f["severity"]], f["rule"], f["file"]))


def render(findings):
    if not findings:
        return "No findings."
    lines = [f"{len(findings)} findings", ""]
    for f in findings:
        where = f["file"] + (f":{f['line']}" if f["line"] else "")
        lines.append(f"- [{f['severity']}] {f['rule']} {where} — {f['message']}")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    cfg = cfgmod.load()
    if cfg is None:
        sys.exit("Not inside a brain (no teambrain.yaml found; set BRAIN_ROOT).")
    result = check(cfg)
    print(json.dumps(result, ensure_ascii=False, indent=1) if a.json else render(result))
