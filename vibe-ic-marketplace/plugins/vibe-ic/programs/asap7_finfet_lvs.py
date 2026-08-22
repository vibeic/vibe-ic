#!/usr/bin/env python3
"""asap7_finfet_lvs — device-level LVS for the ASAP7 (predictive 7nm FinFET) PDK.

B1/#174 — device-level LVS on asap7 was long DEFERRED as "no golden netlist +
FinFET device recognition blocked". BOTH blockers are now retired:
  1. The transistor-level GOLDEN exists and is PUBLIC/BSD-3 — the ASAP7 std-cell
     CDL (`asap7sc7p5t_28_R.cdl`, github The-OpenROAD-Project/asap7sc7p5t_28),
     one `.SUBCKT` per std cell with 4-terminal FinFETs (nmos_rvt/pmos_rvt,
     `nfin=N`). vibeic-eda stages it at libs.tech/cdl/ (see the Dockerfile).
  2. FinFET device recognition needs no FinFET-native extractor. KLayout's planar
     DeviceExtractorMOS3Transistor recognizes the ASAP7 transistor GEOMETRICALLY —
     GATE poly crossing ACTIVE, split N/P by the NSELECT/PSELECT implant markers.
     The ASAP7-specific unlock is GATE_CUT (10/0): the drawn GATE poly runs the
     full cell height UNDER the full-width LIG power-rail straps; GATE_CUT
     electrically SEVERS it into the active gate plus rail-tied stubs, so the real
     gate = (GATE - GATE_CUT) ∩ ACTIVE. WITHOUT the cut, connect(gate,LIG) welds
     the gate to VDD/VSS (a false short) and every cell mismatches.

The extraction emits a 4-terminal SPICE subckt (bulk normalized to the physical
rail: NMOS body->VSS, PMOS body->VDD — an isolated std cell has no local well-tap
so the geometric bulk floats, and the CDL golden ties the 4th terminal to the
rail; that is the physical truth). Both the extracted subckt and the CDL golden
are then read by the SAME reader and compared with klayout_pdk_lvs's proven
NetlistComparer path (bulk-normalize + power-only-cap waiver + W/L tolerance).

RESULT (asap7sc7p5t_28 R library, 208 CDL golden subckts, verified in vibeic-eda):
  159/208 (76%) device-level MATCH, proven-negative confirmed (a one-net corrupt
  -> MISMATCH). The 49-cell residual is a DISCLOSED, well-understood LVS-hard case
  — folded multi-finger drive cells whose layout draws a golden `nfin=N` device as
  M parallel series-stacks with independent internal diffusion nodes (device
  FOLDING): electrically equivalent but topologically distinct, needing
  series-parallel device reduction the comparer does not perform. It is NEVER
  reported as a MATCH. §4.05: reads only the layout GDS + the CDL golden (both are
  design/reference netlists, never a per-instance oracle). Never call a MATCH
  "silicon-proven": ASAP7 is a predictive academic PDK, tapeout_capable=false.

ASAP7 R staged-GDS FEOL layer map (verified against the staged std-cell GDS):
  NWELL 1/0  FIN 2/0  GATE 7/0  GATE_CUT 10/0  ACTIVE 11/0  NSELECT 12/0
  PSELECT 13/0  LIG 16/0 (MOL gate contact)  LISD 17/0 (MOL S/D contact)
  V0 18/0  M1 19/0  M1.pin-text 19/251

CLI:
  asap7_finfet_lvs.py extract <gds> --cell NAME [--out cell.spice]
  asap7_finfet_lvs.py compare <gds> --cell NAME --golden-cdl asap7sc7p5t_28_R.cdl
  asap7_finfet_lvs.py batch   <gds> --golden-cdl asap7sc7p5t_28_R.cdl [--json out.json]
Requires the KLayout Python module ('pya', inside vibeic-eda); exits 3 if absent.
"""
import sys, os, re, json, argparse
from _atomic_artefact import writing as atomic_writing  # vibe-ic#1082 (helper from PR #1094)

# ASAP7 FEOL layer map (layer, datatype). PDK-specific but data-driven — a third
# ASAP7 re-numbering only edits this table.
ASAP7_LAYERS = {
    "nwell": (1, 0), "fin": (2, 0), "gate": (7, 0), "gate_cut": (10, 0),
    "active": (11, 0), "nselect": (12, 0), "pselect": (13, 0),
    "lig": (16, 0), "lisd": (17, 0), "v0": (18, 0), "m1": (19, 0),
    "m1txt": (19, 251),
}
WL_TOL_ABS = 0.05   # um — geometric finger-sum W jitter tolerance
WL_TOL_REL = 0.02

