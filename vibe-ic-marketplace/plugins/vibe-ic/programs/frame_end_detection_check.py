#!/usr/bin/env python3
"""frame_end_detection_check.py — BACKLOG-v11 P0.4.

Detect rx_phy modules that re-use the frame-START pulse class as the
frame-END marker without an explicit L3 declaration. Recommend
gap-timeout based frame-end detection instead.

Motivation
==========

v0.116 <benchmark> rx_phy classified low pulses by width:
  - BIT0_LOW / BIT1_LOW → bits
  - BR_LOW (long pulse) → either start-of-frame OR end-of-frame
    depending on a `br_seen` flag that toggled across consecutive
    BR pulses.

The host-side protocol (cable-side ID, I²C, SPI, MDIO and most
byte-level protocols) marks end-of-frame by **bus going idle for ≥
inter-byte gap**, NOT by a second BR pulse. Result: the chip's
cmd_decoder.cmd_pass never fired because rx_end_br never asserted —
host released bus, chip waited forever. byte[6]=0x02. Caught only
after exhaustive RTL trace.

Gate behaviour
==============

Scan RTL for any module whose name contains `rx_phy` / `rx_pad` /
`rx_decoder` / `rx_serial` / similar receiver patterns. In each
such module:

  1. Look for a `br_seen` style state flag (1-bit register that
     toggles on a long-low classification).
  2. If a low-pulse classification produces BOTH `rx_br <= 1'b1`
     AND `rx_end_br <= 1'b1` controlled by that flag, emit
     `FRAME_END_BY_DUPLICATE_START_PULSE`.

Recommended fix is documented in the warning message: replace the
toggle pattern with a `gap_cnt` counter that fires `rx_end_br` once
the bus has been idle for `FRAME_END_GAP` ticks.

False-alert guards
==================

  - Silent if the module has an explicit `gap_cnt` / `frame_end_gap`
    counter (gap-timeout pattern present — already correct).
  - Silent if L3 declares `frame_delimiters: [...]` with two distinct
    pulse classes (some protocols genuinely use two-pulse start/end
    markers — explicit override).
  - Silent if no `rx_*` module exists (non-protocol design).

Severity: WARNING (informational; might be intentional with override).
Use `--strict` to upgrade.

Exit codes: 0 PASS / 1 FAIL (strict) / 2 skip
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


def _l3_frame_delimiters(project: Path) -> bool:
    """Return True if L3 declares frame_delimiters with multiple classes."""
    for cand in (
        list(project.glob("phase1/generated_docs/L3*.json"))
        + list(project.glob("L3*.json"))
        + list(project.glob("input/docs/L3*.json"))
    ):
        try:
            data = json.loads(_read(cand) or "{}")
        except json.JSONDecodeError:
            continue
        delim = data.get("frame_delimiters") if isinstance(data, dict) else None
        if isinstance(delim, list) and len(delim) >= 2:
            return True
    return False


_RX_MODULE_RE = re.compile(
    r"\bmodule\s+(\w*rx[_\w]*)\b", re.IGNORECASE
)


def _module_body(rtl: str, name: str) -> str:
    """Return body of module(name) from `module name(...)` to `endmodule`."""
    start_m = re.search(rf"\bmodule\s+{re.escape(name)}\b", rtl)
    if not start_m:
        return ""
    end_m = re.search(r"\bendmodule\b", rtl[start_m.start():])
    if not end_m:
        return rtl[start_m.start():]
    return rtl[start_m.start():start_m.start() + end_m.end()]


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "rx_modules": [],
        "l3_explicit_two_class": False,
        "skipped_reason": "",
    }

    if _l3_frame_delimiters(project):
        summary["l3_explicit_two_class"] = True
        summary["skipped_reason"] = (
            "L3 declares frame_delimiters with two pulse classes "
            "(engineer override)"
        )
        return findings, summary

    rtl_files = _rtl_files(project)
    if not rtl_files:
        summary["skipped_reason"] = "no RTL files found"
        return findings, summary

    any_rx = False
    for f in rtl_files:
        rtl = _read(f)
        for m in _RX_MODULE_RE.finditer(rtl):
            mname = m.group(1)
            body = _module_body(rtl, mname)
            if not body:
                continue
            any_rx = True
            summary["rx_modules"].append(
                f"{mname}@{f.relative_to(project)}"
            )

            # Has gap-timeout pattern? (good)
            has_gap_cnt = bool(
                re.search(r"\bgap_cnt\b|\bframe_end_gap\b|"
                          r"\bidle_cnt\b|\bquiet_cnt\b|\bidle_timer\b|"
                          r"\bbus_idle_\w*\b", body)
            )
            # Has *_seen-style toggle anti-pattern? Accept any 1-bit flag
            # whose name ends with _seen / _toggle / _phase that is BOTH
            # tested in `if (!_seen)` / `if (_seen)` AND used to gate
            # two distinct output strobes — one a "start" class and one
            # an "end" class signal. Generalises the v0.116 `br_seen`
            # specific detection to other naming conventions.
            seen_match = re.search(
                r"\b(\w*(?:seen|phase|toggle|alt))\b\s*<=", body)
            has_seen_toggle = False
            if seen_match:
                seen_var = seen_match.group(1)
                gates_test = re.search(
                    rf"if\s*\(\s*!?\s*{re.escape(seen_var)}\s*\)", body)
                # accept any signal containing 'end' / 'eof' as the END
                # marker, and any signal NOT containing those tokens but
                # raised in the same toggle as a START marker.
                # Accept either `<= 1` (bare decimal) or `<= 1'b1` /
                # `<= 1'h1` literal forms — both are common idioms.
                _RAISE = r"<=\s*(?:1\s*'\s*[hHbBdD]?1|1)\s*[;,]"
                has_end_sig = re.search(
                    rf"\b(\w*(?:end|eof|stop|terminate)\w*)\s*{_RAISE}",
                    body, re.IGNORECASE)
                has_start_sig = re.search(
                    rf"\b(\w*(?:start|begin|sof|br|sob)\w*)\s*{_RAISE}",
                    body, re.IGNORECASE)
                has_seen_toggle = bool(
                    gates_test and has_end_sig and has_start_sig
                )
            has_br_seen_toggle = has_seen_toggle
            if has_gap_cnt:
                continue
            if has_br_seen_toggle:
                findings.append(Finding(
                    severity="WARNING",
                    rule="FRAME_END_BY_DUPLICATE_START_PULSE",
                    message=(
                        f"module `{mname}` re-uses the BR (frame-start) "
                        f"pulse class as frame-END marker via a "
                        f"`br_seen` toggle. Most byte-level protocols "
                        f"mark end-of-frame by bus idle ≥ inter-byte "
                        f"gap, NOT by a second BR pulse. Recommend "
                        f"replacing with a `gap_cnt` counter that "
                        f"fires `rx_end_br` after FRAME_END_GAP ticks "
                        f"of bus idle. Override: declare "
                        f"`frame_delimiters: [<start>, <end>]` in L3 "
                        f"with two distinct pulse classes if your "
                        f"protocol genuinely uses dual BR pulses."
                    ),
                    file=str(f.relative_to(project)),
                ))

    if not any_rx:
        summary["skipped_reason"] = "no rx_* modules found"
    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="frame_end_detection_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="Upgrade WARNING → ERROR")
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "frame_end_detection_check",
            "passed": not findings or not args.strict,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== frame_end_detection_check ({project.name}) ===")
    if summary["skipped_reason"]:
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2
    if not findings:
        print(f"  [PASS] {len(summary['rx_modules'])} rx module(s); "
              f"all use gap-timeout frame-end (or no frame-end pattern)")
        return 0
    rc = 0
    for f in findings:
        sev = "ERROR" if (args.strict and f.severity == "WARNING") else f.severity
        if sev == "ERROR":
            rc = 1
        loc = f" ({f.file})" if f.file else ""
        print(f"  [{sev.lower()}] {f.rule}{loc}: {f.message}")
    print(f"\nOverall: {'FAIL' if rc else 'PASS (with warnings)'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
