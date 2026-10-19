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

WHAT IT READS -- four sources, none of them a guessed design value
=================================================================
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
4. THE PROJECT'S TAPE-OUT DECLARATION, only for a pad-edge-spacing override.
   The value is resolved through `pad_assignment_gen.compose`, so geometry
   and assignment use its one authority order: declaration over the selected
   IO library. The library's raw value and file:line remain in the record.

When a multi-rail library needs engineering choices, the same agent may write
``phase3/stage3/pnr/io_power_ring_plan.json`` with ``supply_masters`` and
``connector_masters`` lists. These are implementation choices, not original
input facts. Each named master must be in the selected PDK. Bond terminals,
resistor paths, passive connector models and compatible rail voltages are
verified from that PDK; every claimed connector is instantiated in the wrapper.

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
* It will not guess named power-pad masters or silently assume separate IO and
  core voltage domains.  When the caller supplies the PDN's already-derived
  power and ground rail names, it may derive the minimum electrically complete
  SAME-DOMAIN pair from ``CLASS PAD POWER`` and the LEF pins' ``USE`` roles.
  Every connection, source LEF and selection refusal is then recorded.  If the
  library cannot prove such a pair, it refuses instead of emitting a cosmetic
  ring whose supply is open.
* It will not leave an auxiliary IO control floating or disguise a signal pin
  as a power-grid terminal.  Liberty-derived 1/0 controls are driven by the
  active standard-cell library's own tie cells, supplied with their
  Liberty-derived output pins.  If a required tie cell is absent, the producer
  refuses instead of writing a wrapper whose logical record and routed
  connectivity disagree.

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
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082
import _l_doc_pad_placement as LPP          # noqa: E402
import _pad_ring as PR                      # noqa: E402
import _source_record_merge as _srm     # noqa: E402
import pad_assignment_gen as PAG            # noqa: E402

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
    def __init__(self, rule: str, message: str,
                 evidence: Optional[Dict[str, object]] = None) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message
        self.evidence = evidence or {}


class Unavailable(Exception):
    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message


def _effective_pad_edge_spacing(
        project: Path, decls: "PR.PdkDeclarations") -> Tuple[float, str]:
    """Resolve the value geometry shares with ``pad_assignment_gen``.

    The assignment author owns source precedence.  For this variable a slot
    cannot speak, so its ``compose`` contract reduces to project declaration
    over the selected IO library.  Keep the library value in the caller's raw
    PDK record; this returns only the effective numeric value and provenance.
    """
    declaration, unreadable = PAG.read_declaration(project)
    if unreadable:
        raise Refusal(
            "PAD_EDGE_SPACING_SOURCE_UNREADABLE",
            "the tape-out declaration could not be read, so its higher-"
            f"precedence pad-edge spacing is unknown: {unreadable}")

    if declaration is not None:
        answers = declaration.get("answers")
        if not isinstance(answers, dict):
            raise Refusal(
                "PAD_EDGE_SPACING_SOURCE_UNREADABLE",
                "the tape-out declaration's `answers` is not a mapping, so "
                "its higher-precedence pad-edge spacing is unknown")
        invalid = [
            finding for finding in PAG.TD.validate(declaration)
            if finding.get("key") == "pad_edge_spacing_um"
        ]
        if invalid:
            raise Refusal("PAD_EDGE_SPACING_INVALID",
                          str(invalid[0].get("message")))

    pdk_raw = decls.values.get("PAD_EDGE_SPACING")
    library_value = {}
    if pdk_raw is not None and pdk_raw != "":
        library_value["PAD_EDGE_SPACING"] = {
            "value": pdk_raw,
            "source": ("pdk io library "
                       f"{decls.sources.get('PAD_EDGE_SPACING', '?')}"),
        }
    config, provenance, _answered, _owed = PAG.compose(
        {}, declaration, library_value)
    raw = config.get("PAD_EDGE_SPACING", 0.0)
    source = provenance.get(
        "PAD_EDGE_SPACING",
        "selected IO library declares no PAD_EDGE_SPACING; upstream default 0")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise Refusal(
            "PAD_EDGE_SPACING_INVALID",
            f"effective PAD_EDGE_SPACING from {source} must be a finite "
            f"non-negative number, got {raw!r}") from exc
    if not math.isfinite(value) or value < 0:
        raise Refusal(
            "PAD_EDGE_SPACING_INVALID",
            f"effective PAD_EDGE_SPACING from {source} must be a finite "
            f"non-negative number, got {raw!r}")
    return value, source


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
    from _staged_top_module import refresh_selected_interface
    try:
        doc = refresh_selected_interface(project, spec, doc)
    except ValueError as exc:
        raise Refusal("SELECTED_INTERFACE_BINDING_REFUSED", str(exc))
    ports = doc.get("top_ports") or doc.get("ports") or []
    if not isinstance(ports, list) or not ports:
        raise Unavailable("NO_TOP_PORTS",
                          "the integration spec declares no top_ports")
    return [p for p in ports if isinstance(p, dict)]


def _implemented_core_ports(project: Path
                            ) -> Optional[Tuple[Path, List[Dict[str, object]]]]:
    """(selected netlist, its core's ports as {name, direction, width}), or
    None when the netlist cannot be read or declares no port. `width` is None
    when the range is not a literal."""
    try:
        from phase3_one_shot_runner import pnr_input_netlist
        from lec_run import netlist_top_ports
        spec = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
        core = str(json.loads(spec.read_text()).get("top_module") or "core")
        netlist, _note, _scan = pnr_input_netlist(project, core)
        header = netlist_top_ports(netlist.read_text(), core)
    except Exception:  # noqa: BLE001 — unreadable: the caller decides
        return None
    out: List[Dict[str, object]] = []
    for direction, rng, name in header:
        m = re.fullmatch(r"\[\s*(-?\d+)\s*:\s*(-?\d+)\s*\]", rng.strip())
        width = (abs(int(m.group(1)) - int(m.group(2))) + 1 if m
                 else (1 if not rng.strip() else None))
        out.append({"name": name, "direction": direction, "width": width})
    return (netlist, out) if out else None