# DESIGN-level layer map (#182) — the FEOL device layers PLUS the routed-design
# metal/via stack a placed-and-routed asap7 design uses for inter-cell wiring. A
# LIBRARY cell touches only M1 (19/0); a ROUTED design also carries M2..M9 and the
# vias between them, so the design extraction MUST cover the full stack or an
# upper-metal net splits into disconnected pieces (a false MISMATCH). Numbers are
# the official ASAP7 GDS layers (libs.tech/klayout/lvs/asap7.lyt LEF/DEF map):
# M1 19/0, M2 20/0, M3 30/0, M4 40/0 ... M9 90/0; V0 18/0 (M1<->MOL), V1 21/0,
# V2 25/0, V3 35/0 ... (V_i joins M_i<->M_{i+1}). label_dt = the datatype the DEF
# port/rail-name texts are injected on (metal/2); vdd/vss_marker = dedicated rail
# marker layers for the geometric power-net assignment (reused from klayout_pdk_lvs).
ASAP7_DESIGN_LAYERS = dict(ASAP7_LAYERS)
ASAP7_DESIGN_LAYERS.update({
    "metals": [(19, 0), (20, 0), (30, 0), (40, 0), (50, 0),
               (60, 0), (70, 0), (80, 0), (90, 0)],           # M1..M9 (bottom->top)
    "vias":   [(21, 0), (25, 0), (35, 0), (45, 0), (55, 0),
               (65, 0), (75, 0), (85, 0)],                    # V1..V8 (M_i<->M_i+1)
    "label_dt": 2,
    "vdd_marker": (901, 0), "vss_marker": (902, 0),
})


def _require_pya():
    try:
        import pya  # noqa
        return pya
    except Exception:
        sys.stderr.write("asap7_finfet_lvs: KLayout Python module 'pya' not "
                         "available (run inside vibeic-eda). DISCLOSED, not faked.\n")
        sys.exit(3)


# ---------------------------------------------------------------- extraction core
def extract_cell(pya, gds, cell_name, lm=None, power="VDD", ground="VSS", threads=4):
    """Extract one ASAP7 std cell's layout -> KLayout Netlist circuit (MOS3 + the
    GATE_CUT-severed real gate). Returns (l2n, netlist, circuit) — the l2n + netlist
    MUST be kept alive by the caller or the circuit object is destroyed."""
    lm = lm or ASAP7_LAYERS
    ly = pya.Layout(); ly.read(gds)
    top = ly.cell(cell_name)
    if top is None:
        raise RuntimeError(f"cell {cell_name!r} not in {gds}")
    L = lambda k: ly.layer(*lm[k])
    l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, top, []))
    try:
        l2n.threads = threads
    except Exception:
        pass
    mk = lambda k, nm: l2n.make_polygon_layer(L(k), nm)
    nwell = mk("nwell", "nwell"); active = mk("active", "active")
    gate_all = mk("gate", "gate_all"); gcut = mk("gate_cut", "gate_cut")
    nsel = mk("nselect", "nsel"); psel = mk("pselect", "psel")
    lisd = mk("lisd", "lisd"); lig = mk("lig", "lig")
    v0 = mk("v0", "v0"); m1 = mk("m1", "m1")
    # GATE_CUT severs the drawn poly -> real gate = (GATE - GATE_CUT) crossing ACTIVE
    gate = (gate_all - gcut).interacting(active)
    l2n.register(gate, "gate")
    # WELL-AWARE device regions (implant-marker split, same as a foundry deck)
    nact = active & nsel
    pact = active & psel
    ngate = gate & nact
    pgate = gate & pact
    nsd = nact - gate
    psd = pact - gate
    for r, nm in ((nsd, "nsd"), (psd, "psd"), (ngate, "ngate"), (pgate, "pgate")):
        l2n.register(r, nm)
    nmos = pya.DeviceExtractorMOS3Transistor("nmos_rvt")
    pmos = pya.DeviceExtractorMOS3Transistor("pmos_rvt")
    l2n.extract_devices(nmos, {"SD": nsd, "G": ngate, "tS": nsd, "tD": nsd, "tG": gate})
    l2n.extract_devices(pmos, {"SD": psd, "G": pgate, "tS": psd, "tD": psd, "tG": gate})
    # MOS3 connectivity: S/D->LISD, gate->LIG, LI->V0->M1 (no wells/taps in graph)
    for r in (nsd, psd, gate, lisd, lig, v0, m1):
        l2n.connect(r)
    l2n.connect(nsd, lisd); l2n.connect(psd, lisd); l2n.connect(gate, lig)
    l2n.connect(lisd, v0); l2n.connect(lig, v0); l2n.connect(v0, m1)
    tl = l2n.make_text_layer(L("m1txt"), "m1txt"); l2n.connect(m1, tl)
    l2n.extract_netlist()
    nl = l2n.netlist(); nl.combine_devices(); nl.purge()
    ckt = None
    for c in nl.each_circuit():
        if c.name.lower() == cell_name.lower():
            ckt = c; break
    if ckt is None:
        cs = list(nl.each_circuit())
        ckt = cs[0] if cs else None
    if ckt is None:
        raise RuntimeError("no circuit extracted")
    return l2n, nl, ckt


