#!/usr/bin/env python3
"""
pnr_timing_repair_completeness_check.py — chip-AGNOSTIC static audit of an
OpenROAD P&R Tcl script for the MANDATORY setup-timing-repair sequence.

Background (sta-review SKILL.md captured note, 2026-05-28; v0.1.26)
------------------------------------------------------------------
A PnR script that runs ONLY ``repair_timing -hold`` (and never
``set_wire_rc`` + ``repair_design`` + ``repair_timing -setup``) ships a
silicon-DOA design:

  * Without ``set_wire_rc``, OpenROAD has no per-layer R/C, so STA ignores
    interconnect delay (optimistic) and ``repair_timing -setup`` aborts with
    RSZ-0089. High-fanout control nets (reset_n, FSM state-decode, enable
    nets driving hundreds of flops) stay on zero-strength gates with no
    buffer tree.
  * Worked example (benchmark_clean/sha256, v0.1.25 → v0.1.26): post-route
    WNS = -102.76 ns VIOLATED, mis-attributed to a single-cycle SHA round.
    Real root cause: no ``set_wire_rc`` / ``repair_design`` /
    ``repair_timing -setup``. After adding the chain, WNS = +10.95 ns MET on
    the SAME RTL.

This is GENERAL: universal across OpenROAD-driven PnR (sky130 / gf180 / any
PDK without commercial DC sign-off). Every IC class suffers from unbuffered
high-fanout nets when only hold-repair runs.

What this program checks (inverse of openroad_tcl_deprecation_check.py — that
flags PRESENCE of bad tokens; this flags ABSENCE of required ones)
-----------------------------------------------------------------------------
Given a PnR Tcl script (or a file with an embedded Tcl heredoc), confirm that
ALL of the following appear in the placement/optimisation flow:

  REQUIRED (FAIL if any missing):
    1. set_wire_rc            — per-layer parasitic R/C (else STA optimistic)
    2. repair_design          — fix max-cap / max-slew on high-fanout nets
    3. repair_timing -setup   — close setup paths (needs wire RC + buffer trees)

  EXPECTED-WITH-SETUP (WARN if missing while setup-repair present):
    4. estimate_parasitics    — populate RC before repair (placement or GR)
    5. repair_timing -hold    — hold-fix is still needed (post-CTS / post-GR)

  HOLD-ONLY ANTI-PATTERN (FAIL): a script that has ``repair_timing -hold`` but
    NONE of {set_wire_rc, repair_design, repair_timing -setup} — the exact
    sha256 silicon-DOA shape.

A token counts as "present" if it appears uncommented OR inside a Tcl
``catch {...}`` NONFATAL guard (the runner template wraps every repair command
in ``catch`` — those still execute). A line whose FIRST non-space char is
``#`` is treated as commented-out and does NOT count.

Honest-FAIL contract
--------------------
  * Missing file / unreadable        -> exit 2 (error), never vacuous PASS.
  * Empty / no-Tcl-content file       -> exit 2 (no flow to audit).
  * A real PnR script missing a req   -> exit 1 (FAIL) with the missing list.
  * Only PASS when all 3 required commands are genuinely present.

CLI::

    python3 pnr_timing_repair_completeness_check.py pnr.tcl
    python3 pnr_timing_repair_completeness_check.py pnr.tcl --json out.json

Exit codes::

    0 — PASS: all required setup-repair commands present.
    1 — FAIL: at least one required command missing (or hold-only anti-pattern).
    2 — error: file missing / unreadable / empty / no Tcl content.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Each requirement: (key, human_label, regex, severity)
#   severity "required"  -> missing => FAIL
#   severity "expected"  -> missing => WARN (only when setup-repair is present)
REQUIRED = (
    ("set_wire_rc",
     "set_wire_rc (per-layer parasitic R/C)",
     re.compile(r"\bset_wire_rc\b")),
    ("repair_design",
     "repair_design (max-cap / max-slew on high-fanout nets)",
     re.compile(r"\brepair_design\b")),
    ("repair_timing_setup",
     "repair_timing -setup (close setup paths)",
     re.compile(r"\brepair_timing\b[^\n#]*\-setup\b")),
)
EXPECTED = (
    ("estimate_parasitics",
     "estimate_parasitics (populate RC before repair)",
     re.compile(r"\bestimate_parasitics\b")),
    ("repair_timing_hold",
     "repair_timing -hold (hold-fix post-CTS / post-GR)",
     re.compile(r"\brepair_timing\b[^\n#]*\-hold\b")),
)


def _strip_commented(text: str) -> str:
    """Drop lines whose first non-space char is '#' (Tcl comment).

    Lines inside ``catch {...}`` still execute, so they are kept. Only a
    fully-commented-out line is removed. This is deliberately conservative —
    we do not attempt to parse inline trailing comments because a command
    before a trailing ``;# note`` still runs.
    """
    kept: List[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        kept.append(line)
    return "\n".join(kept)


def _looks_like_tcl_pnr(text: str) -> bool:
    """Heuristic: does this contain an OpenROAD P&R Tcl flow at all?

    We require at least one recognisable OpenROAD command so we never audit
    (and FAIL) a file that simply has no P&R flow — that is exit-2 territory,
    not a FAIL.
    """
    anchors = (
        r"\bread_verilog\b", r"\bread_liberty\b", r"\blink_design\b",
        r"\bglobal_placement\b", r"\bdetailed_placement\b",
        r"\bglobal_route\b", r"\bdetailed_route\b",
        r"\bclock_tree_synthesis\b", r"\bplace_pins\b",
        r"\brepair_timing\b", r"\brepair_design\b", r"\bset_wire_rc\b",
        r"\bplace_pins\b", r"\binitialize_floorplan\b",
    )
    return any(re.search(a, text) for a in anchors)


@dataclass
class TokenFinding:
    key: str
    label: str
    present: bool
    severity: str  # "required" | "expected"


def audit(script_path: Path) -> Tuple[str, List[TokenFinding], Dict[str, Any]]:
    raw = script_path.read_text(errors="replace")
    active = _strip_commented(raw)

    findings: List[TokenFinding] = []
    for key, label, rx in REQUIRED:
        findings.append(TokenFinding(key, label, bool(rx.search(active)), "required"))
    for key, label, rx in EXPECTED:
        findings.append(TokenFinding(key, label, bool(rx.search(active)), "expected"))

    by_key = {f.key: f for f in findings}
    missing_required = [f.label for f in findings
                        if f.severity == "required" and not f.present]
    missing_expected = [f.label for f in findings
                        if f.severity == "expected" and not f.present]

    setup_present = (by_key["set_wire_rc"].present
                     and by_key["repair_design"].present
                     and by_key["repair_timing_setup"].present)
    hold_present = by_key["repair_timing_hold"].present

    # Hold-only anti-pattern: hold-repair runs but NONE of the setup chain.
    hold_only_antipattern = (
        hold_present
        and not by_key["set_wire_rc"].present
        and not by_key["repair_design"].present
        and not by_key["repair_timing_setup"].present
    )

    if missing_required:
        verdict = "FAIL"
    elif missing_expected:
        verdict = "WARN"
    else:
        verdict = "PASS"

    summary = {
        "setup_repair_chain_present": setup_present,
        "hold_repair_present": hold_present,
        "hold_only_antipattern": hold_only_antipattern,
        "missing_required": missing_required,
        "missing_expected": missing_expected,
    }
    return verdict, findings, summary


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit an OpenROAD P&R Tcl script for the mandatory "
                    "setup-timing-repair sequence (set_wire_rc + "
                    "repair_design + repair_timing -setup). Catches the "
                    "hold-only silicon-DOA anti-pattern.")
    ap.add_argument("script", help="path to the PnR Tcl script (or a file "
                                    "with an embedded Tcl flow)")
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    path = Path(args.script)
    if not path.is_file():
        print(f"error: script not found: {path}", file=sys.stderr)
        return 2
    try:
        raw = path.read_text(errors="replace")
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 2
    if not raw.strip():
        print(f"error: empty file, no PnR flow to audit: {path}", file=sys.stderr)
        return 2
    if not _looks_like_tcl_pnr(raw):
        print(f"error: no OpenROAD P&R Tcl flow detected in {path} "
              f"(no read_verilog/global_placement/repair_* anchors)",
              file=sys.stderr)
        return 2

    verdict, findings, summary = audit(path)
    report = {
        "gate": "pnr_timing_repair_completeness_check",
        "verdict": verdict,
        "script": str(path),
        "summary": summary,
        "findings": [asdict(f) for f in findings],
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    print(f"{verdict}: pnr_timing_repair_completeness_check — "
          f"setup_chain={'yes' if summary['setup_repair_chain_present'] else 'NO'}; "
          f"hold={'yes' if summary['hold_repair_present'] else 'no'}; "
          f"missing_required={summary['missing_required'] or 'none'}")
    if summary["hold_only_antipattern"]:
        print("  [hold_only_antipattern] script runs `repair_timing -hold` but "
              "NONE of {set_wire_rc, repair_design, repair_timing -setup} — "
              "this is the sha256 silicon-DOA shape (optimistic STA, "
              "unbuffered high-fanout nets).")
    if args.verbose or verdict != "PASS":
        for f in findings:
            mark = "ok" if f.present else "MISSING"
            print(f"  [{f.severity}] {f.label}: {mark}")

    return 0 if verdict in ("PASS", "WARN") else 1


if __name__ == "__main__":
    sys.exit(main())
