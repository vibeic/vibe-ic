#!/usr/bin/env python3
"""
bist_window_calculator.py — Size BIST response-capture windows for worst-case.

Learned from <chip-class> FPGA BIST debug (2026-04-21):

  A BIST sample window that is sized for the MEDIAN response length silently
  drops the tail of the LONGEST response. The CRC residual check then reports
  a bogus "CRC error" for every long opcode. This looks like a CRC bug but is
  really a timing-window bug.

Given:
  --max-bytes N           Maximum response length (including CRC)
  --bit-period-us X       Per-bit time (from TX_PHY: H0_LOW+H0_HIGH or equiv)
  --ibt-us Y              Inter-byte idle gap
  --br-us Z               Leading BR pulse (optional, default 14us)
  --margin M              Safety multiplier (default 1.5)
  --clk-mhz F             Checker clock rate (to convert ms → cycle count)

Prints:
  - Required window in milliseconds
  - Required checker cycle count (win_cnt register width hint)
  - Required SEQ_RX wait-timer cycle count (> window)
  - Register width needed for win_cnt (bits)

Usage:
  python3 bist_window_calculator.py --max-bytes 22 --bit-period-us 8.8 \
                                     --ibt-us 14 --clk-mhz 2.5

Exit code: always 0 (this is a calculator, not a lint).
"""

from __future__ import annotations

import argparse
import math
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--max-bytes", type=int, required=True,
                   help="Longest response length including CRC")
    p.add_argument("--bit-period-us", type=float, required=True,
                   help="Per-bit time in microseconds")
    p.add_argument("--ibt-us", type=float, default=14.0,
                   help="Inter-byte idle gap in us (default 14)")
    p.add_argument("--br-us", type=float, default=14.0,
                   help="Leading BR pulse in us (default 14)")
    p.add_argument("--margin", type=float, default=1.5,
                   help="Safety multiplier (default 1.5)")
    p.add_argument("--clk-mhz", type=float, required=True,
                   help="Checker clock rate in MHz")
    args = p.parse_args(argv)

    # Core formula: window ≥ BR + N × (8 × bit + IBT)
    per_byte_us = 8 * args.bit_period_us + args.ibt_us
    payload_us = args.max_bytes * per_byte_us
    raw_us = args.br_us + payload_us
    window_us = raw_us * args.margin

    # Convert to checker cycles
    cycles = int(math.ceil(window_us * args.clk_mhz))
    seq_rx_cycles = int(math.ceil(cycles * 1.15))  # sequencer should wait longer
    bits_needed = max(1, math.ceil(math.log2(seq_rx_cycles + 1)))

    print("=== BIST sample window sizing ===")
    print(f"  max response bytes        : {args.max_bytes}")
    print(f"  per-byte period           : {per_byte_us:.2f} us "
          f"(8 x {args.bit_period_us:.2f} + {args.ibt_us:.2f})")
    print(f"  raw payload + BR          : {raw_us:.2f} us")
    print(f"  with margin {args.margin:.2f}x   : {window_us:.2f} us "
          f"({window_us/1000:.3f} ms)")
    print()
    print("=== Generated constants ===")
    print(f"  // Sample window cycles @ {args.clk_mhz} MHz")
    print(f"  localparam WIN_CYCLES     = {cycles};")
    print(f"  localparam SEQ_RX_CYCLES  = {seq_rx_cycles};  // sequencer wait")
    print(f"  reg [{bits_needed-1}:0] win_cnt;              "
          f"// {bits_needed}-bit reg for WIN_CYCLES")
    print()
    print("Paste WIN_CYCLES into aid_checker.v's `win_cnt >= WIN_CYCLES` guard")
    print("and SEQ_RX_CYCLES into the sequencer's SEQ_RX wait.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
