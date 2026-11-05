#!/usr/bin/env python3
"""sim_dual_compare.py — one cocotb testbench, two simulators, one answer.

Step 4 runs its cocotb bundle under Icarus (4-state, event-driven). Verilator
(2-state, cycle-scheduled) is installed in the same image and cocotb drives it
with the same `make SIM=verilator`. A testbench whose per-case outcome differs
between the two is not evidence about the design until the difference is
explained: the usual causes are an X read as a value (Icarus fails, Verilator's
2-state 0 passes) or a race the two schedulers order differently.

MEASURED in the released image (cocotb 2.2.0.dev, Icarus 12, Verilator 5.053):
a flop with no reset read by `int(dut.q.value)` FAILS under Icarus with
`Cannot convert Logic('X') to int` and PASSES under Verilator; the same flop
with a synchronous reset passes under both. Those four JUnit files are the
calibration pair under `programs/calibration/sim_dual_*`.

The comparison is per CASE (classname, name), never per count: two suites with
the same pass total can pass different cases.

Exit: 0 both arms ran the same cases with identical outcomes; 1 a named
disagreement (SIM_DIFFERENTIAL_DISAGREES); 2 NOT_MEASURED (an arm's JUnit is
missing, unreadable or empty). chip-AGNOSTIC: JUnit structure only.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402

FINDING = "SIM_DIFFERENTIAL_DISAGREES"


def junit_cases(path: Path) -> Optional[Dict[Tuple[str, str], str]]:
    """`{(classname, name): PASS|FAIL|ERROR|SKIP}`, or None when unreadable."""
    try:
        root = ET.parse(str(path)).getroot()
    except (OSError, ET.ParseError):
        return None
    cases: Dict[Tuple[str, str], str] = {}
    for case in root.iter("testcase"):
        key = (case.get("classname") or "", case.get("name") or "")
        if case.find("error") is not None:
            outcome = "ERROR"
        elif case.find("failure") is not None:
            outcome = "FAIL"
        elif case.find("skipped") is not None:
            outcome = "SKIP"
        else:
            outcome = "PASS"
        cases[key] = outcome
    return cases


def compare_junit(a: Path, b: Path, *, a_name: str = "icarus",
                  b_name: str = "verilator") -> Dict[str, Any]:
    """Compare two JUnit files case by case."""
    left, right = junit_cases(a), junit_cases(b)
    arms = {a_name: str(a), b_name: str(b)}
    for name, cases, path in ((a_name, left, a), (b_name, right, b)):
        if not cases:
            return {"verdict": "NOT_MEASURED", "arms": arms,
                    "reason": (f"{name} JUnit {path} is "
                               + ("missing or unreadable" if cases is None
                                  else "empty (0 test cases)"))}
    rows = []
    for key in sorted(set(left) | set(right)):
        la, rb = left.get(key, "ABSENT"), right.get(key, "ABSENT")
        if la != rb:
            rows.append({"case": f"{key[0]}.{key[1]}", a_name: la, b_name: rb})
    return {"verdict": "FAIL" if rows else "PASS",
            "finding": FINDING if rows else None,
            "arms": arms, "cases": len(set(left) | set(right)),
            "disagreements": rows,
            "why": ("a case whose outcome depends on the simulator is an "
                    "X-semantics or scheduling hazard, not a design result"
                    if rows else None)}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--a", required=True, type=Path, help="Icarus JUnit")
    ap.add_argument("--b", required=True, type=Path, help="Verilator JUnit")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    result = compare_junit(args.a, args.b)
    if args.json:
        write_json(args.json, result)
    print(f"[sim_dual_compare] {result['verdict']}: "
          + (result.get("reason") or
             f"{result.get('cases')} case(s), "
             f"{len(result.get('disagreements') or [])} disagreement(s)"))
    return {"PASS": 0, "FAIL": 1}.get(result["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
