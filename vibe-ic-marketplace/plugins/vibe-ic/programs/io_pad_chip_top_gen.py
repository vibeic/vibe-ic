#!/usr/bin/env python3
"""io_pad_chip_top_gen — the PRODUCER of the chip-top that carries IO pads.

ENFORCEMENT: blocking — ``phase3_one_shot_runner`` invokes this program inline
BEFORE ``step_pad_ring_gen``. Its record is what makes the instance-keyed half
of declaration section 2B derivable; a refusal here leaves those questions
owed and step 15.5ic refuses exactly as it did before. This token names the
measured runner control path, not finding severity.

WHY THIS PROGRAM EXISTS
=======================
The chip path asked every design for a pad ring over instances NOTHING BUILT.
Measured on spm x gf180mcuD at plugin 1.15.67 (2026-09-02), with all eight
section-2B questions answered by hand::

    PAD_INSTANCE_NOT_IN_BLOCK: 36 ordered pad instance(s) are not COMPONENTS
    of phase3/stage3/pnr/floorplan.def -- the side variables name instances
    the netlist must already carry, and this step does not create them

`pad_assignment_gen`'s own docstring had already localised it: PAD_SOUTH /
PAD_EAST / PAD_NORTH / PAD_WEST and SIGNAL_MAP "are lists of NETLIST
INSTANCES", a document "partitions PORTS", and writing instance names for a
netlist that does not contain them "would be inventing the one thing this step
exists to refuse to invent". Both statements were correct and neither could be
acted on, because no step in the flow instantiated an IO cell. A grep over the
tree found the pad-cell masters named in exactly two places -- `bsdl_emit`'s
recogniser and a comment in `foundry_handoff_pack_gen` -- and in no producer.

So the SELF_TAPEOUT route could not be completed by ANY design arriving with
L-documents and a declaration. This program closes that, and it closes it by
DERIVING the instances rather than by relaxing the refusal: the instances it
names exist because it created them.

WHAT IT READS -- three sources, none of them a default
=====================================================
1. THE DESIGN'S OWN PARTITION, via `_l_doc_pad_placement`: which top-level
   PORT sits on which die edge, one entry per bus bit, in the document's own
   order. This is the same reader `pad_assignment_gen` already uses, so the
   partition this producer instantiates and the partition that program reports
   cannot disagree.
2. THE DESIGN'S PORT LIST AND DIRECTIONS, from `L9_INTEGRATION_SPEC.json`
   `top_ports`. Directions decide the pad CLASS; nothing here guesses a
   direction from a name.
3. THE IO CELL LIBRARY, via `_pad_ring.IoLibrary` and
   `_pad_ring.PdkDeclarations`: the masters and their LEF CLASS, the site
   names, the corner master, the fillers and the edge spacing. Read from the
   PDK the RUN selected -- a named tree that does not resolve is NOT RESOLVED,
   never a scan that would draw masters from an unrelated process.

MASTER SELECTION -- a stated rule, and it is recorded per port
==============================================================
An `input` port takes the narrowest ``CLASS PAD INPUT`` master; an `output` or
`inout` port takes the narrowest ``CLASS PAD INOUT`` master; ties break on the
master name so the choice is stable across runs and across filesystems. Where
a library ships no ``PAD INPUT`` at all -- sky130's does not, measured: its
IO LEFs carry 2 ``PAD INOUT`` and 0 ``PAD INPUT`` -- inputs fall back to
``PAD INOUT`` and the fallback is NAMED in the record, per port.

This is a choice, and it is legitimate here only because the design DELEGATED
it: `_l_doc_pad_placement` sets `delegates_io_library_to_pdk` when the design's
own document says the IO cell type is the PDK's to pick. A design that does
NOT delegate is refused rather than chosen for.

ROTATIONS -- library first, geometry second, basis always recorded
=================================================================
Where the IO library declares PAD_ROTATION_HORIZONTAL / _VERTICAL / _CORNER
they are adopted verbatim and the basis is `pdk_declaration` with the
`<file>:<line>` the declaration came from -- sky130_ef_io declares all three.
Where it does not -- gf180mcu_fd_io declares none, measured -- they are
derived from SIDE GEOMETRY by the rule this flow already states in
`_tapeout_declaration`: a pad row along a horizontal edge and a pad row along
a vertical edge differ by a quarter turn, "NORTH is SOUTH's half turn and each
corner is a further quarter turn". The basis is then `side_geometry` and the
rule is written into the record. A derived value is never reported as a
declared one.

WHAT IT WILL NOT DO
===================
* It will not invent a partition. No pad-placement section, an unresolved bus
  token, or a port the partition does not mention: REFUSE, naming it.
* It will not place a port twice, and it will not leave a top-level port
  padless -- both are refusals, because a chip-top that drops a port is a
  different design.
* It will not choose an IO library for a design that did not delegate one.
* It will not write power pads. A ring's rails are formed by cells touching
  and this producer does not know how many supply pads a design wants; that
  is section 2B's own unanswered territory and inventing it here would put a
  power plan in a netlist nobody asked for. The record says so explicitly
  rather than leaving the absence to be noticed.

OUTPUTS
=======
``phase3/stage3/pnr/chip_top_io.v``   the chip-top: core instance, one pad
                                      instance per top-level port, ports
                                      renamed to the pad-side nets
``reports/phase3/io_pad_chip_top.json`` the record: per-port master and why,
                                      the per-side instance ORDER, the
                                      SIGNAL_MAP, the rotations with their
                                      basis, and every refusal

EXIT CODES
    0 = a chip-top and a complete derived record were written
    1 = refused; the record names the rule and nothing was written
    2 = the inputs this producer needs are absent (no partition, no port list,
        no IO library) -- NOT a defect in the design, and not a pass either

chip-AGNOSTIC: no design name, no PDK name and no master name appears in this
file. Every one is read from the project or the PDK tree the run selected.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _l_doc_pad_placement as LPP          # noqa: E402
import _pad_ring as PR                      # noqa: E402

PROGRAM = "io_pad_chip_top_gen"

#: The four sides, in the order a ring is walked. Used only to give the record
#: a stable key order; the ORDER WITHIN a side is always the document's.
SIDES = ("S", "E", "N", "W")

#: LEF classes, by what a port direction needs. First match wins; the fallback
#: is recorded per port when it is taken.
CLASS_PREFERENCE: Dict[str, Tuple[str, ...]] = {
    "input": ("PAD INPUT", "PAD INOUT"),
    "output": ("PAD INOUT",),
    "inout": ("PAD INOUT",),
}

#: The sides whose pad row runs horizontally, and the ones where it runs
#: vertically. This is geometry, not a convention: it is the same north/south
#: vs east/west split `_pad_ring.nearest_side` already uses.
HORIZONTAL_SIDES = ("N", "S")
VERTICAL_SIDES = ("E", "W")

#: The quarter-turn between a horizontal pad row and a vertical one, used only
#: when the IO library declares no rotation of its own.
GEOMETRIC_VERTICAL_QUARTERS = 1


class Refusal(Exception):
    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message


class Unavailable(Exception):
    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message


def instance_name(port: str) -> str:
    """A netlist-legal instance name for the pad that brings `port` out.

    One rule, applied to every port: bus subscripts become underscores. It has
    to be a pure function of the port name, because the SIGNAL_MAP this
    producer writes and the COMPONENTS the DEF later carries are compared by
    string.
    """
    return "u_pad_" + re.sub(r"[^A-Za-z0-9_]", "_", port).strip("_")


def _read_top_ports(project: Path) -> List[Dict[str, object]]:
    spec = project / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    if not spec.is_file():
        raise Unavailable("NO_INTEGRATION_SPEC",
                          f"{spec.relative_to(project)} is absent, so the "
                          "top-level port list and its directions are not "
                          "readable")
    try:
        doc = json.loads(spec.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        raise Unavailable("INTEGRATION_SPEC_UNREADABLE", str(exc))
    ports = doc.get("top_ports") or doc.get("ports") or []
    if not isinstance(ports, list) or not ports:
        raise Unavailable("NO_TOP_PORTS",
                          "the integration spec declares no top_ports")
    return [p for p in ports if isinstance(p, dict)]


def _bit_names(port: Dict[str, object]) -> List[str]:
    """Every net this port contributes, one per bit, MSB first.

    Matches `_l_doc_pad_placement.expand_side_ports`, which is what the
    partition is expressed in -- a scalar stays bare, a bus becomes one
    `name[bit]` per bit.
    """
    name = str(port.get("name") or "")
    try:
        width = int(port.get("width") or 1)
    except (TypeError, ValueError):
        width = 1
    if width <= 1:
        return [name]
    try:
        msb = int(port.get("msb"))
        lsb = int(port.get("lsb"))
    except (TypeError, ValueError):
        msb, lsb = width - 1, 0
    step = -1 if msb >= lsb else 1
    return [f"{name}[{b}]" for b in range(msb, lsb + step, step)]


#: The PDK's own `PAD_PLACE_IO_TERMINALS` reader now lives in `_pad_ring`,
#: because BOTH producers need the same answer from it: this one wires the
#: port to the pad's terminal, and `pad_ring_gen` places the die's BTerm ON
#: that terminal. Two readers of one PDK variable is one reader too many —
#: they would drift, and the pin they disagreed about would be the pin the
#: router could not reach. Re-exported under its old name so every existing
#: caller and test is unchanged.
io_terminals = PR.io_terminals


def library_prefix(decls: "PR.PdkDeclarations") -> Optional[str]:
    """The IO library the PDK itself names, as the prefix its masters share.

    A PDK tree ships more than one IO library in one directory: gf180mcuD's
    `libs.ref/gf180mcu_fd_io/lef/` carries a `gf180mcu_ef_io__bi_t` alongside
    the `gf180mcu_fd_io__*` masters, and the two are DIFFERENT libraries with
    the same footprint. MEASURED: selecting on (width, name) alone picked the
    `ef` master for the one output port and the `fd` masters for the other 35,
    which is a ring built from two libraries and nobody asked for either.

    So the prefix is taken from a master the PDK's own config NAMES -- the
    corner cell -- and read as everything before the `__` separator the
    libraries use. Derived from the declaration, not a literal: a PDK that
    names no corner master yields None and selection stays as it was.
    """
    corner = decls.values.get("PAD_CORNER")
    if not isinstance(corner, str) or "__" not in corner:
        return None
    return corner.split("__", 1)[0] + "__"


def _select_master(direction: str,
                   classes: Dict[str, str],
                   sizes: Dict[str, Tuple[float, float]],
                   prefix: Optional[str] = None,
                   terminals: Optional[Dict[str, str]] = None
                   ) -> Tuple[str, str, bool]:
    """(master, the LEF class it was chosen for, whether it is a fallback)."""
    wanted = CLASS_PREFERENCE.get(direction)
    if wanted is None:
        raise Refusal("PORT_DIRECTION_UNKNOWN",
                      f"port direction {direction!r} is not one of "
                      f"{sorted(CLASS_PREFERENCE)}")
    pool = classes
    if prefix:
        scoped = {m: c for m, c in classes.items() if m.startswith(prefix)}
        if scoped:
            pool = scoped
    if terminals:
        # ONLY MASTERS THE PDK SAYS BRING A SIGNAL OUT. `PAD_PLACE_IO_TERMINALS`
        # is the library's own list of pad masters and the pin each one
        # presents; a master absent from it is not a signal pad.
        listed = {m: c for m, c in pool.items() if m in terminals}
        if listed:
            pool = listed
        # AND, WHERE THE LIBRARY MAKES THE DISTINCTION, ONLY THE DIGITAL ONES.
        # A library's INPUT-class masters are digital by construction, so the
        # terminal THEY present is that library's digital signal terminal.
        # MEASURED on gf180mcuD: in_c and in_s (CLASS PAD INPUT) present
        # `PAD`, and `asig_5p0` -- also CLASS PAD INOUT, also 75 um wide, and
        # alphabetically first -- presents `ASIG5V`. Without this the design's
        # one output port was given an ANALOG pad, silently, because class and
        # width could not tell them apart.
        #
        # A library with no INPUT-class master makes no such distinction, and
        # then this filter does nothing: sky130's IO LEFs carry 0 PAD INPUT
        # and exactly 1 listed PAD INOUT, so the list above has already
        # decided. An earlier attempt used the MODAL terminal instead and was
        # measured picking sky130's five analog entries over its one gpio.
        digital = {t for m, t in terminals.items()
                   if classes.get(m) == "PAD INPUT"}
        if digital:
            narrowed = {m: c for m, c in pool.items()
                        if terminals.get(m) in digital}
            if narrowed:
                pool = narrowed
    for rank, cls in enumerate(wanted):
        cands = sorted((m for m, c in pool.items() if c == cls),
                       key=lambda m: (sizes.get(m, (float('inf'), 0.0))[0], m))
        if cands:
            return cands[0], cls, rank > 0
    raise Refusal("NO_PAD_MASTER_FOR_DIRECTION",
                  f"the IO cell library ships no master of class "
                  f"{' or '.join(wanted)}, so a {direction} port cannot be "
                  "brought out")


def declared_rotations(configs: Sequence[Path]) -> Dict[str, Tuple[str, str]]:
    """`{var: (value, "<file>:<line>")}` for the three PAD_ROTATION_* vars.

    READ HERE AND NOT FROM `PdkDeclarations`, on that class's own grounds:
    `_pad_ring.PDK_DECLARED_VARS` deliberately excludes the rotations, because
    that tuple answers "what may the RING STEP adopt into a config somebody
    else wrote". This producer is asking the other question -- what does the
    library declare -- which `pad_assignment_gen.PDK_DELEGATED_VARS` already
    treats as delegable. Same parser either way: `parse_pad_env_declarations`
    is the single `set ::env(PAD_*)` reader in this codebase and it carries the
    line number a reader needs to find the declaration among the others.

    sky130's `sky130_ef_io/config.tcl` declares all three; gf180mcuD's
    `gf180mcu_fd_io/config.tcl` declares none. Both measured.
    """
    want = ("PAD_ROTATION_HORIZONTAL", "PAD_ROTATION_VERTICAL",
            "PAD_ROTATION_CORNER")
    out: Dict[str, Tuple[str, str]] = {}
    for cfg in configs:
        try:
            text = cfg.read_text(errors="replace")
        except OSError:
            continue
        for var, (value, line) in PR.parse_pad_env_declarations(text).items():
            if var in want and var not in out:
                out[var] = (value, f"{cfg}:{line}")
    return out


def _rotations(configs: Sequence[Path]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """(the three rotations, the basis of each)."""
    out: Dict[str, str] = {}
    basis: Dict[str, str] = {}
    found = declared_rotations(configs)
    names = {"horizontal": "PAD_ROTATION_HORIZONTAL",
             "vertical": "PAD_ROTATION_VERTICAL",
             "corner": "PAD_ROTATION_CORNER"}
    for key, var in names.items():
        rec = found.get(var)
        if rec is not None and PR.normalise_orient(rec[0]) is not None:
            out[key] = rec[0]
            basis[key] = f"pdk_declaration {rec[1]}"
    if len(out) == 3:
        return out, basis
    # THE LIBRARY DID NOT DECLARE THEM — take librelane's own default for all
    # three, and say why it is not a quarter-turn derivation.
    #
    # AN EARLIER VERSION OF THIS FUNCTION DERIVED THE VERTICAL SIDES BY
    # ROTATING THE HORIZONTAL ONE, and it was wrong: the ring builder does not
    # read a per-side rotation out of this answer at all. `_pad_ring.
    # SIDE_ORIENT` holds what the placer ACTUALLY orients each side to —
    # S=N, N=FS, W=FW, E=W in DEF spelling — measured against OpenROAD across
    # three builds and re-derived by `test_the_shipped_orientations_are_what_
    # the_placer_produces`. The three PAD_ROTATION_* values are the REFERENCE
    # the placer starts from, and `_pad_ring` records that the step "has
    # measured it cannot honour a non-default one".
    #
    # So deriving a turn here would have written a value the consumer cannot
    # act on, dressed as an answer. The geometry per side is the ring
    # builder's, it is already measured, and this producer must not
    # re-derive it.
    for key in ("horizontal", "vertical", "corner"):
        out.setdefault(key, PR.ROTATION_DEFAULT)
        basis.setdefault(key, (
            "librelane_default: the IO cell library declares no "
            f"PAD_ROTATION_{key.upper()}, and the per-side orientation is not "
            "this answer's to give — the ring builder derives it from its own "
            "measured _pad_ring.SIDE_ORIENT, which is defined at this default"))
    return out, basis


#: The design's own statement about a pad's AUXILIARY pins, if it makes one.
#: BY PIN AND LEVEL, deliberately. A document saying "pull-up" names an
#: intention; mapping that word onto a pin requires a library statement that
#: the pin is a pull-up enable, and the Liberty of the library in this image
#: gives its `PU` no function at all. So a design that wants a pull states the
#: PIN, which is a fact this program can carry, and one that states a word
#: this program cannot map gets a refusal instead of a guess.
_AUX_SECTION_RE = re.compile(
    r"(?ims)^#{1,6}[^\n]*pad[^\n]*auxiliary[^\n]*$(?P<body>.*?)(?=^#{1,6}\s|\Z)")
_AUX_ENTRY_RE = re.compile(
    r"(?m)^\s*[-*|]?\s*(?P<port>[A-Za-z_][\w$]*(?:\[\d+\])?)\s*[:|]\s*"
    r"(?P<pins>(?:[A-Za-z_]\w*\s*=\s*[01]\s*,?\s*)+)")


def declared_aux_levels(sources: Sequence[Path]
                        ) -> Dict[str, Dict[str, int]]:
    """`{port: {pin: level}}` the DESIGN declares for its pads' aux pins."""
    out: Dict[str, Dict[str, int]] = {}
    for src in sources:
        try:
            text = src.read_text(errors="replace")
        except OSError:
            continue
        for sec in _AUX_SECTION_RE.finditer(text):
            for e in _AUX_ENTRY_RE.finditer(sec.group("body")):
                levels = dict(
                    (m.group(1), int(m.group(2))) for m in
                    re.finditer(r"([A-Za-z_]\w*)\s*=\s*([01])",
                                e.group("pins")))
                if levels:
                    out.setdefault(e.group("port"), {}).update(levels)
    return out


