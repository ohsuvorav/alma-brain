"""Install the brain's nightly jobs (retro, lint, snapshot, incremental index).

Jobs come from `schedule.jobs` in teambrain.yaml; nothing is scheduled until that list is set.

  brain schedule install [--dry-run]   write and load the jobs (replaces this brain's previous ones)
  brain schedule uninstall             remove this brain's jobs
  brain schedule status                list installed jobs and the last log line of each

macOS: one launchd agent per job in ~/Library/LaunchAgents (label teambrain.<name>.<job>).
Linux: a marked block in the user's crontab; lines outside the block are never touched.
Logs: <state_dir>/logs/<job>.log
"""
import argparse
import os
import platform
import plistlib
import re
import shlex
import subprocess
import sys
from pathlib import Path

from . import config as cfgmod

ENGINE = Path(__file__).resolve().parent.parent
BRAIN = ENGINE / "bin" / "brain"
# Subcommands that make no sense unattended (interactive, servers, hooks, venv setup).
REFUSED = {"setup", "mcp", "query", "hook-search", "hook-stop", "hook-session-start", "schedule", "help",
           "onboard", "suggest", "init", "review"}
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"


class SchedulerMissing(RuntimeError):
    """cron or launchd is not installed, so the jobs were not written."""

    def __init__(self, tool):
        self.tool = tool
        super().__init__(
            f"Nightly jobs were not installed because `{tool}` is not available. "
            f"Install {tool}, then run `brain schedule install`."
        )


def _scheduler(argv, **kwargs):
    try:
        return subprocess.run(argv, **kwargs)
    except FileNotFoundError:
        raise SchedulerMissing(argv[0]) from None


def _note_schedule_ok(cfg):
    from . import onboard
    onboard.mark_schedule_install(cfg, "ok")


def _slug(text):
    return re.sub(r"[^a-z0-9-]+", "-", str(text).lower()).strip("-") or "brain"


def label_prefix(cfg):
    return f"teambrain.{_slug(cfg['name'])}."


def jobs(cfg, path_env=None, answers=None):
    """Validated job specs from config: [{name, label, args, hour, minute, log, path}].

    A job with `when: <question id>` is kept only if this person answered yes in `brain onboard`.
    """
    from . import onboard
    out, seen = [], set()
    if answers is None:
        answers = onboard.load_answers(cfg)
    qids = {q["id"] for q in onboard.questions(cfg)}
    path_env = cfg["schedule"]["path"] or path_env or os.environ.get("PATH", "/usr/bin:/bin")
    for raw in cfg["schedule"]["jobs"] or []:
        name = _slug(raw.get("name", ""))
        if name in seen:
            raise ValueError(f"schedule: duplicate job name {name!r}")
        args = shlex.split(str(raw.get("run", "")))
        if not args or args[0] in REFUSED:
            raise ValueError(f"schedule: job {name!r} has no runnable brain command: {raw.get('run')!r}")
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(raw.get("at", "")))
        if not m or int(m[1]) > 23 or int(m[2]) > 59:
            raise ValueError(f"schedule: job {name!r} needs at: \"HH:MM\", got {raw.get('at')!r}")
        seen.add(name)
        when = raw.get("when")
        if when and when not in qids:
            raise ValueError(f"schedule: job {name!r} has when: {when!r}, which is not an onboarding question id")
        if when and not answers.get(when):
            continue
        out.append({
            "name": name,
            "label": label_prefix(cfg) + name,
            "args": args,
            "hour": int(m[1]),
            "minute": int(m[2]),
            "log": str(cfg.state_dir / "logs" / f"{name}.log"),
            "path": path_env,
        })
    return out


# launchd -----------------------------------------------------------------------
def plist(cfg, job):
    return plistlib.dumps({
        "Label": job["label"],
        "ProgramArguments": [str(BRAIN), *job["args"]],
        "WorkingDirectory": str(cfg.root),
        "EnvironmentVariables": {"BRAIN_ROOT": str(cfg.root), "PATH": job["path"]},
        "StartCalendarInterval": {"Hour": job["hour"], "Minute": job["minute"]},
        "StandardOutPath": job["log"],
        "StandardErrorPath": job["log"],
    })


def _launchctl(*args):
    return _scheduler(["launchctl", *args], capture_output=True, text=True)


def _installed_plists(cfg):
    return sorted(LAUNCH_AGENTS.glob(label_prefix(cfg) + "*.plist"))


def _launchd_uninstall(cfg):
    uid = os.getuid()
    for p in _installed_plists(cfg):
        _launchctl("bootout", f"gui/{uid}/{p.stem}")
        p.unlink()
        print(f"removed {p.stem}")


def _launchd_install(cfg, specs):
    _launchd_uninstall(cfg)
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    uid = os.getuid()
    for job in specs:
        p = LAUNCH_AGENTS / f"{job['label']}.plist"
        p.write_bytes(plist(cfg, job))
        r = _launchctl("bootstrap", f"gui/{uid}", str(p))
        if r.returncode != 0:
            raise RuntimeError(f"launchctl bootstrap {p.name} failed: {r.stderr.strip()}")
        print(f"installed {job['label']} at {job['hour']:02d}:{job['minute']:02d}")