def _net_name(net, counter):
    if net is None:
        counter[0] += 1
        return f"UNCONN_{counter[0]}"
    nm = net.name
    return nm.strip() if (nm and nm.strip()) else f"n{net.expanded_name()}".replace(":", "_")


def emit_subckt(ckt, cell_name, power="VDD", ground="VSS", out=None):
    """Emit the extracted circuit as a 4-terminal SPICE subckt (CDL/netgen shape).
    Ports = every NAMED net (the M1 pin-label texts); the compare is by net-name
    hint so the order only needs to be stable. Bulk = physical rail."""
    counter = [0]
    named = sorted({n.name.strip() for n in ckt.each_net()
                    if n.name and n.name.strip()})
    sig = [n for n in named if n not in (power, ground)]
    ports = sig + [ground, power]
    lines = ["* ASAP7 klayout FinFET extraction (4-terminal, bulk normalized to rail)",
             f".SUBCKT {cell_name} " + " ".join(ports)]
    n = 0
    for d in ckt.each_device():
        cn = d.device_class().name.lower()
        term = {td.name: d.net_for_terminal(td.id())
                for td in d.device_class().terminal_definitions()}
        S = _net_name(term.get("S"), counter)
        G = _net_name(term.get("G"), counter)
        D = _net_name(term.get("D"), counter)
        bulk = ground if "nmos" in cn else power
        try:
            W = d.parameter("W"); Lp = d.parameter("L")
        except Exception:
            W = 0.0; Lp = 0.0
        model = "nmos_rvt" if "nmos" in cn else "pmos_rvt"
        lines.append(f"M{n} {D} {G} {S} {bulk} {model} w={W:.4g}u l={Lp:.4g}u")
        n += 1
    lines.append(".ENDS"); lines.append("")
    txt = "\n".join(lines)
    if out:
        with atomic_writing(out) as f:
            f.write(txt)
    return txt, n


# ---------------------------------------------------------------- CDL golden split
def split_cdl_subckts(cdl_path):
    """Parse a CDL into {cell_name: subckt_text}. Chip-AGNOSTIC pure text — needs
    no pya, so it is unit-testable outside the container."""
    blocks = {}
    cur = None; buf = []
    with open(cdl_path) as f:
        for line in f.read().splitlines():
            m = re.match(r"^\s*\.SUBCKT\s+(\S+)", line, re.I)
            if m:
                cur = m.group(1); buf = [line]
            elif cur is not None:
                buf.append(line)
                if re.match(r"^\s*\.ENDS", line, re.I):
                    blocks[cur] = "\n".join(buf) + "\n"; cur = None; buf = []
    return blocks


def subckt_device_count(subckt_text):
    """Count transistor cards (M...) in a subckt block — 0 = physical-only cell."""
    return sum(1 for ln in subckt_text.splitlines()
               if re.match(r"^\s*M", ln, re.I))


# ---------------------------------------------------------------- compare (reuse)
def _compare(pya, K, lay_path, src_path, cell, power="VDD", ground="VSS"):
    realports = K._lvs_source_ports(pya, src_path, cell) | {power, ground}
    lay, dl = K._lvs_prep(pya, lay_path, cell, realports, power, ground, is_layout=True)
    src, ds = K._lvs_prep(pya, src_path, cell, realports, power, ground, is_layout=False)
    K._lvs_tune(lay, pya, WL_TOL_ABS, WL_TOL_REL)
    K._lvs_tune(src, pya, WL_TOL_ABS, WL_TOL_REL)
    lg = K._LvsLogger(pya)
    ok = pya.NetlistComparer(lg).compare(lay, src)

    def ndev(nl):
        c = K._circuit_ci(nl, cell)
        return sum(1 for _ in c.each_device()) if c else -1
    return ok, ndev(lay), ndev(src), lg.mismatches