def _drop_unimplemented_optional_ports(
        project: Path, ports: Sequence[Dict[str, object]]
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """An OPTIONAL L9 port the implemented core does not carry gets no pad.

    L9 records `optional: true` when the input marks a port optional
    (`(optional) i_gpio` in the interface table). Whether the design built it
    is the IMPLEMENTED core's answer, not the document's. MEASURED on
    subservient x gf180mcuD r34 (a DIE): the wrapper gave `i_gpio` a pad and
    wired `.i_gpio(...)` into a core whose synthesised netlist has no such
    port, and routing refused with PADRING_CORE_PORT_CONNECTION_MISMATCH
    unknown=['i_gpio'].

    Only `optional is True` ports that are ABSENT from the selected netlist are
    dropped, and each is recorded. A required port that is absent stays, so
    the runner's connection check still refuses it; when the netlist cannot be
    read nothing is dropped, for the same reason.

    L9's OWN RECONCILIATION LABEL COUNTS THE SAME WAY (D2). L9 top_ports is
    the document's ports UNION the staged top's, and it labels the doc-only
    ones `declared_by_staged_top: false` rather than deleting them. MEASURED
    on subservient x gf180mcuD (v1.25.64): the L3 illustrative
    `o_sram_data`/`o_sram_addr`/... kept their group sides while the core's
    real `o_sram_wdata`/`o_sram_waddr`/... got none, and 15.5ic refused
    PORT_WITHOUT_A_SIDE. An entry L9 itself says the staged top does not
    declare, and which the netlist does not carry either, is a document port
    the implemented core does not have: it is dropped and recorded, carrying
    `declared_by_staged_top: false` where an optional one carries
    `optional: true`. An UNLABELLED absent port still stays.
    """
    selected = _implemented_core_ports(project)
    if not selected:
        return list(ports), []
    netlist, implemented_ports = selected
    implemented = {p["name"] for p in implemented_ports}
    kept, dropped = [], []
    for p in ports:
        absent = str(p.get("name")) not in implemented
        if absent and p.get("optional") is True:
            dropped.append({"name": p.get("name"), "optional": True,
                            "evidence": p.get("evidence"),
                            "netlist": LPP.project_relative(netlist, project)})
        elif absent and p.get("declared_by_staged_top") is False:
            dropped.append({"name": p.get("name"),
                            "declared_by_staged_top": False,
                            "evidence": p.get("evidence"),
                            "netlist": LPP.project_relative(netlist, project)})
        else:
            kept.append(p)
    return kept, dropped


def _check_scan_interface(project: Path,
                          ports: Sequence[Dict[str, object]]) -> Dict[str, object]:
    """Do not emit a wrapper with floating controls on the selected scan core.

    Reuse PnR's selector and the scan producer's functional-mode metadata.
    Proof-only tie values do not authorize permanent physical tie-offs or pads.
    """
    from phase3_one_shot_runner import pnr_input_netlist
    from lec_run import netlist_top_ports, scan_mode_from_meta

    spec = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    core = str(json.loads(spec.read_text()).get("top_module") or "core")
    netlist, note, is_scan = pnr_input_netlist(project, core)
    if not is_scan:
        return {"selected_scan_netlist": False, "selection": note}
    meta_path = project / "reports/phase2/dft/scan_chain.json"
    meta = json.loads(meta_path.read_text())
    mode = scan_mode_from_meta(meta)
    actual = {name: direction for direction, _, name in
              netlist_top_ports(netlist.read_text(), core)}
    declared = {str(p.get("name")): str(p.get("direction") or p.get("mode") or "")
                for p in ports}
    controls = sorted((mode or {}).get("tieoff", {}))
    missing = [name for name in controls
               if actual.get(name) != "input" or declared.get(name) != "input"]
    evidence = {"selected_scan_netlist": True, "selection": note,
                "netlist": LPP.project_relative(netlist, project),
                "netlist_sha256": _sha256(netlist),
                "scan_metadata": LPP.project_relative(meta_path, project),
                "scan_metadata_sha256": _sha256(meta_path),
                "integration_spec": LPP.project_relative(spec, project),
                "integration_spec_sha256": _sha256(spec),
                "functional_mode": mode, "unconnected_controls": missing,
                "unconnected_scan_outputs": [name for name in
                    [str((mode or {}).get("scan_out_port") or "")]
                    if name and declared.get(name) != "output"],
                "physical_tieoff_authorized": False}
    if mode is None or missing or evidence["unconnected_scan_outputs"]:
        raise Refusal(
            "DFT_CONTROL_UNCONNECTED",
            "selected post-DFT core has no approved chip-top connection for "
            f"scan controls {missing} / outputs {evidence['unconnected_scan_outputs']}; "
            "functional-mode proof tie-offs are not "
            "physical interface authority. Declare test access in the approved "
            "integration/pad plan before emitting a wrapper; no pads, pin mux "
            "or permanent tie-off were invented.", {"scan_interface": evidence})
    return evidence



def _declared_test_access(project: Path, ports: Sequence[Dict[str, object]]):
    """Extend the physical interface only through an explicit, source-bound plan.

    config/dft_test_access.json is an integration choice, never a rewrite of L9.
    The supported mapping is a dedicated pad per scalar scan port, preserving
    the core's names and polarities. No implicit mux, constant or protocol is
    synthesized. Absence keeps the existing DFT_CONTROL_UNCONNECTED refusal.
    All pad masters and connections still come from the usual LEF/Liberty path.
    """
    path = project / "config/dft_test_access.json"
    if not path.exists():
        return [], {}, None
    from phase3_one_shot_runner import pnr_input_netlist
    from lec_run import netlist_top_ports, scan_mode_from_meta

    def refuse(message):
        raise Refusal("DFT_TEST_ACCESS_INVALID", message)

    try:
        plan = json.loads(path.read_text())
    except OSError as exc:
        refuse(f"cannot read {LPP.project_relative(path, project)}: "
               f"{LPP.pathless_os_error(exc)}")
    except ValueError as exc:
        refuse(f"cannot read {LPP.project_relative(path, project)}: {exc}")
    if not isinstance(plan, dict) or plan.get("schema") != "vibeic.dft-test-access.v1":
        refuse("test access needs schema vibeic.dft-test-access.v1")
    if plan.get("mapping") != "dedicated_pads" or not plan.get("authority"):
        refuse("test access needs an explicit authority and dedicated_pads mapping")
    spec = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    core = str(json.loads(spec.read_text()).get("top_module") or "core")
    netlist, note, is_scan = pnr_input_netlist(project, core)
    meta_path = project / "reports/phase2/dft/scan_chain.json"
    if not is_scan:
        refuse("a test-access plan requires the selected published scan netlist")
    if (plan.get("netlist_sha256") != _sha256(netlist)
            or plan.get("scan_metadata_sha256") != _sha256(meta_path)):
        refuse("test-access plan does not bind the current netlist and scan metadata")
    try:
        mode = scan_mode_from_meta(json.loads(meta_path.read_text()))
    except (OSError, ValueError, TypeError) as exc:
        refuse(f"scan functional-mode metadata is invalid: {exc}")
    if not mode or any(v not in (0, 1) for v in mode["tieoff"].values()):
        refuse("scan metadata needs binary functional control levels")
    if plan.get("functional_mode") != mode["tieoff"]:
        refuse("declared external functional-mode levels disagree with scan metadata")
    actual = {n: (d, rng.strip()) for d, rng, n in
              netlist_top_ports(netlist.read_text(), core)}
    functional = {str(p.get("name")) for p in ports}
    expected = dict.fromkeys(mode["tieoff"], "input")
    sout = mode["scan_out_port"]
    if not sout or sout in expected:
        refuse("scan output is absent or conflicts with a control")
    expected[sout] = "output"
    if functional & expected.keys():
        refuse("dedicated test access cannot replace an existing functional port")
    if set(actual) != functional | expected.keys():
        refuse("selected netlist ports disagree with the functional and scan interfaces")
    for name, direction in expected.items():
        if actual.get(name) != (direction, ""):
            refuse(f"scan port {name!r} must be an actual scalar {direction}")
    rows = plan.get("ports")
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        refuse("test access ports must be explicit per-port records")
    names = [r.get("name") for r in rows]
    if any(not isinstance(n, str) or not re.fullmatch(r"[A-Za-z_]\w*", n) for n in names):
        refuse("test-access port names must be simple Verilog identifiers")
    if len(names) != len(set(names)) or set(names) != set(expected):
        refuse("test-access plan must map every scan port exactly once")
    additions, sides = [], {s: [] for s in SIDES}
    for row in rows:
        name, side = row["name"], row.get("side")
        if side not in SIDES or row.get("direction") != expected[name]:
            refuse(f"invalid direction or side for scan port {name!r}")
        additions.append({"name": name, "direction": expected[name], "width": 1})
        sides[side].append(name)
    record = {"declaration": LPP.project_relative(path, project),
              "declaration_sha256": _sha256(path),
              "authority": plan["authority"], "mapping": plan["mapping"],
              "netlist_sha256": _sha256(netlist),
              "scan_metadata_sha256": _sha256(meta_path),
              "ports": rows, "functional_mode": mode["tieoff"],
              "functional_mode_source": "external tester or board drives these levels",
              "permanent_control_tieoffs": False, "selection": note}
    return additions, sides, record


#: MOVED TO `_l_doc_pad_placement` (R-0915-101), for the reason the PDK
#: terminal reader below was moved to `_pad_ring`: BOTH consumers need the
#: same answer out of the same document. This one derives the ring at step
#: 15.5ic; `slot_pad_budget_check` budgets a DIE against that same ring at
#: step 2. Two readers of one pad-placement section is one reader too many --
#: they would drift, and the pad they disagreed about would be the pad the
#: budget did not refuse. Re-exported under their old private names so every
#: existing caller and test in this module is unchanged.
_GROUP_CARRIER_WORDS = LPP.GROUP_CARRIER_WORDS
_GROUP_ATOM_ALIASES = LPP.GROUP_ATOM_ALIASES
_group_atoms = LPP.group_atoms
_bit_names = LPP.bit_names
_resolve_declared_pad_groups = LPP.resolve_declared_pad_groups


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
                   terminals: Optional[Dict[str, str]] = None,
                   declines: Optional[List[str]] = None
                   ) -> Tuple[str, str, bool]:
    """(master, the LEF class it was chosen for, whether it is a fallback).

    `declines` collects, BY NAME, every narrowing this selection wanted and
    could not have. MEASURED on live main 7903c1972305 (2026-09-03):
    `silent_decline_audit programs --ratchet` took the shipped residual from
    15 to 16 on `io_pad_chip_top_gen.py:263  library_prefix() -> prefix: no
    else branch — the refusal is silent`. The caller already records
    `io_library_prefix_basis` when the PDK names no corner master, but the
    SELECTION itself then silently searched every library on the machine and
    the port record said nothing about it. A pad master chosen out of an
    unscoped pool is a different artefact from one chosen out of the design's
    own IO library, and the difference belongs on the record that names the
    master, not only in a field a reader has to correlate.
    """
    # The sink is a plain list and the branches append to it INLINE rather
    # than through a helper: `silent_decline_audit` reads the branch body, and
    # a disclosure hidden one call deep reads to it — correctly — as a branch
    # that says nothing. MEASURED: routing these through a `_declined()`
    # helper moved the finding from "no else branch" to "else branch present
    # but discloses nothing", which is the same silence with an else on it.
    if declines is None:
        declines = []
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
        else:
            declines.append(
                f"library scoping declined: no master under the declared IO "
                f"library prefix {prefix!r}; the pool is every master read, "
                f"unscoped")
    else:
        declines.append(
            "library scoping declined: the PDK declares no IO library prefix, "
            "so the pool is every master read, unscoped")
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
_AUX_PIN_REF = r"[A-Za-z_]\w*(?:\[\d+\])?"
_AUX_ENTRY_RE = re.compile(
    r"(?m)^\s*[-*|]?\s*(?P<port>[A-Za-z_][\w$]*(?:\[\d+\])?)\s*[:|]\s*"
    rf"(?P<pins>(?:{_AUX_PIN_REF}\s*=\s*[01](?!\d)\s*,?\s*)+)")


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
                    re.finditer(rf"({_AUX_PIN_REF})\s*=\s*([01])(?!\d)",
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


def _sha256(path: Path) -> Optional[str]:
    """Hash one readable authority file; unreadable remains explicit None."""
    try:
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _derive_supply_pad_pair(
        classes: Dict[str, str],
        sizes: Dict[str, Tuple[float, float]],
        pin_roles: Dict[str, Dict[str, Tuple[str, str]]],
        prefix: Optional[str], power_net: str, ground_net: str,
        macro_sources: Dict[str, List[Path]],
        ) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    """Derive one external POWER pad and one external GROUND pad.

    This is deliberately electrical, not name-based.  For a same-domain ring,
    the external POWER pad is the ``CLASS PAD POWER`` macro which exposes a
    POWER-use pin other than the core rail while omitting the core POWER pin;
    the ground pad is the symmetric case.  That missing core-side pin is what
    distinguishes the two ESD supply cells in libraries where both macros also
    carry the opposite rail.  All USE POWER pins bind to ``power_net`` and all
    USE GROUND pins bind to ``ground_net``.

    One cell per polarity is the minimum complete pair.  Current capacity is a
    separate sign-off measurement: no LEF syntax carries an ampere rating, so
    this helper records that it is not determined rather than fabricating one.
    """
    rails = {power_net, ground_net}
    uses = (("power", "POWER", power_net),
            ("ground", "GROUND", ground_net))
    pair: List[Dict[str, object]] = []
    declined: Dict[str, List[str]] = {"power": [], "ground": []}
    for kind, use, core_rail in uses:
        eligible: List[Tuple[float, str, str, Dict[str, str]]] = []
        for master, cls in sorted(classes.items()):
            if cls.upper() != "PAD POWER":
                continue
            if prefix and not master.startswith(prefix):
                declined[kind].append(
                    f"{master}: outside selected IO-library prefix {prefix}")
                continue
            roles = pin_roles.get(master, {})
            by_use = {pin: role_use for pin, (_direction, role_use)
                      in roles.items() if role_use in ("POWER", "GROUND")}
            same_use = sorted(pin for pin, role_use in by_use.items()
                              if role_use == use)
            external = [pin for pin in same_use if pin not in rails]
            opposite = "GROUND" if use == "POWER" else "POWER"
            if core_rail in by_use:
                declined[kind].append(
                    f"{master}: carries core {kind} rail {core_rail}; not the "
                    f"external {kind} bridge cell")
                continue
            if len(external) != 1:
                declined[kind].append(
                    f"{master}: expected one non-core {use} terminal, found "
                    f"{external}")
                continue
            if not any(role_use == opposite for role_use in by_use.values()):
                declined[kind].append(
                    f"{master}: no {opposite}-use pin for the ESD return")
                continue
            connections = {
                pin: power_net if role_use == "POWER" else ground_net
                for pin, role_use in sorted(by_use.items())
            }
            eligible.append((float(sizes.get(master, (float("inf"), 0.0))[0]),
                             master, external[0], connections))
        if not eligible:
            raise Refusal(
                "SUPPLY_PAD_PAIR_UNRESOLVED",
                f"the selected IO library proves no external {kind} bridge "
                f"cell for same-domain rails {power_net}/{ground_net}; "
                + "; ".join(declined[kind][:8]))
        _width, master, terminal, connections = sorted(eligible)[0]
        source_records = []
        for source in sorted(set(macro_sources.get(master, []))):
            source_records.append({"path": str(source),
                                   "sha256": _sha256(source)})
        pair.append({
            "kind": kind,
            "port": power_net if kind == "power" else ground_net,
            "master": master,
            "terminal": terminal,
            "supply_connections": connections,
            "chosen_for_class": "PAD POWER",
            "direction": "inout",
            "class_fallback": False,
            "selection_declines": declined[kind],
            "source_lefs": source_records,
            "is_supply_pad": True,
        })
    return pair, {
        "domain_topology": "single_domain",
        "power_net": power_net,
        "ground_net": ground_net,
        "minimum_pair_count": 1,
        "capacity_from_lef": "NOT_DETERMINED",
        "capacity_reason": (
            "LEF proves pin roles and geometry but carries no current rating; "
            "the final project must bind the installed-library revision to a "
            "public PDK current rating and measured worst-case current"),
        "selection_rule": (
            "one PAD POWER macro per polarity, scoped to the PDK-selected IO "
            "library; the external terminal is the sole same-USE pin outside "
            "the core rails on the macro which omits that core-side rail"),
    }


def _faces_core(rect: Tuple[float, float, float, float], side: str,
                placed_size: Tuple[float, float]) -> bool:
    """Does a placed pin rectangle reach the pad edge that faces the core?

    The same test pdngen's `PadDirectConnectionStraps::getPinsFacingCore`
    applies: a pad in the south row faces the core with its top edge, the
    north row with its bottom edge, the west column with its right edge and
    the east column with its left edge.
    """
    w, h = placed_size
    eps = 1e-6
    return {"S": rect[3] >= h - eps, "N": rect[1] <= eps,
            "W": rect[2] >= w - eps, "E": rect[0] <= eps}[side]


def _supply_pad_strap_reach(pair: Sequence[Dict[str, object]],
                            pin_ports: Dict[str, Dict[str, List[Tuple[str, Tuple[
                                float, float, float, float]]]]],
                            sizes: Dict[str, Tuple[float, float]],
                            connect_layers: Optional[Sequence[str]],
                            pad_rotations: Optional[Dict[str, str]] = None,
                            ) -> Dict[str, object]:
    """How far from the pad edge the PDN ring must lie for pdngen to strap
    each supply cell to it.

    pdngen (`add_pdn_ring -connect_to_pads`) connects a supply pad with one
    strap per core-facing pin of the net the pad supplies: from the pin's far
    end, across the pad edge, to the far edge of that net's ring. The strap is
    as wide as the pin. MEASURED (subservient x gf180mcuD, OpenROAD
    26Q3-3002): pdngen keeps such a strap only when it is LONGER THAN IT IS
    WIDE. It reads a strap's direction from its aspect ratio, so a shorter
    strap counts as running along the edge, the pad's own obstruction at its
    pad end is stretched over all of it, and it is cut away (vibeic/OpenROAD
    #33). The ground cell's pins are 1.0 um deep and 9.5-10.25 um wide; its
    straps were 8.82 um (west) and 8.9 um (north, a 2412 um die) long and the
    core's ground grid was left without a source (PSM-0069). With the ring
    8 um further out the same cell connected on every edge, and the power
    cell (4.655 um pins) connected on every edge either way. The routing
    direction of the pin's layer does not decide it.

    So a strap needs `pin depth + pad-edge-to-ring-far-edge > pin width`, and
    this returns, per cell and per edge, `reach_um = pin width - pin depth`:
    the distance the ring's far edge must lie beyond the pad edge. Only the
    pins on the net the cell supplies count (pdngen builds its straps per
    ITerm, so an opposite-polarity ESD pin never sources this net), and only
    on the declared pad-connect layers when they are given. `reach_um` is
    the largest over the pair; the runner reserves it in the core inset.
    Pin geometry and cell size come from the IO LEF; nothing is named.
    """
    layers = set(connect_layers or [])
    cells: Dict[str, Dict[str, object]] = {}
    worst: Optional[float] = None
    undetermined = []
    for entry in pair:
        master = str(entry["master"])
        net = entry.get("grid_net", entry.get("port"))
        size = sizes.get(master)
        pins = sorted(pin for pin, pin_net in dict(
            entry.get("supply_connections") or {}).items() if pin_net == net)
        ports = pin_ports.get(master) or {}
        if not size or not any(ports.get(pin) for pin in pins):
            cells[master] = {"verdict": "NOT_DETERMINED", "net": net,
                             "reason": "the IO LEF gives this cell no size or "
                                       "no pin geometry on the net it supplies"}
            undetermined.append(master)
            continue
        by_side: Dict[str, object] = {}
        for side in SIDES:
            orient = PR.SIDE_ORIENT[side]
            # Native row-axis rotations: vertical controls S/N, horizontal
            # controls W/E. Apply the PDK reference rotation before the
            # placer's measured per-side transform, just as make_io_sites does.
            axis = "vertical" if side in ("S", "N") else "horizontal"
            reference = PR.normalise_orient((pad_rotations or {}).get(axis, "R0"))
            rotated = PR.orient_rect((0.0, 0.0, size[0], size[1]), reference, size)
            rotated_size = (rotated[2] - rotated[0], rotated[3] - rotated[1])
            outline = PR.orient_rect(rotated, orient, rotated_size)
            placed_size = (outline[2] - outline[0], outline[3] - outline[1])
            straps = []
            for pin in pins:
                for layer, rect in ports.get(pin) or []:
                    if layers and layer not in layers:
                        continue
                    placed = PR.orient_rect(PR.orient_rect(rect, reference, size),
                                            orient, rotated_size)
                    if not _faces_core(placed, side, placed_size):
                        continue
                    across_x = side in ("E", "W")
                    width = (placed[3] - placed[1]) if across_x else (placed[2] - placed[0])
                    depth = (placed[2] - placed[0]) if across_x else (placed[3] - placed[1])
                    straps.append({"pin": pin, "layer": layer,
                                   "width_um": round(width, 6),
                                   "depth_um": round(depth, 6),
                                   "reach_um": round(width - depth, 6)})
            by_side[side] = {"straps": straps,
                             "reach_um": (max(s["reach_um"] for s in straps)
                                          if straps else None)}
        side_reach = [v["reach_um"] for v in by_side.values()
                      if v["reach_um"] is not None]
        if not side_reach:
            cells[master] = {"verdict": "NOT_DETERMINED", "net": net,
                             "reason": "no pin of the net this cell supplies "
                                       "reaches its core-facing edge on a "
                                       "pad-connect layer",
                             "sides": by_side}
            undetermined.append(master)
            continue
        cell_reach = max(side_reach)
        worst = cell_reach if worst is None else max(worst, cell_reach)
        cells[master] = {"verdict": "MEASURED", "net": net,
                         "reach_um": cell_reach, "sides": by_side}
    return {
        "verdict": "NOT_DETERMINED" if undetermined or worst is None else "MEASURED",
        "reach_um": None if undetermined else worst,
        "connect_layers": sorted(layers) if layers else None,
        "rule": ("pdngen keeps a pad strap only when it is longer than it is "
                 "wide: pin depth + (pad edge to the net's ring far edge) > "
                 "pin width. reach_um = pin width - pin depth, the distance "
                 "the ring's far edge must lie beyond the pad edge"),
        "reason": ("" if not undetermined else
                   f"no strap geometry for {sorted(undetermined)}; the core "
                   f"inset keeps the PDK's own clearance and the PDN run "
                   f"judges the connection"),
        "cells": cells,
    }


def core_rail_voltage(liberty_text: str, power_net: str
                      ) -> Tuple[Optional[float], str]:
    """The core power rail's voltage from the ACTIVE standard-cell Liberty:
    its `voltage_map` entry for `power_net`, else the library `nom_voltage`."""
    view = PR.parse_liberty_supply_view(liberty_text)
    vmap = view["voltage_map"]
    if power_net in vmap:
        return vmap[power_net], f"voltage_map({power_net})"
    if view["nom_voltage"] is not None:
        return view["nom_voltage"], "nom_voltage"
    return None, f"the Liberty maps no voltage for {power_net} and states no nom_voltage"


def _derive_multi_rail_supply_pair(
        classes: Dict[str, str],
        sizes: Dict[str, Tuple[float, float]],
        pin_roles: Dict[str, Dict[str, Tuple[str, str]]],
        prefix: Optional[str], power_net: str, ground_net: str,
        macro_sources: Dict[str, List[Path]],
        terminals: Dict[str, str],
        lib_views: Sequence[Dict[str, object]],
        subckts: Dict[str, Tuple[List[str], List[List[str]]]],
        core_voltage: Optional[float],
        extra_supply_masters: Sequence[str] = (),
        ) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    """The supply pair for an IO library whose supply cells carry SEVERAL
    ring rails, so no pin is "the one non-core terminal".

    Every fact is read from the PDK, never from a pin or cell name:
      * the BOND terminal: the PDK's own PAD_PLACE_IO_TERMINALS entry, else
        the Liberty pin or pg_pin marked `is_pad`;
      * the rail it FEEDS: the bond itself when it is a `pg_pin` (a ring rail
        bonded directly), else the cell port the PDK netlist joins to it
        through one series resistor;
      * the CORE power rail: a fed rail the Liberty characterises at the core
        voltage the active standard-cell Liberty states;
      * the CORE ground rail: the `related_ground_pin` the IO library pairs
        with that power rail.
    Candidates are the PDK-declared supply masters when the PDK declares any,
    else every PAD POWER master of the selected library. Zero or several
    bridges for a polarity REFUSE with the candidates named: nothing is picked
    by order. Ring rails other than the core pair stay ring rails."""
    why: List[str] = []
    pool = sorted(m for m, cls in classes.items()
                  if cls.upper() == "PAD POWER"
                  and (not prefix or m.startswith(prefix)))
    declared = [m for m in pool if m in terminals]
    basis = ("the PDK's PAD_PLACE_IO_TERMINALS" if declared
             else "every PAD POWER master of the selected library")
    primary_pool = declared or pool
    unknown = sorted(set(extra_supply_masters) - set(pool))
    if unknown:
        raise Refusal("RING_SUPPLY_MASTER_UNPROVED",
                      f"implementation supply masters are not selected-library PAD POWER cells: {unknown}")
    pool = sorted(set(primary_pool) | set(extra_supply_masters))

    def views_of(master: str) -> List[Dict[str, object]]:
        return [v for v in lib_views if master in v["cells"]]

    def volts(master: str, rail: str) -> List[float]:
        out = set()
        for v in views_of(master):
            pg = v["cells"][master]["pg_pins"].get(rail) or {}
            name = pg.get("voltage_name") or rail
            if name in v["voltage_map"]:
                out.add(v["voltage_map"][name])
        return sorted(out)

    cells: Dict[str, Dict[str, object]] = {}
    for m in pool:
        roles = pin_roles.get(m, {})
        uses = {pin: u for pin, (_d, u) in roles.items()
                if u in ("POWER", "GROUND")}
        bond = terminals.get(m)
        if not bond:
            pads = sorted({p for v in views_of(m)
                           for kind in ("pins", "pg_pins")
                           for p, a in v["cells"][m][kind].items()
                           if str(a.get("is_pad", "")).lower() == "true"})
            if len(pads) != 1:
                why.append(f"{m}: bond terminal not determined (is_pad on "
                           f"{pads or 'no pin'})")
                continue
            bond = pads[0]
        use = uses.get(bond)
        if use is None:
            why.append(f"{m}: bond {bond} is not a POWER/GROUND pin in the LEF")
            continue
        is_pg = any(bond in v["cells"][m]["pg_pins"] for v in views_of(m))
        if is_pg:
            fed, how = [bond], "the bond terminal is itself the ring rail (pg_pin)"
        else:
            fed, how = PR.bond_fed_rails(subckts, m, bond)
            fed = [f for f in fed if uses.get(f) == use]
        if len(fed) != 1:
            why.append(f"{m}: bond {bond} feeds {fed or 'no'} {use} rail "
                       f"({how})")
            continue
        cells[m] = {"bond": bond, "use": use, "fed": fed[0], "how": how,
                    "uses": uses}

    def refuse(kind: str, detail: str) -> Refusal:
        return Refusal(
            "SUPPLY_PAD_PAIR_UNRESOLVED",
            f"the selected IO library proves no external {kind} bridge cell "
            f"for rails {power_net}/{ground_net}: {detail}; candidates from "
            f"{basis}; " + "; ".join(why[:8]))

    if core_voltage is None:
        raise refuse("power", "the core rail's voltage is not stated by the "
                     "active standard-cell Liberty, so no fed rail can be "
                     "matched to it")
    power = sorted(m for m, c in cells.items() if m in primary_pool and c["use"] == "POWER"
                   and core_voltage in volts(m, str(c["fed"])))
    if len(power) != 1:
        raise refuse("power", f"{len(power)} candidate(s) feed a rail "
                     f"characterised at the core voltage {core_voltage:g} V: "
                     f"{power or [(m, c['fed'], volts(m, str(c['fed']))) for m, c in cells.items() if c['use'] == 'POWER']}")
    p_master = power[0]
    p_rail = str(cells[p_master]["fed"])
    grounds = sorted({str(a.get("related_ground_pin"))
                      for v in lib_views for cell in v["cells"].values()
                      for a in cell["pins"].values()
                      if a.get("related_power_pin") == p_rail
                      and a.get("related_ground_pin")})
    if len(grounds) != 1:
        raise refuse("ground", f"the IO library pairs power rail {p_rail} "
                     f"with {grounds or 'no'} ground rail(s)")
    g_rail = grounds[0]
    ground = sorted(m for m, c in cells.items()
                    if m in primary_pool and c["use"] == "GROUND" and c["fed"] == g_rail)
    if len(ground) != 1:
        raise refuse("ground", f"{len(ground)} candidate(s) feed the core "
                     f"ground rail {g_rail}: {ground}")
    pair: List[Dict[str, object]] = []
    unbound: Dict[str, List[str]] = {}
    for kind, master, net in (("power", p_master, power_net),
                              ("ground", ground[0], ground_net)):
        c = cells[master]
        connections = {str(c["bond"]): net, str(c["fed"]): net}
        uses = c["uses"]
        if uses.get(p_rail) == "POWER":
            connections[p_rail] = power_net
        if uses.get(g_rail) == "GROUND":
            connections[g_rail] = ground_net
        unbound[master] = sorted(p for p in uses if p not in connections)
        pair.append({
            "kind": kind,
            "port": net,
            "master": master,
            "terminal": c["bond"],
            "supply_connections": dict(sorted(connections.items())),
            "chosen_for_class": "PAD POWER",
            "direction": "inout",
            "class_fallback": False,
            "selection_declines": list(why),
            "source_lefs": [{"path": str(src), "sha256": _sha256(src)}
                            for src in sorted(set(macro_sources.get(master, [])))],
            "is_supply_pad": True,
            "derivation": {"bond": c["bond"], "fed_rail": c["fed"],
                           "fed_rail_basis": c["how"],
                           "fed_rail_volts": volts(master, str(c["fed"])),
                           "candidates_from": basis},
        })
    # A core bridge cell carries every ring rail, but only bonds the one its
    # own pad terminal feeds. Resolve the other rails against ALL PDK-declared
    # supply cells. A declared cell is a usable path only when its bond and
    # fed rail are proved by the Liberty/netlist above; it must also be put in
    # the wrapper below, since a catalogue cell alone is not a bond.
    needed = sorted({r for rails in unbound.values() for r in rails})
    auxiliary: List[Dict[str, object]] = []
    bond_paths: Dict[str, Dict[str, str]] = {}
    selected_uses: Dict[str, set] = {}
    for master in (p_master, ground[0]):
        for rail, (_direction, use) in pin_roles[master].items():
            if use in ("POWER", "GROUND"):
                selected_uses.setdefault(rail, set()).add(use)
    for rail in needed:
        if len(selected_uses.get(rail, set())) != 1:
            continue
        required_use = next(iter(selected_uses[rail]))
        candidates = sorted(m for m, c in cells.items()
                            if c["fed"] == rail and
                            c["use"] == required_use
                            and m not in (p_master, ground[0]))
        if len(candidates) != 1:
            continue
        master = candidates[0]
        c = cells[master]
        bond_paths[rail] = {"master": master, "bond": str(c["bond"]),
                            "basis": str(c["how"])}
        auxiliary.append({
            "kind": f"ring_{len(auxiliary)}", "port": rail,
            "master": master, "terminal": c["bond"],
            "supply_connections": {str(c["bond"]): rail, rail: rail},
            "chosen_for_class": "PAD POWER", "direction": "inout",
            "class_fallback": False, "selection_declines": list(why),
            "source_lefs": [{"path": str(src), "sha256": _sha256(src)}
                            for src in sorted(set(macro_sources.get(master, [])))],
            "is_supply_pad": True,
            "derivation": {"bond": c["bond"], "fed_rail": rail,
                           "fed_rail_basis": c["how"],
                           "candidates_from": (
                               "engineering implementation master; PDK Liberty is_pad and netlist"
                               if master in extra_supply_masters and master not in primary_pool else basis)},
        })
    return pair, {
        "domain_topology": "single_domain",
        "power_net": power_net,
        "ground_net": ground_net,
        "minimum_pair_count": 1,
        "capacity_from_lef": "NOT_DETERMINED",
        "capacity_reason": (
            "LEF proves pin roles and geometry but carries no current rating"),
        "core_rails_on_ring": {"power": p_rail, "ground": g_rail,
                               "core_voltage": core_voltage},
        "ring_rails_unbound": unbound,
        "ring_rails_without_bond": sorted(set(needed) - set(bond_paths)),
        "ring_rail_bond_paths": bond_paths,
        "core_supply_pads": pair,
        "supplemental_supply_pads": auxiliary,
        "selection_rule": (
            "multi-rail IO library: the bond terminal's fed rail at the core "
            "voltage (Liberty) is the power bridge; the ground rail the "
            "library pairs with it is the ground bridge; other ring rails are "
            "left to the ring"),
    }


def _complete_ring_supply_paths(pair, plan, classes, pin_roles, prefix,
                                macro_sources, lib_views, subckts,
                                connector_masters, verilog_texts):
    """Resolve proved passive paths for scheduled supply pads and connectors.

    Engineering choices name existing PDK masters, never rail aliases. The
    actual resistor/model connections and voltages come from the PDK. No
    supply is tied to another merely because both are POWER pins.
    """
    paths = plan["ring_rail_bond_paths"]
    core = plan["core_rails_on_ring"]
    roots = {core["power"]: pair[0], core["ground"]: pair[1]}
    scheduled = pair + list(plan["supplemental_supply_pads"])
    needed = {rail for rails in plan["ring_rails_unbound"].values() for rail in rails}

    def volts(rail):
        return {view["voltage_map"][attrs.get("voltage_name") or rail]
                for view in lib_views for cell in view["cells"].values()
                for pin, attrs in cell["pg_pins"].items()
                if pin == rail and (attrs.get("voltage_name") or rail) in view["voltage_map"]}

    for entry in scheduled:
        master, bond = str(entry["master"]), str(entry["terminal"])
        source_rail = str(entry["derivation"]["fed_rail"])
        roles = pin_roles[master]
        for rail, nodes in PR.bond_resistor_paths(subckts, master, bond).items():
            if (rail not in needed or rail in paths or len(nodes) < 3
                    or nodes[1] != source_rail
                    or roles.get(rail, (None, None))[1] != roles[source_rail][1]
                    or not volts(rail) or volts(rail) != volts(source_rail)):
                continue
            paths[rail] = {"master": master, "bond": bond,
                           "source_rail": source_rail, "resistor_path": nodes,
                           "basis": "same-polarity, same-voltage resistor path in the PDK supply-pad netlist"}

    bridges = {}
    for text in verilog_texts:
        for master, pairs in PR.parse_verilog_rail_bridges(text).items():
            if master in bridges and bridges[master] != pairs:
                raise Refusal("RING_CONNECTOR_UNPROVED", f"PDK connector models disagree for {master}")
            bridges[master] = pairs
    connectors = []
    for master in connector_masters:
        pairs = bridges.get(master)
        roles = pin_roles.get(master, {})
        if (classes.get(master, "").upper() not in ("PAD AREAIO", "PAD SPACER")
                or (prefix and not master.startswith(prefix)) or not pairs):
            raise Refusal("RING_CONNECTOR_UNPROVED", f"no selected-library passive connector model and LEF for {master}")
        for a, b in pairs:
            if (a == b or roles.get(a, (None, None))[1] not in ("POWER", "GROUND")
                    or roles.get(a, (None, None))[1] != roles.get(b, (None, None))[1]
                    or not volts(a) or volts(a) != volts(b)):
                raise Refusal("RING_CONNECTOR_UNPROVED", f"connector {master} does not prove compatible supply rails {a}/{b}")
        connectors.append({
            "kind": f"connector_{len(connectors)}", "port": master,
            "master": master, "terminal": "", "direction": "inout",
            "is_ring_connector": True, "is_supply_pad": False,
            "class_fallback": False, "selection_declines": [],
            "rail_bridges": [list(p) for p in pairs],
            "supply_connections": {rail: rail for pair_ in pairs for rail in pair_},
            "chosen_for_class": classes[master],
            "source_lefs": [{"path": str(p), "sha256": _sha256(p)}
                            for p in sorted(set(macro_sources.get(master, [])))]})
    # Resolve only connectors reaching an already bonded rail; the PDK model
    # alone, without a reachable source and a scheduled instance, is not a bond.
    changed = True
    while changed:
        changed = False
        for entry in connectors:
            for a, b in entry["rail_bridges"]:
                for rail, source in ((a, b), (b, a)):
                    if rail not in needed or rail in paths or (source not in roots and source not in paths):
                        continue
                    if source in roots:
                        root = roots[source]
                        path = {"master": root["master"], "bond": root["terminal"], "source_rail": source}
                    else:
                        path = dict(paths[source])
                        path.setdefault("source_rail", source)
                    path.update({"connector_master": entry["master"], "via_rail": source,
                                 "basis": "declared PDK connector model joining a compatible, bond-reachable rail"})
                    paths[rail] = path
                    changed = True
    plan["ring_connectors"] = connectors
    plan["ring_rails_without_bond"] = sorted(needed - set(paths))


def resolve_supply_pad_pair(
        classes: Dict[str, str],
        sizes: Dict[str, Tuple[float, float]],
        pin_roles: Dict[str, Dict[str, Tuple[str, str]]],
        prefix: Optional[str], power_net: str, ground_net: str,
        macro_sources: Dict[str, List[Path]],
        terminals: Dict[str, str],
        liberty_texts,
        netlist_texts,
        core_liberty_text,
        core_liberty: str = "",
        ring_implementation: Optional[Dict[str, object]] = None,
        verilog_texts=(),
        ) -> Tuple[List[Dict[str, object]], Dict[str, object],
                   Optional[Dict[str, object]]]:
    """`(pair, plan, core_voltage_record)` for the chip's supply pads.

    The same-domain rule first (one non-core terminal per supply cell). An IO
    library whose supply cells carry several ring rails has no such terminal,
    and is resolved from its own Liberty and netlist instead
    (`_derive_multi_rail_supply_pair`). When neither rule proves a pair the
    refusal carries both rules' reasons. The three PDK inputs may be given
    as values or as zero-argument loaders; loaders run only when the
    same-domain rule cannot decide."""
    def _value(x):
        return x() if callable(x) else x

    choices = {} if ring_implementation is None else ring_implementation
    if not isinstance(choices, dict):
        raise Refusal("RING_IMPLEMENTATION_INVALID", "ring implementation must be an object")
    for key in ("supply_masters", "connector_masters"):
        names = choices.get(key, [])
        if (not isinstance(names, list) or any(not isinstance(n, str) or not n for n in names)
                or len(names) != len(set(names))):
            raise Refusal("RING_IMPLEMENTATION_INVALID", f"{key} must be a list of distinct PDK masters")
    try:
        pair, plan = _derive_supply_pad_pair(
            classes, sizes, pin_roles, prefix, power_net, ground_net,
            macro_sources)
        return pair, plan, None
    except Refusal as same_domain:
        if same_domain.rule != "SUPPLY_PAD_PAIR_UNRESOLVED":
            raise
        core_v, core_v_basis = (None, "no active standard-cell Liberty was "
                                "supplied (--tie-liberty)")
        core_text = _value(core_liberty_text)
        if core_text:
            core_v, core_v_basis = core_rail_voltage(core_text, power_net)
        views = [PR.parse_liberty_supply_view(t)
                 for t in _value(liberty_texts)]
        subckts: Dict[str, Tuple[List[str], List[List[str]]]] = {}
        for text in _value(netlist_texts):
            for k, v in PR.parse_spice_subckts(text).items():
                subckts.setdefault(k, v)
        record = {"volts": core_v, "basis": core_v_basis,
                  "liberty": core_liberty}
        try:
            pair, plan = _derive_multi_rail_supply_pair(
                classes, sizes, pin_roles, prefix, power_net, ground_net,
                macro_sources, terminals, views, subckts, core_v,
                extra_supply_masters=choices.get("supply_masters", []))
            _complete_ring_supply_paths(
                pair, plan, classes, pin_roles, prefix, macro_sources, views,
                subckts, choices.get("connector_masters", []),
                _value(verilog_texts) if choices.get("connector_masters") else ())
        except Refusal as multi_rail:
            raise Refusal(
                "SUPPLY_PAD_PAIR_UNRESOLVED",
                f"same-domain rule: {same_domain.message} || multi-rail "
                f"rule: {multi_rail.message}") from multi_rail
        return pair, plan, record


def require_bonded_ring_rails(plan: Dict[str, object]) -> None:
    """Refuse a chip top whose PDK-derived supply plan leaves a ring rail
    without a bond-reachable supply pad or declared connector.

    A multi-rail pad can prove the core pair while still carrying additional
    rail pins.  Reporting that condition but writing the wrapper creates a
    die with an electrically floating ring. Engineering implementation choices
    may name actual PDK connectors; their models must prove the compatible
    connection and their instances must be scheduled. No rail alias is invented.
    """
    raw = plan.get("ring_rails_unbound")
    if not isinstance(raw, dict):
        return
    rails = sorted({str(rail) for values in raw.values()
                    if isinstance(values, list) for rail in values})
    paths = plan.get("ring_rail_bond_paths") or {}
    scheduled = list(plan.get("core_supply_pads") or []) + list(plan.get("supplemental_supply_pads") or [])
    bonded = {str(item["derivation"]["fed_rail"])
              for item in plan.get("core_supply_pads", []) if item.get("is_supply_pad")}
    connectors = {item["master"]: item for item in plan.get("ring_connectors", [])
                  if item.get("is_ring_connector")}
    changed = True
    while changed:
        changed = False
        for rail, path in paths.items():
            if rail in bonded or not isinstance(path, dict):
                continue
            entries = [item for item in scheduled if item.get("is_supply_pad")
                       and item.get("master") == path.get("master")
                       and item.get("terminal") == path.get("bond")]
            if not entries:
                continue
            source = path.get("source_rail", rail)
            if not any(item.get("derivation", {}).get("fed_rail") == source for item in entries):
                continue
            connector = path.get("connector_master")
            resistor_path = path.get("resistor_path")
            if connector:
                item = connectors.get(connector, {})
                via = path.get("via_rail")
                if via not in bonded or not any(set(pair_) == {rail, via}
                                                for pair_ in item.get("rail_bridges", [])):
                    continue
            elif resistor_path:
                if (not isinstance(resistor_path, list) or len(resistor_path) < 3
                        or resistor_path[:2] != [path["bond"], source]
                        or resistor_path[-1] != rail):
                    continue
            elif not any(item.get("grid_net", item.get("port")) == rail for item in entries):
                continue
            bonded.add(rail)
            changed = True
    rails = [rail for rail in rails if rail not in bonded]
    if rails:
        raise Refusal(
            "RING_RAIL_BOND_UNDECLARED",
            "the selected IO library's PDK supply-cell/netlist evidence leaves "
            "ring rail(s) without a scheduled bond-reachable supply pad or a "
            "declared connector: " + ", ".join(rails) + "; this producer will not "
            "invent a rail short or choose an undeclared connector")


def connect_bonded_ring_rails(
        supply_group: Sequence[Dict[str, object]], plan: Dict[str, object],
        pin_roles: Dict[str, Dict[str, Tuple[str, str]]],
        power_net: str, ground_net: str,
        signal_pads: Sequence[Dict[str, object]] = ()) -> None:
    """Put every scheduled bonded rail on every pad's matching LEF pin.

    The selected core pair and the supplemental PDK pads share ring rails.
    Leaving their non-core pins open would turn catalogue reachability into a
    false physical claim, even though a bridge cell exists in the PDK.
    """
    core_ring = plan.get("core_rails_on_ring") or {}
    net_for_rail = {str(core_ring["power"]): power_net,
                    str(core_ring["ground"]): ground_net} if core_ring else {}
    net_for_rail.update({str(rail): str(rail) for rail in
                         (plan.get("ring_rail_bond_paths") or {})})
    for entry in supply_group:
        for rail, net in entry["supply_connections"].items():
            if pin_roles[str(entry["master"])].get(rail, (None, None))[1] in ("POWER", "GROUND"):
                net_for_rail.setdefault(rail, net)
    # A proved hard-short connector needs one electrical net in the wrapper
    # and ODB. Separate names on physically touching connector pins make
    # OpenROAD correctly refuse PAD-0002. Resistor-fed quiet rails stay separate.
    paths = plan.get("ring_rail_bond_paths") or {}
    for _ in range(len(paths)):
        for rail, path in paths.items():
            if path.get("connector_master") and path.get("via_rail") in net_for_rail:
                net_for_rail[rail] = net_for_rail[path["via_rail"]]
    plan["ring_net_bindings"] = dict(sorted(net_for_rail.items()))
    for entry in supply_group:
        roles = pin_roles[str(entry["master"])]
        connections = dict(entry["supply_connections"])
        for rail, net in net_for_rail.items():
            if rail in roles and (not entry.get("is_ring_connector") or rail in connections):
                connections[rail] = net
        entry["supply_connections"] = dict(sorted(connections.items()))
    # A PDK series resistor separates the external bond from the core/ring
    # rail. Putting its two terminals on one wrapper net shorts that resistor
    # and makes the bond's metal look like an unconnected part of the core PDN.
    # Keep the already resolved grid name; expose the PDK bond terminal as
    # the external supply port. Hard-short connectors above still share nets.
    for entry in supply_group:
        bond = entry.get("terminal")
        fed = (entry.get("derivation") or {}).get("fed_rail")
        if entry.get("is_supply_pad") and bond and fed and bond != fed:
            entry["grid_net"] = entry["supply_connections"][fed]
            entry["port"] = str(bond)
            entry["supply_connections"][bond] = str(bond)
            plan["ring_net_bindings"][str(bond)] = str(bond)
    # Signal-pad PG pins must use these same bindings. Matching rails only by
    # nominal voltage loses the distinction between IO, quiet and switched
    # supplies and can disagree with adjacent supply/connector instances.
    for entry in signal_pads:
        roles = pin_roles.get(str(entry["master"]), {})
        entry["power_connections"] = {
            rail: net for rail, net in sorted(net_for_rail.items())
            if roles.get(rail, (None, None))[1] in ("POWER", "GROUND")}


_BIT_PIN_RE = re.compile(r"^([A-Za-z_]\w*)\[(-?\d+)\]$")


def _named_connections(inst: str, master: str,
                       pairs: Sequence[Tuple[str, str]],
                       bus_ports: Optional[Dict[str, Dict[str, Tuple[int, int]]]]
                       ) -> List[str]:
    """`.pin(net)` for each pair; the bits of one BUS become ONE connection.

    A named port connection cannot select a bit (`.DM[0](x)` is not Verilog).
    Bits of the same pin are grouped and emitted as a concatenation ordered by
    the range the IO library's own Verilog declares (`.DM({b2,b1,b0})` for
    `[2:0]`). A bit whose bus the PDK Verilog does not declare, or a bus only
    partly connected, is REFUSED by name: no order is assumed and no fill
    value is invented (this producer reads no PDK-stated default)."""
    items: List[Tuple[str, str, str]] = []
    groups: Dict[str, Dict[int, str]] = {}
    for pin, net in pairs:
        m = _BIT_PIN_RE.match(str(pin))
        if m is None:
            items.append(("pin", str(pin), str(net)))
            continue
        base, idx = m.group(1), int(m.group(2))
        if base not in groups:
            items.append(("bus", base, ""))
            groups[base] = {}
        if idx in groups[base]:
            raise Refusal("PAD_BUS_BIT_CONNECTED_TWICE",
                          f"{inst} ({master}): bit {pin} is connected twice")
        groups[base][idx] = str(net)
    out: List[str] = []
    for kind, name, net in items:
        if kind == "pin":
            out.append(".%s(%s)" % (name, net))
            continue
        decl = (bus_ports or {}).get(master, {}).get(name)
        if decl is None:
            raise Refusal(
                "PAD_BUS_PIN_UNDECLARED",
                f"{inst} ({master}): bits {sorted(groups[name])} of pin "
                f"{name!r} are connected, but the IO library's Verilog "
                f"declares no range for {master}.{name}, so neither the "
                f"width nor the bit order of the concatenation is known")
        msb, lsb = decl
        step = -1 if msb >= lsb else 1
        want = list(range(msb, lsb + step, step))
        missing = [i for i in want if i not in groups[name]]
        extra = sorted(set(groups[name]) - set(want))
        if missing or extra:
            raise Refusal(
                "PAD_BUS_PARTIALLY_CONNECTED",
                f"{inst} ({master}): pin {name}[{msb}:{lsb}] has bits "
                f"{sorted(groups[name])} connected; missing {missing}, outside "
                f"the declared range {extra}. No PDK-stated default fill is "
                f"read by this producer, so none is invented")
        out.append(".%s({%s})" % (name, ", ".join(groups[name][i]
                                                   for i in want)))
    return out


def io_bus_ports(verilog_texts: Sequence[str]
                 ) -> Dict[str, Dict[str, Tuple[int, int]]]:
    """Merge every IO Verilog file's bus declarations; two files that
    declare one port with different ranges are REFUSED, never resolved by
    file order."""
    merged: Dict[str, Dict[str, Tuple[int, int]]] = {}
    for text in verilog_texts:
        for module, buses in PR.parse_verilog_bus_ports(text).items():
            for port, rng in buses.items():
                have = merged.setdefault(module, {}).get(port)
                if have is not None and have != rng:
                    raise Refusal(
                        "PAD_BUS_DECLARATION_CONFLICT",
                        f"the IO library's Verilog declares {module}.{port} "
                        f"as both [{have[0]}:{have[1]}] and [{rng[0]}:{rng[1]}]")
                merged[module][port] = rng
    return merged


def _emit_verilog(top: str, core: str,
                  ordered: Dict[str, List[str]],
                  chosen: Dict[str, Dict[str, object]],
                  ports: Sequence[Dict[str, object]],
                  supply_ports: Sequence[str] = (),
                  tie_cells: Optional[Dict[int, Dict[str, str]]] = None,
                  tie_liberty: str = "",
                  bus_ports: Optional[Dict[str, Dict[str, Tuple[int, int]]]] = None,
                  ) -> str:
    """The chip-top: core instance plus one pad instance per top-level port.

    Every connection is POSITIONAL-FREE and named from the IO library.  The
    bond terminal takes the chip port, the core-facing pin takes the internal
    net, and every Liberty-derived auxiliary control takes a routed signal net
    driven by the active PDK's tie cell for its required logic level.  Thus the
    wrapper PnR consumes and the producer's decision record describe the same
    electrical circuit without placing SIGNAL pins in DEF SPECIALNETS.
    """
    auxiliary_signals, used_ties = _auxiliary_pin_signal_connections(
        chosen, tie_cells or {}, liberty=tie_liberty or "")
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
    for name in supply_ports:
        decl.append("    inout %s" % name)
    lines.append("module %s (" % top)
    lines.append(",\n".join(decl))
    lines.append(");")
    lines.append("")
    internal_supplies = sorted({str(net) for entry in chosen.values()
                               for key in ("supply_connections", "power_connections")
                               for net in (entry.get(key) or {}).values()}
                              - set(supply_ports) - {str(p.get("name")) for p in ports})
    for net in internal_supplies:
        lines.append(f"    wire {net};")
    if internal_supplies:
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

    for net in sorted({str(tie["net"]) for tie in used_ties.values()}):
        lines.append("    wire %s;" % net)
    if used_ties:
        lines.append("")
        for _endpoint, tie in sorted(used_ties.items()):
            if tie.get("source") == "pad":
                continue  # The driver is already the selected pad instance.
            lines.append("    %s %s (.%s(%s));"
                         % (tie["master"], tie["instance"], tie["pin"],
                            tie["net"]))
        lines.append("")

    for side in SIDES:
        for inst in ordered.get(side, []):
            rec = chosen[inst]
            lines.append("    // %s edge -- %s" % (side, rec["port"]))
            if rec.get("supply_connections"):
                pairs = sorted(dict(rec["supply_connections"]).items())
            else:
                pairs = [(rec["terminal"], rec["port"])]
                pairs.extend(sorted((rec.get("power_connections") or {}).items()))
            if rec.get("core_pin"):
                pairs.append((rec["core_pin"], _core_bit(str(rec["port"]))))
            # Never use Verilog constants or direct POWER/GROUND nets for IO
            # control SIGNAL pins.  Constants once materialised unrouted
            # zero_/one_ nets; direct rails put these signal ITerms into
            # regular VDD/VSS NETS that neither PDN nor detailed routing
            # completed.  A PDK tie-cell output is an ordinary routed signal.
            pairs.extend(sorted(auxiliary_signals.get(inst, {}).items()))
            pairs.extend(sorted({(str(tie["pin"]), str(tie["net"]))
                                 for tie in used_ties.values()
                                 if tie.get("source") == "pad"
                                 and tie["instance"] == inst}))
            conn = _named_connections(inst, str(rec["master"]), pairs,
                                      bus_ports)
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


def _auxiliary_pin_signal_connections(
        chosen: Dict[str, Dict[str, object]],
        tie_cells: Dict[int, Dict[str, str]],
        liberty: str = "",
        ) -> Tuple[Dict[str, Dict[str, str]],
                   Dict[Tuple[str, str], Dict[str, object]]]:
    """Resolve every IO control onto an ordinary tie-driven signal net.

    ``pad_cell_faces`` owns the Boolean decision.  This helper owns its
    physical representation. A pad's own constant output drives controls in
    its IO voltage domain; remaining controls use the active core tie cell. Each
    control gets its own tie-cell driver/net: that is the smallest bounded
    legal topology (fanout one), lets placement co-locate the driver with the
    pad load, and avoids asking the resizer to construct a chip-spanning tree
    from one minimum-drive tie cell.
    """
    tied = {inst: dict(rec.get("ties") or {})
            for inst, rec in chosen.items() if rec.get("ties")}
    if not tied:
        return {}, {}
    endpoints: List[Tuple[str, str, int]] = []
    for inst, ties in sorted(tied.items()):
        for pin, level in sorted(ties.items()):
            if level not in (0, 1, False, True):
                raise Refusal(
                    "AUXILIARY_PAD_LEVEL_NOT_BOOLEAN",
                    f"{inst}/{pin} requests level {level!r}; only 0 or 1 can "
                    "be represented by a derived tie-cell output")
            endpoints.append((inst, str(pin), int(level)))
    used: Dict[Tuple[str, str], Dict[str, object]] = {}
    occupied_instances = set(chosen)
    occupied_nets = {str(rec.get("port") or "") for rec in chosen.values()}
    resolved: Dict[str, Dict[str, str]] = {}
    local_nets: Dict[Tuple[str, str], str] = {}
    for index, (inst, control_pin, level) in enumerate(endpoints):
        local_pin = (chosen[inst].get("local_tie_sources") or {}).get(control_pin)
        if local_pin:
            driver = (inst, str(local_pin))
            net = local_nets.setdefault(driver, f"_vibeic_aux_tie_{index:04d}")
            if net in occupied_nets:
                raise Refusal("AUXILIARY_PAD_TIE_NAME_COLLISION",
                              f"reserved local tie net {net} collides with a port")
            used[(inst, control_pin)] = {
                "level": level, "master": chosen[inst]["master"],
                "pin": str(local_pin), "instance": inst, "net": net,
                "source": "pad"}
            resolved.setdefault(inst, {})[control_pin] = net
            continue
        raw = tie_cells.get(level) or {}
        master = str(raw.get("master") or "")
        tie_pin = str(raw.get("pin") or "")
        if not master or not tie_pin:
            # NAMES ITS SEARCH SPACE. "no tie cell for this level" and "no
            # Liberty was consulted at all" are different facts, and a reader
            # who cannot tell them apart cannot tell a real library gap from a
            # mis-wired producer. So the refusal states the Liberty it read,
            # and says so explicitly when it was handed none.
            _looked = (f"the active standard-cell Liberty {liberty!r}"
                       if liberty else
                       "NO standard-cell Liberty path was supplied to this "
                       "producer (tie_liberty was empty), so nothing was read")
            raise Refusal(
                "AUXILIARY_PAD_TIE_CELL_ABSENT",
                f"one or more IO pads require logic level {level}, but "
                f"{_looked} resolved no tie-cell master and output pin for "
                f"that level (master={master!r}, pin={tie_pin!r})")
        instance = f"_vibeic_aux_tie_cell_{index:04d}"
        net = f"_vibeic_aux_tie_{index:04d}"
        if instance in occupied_instances or net in occupied_nets:
            raise Refusal(
                "AUXILIARY_PAD_TIE_NAME_COLLISION",
                f"reserved tie identity {instance}/{net} collides with a "
                "design or pad identity")
        key = (inst, control_pin)
        used[key] = {"level": level, "master": master, "pin": tie_pin,
                     "instance": instance, "net": net}
        resolved.setdefault(inst, {})[control_pin] = net
    return resolved, used


def _local_pad_tie_sources(pins, ties, power_connections):
    """Constant outputs with the control's own Liberty power domain.

    A core tie-high at 1.8 V cannot drive a 3.3 V IO control. The pad's
    TIE_HI_ESD/TIE_LO_ESD are ordinary routable signal outputs. Compare actual
    connected rails as well as pin identities (VSWITCH may share VDDIO).
    """
    result = {}
    for control, level in ties.items():
        rail = pins[control].get("related_power_pin")
        if not rail:
            continue
        candidates = []
        for name, rec in pins.items():
            other_rail = rec.get("related_power_pin")
            same_domain = bool(other_rail and (other_rail == rail or
                               (power_connections.get(rail) and
                                power_connections.get(rail) ==
                                power_connections.get(other_rail))))
            if (rec.get("direction") == "output" and same_domain
                    and rec.get("function") == str(int(level))):
                candidates.append(name)
        if len(candidates) == 1:
            result[control] = candidates[0]
    return result


def run(project: Path, pdk_root: Optional[str], pdk: Optional[str],
        power_net: Optional[str] = None, ground_net: Optional[str] = None,
        tie_high_cell: Optional[str] = None,
        tie_high_pin: Optional[str] = None,
        tie_low_cell: Optional[str] = None,
        tie_low_pin: Optional[str] = None,
        tie_liberty: Optional[str] = None,
        supply_plan: Optional[Dict[str, object]] = None,
        pad_connect_layers: Optional[Sequence[str]] = None,
        ) -> Tuple[int, Dict[str, object]]:
    # Name the run and its files independently of the container's bind mount.
    rec: Dict[str, object] = {"program": PROGRAM, "verdict": "REFUSE",
                              "findings": [], "project": project.name}

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

    ports, not_implemented = _drop_unimplemented_optional_ports(
        project, _read_top_ports(project))
    selected_core = _implemented_core_ports(project)
    splits, rejected_splits = LPP.accepted_exposed_output_splits(
        project, selected_core[1] if selected_core else None)
    if rejected_splits:
        rec["exposed_output_splits_rejected"] = rejected_splits
        raise Refusal("EXPOSED_OUTPUT_SPLIT_INVALID",
                      "a declared extra output is not a same-width output "
                      "of the selected core and L9 carrier: "
                      + json.dumps(rejected_splits, sort_keys=True))
    if splits:
        implemented_by_name = {str(p["name"]): p for p in selected_core[1]}
        for _carrier, targets in splits:
            for name in sorted(targets):
                width = int(implemented_by_name[name]["width"])
                ports.append({"name": name, "direction": "output",
                              "mode": "output", "width": width,
                              "msb": width - 1, "lsb": 0,
                              "evidence": "phase2/stage1/rtl/SOURCE_MANIFEST.json",
                              "extraction_strategy": "authored_manifest_exposed_output"})
        rec["exposed_output_splits"] = [
            {"l9": sorted(carrier), "rtl": sorted(targets)}
            for carrier, targets in splits]
    optional_absent = [d for d in not_implemented if d.get("optional") is True]
    doc_only_absent = [d for d in not_implemented if d not in optional_absent]
    if optional_absent:
        rec["optional_ports_not_implemented"] = optional_absent
    if doc_only_absent:
        rec["doc_ports_not_implemented"] = doc_only_absent
    rec["functional_top_port_count"] = len(ports)
    test_ports, test_sides, test_record = _declared_test_access(project, ports)
    functional_ports = ports
    ports = ports + test_ports
    rec["top_port_count"] = len(ports)
    if test_record is not None:
        rec["test_access"] = test_record
    rec["scan_interface"] = _check_scan_interface(project, ports)

    side_ports, unresolved = LPP.expand_side_ports(placement, params)
    if unresolved:
        raise Refusal("PARTITION_UNRESOLVED",
                      "the pad placement names signal token(s) whose bit "
                      f"range does not resolve from a declared parameter: "
                      f"{sorted(unresolved)}")

    # A DECLARED RENAME CARRIES ITS GROUP'S SIDE (D2): the hand-authored
    # SOURCE_MANIFEST pairs, read by the same function step 2 reads them with.
    # Only a pair phase 2's spec_conformance_check would accept counts
    # (`accept_renames`); a rejected one is recorded with its reasons.
    renames, rejected_renames = LPP.accepted_renames(
        project, selected_core[1] if selected_core else None)
    side_ports, unresolved = LPP.expand_renamed_side_ports(
        placement, params, functional_ports, renames + splits,
        exact_carriers=LPP.input_delegated_rename_names(project, renames + splits))
    if renames:
        rec["renamed_interfaces"] = [
            {"l9": sorted(l9), "rtl": sorted(rtl)} for l9, rtl in renames]
    # A refusal below names the rejected pairs too: they are why a group or
    # a port the author meant to place has no side.
    rename_evidence = ({"renamed_interfaces_rejected": rejected_renames}
                       if rejected_renames else None)
    if rejected_renames:
        rec["renamed_interfaces_rejected"] = rejected_renames
    grouped, group_records = _resolve_declared_pad_groups(
        placement, functional_ports, renames=renames + splits, params=params)
    if group_records:
        rec["pad_group_resolution"] = group_records
    unresolved_groups = [r for r in group_records if not r["resolved_nets"]]
    if unresolved_groups:
        raise Refusal(
            "PAD_GROUP_UNRESOLVED",
            "the pad placement names group(s) which match no complete "
            "identifier in the design's own top-level port list: "
            + "; ".join(
                f"{r['side']}={r['statement']!r}" for r in unresolved_groups),
            rename_evidence)
    for side, group_nets in grouped.items():
        side_ports.setdefault(side, []).extend(group_nets)

    for side, test_nets in test_sides.items():
        side_ports.setdefault(side, []).extend(test_nets)

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
                      f"{missing[:8]}", rename_evidence)
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
    # ONE MACRO, SEVERAL LEFS, AND NO ARRIVAL ORDER. `dict.update` in
    # discovery order is a last-wins merge: a LEF that mentions a macro
    # without a CLASS or a SIZE overwrites one that gave it, and which one
    # wins is decided by whatever order `discover_io_lefs` happened to
    # return. Folding through `merge_source_records` groups by macro first
    # and reduces second, so a source that says nothing cannot erase one
    # that spoke, and the answer does not depend on the walk.
    per_lef = [lef.read_text(errors="replace") for lef in lefs]
    macro_sources: Dict[str, List[Path]] = {}
    pin_roles: Dict[str, Dict[str, Tuple[str, str]]] = {}
    pin_role_conflicts: Dict[str, List[str]] = {}
    for lef, text in zip(lefs, per_lef):
        mentioned = (set(PR.parse_lef_macro_classes(text))
                     | set(PR.parse_lef_macros(text)))
        for master in mentioned:
            macro_sources.setdefault(master, []).append(lef)
        for master, roles in PR.parse_lef_pin_roles(text).items():
            if master in pin_roles and pin_roles[master] != roles:
                pin_role_conflicts.setdefault(master, []).extend(
                    str(x) for x in (macro_sources.get(master) or [lef]))
                continue
            pin_roles[master] = roles
    classes, class_conflicts = _srm.merge_source_records(
        (PR.parse_lef_macro_classes(text) for text in per_lef),
        on_conflict="richer")
    sizes, size_conflicts = _srm.merge_source_records(
        (PR.parse_lef_macros(text) for text in per_lef),
        on_conflict="richer")
    if class_conflicts or size_conflicts:
        rec["io_library_lef_conflicts"] = {
            "macro_class": class_conflicts, "macro_size": size_conflicts,
            "policy": "richer",
            "note": ("two IO LEFs describe the same macro differently; the "
                     "fuller description is kept and the disagreement is "
                     "reported rather than decided by discovery order")}
    if pin_role_conflicts:
        rec["io_library_pin_role_conflicts"] = {
            master: sorted(set(paths))
            for master, paths in sorted(pin_role_conflicts.items())}
    rec["io_library_lefs"] = [str(p) for p in lefs]
    rec["io_master_count"] = len(classes)

    cfgs = PR.discover_io_library_configs(pdk_root, pdk)
    decls = PR.PdkDeclarations(cfgs, masters=sizes)
    rec["pdk_declared"] = {k: v for k, v in decls.values.items()}
    rec["pdk_declared_sources"] = dict(decls.sources)
    edge_um, edge_source = _effective_pad_edge_spacing(project, decls)
    rec["effective_pad_edge_spacing"] = {
        "value_um": edge_um,
        "source": edge_source,
    }

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
            declines: List[str] = []
            master, cls, fallback = _select_master(
                direction_of[net], classes, sizes, prefix,
                terminals, declines)
            chosen[inst] = {"port": net, "master": master,
                            "chosen_for_class": cls,
                            "terminal": terminals.get(master, "PAD"),
                            "terminal_from_pdk": master in terminals,
                            "direction": direction_of[net],
                            "class_fallback": fallback,
                            "selection_declines": declines}
            ordered[side].append(inst)

    # Supply cells are PHYSICAL-DESIGN freedom, not logical input ports.  The
    # runner opts in only after it has derived exactly one power and one ground
    # rail from the same PDK used by PDN generation.  Both must be present: a
    # one-polarity supply plan is an electrical open and is refused.
    supply_ports: List[str] = []
    if bool(power_net) != bool(ground_net):
        raise Refusal("SUPPLY_RAIL_PAIR_INCOMPLETE",
                      "power_net and ground_net must be supplied together")
    if power_net and ground_net:
        if power_net == ground_net:
            raise Refusal("SUPPLY_RAILS_COLLIDE",
                          "the derived power and ground rail have one name")
        conflicted = sorted(set(pin_role_conflicts) & {
            m for m, cls in classes.items() if cls.upper() == "PAD POWER"})
        if conflicted:
            raise Refusal(
                "SUPPLY_PAD_PIN_ROLE_CONFLICT",
                "the supply candidates disagree across LEFs: "
                + ", ".join(conflicted))
        ring_file = project / "phase3/stage3/pnr/io_power_ring_plan.json"
        ring_implementation = None
        if ring_file.is_file():
            try:
                ring_implementation = json.loads(ring_file.read_text())
            except (OSError, ValueError) as exc:
                raise Refusal("RING_IMPLEMENTATION_INVALID", f"cannot read {ring_file}: {exc}") from exc
            rec["ring_implementation_source"] = {"path": str(ring_file), "sha256": _sha256(ring_file)}
        pair, plan, _core_v = resolve_supply_pad_pair(
            classes, sizes, pin_roles, prefix, power_net, ground_net,
            macro_sources, terminals,
            liberty_texts=lambda: [x.read_text(errors="replace") for x in
                                   PR.discover_io_liberty(pdk_root, pdk)],
            netlist_texts=lambda: [x.read_text(errors="replace") for x in
                                   PR.discover_io_netlists(pdk_root, pdk)],
            core_liberty_text=lambda: (
                Path(str(tie_liberty)).read_text(errors="replace")
                if tie_liberty and Path(str(tie_liberty)).is_file() else None),
            core_liberty=str(tie_liberty or ""),
            ring_implementation=ring_implementation,
            verilog_texts=lambda: [x.read_text(errors="replace") for x in
                                    PR.discover_io_verilog(pdk_root, pdk)])
        if _core_v is not None:
            rec["supply_core_voltage"] = _core_v
        require_bonded_ring_rails(plan)
        supply_group = (pair + list(plan.get("supplemental_supply_pads") or [])
                       + list(plan.get("ring_connectors") or []))
        connect_bonded_ring_rails(supply_group, plan, pin_roles,
                                  power_net, ground_net, signal_pads=list(chosen.values()))
        # How far the PDN ring must stay from the pad edge for pdngen to strap
        # this pair to it (see `_supply_pad_strap_reach`); the runner reserves
        # it in the core inset. The first LEF to give a master its pins is
        # kept, as `pin_roles` keeps it.
        pin_ports: Dict[str, Dict[str, List[Tuple[str, Tuple[
            float, float, float, float]]]]] = {}
        for text in per_lef:
            for master, master_pins in PR.parse_lef_pin_ports(text).items():
                pin_ports.setdefault(master, master_pins)
        rotations, rotation_basis = _rotations(cfgs)
        strap_reach = _supply_pad_strap_reach(pair, pin_ports, sizes,
                                              pad_connect_layers, rotations)
        # Without a measured current, one pair is the exploration baseline.
        # A same-run PSM plan may request more; it is never an input-side pad
        # assignment and it never changes the signal instances or their order.
        side_widths = {
            side: sum(sizes.get(str(chosen[i]["master"]), (0.0, 0.0))[0]
                      for i in ordered[side])
            for side in SIDES}
        pair_count = 1
        if supply_plan is not None:
            if (supply_plan.get("verdict") != "PLANNED"
                    or not isinstance(supply_plan.get("pair_count"), int)
                    or supply_plan["pair_count"] < 1
                    or not supply_plan.get("subject_def_sha256")):
                raise Refusal("SUPPLY_ENTRY_PLAN_INVALID",
                              "the measured-current supply plan lacks a positive count or subject")
            pair_count = int(supply_plan["pair_count"])
        pair_width = sum(sizes[str(entry["master"])][0]
                         for entry in supply_group)
        supply_placement: Dict[str, List[List[str]]] = {s: [] for s in SIDES}
        if supply_plan is None:
            side = min(SIDES, key=lambda s: (side_widths[s], SIDES.index(s)))
            allocation = [side]
        else:
            die = float(supply_plan.get("die_side_um") or 0)
            corner_size = sizes.get(str(decls.values.get("PAD_CORNER")), (0, 0))
            edge = edge_um
            if not (die > 2 * (max(corner_size) + edge) and pair_width > 0):
                raise Refusal("SUPPLY_ENTRY_NO_LEGAL_SITE",
                              "die, corner, edge, or supply-master geometry is absent")
            # The first pass has already written the floorplan DEF. Reuse its
            # DBU scale, and the ring producer's site-grid/filler rules, when
            # the measured-current plan changes the supply population.
            floorplan = project / PR.FLOORPLAN_DEF_REL
            if not floorplan.is_file():
                raise Refusal("SUPPLY_ENTRY_FLOORPLAN_MISSING",
                              f"requested_pairs={pair_count}, die_side_um={die:g}; "
                              "the preceding PnR pass wrote no floorplan DEF at "
                              f"{PR.FLOORPLAN_DEF_REL} in this run")
            try:
                prior_die = PR.read_def(floorplan)
            except (PR.DefError, OSError) as exc:
                raise Refusal("SUPPLY_ENTRY_FLOORPLAN_UNREADABLE",
                              f"{PR.FLOORPLAN_DEF_REL}: {exc}") from exc
            units = prior_die.units
            prior_box = prior_die.box
            if any(abs(span - round(die * units)) > 1 for span in
                   (prior_box[2] - prior_box[0],
                    prior_box[3] - prior_box[1])):
                raise Refusal("SUPPLY_ENTRY_DIE_MISMATCH",
                              f"requested_pairs={pair_count}, plan_die_um={die:g}, "
                              f"prior_floorplan_die_um={[(prior_box[2] - prior_box[0]) / units, (prior_box[3] - prior_box[1]) / units]}")
            library = PR.IoLibrary(
                lefs, PR.discover_io_site_declarations(pdk_root, pdk))
            site = library.resolve_site(str(decls.values.get("PAD_SITE_NAME") or ""))
            if not site or not site.get("size") or site.get("class") != "PAD":
                raise Refusal("SUPPLY_ENTRY_SITE_UNRESOLVED",
                              f"PAD_SITE_NAME={decls.values.get('PAD_SITE_NAME')!r} "
                              "has no PAD-class site width in the selected IO library")
            site_w = int(round(float(site["size"][0]) * units))
            filler_names = decls.values.get("PAD_FILLERS") or []
            filler_widths = [int(round(sizes[name][0] * units))
                             for name in filler_names if name in sizes]
            legal: Dict[str, List[int]] = {}
            final_widths: Dict[str, Dict[int, int]] = {}
            for side in SIDES:
                corner = corner_size[0] if side in ("S", "N") else corner_size[1]
                available = int(round((die - 2 * (corner + edge)) * units))
                base_widths = [int(round(sizes[str(chosen[i]["master"])][0] * units))
                               for i in ordered[side]]
                supply_widths = [int(round(sizes[str(entry["master"])][0] * units))
                                 for entry in supply_group]
                legal[side] = []
                final_widths[side] = {}
                for count in range(pair_count + 1):
                    widths = base_widths + supply_widths * count
                    total = sum(widths)
                    if not widths:
                        good = PR.gap_is_fillable(available, filler_widths)
                    else:
                        spacing = PR.side_spacing(total, len(widths),
                                                  available, site_w)
                        good = (spacing is not None and all(
                            PR.gap_is_fillable(gap, filler_widths)
                            for gap in spacing))
                    if good:
                        legal[side].append(count)
                        final_widths[side][count] = total
            # Search complete legal side counts; a greedy pair-at-a-time move
            # can get stuck when count+1 is illegal but count+2 is legal.
            states = {0: ()}
            for side in SIDES:
                next_states = {}
                for used, counts in states.items():
                    for count in legal[side]:
                        total = used + count
                        if total > pair_count:
                            continue
                        candidate = counts + (count,)
                        old = next_states.get(total)
                        def rank(values):
                            widths = [final_widths[s][n]
                                      for s, n in zip(SIDES[:len(values)], values)]
                            return (max(widths), sum(w * w for w in widths), values)
                        if old is None or rank(candidate) < rank(old):
                            next_states[total] = candidate
                states = next_states
            selected = states.get(pair_count)
            if selected is None:
                raise Refusal(
                    "SUPPLY_ENTRY_RING_GEOMETRY_INFEASIBLE",
                    f"requested_pairs={pair_count}, die_side_um={die:g}, "
                    f"pair_width_um={pair_width:g}, site_width_um="
                    f"{site_w / units:g}, legal_pair_counts_by_side={legal}; "
                    "no assignment passes pad-ring width, corner-site and "
                    "declared-filler rules")
            allocation = [side for side, count in zip(SIDES, selected)
                          for _ in range(count)]
        supply_instances: List[str] = []
        for index, side in enumerate(allocation):
            group = []
            for entry in supply_group:
                suffix = "" if pair_count == 1 else f"_{index}"
                inst = f"u_pad_supply_{entry['kind']}{suffix}"
                if inst in chosen:
                    raise Refusal("INSTANCE_NAME_COLLISION",
                                  f"supply pad maps to existing {inst!r}")
                chosen[inst] = dict(entry)
                supply_instances.append(inst)
                group.append(inst)
            supply_placement[side].append(group)
        for side in SIDES:
            signals = ordered[side]
            groups = supply_placement[side]
            if not groups:
                continue
            # Preserve the relative signal order while distributing entries.
            buckets = [[] for _ in range(len(signals) + 1)]
            for n, group in enumerate(groups):
                buckets[(n * len(buckets)) // len(groups)].extend(group)
            ordered[side] = [item for n, signal in enumerate(signals)
                             for item in [*buckets[n], signal]] + buckets[-1]
        supply_ports = list(dict.fromkeys(
            str(entry["port"]) for entry in supply_group if entry.get("is_supply_pad")))
        source_file = (Path(pdk_root) / str(pdk) / "SOURCES"
                       if pdk_root and pdk else None)
        plan.update({
            "placement_side": allocation[0] if pair_count == 1 else None,
            "placement_basis": ("minimum pair on shortest signal edge" if pair_count == 1
                                else "measured-current pairs balanced across legal sides; signal order retained"),
            "pad_strap_reach": strap_reach,
            "pair_count": pair_count,
            "pairs_by_side": {s: len(supply_placement[s]) for s in SIDES},
            "measured_supply_entry_plan": supply_plan,
            "signal_width_before_um": side_widths,
            "instances": supply_instances,
            "pdk_sources": ({"path": str(source_file),
                             "sha256": _sha256(source_file),
                             "text": source_file.read_text(errors="replace").strip()}
                            if source_file and source_file.is_file() else None),
        })
        rec["power_pad_plan"] = plan

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
        if rc.get("is_supply_pad") or rc.get("is_ring_connector"):
            continue
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
        core_power_pins = sorted(pin for pin, net in
                                 (rc.get('power_connections') or {}).items()
                                 if net == (rec.get('power_pad_plan') or {}).get('power_net'))
        faces = PR.pad_cell_faces(lib_cells[master], str(rc["direction"]),
                                  declared_aux.get(str(rc["port"])),
                                  master=master,
                                  **({'core_power_pins': core_power_pins}
                                     if core_power_pins else {}))
        if faces.refused:
            faces_refused[inst] = faces.refused
            continue
        rc["terminal"] = faces.terminal
        rc["core_pin"] = faces.core_pin
        rc["ties"] = dict(faces.ties)
        rc["tie_reasons"] = dict(faces.reasons)
        rc["local_tie_sources"] = _local_pad_tie_sources(
            lib_cells[master], faces.ties, rc.get("power_connections") or {})
        for pin, level in sorted(faces.ties.items()):
            entry = {"instance": inst, "port": rc["port"], "pin": pin,
                     "level": level, "reason": faces.reasons.get(pin, "")}
            (aux_defaulted if faces.reasons.get(pin, "").startswith("DEFAULTED")
             else aux_declared).append(entry)
    rec["core_side_refusals"] = faces_refused
    rec["aux_pins_defaulted"] = aux_defaulted
    rec["aux_pins_tied_by_derivation"] = aux_declared
    rec["aux_pins_declared_by_design"] = sorted(declared_aux)
    tie_cells = {
        1: {"master": str(tie_high_cell or ""),
            "pin": str(tie_high_pin or "")},
        0: {"master": str(tie_low_cell or ""),
            "pin": str(tie_low_pin or "")},
    }
    aux_signals, used_ties = _auxiliary_pin_signal_connections(
        chosen, tie_cells, liberty=str(tie_liberty or ""))
    rec["aux_pin_signal_connections"] = [
        {"instance": inst, "port": chosen[inst].get("port"), "pin": pin,
         "level": int(dict(chosen[inst].get("ties") or {})[pin]),
         "net": net,
         "tie_instance": used_ties[(inst, pin)]["instance"],
         "tie_master": used_ties[(inst, pin)]["master"],
         "tie_pin": used_ties[(inst, pin)]["pin"]}
        for inst, pins in sorted(aux_signals.items())
        for pin, net in sorted(pins.items())
    ]
    rec["aux_tie_cells"] = [
        dict(tie) for _endpoint, tie in sorted(used_ties.items())
        if tie.get("source") != "pad"]
    rec["aux_pad_local_tie_sources"] = [
        dict(tie) for _endpoint, tie in sorted(used_ties.items())
        if tie.get("source") == "pad"]
    if used_ties:
        liberty_path = Path(str(tie_liberty or ""))
        rec["aux_tie_cell_provenance"] = {
            "derivation": (
                "cell master and output pin discovered from the active "
                "standard-cell Liberty by phase3_one_shot_runner"),
            "liberty": str(tie_liberty or ""),
            "liberty_sha256": (_sha256(liberty_path)
                               if liberty_path.is_file() else None),
        }

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
    # A bussed pad pin is connected as one concatenation ordered by the IO
    # library's own Verilog; read it only when some connection selects a bit.
    _pins = [str(p) for r in chosen.values()
             for p in (list((r.get("ties") or {}).keys())
                       + list((r.get("supply_connections") or {}).keys())
                       + [r.get("terminal") or "", r.get("core_pin") or ""])]
    bus_ports = (io_bus_ports([x.read_text(errors="replace") for x in
                               PR.discover_io_verilog(pdk_root, pdk)])
                 if any(_BIT_PIN_RE.match(p) for p in _pins) else None)
    if bus_ports is not None:
        rec["io_bus_ports"] = {m: {p: list(r) for p, r in b.items()}
                               for m, b in sorted(bus_ports.items())
                               if m in {str(c.get("master")) for c in
                                        chosen.values()}}
    out_v.write_text(_emit_verilog(top, core, ordered, chosen, ports,
                                   supply_ports, tie_cells,
                                   str(tie_liberty or ""), bus_ports))

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
    # declared PAD_EDGE_SPACING of 26. The effective term is resolved through
    # the same `pad_assignment_gen.compose` precedence that writes the config,
    # so the two cannot disagree; the raw library value remains recorded, and
    # a library that declares none contributes upstream's own default of 0.
    corner_master = decls.values.get("PAD_CORNER")
    corner_w = sizes.get(str(corner_master), (0.0, 0.0))[0]
    side_um: Dict[str, float] = {}
    for side in SIDES:
        pads = sum(sizes.get(str(chosen[i]["master"]), (0.0, 0.0))[0]
                   for i in ordered[side])
        side_um[side] = 2.0 * edge_um + 2.0 * corner_w + pads
    need = max(side_um.values()) if side_um else 0.0
    die_um = float(int(need) + (1 if need > int(need) else 0))
    # ── HOW DEEP THE RING IS, and why the core must be told ──────────────
    # MEASURED on spm x gf180mcuD (v1.16.38): the floorplan inset the runner
    # used was a flat 10 um, so `CORE 20160 23520 -> 6283200 6279840` inside a
    # `DIEAREA 0 0 6324000 6324000` — the core overlapped the pad ring by
    # ~366 um on every side. Placement and routing therefore ran UNDER the
    # pads, where the pads' own obstruction fills M1 and M2, and the first
    # detailed_route reported 3515 violations of which 3112 were Shorts and
    # 3104 of those lay inside that band, 2054 of them naming an IO instance.
    #
    # The band is the IO ROW's depth plus the effective edge spacing, and both
    # terms are read: spacing from the shared declaration-over-library
    # authority and depth from each PLACED master's own LEF SIZE — its HEIGHT
    # for a pad on a horizontal side, and a corner cell counted at its larger
    # dimension because it occupies both. A master whose
    # SIZE the LEF does not carry contributes NOTHING and is NAMED, so an
    # unreadable library yields no depth rather than a default one.
    depth_terms: Dict[str, float] = {}
    unsized: List[str] = []
    for inst, r in sorted(chosen.items()):
        master = str(r["master"])
        size = sizes.get(master)
        if not size:
            unsized.append(master)
            continue
        depth_terms[master] = max(depth_terms.get(master, 0.0), float(size[1]))
    if corner_master:
        csize = sizes.get(str(corner_master))
        if csize:
            depth_terms[str(corner_master)] = max(
                depth_terms.get(str(corner_master), 0.0),
                float(max(csize)))
        else:
            unsized.append(str(corner_master))
    ring_depth = (max(depth_terms.values()) + edge_um) if depth_terms else None
    strap = (rec.get("power_pad_plan") or {}).get("pad_strap_reach") or {}
    rec["die_required_um"] = {
        "ring_depth_um": ring_depth,
        # How far beyond the pad edge the PDN ring's far edge must lie for
        # pdngen to keep the supply pads' straps (`_supply_pad_strap_reach`).
        # None when there is no supply pair or its geometry is not measured.
        "pad_strap_reach_um": strap.get("reach_um"),
        "ring_depth_terms_um": depth_terms,
        "ring_depth_masters_without_a_lef_size": sorted(set(unsized)),
        "ring_depth_basis": (
            "the deepest PLACED ring master (each pad at its own LEF SIZE "
            "height, the corner cell at its larger dimension because it "
            "occupies both sides) plus the effective PAD_EDGE_SPACING whose "
            "source is recorded beside this field. This is how far a "
            "placeable core must stay "
            "back from the die edge; a master with no LEF SIZE contributes "
            "nothing and is named in "
            "`ring_depth_masters_without_a_lef_size`, so a consumer can "
            "refuse rather than inset by a default"),
        "per_side": side_um,
        "corner_master": corner_master,
        "corner_width_um": corner_w,
        "edge_spacing_um": edge_um,
        "edge_spacing_source": edge_source,
        "die_side_um": die_um,
        "basis": ("twice the effective PAD_EDGE_SPACING, plus two "
                  "corner cells, plus the pads on the longest side, at each "
                  "master's own LEF width, rounded up to a whole micron -- the "
                  "same three terms `pad_ring_gen.side_width` subtracts, in "
                  "the same order; the shorter sides are closed by the "
                  "declared fillers"),
    }

    rec["not_written"] = {}
    if not supply_ports:
        rec["not_written"]["power_pads"] = (
            "the caller supplied no PDK-derived power/ground rail pair; no "
            "supply pad is written and this absence is not a PASS")
    rec["fallback_masters"] = sorted(
        i for i, r in chosen.items() if r["class_fallback"])
    return 0, rec


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", nargs="?", default=".")
    ap.add_argument("--pdk-root", default=None)
    ap.add_argument("--pdk", default=None)
    ap.add_argument("--power-net", default=None)
    ap.add_argument("--ground-net", default=None)
    ap.add_argument("--supply-plan", default=None)
    ap.add_argument("--tie-high-cell", default=None)
    ap.add_argument("--tie-high-pin", default=None)
    ap.add_argument("--tie-low-cell", default=None)
    ap.add_argument("--tie-low-pin", default=None)
    ap.add_argument("--tie-liberty", default=None)
    ap.add_argument("--pad-connect-layers", default=None,
                    help="JSON list of the layers the PDN connects pads on "
                         "(the PDK's pdn_ring.connect_to_pad_layers); only "
                         "supply-pad pins on them are measured for strap reach")
    ap.add_argument("--json", dest="out_json", default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)

    project = Path(args.project).resolve()
    pdk_root = args.pdk_root or os.environ.get("PDK_ROOT")
    pdk = args.pdk or os.environ.get("PDK")

    try:
        plan = json.loads(Path(args.supply_plan).read_text()) if args.supply_plan else None
        rc, rec = run(
            project, pdk_root, pdk, args.power_net, args.ground_net,
            args.tie_high_cell, args.tie_high_pin,
            args.tie_low_cell, args.tie_low_pin, args.tie_liberty, plan,
            json.loads(args.pad_connect_layers)
            if args.pad_connect_layers else None)
    except Unavailable as exc:
        rc, rec = 2, {"program": PROGRAM, "verdict": "NOT_AVAILABLE",
                      "rule": exc.rule, "findings": [exc.message]}
    except Refusal as exc:
        rc, rec = 1, {"program": PROGRAM, "verdict": "REFUSE",
                      "rule": exc.rule, "findings": [exc.message],
                      **exc.evidence}

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
    _aa.write_text(target,
                   json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
