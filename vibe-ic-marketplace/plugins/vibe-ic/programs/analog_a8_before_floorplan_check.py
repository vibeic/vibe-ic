#!/usr/bin/env python3
"""analog_a8_before_floorplan_check.py — analog/digital ordering gate.

Enforces analog-flow-orchestrate **Hard rule #1** ("A8 must complete
BEFORE digital Step 15 / Floorplan") and the corollary of **Hard rule #2**
("A9 — and only A9 — may run in parallel with Step 15+").

WHY THIS IS A REAL DEFECT
-------------------------
Digital place-and-route reads each analog block's hardmacro abstract
(``phase3/analog/hardmacro/<block>/<block>.lef``) to reserve the block's
footprint, pins and routing-blockage during floorplan. If the floorplan
DEF (``phase3/stage3/pnr/floorplan.def`` or ``phase3/pnr/<top>.def``) is
written while ANY analog block is still missing its A8 LEF, that block is
either dropped from the floorplan or placed without a physical abstract —
a broken mixed-signal integration that ships an UNROUTABLE / silicon-DOA
layout. This gate makes that ordering inversion a hard FAIL instead of a
silently-broken DEF.

The compliance gate (``analog_flow_compliance_check.py``) only checks that
each A-step *deliverable exists* at audit time; it does NOT check the
A8↔floorplan *ordering*. This program closes that gap.

ALGORITHM (chip-AGNOSTIC, deterministic)
----------------------------------------
  1. Load the analog block list (``phase3/analog/analog_block_list.json``).
     Empty / absent  → SKIP (exit 0, INFO) — pure-digital IC, no constraint.
  2. Locate a floorplan DEF artefact. None present → SKIP (exit 0, INFO):
     floorplan has not run yet, so the ordering constraint is not yet
     triggered — we never assert a violation that has not happened.
  3. Floorplan DEF present → for every analog block, REQUIRE its A8 LEF
     (``phase3/analog/hardmacro/<block>/<block>.lef``) to exist UNLESS the
     block carries an ``A8`` waiver in ``phase3/analog/waivers.json``.
  4. Any block missing its A8 LEF (and unwaived) → FAIL (ordering inversion).
     All blocks have A8 LEF (or waived) → PASS (earned — floorplan ran with
     every hardmacro abstract present).

HONEST FAIL/SKIP
----------------
  - Missing / garbage block list            → VACUOUS (no analog content).
  - Block list present but floorplan absent → VACUOUS (not yet triggered).
  - Floorplan present, A8 LEF missing       → FAIL (real ordering defect).
  - Non-directory project                   → exit 2 (IO error).

Usage:
    python3 analog_a8_before_floorplan_check.py <project_dir>
    python3 analog_a8_before_floorplan_check.py <project_dir> --json report.json

Exit codes:
    0 = PASS: a floorplan DEF exists AND every analog block's A8 LEF was
        present when it was written — the ordering was actually checked
    1 = FAIL (A8 not complete before floorplan ran)
    2 = VACUOUS: nothing was examined — no analog block list, or no floorplan
        DEF, so the ordering constraint was never evaluated. #521: this gate
        was the sharpest instance of the class. It ALREADY read
        `summary["skipped"]` and ALREADY printed `[SKIP]` — and then returned
        `0 if result.passed else 1`, which discarded that distinction at the
        one place a consumer can see it. Measured over the 200 tracked
        project roots: 200 of 200 rc 0, 200 of 200 self-reporting a skip.
        Also rc 2 for an IO / parse error.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Set, Tuple

import _path_layout as _pl
import _vacuous_exit as _vx
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""


@dataclass
class AuditResult:
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _load_block_list(project: Path) -> List[str]:
    """Reuse the canonical analog_block_list.json shape used by the
    other analog gates: either a bare list or {"blocks": [...]}; each
    entry is a name string or {"name": ...} object."""
    bl = _pl.analog_dir(project) / "analog_block_list.json"
    if not bl.exists():
        return []
    try:
        data = json.loads(bl.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict) and "blocks" in data:
        data = data["blocks"]
    if not isinstance(data, list):
        return []
    out: List[str] = []
    for b in data:
        if isinstance(b, dict) and "name" in b:
            out.append(str(b["name"]))
        elif isinstance(b, str):
            out.append(b)
    return out


def _load_a8_waivers(project: Path) -> Set[str]:
    """Blocks whose A8 step is explicitly waived (same waivers.json shape
    as analog_flow_compliance_check)."""
    wf = _pl.analog_dir(project) / "waivers.json"
    if not wf.exists():
        return set()
    try:
        data = json.loads(wf.read_text(errors="replace"))
        waivers = data.get("analog_waivers", [])
        return {str(w["block"]) for w in waivers
                if isinstance(w, dict) and w.get("step") == "A8" and "block" in w}
    except (json.JSONDecodeError, OSError, KeyError):
        return set()


def _find_floorplan_def(project: Path) -> Optional[Path]:
    """Locate a floorplan DEF written by the digital Step 15 floorplan.
    The phase3 runner writes ``phase3/stage3/pnr/floorplan.def`` and a
    top-level ``phase3/pnr/<top>.def``. Any DEF under either pnr dir means
    floorplan has begun and the A8 abstracts had to be present."""
    candidates: List[Path] = []
    pnr = _pl.pnr_dir(project)                      # phase3/stage3/pnr
    if pnr.is_dir():
        candidates += sorted(pnr.glob("*.def"))
    legacy_pnr = project / "phase3" / "pnr"         # phase3/pnr/<top>.def
    if legacy_pnr.is_dir():
        candidates += sorted(legacy_pnr.glob("*.def"))
    return candidates[0] if candidates else None


def _a8_lef(project: Path, block: str) -> Path:
    return _pl.hardmacro_dir(project) / block / f"{block}.lef"


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    blocks = _load_block_list(project)
    if not blocks:
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG",
            severity="INFO",
            message="No analog block list; pure-digital IC — A8/floorplan ordering N/A",
        ))
        result.summary = {"skipped": True, "reason": "no_analog_blocks"}
        return result

    fp = _find_floorplan_def(project)
    if fp is None:
        result.findings.append(Finding(
            rule="SKIP_FLOORPLAN_NOT_RUN",
            severity="INFO",
            message="No floorplan DEF found; ordering constraint not yet triggered",
        ))
        result.summary = {
            "skipped": True,
            "reason": "floorplan_not_run",
            "blocks": blocks,
        }
        return result

    waived = _load_a8_waivers(project)
    missing: List[str] = []
    present: List[str] = []
    for block in blocks:
        if block in waived:
            result.findings.append(Finding(
                rule="A8_WAIVED",
                severity="INFO",
                message=f"Block '{block}' A8 hardmacro waived",
            ))
            continue
        lef = _a8_lef(project, block)
        if lef.exists():
            present.append(block)
            result.findings.append(Finding(
                rule="A8_PRESENT_BEFORE_FLOORPLAN",
                severity="INFO",
                message=f"Block '{block}' A8 LEF present before floorplan",
                file=str(lef),
            ))
        else:
            missing.append(block)
            result.findings.append(Finding(
                rule="A8_MISSING_BUT_FLOORPLAN_RAN",
                severity="ERROR",
                message=(
                    f"ORDERING VIOLATION: floorplan DEF {fp.name} exists but block "
                    f"'{block}' has no A8 hardmacro LEF ({lef}). Digital Step 15 "
                    f"floorplan placed analog blocks without this abstract — "
                    f"broken mixed-signal integration. Hard rule #1 violated."
                ),
                file=str(lef),
            ))

    result.passed = (len(missing) == 0)
    result.summary = {
        "skipped": False,
        "floorplan_def": str(fp),
        "total_blocks": len(blocks),
        "a8_present": present,
        "a8_waived": sorted(waived & set(blocks)),
        "a8_missing": missing,
        "pass": result.passed,
    }
    return result


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)

    # #521 — this gate already COMPUTED `skipped` and already PRINTED `[SKIP]`;
    # what it never did was let that reach the exit code, which is the only
    # channel `flow_compliance_check` reads. Same source of truth, now routed.
    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)

    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)
    else:
        print(_vx.verdict_line("analog_a8_before_floorplan_check",
                               result.passed, skipped, reason))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.passed and skipped:
        # This gate's AuditResult carries no `program` field (unlike its
        # sixteen siblings), so the name is the module's own literal.
        _vx.announce_vacuous("analog_a8_before_floorplan_check", reason)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