def _import_klayout_pdk_lvs():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import klayout_pdk_lvs as K
    return K


def _import_gate_verilog_to_spice():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gate_verilog_to_spice as G
    return G


def cmd_compare_one(pya, gds, cell, golden_cdl, power, ground, out=None):
    K = _import_klayout_pdk_lvs()
    blocks = split_cdl_subckts(golden_cdl)
    if cell not in blocks:
        return {"cell": cell, "verdict": "NO_GOLDEN"}
    l2n, nl, ckt = extract_cell(pya, gds, cell, power=power, ground=ground)
    lay_txt, ndev = emit_subckt(ckt, cell, power, ground, None)
    lay_path = (out or f"/tmp/_a7_{cell}") + ".lay.spice"
    src_path = (out or f"/tmp/_a7_{cell}") + ".src.spice"
    with atomic_writing(lay_path) as f:
        f.write(lay_txt)
    with atomic_writing(src_path) as f:
        f.write(blocks[cell])
    ok, nl_l, nl_s, mm = _compare(pya, K, lay_path, src_path, cell, power, ground)
    res = {"cell": cell,
           "verdict": "MATCH" if ok else "MISMATCH",
           "layout_devices": nl_l, "golden_devices": nl_s, "mismatch_msgs": mm,
           "method": "klayout_finfet_geometric_extract + NetlistComparer",
           "disclosure": ("ASAP7 predictive PDK (tapeout_capable=false). Reads only "
                          "layout GDS + CDL golden (§4.05). NOT silicon-proven.")}
    print("A7_LVS " + json.dumps(res))
    return res


def cmd_batch(pya, gds, golden_cdl, power, ground, json_out=None):
    K = _import_klayout_pdk_lvs()
    blocks = split_cdl_subckts(golden_cdl)
    ly = pya.Layout(); ly.read(gds)
    cells = sorted(c.name for c in ly.each_cell())
    tally = {"MATCH": 0, "MISMATCH": 0, "EXTRACT_ERR": 0, "COMPARE_ERR": 0,
             "NO_GOLDEN": 0, "PHYSICAL_ONLY": 0}
    detail = []
    for cell in cells:
        if cell not in blocks:
            tally["NO_GOLDEN"] += 1; continue
        if subckt_device_count(blocks[cell]) == 0:
            tally["PHYSICAL_ONLY"] += 1; continue
        try:
            l2n, nl, ckt = extract_cell(pya, gds, cell, power=power, ground=ground)
            lay_txt, _ = emit_subckt(ckt, cell, power, ground, None)
        except Exception as e:
            tally["EXTRACT_ERR"] += 1
            detail.append((cell, "EXTRACT_ERR", str(e)[:80])); continue
        lay_path = "/tmp/_a7b.lay.spice"; src_path = "/tmp/_a7b.src.spice"
        with atomic_writing(lay_path) as f:
            f.write(lay_txt)
        with atomic_writing(src_path) as f:
            f.write(blocks[cell])
        try:
            ok, nl_l, nl_s, mm = _compare(pya, K, lay_path, src_path, cell, power, ground)
        except Exception as e:
            tally["COMPARE_ERR"] += 1
            detail.append((cell, "COMPARE_ERR", str(e)[:80])); continue
        tally["MATCH" if ok else "MISMATCH"] += 1
        if not ok:
            detail.append((cell, "MISMATCH", f"layout={nl_l} golden={nl_s} mm={mm}"))
    compared = tally["MATCH"] + tally["MISMATCH"]
    out = {"gds": gds, "golden_cdl": golden_cdl, "cells": len(cells),
           "compared": compared, "tally": tally,
           "match_rate": round(tally["MATCH"] / compared, 4) if compared else None,
           "detail": detail}
    print("A7_LVS_BATCH " + json.dumps({k: out[k] for k in
          ("cells", "compared", "tally", "match_rate")}))
    if json_out:
        with open(json_out, "w") as f:
            json.dump(out, f, indent=1)
        print("wrote", json_out)
    return out


