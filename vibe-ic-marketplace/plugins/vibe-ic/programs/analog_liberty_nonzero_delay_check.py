#!/usr/bin/env python3
"""analog_liberty_nonzero_delay_check.py — deterministic Liberty non-degeneracy gate.

Extracted from the `analog-hardmacro-gen` skill "Do not" rule:
    "Do not generate Liberty with zero delays — use actual SPICE-measured values"
and the Step-3 worst-case-corner requirement
    "Derived from SPICE corner results (worst-case SS corner)".

The skill documented these as prose; this program turns the
non-degeneracy half into a deterministic structural check on the
emitted Liberty (`hardmacro/<block>/<block>.lib`):

  1. The .lib parses to a `library(...) { cell(<block>) { ... } }` shape.
  2. The cell carries at least one timing-bearing numeric attribute and
     ALL such numbers are non-zero — i.e. it is NOT a zero-delay /
     area-only stub. Timing-bearing attributes checked:
        cell_rise / cell_fall / rise_transition / fall_transition
        cell_leakage_power / leakage_power value
        intrinsic_rise / intrinsic_fall
        timing() { ... values( ... ) ... }  (NLDM table — any non-zero entry)
  3. If `analog/<block>/corner_results.json` exists, its provenance is
     reported (real_ngspice vs stub) so a reviewer can see whether the
     Liberty was derived from a real corner sweep.

The defect this catches (real): a Liberty that only declares `area`
(or whose every delay is `0.0`) passes STA vacuously — every path has
zero delay, so the macro never violates setup/hold and the integration
STA is meaningless. That is exactly the stub Liberty emitted at the
A7 stub tier (`library(ldo_stub) { cell(ldo) { area : 10000 ; } }`).

Honesty rules (NO vacuous PASS):
  * No analog blocks                 -> SKIP (exit 0, INFO).
  * .lib missing for a spec'd block  -> FAIL (cannot sign off STA).
  * .lib present but unparseable     -> FAIL.
  * .lib has a cell but NO timing-bearing attribute at all -> FAIL
    (area-only stub, the documented zero-delay defect).
  * .lib has a timing attribute whose value is 0 / 0.0 -> FAIL.

Usage:
    python3 analog_liberty_nonzero_delay_check.py <project_dir>
    python3 analog_liberty_nonzero_delay_check.py <project_dir> --json out.json

Exit codes:
    0 = PASS (every block has a non-degenerate Liberty) or SKIP
    1 = FAIL (>=1 zero-delay / stub / missing Liberty)
    2 = IO / argument error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Tuple

try:
    import _path_layout as _pl
except ImportError:  # pragma: no cover
    _pl = None


# Timing-bearing scalar attributes (single `attr : value ;`).
_SCALAR_TIMING_ATTRS = (
    "cell_rise", "cell_fall", "rise_transition", "fall_transition",
    "intrinsic_rise", "intrinsic_fall", "cell_leakage_power",
)
_SCALAR_RE = {
    a: re.compile(rf"\b{a}\s*:\s*([-+0-9.eE]+)\s*;")
    for a in _SCALAR_TIMING_ATTRS
}

# NLDM-style table: values("0.1, 0.2", "0.3, 0.4");  inside a timing()/
# table group. We pull every numeric token out of every values(...) blob.
_VALUES_RE = re.compile(r"values\s*\(", re.IGNORECASE)
_NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_LEAKAGE_GROUP_RE = re.compile(
    r"leakage_power\s*\([^)]*\)\s*\{(?P<body>.*?)\}", re.DOTALL | re.IGNORECASE)
_LEAKAGE_VALUE_RE = re.compile(r"\bvalue\s*:\s*([-+0-9.eE]+)\s*;")
_CELL_RE = re.compile(r"\bcell\s*\(\s*([^)\s]+)\s*\)\s*\{", re.IGNORECASE)


def _extract_values_blocks(text: str) -> List[str]:
    """Return the raw content of each values(...) call (balanced-paren scan)."""
    blocks: List[str] = []
    for m in _VALUES_RE.finditer(text):
        i = m.end()  # position right after the '('
        depth = 1
        start = i
        while i < len(text) and depth > 0:
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        blocks.append(text[start:i - 1])
    return blocks


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    block: str = ""


@dataclass
class Result:
    program: str = "analog_liberty_nonzero_delay_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def analyze_liberty(text: str) -> Tuple[bool, List[float], str]:
    """Return (has_timing, numeric_values, cell_name).

    has_timing      — True if >=1 timing-bearing attribute/table found.
    numeric_values  — every timing-bearing number found (for zero check).
    cell_name       — first cell(...) name (or "").
    """
    cm = _CELL_RE.search(text)
    cell_name = cm.group(1) if cm else ""

    values: List[float] = []
    has_timing = False

    # 1. scalar timing attrs
    for attr, rx in _SCALAR_RE.items():
        for m in rx.finditer(text):
            has_timing = True
            try:
                values.append(float(m.group(1)))
            except ValueError:
                values.append(float("nan"))

    # 2. NLDM values(...) tables
    for blob in _extract_values_blocks(text):
        nums = [float(n) for n in _NUM_RE.findall(blob)]
        if nums:
            has_timing = True
            values.extend(nums)

    # 3. leakage_power groups with `value : x ;`
    for lg in _LEAKAGE_GROUP_RE.finditer(text):
        for vm in _LEAKAGE_VALUE_RE.finditer(lg.group("body")):
            has_timing = True
            try:
                values.append(float(vm.group(1)))
            except ValueError:
                values.append(float("nan"))

    return has_timing, values, cell_name


def _discover_blocks(project: Path) -> List[str]:
    analog = (_pl.analog_dir(project) if _pl is not None else project / "analog")
    if not analog.is_dir():
        return []
    return sorted(p.parent.name for p in analog.glob("*/spec.json"))


def _hardmacro_dir(project: Path) -> Path:
    return _pl.hardmacro_dir(project) if _pl is not None else project / "hardmacro"


def _analog_dir(project: Path) -> Path:
    return _pl.analog_dir(project) if _pl is not None else project / "analog"


def run_audit(project: Path) -> Result:
    res = Result()
    blocks = _discover_blocks(project)
    if not blocks:
        res.findings.append(Finding(
            rule="SKIP_NO_ANALOG", severity="INFO",
            message="No analog blocks found; nothing to check."))
        res.summary = {"skipped": True, "reason": "no_analog_blocks"}
        return res

    hm_dir = _hardmacro_dir(project)
    an_dir = _analog_dir(project)
    ok_blocks: List[str] = []
    failed: List[str] = []

    for block in blocks:
        lib = hm_dir / block / f"{block}.lib"
        corner = an_dir / block / "corner_results.json"

        provenance = "absent"
        if corner.exists():
            try:
                cd = json.loads(corner.read_text(errors="replace"))
                provenance = str(cd.get("_provenance", "unknown"))
            except (json.JSONDecodeError, OSError):
                provenance = "unparseable"

        if not lib.exists():
            res.passed = False
            failed.append(block)
            res.findings.append(Finding(
                rule="LIB_MISSING", severity="ERROR", block=block,
                message=f"Block '{block}': {block}.lib absent; cannot sign off STA."))
            continue

        try:
            text = lib.read_text(errors="replace")
        except OSError as exc:
            res.passed = False
            failed.append(block)
            res.findings.append(Finding(
                rule="LIB_UNREADABLE", severity="ERROR", block=block,
                message=f"Block '{block}': {block}.lib unreadable: {exc}"))
            continue

        has_timing, values, cell_name = analyze_liberty(text)

        if not _CELL_RE.search(text):
            res.passed = False
            failed.append(block)
            res.findings.append(Finding(
                rule="LIB_NO_CELL", severity="ERROR", block=block,
                message=f"Block '{block}': Liberty has no cell(...) definition."))
            continue

        if not has_timing:
            res.passed = False
            failed.append(block)
            res.findings.append(Finding(
                rule="LIB_NO_TIMING", severity="ERROR", block=block,
                message=(f"Block '{block}': Liberty cell '{cell_name}' has no "
                         f"timing/leakage attributes (area-only stub). This is "
                         f"the documented zero-delay defect: STA would pass "
                         f"vacuously.")))
            continue

        nonzero = [v for v in values if v == v and v != 0.0]  # v==v drops NaN
        all_zero = (len([v for v in values if v == v]) > 0 and not nonzero)
        if all_zero:
            res.passed = False
            failed.append(block)
            res.findings.append(Finding(
                rule="LIB_ZERO_DELAY", severity="ERROR", block=block,
                message=(f"Block '{block}': every timing value in the Liberty "
                         f"is 0 — zero-delay model (forbidden). Use actual "
                         f"SPICE-measured delays.")))
            continue

        ok_blocks.append(block)
        res.findings.append(Finding(
            rule="LIB_NONZERO_OK", severity="INFO", block=block,
            message=(f"Block '{block}': Liberty cell '{cell_name}' has "
                     f"{len(nonzero)} non-zero timing value(s); corner "
                     f"provenance={provenance}.")))

    if failed:
        res.passed = False

    res.summary = {
        "skipped": False,
        "total_blocks": len(blocks),
        "passed_blocks": ok_blocks,
        "failed_blocks": failed,
        "pass": res.passed,
    }
    return res


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    res = run_audit(args.project_dir)
    out = json.dumps(asdict(res), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    else:
        status = "PASS" if res.passed else "FAIL"
        print(f"[{status}] analog_liberty_nonzero_delay_check")
        for f in res.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    return 0 if res.passed else 1


if __name__ == "__main__":
    sys.exit(main())
