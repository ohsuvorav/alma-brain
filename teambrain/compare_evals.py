#!/usr/bin/env python3
"""
Compare eval pass rate: current CLAUDE.md vs. a proposed version.

Usage:
  brain eval-compare path/to/proposed_CLAUDE.md
  brain eval-compare path/to/proposed_CLAUDE.md case_id1 case_id2

Exit 0 = no regressions. Exit 1 = regressions found.
"""
import sys
from pathlib import Path

from teambrain.evals import BASELINE_SYSTEM_FILE, load_cases, claude, judge


def score_cases(cases: list, system_file: Path) -> dict:
    results = {}
    for case in cases:
        print(f"  {case['id']} ... ", end="", flush=True)
        response = claude(case["input"], system_file=system_file)
        j = judge(case, response)
        verdict = j.get("overall", "error")
        results[case["id"]] = {"verdict": verdict, "notes": j.get("notes", "")}
        print(verdict)
    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: compare_evals.py proposed_CLAUDE.md [case_id ...]")
        sys.exit(1)

    proposed_path = Path(sys.argv[1])
    if not proposed_path.exists():
        print(f"File not found: {proposed_path}")
        sys.exit(1)

    case_filter = set(sys.argv[2:]) if len(sys.argv) > 2 else None
    cases = load_cases()
    if case_filter:
        cases = [c for c in cases if c["id"] in case_filter]
    if not cases:
        print("No cases found.")
        sys.exit(1)

    baseline_file = BASELINE_SYSTEM_FILE
    print(f"\nBaseline ({len(cases)} cases):")
    baseline = score_cases(cases, baseline_file)

    print(f"\nProposed ({proposed_path.name}):")
    proposed = score_cases(cases, proposed_path)

    improved, regressed, unchanged = [], [], []
    for cid in baseline:
        b, p = baseline[cid]["verdict"], proposed[cid]["verdict"]
        if b == p:
            unchanged.append(cid)
        elif p == "pass":
            improved.append((cid, b, p, proposed[cid]["notes"]))
        else:
            regressed.append((cid, b, p, proposed[cid]["notes"]))

    print("\n── Delta ───────────────────────────────")
    if improved:
        print(f"\n✓ Improved ({len(improved)}):")
        for cid, b, p, notes in improved:
            print(f"  {cid}: {b} → {p}  {notes}")
    if regressed:
        print(f"\n✗ Regressed ({len(regressed)}):")
        for cid, b, p, notes in regressed:
            print(f"  {cid}: {b} → {p}  {notes}")
    print(f"\n○ Unchanged: {len(unchanged)}")

    base_pass = sum(1 for v in baseline.values() if v["verdict"] == "pass")
    prop_pass = sum(1 for v in proposed.values() if v["verdict"] == "pass")
    total = len(cases)
    print(f"\nScore: {base_pass}/{total} → {prop_pass}/{total}")
    verdict = "SAFE TO MERGE" if not regressed else "REGRESSIONS — review before merging"
    print(f"\n{verdict}\n")
    sys.exit(0 if not regressed else 1)


if __name__ == "__main__":
    main()
