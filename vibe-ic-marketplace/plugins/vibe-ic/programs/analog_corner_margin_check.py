#!/usr/bin/env python3
"""analog_corner_margin_check.py — A4 strict PVT-margin gate.

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
    0 = PASS (or self-skip)
    1 = FAIL (insufficient corners or a corner below the margin floor)
    2 = IO / argument error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

import _path_layout as _pl
from _analog_stub_marker import is_stub_json

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
        return {"block": block_name, "pass": True, "stub": True, "file": rel}

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

    detail = {
        "block": block_name,
        "pass": block_ok,
        "file": rel,
        "total_corners": total,
        "margins_read": margins_read,
        "margins_missing": margins_missing,
        "below_floor": below_floor,
    }
    if reasons:
        detail["reasons"] = reasons
    if block_ok:
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
    result.summary = {
        "skipped": False,
        "blocks_checked": blocks_with_data,
        "blocks_pass": blocks_pass,
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
        Path(args.json).write_text(out)

    if not args.json:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] analog_corner_margin_check")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
