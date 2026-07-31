#!/usr/bin/env python3
"""_dft_netlist_ports.py — PURE netlist port helpers shared by the DFT tools.

`fault chain` AND `fault atpg` (AUCOHL/Fault `Module.Port.extract`) classify
every module port as strictly `.input` or `.output`; a Verilog `inout`
declaration matches NEITHER branch, so the invariant `ports == inputs + outputs`
fails and the tool aborts at port classification:

    chain.swift / atpg: Fatal error: ... RuntimeError("Some ports in <top> are
    not properly declared as an input or output.")

Every pad-ring / wrapper / analog-bearing top with a bidirectional port hits
this and silently loses its scan chain and its ATPG coverage (as a "disclosed
capability gap").  An `inout` port that carries NO scannable logic (an analog
pass-through, an unbonded pad) can be REMOVED from the netlist the fault tools
read — losslessly, because the chain/cut never touch it — and, where the tool's
output is a shippable netlist, RESTORED byte-for-byte afterwards.

`fault_scan_chain_insert.py` (scan insertion) restores the port into its
published netlist; `fault_atpg_run.py` (the ATPG cut) does not need to — the cut
netlist is a fault-sim intermediate, never built — but both must first STRIP the
inout port so the tool can parse the module at all.  These helpers are the ONE
implementation both consume, unit-tested directly with no Docker.

Measured on caravel_user_project x sky130A (fault 0.9.4): the synthesised
`user_project_wrapper` carries `inout [28:0] analog_io;` — the only inout — and
it is unconnected (a pure analog pass-through).  With it stripped, `fault chain`
builds a 33-flop scan chain and `fault atpg` measures stuck-at coverage; with it
present both abort at chain.swift:578 / atpg with the RuntimeError above.
"""
from __future__ import annotations

import re

_INOUT_DECL_RE = re.compile(
    r"^[ \t]*inout[ \t]+(?:(?:wire|reg|logic)[ \t]+)?"
    r"(?:\[[^\]]*\][ \t]*)?([A-Za-z_][A-Za-z0-9_$]*)[ \t]*;[ \t]*$", re.M)


def find_inout_ports(netlist_text: str) -> dict:
    """`{name: exact declaration line}` for every `inout` port.  PURE.

    Targets the yosys NON-ANSI netlist form (one `inout ... name;` per line),
    the only form the fault tools ever receive — they run on the synth /
    tech-mapped netlist, never on ANSI-header RTL.
    """
    return {m.group(1): m.group(0).strip()
            for m in _INOUT_DECL_RE.finditer(netlist_text or "")}


def port_is_connected(netlist_text: str, name: str) -> bool:
    """True if `name` is used beyond its port-list entry and declaration lines —
    a real net that must NOT be stripped.  PURE.

    Whole-identifier match, so an indexed bit-select `name[3]` counts as a use.
    Subtract the single module-header port-list mention and the
    `inout`/`wire`/`reg`/`logic` declaration lines; anything left is a real
    connection.
    """
    word = re.compile(r"(?<![A-Za-z0-9_$])" + re.escape(name)
                      + r"(?![A-Za-z0-9_$])")
    total = len(word.findall(netlist_text or ""))
    decls = len(re.findall(
        r"^[ \t]*(?:inout|wire|reg|logic)[ \t]+(?:\[[^\]]*\][ \t]*)?"
        + re.escape(name) + r"[ \t]*;[ \t]*$", netlist_text or "", re.M))
    return (total - decls - 1) > 0     # -1 for the port-list entry itself


def port_list_successor(netlist_text: str, name: str) -> str | None:
    """The port name that FOLLOWS `name` in the module header port list, or None
    if `name` is last / not found.  Used to restore a stripped port to its exact
    original position.  PURE.
    """
    m = re.search(r"^module\s+[A-Za-z_][A-Za-z0-9_$]*\s*\((.*?)\)\s*;",
                  netlist_text or "", re.M | re.S)
    if not m:
        return None
    names = [p.strip() for p in m.group(1).split(",") if p.strip()]
    try:
        i = names.index(name)
    except ValueError:
        return None
    return names[i + 1] if i + 1 < len(names) else None


def strip_inout_ports(netlist_text: str, names) -> str:
    """Remove each port in `names` from the module header port list and drop its
    `inout`/`wire` declaration lines.  Header surgery is confined to the
    module-header span.  PURE.
    """
    text = netlist_text
    hdr_re = re.compile(r"^module\s+[A-Za-z_][A-Za-z0-9_$]*\s*\(.*?\)\s*;",
                        re.M | re.S)
    for name in names:
        text = re.sub(
            r"^[ \t]*(?:inout|wire)[ \t]+(?:\[[^\]]*\][ \t]*)?"
            + re.escape(name) + r"[ \t]*;[ \t]*\n", "", text, flags=re.M)
        hdr = hdr_re.search(text)
        if not hdr:
            continue
        span = hdr.group(0)
        span2 = re.sub(r"(?<![A-Za-z0-9_$])" + re.escape(name)
                       + r"(?![A-Za-z0-9_$])[ \t]*,[ \t]*", "", span, count=1)
        if span2 == span:
            span2 = re.sub(r",[ \t]*(?<![A-Za-z0-9_$])" + re.escape(name)
                           + r"(?![A-Za-z0-9_$])(?=[ \t]*\))", "", span, count=1)
        text = text[:hdr.start()] + span2 + text[hdr.end():]
    return text


def restore_inout_ports(chained_text: str, decls: dict,
                        successors: dict) -> str:
    """Re-insert stripped inout ports into a fault tool's output netlist.

    Each name goes back into the module header port list (before its original
    successor port, else before the closing paren) and its exact declaration
    line is re-added right after the header.  ALL header surgery is confined to
    the module-header span, so an identifier that ALSO appears in fault's
    `/* FAULT METADATA ... */` comment can never be hit by mistake.  PURE.
    """
    hdr = re.compile(r"^module\s+[A-Za-z_][A-Za-z0-9_$]*\s*\(.*?\)\s*;",
                     re.M | re.S)
    m = hdr.search(chained_text)
    if not m:
        return chained_text
    header = m.group(0)
    decl_block = ""
    for name, decl in decls.items():
        succ = successors.get(name)
        anchor = (re.compile(r"(?<![A-Za-z0-9_$])(" + re.escape(succ)
                             + r")(?![A-Za-z0-9_$])") if succ else None)
        if anchor and anchor.search(header):
            header = anchor.sub(name + ", " + r"\1", header, count=1)
        else:
            header = re.sub(r"\)\s*;\s*$", ", " + name + ");", header, count=1)
        decl_block += "\n  " + decl.strip()
    return chained_text[:m.start()] + header + decl_block + chained_text[m.end():]
