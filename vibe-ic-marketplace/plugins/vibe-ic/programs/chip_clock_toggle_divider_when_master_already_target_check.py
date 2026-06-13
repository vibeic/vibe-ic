#!/usr/bin/env python3
"""
chip_clock_toggle_divider_when_master_already_target_check.py — gate
(LL-30) catching the antipattern of introducing a toggle-divider for
the chip's core clock when the FPGA master clock is already at the
chip's target frequency.

Why this gate exists
====================
v0.119.30 <benchmark> vendor benchmark. Vendor reference uses direct 50 MHz
clock (master is 50 MHz, chip target is 50 MHz). Fresh agent emitted:

    always_ff @(posedge clk_50m)
        clk_2p5m <= ~clk_2p5m;          // unnecessary divider
    ...
    as3616_top u_chip ( .clk(clk_2p5m), ... );

The 16× coarser tick granularity (50→2.5 MHz) plus uncontrolled
clock-tree route on the toggle-register output produced sub-microsecond
edge skew that exceeds <half-duplex-tester>'s analog frontend tolerance —
byte[6]=0x02 deterministic FAIL.

The fix is structural: when chip_target_freq_hz == master_freq_hz, the
chip clock must be the master clock directly. No toggle, no counter
derivation, no divider.

Rule
----
1. Identify master clock frequency from one of:
   - L9_INTEGRATION_SPEC.json `fpga_master_clock_hz`
   - L9_INTEGRATION_SPEC.json `clock_binding[*].master_freq_hz`
   - constraints/*.json `master_clock_hz`
   - top-level RTL comment `// MASTER_CLOCK_HZ = N`
   Skip silently if none found.

2. Identify chip target clock frequency:
   - L2_FRS.json `clock.primary.freq_hz`
   - L8_TIMING_WAVEFORM.json `time_base.primary_clock_hz`
   - project.json `chip_clock_hz`
   Skip silently if none found.

3. Skip silently if master != chip target (legit divider case).

4. Scan rtl/*.{v,sv,svh} for any toggle-divider pattern
   (`<sig> <= ~<sig>` inside an always block) where <sig> is then
   passed to the chip submodule's clock port. If found, FAIL.

Honors waivers.json key `chip_clock_intentional_divider` (≥20 chars).

Usage
-----
python3 chip_clock_toggle_divider_when_master_already_target_check.py \
    <project_dir>

Returns 0 on PASS / silent-skip / waived, 1 on FAIL.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def find_rtl_files(project: Path) -> list[Path]:
    rtl = _pl.rtl_dir(project)
    if not rtl.is_dir():
        return []
    return sorted(list(rtl.glob("*.sv")) + list(rtl.glob("*.v"))
                  + list(rtl.glob("*.svh")))


def _load_json(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def find_master_freq(project: Path) -> int | None:
    # L9
    for stem in ("L9_INTEGRATION_SPEC.json",):
        for base in (_pl.generated_docs_dir(project), project / "docs", project):
            p = base / stem
            if p.is_file():
                d = _load_json(p)
                if not d:
                    continue
                v = d.get("fpga_master_clock_hz")
                if isinstance(v, (int, float)):
                    return int(v)
                cb = d.get("clock_binding") or []
                if isinstance(cb, list):
                    for entry in cb:
                        if isinstance(entry, dict):
                            mf = entry.get("master_freq_hz")
                            if isinstance(mf, (int, float)):
                                return int(mf)
    # constraints/*.json
    cdir = _pl.constraints_dir(project)
    if cdir.is_dir():
        for p in cdir.glob("*.json"):
            d = _load_json(p)
            if isinstance(d, dict):
                v = d.get("master_clock_hz")
                if isinstance(v, (int, float)):
                    return int(v)
    # RTL comment hint
    for f in find_rtl_files(project):
        try:
            text = f.read_text(errors="replace")
        except Exception:
            continue
        m = re.search(
            r"MASTER_CLOCK_HZ\s*[:=]\s*(\d+)",
            text, re.IGNORECASE,
        )
        if m:
            return int(m.group(1))
    return None


def find_chip_freq(project: Path) -> int | None:
    candidates = [
        ("L2_FRS.json", ["clock", "primary", "freq_hz"]),
        ("L8_TIMING_WAVEFORM.json", ["time_base", "primary_clock_hz"]),
    ]
    for stem, path in candidates:
        for base in (_pl.generated_docs_dir(project), project / "docs", project):
            p = base / stem
            if not p.is_file():
                continue
            d = _load_json(p)
            cur = d
            for k in path:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    cur = None
                    break
            if isinstance(cur, (int, float, str)):
                try:
                    return int(float(cur))
                except (TypeError, ValueError):
                    pass
    p = project / "project.json"
    if p.is_file():
        d = _load_json(p)
        if isinstance(d, dict):
            v = d.get("chip_clock_hz")
            if isinstance(v, (int, float)):
                return int(v)
    return None


# Match a toggle assignment `<sig> <= ~<sig>` (any RHS spacing).
TOGGLE_PAT = re.compile(
    r"\b(\w+)\s*<=\s*~\s*\1\b",
    re.MULTILINE,
)

# Find module instantiations: walk `<modname> <instname> ( .clk(<sig>) ...);`
# We look for `.clk(<sig>)` — the most common chip clock port name —
# but also accept `.sys_clk(...)`, `.core_clk(...)`. The submodule name
# heuristic: any submodule that contains the strings `top` or `core` in
# its module name AND whose port `clk` (or known aliases) gets the
# toggled signal.
PORT_PAT = re.compile(
    r"\.\s*(clk|sys_clk|core_clk|chip_clk|clk_in)\s*\(\s*(\w+)\s*\)",
    re.IGNORECASE,
)


def collect_toggle_signals(src: str) -> set[str]:
    return {m.group(1) for m in TOGGLE_PAT.finditer(src)}


def collect_chip_clock_args(src: str) -> set[str]:
    return {m.group(2) for m in PORT_PAT.finditer(src)}


def waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
        v = d.get("chip_clock_intentional_divider", "")
        return isinstance(v, str) and len(v.strip()) >= 20
    except Exception:
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: chip_clock_toggle_divider_when_master_already_"
              "target_check.py <project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    rtl_files = find_rtl_files(project)
    if not rtl_files:
        print("PASS — no rtl/ directory or no Verilog files (skipped)")
        return 0

    master = find_master_freq(project)
    chip = find_chip_freq(project)
    if master is None or chip is None:
        print("PASS — master / chip target frequency not declared in L9 "
              "/ L2 / project.json (gate skipped, no false alerts)")
        return 0

    # Tolerate 1% drift (rounding).
    if abs(master - chip) / max(abs(master), 1) > 0.01:
        print(f"PASS — master {master}Hz != chip {chip}Hz; legitimate "
              f"divider use case (gate skipped)")
        return 0

    all_src = ""
    for f in rtl_files:
        try:
            all_src += "\n" + strip_comments(f.read_text())
        except Exception:
            pass

    toggles = collect_toggle_signals(all_src)
    if not toggles:
        print(f"PASS — master == chip clock ({master}Hz) and no toggle "
              "divider in RTL (clock used directly)")
        return 0

    chip_clk_args = collect_chip_clock_args(all_src)
    offenders = sorted(toggles & chip_clk_args)

    if not offenders:
        # toggle exists but not driving chip clock — out of scope here.
        print(f"PASS — toggle dividers exist but none drives the chip "
              f"clock port ({sorted(toggles)} not in chip-clock args "
              f"{sorted(chip_clk_args)})")
        return 0

    if waived(project):
        print(f"PASS_WITH_WAIVER — {len(offenders)} chip-clock toggle "
              f"divider(s) when master already at chip target freq "
              f"({master}Hz), waiver set: {offenders}")
        return 0

    print(f"FAIL — chip target clock = master clock = {master}Hz, but "
          f"RTL introduces toggle divider(s) on the chip clock port:")
    for sig in offenders:
        print(f"  • {sig} <= ~{sig}  → connected to chip submodule .clk")
    print()
    print("Why this matters:")
    print("  Vendor reference design ties the chip core clock directly")
    print("  to the master pad. Inserting a toggle divider when no")
    print("  frequency change is needed:")
    print("    1. Halves effective tick granularity (silent timing skew)")
    print("    2. Routes a toggling register output through general")
    print("       logic fabric instead of the dedicated clock tree")
    print("    3. Produces sub-microsecond edge-shape mismatches that")
    print("       exceed master tester analog frontend tolerance")
    print()
    print("Fix: drop the divider, wire master_clk directly to chip.clk:")
    print("    chip_top u_chip (.clk(MAX10_CLK1_50), ...);")
    print()
    print('Or document an intentional case in waivers.json (>=20 chars):')
    print('    {"chip_clock_intentional_divider": "<reason>"}')
    return 1


if __name__ == "__main__":
    sys.exit(main())