# cron --------------------------------------------------------------------------
def _markers(cfg):
    tag = label_prefix(cfg).rstrip(".")
    return f"# >>> {tag} (managed by brain schedule)", f"# <<< {tag}"


def cron_line(cfg, job):
    env = f"BRAIN_ROOT={shlex.quote(str(cfg.root))} PATH={shlex.quote(job['path'])}"
    cmd = " ".join(shlex.quote(a) for a in [str(BRAIN), *job["args"]])
    return (f"{job['minute']} {job['hour']} * * * cd {shlex.quote(str(cfg.root))} && {env} {cmd}"
            f" >> {shlex.quote(job['log'])} 2>&1")


def cron_merge(cfg, current, specs):
    """`current` crontab with this brain's block replaced by `specs` (removed when empty)."""
    start, end = _markers(cfg)
    kept, inside = [], False
    for line in (current or "").splitlines():
        if line == start:
            inside = True
        elif line == end:
            inside = False
        elif not inside:
            kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    if specs:
        kept += ([""] if kept else []) + [start, *(cron_line(cfg, j) for j in specs), end]
    return "\n".join(kept) + "\n" if kept else ""


def _cron_read():
    r = _scheduler(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def installed_job_count(cfg):
    """How many of this brain's jobs are installed. None when cron or launchd is missing."""
    if _is_mac():
        return len(list(_installed_plists(cfg)))
    try:
        text = _cron_read()
    except SchedulerMissing:
        return None
    start, end = _markers(cfg)
    if start not in text:
        return 0
    block = text.split(start, 1)[-1].split(end, 1)[0]
    return sum(1 for line in block.splitlines() if line.strip() and not line.strip().startswith("#"))


def _cron_write(text):
    _scheduler(["crontab", "-"], input=text, text=True, check=True)


# commands ----------------------------------------------------------------------
def _is_mac():
    return platform.system() == "Darwin"


def install(cfg, dry_run=False):
    specs = jobs(cfg)
    if not specs:
        if cfg["schedule"]["jobs"]:
            if not dry_run:
                uninstall(cfg)  # every job is gated off by onboarding answers: remove ones installed earlier
                _note_schedule_ok(cfg)
            print("schedule: no jobs apply to you (onboarding answers); nothing installed")
        else:
            print("schedule: no jobs in teambrain.yaml (schedule.jobs); nothing to install")
        return 0
    if dry_run:
        for job in specs:
            print(plist(cfg, job).decode() if _is_mac() else cron_line(cfg, job))
        return 0
    Path(specs[0]["log"]).parent.mkdir(parents=True, exist_ok=True)
    if _is_mac():
        _launchd_install(cfg, specs)
    else:
        _cron_write(cron_merge(cfg, _cron_read(), specs))
        for job in specs:
            print(f"installed {job['label']} at {job['hour']:02d}:{job['minute']:02d} (crontab)")
    _note_schedule_ok(cfg)
    return 0


def uninstall(cfg):
    if _is_mac():
        _launchd_uninstall(cfg)
    else:
        _cron_write(cron_merge(cfg, _cron_read(), []))
        print("removed this brain's crontab block")
    return 0


def _last_line(path):
    try:
        lines = Path(path).read_text(errors="replace").strip().splitlines()
        return lines[-1][:160] if lines else "(empty log)"
    except OSError:
        return "(no log yet)"


def status(cfg):
    specs = {j["label"]: j for j in jobs(cfg)}
    if _is_mac():
        installed = [p.stem for p in _installed_plists(cfg)]
    else:
        start, end = _markers(cfg)
        block = _cron_read().split(start, 1)[-1].split(end, 1)[0] if start in _cron_read() else ""
        installed = [lbl for lbl in specs if specs[lbl]["log"] in block]
    for lbl in sorted(set(specs) | set(installed)):
        job = specs.get(lbl)
        state = "installed" if lbl in installed else "NOT installed"
        if job is None:
            print(f"{lbl}: installed but no longer in teambrain.yaml (run install to remove)")
            continue
        print(f"{lbl}: {state}, {job['hour']:02d}:{job['minute']:02d} `brain {' '.join(job['args'])}`"
              f" | last log: {_last_line(job['log'])}")
    if not specs and not installed:
        print("schedule: no jobs configured or installed")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["install", "uninstall", "status"])
    ap.add_argument("--dry-run", action="store_true", help="print what install would write")
    a = ap.parse_args(argv)
    cfg = cfgmod.load()
    if cfg is None:
        print("schedule: not inside a brain (no teambrain.yaml; set BRAIN_ROOT)", file=sys.stderr)
        return 1
    try:
        if a.action == "install":
            return install(cfg, a.dry_run)
        return uninstall(cfg) if a.action == "uninstall" else status(cfg)
    except SchedulerMissing as e:
        from . import onboard
        onboard.mark_schedule_install(cfg, "failed")
        print(e, file=sys.stderr)
        return 1
    except (ValueError, RuntimeError) as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