def merge_liberty_pad_cells(paths: Sequence[Path]
                            ) -> Tuple[Dict[str, Dict[str, Dict[str, object]]],
                                       Dict[str, str]]:
    """One role table from every corner Liberty, and the masters they disagree on.

    A pin's DIRECTION, FUNCTION, THREE_STATE and IS_PAD are properties of the
    cell, not of the corner, so every corner file must say the same thing.
    Reading one file and ignoring the rest would hide a library that does not
    — so all are read and a master whose role fields differ between corners is
    REFUSED by name rather than resolved by file order.
    """
    seen: Dict[str, Dict[str, Dict[str, set]]] = {}
    for path in paths:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for cell, pins in PR.parse_liberty_pad_cells(text).items():
            for pin, rec in pins.items():
                for key, value in rec.items():
                    (seen.setdefault(cell, {}).setdefault(pin, {})
                     .setdefault(key, set()).add(value))
    table: Dict[str, Dict[str, Dict[str, object]]] = {}
    conflicts: Dict[str, str] = {}
    for cell, pins in seen.items():
        bad = [f"{pin}.{key}={sorted(str(v) for v in values)}"
               for pin, keys in sorted(pins.items())
               for key, values in sorted(keys.items()) if len(values) > 1]
        if bad:
            conflicts[cell] = ("the corner Liberty views disagree about this "
                               "master's pin roles: " + "; ".join(bad[:4]))
            continue
        table[cell] = {pin: {k: next(iter(v)) for k, v in keys.items()}
                       for pin, keys in pins.items()}
    return table, conflicts