# ============================================================ DESIGN-level LVS (#182)
# The CELL/LIBRARY path above compares one std-cell's layout to its CDL golden. The
# DESIGN path compares a whole PLACED-AND-ROUTED asap7 design's layout to the
# device-level golden BUILT FROM ITS GATE NETLIST — so a routed design gets a real
# per-design MATCH/MISMATCH instead of the library-only WAIVED. Three steps:
#   (1) restore_design_labels — inject the routed DEF's top-port names + power-rail
#       markers into the streamed GDS (KLayout streamout writes no port texts), so
#       the extraction can NAME the top ports and unite the FOLLOWPIN rails.
#   (2) extract_design — the SAME GATE_CUT FinFET recipe as extract_cell, but across
#       the design and over the full M1..M9 + V0..V8 routing stack (inter-cell wiring),
#       then geometric power-net assignment (rail markers) that also REPORTS a real
#       VDD<->VSS short instead of hiding it.
#   (3) build_golden_netlist — expand each std-cell instance in the gate netlist into
#       its CDL .SUBCKT (via gate_verilog_to_spice) -> a device-level reference.
# The compare is klayout_pdk_lvs's proven NetlistComparer path (flatten both sides,
# bulk-normalize + power-only-cap waiver + W/L tolerance). §4.05: reads only the
# routed layout GDS + the gate netlist + the CDL golden — never a per-instance oracle.
# A folded multi-finger drive cell can still mismatch (the disclosed library residual);
# NEVER reported as a MATCH.
_PIN_RE = re.compile(r"\+\s*LAYER\s+M(\d+)")
_PLACED_RE = re.compile(r"\+\s*(?:PLACED|FIXED)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)")
# a SPECIALNET rail segment: `M<n> <width> ... ( x1 y1 ) ( x2|* y2|* )`
_RAIL_SEG_RE = re.compile(
    r"(M\d+)\s+(\d+)\s+.*?\(\s*(\d+)\s+(\d+)\s*\)\s*\(\s*(\*|\d+)\s+(\*|\d+)\s*\)")


