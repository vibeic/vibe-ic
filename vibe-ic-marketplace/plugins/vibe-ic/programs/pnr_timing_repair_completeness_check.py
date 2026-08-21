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

DIRECTORY MODE (added when this gate was wired into Step 17)
-----------------------------------------------------------
A positional argument that is a DIRECTORY is expanded to every ``pnr*.tcl``
inside it, and the worst verdict across them is returned. Two measured reasons,
both about the same failure — a gate wired onto a path that the corpus does not
use is a gate that never runs:

  * the published run whose silicon-DOA this gate was WRITTEN for names its
    script ``pnr_fixed.tcl``, not ``pnr.tcl``. Wired on the literal
    ``phase3/stage3/pnr/pnr.tcl`` the gate would have returned the
    input-missing tier on exactly that run.
  * the flow's gate commands are evaluated with bash-nullglob semantics, so a
    ``pnr*.tcl`` pattern that matches nothing is DROPPED from argv entirely and
    argparse's own "missing argument" exit happens to be 2. Relying on that
    coincidence to produce the disclosed-skip tier is not a contract.

A directory holding no ``pnr*.tcl`` (a run that never reached P&R) is the
DISCLOSED-SKIP tier, exit 2 — not a pass and not a failure. That is what lets
the gate be wired UNCONDITIONALLY: a `condition_files_exist` on the very script
whose absence would be interesting is the self-disabling shape
`flow_condition_reachability_check` exists to refuse.

KNOWN HARDENING GAP (disclosed, not fixed here)
-----------------------------------------------
This is a token audit, not a Tcl interpreter. Two shapes still read as present:
a chain inside a disabled ``if {0} { ... }`` block, and the command names
quoted inside a ``puts "TODO: add set_wire_rc …"`` string. Both are false
PASSes on a script a human wrote to be obviously dead. The gate is still the
declared inverse of ``openroad_tcl_deprecation_check`` and still catches the
absence it was written for (see the negative control in the PR that wired it).

CLI::

    python3 pnr_timing_repair_completeness_check.py pnr.tcl
    python3 pnr_timing_repair_completeness_check.py phase3/stage3/pnr
    python3 pnr_timing_repair_completeness_check.py pnr.tcl --json out.json

Exit codes::

    0 — PASS: all required setup-repair commands present.
    1 — FAIL: at least one required command missing (or hold-only anti-pattern).
    2 — error / disclosed skip: file missing / unreadable / empty / no Tcl
        content / a directory that holds no P&R script at all.
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


#: What a DIRECTORY positional expands to. `pnr_fixed.tcl` is a real published
#: name; `sta_one.tcl` / `magic_stream_out.tcl` / `metal_fill_*.tcl` sit in the
#: same directory and are NOT P&R flows, so the glob is deliberately narrow.
_PNR_SCRIPT_GLOB = "pnr*.tcl"

_WORST = {"PASS": 0, "WARN": 1, "FAIL": 2}


def _expand(paths: List[str]) -> Tuple[List[Path], List[str]]:
    """Resolve positionals to concrete scripts. Returns (scripts, skips)."""
    scripts: List[Path] = []
    skips: List[str] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            hits = sorted(p.glob(_PNR_SCRIPT_GLOB))
            if not hits:
                skips.append(f"{p}: no {_PNR_SCRIPT_GLOB} in this directory")
            scripts.extend(hits)
        elif p.is_file():
            scripts.append(p)
        else:
            skips.append(f"{p}: not found")
    # de-dup, order-stable
    seen, out = set(), []
    for s in scripts:
        r = s.resolve()
        if r not in seen:
            seen.add(r)
            out.append(s)
    return out, skips


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit an OpenROAD P&R Tcl script for the mandatory "
                    "setup-timing-repair sequence (set_wire_rc + "
                    "repair_design + repair_timing -setup). Catches the "
                    "hold-only silicon-DOA anti-pattern. A DIRECTORY "
                    "positional expands to every pnr*.tcl inside it.")
    ap.add_argument("script", nargs="+",
                    help="PnR Tcl script(s), or a directory holding pnr*.tcl")
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    scripts, skips = _expand(args.script)
    single = len(args.script) == 1 and Path(args.script[0]).is_file()

    audited: List[Dict[str, Any]] = []
    for path in scripts:
        try:
            raw = path.read_text(errors="replace")
        except OSError as exc:
            skips.append(f"{path}: cannot read ({exc})")
            continue
        if not raw.strip():
            skips.append(f"{path}: empty file, no PnR flow to audit")
            continue
        if not _looks_like_tcl_pnr(raw):
            skips.append(f"{path}: no OpenROAD P&R Tcl flow detected "
                         f"(no read_verilog/global_placement/repair_* anchors)")
            continue
        verdict, findings, summary = audit(path)
        audited.append({"script": str(path), "verdict": verdict,
                        "summary": summary,
                        "findings": [asdict(f) for f in findings]})

    if not audited:
        # DISCLOSED SKIP (exit 2), never a vacuous PASS: nothing auditable was
        # found, and "no P&R script here" is a different fact from "the P&R
        # script is complete".
        for s in skips:
            print(f"error: {s}", file=sys.stderr)
        if not skips:
            print("error: no P&R Tcl script to audit", file=sys.stderr)
        print("VACUOUS_PASS: pnr_timing_repair_completeness_check — "
              "no OpenROAD P&R Tcl flow to audit (NOT CHECKED)")
        return 2

    worst = max(audited, key=lambda a: _WORST[a["verdict"]])
    verdict = worst["verdict"]
    summary = worst["summary"]
    report = {
        "gate": "pnr_timing_repair_completeness_check",
        "verdict": verdict,
        "script": worst["script"],
        "summary": summary,
        "findings": worst["findings"],
        "audited": audited,
        "skipped": skips,
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    for a in audited:
        s = a["summary"]
        scope = "" if single else f" [{a['script']}]"
        print(f"{a['verdict']}: pnr_timing_repair_completeness_check{scope} — "
              f"setup_chain={'yes' if s['setup_repair_chain_present'] else 'NO'}; "
              f"hold={'yes' if s['hold_repair_present'] else 'no'}; "
              f"missing_required={s['missing_required'] or 'none'}")
        if s["hold_only_antipattern"]:
            print("  [hold_only_antipattern] script runs `repair_timing -hold` "
                  "but NONE of {set_wire_rc, repair_design, "
                  "repair_timing -setup} — this is the silicon-DOA shape "
                  "(optimistic STA, unbuffered high-fanout nets).")
        if args.verbose or a["verdict"] != "PASS":
            for f in a["findings"]:
                mark = "ok" if f["present"] else "MISSING"
                print(f"  [{f['severity']}] {f['label']}: {mark}")
    for s in skips:
        print(f"  skipped: {s}")

    return 0 if verdict in ("PASS", "WARN") else 1


if __name__ == "__main__":
    sys.exit(main())