def _core_bit(port_bit: str) -> str:
    """`x[31]` -> `x__core[31]`, `clk` -> `clk__core`.

    One pad drives one BIT; the core takes the whole vector, so the internal
    net is declared once per PORT and indexed here exactly as the port was.
    """
    if port_bit.endswith("]") and "[" in port_bit:
        base, idx = port_bit[:-1].split("[", 1)
        return f"{_core_net(base)}[{idx}]"
    return _core_net(port_bit)


def _core_net(port: str) -> str:
    """The internal net a padded port's CORE side sits on.

    Named from the port, so a reader of the emitted module can see which pad
    it came through, and suffixed so it cannot collide with the port itself.
    """
    return f"{port}__core"


def _emit_verilog(top: str, core: str,
                  ordered: Dict[str, List[str]],
                  chosen: Dict[str, Dict[str, object]],
                  ports: Sequence[Dict[str, object]]) -> str:
    """The chip-top: core instance plus one pad instance per top-level port.

    The pad instances are emitted with POSITIONAL-FREE named connections to a
    single `.PAD` style terminal name discovered from nothing -- so the module
    is written with the pad's own port left UNBOUND except for the core net.
    That is deliberate and it is what this producer's scope is: the netlist
    must CARRY the instances so the ring builder can place them; the pad's
    internal terminal wiring is the IO library's own contract and belongs to
    the step that reads `PAD_PLACE_IO_TERMINALS`.
    """
    lines: List[str] = []
    lines.append("// GENERATED by %s. Do not edit." % PROGRAM)
    lines.append("// One pad instance per top-level port, on the side the "
                 "design's own")
    lines.append("// pad-placement section puts it. See "
                 "reports/phase3/io_pad_chip_top.json")
    lines.append("// for the master chosen for each port and why.")
    decl: List[str] = []
    for p in ports:
        name = str(p.get("name") or "")
        direction = str(p.get("direction") or p.get("mode") or "")
        try:
            width = int(p.get("width") or 1)
        except (TypeError, ValueError):
            width = 1
        rng = ""
        if width > 1:
            rng = " [%s:%s]" % (p.get("msb", width - 1), p.get("lsb", 0))
        decl.append("    %s%s %s" % (direction, rng, name))
    lines.append("module %s (" % top)
    lines.append(",\n".join(decl))
    lines.append(");")
    lines.append("")

    # A PORT WHOSE PAD FACES BOTH WAYS GETS TWO NETS. The port net terminates
    # on the pad's bond terminal and NOWHERE else; the core sits on the pad's
    # core-side pin, through `<port>__core`. A port whose faces could not be
    # resolved keeps the single-net shape it had, so a refusal changes
    # nothing but the record.
    faced = {inst: r for inst, r in chosen.items() if r.get("core_pin")}
    by_port = {str(r["port"]): r for r in faced.values()}
    for p in ports:
        name = str(p.get("name") or "")
        bits = _bit_names(p)
        if not all(b in by_port for b in bits):
            continue
        try:
            width = int(p.get("width") or 1)
        except (TypeError, ValueError):
            width = 1
        rng = ""
        if width > 1:
            rng = " [%s:%s]" % (p.get("msb", width - 1), p.get("lsb", 0))
        lines.append("    wire%s %s;" % (rng, _core_net(name)))
    if faced:
        lines.append("")

    for side in SIDES:
        for inst in ordered.get(side, []):
            rec = chosen[inst]
            lines.append("    // %s edge -- %s" % (side, rec["port"]))
            conn = [".%s(%s)" % (rec["terminal"], rec["port"])]
            if rec.get("core_pin"):
                conn.append(".%s(%s)" % (rec["core_pin"],
                                         _core_bit(str(rec["port"]))))
            # THE TIES ARE RECORDED, NOT WRITTEN AS VERILOG CONSTANTS, and
            # this is a measurement, not a preference. Emitting `.PU(1'b0)`
            # here made OpenROAD's `read_verilog` materialise ONE net named
            # `zero_` carrying 75 pad ITerms; the flow's own POWER-net
            # heuristic types that net GROUND, `pdngen` never builds it, and
            # the PG gate FAILED the run with `PG_UNROUTED_SUPPLY: zero_
            # (GROUND, 75 iterm(s))`. The netlist is not where a pad's
            # auxiliary pin is tied in this flow: `add_global_connection`
            # binds a pin pattern to a real rail, which is the same machinery
            # the hard-macro supply pins already use. What this producer owes
            # is the DECISION and its reason, per pin, in the record below —
            # `aux_pins_defaulted` and `aux_pins_tied_by_derivation` — so the
            # step that owns the rails can bind them and a reviewer can see
            # every level somebody chose. Writing the constant here would
            # have bought a netlist that reads correctly and a chip whose
            # supply net does not exist.
            pass
            lines.append("    %s %s (%s);"
                         % (rec["master"], inst, ", ".join(conn)))
    lines.append("")
    conns = []
    for p in ports:
        name = str(p.get('name'))
        bits = _bit_names(p)
        on_pad = bits and all(b in by_port for b in bits)
        conns.append(".%s(%s)" % (name, _core_net(name) if on_pad else name))
    lines.append("    %s u_core (%s);" % (core, ", ".join(conns)))
    lines.append("")
    lines.append("endmodule")
    lines.append("")
    return "\n".join(lines)