def restore_design_labels(pya, gds_in, def_file, gds_out, lm=None):
    """Inject the routed DEF's top-port names + power-rail markers into `gds_in`.

    KLayout streamout writes NO port text, so a streamed design GDS has anonymous top
    nets and a physically-disjoint FOLLOWPIN power grid. This reads the DEF PINS
    (name/layer/placed) and SPECIALNETS (VDD/VSS rails) and paints:
      * a `pya.Text(name)` on the pin's own metal label layer (metal_gds/label_dt),
        so the extraction NAMES the top port (matching the gate-netlist port name);
      * a rail-marker rectangle per SPECIALNET rail segment on the LOWEST rail metal
        (901=VDD, 902=VSS) — the extractor then names power nets by GEOMETRY.
    Chip-AGNOSTIC DEF parse (mirrors def_gds_port_power_restore, asap7 M<n> layers).
    Returns (n_pins, [rail_net,...])."""
    lm = lm or ASAP7_DESIGN_LAYERS
    metals = lm["metals"]
    txt = open(def_file).read()
    ly = pya.Layout(); ly.read(gds_in)
    tc = ly.top_cell()
    # DEF database unit -> GDS dbu, from the DEF's OWN declared resolution.
    # A hard-coded 1000 mislocates every label by units/1000 on any PDK whose
    # DEF is emitted at another resolution (OpenROAD writes 2000 for a 2000-unit
    # LEF) — see def_gds_port_power_restore.def_units_per_micron for the full
    # consequence chain.
    _um = re.search(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;", txt, re.M)
    _units = int(_um.group(1)) if _um and int(_um.group(1)) > 0 else 1000
    scale = (1.0 / _units) / ly.dbu
    n_pins = 0
    if "PINS" in txt:
        body = txt.split("PINS", 1)[1].split("END PINS", 1)[0]
        for rec in re.split(r"\n\s*-\s+", body)[1:]:
            m = re.match(r"(\S+)", rec)
            ml = _PIN_RE.search(rec)
            mp = _PLACED_RE.search(rec)
            if not (m and ml and mp):
                continue
            mn = int(ml.group(1))
            if not (1 <= mn <= len(metals)):
                continue
            g = metals[mn - 1][0]
            tl = ly.layer(g, lm["label_dt"])
            tc.shapes(tl).insert(pya.Text(
                m.group(1), pya.Trans(pya.Trans.R0,
                                      int(round(int(mp.group(1)) * scale)),
                                      int(round(int(mp.group(2)) * scale)))))
            n_pins += 1
    rails = {}
    if "SPECIALNETS" in txt:
        body = txt.split("SPECIALNETS", 1)[1].split("END SPECIALNETS", 1)[0]
        for rec in re.split(r"\n\s*-\s+", body)[1:]:
            m = re.match(r"(\S+)", rec)
            segs = []
            for sm in _RAIL_SEG_RE.finditer(rec):
                metal = sm.group(1); w = int(sm.group(2))
                x1 = int(sm.group(3)); y1 = int(sm.group(4))
                x2 = x1 if sm.group(5) == "*" else int(sm.group(5))
                y2 = y1 if sm.group(6) == "*" else int(sm.group(6))
                segs.append((metal, x1, y1, x2, y2, w))
            if segs and m:
                rails[m.group(1)] = segs
    marker = {"VDD": lm["vdd_marker"], "VSS": lm["vss_marker"]}
    # paint markers on the LOWEST rail metal only (the follow-pin layer) — an upper
    # PDN strap's 2D marker would project onto signals beneath it = false shorts.
    _metal_num = lambda nm: int(re.match(r"M(\d+)$", nm).group(1)) if re.match(r"M(\d+)$", nm) else 9999
    _all = [_metal_num(s[0]) for segs in rails.values() for s in segs]
    _fp = min(_all) if _all else None
    n_rail = 0
    for net, segs in rails.items():
        if net not in marker:
            continue
        ml = ly.layer(*marker[net])
        for (metal, x1, y1, x2, y2, w) in segs:
            if _metal_num(metal) != _fp:
                continue
            hw = w / 2.0
            xa, xb = sorted((x1, x2)); ya, yb = sorted((y1, y2))
            tc.shapes(ml).insert(pya.Box(
                int(round((xa - hw) * scale)), int(round((ya - hw) * scale)),
                int(round((xb + hw) * scale)), int(round((yb + hw) * scale))))
            n_rail += 1
    ly.write(gds_out)
    return n_pins, [n for n in rails if n in marker]


def extract_design(pya, gds, top, lm=None, threads=4):
    """Extract a routed asap7 DESIGN GDS -> KLayout Netlist (GATE_CUT-severed FinFETs
    across the design + the full M1..M9 + V0..V8 routing connectivity + top-port /
    power-rail names). Returns (l2n, netlist, top_circuit, power_shorts, short_locs).

    The device recipe is IDENTICAL to extract_cell (so a cell that MATCHes library-LVS
    extracts the same devices here); the difference is DESIGN scope — every placed cell
    plus the inter-cell routing metals — and the geometric power assignment that names
    the rails and REPORTS a VDD<->VSS short (never hides it). The l2n + netlist must be
    kept alive by the caller or the circuit object is destroyed."""
    lm = lm or ASAP7_DESIGN_LAYERS
    K = _import_klayout_pdk_lvs()
    ly = pya.Layout(); ly.read(gds)
    tc = ly.cell(top)
    if tc is None:
        raise RuntimeError(f"top cell {top!r} not in {gds}")
    l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, tc, []))
    try:
        l2n.threads = threads
    except Exception:
        pass

    def mk(spec, nm):
        li = ly.find_layer(*spec)
        return l2n.make_polygon_layer(li if li is not None else ly.layer(*spec), nm)

    active = mk(lm["active"], "active")
    gate_all = mk(lm["gate"], "gate_all"); gcut = mk(lm["gate_cut"], "gate_cut")
    nsel = mk(lm["nselect"], "nsel"); psel = mk(lm["pselect"], "psel")
    lisd = mk(lm["lisd"], "lisd"); lig = mk(lm["lig"], "lig")
    v0 = mk(lm["v0"], "v0")
    metals = [mk(s, f"m{i + 1}") for i, s in enumerate(lm["metals"])]
    vias = [mk(s, f"vv{i + 1}") for i, s in enumerate(lm["vias"])]
    # GATE_CUT severs the drawn poly -> real gate = (GATE - GATE_CUT) crossing ACTIVE
    gate = (gate_all - gcut).interacting(active)
    l2n.register(gate, "gate")
    nact = active & nsel; pact = active & psel
    ngate = gate & nact; pgate = gate & pact
    nsd = nact - gate; psd = pact - gate
    for r, nm in ((nsd, "nsd"), (psd, "psd"), (ngate, "ngate"), (pgate, "pgate")):
        l2n.register(r, nm)
    nmos = pya.DeviceExtractorMOS3Transistor("nmos_rvt")
    pmos = pya.DeviceExtractorMOS3Transistor("pmos_rvt")
    l2n.extract_devices(nmos, {"SD": nsd, "G": ngate, "tS": nsd, "tD": nsd, "tG": gate})
    l2n.extract_devices(pmos, {"SD": psd, "G": pgate, "tS": psd, "tD": psd, "tG": gate})
    m1 = metals[0]
    for r in [nsd, psd, gate, lisd, lig, v0] + metals:
        l2n.connect(r)
    l2n.connect(nsd, lisd); l2n.connect(psd, lisd); l2n.connect(gate, lig)
    l2n.connect(lisd, v0); l2n.connect(lig, v0); l2n.connect(v0, m1)
    # inter-cell routing: V_i joins M_i <-> M_{i+1}
    for i, v in enumerate(vias):
        l2n.connect(v, metals[i]); l2n.connect(v, metals[i + 1])
    # top-port / rail names: each metal -> ONLY its own label text (metal_gds/label_dt);
    # the cell GDS's per-cell M1 pin texts (19/251) are deliberately NOT connected, so
    # internal cell nets stay anonymous (topology-matched) and only injected top labels
    # + geometric rails name nets.
    for spec, m in zip(lm["metals"], metals):
        ti = ly.find_layer(spec[0], lm["label_dt"])
        if ti is not None:
            tl = l2n.make_text_layer(ti, f"txt{spec[0]}")
            l2n.connect(m, tl)
    nl = K.finalize(l2n)
    top_ckt = None
    for c in nl.each_circuit():
        if c.name.lower() == top.lower():
            top_ckt = c; break
    if top_ckt is None:
        top_ckt = nl.top_circuit()
    lm_pwr = {"vdd_rail_marker": lm["vdd_marker"], "vss_rail_marker": lm["vss_marker"]}
    shorts, locs = K.assign_power_by_geometry(l2n, ly, top_ckt, lm_pwr, pya)
    return l2n, nl, top_ckt, shorts, locs


