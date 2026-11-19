#!/usr/bin/env python3
"""
Brain eval runner.
Uses `claude -p` (Claude Code CLI, subscription) to get responses.
LLM-as-judge scoring uses a second `claude -p` call.
Cases, results and the system prompt file come from teambrain.yaml `evals`.

Usage:
  brain eval              # run all cases
  brain eval decision_01  # run specific case IDs

Autoresearch loop usage (score a candidate without touching the live file):
  EVAL_SYSTEM_FILE=/tmp/candidate_CLAUDE.md EVAL_OUT=/tmp/r.json brain eval

Output metric: SCORE = (criteria hit) / (criteria total), 0.0-1.0. Higher is better.
"""

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

from teambrain import config as cfgmod

_cfg = cfgmod.load()
if _cfg is None:
    sys.exit("Not inside a brain (no teambrain.yaml found; set BRAIN_ROOT).")
CASES_DIR = _cfg.path(_cfg["evals"]["cases_dir"])
RESULTS_DIR = _cfg.path(_cfg["evals"]["results_dir"])
BASELINE_SYSTEM_FILE = _cfg.path(_cfg["evals"]["system_file"])

# Set by --system / --out so the autoresearch loop can score a candidate
# CLAUDE.md without touching the real one.
SYSTEM_FILE = os.environ.get("EVAL_SYSTEM_FILE")
OUT_PATH = os.environ.get("EVAL_OUT")


def load_cases() -> list[dict]:
    cases = []
    for fpath in sorted(CASES_DIR.glob("*.yaml")):
        content = fpath.read_text()
        for doc in content.split("\n---\n"):
            doc = doc.strip()
            if not doc:
                continue
            try:
                case = yaml.safe_load(doc)
                if case and "id" in case:
                    cases.append(case)
            except yaml.YAMLError as e:
                print(f"YAML error in {fpath.name}: {e}", file=sys.stderr)
    return cases


def claude(prompt: str, system_file=None) -> str:
    cmd = ["claude", "-p", prompt]
    if system_file:
        cmd += ["--system-prompt", f"@{system_file}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    return result.stdout.strip()


JUDGE_TEMPLATE = """Evaluate this AI second-brain response against quality criteria.

Case: {description}

User input:
{input}

AI response:
{response}

MUST do (expect):
{expect}

MUST NOT do (avoid):
{avoid}

Score each criterion 0 or 1. Be strict. Reply ONLY with JSON, no prose:
{{
  "expect_scores": {{"criterion_text": 0_or_1}},
  "avoid_scores": {{"criterion_text": 1_if_avoided_0_if_present}},
  "overall": "pass" or "fail",
  "notes": "one sentence on most important issue or strength"
}}"""


def judge(case: dict, response: str) -> dict:
    expect_lines = "\n".join(f"- {e}" for e in case.get("expect", []))
    avoid_lines = "\n".join(f"- {e}" for e in case.get("avoid", []))
    prompt = JUDGE_TEMPLATE.format(
        description=case.get("description", ""),
        input=case["input"].strip(),
        response=response,
        expect=expect_lines,
        avoid=avoid_lines,
    )
    raw = claude(prompt)
    # Strip markdown fences
    if "```" in raw:
        parts = raw.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            try:
                return json.loads(p)
            except Exception:
                continue
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"overall": "error", "notes": f"judge parse failed: {raw[:120]}"}


def score_judgment(j: dict) -> tuple[int, int]:
    """Collapse a judgment into (hits, total_criteria). This is the metric."""
    hits = total = 0
    for key in ("expect_scores", "avoid_scores"):
        for _, v in (j.get(key) or {}).items():
            total += 1
            hits += 1 if v in (1, True, "1") else 0
    return hits, total


def criterion_rollup(results: list) -> dict:
    """Per-criterion hit rate across all cases — shows which rule is failing."""
    roll = {}
    for r in results:
        j = r.get("judgment", {})
        for key in ("expect_scores", "avoid_scores"):
            for crit, v in (j.get(key) or {}).items():
                slot = roll.setdefault(crit, {"hits": 0, "total": 0})
                slot["total"] += 1
                slot["hits"] += 1 if v in (1, True, "1") else 0
    return roll


def run() -> None:
    cases = load_cases()
    if not cases:
        print("No cases found in", CASES_DIR)
        sys.exit(0)

    if len(sys.argv) > 1:
        ids = set(sys.argv[1:])
        cases = [c for c in cases if c["id"] in ids]
        if not cases:
            print(f"No cases match: {ids}")
            sys.exit(1)

    system_file = Path(SYSTEM_FILE) if SYSTEM_FILE else BASELINE_SYSTEM_FILE
    results = []
    passed = failed = 0
    hits_all = total_all = 0

    for case in cases:
        cid = case["id"]
        print(f"  {cid} ... ", end="", flush=True)

        response = claude(case["input"], system_file=system_file)
        judgment = judge(case, response)

        verdict = judgment.get("overall", "error")
        hits, total = score_judgment(judgment)
        hits_all += hits
        total_all += total
        pct = (100.0 * hits / total) if total else 0.0

        symbol = "✓" if verdict == "pass" else "✗"
        print(f"{symbol} {hits}/{total} ({pct:.0f}%) {verdict}")
        if judgment.get("notes"):
            print(f"    {judgment['notes']}")

        if verdict == "pass":
            passed += 1
        else:
            failed += 1

        results.append({
            "id": cid,
            "description": case.get("description", ""),
            "verdict": verdict,
            "hits": hits,
            "total": total,
            "score": round(hits / total, 4) if total else 0.0,
            "judgment": judgment,
            "response_preview": response[:400],
        })

    score = round(hits_all / total_all, 4) if total_all else 0.0
    payload = {
        "date": str(date.today()),
        "system_file": str(system_file),
        "score": score,
        "hits": hits_all,
        "total": total_all,
        "cases_passed": passed,
        "cases_total": passed + failed,
        "criteria": criterion_rollup(results),
        "cases": results,
    }

    out_path = Path(OUT_PATH) if OUT_PATH else RESULTS_DIR / f"{date.today()}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    print(f"\nSCORE {hits_all}/{total_all} = {100*score:.1f}%   "
          f"(cases {passed}/{passed+failed} clean)")
    print(f"  → {out_path}")

    weakest = sorted(
        ((c, v["hits"] / v["total"]) for c, v in payload["criteria"].items() if v["total"]),
        key=lambda x: x[1],
    )[:5]
    if weakest:
        print("\nWeakest criteria:")
        for crit, rate in weakest:
            print(f"  {100*rate:3.0f}%  {crit[:90]}")

    sys.exit(0)


if __name__ == "__main__":
    run()
