#!/usr/bin/env python3
"""def_gds_port_power_restore — restore top-level port labels + power-rail markers into a
streamed GDS from its routed DEF, so LVS can name ports and unite a FOLLOWPIN power grid.

KLayout streamout (the branch a stdcell-marker / dummy-fill PDK forces) writes NO port
text labels, so the GDS has anonymous top nets and a power grid of physically-disjoint
FOLLOWPIN rails. This pass reads the DEF PINS (name/layer/placed) and SPECIALNETS (power
rails) and injects:
  * a `pya.Text` label per I/O pin on the label-purpose layer (so extraction names ports);
  * a rail-marker rectangle per SPECIALNET FOLLOWPIN segment on a dedicated layer
    (901=VDD, 902=VSS) — the extractor (`klayout_pdk_lvs`) then names power nets by
    GEOMETRY (a net whose m1 overlaps a marker IS that rail), robust to via gaps.

This is the deterministic DEF-parsing half; it is intended to run as a post-streamout pass
in Phase-3 `step_gds` (gated on the KLayout streamout engine). The DEF-pin parsing mirrors
`lvs_def_port_seed.parse_def_pins` and is chip-AGNOSTIC.

CLI:
  def_gds_port_power_restore.py --gds-in in.gds --def-file spm.def --gds-out out.gds
Requires KLayout `pya`; exits 3 (disclosed) if absent.
"""
import sys, re, argparse

LAYER_GDS = {"MET1": (9, 0), "MET2": (11, 0), "MET3": (13, 0), "MET4": (15, 0),
             "MET5": (17, 0), "MET6": (19, 0), "MET7": (21, 0)}
TEXT_LAYER = (100, 0)
RAIL_MARKER = {"VDD": (901, 0), "VSS": (902, 0)}


def parse_pins(def_text):
    """-> list of (name, layer, x_dbu, y_dbu). Coordinates are DEF database units."""
    pins = []
    if "PINS" not in def_text:
        return pins
    body = def_text.split("PINS", 1)[1].split("END PINS", 1)[0]
    for rec in re.split(r"\n\s*-\s+", body)[1:]:
        m = re.match(r"(\S+)", rec)
        if not m:
            continue
        ml = re.search(r"\+\s*LAYER\s+(\w+)\s*\(", rec)
        mp = re.search(r"\+\s*PLACED\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)", rec)
        if ml and mp:
            pins.append((m.group(1), ml.group(1), int(mp.group(1)), int(mp.group(2))))
    return pins


def parse_power_rails(def_text):
    """-> dict net -> list of (x1,y1,x2,y2,width) SPECIALNET rail segments."""
    rails = {}
    if "SPECIALNETS" not in def_text:
        return rails
    body = def_text.split("SPECIALNETS", 1)[1].split("END SPECIALNETS", 1)[0]
    for rec in re.split(r"\n\s*-\s+", body)[1:]:
        m = re.match(r"(\S+)", rec)
        if not m:
            continue
        segs = []
        for sm in re.finditer(
                r"MET\d+\s+(\d+)[^(]*\(\s*(\d+)\s+(\d+)\s*\)\s*\(\s*(\*|\d+)\s+(\*|\d+)\s*\)", rec):
            w = int(sm.group(1)); x1 = int(sm.group(2)); y1 = int(sm.group(3))
            x2 = x1 if sm.group(4) == "*" else int(sm.group(4))
            y2 = y1 if sm.group(5) == "*" else int(sm.group(5))
            segs.append((x1, y1, x2, y2, w))
        if segs:
            rails[m.group(1)] = segs
    return rails


def restore(gds_in, def_file, gds_out, top=None):
    try:
        import pya
    except Exception:
        sys.stderr.write("def_gds_port_power_restore: 'pya' not available. DISCLOSED.\n")
        return 3
    def_text = open(def_file).read()
    pins = parse_pins(def_text)
    rails = parse_power_rails(def_text)

    ly = pya.Layout(); ly.read(gds_in)
    tc = ly.cell(top) if top else ly.top_cell()
    scale = (1.0 / 1000.0) / ly.dbu     # DEF unit (nm) -> GDS dbu
    tlayer = ly.layer(*TEXT_LAYER)

    for name, layer, x, y in pins:
        tc.shapes(tlayer).insert(pya.Text(
            name, pya.Trans(pya.Trans.R0, int(round(x * scale)), int(round(y * scale)))))

    n_rail = 0
    for net, segs in rails.items():
        if net not in RAIL_MARKER:
            continue
        ml = ly.layer(*RAIL_MARKER[net])
        for (x1, y1, x2, y2, w) in segs:
            hw = w / 2.0
            xa, xb = sorted((x1, x2)); ya, yb = sorted((y1, y2))
            tc.shapes(ml).insert(pya.Box(
                int(round((xa - hw) * scale)), int(round((ya - hw) * scale)),
                int(round((xb + hw) * scale)), int(round((yb + hw) * scale))))
            n_rail += 1

    ly.write(gds_out)
    print(f"restored: {len(pins)} I/O labels + {n_rail} power-rail markers "
          f"({', '.join(rails.keys())}) -> {gds_out}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--gds-in", required=True)
    ap.add_argument("--def-file", required=True)
    ap.add_argument("--gds-out", required=True)
    ap.add_argument("--top")
    a = ap.parse_args(argv)
    return restore(a.gds_in, a.def_file, a.gds_out, a.top)


if __name__ == "__main__":
    sys.exit(main())