def _resolve_cdl_paths(golden_cdl, golden_cdl_dir):
    """Return the list of CDL golden files. A single `--golden-cdl` file, or every
    `*.cdl` under `--golden-cdl-dir` (all VT/SRAM flavors — the gate netlist may mix
    them; unused subckts are stripped by the comparer's stray-circuit purge)."""
    if golden_cdl:
        return [golden_cdl]
    if golden_cdl_dir and os.path.isdir(golden_cdl_dir):
        return sorted(os.path.join(golden_cdl_dir, f)
                      for f in os.listdir(golden_cdl_dir) if f.endswith(".cdl"))
    return []


def build_golden_netlist(gate_verilog, cdl_paths, out):
    """Expand a gate netlist into a device-level GOLDEN by substituting each std-cell
    instance's CDL .SUBCKT (via gate_verilog_to_spice). `cdl_paths` = one or more CDL
    files; multiple are concatenated so any VT/SRAM flavor resolves. Deterministic and
    pya-FREE -> unit-testable outside the container. Returns the golden SPICE path."""
    G = _import_gate_verilog_to_spice()
    if not cdl_paths:
        raise RuntimeError("no CDL golden supplied (--golden-cdl / --golden-cdl-dir)")
    if len(cdl_paths) == 1:
        cells = cdl_paths[0]
    else:
        cells = out + ".cells.cdl"
        with atomic_writing(cells) as f:
            for p in cdl_paths:
                f.write(open(p).read())
                f.write("\n")
    G.convert(gate_verilog, cells, out)
    return out


