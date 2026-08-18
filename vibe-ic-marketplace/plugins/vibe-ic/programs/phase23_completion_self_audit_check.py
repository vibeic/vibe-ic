#!/usr/bin/env python3
"""
phase23_completion_self_audit_check.py — v0.109 mandatory self-audit gate.

THIS GATE IS THE SOLE PHASE 2+3 ACCEPTANCE SIGNAL.

Any agent claiming "Phase 2+3 complete", "design flow done", "tape-out
ready", "ready for fab", "<half-duplex-tester> PASS so we're done", "tapeout_signoff
PASS so we're done", or any equivalent — MUST run this gate FIRST and
paste its output into FINAL_REPORT.md as evidence.

Why this gate exists:
- Individual gates (tapeout_signoff_check, md905_connect_test,
  BACKLOG-v6/v7 P0 set, lvs_yosys_equiv) are NECESSARY but INSUFFICIENT.
- The v0.108 fresh-agent benchmark on <benchmark> demonstrated that an agent
  can pass every individual gate while only completing 2/34 canonical
  flow steps — because steps 14-32 (PnR canonical artefacts, SPEF,
  post-route STA, IR/EM/antenna/SI, post-layout sim, SPICE correlation,
  ECO, power, metal fill, tapeout checklist) and step 34 (FPGA final
  sign-off) were never verified.
- This gate wraps `flow_compliance_check.py --strict` and produces a
  single PASS/FAIL with a clear `non-waived PASS = N/34` metric.

Usage:
  python3 phase23_completion_self_audit_check.py <project_dir> [--json [PATH]]

Exit codes:
  0  Overall PASS — Phase 2+3 may be claimed complete
  1  FAIL — at least one canonical step missing/failing without waiver
  2  IO error / project not found

The output of this gate must appear (verbatim, last 10 lines) in
<project>/FINAL_REPORT.md before any release artefact is shipped.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _path_layout as _pl  # noqa: E402  — #525 shared timeout resolver


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


def _find_flow_compliance_check() -> Path:
    """Locate flow_compliance_check.py — sibling in this programs/ dir."""
    me = Path(__file__).resolve()
    sibling = me.parent / "flow_compliance_check.py"
    if sibling.exists():
        return sibling
    raise FileNotFoundError(f"flow_compliance_check.py not found alongside {me}")


def _run_compliance(project: Path, strict: bool = True) -> tuple[int, str]:
    fcc = _find_flow_compliance_check()
    cmd = [sys.executable, str(fcc), str(project)]
    if strict:
        cmd.append("--strict")
    # #525 — size-adaptive budget (shared resolver) instead of the old fixed
    # 300s, which a large SoC's legitimate 8-9 min --strict audit exceeded;
    # AND the TimeoutExpired no longer crashes the whole acceptance gate
    # with a traceback: it returns a named AUDIT_TIMEOUT overall so the
    # caller emits a structured INCONCLUSIVE verdict (timeout ≠ verdict).
    budget = _pl.audit_timeout_s(project)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=budget)
    except subprocess.TimeoutExpired as e:
        partial = (e.stdout or "")
        if isinstance(partial, bytes):
            partial = partial.decode(errors="replace")
        return 124, (f"Overall: AUDIT_TIMEOUT\n"
                     f"AUDIT TIMEOUT after {budget}s — the compliance audit "
                     f"did not run to completion; this is NOT a verdict on "
                     f"the project (INCONCLUSIVE, #525). Raise "
                     f"{_pl.AUDIT_TIMEOUT_ENV} to extend.\n" + partial)
    return proc.returncode, proc.stdout + proc.stderr


_SUMMARY_RE = re.compile(
    r"Steps:\s*(\d+)\s*total\s*\((\d+)/(\d+)\s*executed\s*PASS,\s*(\d+)\s*DEFERRED",
    re.IGNORECASE,
)
# Backward-compat for older flow_compliance_check output.
_SUMMARY_LEGACY_RE = re.compile(
    r"Steps:\s*(\d+)\s*total\s*\((\d+)/(\d+)\s*non-waived\s*PASS\)",
    re.IGNORECASE,
)
_OVERALL_RE = re.compile(
    r"Overall:\s*(PASS_WITH_WAIVERS|PASS|FAIL|AUDIT_TIMEOUT)", re.IGNORECASE)
_TOTAL_REQ = 34


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Phase 2+3 SOLE ACCEPTANCE GATE — wraps flow_compliance_check "
            "--strict and certifies that the canonical 34-step flow is "
            "complete. This is the ONLY signal that authorises a "
            '"Phase 2+3 complete" claim.'
        )
    )
    ap.add_argument("project_dir", help="Project directory (contains rtl/, fpga/, gds/, etc.)")
    ap.add_argument("--json", nargs="?", const="-", default=None,
                    help="Emit machine-readable JSON. With PATH, writes to file; bare flag prints to stdout.")
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    rc, output = _run_compliance(project, strict=True)

    findings = []
    overall_match = _OVERALL_RE.search(output)
    summary_match = _SUMMARY_RE.search(output) or _SUMMARY_LEGACY_RE.search(output)

    overall = overall_match.group(1).upper() if overall_match else "UNKNOWN"
    waived_count = 0
    if summary_match:
        steps_total = int(summary_match.group(1))
        executed_pass = int(summary_match.group(2))
        executed_total = int(summary_match.group(3))
        if summary_match.lastindex and summary_match.lastindex >= 4:
            waived_count = int(summary_match.group(4))
    else:
        steps_total = executed_pass = executed_total = 0

    # Three verdict states. Waivers are NOT pass — production tapeout
    # review must close them with the foundry's commercial deck.
    structurally_complete = overall in ("PASS", "PASS_WITH_WAIVERS")

    if overall == "FAIL":
        findings.append(Finding(
            severity="ERROR",
            category="PHASE23_NOT_COMPLETE",
            message=(
                f"Phase 2+3 is NOT complete. flow_compliance_check returned "
                f"Overall=FAIL, executed PASS={executed_pass}/{executed_total}."
            ),
            details=(
                "Individual gates passing (tapeout_signoff_check, md905_connect_test, "
                "BACKLOG-v6/v7 P0) is necessary but NOT sufficient to claim Phase 2+3 "
                "complete. Read CLAUDE.md rule #11 and skills/spec-to-rtl/SKILL.md "
                "SOLE-ACCEPTANCE-CRITERION section. To proceed: complete the missing "
                "canonical steps, OR add waivers to <project>/waivers.json with "
                "justification, then re-run."
            ),
        ))
    elif overall == "PASS_WITH_WAIVERS":
        findings.append(Finding(
            severity="INFO",
            category="WAIVERS_DEFERRED",
            message=(
                f"Phase 2+3 audit is structurally complete but {waived_count} canonical "
                f"step(s) are DEFERRED via waiver and have NOT been executed. "
                f"Production tapeout requires closing every waiver on the foundry's "
                f"commercial deck before fab can take the GDS."
            ),
            details=(
                "PASS_WITH_WAIVERS satisfies the v0.110 SOLE-ACCEPTANCE rule but "
                "is NOT equivalent to genuine PASS. Each waiver in <project>/"
                "waivers.json must include evidence + ticket + review_required:true. "
                "Do not present this as 'every step passed' — present as 'every step "
                "passed or has a justified deferral pending foundry sign-off'."
            ),
        ))

    result = {
        "program": "phase23_completion_self_audit_check",
        "version": "2.0.0",
        "project": str(project),
        "summary": {
            "overall": overall,
            "executed_pass": executed_pass,
            "executed_total": executed_total,
            "waived_deferred": waived_count,
            "canonical_step_count": _TOTAL_REQ,
            "structurally_complete": structurally_complete,
            "production_tapeout_ready": overall == "PASS",
        },
        "findings": [asdict(f) for f in findings],
        "underlying_output_tail": "\n".join(output.strip().splitlines()[-20:]),
    }

    if args.json is None:
        if overall == "PASS":
            print("[PASS] phase23_completion_self_audit_check")
            print(f"  Overall: PASS — every canonical step executed and verified.")
            print(f"  executed PASS: {executed_pass}/{executed_total} (canonical 34)")
        elif overall == "PASS_WITH_WAIVERS":
            print("[PASS_WITH_WAIVERS] phase23_completion_self_audit_check")
            print(f"  Overall: PASS_WITH_WAIVERS — structurally complete, NOT production-ready.")
            print(f"  executed PASS: {executed_pass}/{executed_total} (canonical 34)")
            print(f"  DEFERRED via waiver (NOT pass): {waived_count} step(s)")
            print()
            print(f"  ⚠ {waived_count} canonical step(s) are NOT executed — they are")
            print(f"    DEFERRED to foundry sign-off / production tapeout review.")
            print(f"    A waivered audit allows engineering claim of 'Phase 2+3 complete'")
            print(f"    but foundry tapeout requires closing every waiver on commercial")
            print(f"    PDK + sign-off deck before fab takes the GDS.")
            print()
            print(f"    Each waiver in {project}/waivers.json must carry evidence,")
            print(f"    ticket id, and review_required:true. Treat waivers as open work,")
            print(f"    not as PASS.")
        else:
            print("[FAIL] phase23_completion_self_audit_check")
            print(f"  Overall: {overall}")
            print(f"  executed PASS: {executed_pass}/{executed_total} (canonical 34)")
            print()
            print("  ⛔ Phase 2+3 is NOT complete. DO NOT claim completion.")
            print("  Run: python3 flow_compliance_check.py <project> --strict")
            print("  See: CLAUDE.md rule #11, skills/spec-to-rtl/SKILL.md")
    elif args.json == "-":
        print(json.dumps(result, indent=2))
    else:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"json: {args.json}")

    return 0 if structurally_complete else 1


if __name__ == "__main__":
    sys.exit(main())
