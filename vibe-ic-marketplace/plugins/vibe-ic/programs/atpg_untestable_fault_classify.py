#!/usr/bin/env python3
"""atpg_untestable_fault_classify.py — which stuck-at faults NO test can detect.

WHY (vibe-ic#603)
=================
The OSS Fault engine reports RAW FAULT coverage, `detected / total_faults`.
Professional ATPG sign-off reports TEST coverage, `detected / (total -
untestable)`. The difference is not cosmetic on a design wrapped in a pad frame
wider than its core: every stuck-at on a net the core never connects is
ATPG-untestable BY CONSTRUCTION — unobservable, or driven by a constant — and
counting it in the denominator drags the number below the 95 % foundry floor on
exactly the designs where the raw ratio means least.

This program answers only the structural half: WHICH nets can carry no test.
It does not grade faults and does not compute a coverage number; it produces the
untestable set that a coverage calculation subtracts from its denominator.

SOUNDNESS, and which way it must err
====================================
Marking a testable fault untestable INFLATES coverage — a false PASS, the one
failure mode that matters here. Marking a genuinely untestable fault as testable
only leaves coverage conservative. So every rule below is written to
UNDER-exclude:

  * UNOBSERVABLE — a net is observable if it IS a primary output, or if it feeds
    an instance any of whose outputs is observable. Everything reachable
    backwards from the POs is observable; only what is not is excluded. In a
    `fault cut` model each flop's D is already declared as a module output, so
    pseudo-POs need no special case — they arrive as POs.

  * UNCONTROLLABLE — a net is uncontrollable if its only driver is a CONSTANT
    cell, or a gate all of whose inputs are uncontrollable. A constant cell is
    identified STRUCTURALLY, as a cell whose liberty declares no input pin at
    all. Never by name: `TIELO`, `conb_1`, `LOGIC0_X1` and `TIE0` are the same
    thing in four libraries, and a name rule is the overfit this repo removes.

  * A net with NO driver and NO load in the model is excluded from neither set
    by inference — it is reported separately, because "not in the netlist" and
    "in the netlist and untestable" are different claims.

PIN DIRECTIONS COME FROM LIBERTY, never from a pin name. `Z`/`Y`/`Q` are
conventions, not rules, and a library that names an output `OUT` would silently
invert every driver/load edge and produce a confidently wrong answer.

chip-AGNOSTIC: netlist + liberty in, net classification out. No PDK, vendor or
design name appears in any rule.

USAGE
-----
    atpg_untestable_fault_classify.py --netlist cut_netlist.v \\
        --liberty a.lib [--liberty b.lib] [--top MODULE] [--json OUT]

EXIT CODES
----------
    0 = classified     2 = could not classify (unreadable input, no cell
                           resolved against the liberty, no module found)

There is no exit 1: this program measures, it does not judge. The gate that
consumes the set is where a verdict belongs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _source_record_merge import merge_source_records  # noqa: E402

RC_OK, RC_CANNOT_CLASSIFY = 0, 2

#: The synthetic master a continuous assignment is modelled as. Registered in
#: the direction table by the classifier itself, so it never counts as an
#: unresolved library cell.
_ASSIGN_CELL = "__assign__" 

# `cell (NAME) {` ... `pin (P) {` ... `direction : output;`
_CELL_RE = re.compile(r'\bcell\s*\(\s*"?([\w$\\\[\]/.-]+)"?\s*\)\s*\{')
_PIN_RE = re.compile(r'\b(?:pin|bus)\s*\(\s*"?([\w$\\\[\]:.-]+)"?\s*\)\s*\{')
#: `direction : input;` AND `direction : "input";` — sky130's liberty quotes
#: the value (it quotes `clock : "false";` the same way), and a pattern that
#: only accepted the bare form found all 428 cells and ZERO pins in it. The
#: failure was silent: no pin direction meant no edge, and no edge meant an
#: empty untestable set that reads exactly like a clean one.
_DIR_RE = re.compile(r'\bdirection\s*:\s*"?(\w+)"?\s*;')

#: `AOI21D1 _178_ ( .A1(n5), .B(n6), .ZN(n7) );` — shared with
#: `fault_cut_async_observe`, which reads the same netlists.
_INST_RE = re.compile(
    r"\b([A-Za-z_][\w$]*)\s+(\\?[^\s(\\]+)\s*\(\s*((?:\.[^;]*?))\)\s*;", re.S)
_CONN_RE = re.compile(r"\.\s*([A-Za-z_][\w$]*)\s*\(\s*([^)]*?)\s*\)")
_PORT_RE = re.compile(
    r'^\s*(input|output|inout)\s+(?:wire\s+|reg\s+)?(?:\[[^\]]*\]\s*)?'
    r'([^;]+);', re.M)
_MODULE_RE = re.compile(r'^\s*module\s+(\\?\S+)', re.M)
#: `assign \_13092_.d  = _01310_;`
#:
#: LOAD-BEARING, and the reason the synthetic control was not enough. `fault
#: cut` wires every pseudo-PI and pseudo-PO through a continuous assignment,
#: not through a cell pin — 3191 of them in a real sha256 cut netlist. Ignoring
#: them left 33 primary outputs instead of 1583, so the backward closure had
#: almost nothing to start from and 7717 of 8187 nets came back "unobservable".
#: That error runs in the direction that INFLATES coverage, which is the one
#: failure mode this program must not have. A hand-built fixture with no
#: `assign` in it passed both controls while this was true.
_ASSIGN_RE = re.compile(r'^\s*assign\s+([^=;]+?)\s*=\s*([^;]+);', re.M)
_IDENT_RE = re.compile(r'\\[^\s,{}]+\s|[A-Za-z_][\w$]*(?:\s*\[[^\]]*\])?')


# ── liberty ────────────────────────────────────────────────────────────────
def parse_liberty_pin_directions(text: str) -> Dict[str, Dict[str, str]]:
    """``{cell: {pin: 'input'|'output'|'inout'}}``.

    Sliced on `cell (` boundaries and scanned within each slice. The first
    version walked the file brace by brace tracking which cell and pin were
    open; it found all 428 cells in a real sky130 liberty and attributed ZERO
    pins to any of them, and 12.8 MB of char-at-a-time backtracking is the
    wrong shape for this anyway. A cell's pins are all inside its own slice, so
    the slice is the scope and no depth bookkeeping is needed.

    `pg_pin` blocks (power/ground) declare no `direction` and simply contribute
    nothing.
    """
    out: dict = {}
    bounds = [m.start() for m in _CELL_RE.finditer(text)]
    for k, start in enumerate(bounds):
        m = _CELL_RE.match(text, start)
        if not m:
            continue
        name = m.group(1)
        end = bounds[k + 1] if k + 1 < len(bounds) else len(text)
        chunk = text[m.end():end]
        pins: dict = {}
        for pm in _PIN_RE.finditer(chunk):
            dm = _DIR_RE.search(chunk, pm.end(),
                                min(pm.end() + 4000, len(chunk)))
            if dm:
                pins[pm.group(1)] = dm.group(1).lower()
        out[name] = pins
    return out


def constant_cells(directions: dict) -> set:
    """Cells that declare NO input pin — structurally, a tie cell.

    Named nowhere. The synthetic identity master used for continuous
    assignments is excluded explicitly: its inputs are attached at classify
    time rather than declared here, so the structural rule would read every
    `assign` in the design as a constant source — it did, and 6569 of 11385
    nets came back uncontrollable. A library calling it `TIELO`, `conb_1`, `LOGIC0_X1` or `TIE0`
    lands in the same set, and a library that ships a tie cell under a name
    nobody has seen still does.
    """
    return {c for c, pins in directions.items()
            if c != _ASSIGN_CELL
            and pins and not any(d == "input" for d in pins.values())}


# ── netlist ────────────────────────────────────────────────────────────────
def _split_bus(decl: str):
    return [t.strip().lstrip('\\').rstrip() for t in decl.split(',') if t.strip()]


def parse_module(netlist_text: str, top: str = None):
    """``(name, ports, instances)`` for the module carrying the instances.

    A cut netlist holds more than one module and the LAST is not always the
    gate-level one. The module with the most instances is the one the ATPG
    model is built from; picking the first or the last characterises the file
    wrongly in opposite directions, and both of those were tried.
    """
    chunks = []
    parts = re.split(r'^\s*endmodule', netlist_text, flags=re.M)
    for p in parts:
        m = _MODULE_RE.search(p)
        if not m:
            continue
        body = p[m.start():]
        insts = []
        for im in _INST_RE.finditer(body):
            cell, inst, conn = im.group(1), im.group(2), im.group(3)
            if cell in ("module", "input", "output", "inout", "wire", "reg",
                        "assign", "endmodule"):
                continue
            conns = {k: v.strip() for k, v in _CONN_RE.findall(conn)}
            if conns:
                insts.append((cell, inst.lstrip('\\').rstrip(), conns))
        # continuous assignments as identity gates: rhs drives lhs
        for am in _ASSIGN_RE.finditer(body):
            lhs, rhs = am.group(1).strip(), am.group(2)
            srcs = [x.strip() for x in _IDENT_RE.findall(rhs)
                    if x.strip() and not x.strip().isdigit()]
            conns = {"Y": lhs}
            for k, src in enumerate(srcs):
                conns[f"A{k}"] = src
            insts.append((_ASSIGN_CELL, f"__assign_{am.start()}", conns))
        ports = {}
        for pm in _PORT_RE.finditer(body):
            for nm in _split_bus(pm.group(2)):
                ports[nm] = pm.group(1)
        chunks.append((m.group(1).lstrip('\\').rstrip(), ports, insts))
    if not chunks:
        return None
    if top:
        for c in chunks:
            if c[0] == top:
                return c
    return max(chunks, key=lambda c: len(c[2]))


def _base(net: str) -> str:
    """`la_data_out[15]` -> `la_data_out`. Bit-blasted nets are attributed to
    their vector so a port declared `[127:0]` is matched by its bits."""
    net = net.strip().lstrip('\\').rstrip()
    return re.sub(r'\[[^\]]*\]\s*$', '', net)


def classify(ports: dict, instances: list, directions: dict,
             const_cells: set) -> dict:
    """The two structural rules, each erring towards NOT excluding."""
    drivers: dict = {}
    loads: dict = {}
    unresolved_cells = set()
    for cell, inst, conns in instances:
        pins = directions.get(cell)
        if not pins:
            unresolved_cells.add(cell)
            continue
        for pin, net in conns.items():
            if not net:
                continue
            d = pins.get(pin)
            if cell == _ASSIGN_CELL and d is None:
                d = "input"          # every `A<k>` of an identity gate
            if d == "output":
                drivers.setdefault(net, []).append((cell, inst, pin))
            elif d == "input":
                loads.setdefault(net, []).append((cell, inst, pin))

    nets = set(drivers) | set(loads)
    pi = {n for n in nets if ports.get(_base(n)) in ("input", "inout")}
    po = {n for n in nets if ports.get(_base(n)) in ("output", "inout")}

    # OBSERVABLE: backward closure from the POs through the load edges.
    inst_outs: dict = {}
    inst_ins: dict = {}
    for net, ds in drivers.items():
        for _c, i, _p in ds:
            inst_outs.setdefault(i, set()).add(net)
    for net, ls in loads.items():
        for _c, i, _p in ls:
            inst_ins.setdefault(i, set()).add(net)

    observable = set(po)
    frontier = list(po)
    while frontier:
        net = frontier.pop()
        for _c, inst, _p in drivers.get(net, []):
            for src in inst_ins.get(inst, ()):    # this gate's inputs
                if src not in observable:
                    observable.add(src)
                    frontier.append(src)
    unobservable = {n for n in nets if n not in observable}

    # UNCONTROLLABLE: constant-driven, then gates whose inputs are all so.
    uncontrollable = set()
    for net, ds in drivers.items():
        if ds and all(c in const_cells for c, _i, _p in ds):
            uncontrollable.add(net)
    changed = True
    while changed:
        changed = False
        for net, ds in drivers.items():
            if net in uncontrollable or net in pi:
                continue
            ins = set()
            for _c, inst, _p in ds:
                ins |= inst_ins.get(inst, set())
            if ins and ins <= uncontrollable:
                uncontrollable.add(net)
                changed = True

    dangling = {n for n in nets
                if n not in drivers and n not in pi}
    untestable = (unobservable | uncontrollable) - pi
    return {
        "nets": len(nets),
        "primary_inputs": len(pi),
        "primary_outputs": len(po),
        "instances": len(instances),
        "unresolved_cells": sorted(unresolved_cells),
        "unobservable": sorted(unobservable),
        "uncontrollable": sorted(uncontrollable),
        "undriven": sorted(dangling),
        "untestable_nets": sorted(untestable),
        "untestable_count": len(untestable),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--netlist", required=True)
    ap.add_argument("--liberty", action="append", default=[])
    ap.add_argument("--top")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)

    nl = Path(a.netlist)
    if not nl.is_file():
        print(f"[SKIP] atpg_untestable_fault_classify: {nl} is not readable — "
              f"nothing was classified, which is not an empty untestable set",
              file=sys.stderr)
        return RC_CANNOT_CLASSIFY

    # ONE LIBERTY PER SOURCE, and a cell two of them both name is NOT resolved
    # by which file sorted last. `parse_liberty_pin_directions` returns `{}` for
    # a cell whose pins carry no `direction` -- documented above: a `pg_pin`
    # block declares none and contributes nothing. Under `dict.update` that
    # empty map ERASES a populated one from another liberty, and then
    # `classify()` hits `if not pins: unresolved_cells.add(cell); continue`,
    # drops every instance of that cell out of the graph, and loses the
    # observability edges THROUGH it -- so nets upstream come back
    # "unobservable", get counted untestable, and test coverage goes UP.
    # The run does not stop: the refusal at `>= len(lib_masters)` needs EVERY
    # master unresolved, so a partial erase leaves only a [WARN] on stderr.
    # That is the direction this file's own comment calls "the one failure mode
    # this program must not have".
    directions: Dict[str, Dict[str, str]] = merge_source_records(
        (parse_liberty_pin_directions(p.read_text(errors="replace"))
         for p in (Path(lp) for lp in a.liberty) if p.is_file()),
        on_conflict="richer",
    )[0]
    if not directions:
        print("[SKIP] atpg_untestable_fault_classify: no liberty resolved, so "
              "no pin DIRECTION is known. Guessing them from pin names would "
              "invert every driver/load edge in a library that names an output "
              "`OUT`. Not classified.", file=sys.stderr)
        return RC_CANNOT_CLASSIFY

    directions[_ASSIGN_CELL] = {"Y": "output"}
    mod = parse_module(nl.read_text(errors="replace"), a.top)
    if mod is None or not mod[2]:
        print(f"[SKIP] atpg_untestable_fault_classify: no module with "
              f"instances found in {nl}", file=sys.stderr)
        return RC_CANNOT_CLASSIFY

    name, ports, instances = mod
    res = classify(ports, instances, directions, constant_cells(directions))
    # AN UNRESOLVED NETLIST IS NOT A CLEAN ONE. With no cell resolved there are
    # no edges, so every set is empty and `untestable_count` reads 0 — the
    # shape this program exists to remove, reproduced by the program itself on
    # its first real run (60 of 60 sky130 masters unresolved -> "untestable 0",
    # exit 0). A warning under a zero is not a refusal.
    # LIBRARY masters only. The synthetic identity master is always resolved,
    # so counting it made "every real cell unresolved" look like partial
    # success: spm's commercial-PDK netlist matched 0 of its 20 masters against
    # a sky130 liberty and still returned a number, because `__assign__`
    # resolved. The same absence-as-a-pass shape, one level in.
    lib_masters = {c for c, _i, _c2 in instances if c != _ASSIGN_CELL}
    if not res["nets"] or len(res["unresolved_cells"]) >= len(lib_masters):
        print(f"[SKIP] atpg_untestable_fault_classify: {len(res['unresolved_cells'])} "
              f"of {len(lib_masters)} library cell master(s) did "
              f"not resolve against the supplied liberty, so NO driver/load "
              f"edge was built and every set is empty for want of input. That "
              f"is not an empty untestable set.", file=sys.stderr)
        if a.json_out:
            res["classified"] = False
            Path(a.json_out).write_text(json.dumps(res, indent=2) + "\n")
        return RC_CANNOT_CLASSIFY
    res["classified"] = True
    res["module"] = name
    res["netlist"] = str(nl)
    if res["unresolved_cells"]:
        print(f"[WARN] {len(res['unresolved_cells'])} cell master(s) are not in "
              f"the supplied liberty, so their pins contributed NO edge and the "
              f"result is partial: "
              f"{', '.join(res['unresolved_cells'][:6])}", file=sys.stderr)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(res, indent=2) + "\n")
    print(f"atpg_untestable_fault_classify: module {name} — {res['instances']} "
          f"instance(s), {res['nets']} net(s); untestable "
          f"{res['untestable_count']} "
          f"(unobservable {len(res['unobservable'])}, uncontrollable "
          f"{len(res['uncontrollable'])})")
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
