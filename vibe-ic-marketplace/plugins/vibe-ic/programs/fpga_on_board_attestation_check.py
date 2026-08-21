#!/usr/bin/env python3
"""
fpga_on_board_attestation_check.py — Step 28 hardening.

Step 28 (FPGA on-board sign-off) was previously gated by a single JSON
field `all_scenarios_passed: true`. Any agent could write that JSON with
`echo`; no hardware run was required. This program demands real hardware
attestation before PASS:

Required evidence in <project>/:

  1. reports/fpga/on_board_pass.json with fields:
        all_scenarios_passed: true
        bitstream_path:  "phase2/stage1/fpga/final/<name>.sof"
        bitstream_sha:   "sha256:..."       ← must match the .sof on disk
        board:           identifier (e.g. "DE10-Lite 10M50DAF484C7G")
        programmed_at:   ISO timestamp
        scenarios:       [ {name, result, ...} , ...]  ← non-empty list

  2. phase2/stage1/fpga/final/<name>.sof exists and hashes to bitstream_sha,
     AND `bitstream_path` really names a `.sof` UNDER that final directory —
     see "WHICH BITSTREAM" below.

  3. Quartus programmer log showing the .sof was programmed. At least one
     file in reports/fpga/ matching *quartus_pgm*.log OR *pgm*.log OR
     containing the string "quartus_pgm" / "Blaster" / "JTAG chain" /
     "INFO_MSGID_PROGRAMMER_DEVICE_OPENED" / equivalents.

  4. At least one non-JSON hardware evidence artefact — one of:
       - reports/fpga/on_board_evidence/*.jpg|png|mp4   (webcam)
       - reports/fpga/on_board_evidence/*.csv|log|bin  (UART/scope)
       - reports/fpga/provenance_attest.jsonl entries logged via
         provenance_logger with tool=quartus_pgm or similar.

Missing any of 1-4 → FAIL. The combination makes pure-JSON self-attestation
unachievable without either real hardware OR forging four separate artefact
types with matching hashes.

WHICH BITSTREAM (the artefact step 39 DECLARES)
----------------------------------------------
Step 39 is the FINAL FPGA sign-off and declares `phase2/stage1/fpga/final/*.sof`
as its required output. This gate hashed whatever `bitstream_path` happened to
name and never asked WHERE that file lived, so an attestation pointing at
step 6's EARLY-PROTOTYPE bitstream cleared the final sign-off. Reproduced on an
otherwise complete evidence set (programmer log + webcam frame + matching
sha256), with `bitstream_path: "phase2/stage1/fpga/output_files/design.sof"`::

    $ fpga_on_board_attestation_check <proj> --min-scenarios 1
      ✓ all 4 evidence classes present and consistent
    Overall: PASS      rc=0

That path is not an accident of the fixture: `design_one_shot_runner.
_stage_final_bitstream` stages the burned bitstream into
`_path_layout.fpga_final_dir` ONLY when `fpga_burn` really PASSed, and falls
back to fpga_burn's own `sof_path` otherwise — its own comment says step 6's
prototype "stays at `phase2/stage1/fpga/output_files/*.sof` so the prototype
and the final sign-off remain distinguishable". They were distinguishable by
PATH and nothing compared the path.

`bitstream_path` must therefore resolve to a `.sof` under
`_path_layout.fpga_final_dir(project)` — the one location the flow yaml, this
docstring and the stager already agree on. Absolute paths and `..` traversal
are resolved before the containment test, so a path that merely *spells*
`fpga/final` cannot satisfy it.

Usage
-----
    fpga_on_board_attestation_check.py <project_dir>
        [--json out.json]
        [--min-scenarios 4]

Exit codes
----------
    0 = all 4 evidence classes present and consistent
    1 = missing evidence / inconsistent
    2 = io error
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path, PurePosixPath
from typing import Dict, List, Tuple
import _path_layout as _pl


TOOL_MARKERS = [
    "quartus_pgm",
    "Blaster",
    "USB-Blaster",
    "JTAG chain",
    "INFO_MSGID_PROGRAMMER",
    "Device detected",
    "Configuration succeeded",
    "Configuration successful",
    "Quartus Prime Programmer",
]

# The artefact step 39 DECLARES, spelled here exactly as
# `flow/phase1_phase2_phase3.yaml` spells it. The containment test below is
# driven by `_path_layout.fpga_final_dir` (one source of truth for the
# location); this literal is the DRIFT GUARD that keeps the helper and the
# flow declaration pointing at the same place. `fpga_final_dir`'s own
# docstring records that three paths once competed for this concept and none
# of them agreed, which made the declared artefact unproducible — a repoint
# must be loud here rather than silently re-aim the sign-off.
STEP39_DECLARED_BITSTREAM = "phase2/stage1/fpga/final/*.sof"

EVIDENCE_GLOBS = (
    "reports/phase2/fpga/on_board_evidence/*.jpg",
    "reports/phase2/fpga/on_board_evidence/*.jpeg",
    "reports/phase2/fpga/on_board_evidence/*.png",
    "reports/phase2/fpga/on_board_evidence/*.mp4",
    "reports/phase2/fpga/on_board_evidence/*.csv",
    "reports/phase2/fpga/on_board_evidence/*.log",
    "reports/phase2/fpga/on_board_evidence/*.bin",
)


@dataclass
class Finding:
    severity: str
    rule: str
    message: str


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return "sha256:" + h.hexdigest()
    except OSError:
        return ""


def declared_final_bitstream_dir(project: Path) -> Tuple[Path, str]:
    """``(resolved final-bitstream dir, drift note)`` for step 39.

    The location comes from ``_path_layout.fpga_final_dir`` so there is ONE
    source of truth. The drift note is non-empty when that helper no longer
    agrees with :data:`STEP39_DECLARED_BITSTREAM` — i.e. when the gate would
    be certifying a directory the flow does not declare.
    """
    final_dir = _pl.fpga_final_dir(project)
    declared_dir = PurePosixPath(STEP39_DECLARED_BITSTREAM).parent
    try:
        actual_rel = PurePosixPath(final_dir.relative_to(project).as_posix())
    except ValueError:
        actual_rel = None
    note = ""
    if actual_rel != declared_dir:
        note = (f"_path_layout.fpga_final_dir resolves to {actual_rel}, but "
                f"the flow declares step 39's bitstream as "
                f"{STEP39_DECLARED_BITSTREAM}; the layout helper and the flow "
                f"declaration have drifted apart, so this gate cannot say "
                f"which directory it is certifying")
    return final_dir.resolve(), note


def inspect(project: Path, min_scenarios: int = 1) -> List[Finding]:
    findings: List[Finding] = []

    # --- 1. on_board_pass.json ---
    pass_json = _pl.report_path(project, "fpga/on_board_pass.json")
    if not pass_json.exists():
        findings.append(Finding("error", "missing-pass-json",
                                f"{pass_json.relative_to(project)} not found"))
        return findings

    try:
        data = json.loads(pass_json.read_text())
    except json.JSONDecodeError as exc:
        findings.append(Finding("error", "bad-pass-json",
                                f"cannot parse on_board_pass.json: {exc}"))
        return findings

    required_fields = ["all_scenarios_passed", "bitstream_path",
                       "bitstream_sha", "board", "programmed_at",
                       "scenarios"]
    missing = [k for k in required_fields if k not in data]
    if missing:
        findings.append(Finding("error", "pass-json-fields-missing",
                                f"on_board_pass.json lacks: {missing}"))

    if data.get("all_scenarios_passed") is not True:
        findings.append(Finding("error", "not-all-passed",
                                "all_scenarios_passed != true"))

    scenarios = data.get("scenarios", [])
    if not isinstance(scenarios, list) or len(scenarios) < min_scenarios:
        findings.append(Finding("error", "not-enough-scenarios",
                                f"need >= {min_scenarios} scenarios, "
                                f"got {len(scenarios) if isinstance(scenarios, list) else '?'}"))

    # --- 2. bitstream present + hash matches + IS the declared final one ---
    bp = data.get("bitstream_path")
    bsha = data.get("bitstream_sha")
    if bp and bsha:
        abs_bp = (project / bp).resolve() if not Path(bp).is_absolute() else Path(bp).resolve()
        # Step 39 declares `phase2/stage1/fpga/final/*.sof`. Check the attested
        # bitstream is THAT artefact before hashing it: a matching sha256 on
        # step 6's prototype certifies the wrong silicon image. Resolve both
        # sides so `..` and absolute spellings cannot fake containment.
        final_dir, drift = declared_final_bitstream_dir(project)
        if drift:
            findings.append(Finding("error", "final-dir-drift", drift))
        try:
            abs_bp.relative_to(final_dir)
            under_final = True
        except ValueError:
            under_final = False
        if not under_final or abs_bp.suffix.lower() != ".sof":
            try:
                shown = abs_bp.relative_to(project)
            except ValueError:
                shown = abs_bp
            findings.append(Finding(
                "error", "bitstream-not-final",
                f"bitstream_path {bp} resolves to {shown}, which does not "
                f"match the artefact step 39 declares, "
                f"{STEP39_DECLARED_BITSTREAM}. Step 39 certifies the FINAL "
                f"recompiled bitstream; an earlier build (step 6's prototype "
                f"lives in fpga/output_files/) hashes just as well and "
                f"attests the wrong image."))
        if not abs_bp.exists():
            findings.append(Finding("error", "bitstream-missing",
                                    f"bitstream_path {bp} not found on disk"))
        else:
            disk_sha = _sha256(abs_bp)
            if disk_sha != bsha:
                findings.append(Finding("error", "bitstream-hash-mismatch",
                                        f"bitstream_sha {bsha[:18]}... "
                                        f"!= disk {disk_sha[:18]}... — "
                                        f"file modified or hash fabricated"))

    # --- 3. quartus_pgm (or equivalent) log ---
    pgm_candidates = list(((_pl.reports_phase2_dir(project) / "fpga")).glob("*pgm*.log")) + \
                     list(((_pl.reports_phase2_dir(project) / "fpga")).glob("*quartus_pgm*.log")) + \
                     list(((_pl.reports_phase2_dir(project) / "fpga")).glob("*programmer*.log"))
    # Also scan all .log files under reports/fpga/ for tool markers
    if not pgm_candidates:
        pgm_candidates = list(((_pl.reports_phase2_dir(project) / "fpga")).glob("*.log"))

    marker_found = False
    for log in pgm_candidates:
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        for m in TOOL_MARKERS:
            if m in text:
                marker_found = True
                break
        if marker_found:
            break
    if not marker_found:
        findings.append(Finding(
            "error", "no-programmer-log",
            "no Quartus programmer log found in reports/fpga/ "
            f"(need one of: {TOOL_MARKERS[:4]}...)"
        ))

    # --- 4. at least one non-JSON hardware evidence artefact ---
    evidence_files: List[Path] = []
    for g in EVIDENCE_GLOBS:
        evidence_files.extend(project.glob(g))
    # Also accept a provenance_attest.jsonl with an entry tagged quartus_pgm
    attest = _pl.report_path(project, "fpga/provenance_attest.jsonl")
    if attest.exists():
        try:
            for line in attest.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("tool") in ("quartus_pgm", "quartus_pgm.exe") \
                        and rec.get("exit_code") == 0:
                    evidence_files.append(attest)
                    break
        except Exception:
            pass
    if not evidence_files:
        findings.append(Finding(
            "error", "no-hardware-evidence",
            "no non-JSON hardware evidence found. Need at least one of: "
            "reports/fpga/on_board_evidence/*.{jpg,png,mp4,csv,log,bin} "
            "or a provenance_attest.jsonl entry for quartus_pgm."
        ))

    return findings


# ── waiver plumbing (same contract as final_test_attestation_check.py) ──
# Deliberately identical to the sibling gate: a waiver is an entry in the
# project's `waivers.json`, written by `waivers_materialize.py` from the
# machinery-sanctioned ENV_UNAVAILABLE auto-waivers (or hand-authored with a
# named approver). It is NOT a field inside the manifest this gate audits.
_STEP_ID = "39"
_STEP_LABEL = "fpga_on_board_attestation"


def _load_waivers(project: Path) -> List[dict]:
    p = project / "waivers.json"
    if not p.is_file():
        return []
    try:
        return (json.loads(p.read_text()).get("waived_steps") or [])
    except Exception:
        return []


def _step_waived(project: Path, *step_labels: str) -> dict | None:
    """Return the waivers.json entry covering this step, or None."""
    wanted = [str(s).strip() for s in step_labels if str(s).strip()]
    for w in _load_waivers(project):
        if not isinstance(w, dict):
            continue
        sid = str(w.get("id", "")).strip()
        ticket = str(w.get("ticket", "") or "")
        for lbl in wanted:
            if sid == lbl or (lbl in ticket and not lbl.isdigit()):
                return w
    return None


def _write_report(json_path: str | None, payload: dict) -> None:
    if not json_path:
        return
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    Path(json_path).write_text(json.dumps(payload, indent=2,
                                          ensure_ascii=False) + "\n")


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir")
    p.add_argument("--min-scenarios", type=int, default=1)
    p.add_argument("--json", help="Write JSON report to this path")
    p.add_argument("--step-label", default=_STEP_LABEL)
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"fpga_on_board_attestation_check: not a directory: {project}",
              file=sys.stderr)
        return 2

    # WAIVED short-circuit — v1.7.37 hardening.
    #
    # v1.6.99 accepted `verdict in {WAIVED, SKIP}` plus three more fields of the
    # SAME manifest (all_scenarios_passed / review_required / waiver_ticket) as
    # sufficient to return 0. Every one of those fields lives inside the file
    # this gate exists to audit, so a four-line hand-written on_board_pass.json
    # cleared the whole hardware sign-off with no .sof, no programmer log and no
    # evidence artefact — the exact pure-JSON self-attestation the module
    # docstring says is "unachievable". A waiver must come from OUTSIDE the
    # audited artefact, so it is now cross-referenced against the project's
    # `waivers.json` (id 39 / label fpga_on_board_attestation), exactly like the
    # sibling final_test_attestation_check.
    #
    # SKIP is also no longer accepted: SKIP is not a waiver tier, it is what the
    # runner writes when the board test simply did not happen (and it is what
    # the real pure-digital run emits). Only an explicit WAIVED manifest backed
    # by a real waiver short-circuits.
    #
    # The sanctioned no-rig route is UNCHANGED and still resolves: on a
    # disclosed FPGA-skip project, waivers_materialize.py already writes the
    # ENV_UNAVAILABLE cap-gap waiver for id 39, and flow_compliance_check
    # applies it at the step level.
    manifest_path = project / "reports/phase2/fpga/on_board_pass.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError):
            manifest = None
        if isinstance(manifest, dict) and manifest.get("verdict") == "WAIVED":
            if (manifest.get("all_scenarios_passed") is True
                    and manifest.get("review_required") is True
                    and manifest.get("waiver_ticket")):
                waiver = _step_waived(project, _STEP_ID, args.step_label)
                if waiver is not None:
                    print(
                        f"[WAIVED] fpga_on_board_attestation_check: "
                        f"verdict=WAIVED, manifest ticket="
                        f"{manifest['waiver_ticket']}, waivers.json ticket="
                        f"{waiver.get('ticket', '?')} "
                        f"(approver: {waiver.get('approver', '?')})"
                    )
                    _write_report(args.json, {
                        "overall": "WAIVED",
                        "manifest_verdict": "WAIVED",
                        "manifest_waiver_ticket": manifest.get("waiver_ticket"),
                        "waiver": waiver,
                        "findings": [],
                    })
                    return 0
                print(
                    "fpga_on_board_attestation_check: on_board_pass.json "
                    "self-declares verdict=WAIVED but NO matching entry exists "
                    f"in {project.name}/waivers.json (id {_STEP_ID} / label "
                    f"{args.step_label}). A step cannot waive itself from "
                    "inside the artefact this gate audits — falling through to "
                    "the full evidence inspection.",
                    file=sys.stderr)

    findings = inspect(project, min_scenarios=args.min_scenarios)
    errors = [f for f in findings if f.severity == "error"]

    print(f"\n=== FPGA on-board attestation ({project.name}) ===")
    if not findings:
        print("  ✓ all 4 evidence classes present and consistent")
    for f in findings:
        icon = "✗" if f.severity == "error" else "⚠"
        print(f"  {icon} [{f.severity}] {f.rule}: {f.message}")
    print(f"\nOverall: {'PASS' if not errors else 'FAIL'}")

    _write_report(args.json, {
        "overall": "PASS" if not errors else "FAIL",
        "findings": [asdict(f) for f in findings],
    })

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
