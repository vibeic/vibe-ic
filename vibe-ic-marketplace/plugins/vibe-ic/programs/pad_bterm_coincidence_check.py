#!/usr/bin/env python3
"""pad_bterm_coincidence_check — is a chip-top signal BTerm ACTUALLY on its
pad's bond terminal? Measured per net, never declared for a class of nets.

DEF pins declared USE POWER or GROUND belong to the routed power grid. Their
BTerms can land on straps away from the pad, so direct bond-terminal overlap
does not establish their connectivity. They are outside this signal-routing
check and are never added to its connected-net exclusions.

WHY THIS PROGRAM EXISTS
=======================
On a padframed die the port net terminates ON the bond pad: there is no wire
from a die-edge pin to the pad, and the detailed router cannot make one.
MEASURED on one open 5 V IO library: the pad's OWN obstruction fully covers its
bond terminal's footprint on the three layers BELOW it (M2, M3, M4 over a
terminal on M5), so no via can land under any candidate access point and
TritonRoute reports `DRT-0073 No access point` once per padded port — 38 of
them on one chip-path run, after which detailed routing produced nothing and
the streamout was 106 bytes. The obstruction is the VENDOR's: this flow reads
the library LEF unmodified (measured: 118 OBS boxes in the database, the same
118 in the vendor file, set-identical), and a bond pad forbidding routing under
itself is what an IO cell is FOR.

So the connection is real and the router must not be asked to make it. That is
one step away from switching a check off, and the difference is this program:

  A NET IS EXCLUDED ONLY IF THIS PROGRAM MEASURED THE CONNECTION.
  Same layer, and an overlap at least as wide and as tall as that layer's own
  minimum width — a touch of one database unit is not a conductor.

  IT ANSWERS PER NET. A design where 35 ports sit on their pads and one does
  not gets 35 exclusions and one net still routed, still failing loudly.

  IT MEASURES THE DEF, not the producer's record. The producer that placed the
  BTerm is not the witness that it landed: the geometry is re-derived here from
  the DEF's own PINS and COMPONENTS plus the master's LEF pin rectangles,
  transformed by the instance's own orientation.

WHAT A CONSUMER MAY DO WITH IT, AND WHAT IT MAY NOT
===================================================
A consumer may exclude a `CONNECTED` net from signal routing. It may NOT
exclude a net this program reports `NOT_CONNECTED` or `UNDECIDED`, and it may
not exclude "the port nets" as a class. A net whose BTerm is moved off its pad
by one layer or one micron comes back as NOT_CONNECTED and must go back into
the router — that is the control this program exists to make possible.

Exit codes: 0 every net decided (whatever the verdicts), 1 a net could not be
decided, 2 nothing to decide (no pad terminal in this DEF).
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _atomic_artefact import write_json as atomic_write_json

import _pad_ring as PR
import _source_record_merge as _srm     # noqa: E402

PROGRAM = "pad_bterm_coincidence_check"
SCHEMA = "vibe-ic/pad_bterm_coincidence/1"
REPORT_REL = "reports/phase3/pad_bterm_coincidence.json"

#: DEF PIN entry: name, its net, and the PORT geometry it was placed with.
_PIN_RE = re.compile(
    r"^-\s+(?P<name>\S+)\s+\+\s+NET\s+(?P<net>\S+)(?P<tail>.*)$", re.S)
_LAYER_RE = re.compile(
    r"\+\s*LAYER\s+(?P<layer>\S+)\s*\(\s*(?P<x1>-?\d+)\s+(?P<y1>-?\d+)\s*\)"
    r"\s*\(\s*(?P<x2>-?\d+)\s+(?P<y2>-?\d+)\s*\)")
_PLACE_RE = re.compile(
    r"\+\s*(?:PLACED|FIXED|COVER)\s*\(\s*(?P<x>-?\d+)\s+(?P<y>-?\d+)\s*\)"
    r"\s*(?P<orient>\w+)")
#: DEF NETS entry: the net name and every ( instance pin ) pair on it.
_NET_RE = re.compile(r"^-\s+(?P<name>\S+)(?P<tail>.*)$", re.S)
_CONN_RE = re.compile(r"\(\s*(?P<inst>[^\s()]+)\s+(?P<pin>[^\s()]+)\s*\)")
#: Tech LEF: a routing layer's own minimum width.
_TECH_LAYER_RE = re.compile(r"^\s*LAYER\s+(\S+)", re.M)
_TECH_WIDTH_RE = re.compile(r"^\s*WIDTH\s+([0-9.]+)\s*;", re.M)


def layer_min_widths(text: str, units: int) -> Dict[str, int]:
    """`{layer: minimum width in DEF units}` from a tech LEF."""
    out: Dict[str, int] = {}
    hits = list(_TECH_LAYER_RE.finditer(text))
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        w = _TECH_WIDTH_RE.search(text, m.end(), end)
        if w:
            out[m.group(1)] = int(round(float(w.group(1)) * units))
    return out


def def_pins(text: str) -> Dict[str, Dict[str, Any]]:
    """`{pin: {net, use, layer, rect}}` in absolute DEF units."""
    out: Dict[str, Dict[str, Any]] = {}
    for entry in PR._section(text, "PINS").split(";"):
        entry = entry.strip()
        m = _PIN_RE.match(entry)
        if not m:
            continue
        use = re.search(r"\+\s+USE\s+(\w+)\b", m.group("tail"))
        rec: Dict[str, Any] = {"net": m.group("net"),
                               "use": use.group(1).upper() if use else None, "layer": None,
                               "rect": None, "placement": None}
        lay = _LAYER_RE.search(m.group("tail"))
        pl = _PLACE_RE.search(m.group("tail"))
        if lay and pl:
            ox, oy = int(pl.group("x")), int(pl.group("y"))
            rec["layer"] = lay.group("layer")
            rec["placement"] = [ox, oy, pl.group("orient")]
            rec["rect"] = [ox + int(lay.group("x1")), oy + int(lay.group("y1")),
                           ox + int(lay.group("x2")), oy + int(lay.group("y2"))]
        out[m.group("name")] = rec
    return out


def def_net_terminals(text: str) -> Dict[str, List[Tuple[str, str]]]:
    """`{net: [(instance, pin), ...]}` for every instance terminal on it.

    Both NETS and SPECIALNETS: OpenROAD's `place_io_terminals` (LibreLane
    OpenROAD.PadRing) writes each port net it lands on a pad as a SPECIAL net,
    `- clk ( PIN clk ) ( u_pad_clk PAD ) + USE SIGNAL ;`. MEASURED on the spm
    PadRing DEF: all 36 port nets were there and none in NETS, so reading NETS
    alone found 0 ports on a pad. A wildcard `( * pin )` connects that pin
    on every component whose master carries it; run() expands it after reading
    the library pin ports. SUBNET connections also belong to the parent net;
    routing-attribute coordinates are geometry, not terminal connections.
    """
    out: Dict[str, List[Tuple[str, str]]] = {}
    for section in ("NETS", "SPECIALNETS"):
        for entry in PR._section(text, section).split(";"):
            entry = entry.strip()
            m = _NET_RE.match(entry)
            if not m:
                continue
            attributes = re.split(r"\s+\+", m.group("tail"))
            connections = " ".join([attributes[0]] + [part for part in attributes[1:]
                                    if re.match(r"\s*SUBNET\b", part)])
            conns = [(c.group("inst"), c.group("pin"))
                     for c in _CONN_RE.finditer(connections)
                     if c.group("inst") != "PIN"]
            out[m.group("name")] = out.get(m.group("name"), []) + conns
    return out


def def_net_uses(text: str) -> Dict[str, str]:
    out = {}
    for section in ('NETS', 'SPECIALNETS'):
        for entry in PR._section(text, section).split(';'):
            m = _NET_RE.match(entry.strip())
            if m:
                use = re.search(r'\+\s+USE\s+(\w+)\b', m.group('tail'))
                if use:
                    out[m.group('name')] = use.group(1).upper()
    return out


def _overlap(a: List[int], b: List[int]) -> Optional[List[int]]:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    return [x1, y1, x2, y2] if x2 > x1 and y2 > y1 else None


def decide(pin_rec: Dict[str, Any], term_layer: str, term_rect: List[int],
           min_width: Optional[int]) -> Tuple[str, str, Optional[List[int]]]:
    """(verdict, reason, overlap). The whole judgement, in one place."""
    if pin_rec.get("rect") is None:
        return ("UNDECIDED",
                "the DEF places this pin with no LAYER rectangle, so where it "
                "is cannot be compared with anything", None)
    if pin_rec["layer"] != term_layer:
        return ("NOT_CONNECTED",
                f"the pin is on {pin_rec['layer']} and the pad terminal is on "
                f"{term_layer}; two shapes on different layers do not touch",
                None)
    ov = _overlap(pin_rec["rect"], term_rect)
    if ov is None:
        return ("NOT_CONNECTED",
                f"the pin {pin_rec['rect']} and the pad terminal {term_rect} "
                f"do not overlap on {term_layer}", None)
    w, h = ov[2] - ov[0], ov[3] - ov[1]
    if min_width is None:
        return ("UNDECIDED",
                f"the overlap is {w}x{h} but the tech LEF states no minimum "
                f"width for {term_layer}, so 'wide enough to conduct' cannot "
                f"be answered", ov)
    if w < min_width or h < min_width:
        return ("NOT_CONNECTED",
                f"the overlap is {w}x{h} and {term_layer}'s minimum width is "
                f"{min_width}; a touch narrower than the layer's own minimum "
                f"is not a conductor", ov)
    return ("CONNECTED",
            f"the pin and the pad terminal share {w}x{h} of {term_layer}, "
            f"at or above that layer's minimum width {min_width}", ov)


def run(def_text: str, tech_text: str, io_lefs: List[Path]
        ) -> Tuple[int, Dict[str, Any]]:
    dfn = PR.parse_def(def_text)
    pins = def_pins(def_text)
    nets = def_net_terminals(def_text)
    widths = layer_min_widths(tech_text, dfn.units)
    uses = def_net_uses(def_text)

    # Grouped, not folded in arrival order. `dict.update` over the discovered
    # LEFs is a last-wins merge: a library that names a macro but lists no
    # pin ports for it would erase the library that listed them, and which
    # one wins would be whatever order the discovery walk returned. An
    # unreadable LEF is silence too, which is why it is passed through as
    # `None` rather than special-cased.
    def _parsed(fn):
        out = []
        for lef in io_lefs:
            try:
                out.append(fn(lef.read_text(errors="replace")))
            except OSError:
                out.append(None)
        return out

    pin_ports, _pp_conf = _srm.merge_source_records(
        _parsed(PR.parse_lef_pin_ports), on_conflict="richer")
    sizes, _sz_conf = _srm.merge_source_records(
        _parsed(PR.parse_lef_macros), on_conflict="richer")
    classes, _cl_conf = _srm.merge_source_records(
        _parsed(PR.parse_lef_macro_classes), on_conflict="richer")
    conflicting_classes = {conflict["key"] for conflict in _cl_conf}

    def terminal_row(pin_name, rec, inst, tpin, comp):
        rects = pin_ports[comp.master][tpin]
        size = sizes.get(comp.master)
        if size is None or comp.x is None or comp.orient is None:
            return {"pin": pin_name, "net": rec["net"], "instance": inst,
                    "terminal": tpin, "verdict": "UNDECIDED",
                    "reason": "the DEF does not place this pad, or its "
                              "master has no LEF SIZE, so the terminal's "
                              "absolute position is unknown"}
        best: Tuple[str, str, Optional[List[int]], Optional[List[int]]] = (
            "NOT_CONNECTED", "no rectangle of the terminal matched", None, None)
        for layer, r in rects:
            try:
                x1, y1, x2, y2 = PR.orient_rect(r, comp.orient, size)
            except KeyError:
                best = ("UNDECIDED",
                        f"the pad is placed {comp.orient!r}, an orientation "
                        f"this program cannot map", None, None)
                break
            abs_rect = [comp.x + int(round(x1 * dfn.units)),
                        comp.y + int(round(y1 * dfn.units)),
                        comp.x + int(round(x2 * dfn.units)),
                        comp.y + int(round(y2 * dfn.units))]
            verdict, reason, ov = decide(rec, layer, abs_rect,
                                         widths.get(layer))
            if best[0] == "CONNECTED":
                continue
            if verdict == "CONNECTED" or best[0] != "UNDECIDED":
                best = (verdict, reason, ov, abs_rect)
        return {
            "pin": pin_name, "net": rec["net"], "instance": inst,
            "terminal": tpin, "master": comp.master, "orient": comp.orient,
            "pin_layer": rec["layer"], "pin_rect": rec["rect"],
            "terminal_rect": best[3], "overlap": best[2],
            "verdict": best[0], "reason": best[1]}

    # DEF wildcard connectivity is instance-pin connectivity, independent of
    # declaration intent. Index only pins actually present in the read LEFs.
    component_pins: Dict[str, List[Tuple[str, str]]] = {}
    for inst, comp in dfn.components.items():
        for pin in pin_ports.get(comp.master, {}):
            component_pins.setdefault(pin, []).append((inst, pin))

    rows: List[Dict[str, Any]] = []
    routed_supply_pins = []
    rank = {"NOT_CONNECTED": 0, "UNDECIDED": 1, "CONNECTED": 2}
    for pin_name, rec in sorted(pins.items()):
        use = rec["use"] or uses.get(rec["net"])
        if use in ("POWER", "GROUND"):
            routed_supply_pins.append({"pin": pin_name, "net": rec["net"], "use": use,
                                       "source": "DEF PINS USE" if rec["use"] else "DEF net USE"})
            continue
        candidates = []
        for inst, pin in nets.get(rec["net"], []):
            candidates.extend(component_pins.get(pin, []) if inst == "*"
                              else [(inst, pin)])
        chosen = None
        for inst, pin in dict.fromkeys(candidates):
            comp = dfn.components.get(inst)
            if comp is None or pin not in pin_ports.get(comp.master, {}):
                continue
            if (comp.master in conflicting_classes
                    or classes.get(comp.master, "").partition(" ")[0] != "PAD"):
                continue
            row = terminal_row(pin_name, rec, inst, pin, comp)
            if chosen is None or rank[row["verdict"]] > rank[chosen["verdict"]]:
                chosen = row
            # Connectivity only supplies candidates. Coincidence decides which
            # pad actually carries this signal BTerm.
            if row["verdict"] == "CONNECTED":
                break
        if chosen is not None:
            rows.append(chosen)

    connected = [r["net"] for r in rows if r["verdict"] == "CONNECTED"]
    undecided = [r for r in rows if r["verdict"] == "UNDECIDED"]
    report = {
        "schema": SCHEMA, "program": PROGRAM,
        "design": dfn.design, "units": dfn.units,
        "layer_min_widths": widths,
        "n_ports_on_a_pad": len(rows),
        "connected_nets": sorted(connected),
        "not_connected_nets": sorted(r["net"] for r in rows
                                     if r["verdict"] == "NOT_CONNECTED"),
        "undecided_nets": sorted(r["net"] for r in undecided),
        "nets": rows,
        "routed_supply_pins": routed_supply_pins,
        "consumer_contract": (
            "This check measures signal bond-terminal coincidence. Declared "
            "POWER/GROUND pins are listed in routed_supply_pins; their routed "
            "grid connectivity is outside this check. "
            "A consumer may exclude a net from signal routing ONLY if it "
            "appears in `connected_nets`. `not_connected_nets` and "
            "`undecided_nets` must stay in the router, and a consumer that "
            "excludes a class of nets rather than these names is switching "
            "the check off."),
    }
    if not rows:
        return 2, report
    return (1 if undecided else 0), report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--def", dest="def_path", default=None,
                    help=f"DEF to measure (default {PR.PADRING_DEF_REL})")
    ap.add_argument("--tech-lef", required=True,
                    help="the tech LEF whose layer WIDTH records decide "
                         "'wide enough to conduct'")
    ap.add_argument("--io-lef", action="append", default=None)
    ap.add_argument("--pdk-root", default=None)
    ap.add_argument("--pdk", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    def_path = (Path(args.def_path) if args.def_path
                else project / PR.PADRING_DEF_REL)
    if not def_path.is_absolute():
        def_path = project / def_path
    io_lefs = ([Path(p) for p in args.io_lef] if args.io_lef
               else PR.discover_io_lefs(args.pdk_root, args.pdk))
    if not def_path.is_file():
        print(f"[{PROGRAM}] no DEF at {def_path}", file=sys.stderr)
        return 2
    rc, report = run(def_path.read_text(errors="replace"),
                     Path(args.tech_lef).read_text(errors="replace"), io_lefs)
    report["def"] = str(def_path)
    dest = Path(args.json) if args.json else (project / REPORT_REL)
    if not dest.is_absolute():
        dest = project / dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(dest, report)
    print(f"=== {PROGRAM} ({project.name}) ===")
    print(f"  {report['n_ports_on_a_pad']} port(s) sit on a pad terminal: "
          f"{len(report['connected_nets'])} CONNECTED, "
          f"{len(report['not_connected_nets'])} NOT_CONNECTED, "
          f"{len(report['undecided_nets'])} UNDECIDED")
    for row in report["nets"]:
        if row["verdict"] != "CONNECTED":
            print(f"  {row['verdict']}: {row['net']} — {row['reason']}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
