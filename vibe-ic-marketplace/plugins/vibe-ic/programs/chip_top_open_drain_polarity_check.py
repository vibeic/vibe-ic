#!/usr/bin/env python3
"""chip_top_open_drain_polarity_check.py — v1.6.225.

When a chip_top exposes split open-drain pad signals (`<bus>_oe_low` +
`<bus>_drive_data`) to a Verilog wrapper that reconstructs the tristate
pad, the wrapper's polarity MUST match the chip's semantic — NOT the
signal name. This gate detects the BENCH-A-class bug where Yosys's
output naming was `id_bus_oe_low` but the actual semantic was
`id_bus_drive_low` (=1 means drive low, opposite of "active low OE").

Bug class: silent gate-level FPGA-reverify failure (DUT silent, byte
fill = 0x02 = bus pull-up) because the wrapper held the bus LOW at
idle. Pre-detection rule: assert that wrapper's tristate conditional
agrees with the assignment direction inside the chip_top_asic .sv:

  RTL chip_top_asic:    assign <bus>_oe_low = <bus>_drive_low;
                        assign <bus>_drive_data = 1'b0;
  Wrapper MUST have:    assign <bus> = (oe_low_w == 1'b1)
                                        ? drive_data_w
                                        : 1'bz;

If the wrapper has `1'b0` instead of `1'b1` → INVERTED → FAIL.

Chip-AGNOSTIC. Triggers automatically for any project with
chip_top_gate_wrapper.v + a chip_top_asic.sv that exports
`<*>_oe_low` outputs.
"""
import argparse, re, sys
from pathlib import Path

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--wrapper",       type=Path, required=True,
                    help="chip_top_gate_wrapper.v")
    p.add_argument("--asic-rtl",      type=Path, required=True,
                    help="chip_top_asic.sv (the RTL source that defines "
                         "the oe_low semantic)")
    p.add_argument("--bus-prefix",    default="id_bus",
                    help="signal prefix for the open-drain bus")
    args = p.parse_args()

    wrapper = args.wrapper.read_text()
    rtl = args.asic_rtl.read_text()

    oe_re = re.compile(rf"assign\s+{re.escape(args.bus_prefix)}_oe_low\s*=\s*(\S+)\s*;")
    m = oe_re.search(rtl)
    if not m:
        print(f"[polarity] no `assign {args.bus_prefix}_oe_low = ...` "
              f"in {args.asic_rtl} — skipping (no split-tristate chip)")
        return 0
    rhs = m.group(1)
    # If RHS is literally `<bus>_drive_low` → semantic is "1 means drive"
    drive_semantic_is_active_high = (
        rhs == f"{args.bus_prefix}_drive_low" or
        rhs.endswith("_drive_low") or
        "drive_low" in rhs)
    print(f"[polarity] chip_top_asic: assign {args.bus_prefix}_oe_low = {rhs};")
    print(f"[polarity] drive_active_high = {drive_semantic_is_active_high}")

    # In the wrapper, look for the assign id_bus = (oe... == X) ? ... : 1'bz;
    wre = re.compile(
        rf"assign\s+{re.escape(args.bus_prefix)}\s*=\s*\(\s*oe_low_w\s*==\s*1'b([01])\s*\)\s*\?\s*\S+\s*:\s*1'bz")
    wm = wre.search(wrapper)
    if not wm:
        print(f"[polarity] WARNING: could not find canonical tristate "
              f"assign in {args.wrapper} — skipping")
        return 0
    wrapper_drive_when = wm.group(1)  # '0' or '1'
    expected = '1' if drive_semantic_is_active_high else '0'
    if wrapper_drive_when == expected:
        print(f"[polarity] PASS: wrapper drives when oe_low=={wrapper_drive_when} "
              f"(matches chip's drive-active-high semantic)")
        return 0
    print(f"[polarity] FAIL: wrapper drives when oe_low=={wrapper_drive_when} "
          f"but chip semantic requires oe_low=={expected}. "
          f"Bus will be held opposite of intended at idle.", file=sys.stderr)
    print(f"[polarity] FIX: change wrapper's `(oe_low_w == 1'b{wrapper_drive_when})` "
          f"to `(oe_low_w == 1'b{expected})`", file=sys.stderr)
    return 1

if __name__ == "__main__":
    sys.exit(main())
