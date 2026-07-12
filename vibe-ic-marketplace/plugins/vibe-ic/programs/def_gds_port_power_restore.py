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
# v1.3.93 — port labels are emitted PER METAL LAYER: text GDS layer TEXT_LAYER[0]
# (100), datatype = the pin's 1-based metal index (MET1->dt1, MET2->dt2, …), so a
# label attaches ONLY to its own metal. A single shared text layer welded a pin's
# net to any FOREIGN higher-metal wire crossing over the pin point (e.g. a MET3
# crossover over a MET2 pin), fabricating a net-merge "short" in extraction.
# datatype 0 = catch-all for a pin with no resolved metal layer (legacy).
TEXT_LAYER = (100, 0)
RAIL_MARKER = {"VDD": (901, 0), "VSS": (902, 0)}


def _metal_index(layer_name):
    """DEF pin layer 'METn' -> 1-based metal index n; 0 for a non-metal layer."""
    m = re.match(r"MET(\d+)$", (layer_name or "").upper())
    return int(m.group(1)) if m else 0


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


def _metal_num(name):
    """'MET3' -> 3; a non-MET layer -> a large sentinel (never the followpin min)."""
    m = re.match(r"MET(\d+)$", (name or "").upper())
    return int(m.group(1)) if m else 9999


def parse_power_rails(def_text):
    """-> dict net -> list of (x1,y1,x2,y2,width,metal) SPECIALNET rail segments.

    The trailing `metal` (e.g. 'MET1') is captured so `restore` can paint the
    uniting rail-marker on the FOLLOW-PIN layer ONLY — see the note in `restore`."""
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
                r"(MET\d+)\s+(\d+)[^(]*\(\s*(\d+)\s+(\d+)\s*\)\s*\(\s*(\*|\d+)\s+(\*|\d+)\s*\)", rec):
            metal = sm.group(1)
            w = int(sm.group(2)); x1 = int(sm.group(3)); y1 = int(sm.group(4))
            x2 = x1 if sm.group(5) == "*" else int(sm.group(5))
            y2 = y1 if sm.group(6) == "*" else int(sm.group(6))
            segs.append((x1, y1, x2, y2, w, metal))
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
    tbase = TEXT_LAYER[0]

    for name, layer, x, y in pins:
        # per-metal text layer keyed to the pin's own metal (layer-aware; never
        # weld the pin net to a foreign crossover on another metal).
        tlayer = ly.layer(tbase, _metal_index(layer))
        tc.shapes(tlayer).insert(pya.Text(
            name, pya.Trans(pya.Trans.R0, int(round(x * scale)), int(round(y * scale)))))

    # v1.3.93 — paint the uniting rail-marker on the FOLLOW-PIN layer ONLY.
    # The marker exists to weld the physically-DISJOINT met1 follow-pin rails
    # (no vertical metal between rows) into one power net for the geometric LVS
    # extractor. An UPPER-metal PDN strap must NOT get a marker: the marker is a
    # flat 2D box, so a strap's footprint would project straight down onto every
    # signal wire routed BENEATH it on a lower layer, and the power-by-geometry
    # extractor would then label those signals as touching the rail = a FLOOD of
    # false VDD<->VSS shorts (measured: 87 on spm once MET4/MET5 straps were
    # added). Straps unite the rails through REAL via connectivity, so they need
    # no marker. Restrict markers to the LOWEST metal among the rail segments
    # (the follow-pin layer); a met1-only PDN paints exactly as before.
    _all_metals = [_metal_num(s[5]) for segs in rails.values() for s in segs]
    _fp_metal = min(_all_metals) if _all_metals else None
    n_rail = 0
    n_strap_skipped = 0
    for net, segs in rails.items():
        if net not in RAIL_MARKER:
            continue
        ml = ly.layer(*RAIL_MARKER[net])
        for (x1, y1, x2, y2, w, metal) in segs:
            if _metal_num(metal) != _fp_metal:
                n_strap_skipped += 1
                continue
            hw = w / 2.0
            xa, xb = sorted((x1, x2)); ya, yb = sorted((y1, y2))
            tc.shapes(ml).insert(pya.Box(
                int(round((xa - hw) * scale)), int(round((ya - hw) * scale)),
                int(round((xb + hw) * scale)), int(round((yb + hw) * scale))))
            n_rail += 1

    ly.write(gds_out)
    _strap_note = (f" (+{n_strap_skipped} upper-metal strap seg(s) NOT marked — "
                   f"united via real via connectivity)" if n_strap_skipped else "")
    print(f"restored: {len(pins)} I/O labels + {n_rail} power-rail markers "
          f"({', '.join(rails.keys())}){_strap_note} -> {gds_out}")
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
