#!/usr/bin/env python3
"""analog_flow_compliance_check.py — analog track compliance gate (A1-A9)

Validates that all 9 analog track steps have been completed for every
block listed in analog/analog_block_list.json:

  A1: analog/<block>/spec.json
  A2: analog/<block>/topology.md
  A3: analog/<block>/*.sp
  A4: analog/<block>/corner_results.json
  A5: analog/<block>/layout.mag OR analog/<block>/*.gds
  A6: analog/<block>/drc_clean.flag AND analog/<block>/lvs_match.flag —
      each carrying an explicit clean / match verdict, not merely present
  A7: analog/<block>/pre_vs_post.json
  A8: hardmacro/<block>/<block>.lef
  A9: cosim/<block>_cosim_results.json OR analog/<block>/hw_measurements.json

Each per-block artefact is resolved at the canonical runner root
(`phase3/analog/<block>/`) first and then at the root the flow declares for
that step (`phase1/analog/` for A1, `phase2/analog/` for A2-A4) — the same
resolution the A1-A9 per-step gates use.

Steps may be waived via analog/waivers.json.

NO PASS WITHOUT A DENOMINATOR (#511)
------------------------------------
MEASURED on a structurally empty project (only `input/docs/` and `reports/`,
nothing in them): this gate's ENTIRE output was

    [PASS] analog_flow_compliance_check

one line, rc 0, and no report file written at all. That is byte-identical in
shape to what it prints for a project whose nine A-steps are genuinely
complete, so neither the exit code nor the text could tell "the analog flow
is compliant" from "there was no analog flow". It is the P0 umbrella's most
widely propagated analog verdict, which is what makes the silence expensive.

The two self-skip conditions — no/empty block list, and the ORGANIC #676
class-N/A skip — now state what they examined, in `_gate_denominator`'s fixed
shape, on stdout AND in `summary.denominator`, and render as a DISCLOSED SKIP
(verdict `VACUOUS_PASS`, rc 2 = NOT CHECKED, plus a `VACUOUS_PASS:` token on
stderr) rather than as a PASS. The class-N/A skip is specifically the
`considered > 0, examined == 0` shape #496 exists to make visible: blocks WERE
declared, and none of them was held to an A-step.

The A1-A9 rule itself is untouched. A project with a declared block and a
missing step is still rc 1 with the same ANALOG_<step>_MISSING findings, and
the `--fpga-stub` waiver still promotes exactly what it promoted before.

Usage:
    python3 analog_flow_compliance_check.py <project_dir>
    python3 analog_flow_compliance_check.py <project_dir> --json reports/gates/analog_compliance.json

Exit codes:
    0 = PASS / PASS_WITH_WAIVERS (blocks examined, every A-step accounted for)
    1 = FAIL (missing steps)
    2 = VACUOUS_PASS (no A-step obligation existed to check — disclosed,
        NOT a sign-off) or IO / parse error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import _path_layout as _pl
import _gate_denominator as _gd

GATE = "analog_flow_compliance_check"

#: What ONE unit is, in this gate's own terms. The gate's subject is not the
#: block and not the step but the PAIR: one declared block owes nine A-step
#: obligations, and it is those obligations the rule is applied to.
DENOMINATOR_UNIT = ("A1-A9 step obligation(s) evaluated (one per declared "
                    "analog block per A-step)")

#: rc 2 is this repo's NOT-CHECKED tier: `flow_compliance_check` promotes it
#: to the VACUOUS_PASS verdict tier rather than a bare PASS.
RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = GATE
    version: str = "1.0.0"
    passed: bool = True
    #: PASS / PASS_WITH_WAIVERS / VACUOUS_PASS / FAIL. `passed` keeps its
    #: literal meaning for every existing consumer; `verdict` is where the
    #: four-way answer lives.
    verdict: str = "PASS"
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


ANALOG_STEPS = [
    ("A1", "Spec Extraction"),
    ("A2", "Topology Selection"),
    ("A3", "Netlist Generation"),
    ("A4", "Corner Sweep"),
    ("A5", "Analog Layout"),
    ("A6", "Per-Block Physical Verification (DRC+LVS)"),
    ("A7", "Post-Layout Resim"),
    ("A8", "Hardmacro Gen"),
    ("A9", "Co-Sim / HW Verify"),
]


def _block_list_file(project: Path) -> Optional[Path]:
    """The analog_block_list.json this project actually carries.

    Two roots are legitimate and this gate used to see only one:
    `_pl.analog_dir` == `phase3/analog/` (where the analog runner writes it)
    and `phase1/analog/` (where `flow/phase1_phase2_phase3.yaml` declares
    every A-step's `condition: files_exist:` and where
    `migrate_to_layout_p.py` moves a top-level list). A project laid out as
    its own flow declares therefore made every A-step applicable while this
    gate answered SKIP_NO_ANALOG. Measured on a project with the list at the
    phase1 root and NINE of nine A-steps unproduced: rc=0,
    `summary.skipped: true, reason: no_analog_blocks`, 0 ERROR findings —
    against rc=1, `total_missing: 9`, 9 ERROR findings once the phase1 root
    is resolved.

    Delegates to `_analog_a_check_common.block_list_path` so this gate and
    the A1-A9 per-step gates resolve the SAME file; falls back to the
    canonical root alone if that helper cannot be imported (never widens
    silently, never fails open)."""
    try:
        import _analog_a_check_common as _aac
        return _aac.block_list_path(project)
    except Exception:  # pragma: no cover — degraded to the historic root
        bl = _pl.analog_dir(project) / "analog_block_list.json"
        return bl if bl.is_file() else None


def _load_block_list(project: Path) -> List[str]:
    bl = _block_list_file(project)
    if bl is None:
        return []
    try:
        data = json.loads(bl.read_text(errors="replace"))
        if isinstance(data, dict) and "blocks" in data:
            return [b["name"] if isinstance(b, dict) else str(b)
                    for b in data["blocks"]]
        if isinstance(data, list):
            return [b["name"] if isinstance(b, dict) else str(b)
                    for b in data]
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    return []


def _load_waivers(project: Path) -> Set[Tuple[str, str]]:
    wf = _pl.analog_dir(project) / "waivers.json"
    if not wf.exists():
        return set()
    try:
        data = json.loads(wf.read_text(errors="replace"))
        waivers = data.get("analog_waivers", [])
        return {(w["block"], w["step"]) for w in waivers
                if isinstance(w, dict) and "block" in w and "step" in w}
    except (json.JSONDecodeError, OSError, KeyError):
        return set()


# ── per-block artefact roots ──────────────────────────────────────────────
# `flow/phase1_phase2_phase3.yaml` declares A1's spec under `phase1/analog/`
# and A2-A4's artefacts under `phase2/analog/`, while the analog RUNNER writes
# every block artefact under the single canonical `_pl.analog_dir`
# (== `phase3/analog/`). A5-A9 are declared at `phase3/analog/` too, so for
# those steps the two roots coincide and nothing here changes.
# The A1-A4 per-step gates reconcile the split with
# `_analog_a_check_common.resolve_block_artefact` (canonical first,
# flow-declared root second); this gate read the canonical root only. That
# mismatch did not surface while `_load_block_list` also read only the
# canonical root — the gate skipped such projects outright — but it would now,
# as ANALOG_A1..A4_MISSING on a project whose artefacts sit exactly where its
# own flow declares them, in direct contradiction of the per-step gate's PASS
# on the same file. Same helper, same ordering, one source of truth.
# A8 is absent below on purpose: its artefact is resolved through
# `_pl.hardmacro_dir`, not a per-block analog dir.
_STEP_DECLARED_PHASE = {"A1": 1, "A2": 2, "A3": 2, "A4": 2,
                        "A5": 3, "A6": 3, "A7": 3, "A9": 3}


def _block_dirs(project: Path, block: str, step_id: str) -> List[Path]:
    """Candidate per-block dirs for `step_id`, canonical root first."""
    phase = _STEP_DECLARED_PHASE.get(step_id, 3)
    try:
        import _analog_a_check_common as _aac
        return _aac.block_dir_candidates(project, block, phase)
    except Exception:  # pragma: no cover — degraded to the historic root
        return [_pl.analog_dir(project) / block]


def _any_file(project: Path, block: str, step_id: str, name: str) -> bool:
    return any((d / name).is_file()
               for d in _block_dirs(project, block, step_id))


def _any_glob(project: Path, block: str, step_id: str, pat: str) -> bool:
    return any(d.is_dir() and any(d.glob(pat))
               for d in _block_dirs(project, block, step_id))


def _pv_flag_signed_off(project: Path, block: str, name: str,
                        kind: str) -> bool:
    """A6 sign-off marker check.

    Presence alone is NOT sign-off evidence: `drc_clean.flag` and
    `lvs_match.flag` were accepted on `.exists()`, so a `touch`-created
    0-byte flag certified A6 — and so did a flag whose own text said
    `violations: 17` / `lvs: mismatch`, because the content was never read.
    Measured on a synthetic project: 0-byte flags -> `[PASS]` rc=0, flags
    reading `violations: 17` + `lvs: mismatch` -> `[PASS]` rc=0, while
    `analog_a6_block_pv_check` gave rc=1 A6_PV_DRC_NO_EVIDENCE and
    `analog_a5_layout_check` gave rc=1 on the same two files.

    Reuses A6's own parsers (tool-generic: Magic / KLayout / Calibre /
    Netgen phrasings) rather than writing a second dialect of the same rule,
    exactly as `analog_a5_layout_check` does. If they cannot be imported the
    check degrades to "non-empty", which is still stricter than `.exists()`
    and never fails open on a 0-byte flag."""
    path = None
    for d in _block_dirs(project, block, "A6"):
        cand = d / name
        if cand.is_file():
            path = cand
            break
    if path is None:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if not text.strip():
        return False  # `touch`-created flag — the marker was never written
    try:
        import analog_a6_block_pv_check as _a6
    except Exception:  # pragma: no cover — degraded to the non-empty minimum
        return True
    if kind == "drc":
        count = _a6._parse_drc_count(text)
        return count == 0
    matched = _a6._parse_lvs_match(text)
    return matched is True


def _a4_signed_off(project: Path, block: str) -> bool:
    """A4 sign-off evidence, not merely A4's filename.

    Presence alone is NOT evidence, for exactly the reason `_pv_flag_signed_off`
    above exists. Measured on a real round: ten blocks each carried a
    corner_results.json and this cell read `PASS` for all ten, while A1/A2/A3
    read `MISSING` for all ten in the same matrix — A3's declared output
    `<block>.sp` existed for none of them, so every deck the sweep simulated was
    its own built-in testbench. A matrix that says "netlist MISSING, corner
    sweep PASS" for the same block is reporting a measurement of something the
    run never built.

    Delegates to `analog_a4_corner_sweep_check`'s own provenance predicates so
    the two can never disagree about the same artefact — the same delegation
    `_pv_flag_signed_off` makes to the A6 gate. On import failure it degrades to
    the historic presence check, which is what it always was."""
    path = None
    for d in _block_dirs(project, block, "A4"):
        cand = d / "corner_results.json"
        if cand.is_file():
            path = cand
            break
    if path is None:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    try:
        import analog_a4_corner_sweep_check as _a4
    except Exception:  # pragma: no cover — degraded to the historic minimum
        return True
    rel = str(path)
    corners = data.get("corners") if isinstance(data.get("corners"), list) else []
    if _a4._netlist_disclosed_fail(project, block, data, rel) is not None:
        return False
    if _a4._netlist_absent_fail(project, block, data, corners, rel) is not None:
        return False
    return True


def _check_step(project: Path, block: str, step_id: str) -> bool:
    if step_id == "A1":
        return _any_file(project, block, "A1", "spec.json")
    elif step_id == "A2":
        return _any_file(project, block, "A2", "topology.md")
    elif step_id == "A3":
        return _any_glob(project, block, "A3", "*.sp")
    elif step_id == "A4":
        return _a4_signed_off(project, block)
    elif step_id == "A5":
        return (_any_file(project, block, "A5", "layout.mag") or
                _any_glob(project, block, "A5", "*.gds"))
    elif step_id == "A6":
        # Per-block physical verification: BOTH a DRC-clean marker AND an
        # LVS-match marker, each carrying an actual clean/match verdict.
        return (_pv_flag_signed_off(project, block, "drc_clean.flag", "drc")
                and _pv_flag_signed_off(project, block, "lvs_match.flag",
                                        "lvs"))
    elif step_id == "A7":
        return _any_file(project, block, "A7", "pre_vs_post.json")
    elif step_id == "A8":
        hm = _pl.hardmacro_dir(project) / block / f"{block}.lef"
        return hm.is_file()
    elif step_id == "A9":
        cosim = _pl.mixed_signal_cosim_dir(project) / f"{block}_cosim_results.json"
        return (cosim.is_file() or
                _any_file(project, block, "A9", "hw_measurements.json"))
    return False


def _vacuous(result: AuditResult, rule: str, reason: str,
             summary_reason: str, considered: int = 0,
             details: Optional[dict] = None) -> AuditResult:
    """Record a run that held ZERO A-step obligations to the rule.

    Constructing the denominator with ``examined == 0`` and no reason raises,
    so this gate cannot regress into a silent zero by omission — only by
    writing a reason down, which is reviewable.
    """
    result.findings.append(Finding(rule=rule, severity="INFO", message=reason))
    result.verdict = "VACUOUS_PASS"
    # `passed` keeps its LITERAL meaning — the A1-A9 rule was applied and found
    # nothing wrong — so a consumer reading only that field can no longer be
    # handed a vacuous run as a clean one. It is not a FAIL either: no ERROR
    # finding is emitted and rc is the skip tier. The four-way answer is in
    # `verdict`, the same split `si_mcf_sta_check` makes.
    result.passed = False
    result.summary = {"skipped": True, "reason": summary_reason,
                      "total_blocks": 0, "total_steps": len(ANALOG_STEPS),
                      "total_missing": 0, "total_waived": 0, "pass": False}
    _gd.attach(result.summary, _gd.Denominator(
        unit=DENOMINATOR_UNIT, examined=0, considered=considered,
        not_applicable_reason=reason, details=details or {}))
    return result


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    blocks = _load_block_list(project)

    if not blocks:
        return _vacuous(
            result, "SKIP_NO_ANALOG",
            ("no analog_block_list.json under phase3/analog/ or "
             "phase1/analog/, or it declares no blocks, so no A1-A9 "
             "obligation exists to hold anything to. NOT a sign-off: the "
             "analog track of this project has NOT been checked — see "
             "analog_block_list_emit_check for whether a list SHOULD "
             "have been emitted."),
            "no_analog_blocks")

    # ORGANIC #676 — class-N/A skip. When the IC is positively classified
    # NON-analog (has_analog:false / analog_applicable:false +
    # verification_track=generic_full_stack) AND every declared block is a
    # low_confidence phantom keyword hit, SKIP (N/A) instead of hard-FAILing a
    # pure-digital SoC — matching the sibling analog gates' class awareness.
    # §4.05 no-leak: a real analog IC, or a high-confidence (spec-backed)
    # block, never reaches this skip and is still gated A1-A9.
    try:
        import _analog_a_check_common as _aac
        if _aac.analog_class_is_na(project):
            # `considered > 0, examined == 0` — blocks WERE declared and none
            # of them was held to an A-step. #496's shape, stated rather than
            # inferable only by reading this branch.
            return _vacuous(
                result, "SKIP_DIGITAL_CLASS_NA",
                (f"IC classified non-analog (analog_applicable=false / "
                 f"generic_full_stack) and all {len(blocks)} declared "
                 f"block(s) are low_confidence phantom keyword hits — analog "
                 f"A1-A9 N/A (ORGANIC #676). NOT a sign-off: no A-step "
                 f"artefact of this project was examined."),
                "digital_class_na_low_confidence",
                considered=len(blocks) * len(ANALOG_STEPS),
                details={"declared_blocks": [str(b) for b in blocks]})
    except Exception:
        pass

    waivers = _load_waivers(project)

    matrix: Dict[str, Dict[str, str]] = {}
    total_missing = 0

    for block in blocks:
        matrix[block] = {}
        for step_id, step_name in ANALOG_STEPS:
            if _check_step(project, block, step_id):
                matrix[block][step_id] = "PASS"
                result.findings.append(Finding(
                    rule=f"ANALOG_{step_id}_PASS",
                    severity="INFO",
                    message=f"Block '{block}' step {step_id} ({step_name}): PASS",
                ))
            elif (block, step_id) in waivers:
                matrix[block][step_id] = "WAIVED"
                result.findings.append(Finding(
                    rule=f"ANALOG_{step_id}_WAIVED",
                    severity="INFO",
                    message=f"Block '{block}' step {step_id} ({step_name}): WAIVED",
                ))
            else:
                matrix[block][step_id] = "MISSING"
                total_missing += 1
                result.findings.append(Finding(
                    rule=f"ANALOG_{step_id}_MISSING",
                    severity="ERROR",
                    message=(
                        f"Block '{block}' step {step_id} ({step_name}): MISSING. "
                        f"Run the corresponding skill or add a waiver."
                    ),
                ))

    if total_missing > 0:
        result.passed = False
    result.verdict = "PASS" if result.passed else "FAIL"

    total_waived = sum(1 for b in matrix.values()
                       for s in b.values() if s == "WAIVED")
    result.summary = {
        "skipped": False,
        "total_blocks": len(blocks),
        "total_steps": len(ANALOG_STEPS),
        "matrix": matrix,
        "total_missing": total_missing,
        "total_waived": total_waived,
        "pass": result.passed,
    }
    # Every obligation in the matrix reached the rule body — each one is a
    # `_check_step` call whose answer is recorded — so examined == considered
    # here. The two fields stay distinct anyway: a future precondition that
    # filters obligations out must show up as the gap, not vanish into a
    # single number (#496).
    _gd.attach(result.summary, _gd.Denominator(
        unit=DENOMINATOR_UNIT,
        examined=len(blocks) * len(ANALOG_STEPS),
        considered=len(blocks) * len(ANALOG_STEPS),
        details={"blocks": [str(b) for b in blocks],
                 "steps": [s for s, _ in ANALOG_STEPS],
                 "missing": total_missing,
                 "waived": total_waived}))
    return result


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    # v1.6.144 (#57) — FPGA-prototype-stage stub waiver.
    import _fpga_stub_waiver as _stub
    _stub.add_fpga_stub_argparse(ap)
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return RC_VACUOUS

    result = run_audit(args.project_dir)

    # The waiver promotes a FAIL, and ONLY a FAIL. A vacuous run has nothing to
    # waive — `result.passed` is False there too, which is why the verdict, not
    # `passed`, guards this branch: promoting a VACUOUS_PASS to
    # PASS_WITH_WAIVERS would dress an unexamined project as a waived one.
    if result.verdict == "FAIL" and _stub.fpga_stub_waiver_active(args):
        result.passed = True
        result.verdict = "PASS_WITH_WAIVERS"
        result.summary["fpga_stub_waiver_applied"] = True
        result.summary["waiver_reason"] = _stub.fpga_stub_reason()
        for f in result.findings:
            if f.severity == "ERROR":
                f.severity = "WARNING"

    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    if not args.json:
        # The verdict line carries the denominator ON ITSELF: a reader of the
        # one line this gate prints must be able to see how many A-step
        # obligations stood behind it (#511).
        print(f"[{result.verdict}] {GATE}: {_gd.line_of(result.summary)}")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.verdict == "VACUOUS_PASS":
        denom = result.summary.get(_gd.DENOMINATOR_KEY) or {}
        # Second, rc-independent channel — emitted even under --json, where
        # stdout is deliberately empty, so a text consumer is never handed
        # silence. `flow_compliance_check._stdout_signals_vacuous` matches this
        # token at line start.
        print(f"VACUOUS_PASS: {denom.get('not_applicable_reason', '')}",
              file=sys.stderr)
        return RC_VACUOUS

    return RC_PASS if result.passed else RC_FAIL


if __name__ == "__main__":
    sys.exit(main())
