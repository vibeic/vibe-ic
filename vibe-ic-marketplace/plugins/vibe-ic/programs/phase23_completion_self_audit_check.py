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
  post-route timing repair, power, metal fill, tapeout checklist) and step 34
  (FPGA final
  sign-off) were never verified.
- This gate wraps `flow_compliance_check.py --strict` and produces a
  single PASS/FAIL with a clear `non-waived PASS = N/34` metric.

Usage:
  python3 phase23_completion_self_audit_check.py <project_dir> [--top TOP] [--json [PATH]]

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
import _audit_verdict  # noqa: E402  — the ONE reader of the audit's verdict + rc
import verdict as _V  # noqa: E402  — the five-word vocabulary

#: The audit word that means 'could not measure', from the vocabulary, not a literal.
_V_NOT_MEASURED = _V.Verdict.NOT_MEASURED.value


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


def _run_compliance(project: Path, strict: bool = True,
                    top: Optional[str] = None) -> tuple[int, str]:
    fcc = _find_flow_compliance_check()
    cmd = [sys.executable, str(fcc), str(project)]
    if strict:
        cmd.append("--strict")
    if top is not None:
        cmd.extend(["--top", top])
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
#: `_OVERALL_RE` IS GONE, AND THE ACCEPTANCE GATE NOW ASKS `_audit_verdict`.
#:
#: It read `Overall:\s*(PASS_WITH_WAIVERS|PASS|FAIL|AUDIT_TIMEOUT)` with `.search` over
#: `proc.stdout + proc.stderr`, took the FIRST match, and the `rc` this file binds at the
#: `_run_compliance` call was read NOWHERE ELSE. Three consequences, all MEASURED on main
#: 7a63a037f by driving this gate's own `main()`:
#:
#:   * UNANCHORED and first-match-wins: the audit prints its blocker list AFTER the verdict
#:     line and those rows quote gate output, so a quoted `Overall: …` could be read as the
#:     run's verdict.
#:   * rc IGNORED: handed the audit's reconciliation-canary stdout (a green word beside
#:     "do not quote its counts") with rc 1, this gate exited 0 and printed
#:     "Overall: PASS — every canonical step executed and verified.", never mentioning the
#:     canary. This file calls itself "the ONLY signal that authorises a 'Phase 2+3
#:     complete' claim", so that was the one verdict in the tree that most needed both
#:     channels.
#:   * NO `NOT_MEASURED` ALTERNATIVE: after #2572 the orchestrator publishes that word, and
#:     here it matched nothing, became "UNKNOWN", and printed `[FAIL]` at exit 1. Failing
#:     closed, so never a false pass -- but it labelled "could not measure" as a defect
#:     found, which is the mislabel R-0915-159 removed from `step_final_audit`.
#:
#: The timeout still arrives as TEXT, not as an rc: `_run_compliance` catches
#: `TimeoutExpired` and synthesises `Overall: AUDIT_TIMEOUT` into the output. `_audit_verdict`
#: names that word for exactly that reason.
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
    ap.add_argument("--top", help="Logical output top; defaults to the project's typed synthesis config")
    ap.add_argument("--json", nargs="?", const="-", default=None,
                    help="Emit machine-readable JSON. With PATH, writes to file; bare flag prints to stdout.")
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    rc, output = (_run_compliance(project, strict=True, top=args.top)
                  if args.top is not None else _run_compliance(project, strict=True))

    findings = []
    # BOTH CHANNELS, FROM THE ONE OWNER. `audit.word` is the audit's own word out of the
    # full vocabulary; `audit.certified` is whether it stands behind it.
    audit = _audit_verdict.read(output, rc)
    summary_match = _SUMMARY_RE.search(output) or _SUMMARY_LEGACY_RE.search(output)

    overall = (audit.word or "UNKNOWN").upper()
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
    # AND THE GATE'S OWN QUESTION IS `is_green`, NOT "is the word one of two". A green word
    # the audit refused to certify does not authorise a completion claim: that is the whole
    # of this gate's job.
    structurally_complete = audit.is_green
    if not audit.certified and audit.why:
        findings.append(Finding(
            severity="ERROR",
            category="AUDIT_DID_NOT_CERTIFY",
            message=f"the compliance audit did not certify this run: {audit.why}",
            details=("A 'Phase 2+3 complete' claim needs an audit that CERTIFIED, not a "
                     "word printed beside a refusal to vouch for it. Resolve what the "
                     "audit withdrew and re-run it.")))

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
    elif overall == "WAIVED":
        findings.append(Finding(
            severity="INFO", category="DRV_WAIVED",
            message="DRV deviations are owner-approved and disclosed; below baseline quality.",
            details="WAIVED is a measured residual, never a PASS claim."))
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
            # BOTH CHANNELS IN THE MACHINE-READABLE SUMMARY TOO, because this is what the
            # MCP tool and every scripted consumer reads. `overall` is the audit's WORD; it
            # says nothing about whether the audit stood behind it, and a consumer keying on
            # the word alone reaches the same wrong answer the human branches used to.
            "certified": audit.certified,
            "certification_note": audit.why,
            "executed_pass": executed_pass,
            "executed_total": executed_total,
            "waived_deferred": waived_count,
            "canonical_step_count": _TOTAL_REQ,
            "structurally_complete": structurally_complete,
            # AND THE STRONGEST CLAIM IN THIS DOCUMENT NEEDS BOTH. Keyed on the bare word,
            # an uncertified green run published `production_tapeout_ready: true` beside
            # `exit 1` -- the JSON contradicting the exit status of the program that wrote it.
            "production_tapeout_ready": (overall == "PASS" and audit.certified),
        },
        "findings": [asdict(f) for f in findings],
        "underlying_output_tail": "\n".join(output.strip().splitlines()[-20:]),
    }

    if args.json is None:
        # THE PRINTED WORD AND THE EXIT CODE ARE ONE DECISION. These branches used to key
        # on `overall` alone while the exit code keyed on `structurally_complete`, so the
        # moment those two could differ -- which is exactly what reading the rc introduced
        # -- this gate printed `[PASS]` and exited 1. A human reading the line and a script
        # reading `$?` must not get opposite answers from the same run.
        if (overall == _audit_verdict.TIMEOUT_WORD):
            # THE TIMEOUT KEEPS ITS OWN NAME, AND IT GOES FIRST. #525 named this state on
            # purpose -- "stopped before it finished" is not "never audited", and neither is
            # a verdict about the design -- and `_audit_verdict` reports it as uncertified,
            # which is true but not specific. Folding it into the generic branch below
            # relabelled it `[AUDIT_DID_NOT_CERTIFY]` and lost the distinction #525 bought;
            # a regression arm catches that now. The exit code is the same either way.
            print(f"[{_audit_verdict.TIMEOUT_WORD}] phase23_completion_self_audit_check")
            print(f"  Overall: {overall} — the audit did not run to completion, so this is")
            print(f"  NOT a verdict on the project (INCONCLUSIVE, #525).")
            print()
            print("  ⛔ Phase 2+3 completion is NOT authorised, and nothing here is a")
            print(f"     finding about the design. Raise {_pl.AUDIT_TIMEOUT_ENV} and re-run.")
        elif not audit.certified:
            # NOT `[FAIL]`: nothing was found wrong with the design. The audit declined to
            # vouch for its own answer, which is an inability to certify -- the same
            # reading R-0915-159 gave `step_final_audit`.
            print("[AUDIT_DID_NOT_CERTIFY] phase23_completion_self_audit_check")
            print(f"  Overall: {overall} — but the audit did not certify it.")
            print(f"  {audit.why}")
            print()
            print("  ⛔ Phase 2+3 completion is NOT authorised. This is an inability to")
            print("     certify, NOT a defect found in the design.")
        elif overall == _V_NOT_MEASURED:
            # THE WORD #2572 MADE REACHABLE. It used to match no alternative in the old
            # regex, read as "UNKNOWN", and print `[FAIL]` -- an absence labelled a defect.
            print("[NOT_MEASURED] phase23_completion_self_audit_check")
            print(f"  Overall: NOT_MEASURED — the audit could not measure every step, so")
            print(f"  it makes no completion claim either way.")
            print(f"  executed PASS: {executed_pass}/{executed_total} (canonical 34)")
            print()
            print("  ⛔ Phase 2+3 completion is NOT authorised, and this is NOT a FAIL:")
            print("     an unmeasured step said nothing about the design.")
        elif overall == "WAIVED":
            print("[WAIVED] phase23_completion_self_audit_check")
            print("  Overall: WAIVED — owner-approved DRV deviations remain open.")
            print("  Below the recorded baseline quality; WAIVED is never PASS.")
            print(f"  executed PASS: {executed_pass}/{executed_total} (canonical 34)")
        elif overall == "PASS":
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
