#!/usr/bin/env python3
"""
openroad_hold_repair_tcl_gen.py — emit the OpenROAD `repair_timing -hold`
block with the SKILL's hard guardrails baked in.

From `skills/hold-fix/SKILL.md` Step 3 + "Constraints and Guardrails":
  repair_timing -hold \\
      -slack_margin <margin_ps> \\
      -allow_setup_violations false \\   # HARD: never trade setup for hold
      -max_buffer_percent <area_budget>  # HARD: cap area overhead at <= 5%

Two fixed safety constants are NOT free knobs:
  * `-allow_setup_violations` is ALWAYS emitted `false` (the SKILL marks this
    "critical — never trade setup for hold"). The builder refuses to emit a
    `true`.
  * `-max_buffer_percent` is capped at the SKILL guardrail (5%). A request for
    more than the cap is an honest FAIL — emitting a runaway buffer budget is a
    real silicon-area/IR hazard, not a stylistic choice.

This replaces the hand-copied prose Tcl with a deterministic Tcl-block builder,
so every agent emits byte-identical, guardrail-correct Tcl.

HARD honesty rules:
  - margin_ps not a finite number  => FAIL (rc=1).
  - max_buffer_percent <= 0 or > cap (5) => FAIL (rc=1).  (0% would insert
    nothing; > cap breaches the area guardrail.)
  - allow_setup_violations requested true => FAIL (rc=1).
  - PASS (rc=0) only emits a Tcl block that (a) carries the literal
    `-allow_setup_violations false`, (b) a `-max_buffer_percent` within cap,
    and (c) the post-fix verification reports.

chip-AGNOSTIC: no PDK / cell / design literal is hard-coded; the only fixed
constants are the SKILL's universal guardrails (false, 5%).

Usage
-----
    python3 openroad_hold_repair_tcl_gen.py --margin-ps 0 --max-buffer-percent 5 \\
        [--out hold_repair.tcl] [--json report.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Tuple


_TOOL = "openroad_hold_repair_tcl_gen"

# SKILL guardrails (universal, not chip-specific).
MAX_BUFFER_PERCENT_CAP = 5.0      # "hold buffers should not exceed 5%"
ALLOW_SETUP_VIOLATIONS = "false"  # "critical — never trade setup for hold"


def build_tcl(margin_ps: float, max_buffer_percent: float) -> str:
    """Build the guardrail-correct repair_timing -hold Tcl block."""
    lines = [
        "# === Hold fix (post-CTS / post-route) ===",
        "# Emitted by openroad_hold_repair_tcl_gen.py — guardrails are FIXED:",
        f"#   -allow_setup_violations {ALLOW_SETUP_VIOLATIONS}  (never trade "
        "setup for hold)",
        f"#   -max_buffer_percent <= {MAX_BUFFER_PERCENT_CAP:g}  (area budget cap)",
        "repair_timing -hold \\",
        f"    -slack_margin {margin_ps:g} \\",
        f"    -allow_setup_violations {ALLOW_SETUP_VIOLATIONS} \\",
        f"    -max_buffer_percent {max_buffer_percent:g}",
        "",
        "# Post-fix verification (Step 3/4)",
        "report_worst_slack -min",
        "report_tns -min",
        "# Confirm no setup regression",
        "report_worst_slack -max",
        "",
    ]
    return "\n".join(lines)


def evaluate(margin_ps: float, max_buffer_percent: float,
             allow_setup_violations: bool) -> Tuple[str, int, dict]:
    report = {
        "tool": _TOOL,
        "margin_ps": margin_ps,
        "max_buffer_percent": max_buffer_percent,
        "guardrails": {
            "allow_setup_violations": ALLOW_SETUP_VIOLATIONS,
            "max_buffer_percent_cap": MAX_BUFFER_PERCENT_CAP,
        },
    }

    # 1. allow_setup_violations may NEVER be true.
    if allow_setup_violations:
        report["verdict"] = "FAIL"
        report["reason"] = "SETUP_VIOLATION_REQUESTED"
        report["message"] = (
            "request to set -allow_setup_violations true rejected — the SKILL "
            "hard rule is to NEVER trade setup for hold")
        report["tcl"] = None
        return "FAIL", 1, report

    # 2. margin must be a finite number.
    if not isinstance(margin_ps, (int, float)) or not math.isfinite(margin_ps):
        report["verdict"] = "FAIL"
        report["reason"] = "MARGIN_NOT_FINITE"
        report["message"] = f"slack margin must be a finite number, got {margin_ps!r}"
        report["tcl"] = None
        return "FAIL", 1, report

    # 3. max_buffer_percent must be in (0, cap].
    if not isinstance(max_buffer_percent, (int, float)) or \
            not math.isfinite(max_buffer_percent):
        report["verdict"] = "FAIL"
        report["reason"] = "BUFFER_PERCENT_NOT_FINITE"
        report["message"] = (
            f"max_buffer_percent must be a finite number, got "
            f"{max_buffer_percent!r}")
        report["tcl"] = None
        return "FAIL", 1, report
    if max_buffer_percent <= 0:
        report["verdict"] = "FAIL"
        report["reason"] = "BUFFER_PERCENT_NONPOSITIVE"
        report["message"] = (
            f"max_buffer_percent {max_buffer_percent:g} <= 0 would insert "
            "nothing — not a valid hold-fix budget")
        report["tcl"] = None
        return "FAIL", 1, report
    if max_buffer_percent > MAX_BUFFER_PERCENT_CAP:
        report["verdict"] = "FAIL"
        report["reason"] = "BUFFER_PERCENT_OVER_CAP"
        report["message"] = (
            f"max_buffer_percent {max_buffer_percent:g} exceeds the SKILL "
            f"guardrail cap {MAX_BUFFER_PERCENT_CAP:g}% — a runaway hold-buffer "
            f"budget is an area/IR hazard")
        report["tcl"] = None
        return "FAIL", 1, report

    tcl = build_tcl(margin_ps, max_buffer_percent)
    report["verdict"] = "PASS"
    report["tcl"] = tcl
    report["message"] = (
        f"emitted guardrail-correct repair_timing -hold "
        f"(margin={margin_ps:g}ps, max_buffer_percent={max_buffer_percent:g}%)")
    return "PASS", 0, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit OpenROAD repair_timing -hold with fixed guardrails")
    ap.add_argument("--margin-ps", type=float, default=0.0,
                    help="hold slack margin in ps (0 = exact, >0 = guardband)")
    ap.add_argument("--max-buffer-percent", type=float, default=5.0,
                    help=f"area-overhead cap (<= {MAX_BUFFER_PERCENT_CAP:g})")
    ap.add_argument("--allow-setup-violations", action="store_true",
                    help="(rejected) attempt to trade setup for hold")
    ap.add_argument("--out", help="write the Tcl block to this path")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    verdict, rc, report = evaluate(
        args.margin_ps, args.max_buffer_percent, args.allow_setup_violations)

    if args.json:
        outp = Path(args.json)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(report, indent=2) + "\n")
    if rc == 0 and report.get("tcl"):
        if args.out:
            op = Path(args.out)
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_text(report["tcl"])
        else:
            print(report["tcl"])
    print(f"=== {_TOOL} === verdict: {verdict}", file=sys.stderr)
    if verdict == "FAIL":
        print(f"  FAIL: {report.get('message')}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
