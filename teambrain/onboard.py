"""First-run setup for a teammate: build the index, ask the brain's yes/no opt-ins, install nightly jobs.

  brain onboard              ask each question in onboarding.questions (re-run any time to change answers)
  brain onboard --defaults   don't ask; use each question's default
  brain onboard --status     print the saved answers

A question: {id, ask, pros, cons, default: y|n, run, undo}. `run` (shell, in the brain root) runs on yes;
`undo` runs on no when the previous answer was yes. Both see BRAIN_ROOT and BRAIN (path to bin/brain).
Answers are personal: <state_dir>/onboarding.json. A schedule job with `when: <id>` is installed
only for people who answered yes to that question.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

from . import config as cfgmod

BRAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "brain")


def answers_path(cfg):
    return cfg.state_dir / "onboarding.json"


def load_answers(cfg):
    try:
        return json.loads(answers_path(cfg).read_text()).get("answers", {})
    except (OSError, ValueError):
        return {}


def onboarded(cfg):
    return answers_path(cfg).is_file()


def _read_state(cfg):
    try:
        data = json.loads(answers_path(cfg).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def schedule_failed(cfg):
    """True when the last schedule install could not run because cron or launchd was missing."""
    return _read_state(cfg).get("schedule_install") == "failed"


def mark_schedule_install(cfg, state):
    """Update schedule_install on an existing answers file. Does not create one."""
    p = answers_path(cfg)
    if not p.is_file():
        return
    data = _read_state(cfg)
    if not data:
        return
    data["schedule_install"] = state
    p.write_text(json.dumps(data, indent=2) + "\n")


def _save(cfg, answers, schedule_install):
    p = answers_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "answers": answers,
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "schedule_install": schedule_install,
    }, indent=2) + "\n")


def questions(cfg):
    out, seen = [], set()
    for q in cfg["onboarding"]["questions"] or []:
        qid = str(q.get("id", "")).strip()
        if not qid or qid in seen or not q.get("ask"):
            raise ValueError(f"onboarding: each question needs a unique id and `ask`: {q!r}")
        if str(q.get("default", "n")).lower() not in ("y", "n", "yes", "no", "true", "false"):
            raise ValueError(f"onboarding: question {qid!r} default must be y or n")
        seen.add(qid)
        out.append(q)
    return out


def _default(q):
    return str(q.get("default", "n")).lower() in ("y", "yes", "true")


def ask(q, interactive, inp=input, out=print):
    d = _default(q)
    if not interactive:
        return d
    out(f"\n? {q['ask']}")
    if q.get("pros"):
        out(f"    + {q['pros']}")
    if q.get("cons"):
        out(f"    - {q['cons']}")
    a = inp(f"  [{'Y/n' if d else 'y/N'}] ").strip().lower()
    return d if not a else a.startswith("y")


def _sh(cfg, cmd, out):
    env = {**os.environ, "BRAIN_ROOT": str(cfg.root), "BRAIN": BRAIN}
    r = subprocess.run(cmd, shell=True, cwd=cfg.root, env=env)
    if r.returncode != 0:
        out(f"   failed (exit {r.returncode}): {cmd}")
    return r.returncode == 0


def run(cfg, interactive=True, inp=input, out=print, index=None, install_jobs=None):
    qs = questions(cfg)
    if not cfg.db_path.exists():
        out("Building the search index (first time: a few minutes)")
        (index or (lambda: subprocess.run([BRAIN, "index"], cwd=cfg.root, check=False)))()
    before = load_answers(cfg)
    answers = {}
    for q in qs:
        yes = ask(q, interactive, inp, out)
        if yes and q.get("run"):
            yes = _sh(cfg, q["run"], out)
        elif not yes and before.get(q["id"]) and q.get("undo"):
            _sh(cfg, q["undo"], out)
        answers[q["id"]] = yes
    summary = (" Your answers: " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in answers.items())
               if answers else "")
    # Record failure before installing. A missing scheduler then leaves the flag set, so the
    # session hook keeps offering `brain schedule install` instead of going quiet.
    if not cfg["schedule"]["jobs"]:
        _save(cfg, answers, "skipped")
        out(f"\nDone.{summary}\nRe-run `brain onboard` any time to change them.")
        return 0
    from .schedule import SchedulerMissing
    _save(cfg, answers, "failed")
    try:
        (install_jobs or _install_jobs)(cfg)
    except SchedulerMissing as e:
        out(f"\nAnswers saved.{summary}")
        out(str(e))
        return 1
    mark_schedule_install(cfg, "ok")
    out(f"\nDone.{summary}\nRe-run `brain onboard` any time to change them.")
    return 0


def _install_jobs(cfg):
    from . import schedule
    schedule.install(cfg)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--defaults", action="store_true", help="don't ask; use each question's default")
    ap.add_argument("--status", action="store_true", help="print the saved answers")
    a = ap.parse_args(argv)
    cfg = cfgmod.load()
    if cfg is None:
        print("onboard: not inside a brain (no teambrain.yaml; set BRAIN_ROOT)", file=sys.stderr)
        return 1
    try:
        if a.status:
            if not onboarded(cfg):
                print("not onboarded yet: run `brain onboard`")
                return 0
            ans = load_answers(cfg)
            print("\n".join(f"{k}: {'yes' if v else 'no'}" for k, v in ans.items()))
            if schedule_failed(cfg):
                print("nightly jobs: not installed; run `brain schedule install`")
            return 0
        return run(cfg, interactive=not a.defaults and sys.stdin.isatty())
    except (ValueError, RuntimeError) as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
