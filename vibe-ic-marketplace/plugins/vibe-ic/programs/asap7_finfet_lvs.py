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
        with open(out, "w") as f:
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


def cmd_compare_one(pya, gds, cell, golden_cdl, power, ground, out=None):
    K = _import_klayout_pdk_lvs()
    blocks = split_cdl_subckts(golden_cdl)
    if cell not in blocks:
        return {"cell": cell, "verdict": "NO_GOLDEN"}
    l2n, nl, ckt = extract_cell(pya, gds, cell, power=power, ground=ground)
    lay_txt, ndev = emit_subckt(ckt, cell, power, ground, None)
    lay_path = (out or f"/tmp/_a7_{cell}") + ".lay.spice"
    src_path = (out or f"/tmp/_a7_{cell}") + ".src.spice"
    with open(lay_path, "w") as f:
        f.write(lay_txt)
    with open(src_path, "w") as f:
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
        with open(lay_path, "w") as f:
            f.write(lay_txt)
        with open(src_path, "w") as f:
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
    return 2


if __name__ == "__main__":
    sys.exit(main())
