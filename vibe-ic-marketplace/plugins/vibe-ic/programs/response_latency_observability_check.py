#!/usr/bin/env python3
"""response_latency_observability_check.py — LL-5.

Half-duplex command-response ICs are notoriously hard to debug on real
hardware when sim PASSes but HW FAILs. The most useful single observable
is the chip's own response latency (cycles from rx_br/byte_done to first
TX bit), routed to FPGA pins (LEDs / GPIO) so the developer can read it
without recompiling for signaltap.

This gate verifies the top-level (or FPGA-wrapper) RTL exposes such an
observable. Pattern: an `output` port whose name matches:

    dbg_(.*)latency(.*)         (any latency observable)
    dbg_(.*)resp(.*)cyc(.*)     (response cycle counter)
    dbg_(.*)turnaround(.*)      (turnaround time observable)

Severity: WARNING (informational; some projects rely on signaltap
instead). Use `--strict` to upgrade.

False-alert escape hatches
==========================

  - Silent for non-half-duplex projects (no L2 ibt+tSRS).
  - Silent if project has signaltap configuration (`*.stp` /
    `signaltap.stp`) — engineer is using JTAG-based observability.
  - Silent for ASIC-only projects (no `.qsf` / `.xdc` constraints
    file — no FPGA debug context).
  - Silent if waivers.json has entry id
    `response_latency_alternative_observable`.
  - Severity is WARNING — informational, never blocks even with
    --strict on by default.

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
import _path_layout as _pl


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


_PORT_NAME_RE = re.compile(
    r"\boutput\b(?:\s+\w+)?(?:\s+\[[^\]]+\])?\s+(\w+)",
    re.IGNORECASE,
)

# v0.119.1 hardening: bidirectional match. Real-world projects name
# observables in many orders — `dbg_response_latency`, `latency_dbg_o`,
# `monitor_resp_cyc`, `response_cycles_obs_o`. The previous regex only
# accepted the dbg-prefix order and silently missed valid observables,
# producing false WARNINGs. We now require BOTH a latency token AND an
# observability token, in either order. Together-but-required keeps
# false-positive rate near zero (a generic `data_out` has neither, a
# generic `dbg_clk` has dbg but no latency token).
_LATENCY_TOKEN_RE = re.compile(
    r"(?:latency|resp_cyc|response_cyc|response_cycles|"
    r"turnaround|response_lat|lat_cnt|lat_cycles|rsp_cyc)",
    re.IGNORECASE,
)
_OBSERV_TOKEN_RE = re.compile(
    # Substring matching is intentional — Verilog port names use `_`
    # which is a word character, so `\b` boundaries don't fire on
    # `dbg_*`/`*_dbg`/etc. False positives are filtered by the AND
    # requirement with _LATENCY_TOKEN_RE: a port like `enabled_out` has
    # `led` substring but no latency token, so it's correctly skipped.
    r"(?:dbg|debug|obs|observ|monitor|probe|"
    r"_o(?:ut)?$|_pin$|led|gpio)",
    re.IGNORECASE,
)


def _is_latency_observable(port_name: str) -> bool:
    """True iff port name has both a latency token and an observability
    marker, regardless of order. Examples that PASS: dbg_response_latency,
    latency_dbg_out, monitor_resp_cyc, response_cycles_obs_o. Examples
    that FAIL (correctly): data_out (no latency), dbg_clk (no latency),
    response_data (no observability indicator)."""
    return bool(_LATENCY_TOKEN_RE.search(port_name)
                and _OBSERV_TOKEN_RE.search(port_name))


def _is_half_duplex(project: Path) -> bool:
    for cand in (
        _pl.generated_docs_dir(project) / "L2_TIMING_WAVEFORM.json",
        project / "input" / "docs" / "L2_TIMING_WAVEFORM.json",
    ):
        if cand.exists():
            try:
                data = json.loads(cand.read_text())
                return ("ibt_us" in data and any(
                    k.lower().startswith("tsrs") for k in data.keys()))
            except Exception:
                pass
    return False


def _has_signaltap(project: Path) -> bool:
    return any(project.rglob("*.stp"))


def _has_fpga_constraints(project: Path) -> bool:
    return (any(project.rglob("*.qsf")) or any(project.rglob("*.xdc")))


def _waiver_rationale(project: Path, waiver_id: str) -> str:
    for cand in (project / "waivers.json", *project.glob("**/waivers.json")):
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


def _find_top_modules(rtl_files: list[Path]) -> list[tuple[Path, str, str]]:
    """Return (file, module_name, header) for likely-top modules."""
    candidates: list[tuple[Path, str, str]] = []
    for f in rtl_files:
        text = read_text(f)
        for mod in find_modules(text):
            name_lower = mod.name.lower()
            if any(tag in name_lower for tag in (
                "fpga_top", "top", "dut_top", "chip"
            )):
                candidates.append((f, mod.name, mod.header))
    return candidates


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "is_half_duplex": False,
        "top_modules": [],
        "observables_found": [],
        "skipped_reason": "",
    }

    if not _is_half_duplex(project):
        summary["skipped_reason"] = "non-half-duplex project"
        return findings, summary
    summary["is_half_duplex"] = True

    if not _has_fpga_constraints(project):
        summary["skipped_reason"] = "no FPGA constraints (.qsf/.xdc) — ASIC project"
        return findings, summary

    if _has_signaltap(project):
        summary["skipped_reason"] = "signaltap config present (alternative observability)"
        return findings, summary

    waiver = _waiver_rationale(
        project, "response_latency_alternative_observable")
    if waiver:
        summary["skipped_reason"] = (
            f"waiver response_latency_alternative_observable: {waiver[:80]}"
        )
        return findings, summary

    rtl_files = find_rtl_files(project)
    if not rtl_files:
        summary["skipped_reason"] = "no RTL files found"
        return findings, summary

    tops = _find_top_modules(rtl_files)
    if not tops:
        summary["skipped_reason"] = "no top-level modules found"
        return findings, summary

    summary["top_modules"] = [m for _, m, _ in tops]
    found_any = False
    for f, mname, header in tops:
        # Walk every output port name; check each for latency-observable
        for pm in _PORT_NAME_RE.finditer(header):
            port_name = pm.group(1)
            if _is_latency_observable(port_name):
                summary["observables_found"].append(
                    f"{mname}:{port_name}@{f.relative_to(project)}"
                )
                found_any = True

    if not found_any:
        findings.append(Finding(
            severity="WARNING",
            rule="MISSING_RESPONSE_LATENCY_OBSERVABLE",
            message=(
                f"Half-duplex protocol IC top module(s) "
                f"{[m for _, m, _ in tops]} have no port matching "
                f"`dbg_*_latency`, `dbg_*_resp_cyc`, or "
                f"`dbg_*_turnaround`. Without such an observable, when "
                f"sim PASSes but HW FAILs (latency-window bugs like "
                f"v0118-vendor <benchmark>), the developer is forced to do "
                f"recompile-iterate-burn loops or set up signaltap, "
                f"both expensive. Recommend: add `output logic [15:0] "
                f"dbg_response_latency_cycles` measuring cycles from "
                f"rx-frame-end-detect to first-TX-bit, routed to LEDs "
                f"or GPIO pins for camera_capture observation."
            ),
        ))
    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="response_latency_observability_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    passed = (
        not any(f.severity in ("ERROR", "WARNING") for f in findings)
        or not args.strict
    )

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "response_latency_observability_check",
            "passed": passed,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== response_latency_observability_check ({project.name}) ===")
    if summary.get("skipped_reason"):
        print(f"skipped: {summary['skipped_reason']}")
        return 0
    print(f"top modules: {summary['top_modules']}")
    print(f"observables found: {summary['observables_found']}")
    for f in findings:
        print(f"[{f.severity}] {f.rule}: {f.message}")
    if not findings:
        print("PASS — half-duplex top exposes response-latency observable")
        return 0
    return 1 if args.strict and not passed else 0


if __name__ == "__main__":
    sys.exit(main())
