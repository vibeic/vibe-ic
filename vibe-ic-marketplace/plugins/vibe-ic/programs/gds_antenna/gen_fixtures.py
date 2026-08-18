#!/usr/bin/env python3
"""gen_fixtures.py — synthetic, NDA-clean antenna fixtures for antenna_check.py.

Builds a one-transistor structure whose antenna ratio is HAND-COMPUTABLE, so the check
can be proven, not trusted:

    gate  = poly (0.5um wide) over active (2um tall)      -> gate area  = 1.0 um^2
    metal = a 0.5um-wide met1 wire of length L um          -> metal area = 0.5*L um^2
    antenna ratio = (0.5*L) / 1.0 = 0.5*L

So ANT_LEN=100 -> ratio 50 (violation vs a 40 limit); ANT_LEN=20 -> ratio 10 (clean).
The poly gate is joined to the met1 antenna by a poly->met1 contact; the diffusion is
left unconnected (no diode credit) so the antenna is not relieved.

Layer numbers here are synthetic placeholders (active=1/0, poly=2/0, cont=3/0,
met1=4/0, via1=5/0, met2=6/0) — no foundry data.

    ANT_OUT=<out.gds> ANT_LEN=<wire_len_um> [ANT_MET2_LEN=<upper_len_um>] \
        klayout -b -r gen_fixtures.py
"""
import os
import sys


def build(path, met1_len_um, met2_len_um=0.0, dbu=0.001, diode=False, diode_offnet=False):
    import pya
    ly = pya.Layout()
    ly.dbu = dbu
    top = ly.create_cell("ANT")
    U = int(round(1.0 / dbu))  # 1 um in dbu

    active = ly.layer(1, 0)
    poly = ly.layer(2, 0)
    cont = ly.layer(3, 0)
    met1 = ly.layer(4, 0)
    via1 = ly.layer(5, 0)
    met2 = ly.layer(6, 0)
    diode_l = ly.layer(7, 0)   # antenna-diode ANODE marker (#45 recognition layer)

    # active 2x2um; poly 0.5um-wide strip crossing it -> gate = 0.5um * 2um = 1.0 um^2
    top.shapes(active).insert(pya.Box(0, 0, 2 * U, 2 * U))
    top.shapes(poly).insert(pya.Box(int(0.75 * U), -1 * U, int(1.25 * U), 3 * U))
    # poly routing up to the contact landing
    top.shapes(poly).insert(pya.Box(int(0.75 * U), 3 * U, int(1.25 * U), int(3.5 * U)))
    # poly->met1 contact
    top.shapes(cont).insert(pya.Box(int(0.85 * U), int(3.1 * U),
                                    int(1.15 * U), int(3.4 * U)))
    # met1 antenna wire: 0.5um wide, length L, area = 0.5*L um^2
    y0 = int(3.0 * U)
    top.shapes(met1).insert(pya.Box(int(0.85 * U), y0,
                                    int(0.85 * U) + int(met1_len_um * U),
                                    y0 + int(0.5 * U)))
    # optional upper-metal jumper: a met2 wire tied to met1 via via1. In the FINAL
    # netlist this enlarges the node, but at the met1 etch STAGE it does not exist,
    # so the staged model must ignore it (this fixture proves the staged behaviour).
    if met2_len_um > 0.0:
        vx = int(1.0 * U)
        top.shapes(via1).insert(pya.Box(vx, y0 + int(0.1 * U),
                                        vx + int(0.3 * U), y0 + int(0.4 * U)))
        top.shapes(met2).insert(pya.Box(vx, y0,
                                        vx + int(met2_len_um * U), y0 + int(0.5 * U)))
    # #45: an antenna-diode ANODE marker overlapping the met1 antenna wire, so it
    # is electrically ON the antenna net. A 0.5x0.5um square at (2.0,3.0)-(2.5,3.5)
    # sits inside the met1 wire (y in [3.0,3.5]) whenever the wire reaches x=2.5.
    if diode:
        top.shapes(diode_l).insert(pya.Box(2 * U, y0, int(2.5 * U), y0 + int(0.5 * U)))
    # a diode marker placed OFF the net (touching no conductor): proves recognition
    # is CONNECTIVITY-based -- a stray diode elsewhere must NOT relieve the antenna.
    if diode_offnet:
        top.shapes(diode_l).insert(pya.Box(50 * U, 50 * U, int(50.5 * U), int(50.5 * U)))
    ly.write(path)


def main():
    out = os.environ.get("ANT_OUT")
    length = float(os.environ.get("ANT_LEN", "100"))
    met2 = float(os.environ.get("ANT_MET2_LEN", "0"))
    diode = os.environ.get("ANT_DIODE", "0") not in ("0", "", "false", "False")
    diode_offnet = os.environ.get("ANT_DIODE_OFFNET", "0") not in ("0", "", "false", "False")
    if not out:
        sys.stderr.write("gen_fixtures: set ANT_OUT and ANT_LEN.\n")
        return 2
    build(out, length, met2, diode=diode, diode_offnet=diode_offnet)
    sys.stderr.write(f"gen_fixtures: wrote {out} (met1_len={length}um, "
                     f"met2_len={met2}um, diode={diode}, diode_offnet={diode_offnet})\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
