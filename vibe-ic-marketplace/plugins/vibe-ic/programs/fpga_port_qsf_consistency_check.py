#!/usr/bin/env python3
"""fpga_port_qsf_consistency_check.py — LL-10.

For FPGA-targeted projects, the top-level RTL module's port names MUST
match the constraint file's pin assignments byte-exact. Otherwise:

  - Quartus / Vivado compile silently with the unmatched ports going to
    auto-assigned (random) physical pins.
  - The constrained pin (e.g. PIN_V10 for ID_BUS) ends up tied to
    nothing — no signal reaches the test rig.
  - Symptoms: SOF burns OK, FPGA configures OK, scope sees zero activity
    on the expected pin, host tester reports "chip absent".

This gate would have caught the v0119_fresh_v2 attempt where fresh agent
named the top module ports `MAX10_CLK1_50`, `KEY[1:0]`, `LEDR[9:0]`,
`ARDUINO_IO_8` while the QSF (project standard) declared
`MAX10_clk_50MHz`, `KEY_rstn`, `LED[7:0]`, `GPIO_id_bus`. All four ports
were unconstrained → clock pin not connected → chip silent on bus.

Detection
=========

  1. Find FPGA top module: pattern `*_fpga_top.sv`, `fpga_top.sv`,
     `top.sv` containing `inout`/`output` ports (FPGA-style ports are a
     reliable marker — pure ASIC top usually has only inputs/outputs no
     inout).
  2. Find constraint file: `*.qsf` or `*.xdc`.
  3. Parse QSF: `set_location_assignment PIN_<X> -to <signal>` plus
     `set_instance_assignment ... -to <signal>`. Bus indexing
     (`signal[0]`, `signal[7]`) is normalized to base name.
  4. Parse RTL top header: extract every input/output/inout port name.
  5. For every constrained signal in QSF: verify it appears (as
     base-name match) in the RTL top port list.
  6. Conversely, for every RTL top inout/output: verify it has at least
     one QSF constraint (warn-only — agent might use auto-assigned for
     internal-debug-only pins).

False-alert escape hatches
==========================

  - Silent if no QSF/XDC found (ASIC project).
  - Silent if no `*_fpga_top.sv` / `fpga_top.sv` / `top.sv` file
    matches.
  - waivers.json id `fpga_port_qsf_unconstrained` skips when present.

Severity: ERROR with --strict; WARNING by default.

Exit codes: 0 PASS / 1 FAIL (strict) / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import find_modules, find_rtl_files, read_text


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


# ============================================================================
# QSF / XDC parsing
# ============================================================================

_QSF_LOC_RE = re.compile(
    r"set_location_assignment\s+\S+\s+-to\s+(\S+)",
)
_QSF_INSTANCE_RE = re.compile(
    r"set_instance_assignment\s+.*?-to\s+(\S+)",
)
_XDC_PORT_RE = re.compile(
    r"set_property\s+\S+\s+\S+\s+\[get_ports\s+(?:\{)?(\S+?)(?:\})?\s*\]",
)


def _normalize_signal(name: str) -> str:
    """Drop bit-index suffix `[N]` and `*` wildcards. Return base name."""
    m = re.match(r"(\w+)(?:\[\d+\])?", name.strip())
    return m.group(1) if m else name.strip()


def find_constraint_files(project: Path) -> list[Path]:
    out: list[Path] = []
    for ext in ("*.qsf", "*.xdc"):
        for f in project.rglob(ext):
            if f.is_file():
                out.append(f)
    return out


def parse_constraint_signals(cfile: Path) -> set[str]:
    """Return set of constrained signal base-names from one QSF/XDC."""
    text = read_text(cfile)
    names: set[str] = set()
    if cfile.suffix.lower() == ".qsf":
        for m in _QSF_LOC_RE.finditer(text):
            names.add(_normalize_signal(m.group(1)))
        for m in _QSF_INSTANCE_RE.finditer(text):
            base = _normalize_signal(m.group(1))
            # Skip wildcard targets like LED* (they match a base)
            if "*" in base:
                continue
            names.add(base)
    else:  # XDC
        for m in _XDC_PORT_RE.finditer(text):
            names.add(_normalize_signal(m.group(1)))
    return names


# ============================================================================
# RTL FPGA-top discovery & port extraction
# ============================================================================

_PORT_DECL_RE = re.compile(
    r"\b(?:input|output|inout)\b\s+(?:wire|logic|reg)?\s*"
    r"(?:\[[^\]]+\])?\s*([A-Za-z_]\w*)",
)


def find_fpga_top(rtl_files: list[Path]) -> tuple[Path, str, list[str]] | None:
    """Look for a top module that has at least one `inout` port (FPGA-style
    bidirectional pad). Return (file, module_name, port_names) or None."""
    candidates: list[tuple[Path, str, list[str]]] = []
    for f in rtl_files:
        text = read_text(f)
        for mod in find_modules(text):
            header = mod.header
            ports: list[str] = []
            for m in _PORT_DECL_RE.finditer(header):
                ports.append(m.group(1))
            has_inout = bool(re.search(r"\binout\b", header))
            name_lower = mod.name.lower()
            is_top_named = any(tag in name_lower for tag in (
                "fpga_top", "top",
            ))
            if has_inout and is_top_named:
                candidates.append((f, mod.name, ports))
    if not candidates:
        # v0.119.5 hardening: fallback used to match ANY module with
        # `inout` in header, which could pick up an analog-pad submodule
        # in an ASIC project. Now require the module name OR file name
        # to contain `top` (case-insensitive), keeping the fallback
        # useful for projects whose top isn't tagged `fpga_top` while
        # rejecting random `inout`-bearing leaf modules. ASIC projects
        # are still pre-filtered by the `qsf/xdc presence` check at the
        # caller site, but this gives belt-and-braces.
        for f in rtl_files:
            text = read_text(f)
            file_has_top = "top" in f.name.lower()
            for mod in find_modules(text):
                if "inout" not in mod.header:
                    continue
                if not (file_has_top or "top" in mod.name.lower()):
                    continue
                ports = [m.group(1) for m in
                         _PORT_DECL_RE.finditer(mod.header)]
                return (f, mod.name, ports)
        return None
    # Prefer files whose name matches *fpga_top*
    for cand in candidates:
        if "fpga_top" in cand[0].name.lower():
            return cand
    return candidates[0]


# ============================================================================
# Waiver
# ============================================================================

def _waiver_rationale(project: Path, waiver_id: str) -> str:
    for cand in (project / "waivers.json",
                 *project.glob("**/waivers.json")):
        if not cand.exists():
            continue
        try:
            data = json.loads(read_text(cand) or "{}")
        except json.JSONDecodeError:
            continue
        entries = data if isinstance(data, list) else (
            data.get("waivers") or data.get("waived_steps") or []
        )
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            if e.get("id") == waiver_id:
                rat = e.get("rationale") or e.get("reason") or ""
                if isinstance(rat, str) and rat.strip():
                    return rat.strip()
    return ""


# ============================================================================
# Inspect
# ============================================================================

def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "constraint_files": [],
        "fpga_top_module": None,
        "fpga_top_file": None,
        "rtl_ports": [],
        "qsf_signals": [],
        "qsf_unmatched_in_rtl": [],
        "rtl_unmatched_in_qsf": [],
        "skipped_reason": "",
    }
    cfiles = find_constraint_files(project)
    if not cfiles:
        summary["skipped_reason"] = "no QSF/XDC constraint file found"
        return findings, summary
    summary["constraint_files"] = [
        str(f.relative_to(project)) for f in cfiles
    ]

    waiver = _waiver_rationale(project, "fpga_port_qsf_unconstrained")
    if waiver:
        summary["skipped_reason"] = (
            f"waiver fpga_port_qsf_unconstrained: {waiver[:80]}"
        )
        return findings, summary

    rtl_files = find_rtl_files(project)
    if not rtl_files:
        summary["skipped_reason"] = "no RTL files found"
        return findings, summary
    top = find_fpga_top(rtl_files)
    if top is None:
        summary["skipped_reason"] = "no FPGA top module found"
        return findings, summary
    f, mname, ports = top
    summary["fpga_top_module"] = mname
    summary["fpga_top_file"] = str(f.relative_to(project))
    summary["rtl_ports"] = ports
    rtl_port_set = {_normalize_signal(p) for p in ports}

    # Aggregate constrained signals across all constraint files
    all_qsf: set[str] = set()
    for cf in cfiles:
        all_qsf.update(parse_constraint_signals(cf))
    summary["qsf_signals"] = sorted(all_qsf)

    qsf_unmatched = sorted(all_qsf - rtl_port_set)
    rtl_unmatched = sorted(rtl_port_set - all_qsf)
    summary["qsf_unmatched_in_rtl"] = qsf_unmatched
    summary["rtl_unmatched_in_qsf"] = rtl_unmatched

    if qsf_unmatched:
        findings.append(Finding(
            severity="ERROR",
            rule="QSF_SIGNAL_NOT_IN_RTL_TOP",
            message=(
                f"Constraint file declares {qsf_unmatched} but FPGA top "
                f"module `{mname}` ({f.relative_to(project)}) has no "
                f"matching port. The pin will go unconstrained — "
                f"compile succeeds but the physical pin is never "
                f"connected to your design. Match the RTL port name to "
                f"the QSF/XDC signal name byte-exact."
            ),
            file=str(f.relative_to(project)),
        ))
    # rtl_unmatched is informational unless STRICT — many projects have
    # internal debug ports auto-assigned by Quartus.
    if rtl_unmatched:
        findings.append(Finding(
            severity="WARNING",
            rule="RTL_PORT_NOT_CONSTRAINED",
            message=(
                f"FPGA top ports {rtl_unmatched} have no QSF/XDC "
                f"location assignment. Quartus will auto-assign random "
                f"pins. If these are debug/observability outputs that's "
                f"fine; if they're functional bus signals (clock, "
                f"reset, data), the design will not work on hardware."
            ),
            file=str(f.relative_to(project)),
        ))
    return findings, summary


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(prog="fpga_port_qsf_consistency_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    has_error = any(f.severity == "ERROR" for f in findings)
    passed = (not has_error) or (not args.strict)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "fpga_port_qsf_consistency_check",
            "passed": passed,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== fpga_port_qsf_consistency_check ({project.name}) ===")
    if summary.get("skipped_reason"):
        print(f"skipped: {summary['skipped_reason']}")
        return 0
    print(f"FPGA top: {summary['fpga_top_module']} @ "
          f"{summary['fpga_top_file']}")
    print(f"  RTL ports ({len(summary['rtl_ports'])}): "
          f"{summary['rtl_ports']}")
    print(f"  QSF signals ({len(summary['qsf_signals'])}): "
          f"{summary['qsf_signals']}")
    if summary["qsf_unmatched_in_rtl"]:
        print(f"  QSF→RTL UNMATCHED: {summary['qsf_unmatched_in_rtl']}")
    if summary["rtl_unmatched_in_qsf"]:
        print(f"  RTL→QSF UNMATCHED: {summary['rtl_unmatched_in_qsf']}")
    for f in findings:
        print(f"[{f.severity}] {f.rule}: {f.message}")
    if not findings:
        print("PASS — RTL top ports match QSF constraints byte-exact")
        return 0
    return 1 if args.strict and not passed else 0


if __name__ == "__main__":
    sys.exit(main())
