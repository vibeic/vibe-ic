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

This is the deterministic DEF-parsing half. It runs as a post-streamout pass in Phase-3
`step_gds`, on EITHER streamout engine, whenever the streamed GDS is MEASURED to be
missing the labels the DEF places (vibe-ic#613 — it used to be gated on a bridge config
declaring `port_label_restore`, i.e. on a PDK class, when the thing that decides it is a
readable fact of the artefact). `gds_port_label_check` takes that measurement. The DEF-pin
parsing mirrors `lvs_def_port_seed.parse_def_pins` and is chip-AGNOSTIC.

LAYER NAMES GO THROUGH ONE RESOLVER (`metal_index`), which must agree with
`klayout_pdk_lvs._METAL_RE` — the consumer of the datatype this file writes. They did not,
and on a PDK naming its routing layers `Metal1 … Metal5` that split every pin onto the
datatype-0 catch-all AND made the SPECIALNETS scan find zero rail segments. A name the
resolver cannot place is DISCLOSED; when NOT ONE resolves, the pass REFUSES (exit 4)
rather than emit labels it knows the extractor will bind to the wrong metal.

CLI:
  def_gds_port_power_restore.py --gds-in in.gds --def-file spm.def --gds-out out.gds
Requires KLayout `pya`; exits 3 (disclosed) if absent, 4 if no pin layer resolves.
"""
import sys, re, argparse

# v1.3.93 — port labels are emitted PER METAL LAYER: text GDS layer TEXT_LAYER[0]
# (100), datatype = the pin's 1-based metal index (MET1->dt1, MET2->dt2, …), so a
# label attaches ONLY to its own metal. A single shared text layer welded a pin's
# net to any FOREIGN higher-metal wire crossing over the pin point (e.g. a MET3
# crossover over a MET2 pin), fabricating a net-merge "short" in extraction.
# datatype 0 = catch-all for a pin with no resolved metal layer (legacy).
TEXT_LAYER = (100, 0)
RAIL_MARKER = {"VDD": (901, 0), "VSS": (902, 0)}

# vibe-ic#613 — THE ONE metal-name resolver for this file. It had THREE separate
# hardcoded `MET(\d+)$` patterns (pin datatype, follow-pin minimum, SPECIALNETS
# segment scan) and the CONSUMER of the datatype contract — klayout_pdk_lvs's
# `_METAL_RE` — has always been `^(?:MET|METAL|M)(\d+)$`. On a PDK naming its
# routing layers `Metal1 … Metal5` the two halves of the SAME contract disagreed:
#
#   * every pin fell through to datatype 0, the catch-all the consumer binds to
#     m1 ALONE — so a pin above m1 either names nothing (port stays anonymous)
#     or names whatever m1 wire happens to pass under it. Silently the
#     pre-v1.3.93 behaviour this file exists to have fixed.
#   * `parse_power_rails` matched ZERO segments, so no rail marker was painted
#     and the follow-pin rails stayed physically disjoint — the other half of
#     what this pass is for.
#
# THE TECH-LEF ROUTING ORDER IS DELIBERATELY NOT USED as a fallback, and this is
# a measured negative result worth keeping: sky130's tech LEF declares `li1` as
# TYPE ROUTING, so met1's POSITION in the routing order is 2 while the datatype
# contract (and `klayout_pdk_lvs`'s `lm["metal"]` list) numbers it 1. Resolving
# by position would silently shift every sky130 label by one. The name is the
# contract; a name this cannot read is DISCLOSED and, when NOTHING resolves,
# REFUSED — never quietly bound to the catch-all.
_METAL_NAME_RE = re.compile(r"^(?:MET|METAL|M)(\d+)$", re.IGNORECASE)


def metal_index(layer_name):
    """DEF layer name -> 1-based metal index; 0 when the name declares none.

    Must agree with `klayout_pdk_lvs._METAL_RE`, which reads the datatype this
    produces. `test_issue613_*` drives both over one corpus.
    """
    m = _METAL_NAME_RE.match((layer_name or "").strip())
    return int(m.group(1)) if m else 0


def def_design_name(def_text):
    """The DEF's own `DESIGN <name> ;` — the design's statement of its top cell."""
    m = re.search(r"^\s*DESIGN\s+(\S+)\s*;", def_text or "", re.M)
    return m.group(1) if m else None


#: Stable preference among DEFs that name the SAME design. A PnR directory
#: holds one DEF per stage and they all carry the same `DESIGN` line, so the
#: name alone does not pick one; this orders the tie. Anything not listed sorts
#: after these, alphabetically.
_DEF_PREFERENCE = ("filled.def", "routed.def")


def def_rank(path, design):
    """Sort key (LOWER IS BETTER) for "which DEF describes `design`".

    vibe-ic#626 — THE ONE DEF-PAIRING RULE. It lived privately in
    `gds_port_label_check`, and the sibling half of the same change
    (`mixed_signal_top_lvs_run.resolve_macro_placements`) picked its DEF by
    taking the first entry of a sorted `*.def` glob instead — i.e. by DIRECTORY
    POSITION, the thing `gds_port_label_check`'s own docstring says never to
    pair on. Measured on a real run (IHP SG13G2 `u_hawaii_adc`), the PnR
    directory held nine DEFs; eight agreed on where the macros go and the ninth
    did not, and the alphabetical glob returned exactly that ninth:

        u_hawaii_adc.def  (the DEF the sign-off GDS was streamed from)
                          u_ds1 delta_sigma + FIXED ( 30080 439350 ) N
        filled.def        (a stale earlier iteration, alphabetically first)
                          u_ds1 delta_sigma + FIXED ( 15080 760610 ) FS

    so the merge instantiated the analog macros 15.0 x 321.3 um away from where
    the layout they were merged INTO has them, one of them mirrored. That is
    the failure the orientation guard next to it was written to prevent — "it
    looks integrated and is not" — reached one level up, through DEF choice.

    Both consumers now call THIS, so the flow cannot hold two answers to "which
    DEF describes this layout". `path` is a `pathlib.Path`; `design` may be None
    or empty, in which case only the preference order applies.
    """
    name = getattr(path, "name", str(path))
    if design and name == f"{design}.def":
        return (0, name)
    if name in _DEF_PREFERENCE:
        return (1 + _DEF_PREFERENCE.index(name), name)
    return (1 + len(_DEF_PREFERENCE), name)


def def_declared_pin_count(def_text):
    """The `PINS <n> ;` header count, or None when the DEF declares no PINS
    section at all.

    NOT the same number as `len(parse_pins())`: the header is what the design
    DECLARES, `parse_pins` is what carries a layer AND a placement and can
    therefore be labelled. A pin in the first and not the second has no geometry
    to name, and collapsing the two hides exactly that.
    """
    m = re.search(r"^\s*PINS\s+(\d+)\s*;", def_text or "", re.M)
    return int(m.group(1)) if m else None


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
    """-> dict net -> list of (x1,y1,x2,y2,width,metal) SPECIALNET rail segments.

    The trailing `metal` (e.g. 'MET1') is captured so `restore` can paint the
    uniting rail-marker on the FOLLOW-PIN layer ONLY — see the note in `restore`.

    #613: the layer token is read GENERICALLY and then ACCEPTED BY
    `metal_index`, rather than the layer name being baked into the scan pattern.
    A segment whose layer name does not resolve is dropped — it cannot be
    ordered against the others, so it cannot be told apart from an upper-metal
    strap, and painting a marker for it is the measured 87-false-short failure.
    """
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
                r"([A-Za-z]\w*)\s+(\d+)[^(;]*\(\s*(\d+)\s+(\d+)\s*\)\s*\(\s*(\*|\d+)\s+(\*|\d+)\s*\)", rec):
            metal = sm.group(1)
            if not metal_index(metal):
                continue
            w = int(sm.group(2)); x1 = int(sm.group(3)); y1 = int(sm.group(4))
            x2 = x1 if sm.group(5) == "*" else int(sm.group(5))
            y2 = y1 if sm.group(6) == "*" else int(sm.group(6))
            segs.append((x1, y1, x2, y2, w, metal))
        if segs:
            rails[m.group(1)] = segs
    return rails


def unresolved_pin_layers(pins):
    """The distinct pin-layer names `metal_index` cannot place, sorted.

    A pure function of the DEF — no layout, no KLayout — so the decision below
    can be made, and TESTED, before anything is opened.
    """
    return sorted({layer for _n, layer, _x, _y in pins if not metal_index(layer)})


def restore(gds_in, def_file, gds_out, top=None):
    try:
        def_text = open(def_file).read()
    except OSError as exc:
        sys.stderr.write(f"def_gds_port_power_restore: cannot read DEF: {exc}\n")
        return 3
    pins = parse_pins(def_text)
    rails = parse_power_rails(def_text)

    # #613 — REFUSE rather than silently bind every label to the catch-all.
    # datatype 0 is consumed as "this label belongs to m1"; for a pin actually
    # placed above m1 that either names nothing or names whatever m1 wire runs
    # under the pin point. When NOT ONE pin layer resolves, the naming
    # convention is not understood at all and there is no way to tell which of
    # those two it would be — so the honest outcome is a loud refusal, not a
    # GDS that looks labelled.
    #
    # DECIDED BEFORE `pya` IS TOUCHED, deliberately: it is a fact about the DEF,
    # it will still be true on a host that has KLayout, and a caller told "pya
    # not available" would go and install KLayout to reach the same refusal.
    _unresolved = unresolved_pin_layers(pins)
    if pins and not any(metal_index(l) for _n, l, _x, _y in pins):
        sys.stderr.write(
            "def_gds_port_power_restore: REFUSED — none of the "
            f"{len(pins)} DEF pin layer name(s) resolve to a metal index "
            f"({', '.join(_unresolved)}). Every label would land on the "
            "datatype-0 catch-all, which the extractor binds to m1 alone: a "
            "pin above m1 would name nothing or name a foreign net. The GDS is "
            "left untouched.\n")
        return 4

    try:
        import pya
    except Exception:
        sys.stderr.write("def_gds_port_power_restore: 'pya' not available. DISCLOSED.\n")
        return 3

    ly = pya.Layout(); ly.read(gds_in)
    tc = ly.cell(top) if top else ly.top_cell()
    scale = (1.0 / 1000.0) / ly.dbu     # DEF unit (nm) -> GDS dbu
    tbase = TEXT_LAYER[0]

    for name, layer, x, y in pins:
        # per-metal text layer keyed to the pin's own metal (layer-aware; never
        # weld the pin net to a foreign crossover on another metal).
        tlayer = ly.layer(tbase, metal_index(layer))
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
    _all_metals = [metal_index(s[5]) for segs in rails.values() for s in segs]
    _fp_metal = min(_all_metals) if _all_metals else None
    n_rail = 0
    n_strap_skipped = 0
    for net, segs in rails.items():
        if net not in RAIL_MARKER:
            continue
        ml = ly.layer(*RAIL_MARKER[net])
        for (x1, y1, x2, y2, w, metal) in segs:
            if metal_index(metal) != _fp_metal:
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
    # #613 — a PARTIAL resolution is the dangerous middle: the run looks clean
    # and those pins are on the m1 catch-all. Name them; never let the count
    # stand alone.
    _unres_note = (f" [UNRESOLVED LAYER: {len(_unresolved)} name(s) "
                   f"({', '.join(_unresolved)}) -> datatype-0 catch-all, bound "
                   f"to m1 by the extractor]" if _unresolved else "")
    print(f"restored: {len(pins)} I/O labels + {n_rail} power-rail markers "
          f"({', '.join(rails.keys())}){_strap_note}{_unres_note} -> {gds_out}")
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
