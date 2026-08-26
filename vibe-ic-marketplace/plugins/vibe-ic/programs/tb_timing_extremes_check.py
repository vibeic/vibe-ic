#!/usr/bin/env python3
"""tb_timing_extremes_check.py — LL-6.

For half-duplex protocol ICs whose L2 spec gives ranges (e.g. ibt_us
range [min, max]), verify the project's testbench(es) actually drive
both extremes. If the TB only tests at the favorable end of the range,
sim PASSes but real HW (which may operate at any point in the range)
exposes timing-window bugs that sim missed.

Concrete failure mode this would have caught:
  - v0118-vendor <benchmark>: TB drove `host_idle(22600)` (= L2.ibt_us[1]
    only). Bugs that only manifest at L2.ibt_us[0] (lower end) were
    invisible.

The gate scans TB SystemVerilog/Verilog files for `host_idle(N)` /
`#NUS` / `host_low(N)` style calls and verifies each L2 ranged class
(ranged `timing_windows[]` from L8_TIMING_WAVEFORM.json, and
legacy ibt_us / pulse_classes from L2_TIMING_WAVEFORM.json)
has at least one TB call near both [min, max] (within 10% tolerance).

Severity: WARNING. Use `--strict` to upgrade.

False-alert escape hatches
==========================

  - Skip ranges with span ratio (max/min) > 100. BOR / WAKE classes
    typically have huge ranges; testing 999999us would take forever in
    sim and isn't representative of HW failure modes.
  - Skip if no TB files found.
  - Skip if no L2 timing ranges declared.
  - waivers.json entry `tb_timing_extremes_override` skips entirely.

Exit codes: 0 PASS / 1 FAIL (strict) / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from gate_utils import read_text
import _path_layout as _pl


# Skip ranges with span > this factor (impractical-extreme classes).
MAX_SPAN_RATIO = 100.0


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


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


# Match `host_idle(22600)` or `host_low(13800)` or bare `#22600`
_DELAY_CALL_RE = re.compile(
    r"\b(?:host_idle|host_low|#)\s*\(?\s*(\d+)\s*\)?",
)


def _find_tb_files(project: Path) -> list[Path]:
    out: list[Path] = []
    for d in ("phase2/stage1/sim_full_stack", "phase2/stage1/sim", "phase2/stage1/tb", "sim_full_stack", "sim", "tests", "tb"):
        sub = project / d
        if sub.is_dir():
            for ext in ("*.sv", "*.v"):
                out.extend(sub.rglob(ext))
    # Also scan top-level for tb_*.sv
    for f in project.glob("tb_*.sv"):
        out.append(f)
    for f in project.glob("tb_*.v"):
        out.append(f)
    return out


def _extract_delay_ns(tb_files: list[Path]) -> list[int]:
    """Extract all delay literals (in ns assuming `timescale 1ns/1ns)."""
    delays: list[int] = []
    for f in tb_files:
        text = read_text(f)
        for m in _DELAY_CALL_RE.finditer(text):
            try:
                delays.append(int(m.group(1)))
            except ValueError:
                continue
    return delays


# Multipliers onto microseconds for the unit suffixes the timing-waveform
# layer actually emits (`max_ns`, `max_us`, `max_ms`, ...).
_UNIT_TO_US: dict[str, float] = {
    "s": 1_000_000.0,
    "ms": 1_000.0,
    "us": 1.0,
    "ns": 0.001,
    "ps": 0.000_001,
}


def _bound_us(entry: dict, prefix: str) -> Optional[float]:
    """First `<prefix>_<unit>` bound present in `entry`, converted to us.

    Units are tried coarsest-first. Accepts every suffix in `_UNIT_TO_US`, so
    a window that states its minimum in ns and its maximum in us still pairs
    up into one range.
    """
    for unit, mult in _UNIT_TO_US.items():
        val = entry.get(f"{prefix}_{unit}")
        if isinstance(val, bool):
            continue
        if isinstance(val, (int, float)):
            return float(val) * mult
    return None


def _l2_ranges(project: Path) -> dict[str, tuple[float, float]]:
    """Return dict of timing-class -> (min_us, max_us).

    TWO SOURCES, AND ONLY ONE OF THEM IS EVER WRITTEN
    =================================================
    This function used to read `L2_TIMING_WAVEFORM.json` and nothing else.
    NO PROGRAM IN THIS PLUGIN HAS EVER WRITTEN THAT FILE. The timing-waveform
    layer is emitted as `L8_TIMING_WAVEFORM.json` — by every `*_protocol_synth`
    emitter and by `phase1_doc_one_shot_runner`. Measured over the published
    benchmark corpus: `L2_TIMING_WAVEFORM.json` occurs 0 times, and
    `L8_TIMING_WAVEFORM.json` occurs 175 times.

    So `_l2_ranges` returned `{}` on EVERY real run, `inspect` short-circuited
    at "no L2 timing ranges to verify", and the gate returned PASS
    unconditionally — including under `--strict`. A consumer reading a path no
    producer fills does not report a missing input; it reports nothing at all,
    which is indistinguishable from a clean bill of health. The gate has never
    once been able to say no. The only reason its own suite stayed green is
    that every fixture in it writes `L2_TIMING_WAVEFORM.json` by hand.

    The legacy path is KEPT rather than swapped: this is a union of sources, so
    nothing that used to be measurable stops being measurable. What is added is
    the live layer, in the schema the live layer actually uses — `timing_windows[]`
    entries carrying BOTH a `min_<unit>` and a `max_<unit>`. A window with only
    one bound is not a range and is not reported as one.
    """
    out: dict[str, tuple[float, float]] = {}
    for cand in (
        _pl.generated_docs_dir(project) / "L2_TIMING_WAVEFORM.json",
        project / "input" / "docs" / "L2_TIMING_WAVEFORM.json",
    ):
        if cand.exists():
            try:
                data = json.loads(cand.read_text())
            except Exception:
                continue
            ibt = data.get("ibt_us")
            if isinstance(ibt, list) and len(ibt) >= 2:
                out["ibt_us"] = (float(ibt[0]), float(ibt[1]))
            for pc in data.get("pulse_classes", []) or []:
                if not isinstance(pc, dict):
                    continue
                name = pc.get("class_name")
                lo = pc.get("min_us")
                hi = pc.get("max_us")
                if name and isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                    out[name] = (float(lo), float(hi))

    # The layer the flow actually emits.
    for cand in (
        _pl.generated_docs_dir(project) / "L8_TIMING_WAVEFORM.json",
        project / "input" / "docs" / "L8_TIMING_WAVEFORM.json",
    ):
        if not cand.exists():
            continue
        try:
            data = json.loads(cand.read_text())
        except Exception:
            continue
        for idx, win in enumerate(data.get("timing_windows", []) or []):
            if not isinstance(win, dict):
                continue
            lo = _bound_us(win, "min")
            hi = _bound_us(win, "max")
            if lo is None or hi is None or hi <= lo:
                continue
            name = win.get("name")
            key = str(name) if isinstance(name, str) and name.strip() \
                else f"timing_windows[{idx}]"
            # A class already named by the legacy layer wins: an explicit
            # pulse_class is the more specific statement of the same range.
            out.setdefault(key, (lo, hi))
    return out


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "tb_files": [],
        "l2_ranges": {},
        "delays_us_in_tb": [],
        "extremes_covered": {},
        "skipped_reason": "",
    }

    waiver = _waiver_rationale(project, "tb_timing_extremes_override")
    if waiver:
        summary["skipped_reason"] = (
            f"waiver tb_timing_extremes_override: {waiver[:80]}"
        )
        return findings, summary

    tb_files = _find_tb_files(project)
    summary["tb_files"] = [str(f.relative_to(project)) for f in tb_files]
    if not tb_files:
        summary["skipped_reason"] = "no testbench files found"
        return findings, summary

    ranges_all = _l2_ranges(project)
    # Skip impractical-extreme ranges (span ratio > MAX_SPAN_RATIO)
    ranges = {}
    skipped_classes: list[str] = []
    for cname, (lo, hi) in ranges_all.items():
        if lo > 0 and (hi / lo) > MAX_SPAN_RATIO:
            skipped_classes.append(f"{cname} (ratio={hi/lo:.1f})")
            continue
        ranges[cname] = (lo, hi)
    summary["l2_ranges"] = {k: list(v) for k, v in ranges.items()}
    summary["skipped_classes"] = skipped_classes
    if not ranges:
        summary["skipped_reason"] = "no L2 timing ranges to verify"
        return findings, summary

    delays_ns = _extract_delay_ns(tb_files)
    delays_us = [d / 1000.0 for d in delays_ns]
    summary["delays_us_in_tb"] = delays_us

    # Tolerance: min(10% relative, half-the-range absolute). For tight
    # ranges like ibt_us=[20,22] this avoids classifying a single value
    # as covering both extremes.
    def _near(value, target, span):
        rel_tol = abs(target) * 0.10
        abs_tol = max(0.5, span * 0.49)  # never wider than half-range
        return abs(value - target) <= min(rel_tol, abs_tol)

    uncovered: list[str] = []
    for cname, (lo_us, hi_us) in ranges.items():
        span = hi_us - lo_us
        near_min = any(_near(d, lo_us, span) for d in delays_us)
        near_max = any(_near(d, hi_us, span) for d in delays_us)
        summary["extremes_covered"][cname] = {
            "near_min": near_min, "near_max": near_max,
            "min_us": lo_us, "max_us": hi_us,
        }
        if not (near_min and near_max):
            missing = []
            if not near_min:
                missing.append(f"min={lo_us}us")
            if not near_max:
                missing.append(f"max={hi_us}us")
            uncovered.append(f"{cname} (missing {', '.join(missing)})")

    if uncovered:
        findings.append(Finding(
            severity="WARNING",
            rule="TB_TIMING_EXTREMES_NOT_COVERED",
            message=(
                "Testbench does not drive both extremes of L2 timing "
                f"range(s): {'; '.join(uncovered)}. Real HW may operate "
                "at any point in the spec range; bugs at the unexercised "
                "extreme will pass sim and fail HW (e.g. v0118-vendor "
                "<benchmark>: TB drove only ibt=22us, sim PASS, HW FAIL "
                "because chip latency budget was tight at min-IBT). "
                "Add test cases at each spec extreme."
            ),
        ))
    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="tb_timing_extremes_check")
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
            "program": "tb_timing_extremes_check",
            "passed": passed,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== tb_timing_extremes_check ({project.name}) ===")
    if summary.get("skipped_reason"):
        print(f"skipped: {summary['skipped_reason']}")
        return 0
    print(f"TB files: {summary['tb_files']}")
    print("L2 ranges → coverage:")
    for cname, info in summary["extremes_covered"].items():
        print(f"  {cname} [{info['min_us']}, {info['max_us']}]us  "
              f"min={info['near_min']} max={info['near_max']}")
    for f in findings:
        print(f"[{f.severity}] {f.rule}: {f.message}")
    if not findings:
        print("PASS — TB exercises both extremes of every L2 range")
        return 0
    return 1 if args.strict and not passed else 0


if __name__ == "__main__":
    sys.exit(main())