def run(project: Path, pdk_root: Optional[str], pdk: Optional[str]
        ) -> Tuple[int, Dict[str, object]]:
    rec: Dict[str, object] = {"program": PROGRAM, "verdict": "REFUSE",
                              "findings": [], "project": str(project)}

    placement, params, unreadable, scanned = LPP.read_project_placement(project)
    rec["documents_scanned"] = scanned
    rec["documents_unreadable"] = unreadable
    if unreadable:
        raise Refusal("L_DOC_UNREADABLE",
                      "a design document could not be read, and 'I could not "
                      "read it' must not be reported as 'it said nothing': "
                      + "; ".join(f"{u['file']}: {u['reason']}"
                                  for u in unreadable))
    if placement is None:
        raise Unavailable("NO_PAD_PLACEMENT",
                          "no design document states a pad placement, so "
                          "there is no partition to instantiate")
    rec["pad_placement"] = placement.as_dict()
    if not placement.delegates_io_library_to_pdk:
        raise Refusal("IO_LIBRARY_NOT_DELEGATED",
                      "the design's pad-placement section does not delegate "
                      "the IO cell type to the PDK, so this producer will not "
                      "choose one on its behalf")

    side_ports, unresolved = LPP.expand_side_ports(placement, params)
    if unresolved:
        raise Refusal("PARTITION_UNRESOLVED",
                      "the pad placement names signal token(s) whose bit "
                      f"range does not resolve from a declared parameter: "
                      f"{sorted(unresolved)}")

    ports = _read_top_ports(project)
    rec["top_port_count"] = len(ports)
    nets: List[str] = []
    direction_of: Dict[str, str] = {}
    for p in ports:
        d = str(p.get("direction") or p.get("mode") or "").lower()
        for net in _bit_names(p):
            nets.append(net)
            direction_of[net] = d

    placed = [n for side in side_ports.values() for n in side]
    dupes = sorted({n for n in placed if placed.count(n) > 1})
    if dupes:
        raise Refusal("PORT_ON_TWO_SIDES",
                      f"the pad placement puts {dupes} on more than one edge")
    missing = [n for n in nets if n not in placed]
    if missing:
        raise Refusal("PORT_WITHOUT_A_SIDE",
                      f"{len(missing)} top-level net(s) are on no edge, and a "
                      f"chip-top that drops a port is a different design: "
                      f"{missing[:8]}")
    stray = [n for n in placed if n not in direction_of]
    if stray:
        raise Refusal("SIDE_NAMES_UNKNOWN_PORT",
                      f"the pad placement names net(s) the design's port list "
                      f"does not declare: {stray[:8]}")

    lefs = PR.discover_io_lefs(pdk_root, pdk)
    if not lefs:
        raise Unavailable("NO_IO_LIBRARY",
                          "the selected PDK tree ships no IO cell LEF, so no "
                          "pad master exists to instantiate")
    classes: Dict[str, str] = {}
    sizes: Dict[str, Tuple[float, float]] = {}
    for lef in lefs:
        text = lef.read_text(errors="replace")
        classes.update(PR.parse_lef_macro_classes(text))
        sizes.update(PR.parse_lef_macros(text))
    rec["io_library_lefs"] = [str(p) for p in lefs]
    rec["io_master_count"] = len(classes)

    cfgs = PR.discover_io_library_configs(pdk_root, pdk)
    decls = PR.PdkDeclarations(cfgs, masters=sizes)
    rec["pdk_declared"] = {k: v for k, v in decls.values.items()}
    rec["pdk_declared_sources"] = dict(decls.sources)

    prefix = library_prefix(decls)
    rec["io_library_prefix"] = prefix
    rec["io_library_prefix_basis"] = (
        "the library of the corner master the PDK's own config names "
        f"({decls.values.get('PAD_CORNER')!r} from "
        f"{decls.sources.get('PAD_CORNER', '?')})"
        if prefix else
        "the PDK names no corner master, so master selection is not scoped "
        "to one library")

    terminals = io_terminals(cfgs, prefix)
    rec["io_terminals"] = terminals

    chosen: Dict[str, Dict[str, object]] = {}
    ordered: Dict[str, List[str]] = {}
    for side in SIDES:
        ordered[side] = []
        for net in side_ports.get(side, []):
            inst = instance_name(net)
            if inst in chosen:
                raise Refusal("INSTANCE_NAME_COLLISION",
                              f"two ports map to instance {inst!r}")
            master, cls, fallback = _select_master(
                direction_of[net], classes, sizes, prefix,
                terminals)
            chosen[inst] = {"port": net, "master": master,
                            "chosen_for_class": cls,
                            "terminal": terminals.get(master, "PAD"),
                            "terminal_from_pdk": master in terminals,
                            "direction": direction_of[net],
                            "class_fallback": fallback}
            ordered[side].append(inst)

    # ── THE PAD CELL'S TWO FACES ──────────────────────────────────────────
    # The core connects to the pad's CORE-SIDE pin and the port net terminates
    # on the bond terminal alone. Both faces, and every auxiliary tie, are
    # derived from the IO library's own Liberty — see `PR.pad_cell_faces`.
    # A master whose faces cannot be derived keeps the shape it had, and the
    # reason is recorded against the port BY NAME.
    declared_aux = declared_aux_levels(
        [project / f for f in (rec.get("documents_scanned") or [])])
    lib_paths = PR.discover_io_liberty(pdk_root, pdk)
    rec["io_library_liberty"] = [str(x) for x in lib_paths]
    lib_cells, lib_conflicts = merge_liberty_pad_cells(lib_paths)
    faces_refused: Dict[str, str] = {}
    aux_defaulted: List[Dict[str, object]] = []
    aux_declared: List[Dict[str, object]] = []
    for inst, rc in chosen.items():
        master = str(rc["master"])
        if not lib_paths:
            faces_refused[inst] = (
                "the PDK ships no Liberty view for this IO library, so which "
                "pin faces the core is not readable and is not guessed")
            continue
        if master in lib_conflicts:
            faces_refused[inst] = lib_conflicts[master]
            continue
        if master not in lib_cells:
            faces_refused[inst] = (
                f"the IO library's Liberty declares no cell {master!r}, so "
                f"its faces are unknown")
            continue
        faces = PR.pad_cell_faces(lib_cells[master], str(rc["direction"]),
                                  declared_aux.get(str(rc["port"])))
        if faces.refused:
            faces_refused[inst] = faces.refused
            continue
        rc["terminal"] = faces.terminal
        rc["core_pin"] = faces.core_pin
        rc["ties"] = dict(faces.ties)
        rc["tie_reasons"] = dict(faces.reasons)
        for pin, level in sorted(faces.ties.items()):
            entry = {"instance": inst, "port": rc["port"], "pin": pin,
                     "level": level, "reason": faces.reasons.get(pin, "")}
            (aux_defaulted if faces.reasons.get(pin, "").startswith("DEFAULTED")
             else aux_declared).append(entry)
    rec["core_side_refusals"] = faces_refused
    rec["aux_pins_defaulted"] = aux_defaulted
    rec["aux_pins_tied_by_derivation"] = aux_declared
    rec["aux_pins_declared_by_design"] = sorted(declared_aux)

    rotations, rotation_basis = _rotations(cfgs)

    top = str(placement.source and "chip_top" or "chip_top")
    core_doc = project / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    core = "core"
    try:
        core = str(json.loads(core_doc.read_text(errors="replace")
                              ).get("top_module") or core)
    except (OSError, ValueError):
        pass

    out_v = project / "phase3" / "stage3" / "pnr" / "chip_top_io.v"
    out_v.parent.mkdir(parents=True, exist_ok=True)
    out_v.write_text(_emit_verilog(top, core, ordered, chosen, ports))

    rec["verdict"] = "WROTE"
    rec["chip_top_module"] = top
    rec["core_module"] = core
    rec["chip_top_verilog"] = str(out_v.relative_to(project))
    rec["pad_instances"] = chosen
    rec["derived_answers"] = {
        "pad_order_by_side": {"south": ordered["S"], "east": ordered["E"],
                              "north": ordered["N"], "west": ordered["W"]},
        "pad_signal_map": {i: r["port"] for i, r in chosen.items()},
        "pad_rotations": rotations,
        # THE TWO THE OTHER READERS CANNOT SEE, AND WHY THIS ONE CAN.
        # `pad_assignment_gen` reads the PDK config through
        # `parse_pad_env_declarations`, which deliberately returns NO value
        # carrying a Tcl substitution -- and gf180mcuD spells both of these as
        # `$::env(PAD_CELL_LIBRARY)__cor` / `...__fill10 ...`. That refusal is
        # right for a reader with no way to expand the name. This producer HAS
        # one: `PdkDeclarations` resolved it against the library the LEFs were
        # actually read from, the same resolution `io_library_prefix` is built
        # on and the same corner master whose LEF width sized the die below.
        # So the value is a transcription checked against the LEF, not a guess,
        # and it is published here rather than left owed. A name the library
        # does not carry is not published at all.
        "pad_corner_master": (decls.values.get("PAD_CORNER")
                              if decls.values.get("PAD_CORNER") in classes
                              else None),
        "pad_fillers": [f for f in (decls.values.get("PAD_FILLERS") or [])
                        if f in classes] or None,
    }
    rec["derivation_basis"] = {
        "pad_order_by_side": (
            "the design's own pad-placement section, expanded one entry per "
            f"bus bit in the document's order: {placement.source}"),
        "pad_signal_map": (
            "one pad instance per top-level net, named by `instance_name`; "
            "the instances exist because this producer created them in "
            f"{out_v.name}"),
        "pad_rotations": rotation_basis,
        "pad_corner_master": (
            f"the PDK's own IO-library config, "
            f"{decls.sources.get('PAD_CORNER', '?')}, with its one "
            f"`$::env(PAD_CELL_LIBRARY)` substitution resolved to the library "
            f"the LEFs were read from and the result confirmed to be a MACRO "
            f"that library carries"),
        "pad_fillers": (
            f"the PDK's own IO-library config, "
            f"{decls.sources.get('PAD_FILLERS', '?')}, resolved and confirmed "
            f"the same way; a name the LEF does not carry is dropped rather "
            f"than published"),
    }
    # THE DIE THE RING NEEDS, which the design ITSELF says is derived.
    # L9-style pad-placement documents leave the die unspecified and instruct
    # that it follows "from FP_CORE_UTIL and the pad ring"; this is the pad-ring
    # half, and without it the ring is built against a core-sized die and every
    # side comes out NEGATIVE -- measured on spm x gf180mcuD: a 111 um die, two
    # 355 um corners, `PAD_RING_DOES_NOT_FIT` on all four sides at once.
    #
    # Per side: the two corner cells plus every pad on that side, at the
    # master's own LEF width. The die is the LARGEST side, so the ring closes
    # on all four; the remainder on the shorter sides is what the declared
    # fillers exist to close. Rounded UP to a whole micron -- never down,
    # because a die that is 0.4 um short is a ring that does not abut.
    # THE EDGE SPACING IS PART OF THE DIE AND WAS MISSING FROM THIS SUM.
    # `pad_ring_gen` computes the usable side as
    #     side = (die extent) - 2 * PAD_EDGE_SPACING - 2 * (corner extent)
    # (`side_width`, one expression per side, all four the same shape). A die
    # sized without the edge term is therefore short by exactly twice it, and
    # the refusal that produced reads like a pad-ring defect. MEASURED on
    # spm x gf180mcuD after the corner term was added and before this one:
    #     PAD_NORTH: the sum of cell widths is 4800000 DEF unit(s) and the
    #     side is 4696000 -- 104000 unit(s) wider than the declared die
    # 104000 units at 2000 units/um is 52 um, which is 2 x the library's own
    # declared PAD_EDGE_SPACING of 26. The term is read from the same
    # declaration `pad_assignment_gen` writes into the config, so the two
    # cannot disagree; a library that declares none contributes 0, which is
    # what upstream's own default for that variable is.
    corner_master = decls.values.get("PAD_CORNER")
    corner_w = sizes.get(str(corner_master), (0.0, 0.0))[0]
    try:
        edge_um = float(decls.values.get("PAD_EDGE_SPACING") or 0.0)
    except (TypeError, ValueError):
        edge_um = 0.0
    side_um: Dict[str, float] = {}
    for side in SIDES:
        pads = sum(sizes.get(str(chosen[i]["master"]), (0.0, 0.0))[0]
                   for i in ordered[side])
        side_um[side] = 2.0 * edge_um + 2.0 * corner_w + pads
    need = max(side_um.values()) if side_um else 0.0
    die_um = float(int(need) + (1 if need > int(need) else 0))
    rec["die_required_um"] = {
        "per_side": side_um,
        "corner_master": corner_master,
        "corner_width_um": corner_w,
        "edge_spacing_um": edge_um,
        "edge_spacing_source": decls.sources.get("PAD_EDGE_SPACING"),
        "die_side_um": die_um,
        "basis": ("twice the library's declared PAD_EDGE_SPACING, plus two "
                  "corner cells, plus the pads on the longest side, at each "
                  "master's own LEF width, rounded up to a whole micron -- the "
                  "same three terms `pad_ring_gen.side_width` subtracts, in "
                  "the same order; the shorter sides are closed by the "
                  "declared fillers"),
    }

    rec["not_written"] = {
        "power_pads": ("no supply pad is instantiated: the number and "
                       "placement of supply pads is not stated by the design "
                       "and not derivable from the library, and a power plan "
                       "invented here would be indistinguishable in the "
                       "netlist from a declared one"),
    }
    rec["fallback_masters"] = sorted(
        i for i, r in chosen.items() if r["class_fallback"])
    return 0, rec


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", nargs="?", default=".")
    ap.add_argument("--pdk-root", default=None)
    ap.add_argument("--pdk", default=None)
    ap.add_argument("--json", dest="out_json", default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)

    project = Path(args.project).resolve()
    pdk_root = args.pdk_root or os.environ.get("PDK_ROOT")
    pdk = args.pdk or os.environ.get("PDK")

    try:
        rc, rec = run(project, pdk_root, pdk)
    except Unavailable as exc:
        rc, rec = 2, {"program": PROGRAM, "verdict": "NOT_AVAILABLE",
                      "rule": exc.rule, "findings": [exc.message]}
    except Refusal as exc:
        rc, rec = 1, {"program": PROGRAM, "verdict": "REFUSE",
                      "rule": exc.rule, "findings": [exc.message]}

    print(f"=== {PROGRAM} ({project.name}) ===")
    print(f"  verdict: {rec.get('verdict')}")
    if rec.get("verdict") == "WROTE":
        d = rec["derived_answers"]
        n = sum(len(v) for v in d["pad_order_by_side"].values())
        print(f"  {n} pad instance(s) over 4 side(s) -> "
              f"{rec['chip_top_verilog']}")
        print(f"  derived: pad_order_by_side, pad_signal_map, pad_rotations "
              f"({', '.join(sorted(set(v.split(':')[0].split(' ')[0] for v in (rec['derivation_basis']['pad_rotations'].values())))) })")
        if rec.get("fallback_masters"):
            print(f"  class fallback used for "
                  f"{len(rec['fallback_masters'])} instance(s)")
    else:
        for f in rec.get("findings", []):
            print(f"  {rec.get('rule')}: {f}")

    target = Path(args.out_json) if args.out_json else (
        project / "reports" / "phase3" / "io_pad_chip_top.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
