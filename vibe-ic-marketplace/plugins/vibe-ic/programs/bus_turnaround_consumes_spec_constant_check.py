#!/usr/bin/env python3
"""bus_turnaround_consumes_spec_constant_check.py — R1 deterministic gate

For any half-duplex protocol project, scan the L2/L8 timing package for
constants whose names match turnaround/response-delay patterns. Then grep
RTL for references. If a constant is defined but referenced 0 times
outside its own declaration line → ERROR.

v0.106 upgrade (BACKLOG-v7 P1.2): also validates magnitude. Derives
expected cycle count from L2 tSRS_min_us × core_clk_hz, compares against
L8/RTL declared value. Too-short → ERROR, too-long (>5×) → WARNING.

Mitigation: comment `// turnaround-spec-N/A` on the declaration line.

Usage:
    python3 bus_turnaround_consumes_spec_constant_check.py <project_dir>
    python3 bus_turnaround_consumes_spec_constant_check.py <project_dir> --json

Exit codes:
    0 = all turnaround constants referenced and magnitude OK
    1 = dead constant or magnitude out of range
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional
import _path_layout as _pl

# Kimi-scale fix — this gate audits AUTHORED RTL SOURCE. Collection routes
# through the shared collector (canonical phase2/stage1/rtl preferred;
# generated netlist/sim/verify outputs + >8MB files excluded on fallback) so a
# 342 MB emitted netlist can never enter the per-constant reference scan again
# (see _specrtl_common.rtl_source_files for the full scale rationale). The
# L2/L8 JSON reads (generated_docs) and the mitigation marker are untouched.
try:
    from _specrtl_common import rtl_source_files
except ImportError:                      # packaged relative import
    from ._specrtl_common import rtl_source_files

TURNAROUND_REGEX = re.compile(
    r"(t_?srs|response.?delay|turnaround|bus.?guard|reply.?gap|slave.?reply)",
    re.IGNORECASE,
)

MITIGATION_MARKER = "turnaround-spec-N/A"

DEFINE_RE = re.compile(r"^\s*`define\s+(\w+)")
LOCALPARAM_RE = re.compile(r"\blocalparam\b.*?\b(\w+)\s*=")
PARAMETER_RE = re.compile(r"\bparameter\b.*?\b(\w+)\s*=")


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "bus_turnaround_consumes_spec_constant_check"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def discover_rtl_files(base: Path) -> List[Path]:
    # Kimi-scale fix: shared authored-RTL collector. This gate has always
    # also scanned *.vh/*.svh headers (turnaround `define/localparam
    # constants live there), so the suffix set is widened accordingly.
    return rtl_source_files(base, exts=("*.v", "*.sv", "*.vh", "*.svh"))


def extract_declarations(rtl_files: List[Path]) -> List[dict]:
    decls = []
    for fpath in rtl_files:
        try:
            lines = fpath.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            for regex in (DEFINE_RE, LOCALPARAM_RE, PARAMETER_RE):
                m = regex.search(line)
                if m:
                    name = m.group(1)
                    if TURNAROUND_REGEX.search(name):
                        mitigated = MITIGATION_MARKER in line
                        decls.append({
                            "name": name,
                            "file": str(fpath),
                            "line": i,
                            "mitigated": mitigated,
                            "raw": line.strip(),
                        })
    return decls


def count_references(name: str, rtl_files: List[Path], decl_file: str, decl_line: int) -> int:
    pattern = re.compile(r"\b" + re.escape(name) + r"\b")
    refs = 0
    for fpath in rtl_files:
        try:
            lines = fpath.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            if str(fpath) == decl_file and i == decl_line:
                continue
            if pattern.search(line):
                refs += 1
    return refs


def _load_json_glob(base: Path, pattern: str) -> Optional[dict]:
    """Load first matching JSON file under base/generated_docs/."""
    gd = _pl.generated_docs_dir(base)
    if not gd.is_dir():
        return None
    for p in sorted(gd.glob(pattern)):
        try:
            return json.loads(p.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _extract_constant_value(decls: list, rtl_files: List[Path]) -> Optional[int]:
    """Extract the numeric value of the first turnaround constant from RTL."""
    value_re = re.compile(r"=\s*(\d+)")
    for d in decls:
        m = value_re.search(d["raw"])
        if m:
            return int(m.group(1))
    return None


def check_magnitude(base: Path, decls: list) -> Optional[List[Finding]]:
    """BACKLOG-v7 P1.2: validate turnaround magnitude against L2/L8 spec.

    Derives expected cycle count from L2 tSRS_min_us × core_clk_hz,
    compares against the RTL-declared constant value.
    """
    findings: List[Finding] = []

    l2 = _load_json_glob(base, "L2_*.*json")
    l8 = _load_json_glob(base, "L8_*.*json")

    if not l2 and not l8:
        return None

    t_srs_min_us: Optional[float] = None
    core_clk_hz: Optional[float] = None

    if l2:
        for key in ("tSRS_min_us", "t_srs_min_us", "turnaround_min_us", "response_delay_min_us"):
            if key in l2:
                try:
                    t_srs_min_us = float(l2[key])
                except (TypeError, ValueError):
                    pass
                break
        for key in ("core_clk_hz", "clk_hz", "clock_frequency_hz"):
            if key in l2:
                try:
                    core_clk_hz = float(l2[key])
                except (TypeError, ValueError):
                    pass
                break

    if l8:
        if t_srs_min_us is None:
            for key in ("tSRS_min_us", "t_srs_min_us", "turnaround_min_us"):
                if key in l8:
                    try:
                        t_srs_min_us = float(l8[key])
                    except (TypeError, ValueError):
                        pass
                    break
        if core_clk_hz is None:
            for key in ("core_clk_hz", "clk_hz", "clock_frequency_hz"):
                if key in l8:
                    try:
                        core_clk_hz = float(l8[key])
                    except (TypeError, ValueError):
                        pass
                    break

    if t_srs_min_us is None or core_clk_hz is None or core_clk_hz <= 0:
        findings.append(Finding(
            rule="MAGNITUDE_SKIP",
            severity="INFO",
            message="Cannot derive expected turnaround cycles (missing tSRS_min_us or core_clk_hz in L2/L8)",
        ))
        return findings

    expected_cyc = math.ceil(t_srs_min_us * core_clk_hz / 1e6)
    rtl_files = discover_rtl_files(base)
    declared_cyc = _extract_constant_value(decls, rtl_files)

    if declared_cyc is None:
        findings.append(Finding(
            rule="MAGNITUDE_SKIP",
            severity="INFO",
            message="Turnaround constant found but numeric value not extractable",
        ))
        return findings

    if declared_cyc < expected_cyc:
        findings.append(Finding(
            rule="TURNAROUND_TOO_SHORT",
            severity="ERROR",
            message=(
                f"Turnaround constant = {declared_cyc} cycles but spec requires "
                f">= {expected_cyc} cycles (tSRS_min={t_srs_min_us} µs × "
                f"clk={core_clk_hz/1e6:.1f} MHz). Host residue collision risk."
            ),
        ))
    elif declared_cyc > 5 * expected_cyc:
        findings.append(Finding(
            rule="TURNAROUND_TOO_LONG",
            severity="WARNING",
            message=(
                f"Turnaround constant = {declared_cyc} cycles, >5× expected "
                f"{expected_cyc} cycles. Host may time out."
            ),
        ))
    else:
        findings.append(Finding(
            rule="TURNAROUND_MAGNITUDE_OK",
            severity="INFO",
            message=(
                f"Turnaround constant = {declared_cyc} cycles, expected >= {expected_cyc} "
                f"(within 1-5× range). OK."
            ),
        ))

    return findings


def run_audit(base: Path) -> AuditResult:
    result = AuditResult()
    rtl_files = discover_rtl_files(base)

    if not rtl_files:
        result.findings.append(Finding(
            rule="NO_RTL_FILES",
            severity="WARNING",
            message="No RTL files found; skipping turnaround constant check",
        ))
        result.summary = {"rtl_files": 0, "turnaround_constants": 0, "dead": 0}
        return result

    decls = extract_declarations(rtl_files)
    dead_count = 0
    referenced_count = 0

    # Wave 35 (v0.119.67) — behavior-based fix: pass as long as AT
    # LEAST ONE turnaround constant family member is consumed by RTL.
    # Declared-but-unused MAX/MIN siblings are tolerated when a sibling
    # IS consumed (e.g. `T_SRS_MIN_CYC` consumed by FSM, `T_SRS_MAX_CYC`
    # declared as a documentation upper-bound never wired into a
    # comparator). The original Wave-1 strict rule false-positived on
    # this textbook half-duplex MIN/MAX pair pattern.
    for d in decls:
        if d["mitigated"]:
            result.findings.append(Finding(
                rule="TURNAROUND_MITIGATED",
                severity="INFO",
                message=f"Turnaround constant '{d['name']}' mitigated with turnaround-spec-N/A",
                file=d["file"],
                line=d["line"],
            ))
            continue

        refs = count_references(d["name"], rtl_files, d["file"], d["line"])
        if refs == 0:
            dead_count += 1
            # Demote to WARNING; final verdict is decided after we see
            # whether ANY sibling was consumed.
            result.findings.append(Finding(
                rule="UNREFERENCED_TURNAROUND_CONSTANT",
                severity="WARNING",
                message=(
                    f"Turnaround constant '{d['name']}' declared but referenced 0 times in RTL. "
                    f"Tolerated as long as a sibling turnaround constant IS consumed; otherwise FAIL. "
                    f"Add `// turnaround-spec-N/A` on the declaration line if intentionally unused."
                ),
                file=d["file"],
                line=d["line"],
            ))
        else:
            referenced_count += 1
            result.findings.append(Finding(
                rule="TURNAROUND_REFERENCED",
                severity="INFO",
                message=f"Turnaround constant '{d['name']}' referenced {refs} time(s) in RTL",
                file=d["file"],
                line=d["line"],
            ))

    # Wave 35: ZERO references across ALL declared turnaround
    # constants → genuine FAIL (FSM never wires the half-duplex
    # turnaround). At least one reference → PASS.
    if decls and referenced_count == 0:
        result.passed = False
        # Re-emit the unreferenced findings as ERRORs for clarity.
        for d in decls:
            if d["mitigated"]:
                continue
            result.findings.append(Finding(
                rule="DEAD_TURNAROUND_CONSTANT",
                severity="ERROR",
                message=(
                    f"NO turnaround constant in this project is "
                    f"referenced by RTL. Half-duplex protocol requires "
                    f"the dispatcher FSM to consume at least one. "
                    f"'{d['name']}' is declared but unused."
                ),
                file=d["file"],
                line=d["line"],
            ))

    magnitude_result = check_magnitude(base, decls)
    if magnitude_result:
        for f in magnitude_result:
            result.findings.append(f)
            if f.severity == "ERROR":
                result.passed = False

    result.summary = {
        "rtl_files": len(rtl_files),
        "turnaround_constants": len(decls),
        "dead": dead_count,
        "referenced": referenced_count,
        "mitigated": sum(1 for d in decls if d["mitigated"]),
        "magnitude_checked": magnitude_result is not None,
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)

    if args.json:
        out = asdict(result)
        print(json.dumps(out, indent=2))
    else:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] bus_turnaround_consumes_spec_constant_check")
        print(f"  RTL files scanned: {result.summary.get('rtl_files', 0)}")
        print(f"  Turnaround constants found: {result.summary.get('turnaround_constants', 0)}")
        print(f"  Dead (unreferenced): {result.summary.get('dead', 0)}")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                loc = f"{f.file}:{f.line}" if f.file else ""
                print(f"  [{f.severity}] {f.rule}: {f.message} {loc}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
