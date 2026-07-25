#!/usr/bin/env python3
"""drc_engine_coverage_check.py — gate that FAILS when the project spec
requires a DRC engine that did not execute.

Chip-AGNOSTIC and PDK-agnostic.  The required engine set is configurable
(CLI flag or caller API) so it is never hard-coded to a specific PDK or
design.  The check is intentionally a DISCLOSURE gate, not a silent pass:
  - A 0-violation report from one engine NEVER satisfies a two-engine
    requirement.
  - A vacuously-run engine (geometry not loaded) is NOT counted as a
    real run.
  - An empty/absent required set yields an explicit vacuous-pass note
    rather than a crash or a silent pass.

Usage:
  python drc_engine_coverage_check.py <project_dir> \\
      --required klayout magic

Exit codes:
  0  PASS (all required engines ran, or required set is empty)
  1  FAIL (at least one required engine is absent from engines_run)
  2  ERROR (drc_signoff.json absent / unreadable — report presence,
             not geometry, so the missing-report gate fires too)

The check reads engines_run from reports/phase3/drc_signoff.json (written
by phase3_one_shot_runner:step_drc).  engines_run entries that end with
"(vacuous)" are excluded: magic(vacuous) means Magic ran but loaded no
geometry and its result is unreliable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


_DEFAULT_REQUIRED: List[str] = []  # empty = vacuous-pass by default


# ---------------------------------------------------------------------------
# Core logic — importable for tests
# ---------------------------------------------------------------------------

def load_engines_run(project: Path) -> Optional[List[str]]:
    """Load engines_run from reports/phase3/drc_signoff.json.
    Returns None when the file is absent or unreadable."""
    candidates = [
        project / "reports" / "phase3" / "drc_signoff.json",
        project / "reports" / "drc_signoff.json",
    ]
    for cand in candidates:
        if cand.is_file():
            try:
                d: Any = json.loads(cand.read_text(encoding="utf-8",
                                                    errors="replace"))
                if isinstance(d, dict):
                    er = d.get("engines_run")
                    if isinstance(er, list):
                        return [str(e) for e in er]
            except Exception:
                pass
    return None


def normalise_engine(name: str) -> str:
    """Strip trailing parenthetical qualifiers (e.g. '(vacuous)') and
    lower-case so comparison is case-insensitive."""
    base = name.split("(")[0].strip().lower()
    return base


def engines_ran_clean(engines_run: List[str]) -> Set[str]:
    """Return the set of engine names that ran non-vacuously."""
    result: Set[str] = set()
    for e in engines_run:
        if "(vacuous)" in e.lower():
            continue
        result.add(normalise_engine(e))
    return result


def check_coverage(engines_run: List[str],
                   required: List[str]) -> Dict[str, Any]:
    """Core gate logic.  Returns a result dict with keys:
      status   : "PASS" | "FAIL" | "VACUOUS_PASS"
      missing  : list of required engines not in engines_ran_clean
      ran      : list of clean engines (normalised)
      note     : human message
    """
    if not required:
        return {
            "status": "VACUOUS_PASS",
            "missing": [],
            "ran": list(engines_ran_clean(engines_run)),
            "note": "Required engine set is empty — vacuous pass "
                    "(no spec constraint to evaluate).",
        }

    req_norm: Set[str] = {normalise_engine(r) for r in required}
    ran = engines_ran_clean(engines_run)
    missing = sorted(req_norm - ran)

    if missing:
        return {
            "status": "FAIL",
            "missing": missing,
            "ran": sorted(ran),
            "note": (
                f"DRC engine coverage FAIL: required {sorted(req_norm)} "
                f"but only {sorted(ran)} ran clean.  "
                f"Missing: {missing}.  "
                "A 0-violation report from one engine does NOT satisfy "
                "a multi-engine requirement."
            ),
        }
    return {
        "status": "PASS",
        "missing": [],
        "ran": sorted(ran),
        "note": (
            f"DRC engine coverage PASS: all required engines ran — "
            f"{sorted(req_norm)}."
        ),
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("project", type=Path,
                   help="Project root directory containing reports/")
    p.add_argument("--required", nargs="*", default=_DEFAULT_REQUIRED,
                   metavar="ENGINE",
                   help="Required engine names (e.g. klayout magic).  "
                        "Empty list => vacuous-pass with a note.")
    p.add_argument("--json-out", type=Path, default=None,
                   metavar="FILE",
                   help="Write JSON result to FILE (optional).")
    args = p.parse_args(argv)

    engines_run = load_engines_run(args.project)
    if engines_run is None:
        msg = (f"ERROR: drc_signoff.json not found or unreadable under "
               f"{args.project / 'reports'}.  "
               "Run phase3_one_shot_runner (step_drc) first.")
        print(msg, file=sys.stderr)
        result = {
            "status": "ERROR",
            "missing": args.required or [],
            "ran": [],
            "note": msg,
        }
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(json.dumps(result, indent=2) + "\n")
        return 2

    result = check_coverage(engines_run, args.required or [])
    result["engines_run_raw"] = engines_run

    if args.json_out:
        try:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(json.dumps(result, indent=2) + "\n")
        except OSError as exc:
            print(f"WARNING: could not write json-out: {exc}", file=sys.stderr)

    status = result["status"]
    print(result["note"])
    return 0 if status in ("PASS", "VACUOUS_PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
