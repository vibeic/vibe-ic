#!/usr/bin/env python3
"""gate_verilog_to_spice — convert a structural (gate-level) Verilog netlist to SPICE for
netgen LVS against a KLayout-extracted layout netlist.

Chip-AGNOSTIC and deterministic (no LLM). Reads a structural Verilog netlist + a SPICE cell
library (to learn each cell's pin ORDER) and emits `.subckt <top> <ports>` with one
`X<inst> <nets> <cell>` per instance. Handles the three things that otherwise break a
verilog-vs-spice LVS on a post-PnR netlist:
  * bus expansion (`input [31:0] x` -> x.0 .. x.31; `x[3]` -> `x.3` consistently);
  * `assign a = b;` aliases (a port driven through a wire alias -> the port net is connected);
  * unconnected cell power pins tie to global VDD/VSS (emits `.GLOBAL VDD VSS`).

Pair with `klayout_pdk_lvs.py` (layout + cell-library SPICE) and run:
  netgen -batch lvs "layout.spice <top>" "<this-output> <top>" setup.tcl report

CLI:
  gate_verilog_to_spice.py --verilog spm_pnr.v --cells cells.spice --out source.spice
Pure Python; no external deps.
"""
import sys, re, argparse
from _atomic_artefact import writing as atomic_writing  # vibe-ic#1082 (helper from PR #1094)

# Supply-net names that are GLOBAL (`.GLOBAL VDD VSS`) and must NOT be emitted as
# subckt ports (the layout extraction treats power as global-only). Exact set +
# clear prefixes; a real functional signal effectively never starts with these.
_SUPPLY_EXACT = frozenset(("VDD", "VSS", "VPWR", "VGND", "VCC", "VEE", "GND",
                           "VBB", "VNB", "VPB", "AVDD", "AVSS", "DVDD", "DVSS"))
_SUPPLY_PREFIXES = ("VDD", "VSS", "VPWR", "VGND", "VCC", "VEE",
                    "AVDD", "AVSS", "DVDD", "DVSS")


def _is_supply_port(name):
    n = (name or "").upper()
    return n in _SUPPLY_EXACT or n.startswith(_SUPPLY_PREFIXES)


def parse_cell_pins(spice_text):
    """cell name -> ordered pin list (from .SUBCKT lines)."""
    return {m.group(1): m.group(2).split()
            for m in re.finditer(r"(?im)^\.subckt\s+(\S+)\s+(.*)$", spice_text)}


def norm(net):
    net = net.strip()
    if net in ("1'b0", "1'B0"):
        return "VSS"
    if net in ("1'b1", "1'B1"):
        return "VDD"
    # Verilog escaped identifier + bit-select. A yosys gate netlist writes a
    # bit-select on an ESCAPED bus as `\name [N]`: per Verilog LRM the escaped id
    # runs `\` + non-whitespace until whitespace TERMINATES it, and the trailing
    # `[N]` is the bit-select that BELONGS to the net. That terminator space is
    # not outer whitespace, so `.strip()` leaves it in the MIDDLE of the name;
    # `[->.` then yields `\name .N` and `' '.join(nets)` splits the ONE net into
    # TWO SPICE tokens, giving the cell call an extra node ("Too many parameters
    # in call in <cell>"). Collapse whitespace sitting between an escaped id and
    # its bit-select so `\a.b.c [N]` normalizes to the single node `\a.b.c.N`,
    # identical in form to an ordinary `bus[N]` -> `bus.N`. Chip-AGNOSTIC: pure
    # Verilog/SPICE syntax. Ordinary nets (no leading `\`) are byte-unchanged.
    if net.startswith("\\"):
        net = re.sub(r"\s+(\[\d)", r"\1", net)
    return net.replace("[", ".").replace("]", "")


def parse_verilog(vtext):
    vtext = re.sub(r"//[^\n]*", "", vtext)
    vtext = re.sub(r"/\*.*?\*/", "", vtext, flags=re.S)
    mm = re.search(r"module\s+(\w+)\s*\((.*?)\)\s*;(.*)endmodule", vtext, re.S)
    top, body = mm.group(1), mm.group(3)

    alias = {}
    for am in re.finditer(r"\bassign\s+([^=;]+?)\s*=\s*([^;]+?)\s*;", body):
        alias[norm(am.group(2))] = norm(am.group(1))

    def resolve(n):
        seen = set()
        while n in alias and n not in seen:
            seen.add(n); n = alias[n]
        return n

    ports = []
    for m in re.finditer(r"\b(input|output|inout)\b\s*(?:\[(\d+):(\d+)\])?\s*([\w,\s]+?);", body):
        hi, lo = m.group(2), m.group(3)
        for nm in m.group(4).replace("\n", " ").split(","):
            nm = nm.strip()
            if not nm:
                continue
            if hi is not None:
                for i in range(max(int(hi), int(lo)), min(int(hi), int(lo)) - 1, -1):
                    ports.append(f"{nm}.{i}")
            else:
                ports.append(nm)
    ports = [resolve(p) for p in ports]
    # v1.3.93 — VDD/VSS are GLOBAL (`.GLOBAL VDD VSS`); a global net must NOT also
    # be a subckt PORT. The routed gate netlist carries PDN-added VDD/VSS module
    # ports, but the KLayout layout extraction treats power as global-only (no
    # power ports), so leaving them here gives the netgen SOURCE side 2 extra
    # ports -> "Top level cell failed pin matching". Drop supply-named ports (they
    # stay connected via .GLOBAL). Chip-AGNOSTIC name match.
    ports = [p for p in ports if not _is_supply_port(p)]

    insts = []
    for m in re.finditer(r"\b([A-Z]\w+)\s+(\S+)\s*\(([^;]*?)\)\s*;", body, re.S):
        cell, inst, conns = m.group(1), m.group(2), m.group(3)
        pinmap = {}
        for pm in re.finditer(r"\.(\w+)\s*\(\s*([^)]*?)\s*\)", conns):
            pinmap[pm.group(1)] = resolve(norm(pm.group(2))) if pm.group(2).strip() else None
        insts.append((cell, inst, pinmap))
    return top, ports, insts


def convert(vfile, cellspice, out, include_cells=True):
    cell_pins = parse_cell_pins(open(cellspice).read())
    top, ports, insts = parse_verilog(open(vfile).read())

    lines = ["* gate_verilog_to_spice (netgen LVS source side)", ".GLOBAL VDD VSS"]
    if include_cells:
        lines.append(f".include {cellspice}")
    lines.append("")
    lines.append(f".SUBCKT {top} {' '.join(ports)}")
    dangle = [0]
    unknown = set()
    n_emit = 0
    for cell, inst, pinmap in insts:
        order = cell_pins.get(cell)
        if order is None:
            unknown.add(cell)
            continue
        nets = []
        for pin in order:
            if pin in pinmap and pinmap[pin]:
                nets.append(pinmap[pin])
            elif pin in ("VDD", "VSS"):
                nets.append(pin)
            else:
                dangle[0] += 1
                nets.append(f"DANGLE_{dangle[0]}")
        lines.append(f"X{inst} {' '.join(nets)} {cell}")
        n_emit += 1
    lines.append(".ENDS")
    lines.append("")
    with atomic_writing(out) as f:
        f.write("\n".join(lines))
    print(f"wrote {out}: top={top} ports={len(ports)} instances_emitted={n_emit}")
    if unknown:
        print(f"  NOTE cells not in library (device-less fill?): {sorted(unknown)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--verilog", required=True)
    ap.add_argument("--cells", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    return convert(a.verilog, a.cells, a.out)


if __name__ == "__main__":
    sys.exit(main())
