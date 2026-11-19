"""Snapshot your uncommitted work in the brain to a local branch wip/<you>. Never pushes.

  brain wip ["message"]

Built in a throwaway index, so your current branch, your staging area and main stay untouched
and `git pull` stays conflict-free. Git-ignored files are never included.
Nightly: add `{name: wip, run: "wip", at: "03:00"}` to schedule.jobs (optionally `when: <question id>`).
Share later: git push <remote> wip/<you>, then open a pull request.

Refuses (exit 2) when `wip/<you>` is the branch you have checked out, or the snapshot adds a
likely secret, an email whose domain is outside `wip.allow_email_domains` (exact domain or a
subdomain), or a file larger than `wip.max_file_mb`.
"""
import datetime
import getpass
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config as cfgmod

# Written so that this file never matches its own patterns.
SECRET_PATTERNS = [
    r"_auth[T]oken",
    r"xox[abp]-[0-9A-Za-z-]{10,}",
    r"AKIA[0-9A-Z]{16}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY",
    r"sk-ant-[A-Za-z0-9_-]{20,}",
    r"sk_live_[0-9A-Za-z]{10,}",
    r"ATATT[0-9A-Za-z_-]{20,}",
    r"gh[pousr]_[A-Za-z0-9]{30,}",
]
SECRET_RE = re.compile("|".join(SECRET_PATTERNS))
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")

# Caller environment must not redirect git at another repo or the user's index.
# GIT_COMMON_DIR is cleared too, matching `bin/brain snapshot`.
_GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


def git_env(overlay=None):
    """Environment for git subprocesses. Drops GIT_DIR, GIT_WORK_TREE and GIT_INDEX_FILE.

    `overlay` may set GIT_INDEX_FILE to a throwaway index. GIT_DIR, GIT_WORK_TREE and
    GIT_COMMON_DIR coming in through `overlay` are ignored.
    """
    env = {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_VARS}
    for k, v in (overlay or {}).items():
        if k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
            continue
        env[k] = v
    return env


def _git(root, *args, env=None, check=True):
    r = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, errors="replace", env=git_env(env),
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def _norm_domain(value):
    a = str(value).strip().lower()
    if a.startswith("@"):
        a = a[1:]
    if a.startswith("*."):
        a = a[2:]
    return a.strip(".")


def email_allowed(addr, allow_domains):
    """True when the address domain equals an allow entry, or is a subdomain of one.

    An entry example.com allows that domain and a.example.com. It does not allow a domain
    that merely contains that text, or a longer domain that only starts with it.
    """
    if "@" not in addr:
        return False
    domain = addr.rsplit("@", 1)[1].lower().rstrip(".")
    if not domain:
        return False
    for raw in allow_domains:
        allowed = _norm_domain(raw)
        if allowed and (domain == allowed or domain.endswith("." + allowed)):
            return True
    return False


def who(root):
    email = _git(root, "config", "user.email", check=False)
    me = email.split("@")[0] if email else getpass.getuser()
    return re.sub(r"[^A-Za-z0-9._-]+", "-", me).strip("-.") or "me"


def scan(diff, allow_domains):
    """Problems in the added lines of a unified diff: (secrets, emails)."""
    added = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    secrets = sorted({m.group(0)[:12] + "…" for l in added for m in SECRET_RE.finditer(l)})
    emails = sorted({e for l in added for e in EMAIL_RE.findall(l)
                     if not email_allowed(e, allow_domains)})
    return secrets, emails


def _over_limit(root, rel, limit):
    path = Path(root) / rel
    try:
        return path.is_file() and path.stat().st_size > limit
    except OSError:
        return False


def snapshot(cfg, message=None, out=print):
    """Commit the working tree to wip/<you>. Returns 0 (saved or nothing to do), 2 (refused), 1 (error)."""
    w = cfg["wip"]
    root = cfg.root
    if _git(root, "rev-parse", "--is-inside-work-tree", check=False) != "true":
        out(f"wip: {root} is not a git repository")
        return 1
    if not _git(root, "rev-parse", "-q", "--verify", "HEAD", check=False):
        out("wip: no commits yet; nothing to snapshot against")
        return 1
    branch = f"{w['branch_prefix']}{who(root)}"
    ref = f"refs/heads/{branch}"
    if _git(root, "symbolic-ref", "-q", "HEAD", check=False) == ref:
        out(f"wip: refusing to snapshot because {branch} is the branch you have checked out. "
            f"Switch to another branch and re-run. Nothing was changed.")
        return 2
    tip = _git(root, "rev-parse", "-q", "--verify", ref, check=False)
    base = tip or "HEAD"

    with tempfile.TemporaryDirectory() as tmp:
        index_env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(root, "read-tree", base, env=index_env)
        _git(root, "add", "-A", env=index_env)
        tree = _git(root, "write-tree", env=index_env)
        head_in_tip = bool(tip) and subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", "HEAD", tip],
            capture_output=True, env=git_env()).returncode == 0
        if tree == _git(root, "rev-parse", f"{base}^{{tree}}") and (not tip or head_in_tip):
            out("wip: nothing to commit")
            return 0

        # Size is decided from filenames and stat, before any diff body is read.
        changed = _git(root, "diff", "--cached", "--name-only", "--diff-filter=AM",
                       "HEAD", env=index_env).splitlines()
        limit = float(w["max_file_mb"]) * 1_000_000
        big = [f for f in changed if _over_limit(root, f, limit)]
        if big:
            out("wip: REFUSED. Remove these or move them to a git-ignored folder, then re-run.")
            out(f"  files over {w['max_file_mb']} MB: {', '.join(big)}")
            return 2

        skip = [f":!{p}" for p in w["skip_scan"]]
        diff = _git(root, "diff", "--cached", "-U0", "--diff-filter=AM", "HEAD",
                    "--", ".", *skip, env=index_env)
        secrets, emails = scan(diff, w["allow_email_domains"])
        if secrets or emails:
            out("wip: REFUSED. Remove these or move them to a git-ignored folder, then re-run.")
            if secrets:
                out(f"  possible secrets: {', '.join(secrets[:3])}")
            if emails:
                out(f"  emails outside wip.allow_email_domains: {', '.join(emails[:5])}")
            return 2

        # Parents: the previous snapshot, plus your branch when it has moved on (e.g. after a pull),
        # so a pull request from wip/<you> shows only your own changes.
        parents = []
        if tip:
            parents += ["-p", tip]
        if not head_in_tip:
            parents += ["-p", _git(root, "rev-parse", "HEAD")]
        n = len(_git(root, "diff", "--cached", "--name-only", "HEAD", env=index_env).splitlines())
        msg = message or f"wip: {datetime.datetime.now():%Y-%m-%d %H:%M} ({n} files differ from your branch)"
        commit = _git(root, "commit-tree", tree, *parents, "-m", msg, env=index_env)
        _git(root, "update-ref", "-m", "brain wip", ref, commit, *([tip] if tip else []))
    out(f"wip: saved to {branch} ({n} files differ from your branch)")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cfg = cfgmod.load()
    if cfg is None:
        print("wip: not inside a brain (no teambrain.yaml; set BRAIN_ROOT)", file=sys.stderr)
        return 1
    try:
        return snapshot(cfg, " ".join(argv) or None)
    except RuntimeError as e:
        print(f"wip: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
