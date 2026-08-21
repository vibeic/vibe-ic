#!/usr/bin/env python3
"""analog_corner_margin_check.py — A4 strict PVT-margin gate. NOT WIRED.

╔════════════════════════════════════════════════════════════════════════════╗
║ NOT WIRED — DELIBERATELY, AND HERE IS THE MEASUREMENT (vibe-ic#693)        ║
╚════════════════════════════════════════════════════════════════════════════╝

This gate is referenced from no executable location: not the flow definition,
not `benchmark/CAPTURE_ROUTING.json`, not another program, not `hooks/`, not
`tools/ci/`. That is not an oversight left standing — it is the conclusion,
and this block is the disclosure the repo's own rule requires (a gate must
never be both unwired and unlisted). It is ALSO recorded in
`programs/checker_execution_wiring_baseline.json`, where a machine reads it.

BOTH OF ITS TWO RULES ARE UNREACHABLE BY THE PRODUCER THAT WRITES THE
ARTEFACT IT GRADES. Neither is a threshold that is merely strict; each is a
question the flow has no way to answer, so wiring it in any tier — blocking
OR advisory — makes it say the same wrong thing on every analog run forever.

  (1) `MIN_CORNERS = 27` HAS NO PRODUCER. The threshold is quoted honestly
      from the skill ("3 process x 3 temp x 3 voltage"). The producer,
      `analog_real_corner_sweep.build_pvt_grid`, iterates
      `process_corners x PVT_TEMPS` and nothing else: `PVT_PROCESS` is
      (ss, tt, ff) and `PVT_TEMPS` is (-40C, 27C, 125C). THERE IS NO VOLTAGE
      AXIS ANYWHERE IN THE GRID — the emitted corner dicts carry
      name/process/temp_c/simulator_run/vout_v and no supply field at all.
      9 is the ceiling by construction, which is why the wired project-wide
      sibling `analog_corner_sweep_check` sets MIN_CORNERS = 9 for the same
      artefact. Measured over the published corpus: every corner artefact
      reports `total_corners: 9`. So this rule fails 100% of analog runs,
      permanently, on a defect no producer can fix — the shape that trains
      people to waive a gate rather than read it.

  (2) `corners[].margin` IS THE SPEC TOLERANCE, NOT AN ACHIEVED MARGIN, so
      `_read_margin_pct` branch 2 is a category error and the polarity is
      inverted: a TIGHTER (better) spec makes the gate REDDER.
      `build_pvt_grid` writes `entry["margin"] = tol`, and the call site
      passes `target.get("tol")` — the spec's tolerance BAND, either from the
      static per-block target table or derived as
      `max(|hi-tgt|, |tgt-lo|) / |tgt|`. THE PROOF that it cannot be a
      per-corner measurement, from one published artefact: its nine corners
      carry NINE DISTINCT measured values and ONE identical `margin`
      (0.0833...), repeated verbatim. A field that varies with nothing while
      the measurement varies with everything is a property of the spec, not
      of the corner. Read as an achieved margin it produced
      `MARGIN_BELOW_FLOOR: corner 'ss_m40c' margin 8.3% < 10% floor` on a
      run whose measured values all sit inside spec. Worse, the static
      default band for one common block type is 0.05 — 5%, hard-coded BELOW
      this gate's own 10% floor — so such a block fails by construction while
      a LOOSER spec would clear.

  (3) On today's schema the margin half is additionally VACUOUS: the
      published corner artefacts carry no `margin_pct`, no `value`/`target`
      pair, so `margins_read: 0, margins_missing: 9`. Only the unreachable
      count rule ever fires.

WHAT IS ALREADY THE GATE OF RECORD. `analog_a4_corner_sweep_check` is wired
at A4 in `flow/phase1_phase2_phase3.yaml` AND invoked inline by
`analog_one_shot_runner` (`"A4_corner_sweep": .../analog_a4_corner_sweep_check
.py`). It already enforces the anti-stub rule, simulator/netlist provenance,
the worst-corner margin finding and the `design_content` disclosure.
`analog_corner_sweep_check` enforces the reachable 9-corner floor. The ONLY
thing this file adds that no wired gate has is exactly the two rules measured
broken above.

WHAT WOULD MAKE THIS WIREABLE — a PRODUCER change, not a gate change:
  * give `build_pvt_grid` a voltage axis, so 27 corners become achievable;
  * emit a genuine per-corner `margin_pct` under a key distinct from `tol`,
    so an achieved margin can be told from a spec band.
Only then is a >=27 / >=10% rule a tightening rather than a permanent red,
and only then does this file become a gate rather than a claim about one.

NOTE ON THE `ENFORCEMENT:` LINE THIS BLOCK DOES NOT CARRY. `flow_gate_
enforcement_audit._DECL_RE` accepts only `blocking|advisory`; a declared
`advisory` on an UNWIRED gate is recorded as `orphan::` and fails that audit
(measured: rc 1), and a literal `ENFORCEMENT: none` matches nothing at all,
so it would record nothing while looking like a declaration. The two
registers that DO record this are the baseline named above and this block.

────────────────────────────────────────────────────────────────────────────
Codifies the fixed thresholds in
`skills/analog-output-verify/SKILL.md` (A4 corner_sweep checklist):

  * "A4_corners.json covers ≥27 corners" (3 process × 3 temp × 3
    voltage = the full PVT cube, NOT the lighter 9-corner
    3-process × 3-temp matrix that `analog_corner_sweep_check.py`
    enforces with MIN_CORNERS=9).
  * "Margin to spec on every corner ≥10%".

For each analog block this gate looks for the A4 corner-sweep
artefact, accepting either canonical filename:
  * `A4_corners.json`     (the name documented in SKILL.md)
  * `corner_results.json` (the name the runner actually emits)

and verifies:
  1. the corner array declares ≥ 27 corners;
  2. every corner whose margin can be read meets ≥ 10 %.

Margin is read from (in priority order):
  * `margin_pct`           — explicit percent (e.g. 12.5 → 12.5 %)
  * `margin`               — fraction (0.12) OR percent (12.0); a
                             value > 1.0 is treated as already-percent
  * derived from `value` + `target` (+ optional `tolerance`/`tol`)
    when no explicit margin field is present.

NO FALSE ALERTS (chip-AGNOSTIC, deterministic):
  * No analog/ dir, no corner file, or a deterministic-stub file →
    self-skip (exit 0, INFO) — never crash, never FAIL.
  * A corner with NO readable numeric margin is reported MISSING (not
    a violation) — the gate only flags a corner when it can prove the
    margin is < 10 %. This avoids over-flagging informational corners
    (POR trip-point, DAC monotonicity) that legitimately carry no
    fixed numeric target.
  * Unparsable JSON / IO error → ERROR finding, but the run still
    completes and reports per-block status.

Usage:
    python3 analog_corner_margin_check.py <project_dir>
    python3 analog_corner_margin_check.py <project_dir> \
        --json reports/gates/analog_corner_margin.json

Exit codes:
    0 = PASS: at least one block's A4 corner artefact was read and every
        corner it declares meets the floor. The verdict WORD carries the
        tier: `PASS_STRUCTURE_ONLY` when every certified block's artefact
        records that its circuit came from a library default (a disclosed
        honest ceiling — it certifies, in its own tier, and never as a
        design-bound pass).
    1 = FAIL (insufficient corners, a corner below the margin floor, or an
        artefact that declines to say what circuit it measured —
        MARGIN_SUBJECT_UNDECLARED)
    2 = VACUOUS: nothing was examined — no analog/ directory, or no block
        carries a readable A4 corner artefact (a deterministic stub reads as
        no data). #521: both used to be rc 0, so a margin gate that read no
        margin was credited in the plain PASS tier. Also rc 2 for an IO /
        argument error.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

import _path_layout as _pl
import _vacuous_exit as _vx
import _analog_a_check_common as _acc
from _analog_stub_marker import is_stub_json
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

# ── THE STRICTEST CLAIM IN THE REPO IS STILL A CLAIM ABOUT SOMETHING ──────
# THE RULE, with no tool, step or block name in it:
#
#   A gate that re-derives a verdict from an artefact's own numbers is making
#   a claim about the circuit those numbers describe. It must read what that
#   circuit is, and it must not report a measurement of a library default as a
#   measurement of the design — nor certify at all from an artefact that will
#   not say which of the two it holds.
#
# MEASURED, on three synthetic trees identical in every artefact except the
# one recorded `design_content` value: this gate re-derived the strictest PVT
# claim in the repo — 27 corners, every corner ≥ 10 % margin — and answered
# `[PASS]` rc 0 with a BYTE-IDENTICAL `--json` summary on the design-bound
# tree, the structure-only tree and the silent one. 27 corners on a library
# nominal is a self-test of the topology library; the spec it satisfied is the
# design's, and the circuit that satisfied it is not.
#
# THREE OUTCOMES, ranked so that disclosure is never the expensive answer,
# exactly as the sibling corner gates rank them:
#   design-bound   -> PASS, unchanged.
#   structure-only -> PASS_STRUCTURE_ONLY. It certifies, in its own tier, and
#                     leaves the design-bound pass count. Not a FAIL: the
#                     bounded inputs did not determine the content, and
#                     failing an honest ceiling teaches the next run to stop
#                     being honest.
#   undisclosed    -> does not certify. The gate cannot say what it graded.
#
# ASKED LAST, after the corner-count rule and after the margin rule, so a
# reader is never sent to fix the wrong thing first: "your 14th corner is 5 %
# below the floor" names a deeper cause and answers "what did you measure?" as
# a side effect; the reverse is not true.
#
# READ FROM THE ARTEFACT THIS GATE GRADES, with no fallback — the corner
# artefact IS what this gate reads, so it is the artefact whose own record
# decides, identically to `analog_a4_corner_sweep_check`, the gate of record
# for that file. A consumer that resolved it more leniently than its own gate
# of record would re-open the gap by another door.

# Thresholds — verbatim from skills/analog-output-verify/SKILL.md (A4):
#   "A4_corners.json covers ≥27 corners" (3 process × 3 temp × 3 voltage)
#   "Margin to spec on every corner ≥10%"
MIN_CORNERS = 27
MIN_MARGIN_PCT = 10.0

# Both the skill-documented name and the runner-emitted name.
CORNER_FILENAMES = ("A4_corners.json", "corner_results.json")


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "analog_corner_margin_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _corner_file_for(block_dir: Path) -> Optional[Path]:
    """Return the first existing A4 corner artefact in `block_dir`."""
    for name in CORNER_FILENAMES:
        cand = block_dir / name
        if cand.is_file():
            return cand
    return None


def _read_margin_pct(corner: dict) -> Optional[float]:
    """Extract a margin-to-spec percentage from one corner dict.

    Returns the margin in PERCENT, or None when no numeric margin can
    be established (→ caller reports MISSING, never a violation).
    chip-AGNOSTIC — keyed on field shape only.
    """
    if not isinstance(corner, dict):
        return None

    # 1) explicit percent
    mp = corner.get("margin_pct")
    if isinstance(mp, (int, float)):
        return float(mp)

    # 2) `margin` as fraction (<=1.0) or already-percent (>1.0)
    m = corner.get("margin")
    if isinstance(m, (int, float)):
        return float(m) * 100.0 if abs(m) <= 1.0 else float(m)

    # 3) derive from value + target (+ tolerance band when present)
    value = corner.get("value")
    target = corner.get("target")
    if isinstance(value, (int, float)) and isinstance(target, (int, float)) \
            and target != 0:
        rel_err = abs(value - target) / abs(target)  # fraction off-target
        tol = corner.get("tolerance")
        if tol is None:
            tol = corner.get("tol")
        if isinstance(tol, (int, float)) and tol > 0:
            tol_frac = float(tol) if abs(tol) <= 1.0 else float(tol) / 100.0
            # margin = how far inside the spec band, as % of the band
            margin_frac = (tol_frac - rel_err) / tol_frac
            return margin_frac * 100.0
        # no tolerance band → margin = headroom to target itself
        return (1.0 - rel_err) * 100.0

    return None


def _check_block(project: Path, block_dir: Path,
                 result: AuditResult) -> Optional[dict]:
    """Check one block. Returns a per-block detail dict, or None when
    the block has no A4 artefact / is a stub (skipped, not failed)."""
    block_name = block_dir.name
    cf = _corner_file_for(block_dir)
    if cf is None:
        return None  # no A4 artefact for this block → skip silently

    rel = str(cf.relative_to(project))
    data = _load_json(cf)
    if data is None:
        result.findings.append(Finding(
            rule="CORNER_PARSE_ERROR",
            severity="ERROR",
            message=f"Cannot parse {rel}",
            file=rel,
        ))
        result.passed = False
        return {"block": block_name, "pass": False,
                "reason": "parse_error", "file": rel}

    # Deterministic stub demonstrates flow shape, not real PVT closure —
    # never FAIL it on the strict 27-corner / 10%-margin thresholds.
    if is_stub_json(data):
        result.findings.append(Finding(
            rule="CORNER_MARGIN_STUB_SKIPPED",
            severity="INFO",
            message=(f"Block '{block_name}': deterministic-stub corner "
                     f"data — strict margin gate skipped"),
            file=rel,
        ))
        # Returned BEFORE the certification question on purpose: the stub tier
        # is its own disclosure, decided earlier, and it already says the
        # numbers here are not this design's. Same ordering the sibling
        # yield-vs-spec gate uses for the same branch.
        return {"block": block_name, "pass": True, "stub": True, "file": rel,
                "content": _acc.CONTENT_UNDISCLOSED}

    corners = data.get("corners")
    if not isinstance(corners, list):
        corners = []
    total = data.get("total_corners")
    if not isinstance(total, int):
        total = len(corners)

    block_ok = True
    reasons: List[str] = []

    # (1) corner-count floor
    if total < MIN_CORNERS:
        result.findings.append(Finding(
            rule="INSUFFICIENT_PVT_CORNERS",
            severity="ERROR",
            message=(
                f"Block '{block_name}': only {total} corners "
                f"(minimum {MIN_CORNERS} required = 3 process × 3 temp "
                f"× 3 voltage)"
            ),
            file=rel,
        ))
        result.passed = False
        block_ok = False
        reasons.append("insufficient_corners")

    # (2) per-corner margin floor — only flag corners whose margin we
    #     can actually read; corners with no numeric margin → MISSING.
    margins_read = 0
    margins_missing = 0
    below_floor = 0
    for idx, corner in enumerate(corners):
        mp = _read_margin_pct(corner if isinstance(corner, dict) else {})
        if mp is None:
            margins_missing += 1
            continue
        margins_read += 1
        if mp < MIN_MARGIN_PCT:
            below_floor += 1
            cname = (corner.get("name") if isinstance(corner, dict)
                     else None) or f"#{idx}"
            result.findings.append(Finding(
                rule="MARGIN_BELOW_FLOOR",
                severity="ERROR",
                message=(
                    f"Block '{block_name}': corner '{cname}' margin "
                    f"{mp:.1f}% < {MIN_MARGIN_PCT:.0f}% floor"
                ),
                file=rel,
            ))
            result.passed = False
            block_ok = False

    if below_floor:
        reasons.append("margin_below_floor")

    if margins_read == 0 and margins_missing:
        result.findings.append(Finding(
            rule="MARGIN_DATA_MISSING",
            severity="INFO",
            message=(
                f"Block '{block_name}': {margins_missing} corner(s) carry "
                f"no numeric margin — margin floor not asserted "
                f"(informational corners)"
            ),
            file=rel,
        ))

    # READ here, beside the numbers it describes; ACTED ON below, LAST.
    content = _acc.classify_design_content(data.get("design_content"))

    detail = {
        "block": block_name,
        "pass": block_ok,
        "content": content,
        "file": rel,
        "total_corners": total,
        "margins_read": margins_read,
        "margins_missing": margins_missing,
        "below_floor": below_floor,
    }
    if reasons:
        detail["reasons"] = reasons

    # ── the certification question, asked LAST ────────────────────────────
    if block_ok and content == _acc.CONTENT_UNDISCLOSED:
        detail["pass"] = False
        detail.setdefault("reasons", []).append("design_content_undeclared")
        result.findings.append(Finding(
            rule="MARGIN_SUBJECT_UNDECLARED",
            severity="ERROR",
            message=(
                f"Block '{block_name}': {total} corners and every readable "
                f"margin ≥ {MIN_MARGIN_PCT:.0f}%, and the artefact records no "
                f"answer to what circuit produced them (`design_content` "
                f"{data.get('design_content')!r}) — so the PVT margin "
                f"re-derived here cannot be reported as this design's. Naming "
                f"a library default (`{_acc.CONTENT_STRUCTURE_ONLY}`) "
                f"certifies in its own tier; declining to answer does not, or "
                f"saying nothing would cost less than saying so."
            ),
            file=rel,
        ))
        result.passed = False
    elif block_ok and content == _acc.CONTENT_STRUCTURE_ONLY:
        # Disclosed as a library default. The margins above are real, and they
        # are margins OF THAT TOPOLOGY — reported, never as this design's.
        result.findings.append(Finding(
            rule="CORNER_MARGIN_STRUCTURE_ONLY",
            severity="WARNING",
            message=(
                f"Block '{block_name}': {total} corners, {margins_read} "
                f"margin(s) checked, all ≥ {MIN_MARGIN_PCT:.0f}% — OF A "
                f"LIBRARY TOPOLOGY. The artefact records that its circuit came "
                f"from a topology library and that no bound input reached any "
                f"device parameter. Not missing (re-running produces the same "
                f"artefact) and not a design-bound pass."
            ),
            file=rel,
        ))
    elif block_ok:
        result.findings.append(Finding(
            rule="CORNER_MARGIN_OK",
            severity="INFO",
            message=(
                f"Block '{block_name}': {total} corners, "
                f"{margins_read} margin(s) checked, all ≥ "
                f"{MIN_MARGIN_PCT:.0f}%"
            ),
            file=rel,
        ))
    return detail


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    analog_dir = _pl.analog_dir(project)
    if not analog_dir.is_dir():
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG_DIR",
            severity="INFO",
            message="No analog/ directory; skipping corner-margin check",
        ))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    block_dirs = sorted(d for d in analog_dir.iterdir() if d.is_dir())
    details = []
    blocks_with_data = 0
    for bdir in block_dirs:
        detail = _check_block(project, bdir, result)
        if detail is not None:
            blocks_with_data += 1
            details.append(detail)

    if blocks_with_data == 0:
        result.findings.append(Finding(
            rule="SKIP_NO_CORNER_DATA",
            severity="INFO",
            message=(f"No A4 corner artefact "
                     f"({' / '.join(CORNER_FILENAMES)}) found; skipping"),
        ))
        result.summary = {"skipped": True, "reason": "no_corner_data"}
        return result

    blocks_pass = sum(1 for d in details if d.get("pass"))
    so = [d["block"] for d in details
          if d.get("pass") and not d.get("stub")
          and d.get("content") == _acc.CONTENT_STRUCTURE_ONLY]
    design_bound = sum(1 for d in details
                       if d.get("pass") and not d.get("stub")
                       and d.get("content") == _acc.CONTENT_DESIGN_BOUND)
    # A pass over a library default is a pass in its own tier, so it travels
    # on the verdict WORD as well as in the JSON. Only when NO block cleared
    # the gate as a design-bound one: a project with both has a design-bound
    # margin to report, and the structure-only subset is named beside it.
    verdict_tier = ("PASS_STRUCTURE_ONLY"
                    if (result.passed and so and not design_bound) else "PASS")
    result.summary = {
        "skipped": False,
        "blocks_checked": blocks_with_data,
        "blocks_pass": blocks_pass,
        # The design-bound pass count is the one a reader wants when asking
        # "did THIS DESIGN's PVT margin close" — `blocks_pass` answers a
        # different question and is kept unchanged for back-compat.
        "blocks_design_bound_pass": design_bound,
        "blocks_structure_only": len(so),
        "structure_only_blocks": so,
        "verdict_tier": verdict_tier,
        "blocks_fail": blocks_with_data - blocks_pass,
        "min_corners_required": MIN_CORNERS,
        "min_margin_pct": MIN_MARGIN_PCT,
        "details": details,
        "pass": result.passed,
    }
    return result


def main(argv: Optional[list] = None) -> int:
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

    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)

    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)

    so_blocks = (result.summary or {}).get("structure_only_blocks") or []
    if not args.json:
        # The tier travels on the verdict WORD — `pass_token` is the seam
        # `_vacuous_exit` already provides for it — so a reader of the one
        # line can tell this design's PVT margin from a library topology's.
        print(_vx.verdict_line(
            "analog_corner_margin_check", result.passed, skipped, reason,
            pass_token=((result.summary or {}).get("verdict_tier") or "PASS")))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    # LAST, SHORT, and on every path — the disclosure the flow auditor reads
    # from a fixed-width TAIL of this stream, whatever the verdict was. To
    # stderr for the same reason `announce_vacuous` is: `--json` puts a
    # document on stdout and a sentinel mixed into it would not parse.
    if so_blocks:
        names = ", ".join(str(b) for b in so_blocks)
        if len(names) > 60:
            names = f"{names[:57]}..."
        print(f"{_acc.STRUCTURE_ONLY_TOKEN} {len(so_blocks)} corner "
              f"artefact(s) ({names}) came from a library default, not a "
              f"bound input [analog_corner_margin_check]", file=sys.stderr)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
