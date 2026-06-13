#!/usr/bin/env python3
"""coverage_closure.py — read coverage report; identify gaps.

Replaces skill `coverage-closure` (archived) for the deterministic-detection
portion. AI's `rtl-review` skill takes over for novel close-loop strategies.
"""
import argparse, json, sys
from pathlib import Path
import _path_layout as _pl

def main():
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    args = p.parse_args()
    cov = _pl.report_path(args.project, "coverage/coverage_actual.json")
    if not cov.is_file():
        print(f"[SKIP] coverage_closure: no {cov}")
        return 0
    try:
        d = json.loads(cov.read_text())
    except Exception as e:
        print(f"[FAIL] coverage_closure: parse {e}")
        return 1
    pct = d.get("coverage_pct") or d.get("pct") or 0
    threshold = 80
    if pct < threshold:
        print(f"[FAIL] coverage_closure: {pct}% < {threshold}%")
        return 1
    print(f"[PASS] coverage_closure: {pct}%")
    return 0

if __name__ == "__main__":
    sys.exit(main())
