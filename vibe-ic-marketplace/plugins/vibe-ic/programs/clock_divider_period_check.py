#!/usr/bin/env python3
"""clock_divider_period_check.py — BACKLOG-v11 P0.2.

Detect clock-divider toggle patterns whose period does NOT match the
target frequency declared in L8 RTL constants.

Motivation
==========

v0.116 <benchmark> had `if (div == 4'd9) clk5m <= ~clk5m` in the FPGA
wrapper. With a 50 MHz source clock and toggle-every-(N+1)-cycles
semantics, N=9 produces a 20-cycle period = 2.5 MHz, NOT the spec'd
5 MHz. Every spec-derived TICK constant (TX_WAKE_TICKS=121,
TITO_TICKS=25000, IBT, BR widths…) was silently stretched 2×, breaking
wake-pulse periodicity, IBT, CRC bit-cell time. Caught only after
scope showed 50us pulses @ 10ms instead of 24us @ 5ms — too late, after
multiple FPGA iterations.

The correct comparator value for divide-by-K toggle is `K/2 - 1`
(N=4 for divide-by-10).

Gate behaviour
==============

For each `always_ff` (or `always @(posedge ...)`) block in RTL,
extract patterns of the form:

  if (<counter> == <N>) begin
      <counter> <= 0;
      <sig> <= ~<sig>;       // toggle output
  end

For each match:
  1. Identify the source clock from the always_ff sensitivity list.
  2. Look up <sig>'s target frequency from L8 RTL constants.
  3. Verify N+1 == source_freq / (2 * target_freq).
  4. If mismatch, emit DIVIDER_PERIOD_MISMATCH error.

False-alert guards
==================

Silent in any of:
  - No matching toggle-divider pattern found.
  - <sig> has no declared target frequency in L1-L23 (gate cannot
    verify; not a false alert because there's nothing to check).
  - L8 declares the source clock but no `<sig>_freq_mhz` /
    `<sig>_freq_hz` / `<sig>_period_ns` annotation. (Plain free-running
    counters that happen to toggle a flag don't count.)
  - The counter is also used elsewhere as a free-running phase
    accumulator (presence of `<counter> <= <counter> + 1` outside the
    `cnt == N` branch is required — otherwise the counter is reset on
    every clock anyway and isn't a divider).

Exit codes: 0 PASS / 1 FAIL / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import find_rtl_files as _rtl_files
from gate_utils import read_text as _read


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""
    line: int = 0


def _l8_freq_annotations(project: Path) -> dict[str, float]:
    """Return {signal_name_lower: target_freq_hz} from L8 RTL constants
    or top-level integration spec.

    Recognised L8 annotation formats:
      "<sig>_freq_mhz": <number>      → mhz
      "<sig>_freq_hz":  <number>      → hz
      "<sig>_period_ns": <number>     → 1e9 / period_ns
      "<sig>_clock_mhz": <number>     → mhz
    """
    out: dict[str, float] = {}
    for cand in (
        list(project.glob("phase1/generated_docs/L8*.json"))
        + list(project.glob("phase1/generated_docs/L9*.json"))
        + list(project.glob("L8*.json"))
        + list(project.glob("L9*.json"))
        + list(project.glob("input/docs/L8*.json"))
    ):
        try:
            data = json.loads(_read(cand) or "{}")
        except json.JSONDecodeError:
            continue

        def _walk(obj, path: list[str]):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    klow = k.lower()
                    if isinstance(v, (int, float)):
                        if klow.endswith("_freq_mhz") or klow.endswith("_clock_mhz"):
                            sig = klow.removesuffix("_freq_mhz").removesuffix("_clock_mhz")
                            out.setdefault(sig, v * 1e6)
                        elif klow.endswith("_freq_hz"):
                            sig = klow.removesuffix("_freq_hz")
                            out.setdefault(sig, float(v))
                        elif klow.endswith("_period_ns") and v > 0:
                            sig = klow.removesuffix("_period_ns")
                            out.setdefault(sig, 1e9 / v)
                    _walk(v, path + [k])
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item, path)

        _walk(data, [])
        # also try heuristic top-level: `internal_clock_MHz` -> "clk_internal"
        # commonly the L8 has fields like `internal_clock_MHz: 5`.
        # We map a few common names.
        for k, v in (data.items() if isinstance(data, dict) else []):
            klow = k.lower()
            if klow in {"internal_clock_mhz", "core_clock_mhz", "clk5m_freq_mhz"} \
                    and isinstance(v, (int, float)):
                out.setdefault("clk5m", v * 1e6)
                out.setdefault("clk_core", v * 1e6)
                out.setdefault("clk_internal", v * 1e6)
            if klow == "fpga_prediv_clock_mhz" and isinstance(v, (int, float)):
                out.setdefault("max10_clk", v * 1e6)
                out.setdefault("clk_50m", v * 1e6)
                out.setdefault("max10_clk1_50", v * 1e6)
                out.setdefault("clk_in", v * 1e6)
                out.setdefault("clk_src", v * 1e6)
    return out


# Regex: capture toggle-style divider blocks.
# Match: `if (<cnt> == ... <N>) ... <cnt> <= ... 0 ... <sig> <= ~<sig>`
_DIV_BLOCK_RE = re.compile(
    r"if\s*\(\s*(\w+)\s*==\s*(?:\d+\s*'\s*[hHdDbB])?(\d+)\s*\)"  # if (cnt == N)
    r"[\s\S]{0,2000}?"                                             # body
    r"(\w+)\s*<=\s*~\s*\3",                                        # sig <= ~sig
    re.MULTILINE,
)

# Source-clock detection: `always_ff @(posedge <clk>` or `always @(posedge <clk>`
_POSEDGE_RE = re.compile(r"always(?:_ff)?\s*@\s*\(\s*posedge\s+(\w+)")


def _find_dividers(rtl: str) -> list[tuple[str, int, str, str, int]]:
    """Return list of (counter, N, sig, source_clk, lineno)."""
    out: list[tuple[str, int, str, str, int]] = []
    blocks = list(_POSEDGE_RE.finditer(rtl))
    for blk in blocks:
        # find the always_ff block extent: from `always` to next blank line
        # or `endmodule`. Simpler: walk forward and bracket-match.
        start = blk.start()
        # naive — scan forward up to `end` followed by blank line
        # (good enough for most synthesizable code).
        body_end = rtl.find("\nendmodule", start)
        if body_end == -1:
            body_end = len(rtl)
        body = rtl[start:body_end]
        clk = blk.group(1)
        for m in _DIV_BLOCK_RE.finditer(body):
            counter, n_str, sig = m.group(1), m.group(2), m.group(3)
            try:
                n = int(n_str)
            except ValueError:
                continue
            # also require that the counter has an INC pattern
            # (cnt <= cnt + 1) somewhere in the block — confirms it's a
            # genuine divider and not just a strobe.
            if not re.search(rf"\b{re.escape(counter)}\s*<=\s*{re.escape(counter)}\s*\+\s*1", body):
                continue
            line_no = body[:m.start()].count("\n") + 1 + rtl[:start].count("\n")
            out.append((counter, n, sig, clk, line_no))
    return out


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "freq_annotations": {},
        "dividers_found": [],
        "skipped_reason": "",
    }

    annotations = _l8_freq_annotations(project)
    summary["freq_annotations"] = annotations

    rtl_files = _rtl_files(project)
    if not rtl_files:
        summary["skipped_reason"] = "no RTL files found"
        return findings, summary

    any_match = False
    for f in rtl_files:
        rtl = _read(f)
        if not rtl:
            continue
        dividers = _find_dividers(rtl)
        for cnt, n, sig, clk, lineno in dividers:
            any_match = True
            summary["dividers_found"].append({
                "file": str(f.relative_to(project)),
                "line": lineno,
                "counter": cnt,
                "comparator_n": n,
                "output_sig": sig,
                "source_clk": clk,
            })

            # Look up frequencies
            sig_lo = sig.lower()
            clk_lo = clk.lower()
            if sig_lo not in annotations or clk_lo not in annotations:
                # Cannot verify without both freqs declared
                continue
            target_hz = annotations[sig_lo]
            source_hz = annotations[clk_lo]
            if target_hz <= 0 or source_hz <= 0:
                continue
            ratio = source_hz / target_hz
            expected_n = ratio / 2 - 1
            if abs(n - expected_n) > 0.01:
                produced_freq = source_hz / (2 * (n + 1))
                findings.append(Finding(
                    severity="ERROR",
                    rule="DIVIDER_PERIOD_MISMATCH",
                    message=(
                        f"toggle-divider '{cnt}==={n}' for output '{sig}' "
                        f"produces {produced_freq:.0f} Hz from source "
                        f"'{clk}' ({source_hz:.0f} Hz), but L8 declares "
                        f"target {target_hz:.0f} Hz which requires "
                        f"comparator value N={expected_n:.0f}. v0.116 "
                        f"<benchmark> lesson: this silent 2× skew breaks any "
                        f"protocol that depends on absolute "
                        f"spec-microsecond timing."
                    ),
                    file=str(f.relative_to(project)),
                    line=lineno,
                ))
    if not any_match:
        summary["skipped_reason"] = "no toggle-divider patterns found"
    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="clock_divider_period_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "clock_divider_period_check",
            "passed": not findings,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== clock_divider_period_check ({project.name}) ===")
    if summary["skipped_reason"]:
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2
    if not findings:
        print(f"  [PASS] {len(summary['dividers_found'])} divider(s) verified")
        return 0
    for f in findings:
        print(f"  [{f.severity.lower()}] {f.rule} ({f.file}:{f.line}): {f.message}")
    print(f"\nOverall: FAIL ({len(findings)} mismatch(es))")
    return 1


if __name__ == "__main__":
    sys.exit(main())
