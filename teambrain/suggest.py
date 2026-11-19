"""Compare your own Claude Code setup (~/.claude) with the brain and propose improvements as a pull request.

  brain suggest

Claude runs unattended in a separate worktree on branch suggest/<you>-<date>-<time> (off `suggest.base`),
reads your ~/.claude (not chats, memory or secrets) and writes only generic improvements plus
SUGGESTIONS.md. You see the summary and diff first; nothing is pushed without your yes.
A likely secret or an email outside `wip.allow_email_domains` refuses the push.
"""
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

from . import config as cfgmod
from .wip import _git, scan, who

ENGINE = Path(__file__).resolve().parent.parent
DEFAULT_PROMPT = ENGINE / "templates" / "suggest" / "prompt.md"


def pr_url(remote_url, branch, base_branch):
    """Link that opens a new pull request on GitHub, Bitbucket or GitLab; None for other hosts."""
    m = (re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?/?$", remote_url)
         or re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", remote_url))
    if not m:
        return None
    host, repo = m.group(1).lower(), m.group(2)
    if host.endswith("github.com"):
        return f"https://github.com/{repo}/compare/{base_branch}...{branch}?expand=1"
    if host.endswith("bitbucket.org"):
        return f"https://bitbucket.org/{repo}/pull-requests/new?source={branch}&dest={base_branch}&t=1"
    if host.endswith("gitlab.com"):
        return (f"https://gitlab.com/{repo}/-/merge_requests/new?merge_request[source_branch]={branch}"
                f"&merge_request[target_branch]={base_branch}")
    return None


def prompt_text(cfg):
    s = cfg["suggest"]
    path = cfg.path(s["prompt_file"]) if s["prompt_file"] else DEFAULT_PROMPT
    return (path.read_text().replace("{name}", str(cfg["name"]))
            .replace("{max_changes}", str(s["max_changes"])))


def run(cfg, inp=input, out=print):
    s = cfg["suggest"]
    root = cfg.root
    remote, _, base_branch = s["base"].partition("/")
    if not base_branch:
        raise ValueError(f"suggest.base must look like <remote>/<branch>, got {s['base']!r}")
    branch = f"{s['branch_prefix']}{who(root)}-{datetime.datetime.now():%Y%m%d-%H%M}"  # one branch per run
    wt = cfg.state_dir / "suggest-worktree"

    _git(root, "fetch", "-q", remote, base_branch)
    if wt.exists():
        _git(root, "worktree", "remove", "--force", str(wt), check=False)
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(root, "worktree", "add", "-q", "-B", branch, str(wt), s["base"])

    out("Claude is comparing your setup with the brain (a few minutes)...")
    r = subprocess.run([s["claude_bin"], "-p", prompt_text(cfg),
                        "--add-dir", os.path.expanduser("~/.claude"),
                        "--permission-mode", "acceptEdits",
                        "--allowedTools", "Read", "Glob", "Grep", "Edit", "Write"],
                       cwd=wt, stdout=subprocess.DEVNULL)
    if r.returncode != 0:
        out("suggest: the Claude run failed; nothing changed")
        return 1

    _git(wt, "add", "-A")
    summary = wt / "SUGGESTIONS.md"
    if not summary.is_file():
        out("suggest: no SUGGESTIONS.md written; nothing to share")
        return 0
    out("\n" + summary.read_text())
    files = [f for f in _git(wt, "diff", "--cached", "--name-only").splitlines() if f != "SUGGESTIONS.md"]
    if not files:
        out("Nothing to suggest: your setup has nothing the brain is missing.")
        return 0
    out(_git(wt, "diff", "--cached", "--stat"))
    out(f"\nReview the full diff:  git -C {wt} diff --cached")
    # Same scanner as `brain wip`. SUGGESTIONS.md is not part of the commit.
    diff = _git(wt, "diff", "--cached", "-U0", "--diff-filter=AM", "--", ".", ":!SUGGESTIONS.md")
    secrets, emails = scan(diff, cfg["wip"]["allow_email_domains"])
    if secrets or emails:
        out("suggest: REFUSED. Nothing was pushed.")
        if secrets:
            out(f"  possible secrets: {', '.join(secrets[:3])}")
        if emails:
            out(f"  emails outside wip.allow_email_domains: {', '.join(emails[:5])}")
        return 2
    if not sys.stdin.isatty() and inp is input:
        out(f"Kept local in {wt} (not pushed; run in a terminal to push).")
        return 0
    try:
        ok = inp(f"Push branch {branch} and open a pull request? [y/N] ").strip().lower().startswith("y")
    except EOFError:
        ok = False
    if not ok:
        out(f"Kept local in {wt} (not pushed).")
        return 0
    _git(wt, "reset", "-q", "SUGGESTIONS.md")
    _git(wt, "commit", "-q", "-m", f"suggest: improvements from {who(root)}'s Claude setup",
         "-m", summary.read_text())
    _git(wt, "push", "-q", "-u", remote, branch)
    url = pr_url(_git(root, "remote", "get-url", remote), branch, base_branch)
    out(f"Pushed. Open the pull request: {url}" if url else f"Pushed {branch}; open a pull request on your git host.")
    return 0


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cfg = cfgmod.load()
    if cfg is None:
        print("suggest: not inside a brain (no teambrain.yaml; set BRAIN_ROOT)", file=sys.stderr)
        return 1
    try:
        return run(cfg)
    except (ValueError, RuntimeError) as e:
        print(f"suggest: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
