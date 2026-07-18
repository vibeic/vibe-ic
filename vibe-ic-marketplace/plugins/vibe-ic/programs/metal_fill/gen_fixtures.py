#!/usr/bin/env python3
"""gen_fixtures.py — synthetic, NDA-clean sparse-die fixture for metal_fill.py.

A ``DIE_UM`` x ``DIE_UM`` die (boundary on layer 0/0) carrying only a handful of thin
signal wires on met1 (34/0) — a genuinely sparse layer well below any CMP density
target, so the fill utility has real work to do and the before/after numbers are
hand-checkable.

    FILL_OUT=<out.gds> [FILL_DIE=<die_um>] [FILL_WIRES=<n>] klayout -b -r gen_fixtures.py
"""
import os
import sys


def build(path, die_um=50.0, n_wires=4, dbu=0.001):
    import pya
    ly = pya.Layout()
    ly.dbu = dbu
    top = ly.create_cell("SP")
    U = int(round(1.0 / dbu))
    die = int(die_um * U)
    m1 = ly.layer(34, 0)
    top.shapes(ly.layer(0, 0)).insert(pya.Box(0, 0, die, die))
    # n evenly-spaced 0.5um-wide vertical wires spanning most of the die height
    span = int((die_um - 4.0) * U)
    for i in range(n_wires):
        x = int(5 * U) + i * int((die_um - 10.0) / max(n_wires - 1, 1) * U)
        top.shapes(m1).insert(pya.Box(x, int(2 * U), x + int(0.5 * U), int(2 * U) + span))
    ly.write(path)


def main():
    out = os.environ.get("FILL_OUT")
    die = float(os.environ.get("FILL_DIE", "50"))
    wires = int(os.environ.get("FILL_WIRES", "4"))
    if not out:
        sys.stderr.write("gen_fixtures: set FILL_OUT.\n")
        return 2
    build(out, die, wires)
    sys.stderr.write(f"gen_fixtures: wrote {out} ({die}x{die}um die, {wires} wires)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