def cmd_design(pya, gds, top, gate_netlist, golden_cdl, golden_cdl_dir,
               def_file, power, ground, out_dir):
    """Design-level LVS: routed GDS vs the CDL-expanded gate netlist. Emits
    `A7_DESIGN_LVS {json}` and returns the verdict dict."""
    K = _import_klayout_pdk_lvs()
    out_dir = out_dir or os.path.dirname(os.path.abspath(gds))
    os.makedirs(out_dir, exist_ok=True)
    cdl_paths = _resolve_cdl_paths(golden_cdl, golden_cdl_dir)
    # 1. restore top-port + power labels from the routed DEF (when available)
    src_gds = gds
    n_pins, rails = 0, []
    if def_file and os.path.isfile(def_file):
        labeled = os.path.join(out_dir, f"{top}_labeled.gds")
        n_pins, rails = restore_design_labels(pya, gds, def_file, labeled)
        src_gds = labeled
    # 2. extract the routed design -> layout SPICE (named ports + geometric rails)
    l2n, nl, top_ckt, shorts, locs = extract_design(
        pya, src_gds, top, threads=(os.cpu_count() or 4))
    lay_sp = os.path.join(out_dir, f"{top}_design_layout.spice")
    K.write_named_spice(nl, lay_sp)
    # 3. build the device-level golden from the gate netlist + CDL
    gold_sp = os.path.join(out_dir, f"{top}_design_golden.spice")
    build_golden_netlist(gate_netlist, cdl_paths, gold_sp)
    # 4. compare (flatten both, NetlistComparer) — reuse the proven prep path
    ok, nl_l, nl_s, mm = _compare(pya, K, lay_sp, gold_sp, top, power, ground)
    ps = shorts not in (None, 0, -1)
    verdict = "MATCH" if (ok and not ps) else "MISMATCH"
    res = {"top": top, "verdict": verdict,
           "layout_devices": nl_l, "golden_devices": nl_s,
           "mismatch_msgs": mm, "power_shorts": shorts,
           "power_short_locations": locs,
           "restored_pin_labels": n_pins, "restored_rails": rails,
           "layout_spice": os.path.basename(lay_sp),
           "golden_spice": os.path.basename(gold_sp),
           "method": "klayout_finfet_geometric_design_extract + NetlistComparer",
           "disclosure": ("ASAP7 predictive PDK (tapeout_capable=false). Reads only "
                          "the routed layout GDS + gate netlist + CDL golden (§4.05). "
                          "A folded multi-finger drive cell may still MISMATCH (the "
                          "disclosed library residual). NOT silicon-proven.")}
    print("A7_DESIGN_LVS " + json.dumps(res))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="ASAP7 FinFET device-level LVS")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pe = sub.add_parser("extract"); pe.add_argument("gds"); pe.add_argument("--cell", required=True)
    pe.add_argument("--out"); pe.add_argument("--power", default="VDD"); pe.add_argument("--ground", default="VSS")
    pc = sub.add_parser("compare"); pc.add_argument("gds"); pc.add_argument("--cell", required=True)
    pc.add_argument("--golden-cdl", required=True); pc.add_argument("--out")
    pc.add_argument("--power", default="VDD"); pc.add_argument("--ground", default="VSS")
    pb = sub.add_parser("batch"); pb.add_argument("gds"); pb.add_argument("--golden-cdl", required=True)
    pb.add_argument("--json"); pb.add_argument("--power", default="VDD"); pb.add_argument("--ground", default="VSS")
    pd = sub.add_parser("design", help="design-level LVS: routed GDS vs CDL-expanded gate netlist (#182)")
    pd.add_argument("gds"); pd.add_argument("--top", required=True)
    pd.add_argument("--gate-netlist", required=True, dest="gate_netlist")
    pd.add_argument("--golden-cdl"); pd.add_argument("--golden-cdl-dir", dest="golden_cdl_dir")
    pd.add_argument("--def", dest="def_file", help="routed DEF for top-port + rail label restore")
    pd.add_argument("--out-dir", dest="out_dir")
    pd.add_argument("--power", default="VDD"); pd.add_argument("--ground", default="VSS")
    a = ap.parse_args(argv)
    pya = _require_pya()
    if a.cmd == "extract":
        l2n, nl, ckt = extract_cell(pya, a.gds, a.cell, power=a.power, ground=a.ground)
        txt, ndev = emit_subckt(ckt, a.cell, a.power, a.ground, a.out)
        sys.stderr.write(f"[extract] {a.cell}: {ndev} device(s)\n")
        print(txt)
        return 0
    if a.cmd == "compare":
        r = cmd_compare_one(pya, a.gds, a.cell, a.golden_cdl, a.power, a.ground, a.out)
        return 0 if r.get("verdict") == "MATCH" else 4
    if a.cmd == "batch":
        cmd_batch(pya, a.gds, a.golden_cdl, a.power, a.ground, a.json)
        return 0
    if a.cmd == "design":
        r = cmd_design(pya, a.gds, a.top, a.gate_netlist, a.golden_cdl,
                       a.golden_cdl_dir, a.def_file, a.power, a.ground, a.out_dir)
        return 0 if r.get("verdict") == "MATCH" else 4
    return 2


if __name__ == "__main__":
    sys.exit(main())
