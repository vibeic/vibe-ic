#!/usr/bin/env python3
"""analog_a2_topology_emit.py — the A2 topology PRODUCER that was missing.

WHAT WAS BROKEN
===============
Flow step A2 ("Analog Topology Selection") declares
`phase{2,3}/analog/<block>/topology.md`. Nothing writes it, so
`analog_a2_topology_select_check` returns rc=2 on every block and the runner
reports WAIVED. Worse, A2 had no consumer either: `analog_real_corner_sweep`'s
`topology_override` selects a per-block-TYPE deck out of a hardcoded table and
its own comment says the type selection "does NOT use topology.md keyword
match". So even a perfect topology.md changed nothing downstream — **there was
no data path from A2 to anything**.

WHAT THIS PROGRAM DOES
======================
For every declared analog block whose canonical TYPE is in the topology
library below, it emits BOTH:

  * `topology.md`   — the artefact the flow declares and the A2 gate reads:
                      the named topology, the port table, the device/role
                      table, the design trade-offs, and the PDK device
                      constants READ from `programs/pdk_registry.json`
                      (`analog_device_params`) rather than retyped.
  * `topology.json` — the machine-readable topology IR, and the first real
                      A2 -> A3 data path. `analog_a3_netlist_emit` renders
                      SPICE from THIS and has no per-type template of its
                      own, which is what stops A3 from being a template table
                      with a design name substituted in.

Emitting a second file is legal: the flow declares `required_outputs`, not an
exclusive list.

AN ENTRY MAY REFUSE ITSELF — `requires_bound` AND THE STAGE TEMPLATE
===================================================================
`delta_sigma` used to sit in LIBRARY_GAPS under a reason that is right about
an UNBOUND block and wrong as an unconditional one: "the switched-capacitor
integrator's capacitor ratio IS the loop coefficient, so the structure is not
separable from the sizing". Read as a requirement rather than a verdict, it
says what the entry needs — and a real declaration was measured to bind all of
it (`order`, `osr`, `enob`, `vref` reached `phase3/analog/<block>/spec.json`)
and reach nothing, because the library had no way to be conditional.

So an entry may now declare `requires_bound` / `requires_pdk_measured` /
`requires_domain` / `requires_derived`. When any one is unmet the block gets
`topology_gap.json` NAMING the unmet requirement and rc 2 — never a topology
emitted on a default, which the A2 gate could not tell from a real one because
it measures vocabulary. And an entry may declare a repeated `stage`, expanded
here in Python before the PDK layout floor runs, so the DEVICE COUNT follows
from a bound spec row and `analog_a3_netlist_emit` still sees a flat IR of
exactly the schema it always did.

An entry that declares none of these keys takes byte-identical paths to the
ones it took before.

WHAT IT DELIBERATELY DOES **NOT** DO
====================================
  * A block TYPE that is not in the library gets **no topology.md**. It gets
    `topology_gap.json` naming the type, the reason the deterministic track
    cannot decide, and the skill that must take over — and rc 2, so the runner
    keeps reporting WAIVED. The library is deliberately small and every entry
    is a textbook circuit class; padding it with a plausible-looking structure
    for a class nobody verified is the defect this round exists to remove.
  * The topology is selected from the block's CIRCUIT CLASS. When the block
    carries no bound spec, `selection_basis` is `block_type_only` and
    `design_inputs_bound` is `[]` — stated in both artefacts, so no reader can
    mistake a class-library topology for one derived from this design.

DRAWN GEOMETRY IS FLOORED TO THE TARGET PDK, NOT TO A LIBRARY CONSTANT
======================================================================
A library constant cannot know what the target process will let you draw. The
`res` width in this library was a static 0.35 and stayed 0.35 on every PDK,
including ones whose poly-resistor rule states a wider minimum — so the layout
generator clamped the DRAWN device up to the rule while the netlist kept the
constant, and KLayout-extract -> netgen then reported a device-property
mismatch on every block built from this library (vibe-ic#1952).

So: every `constants` entry the library declares as a drawn WIDTH (via
`constant_roles`) and every device's `w` is FLOORED to the resolved family's
`analog_device_layout_minima` record, read through
`programs/pdk_analog_layout_minima.py`. The floor is DERIVED — the number is
the registry's record of the PDK's OWN rule, carrying that rule's id and text —
and it is a FLOOR, so a family whose minimum sits below the library nominal
comes out byte-identical. Every clamp that fires is written into
`_provenance.layout_minima.clamps` and `fields_clamped`, and stated in
`topology.md`; a family the registry carries no measured minimum for floors
NOTHING and says so, rather than quietly passing. No family name appears in
this file — which family is affected is entirely a property of the registry
data.

A2 measures VOCABULARY, not structure — and this producer must not exploit it
=============================================================================
`analog_a2_topology_select_check` accepts any file over 200 bytes carrying one
circuit-specific word, and several BLOCK NAMES are themselves in its panel
(`ldo`, `bandgap`, `oscillator`, `comparator`, `charge pump`). Measured: a
content-free office-memo paragraph headed `# Topology - ldo` PASSES A2. Every
document this producer writes therefore has to clear the floor on its own
prose, with the block name removed — and
`test_analog_a2_topology_emit.py::test_topology_md_clears_the_gate_on_a_keyword_free_block_name`
holds it to that against a block called `blk_alpha`.

PROVENANCE IS STAMPED INTO BOTH ARTEFACTS
=========================================
`topology.json#_provenance` and `topology.md`'s `## Provenance` section carry
the producer, the library entry and its circuit-class citation, the inputs
actually read (with digests), which knobs bound to a spec value and which fell
back to a library default (`fields_defaulted`), and `ai_handoff`.

RC CONTRACT
===========
    rc 0  at least one selected block got a topology (or already carried a
          topology.md this producer must not overwrite).
    rc 1  the inputs themselves are unusable (no project dir / no block list).
    rc 2  no selected block's type is in the library. `topology_gap.json`
          written per block; hand off to skill `analog-topology-select`.

chip-AGNOSTIC: every library entry is keyed on a generic circuit class and is
justifiable from public circuit vocabulary alone. No chip, PDK SKU, vendor or
part number appears below.

Usage:
    python3 analog_a2_topology_emit.py <project> [--block NAME] [--pdk sky130]
                                       [--json OUT]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _analog_producer_common as _pc  # noqa: E402
import pdk_analog_device_params as _pdp  # noqa: E402
import pdk_analog_layout_minima as _minima  # noqa: E402

PRODUCER = "analog_a2_topology_emit"
PROVENANCE_SCHEMA = 1
SKILL = "analog-topology-select"
IR_SCHEMA = 1

_CANONICAL_ANALOG = "phase3/analog"
_DECLARED_ANALOG = "phase1/analog"
# The registry path itself now lives with the one reader that opens it
# (`pdk_analog_layout_minima`) — a second copy here would be a second thing to
# keep pointing at the same file.

# Terminal count of each device ROLE, as the open PDKs' own `.subckt` headers
# declare them. The renderer checks the IR against this before it emits, so a
# net-count mistake is caught at production time and not by ngspice aborting
# "Too few parameters for subcircuit".
ROLE_TERMINALS = {
    "nmos": 4,      # d g s b
    "pmos": 4,      # d g s b
    "res": 3,       # r0 r1 sub
    "cap": 2,       # c0 c1
}

# Library key: `constant_roles` maps a `constants` name to the device ROLE
# whose DRAWN WIDTH it is. Only a constant listed here is subject to the PDK
# layout floor — `l_unit` is a length in the same units and must NOT be floored
# by a width rule, and inferring "is this a width?" from a name would do
# exactly that. An entry that declares nothing is floored on its devices only.
CONSTANT_ROLES_KEY = "constant_roles"

# ── SPEC-BOUND ADMISSION: the keys that let a library entry REFUSE ITSELF ──
#
# WHY THIS EXISTS. `delta_sigma` sat in LIBRARY_GAPS under a reason that is
# CORRECT about an unbound block and WRONG as an unconditional refusal: "the
# switched-capacitor integrator's capacitor ratio IS the loop coefficient, so
# the structure is not separable from the sizing". Both halves of that
# sentence are true, and together they state what the entry NEEDS rather than
# that it cannot exist — a block whose declaration BINDS the sizing inputs has
# a determined structure. Measured on a real declaration: `order`, `osr`,
# `enob` and `vref` were all bound, travelled the whole way to
# `phase3/analog/<block>/spec.json`, and reached nothing, because the library
# had no way to say "selectable only when these are bound".
#
# An entry that declares none of these keys behaves exactly as before, which
# is why every pre-existing entry emits byte-identical artefacts.
#
#: {name: {"unit": <declared unit>, "why": <what it determines>}} — spec rows
#: that must be BOUND, with the unit the entry's expressions assume.
REQUIRES_BOUND_KEY = "requires_bound"
#: [name, ...] — the MEASURED process constants the entry's expressions read.
#: `_resolve_params` catches a KeyError on an unknown name and CONTINUES, so
#: an entry whose sizing needs a characterised process must declare it here or
#: it degrades into a library nominal with nothing recording that it did.
REQUIRES_PDK_MEASURED_KEY = "requires_pdk_measured"
#: {name: [admitted values]} — a DISCRETE requirement. The order-N coefficient
#: set is the case this exists for: a set is admitted per order, and an order
#: nobody authored a set for is refused BY NAME rather than falling back to a
#: neighbouring one.
# The unit an entry's device expressions are WRITTEN FOR, per spec field.
# Distinct from the unit check inside `requires_bound`: that one also demands
# the row EXIST, which refuses a block whose declaration is simply thin. This
# key says nothing about a missing row -- the expression over it drops and the
# device keeps its library nominal, which `analog_a3_netlist_emit` already
# discloses as `structure_only`. It fires only on a row that IS bound and
# declares a unit the expressions do not assume, because that is the case the
# unit-free expression environment silently mis-scales instead of refusing.
SIZING_UNIT_CONTRACT_KEY = "sizing_unit_contract"

REQUIRES_DOMAIN_KEY = "requires_domain"
#: [{"name","expr","min","max","why"}] — a bound on a value the entry DERIVES.
#: An admission condition on the INPUTS cannot see that a legal-looking
#: declaration derives an undrawable device; this can.
REQUIRES_DERIVED_KEY = "requires_derived"
#: The repeated-stage template — see `expand_stages`.
STAGE_KEY = "stage"
#: {"<order>": [per-stage coefficient, ...]}. JSON object keys are strings and
#: this table is read back from the emitted IR as well as from source, so the
#: key is a string in both places rather than an int here and a str there.
COEFFICIENT_SETS_KEY = "coefficient_sets"

#: Unit tokens that all mean "a pure number". A spec row's `unit` is
#: human-typed prose lifted from a datasheet table, so the em-dash, the
#: hyphen and the empty string all appear for the same thing. `bit` is here
#: because a resolution in bits IS a dimensionless count: an entry declaring
#: `unit: "bit"` and a document declaring `—` are naming the same number.
DIMENSIONLESS_UNITS = frozenset(
    {"", "-", "—", "–", "none", "n/a", "na", "ratio", "x",
     "bit", "bits", "count"})

# The sampling capacitor of a switched-capacitor delta-sigma stage, in fF,
# written ONCE because two places need the same formula and a second copy is a
# second thing to keep correct: the admission bound that refuses an undrawable
# result, and the per-stage `device_param_exprs` entry that sizes the device.
#
#   sampled kT/C noise, spread over the oversampled band  =  kT / (C * OSR)
#   quantisation noise power of one LSB                   =  LSB^2 / 12
#   LSB                                                   =  Vref / 2**ENOB
#
# Setting the first equal to the second and solving for C:
#
#   C  =  12 * k*T * 2**(2*ENOB) / (OSR * Vref**2)
#
# Every name in it is either a bound spec row (`enob`, `osr`, `vref`), a
# universal physical constant, or a MEASURED process constant read from the
# registry — no design, PDK SKU or vendor number appears.
SAMPLING_CAP_FF_EXPR = (
    "noise_budget_factor * kt_j_300k * farad_to_ff * 2 ** (2 * enob) "
    "/ (osr * vref ** 2)")
#: ...and the DRAWN LENGTH that realises it at the library drawn width.
#: Deliberately a LENGTH: a width is subject to the PDK layout floor applied
#: in `build_ir`, and a `device_param_exprs` entry is resolved one step later
#: in `analog_a3_netlist_emit`, so a width written here would step over the
#: floor that `floor_geometry_to_pdk` had already applied.
SAMPLING_CAP_L_EXPR = (
    "(" + SAMPLING_CAP_FF_EXPR + ") / (cap_area_ff_per_um2 * w_cap)")


# ═══════════════════════════════════════════════════════════════════════════
# THE TOPOLOGY LIBRARY
#
# One entry per CIRCUIT CLASS. Every entry is a textbook topology: it is
# citable from public analog-design vocabulary, it is not tuned to any design,
# and it has been rendered and simulated end-to-end by
# `analog_a3_netlist_emit --verify-sim`. An entry is admitted ONLY when that
# has been done; the classes listed in LIBRARY_GAPS below are absent on
# purpose and say why.
# ═══════════════════════════════════════════════════════════════════════════
LIBRARY: Dict[str, Dict[str, Any]] = {

    "ldo": {
        "topology": ("NMOS-input five-transistor OTA driving a PMOS series "
                     "pass device, closed by a resistive feedback divider, "
                     "Miller-compensated"),
        "circuit_class_citation": (
            "series linear regulator: error amplifier + series pass element "
            "+ resistive feedback divider (Gray & Meyer ch.8; Rincon-Mora, "
            "Analog IC Design with Low-Dropout Regulators ch.2)"),
        "ports": ["vdd", "vss", "vref", "vout"],
        "rails": {"vdd": "vdd", "vss": "vss"},
        "internal_nets": ["nbias", "ntail", "nd1", "vg", "vfb"],
        "constants": {"l_unit": 20.0, "w_res": 0.35,
                      # The share of the bound quiescent-current budget the
                      # FEEDBACK DIVIDER is allowed to draw. A regulator's Iq
                      # is spent on the bias branch, the error amplifier and
                      # the divider string; the split between them is a design
                      # allocation no input states, so it is a library
                      # constant and it is written down here rather than
                      # buried in an expression. It is the only free number in
                      # the divider sizing: everything else comes from the
                      # bound spec and the measured sheet resistance.
                      "iq_divider_fraction": 0.2,
                      # microamp -> amp, so the bound `iq` row (declared in
                      # µA, and REFUSED by `requires_bound` in any other unit)
                      # reaches Ohm's law in SI.
                      "ua_to_a": 1.0e-6},
        # `w_res` is the DRAWN WIDTH of the `res` devices below, so it is
        # floored to the target PDK's poly-resistor minimum; `l_unit` is a
        # length and is deliberately not listed.
        "constant_roles": {"w_res": "res"},
        "devices": [
            {"name": "mn_bias", "role": "nmos", "function":
             "diode-connected bias reference of the tail current mirror",
             "nets": ["nbias", "nbias", "vss", "vss"], "w": 2.0, "l": 2.0},
            {"name": "r_bias", "role": "res", "function":
             "bias-setting resistor from the supply into the mirror diode",
             "nets": ["vdd", "nbias", "vss"], "w": 0.35, "l": 60.0},
            {"name": "mn_tail", "role": "nmos", "function":
             "tail current source of the differential pair (mirror output)",
             "nets": ["ntail", "nbias", "vss", "vss"], "w": 4.0, "l": 2.0},
            {"name": "mn1", "role": "nmos", "function":
             "differential pair, feedback side",
             "nets": ["nd1", "vfb", "ntail", "vss"], "w": 8.0, "l": 1.0},
            {"name": "mn2", "role": "nmos", "function":
             "differential pair, reference side",
             "nets": ["vg", "vref", "ntail", "vss"], "w": 8.0, "l": 1.0},
            {"name": "mp1", "role": "pmos", "function":
             "current-mirror load, diode-connected leg",
             "nets": ["nd1", "nd1", "vdd", "vdd"], "w": 4.0, "l": 1.0},
            {"name": "mp2", "role": "pmos", "function":
             "current-mirror load, output leg (single-ended conversion)",
             "nets": ["vg", "nd1", "vdd", "vdd"], "w": 4.0, "l": 1.0},
            {"name": "mp_pass", "role": "pmos", "function":
             "series pass device; m is the drive-strength knob",
             "nets": ["vout", "vg", "vdd", "vdd"], "w": 5.0, "l": 0.5,
             "m": 20},
            {"name": "cc", "role": "cap", "function":
             "Miller compensation across the pass device gate drive",
             "nets": ["vg", "vout"], "w": 10.0, "l": 10.0},
            {"name": "r1", "role": "res", "function":
             "feedback divider, upper leg (vout -> vfb)",
             "nets": ["vout", "vfb", "vss"], "w": 0.35, "l": 20.0},
            {"name": "r2", "role": "res", "function":
             "feedback divider, lower leg (vfb -> vss)",
             "nets": ["vfb", "vss", "vss"], "w": 0.35, "l": 20.0},
        ],
        # Knobs the SPEC can bind. `expr` is evaluated over the block's bound
        # spec values; when a name in it is absent the `default` is used AND
        # recorded in `fields_defaulted` — never silently.
        "spec_knobs": [
            {"name": "divider_ratio", "expr": "vout / vref", "default": 2.0,
             "rationale": ("the feedback divider sets Vout = Vref * "
                           "(1 + r1/r2); with only Vout bound the ratio is "
                           "undetermined and the library default stands in")},
        ],
        "device_param_exprs": [
            # Split the spec-sized total between the two legs in the ratio the
            # divider has to realise. Both legs therefore carry a BOUND spec
            # value, which is what separates a sized regulator from the
            # circuit class wearing this design's name.
            # The divider's TOTAL drawn length, in microns, comes from the
            # bound output voltage and the bound quiescent budget:
            #   I_div = iq * ua_to_a * iq_divider_fraction     [A]
            #   R_div = vout / I_div                           [Ohm] Ohm's law
            #   L_tot = R_div * w_res / rsheet_ohm_per_sq      [um]  sheet
            # Two BOUND spec rows and one MEASURED process constant; the only
            # library number in it is the allocation fraction declared above.
            # It is written inline in both legs rather than as a `spec_knob`
            # because a knob expression is resolved against the bound spec
            # values ALONE, and this one also needs the entry's constants and
            # the process's measured sheet -- which is exactly the environment
            # `analog_a3_netlist_emit._resolve_params` seeds for a device
            # expression. Splitting the total between the legs in the ratio
            # the divider has to realise leaves BOTH legs carrying a bound
            # spec value, which is what separates a sized regulator from the
            # circuit class wearing this design's name.
            # ORDER IS LOAD-BEARING. `_resolve_params` walks this list in
            # order, SKIPS an expression naming anything the environment does
            # not carry, and lets a later expression overwrite an earlier one
            # for the same device parameter. So the unit-element forms come
            # FIRST and the budget-sized forms SECOND: a declaration that
            # binds no `iq` keeps exactly the geometry it got before this
            # entry learned to size the string, and one that binds it gets
            # the sized length instead. Neither case needs a conditional the
            # IR has no way to express.
            {"device": "r1", "param": "l",
             "expr": "l_unit * (divider_ratio - 1)",
             "rationale": "r1/r2 = divider_ratio - 1 at equal sheet width"},
            {"device": "r2", "param": "l", "expr": "l_unit",
             "rationale": "divider lower leg is the unit element"},
            {"device": "r1", "param": "l",
             "expr": ("(vout / (iq * ua_to_a * iq_divider_fraction)) "
                      "* w_res / rsheet_ohm_per_sq "
                      "* (divider_ratio - 1) / divider_ratio"),
             "rationale": ("upper leg: r1/r2 = divider_ratio - 1, scaled to "
                           "the total length the bound Iq budget allows")},
            {"device": "r2", "param": "l",
             "expr": ("(vout / (iq * ua_to_a * iq_divider_fraction)) "
                      "* w_res / rsheet_ohm_per_sq / divider_ratio"),
             "rationale": ("lower leg: the remainder of the bound-Iq-sized "
                           "divider string")},
        ],
        # The unit the two expressions above are WRITTEN FOR, checked only on
        # a row the declaration actually carries.
        #
        # NOT `requires_bound`. That key refuses a block whose declaration is
        # missing the row, and this entry is the library's generic simple
        # regulator: a design that binds nothing has always got the library
        # nominal here, and `analog_a3_netlist_emit` already DISCLOSES that
        # outcome as `design_content=structure_only`. Turning that disclosed
        # nominal into a refusal is a separate decision about an entry many
        # designs reach, and it is not this one. Measured: declaring these two
        # rows `requires_bound` turned 16 passing tests of unrelated subjects
        # red, all of them driving this entry with a declaration that binds
        # nothing at all.
        #
        # What IS refused is the case the expression environment cannot
        # survive: a row that IS bound and declares a unit the expressions do
        # not assume. `_resolve_params` carries no units, so a quiescent
        # budget stated in mA would be read as microamps and size the divider
        # a thousand times wrong with nothing recording it. Absent row -> the
        # expression drops and the device keeps its library nominal, exactly
        # as before; present-but-mis-united row -> a named refusal.
        SIZING_UNIT_CONTRACT_KEY: {
            "vout": {"unit": "V", "why":
                     "the regulated output is the numerator of the divider "
                     "resistance the bound budget has to realise"},
            "iq": {"unit": "\u00b5A", "why":
                   "the quiescent-current budget is what sizes the divider "
                   "string, and it enters Ohm's law through a microamp "
                   "conversion written into the expression"},
        },
        "tradeoffs": [
            "A PMOS series pass device gives the lowest dropout for a given "
            "area but puts a low-frequency pole at the output, so the "
            "compensation capacitor and the load range are coupled.",
            "An NMOS-input differential pair keeps the input common-mode "
            "near the reference and gives a higher transconductance per "
            "unit current than a PMOS-input pair, at the cost of a lower "
            "input common-mode ceiling.",
            "Making the divider high-ohmic saves quiescent current and "
            "costs phase margin, because the divider resistance and the "
            "feedback node capacitance form an extra pole.",
        ],
        "analyses_implied": ["op", "dc", "ac"],
        # The stimulus the A3 renderer wraps this DUT in. It lives HERE, with
        # the circuit class, so `analog_a3_netlist_emit` stays a generic
        # renderer with no per-type knowledge. `supply_exprs` is tried in
        # order against the bound spec and the PDK constants; the first that
        # resolves wins and is recorded as a testbench CONDITION, which is not
        # part of the netlist and never a spec.
        "testbench": {
            "supply_exprs": ["vin", "vout + 1.5"],
            "env_exprs": {"vref": "vout / divider_ratio"},
            "conditions": [
                "supply = {supply} V (bound Vin if the spec carries one, "
                "else the bound Vout plus 1.5 V of headroom — a testbench "
                "condition, not a spec)",
                "reference = {vref} V, implied by the bound Vout and the "
                "divider ratio",
                "load = 1 kOhm to ground (testbench condition)",
            ],
            "stimulus": ["v_vdd vdd 0 {supply}", "v_vref vref 0 {vref}"],
            "cards": ["r_load vout 0 1k"],
            "control": ["op", "let vo = v(vout)",
                        "echo \"MEAS vout=\" $&vo"],
        },
    },

    "pull": {
        "topology": ("single long-channel NMOS pull-down (weak keeper); the "
                     "gate is the enable and the drain is the pulled node"),
        "circuit_class_citation": (
            "weak pull device / bus keeper: one long-channel MOSFET biased "
            "in the linear region, sized for an effective resistance"),
        "ports": ["vss", "en", "pad"],
        "rails": {"vss": "vss"},
        "internal_nets": [],
        "constants": {},
        "devices": [
            {"name": "mn_pull", "role": "nmos", "function":
             "the pull-down transistor; W/L sets the effective resistance",
             "nets": ["pad", "en", "vss", "vss"], "w": 0.5, "l": 20.0},
        ],
        "spec_knobs": [],
        "device_param_exprs": [],
        "sizing_handoff": (
            "turning a target effective resistance into W/L needs the "
            "process transconductance and the operating bias point; that is "
            "sizing judgment and belongs to skill `analog-sizing`. The "
            "geometry below is the library nominal, NOT a solution of the "
            "bound target."),
        "tradeoffs": [
            "A long channel buys a high effective resistance in a small "
            "width, at the cost of area and of a large gate capacitance on "
            "the enable.",
            "Because the transistor is a resistor only in the linear region, "
            "the effective resistance is a function of the pulled node "
            "voltage; a single number is a small-signal operating-point "
            "statement, not a device constant.",
        ],
        "analyses_implied": ["op", "dc"],
        "testbench": {
            "supply_exprs": ["nominal_supply_v"],
            "env_exprs": {"vprobe": "supply / 4"},
            "conditions": [
                "enable driven to {supply} V (the PDK's nominal supply)",
                "the pulled node is probed through a 1 kOhm series sense "
                "resistor from {vprobe} V — a testbench condition",
            ],
            "stimulus": ["v_en en 0 {supply}", "v_src vsrc 0 {vprobe}"],
            "cards": ["r_sense vsrc pad 1k"],
            "control": ["op", "let vp = v(pad)",
                        "let ip = (v(vsrc)-v(pad))/1000",
                        "let reff = vp/ip",
                        "echo \"MEAS reff=\" $&reff \" vout=\" $&vp"],
        },
    },

    "oscillator": {
        "topology": "three-stage CMOS inverter ring oscillator",
        "circuit_class_citation": (
            "ring oscillator: an odd number of inverting stages closed on "
            "itself; f = 1/(2*N*td) (Razavi, Design of Analog CMOS "
            "Integrated Circuits ch.14)"),
        "ports": ["vdd", "vss", "out"],
        "rails": {"vdd": "vdd", "vss": "vss"},
        "internal_nets": ["n1", "n2"],
        "constants": {},
        "devices": [
            {"name": "mn1", "role": "nmos", "function":
             "stage 1 pull-down", "nets": ["n1", "out", "vss", "vss"],
             "w": 2.0, "l": 0.15},
            {"name": "mp1", "role": "pmos", "function":
             "stage 1 pull-up", "nets": ["n1", "out", "vdd", "vdd"],
             "w": 4.0, "l": 0.15},
            {"name": "mn2", "role": "nmos", "function":
             "stage 2 pull-down", "nets": ["n2", "n1", "vss", "vss"],
             "w": 2.0, "l": 0.15},
            {"name": "mp2", "role": "pmos", "function":
             "stage 2 pull-up", "nets": ["n2", "n1", "vdd", "vdd"],
             "w": 4.0, "l": 0.15},
            {"name": "mn3", "role": "nmos", "function":
             "stage 3 pull-down (closes the ring)",
             "nets": ["out", "n2", "vss", "vss"], "w": 2.0, "l": 0.15},
            {"name": "mp3", "role": "pmos", "function":
             "stage 3 pull-up (closes the ring)",
             "nets": ["out", "n2", "vdd", "vdd"], "w": 4.0, "l": 0.15},
        ],
        "spec_knobs": [],
        "device_param_exprs": [],
        "sizing_handoff": (
            "setting a target frequency means setting the per-stage delay, "
            "which is a sizing and current-starving decision; skill "
            "`analog-sizing` owns it. The geometry below is the library "
            "nominal."),
        "tradeoffs": [
            "Three stages is the minimum odd count that oscillates with a "
            "single-ended CMOS inverter; more stages lower the frequency "
            "and improve the phase noise per stage.",
            "A wider pull-up than pull-down equalises the rise and fall "
            "delays, which is what keeps the duty cycle near 50 percent.",
            "The ring frequency is a transient property: a DC operating "
            "point alone cannot measure it, so an `op`-only testbench "
            "reports bias self-consistency and nothing about frequency.",
        ],
        "analyses_implied": ["tran"],
        "testbench": {
            "supply_exprs": ["nominal_supply_v"],
            "env_exprs": {"vmid": "supply / 2"},
            "conditions": [
                "supply = {supply} V (the PDK's nominal supply)",
                "the ring is started from a mid-rail initial condition "
                "({vmid} V) — a transient testbench condition",
            ],
            "stimulus": ["v_vdd vdd 0 {supply}"],
            "cards": [".ic v(out)={vmid}"],
            "control": ["tran 0.02n 80n uic",
                        "meas tran t1 when v(out)={vmid} rise=2",
                        "meas tran t2 when v(out)={vmid} rise=3",
                        "let per = t2-t1", "let freq = 1/per",
                        "echo \"MEAS freq=\" $&freq \" period=\" $&per"],
        },
    },

    "comparator": {
        "topology": ("clocked StrongARM-style latch: NMOS input "
                     "differential pair, cross-coupled PMOS regenerative "
                     "latch, PMOS reset switches"),
        "circuit_class_citation": (
            "StrongARM / sense-amplifier latch comparator (Kobayashi et al., "
            "JSSC 1993; Razavi, 'The StrongARM Latch', IEEE SSC Magazine "
            "2015)"),
        "ports": ["vdd", "vss", "clk", "inp", "inn", "outp", "outn"],
        "rails": {"vdd": "vdd", "vss": "vss"},
        "internal_nets": ["ntail"],
        "constants": {},
        "devices": [
            {"name": "mn_tail", "role": "nmos", "function":
             "clocked tail switch: low = reset, high = evaluate",
             "nets": ["ntail", "clk", "vss", "vss"], "w": 16.0, "l": 0.5},
            {"name": "mn_inp", "role": "nmos", "function":
             "input differential pair, plus side",
             "nets": ["outp", "inp", "ntail", "vss"], "w": 16.0, "l": 0.5},
            {"name": "mn_inn", "role": "nmos", "function":
             "input differential pair, minus side",
             "nets": ["outn", "inn", "ntail", "vss"], "w": 16.0, "l": 0.5},
            {"name": "mp_lat1", "role": "pmos", "function":
             "cross-coupled regenerative latch, plus side",
             "nets": ["outp", "outn", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            {"name": "mp_lat2", "role": "pmos", "function":
             "cross-coupled regenerative latch, minus side",
             "nets": ["outn", "outp", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            {"name": "mp_rst1", "role": "pmos", "function":
             "reset / pre-charge switch, plus side",
             "nets": ["outp", "clk", "vdd", "vdd"], "w": 4.0, "l": 0.5},
            {"name": "mp_rst2", "role": "pmos", "function":
             "reset / pre-charge switch, minus side",
             "nets": ["outn", "clk", "vdd", "vdd"], "w": 4.0, "l": 0.5},
        ],
        "spec_knobs": [],
        "device_param_exprs": [],
        "sizing_handoff": (
            "input-referred offset and resolve time are set by the input "
            "pair area and the latch transconductance; trading them is "
            "sizing judgment owned by skill `analog-sizing`."),
        "tradeoffs": [
            "The cross-coupled PMOS pair gives regeneration with no static "
            "current, which is why the latch dissipates only during the "
            "evaluate phase.",
            "Enlarging the input differential pair lowers the "
            "input-referred offset as one over the square root of area and "
            "raises the clock load, so offset trades against speed.",
            "The reset switches must fully equalise both output nodes "
            "during the reset phase, or the previous decision leaks into "
            "the next one as hysteresis.",
        ],
        "analyses_implied": ["tran"],
        "testbench": {
            "supply_exprs": ["nominal_supply_v"],
            "env_exprs": {"vhi": "supply / 2 + 0.05",
                          "vlo": "supply / 2 - 0.05"},
            "conditions": [
                "supply = {supply} V (the PDK's nominal supply)",
                "two reset-evaluate cycles with the differential input "
                "reversed between them ({vhi} / {vlo} V) — a testbench "
                "condition, not a spec",
            ],
            "stimulus": [
                "v_vdd vdd 0 {supply}",
                "v_clk clk 0 pulse(0 {supply} 0n 1n 1n 200n 500n)",
                "v_inp inp 0 pwl(0 {vhi} 490n {vhi} 500n {vlo} 1000n {vlo})",
                "v_inn inn 0 pwl(0 {vlo} 490n {vlo} 500n {vhi} 1000n {vhi})",
            ],
            "cards": [],
            # The clock is HIGH (evaluate) for 0..201 ns and 500..701 ns and
            # LOW (reset, both outputs pre-charged to the rail) in between, so
            # the decision must be sampled INSIDE an evaluate window. Sampling
            # at 480 ns / 980 ns reads the reset state, where the two outputs
            # are equal by construction and the measured decision is ~0 V
            # whatever the input did. Measured: 19 uV and -15 uV on a latch
            # that in fact resolves rail-to-rail.
            "control": ["tran 1n 1000n",
                        "meas tran oa1 find v(outp) at=190n",
                        "meas tran ob1 find v(outn) at=190n",
                        "meas tran oa2 find v(outp) at=690n",
                        "meas tran ob2 find v(outn) at=690n",
                        "let d1 = oa1 - ob1", "let d2 = oa2 - ob2",
                        "echo \"MEAS decision1=\" $&d1 \" decision2=\" $&d2"],
        },
    },
    # ── the first SPEC-BOUND entry ────────────────────────────────────────
    # Admitted under `requires_bound`, never unconditionally. Every device
    # geometry below is the value this repo's OWN already-simulated reference
    # deck used (`analog_real_corner_sweep.T["delta_sigma"]`, itself derived
    # from the hand-authored `delta_sigma.sp` / `integrator_settle.sp`), so
    # the structure is not invented here. What is new is that the two
    # capacitors are SIZED FROM THE DECLARATION instead of from a constant —
    # which is exactly the objection the LIBRARY_GAPS row used to raise.
    #
    # WHAT IS EMITTED, stated plainly so the artefact cannot be read as more:
    # the LOOP FILTER — a cascade of `order` switched-capacitor integrators
    # with per-conversion reset switches. The 1-bit quantiser and its DAC
    # feedback are a separate circuit class (`comparator`, in this same
    # library) and closing them into the modulator is the named next step,
    # carried in `ai_handoff`. Emitting a half-loop under the name of the
    # whole one is the substitution this file refuses everywhere else.
    "delta_sigma": {
        # "the CIFB FORWARD PATH", not "a CIFB loop filter". A
        # cascade-of-integrators-feedback modulator is defined by its DAC
        # feedback branches into each summing node, and those arrive with the
        # quantiser, which this entry does not emit. Naming the finished
        # structure here would describe an artefact that is not on disk — the
        # exact substitution this file refuses everywhere else.
        "topology": ("cascade of {stages} switched-capacitor integrator(s) "
                     "around two-stage Miller NMOS-input OTAs — the FORWARD "
                     "PATH of a cascade-of-integrators feedback (CIFB) loop "
                     "filter, with per-conversion reset switches for "
                     "incremental operation and NO DAC feedback branch yet "
                     "(that arrives with the quantiser). Each stage's "
                     "sampling / integrating capacitor RATIO is that stage's "
                     "loop coefficient and the absolute value is the "
                     "sampled-noise budget of the declared resolution"),
        "circuit_class_citation": (
            "switched-capacitor delta-sigma loop filter, forward path of "
            "the cascade-of-integrators feedback form; second-order "
            "coefficient set a1 = a2 = 1/2 (Boser & Wooley, JSSC 23(6), "
            "1988); sampled kT/C noise budgeted against the quantisation "
            "floor (Schreier & Temes, Understanding Delta-Sigma Data "
            "Converters, ch.3)"),
        "ports": ["vdd", "vss", "vin", "vcm", "rst", "vout"],
        "rails": {"vdd": "vdd", "vss": "vss"},
        "internal_nets": ["nbias"],
        "constants": {
            "w_cap": 10.0,
            "w_res": 0.35,
            # Boltzmann's constant times 300 K. A UNIVERSAL physical
            # constant — the same on every process and in every design —
            # which is why it is a library constant and not a registry read.
            "kt_j_300k": 4.141947e-21,
            # One LSB of quantisation noise has power LSB^2/12; the sampled
            # noise budget is set equal to it.
            "noise_budget_factor": 12.0,
            "farad_to_ff": 1.0e15,
        },
        "constant_roles": {"w_cap": "cap", "w_res": "res"},
        # The bias branch is SHARED by every stage, so it is here and not in
        # the stage template.
        "devices": [
            {"name": "r_ib", "role": "res", "function":
             "bias-setting resistor from the supply into the mirror diode",
             "nets": ["vdd", "nbias", "vss"], "w": 0.35, "l": 181.0},
            {"name": "mn_bias", "role": "nmos", "function":
             "diode-connected reference of the tail current mirror, shared "
             "by every integrator stage",
             "nets": ["nbias", "nbias", "vss", "vss"], "w": 4.0, "l": 1.0},
        ],
        "spec_knobs": [],
        "device_param_exprs": [],
        "requires_bound": {
            "order": {"unit": "", "why":
                      "the loop order fixes BOTH the number of integrator "
                      "stages and which coefficient set applies; with no "
                      "order there is no device count"},
            "osr": {"unit": "", "why":
                    "the oversampling ratio sets how far the sampled noise "
                    "falls below the quantisation floor, and therefore the "
                    "absolute sampling capacitance"},
            "enob": {"unit": "bit", "why":
                     "the target resolution fixes the LSB, and the LSB "
                     "fixes the noise budget the sampling capacitor is "
                     "sized against"},
            "vref": {"unit": "V", "why":
                     "the reference is the full scale the LSB is measured "
                     "against"},
        },
        "requires_pdk_measured": ["cap_area_ff_per_um2"],
        "requires_domain": {
            # An order nobody authored a coefficient set for is refused by
            # name. A third-order single-bit loop is stable only under a
            # coefficient set that is a design solution rather than a fixed
            # structure, so it is absent here for the same reason the whole
            # class used to be.
            "order": [1, 2],
        },
        "requires_derived": [
            {"name": "sampling_cap_ff", "expr": SAMPLING_CAP_FF_EXPR,
             "min": 1.0, "max": 100000.0,
             "why": ("the noise budget derived from this declaration has to "
                     "land on a capacitor that can actually be drawn. A "
                     "resolution / reference / OSR triple that asks for one "
                     "outside this range is a statement that the converter "
                     "cannot be built this way, and saying so IS the "
                     "answer — rendering it anyway is not")},
        ],
        "coefficient_sets": {
            "1": [0.5],
            "2": [0.5, 0.5],
        },
        "stage": {
            "count_from": "order",
            "first_in": "vin",
            "last_out": "vout",
            "inner_out": "vo{i}",
            "internal_nets": ["ntail{i}", "nd1_{i}", "nd2_{i}", "vsum{i}"],
            "devices": [
                {"name": "mn_tail{i}", "role": "nmos", "function":
                 "stage {i} tail current source (mirror output)",
                 "nets": ["ntail{i}", "nbias", "vss", "vss"],
                 "w": 8.0, "l": 1.0},
                {"name": "mn_in{i}", "role": "nmos", "function":
                 "stage {i} input pair, summing-node (inverting) side",
                 "nets": ["nd1_{i}", "vsum{i}", "ntail{i}", "vss"],
                 "w": 16.0, "l": 0.5},
                {"name": "mn_ref{i}", "role": "nmos", "function":
                 "stage {i} input pair, common-mode reference side",
                 "nets": ["nd2_{i}", "vcm", "ntail{i}", "vss"],
                 "w": 16.0, "l": 0.5},
                {"name": "mp_ld1_{i}", "role": "pmos", "function":
                 "stage {i} current-mirror load, diode-connected leg",
                 "nets": ["nd1_{i}", "nd1_{i}", "vdd", "vdd"],
                 "w": 8.0, "l": 0.5},
                {"name": "mp_ld2_{i}", "role": "pmos", "function":
                 "stage {i} current-mirror load, output leg",
                 "nets": ["nd2_{i}", "nd1_{i}", "vdd", "vdd"],
                 "w": 8.0, "l": 0.5},
                {"name": "mp_o{i}", "role": "pmos", "function":
                 "stage {i} second-stage common-source driver",
                 "nets": ["{out}", "nd2_{i}", "vdd", "vdd"],
                 "w": 32.0, "l": 0.5},
                {"name": "mn_o{i}", "role": "nmos", "function":
                 "stage {i} second-stage current-source load",
                 "nets": ["{out}", "nbias", "vss", "vss"],
                 "w": 8.0, "l": 1.0},
                {"name": "cc{i}", "role": "cap", "function":
                 "stage {i} Miller compensation across the second stage",
                 "nets": ["nd2_{i}", "{out}"], "w": 10.0, "l": 25.0},
                {"name": "cs{i}", "role": "cap", "function":
                 "stage {i} SAMPLING capacitor — the absolute value is the "
                 "sampled-noise budget of the declared resolution",
                 "nets": ["{in}", "vsum{i}"], "w": 10.0, "l": 2.6},
                {"name": "ci{i}", "role": "cap", "function":
                 "stage {i} INTEGRATING capacitor — cs{i}/ci{i} IS this "
                 "stage's loop coefficient",
                 "nets": ["vsum{i}", "{out}"], "w": 10.0, "l": 5.2},
                {"name": "mn_rsti{i}", "role": "nmos", "function":
                 "stage {i} reset switch across the integrating capacitor: "
                 "the incremental converter's per-conversion reset",
                 "nets": ["vsum{i}", "rst", "{out}", "vss"],
                 "w": 2.0, "l": 0.15},
                {"name": "mn_rstc{i}", "role": "nmos", "function":
                 "stage {i} reset switch tying the summing node to the "
                 "common-mode reference, which is what defines its DC bias",
                 "nets": ["vsum{i}", "rst", "vcm", "vss"],
                 "w": 2.0, "l": 0.15},
            ],
            # `{coeff}` is substituted with THIS stage's coefficient before
            # the expression is written into the IR, so what reaches
            # `analog_a3_netlist_emit` still NAMES the bound spec rows
            # (`enob`, `osr`, `vref`) and is therefore counted as spec-bound
            # by `_resolve_params`. A coefficient folded into a library
            # constant would size the capacitors correctly and report the
            # netlist as a library default.
            "param_exprs": [
                {"device": "cs{i}", "param": "l",
                 "expr": SAMPLING_CAP_L_EXPR,
                 "rationale": ("sampling-capacitor length at the library "
                               "drawn width, from the sampled kT/C budget "
                               "of the declared ENOB / OSR / Vref")},
                {"device": "ci{i}", "param": "l",
                 "expr": "(" + SAMPLING_CAP_L_EXPR + ") / {coeff}",
                 "rationale": ("cs/ci IS this stage's loop coefficient, so "
                               "the integrating capacitor is the sampling "
                               "capacitor divided by it")},
            ],
        },
        "sizing_handoff": (
            "the OTA inside each integrator is carried at the reference "
            "geometry: its transconductance sets whether the stage settles "
            "inside the clock phase, and trading that against current is "
            "sizing judgment owned by skill `analog-sizing`. The CAPACITORS "
            "are not part of that handoff — they are derived above. The "
            "1-bit quantiser and the DAC feedback that close the modulator "
            "around this loop filter are a separate circuit class."),
        "tradeoffs": [
            "The sampling capacitor is set by the sampled kT/C noise "
            "budget, so each extra bit of declared resolution asks for four "
            "times the capacitance; oversampling is what buys it back, "
            "which is why the absolute value falls as OSR rises.",
            "The capacitor RATIO is the loop coefficient. Raising it raises "
            "the loop gain and the integrator's output swing together, so "
            "the coefficient set is bounded by the headroom the supply "
            "leaves and not by stability alone.",
            "Reset switches make the converter incremental — every "
            "conversion starts from a known state — at the cost of "
            "throughput, because the loop filter's memory is discarded at "
            "the end of each window.",
            "A larger sampling capacitor lowers the sampled noise and "
            "raises the load the amplifier has to settle within one clock "
            "phase, so noise trades directly against amplifier current.",
        ],
        "analyses_implied": ["tran"],
        "testbench": {
            "supply_exprs": ["vdd", "nominal_supply_v"],
            "env_exprs": {
                "vcm_v": "supply / 2",
                "vstep_v": "supply / 2 + vref / 10",
            },
            "conditions": [
                "supply = {supply} V (the bound core supply when the spec "
                "carries one, else the PDK's nominal)",
                "common-mode reference = {vcm_v} V, half the supply — a "
                "testbench condition, not a spec",
                "reset is held high for the first 100 ns and then released, "
                "which is the incremental converter's own "
                "start-of-conversion; the operating point is the reset "
                "state, where each summing node is tied to the common mode "
                "and each integrating capacitor is shorted",
                "the input steps {vcm_v} -> {vstep_v} V at 200 ns (one "
                "tenth of the bound reference) and the loop filter "
                "integrates it over a 4 us window — a testbench condition, "
                "not a spec",
            ],
            "stimulus": [
                "v_vdd vdd 0 {supply}",
                "v_vcm vcm 0 {vcm_v}",
                "v_rst rst 0 pwl(0 {supply} 99n {supply} 101n 0 4000n 0)",
                "v_in vin 0 pwl(0 {vcm_v} 199n {vcm_v} 201n {vstep_v} "
                "4000n {vstep_v})",
            ],
            "cards": [],
            "control": [
                "tran 0.5n 4000n",
                "meas tran vrst find v(vout) at=90n",
                "meas tran vstep find v(vout) at=190n",
                "meas tran vsettle find v(vout) at=3900n",
                "let dv = vsettle - vstep",
                "echo \"MEAS vout=\" $&vsettle \" vrst=\" $&vrst"
                " \" vstep=\" $&vstep \" dv=\" $&dv",
            ],
        },
    },
}

# Circuit classes DELIBERATELY absent, and why. The gap artefact quotes these,
# so a consumer reading `topology_gap.json` gets the reason and not just a
# blank. Adding a class means authoring the entry AND simulating it, never
# just adding a row here.
LIBRARY_GAPS: Dict[str, str] = {
    "bandgap": (
        "the PNP-based Brokaw core is netlistable and a 1:8 area ratio was "
        "measured to give the expected dVbe, but the curvature/summing ratio "
        "that lands the reference on its target is a sizing solution, not a "
        "fixed structure; admitted only with a simulated entry"),
    "por": (
        "the offset-plus-divider structure is fixed, but the trip voltage is "
        "the whole design content and a bare `threshold` token in a document "
        "names an over-voltage register far more often than a POR trip "
        "point; the spec vocabulary deliberately refuses it"),
    "trim": (
        "a binary-weighted or R-2R converter is a fixed structure only once "
        "the resolution is known; without a bound resolution there is no "
        "deterministic device count"),
    "esd": (
        "the clamp class (diode string / dual-diode to rail / ggNMOS) "
        "depends on the pin's voltage class, and the open PDK ships more "
        "than one diode subckt spelling with different terminal orders; a "
        "wrong instantiation was measured to return a nonsense forward "
        "voltage rather than to fail loudly"),
    "charge_pump": (
        "a Dickson-style pump only means anything under a two-phase clock in "
        "a transient analysis; emitting a DC-only structure would produce a "
        "netlist whose measured output is meaningless"),
    # `delta_sigma` HAS an entry now; this row is what a reader gets when
    # that entry REFUSES ITSELF for want of a bound input. The old
    # unconditional reason is kept verbatim as the first clause because it is
    # still exactly right for a block that binds nothing — what changed is
    # that it names a CONDITION instead of a permanent absence.
    "delta_sigma": (
        "the switched-capacitor integrator's capacitor ratio IS the loop "
        "coefficient, so the structure is not separable from the sizing — "
        "and the sizing inputs this block declares do not close it. See "
        "`admission_refusals` for which one is missing; a declaration that "
        "binds the loop order, the oversampling ratio, the target "
        "resolution and the reference determines both the device count and "
        "the capacitor ratio, and IS emitted"),
    "adc": (
        "an incremental converter's device count follows from resolution and "
        "oversampling ratio; both are spec content, not structure"),
}


# ── inputs ────────────────────────────────────────────────────────────────
def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None


def block_entries(project: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    for rel in (f"{_CANONICAL_ANALOG}/analog_block_list.json",
                f"{_DECLARED_ANALOG}/analog_block_list.json"):
        data = _read_json(project / rel)
        if data is None:
            continue
        blocks = data.get("blocks") if isinstance(data, dict) else data
        if isinstance(blocks, list):
            return ([b for b in blocks if isinstance(b, dict)], rel)
    data = _read_json(project / "phase1/generated_docs/L5_ADI_SPEC.json")
    if isinstance(data, dict) and isinstance(data.get("analog_blocks"), list):
        return ([b for b in data["analog_blocks"] if isinstance(b, dict)],
                "phase1/generated_docs/L5_ADI_SPEC.json")
    return ([], None)


def _canonical_type(btype: Optional[str]) -> str:
    try:
        import analog_real_corner_sweep as _arcs
        return _arcs.canonical_block_type(btype)
    except Exception:
        return str(btype or "").strip().lower()


def _declared_pdk_target(project: Path) -> Optional[str]:
    """The project's OWN L19-declared PDK target (same field A3 reads).
    None when the doc or field is absent — the caller then falls back
    loudly, never silently."""
    d = _read_json(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json")
    if isinstance(d, dict):
        f = d.get("fields")
        if isinstance(f, dict) and isinstance(f.get("pdk_target"), str):
            return f["pdk_target"].strip() or None
    return None


def pdk_device_params(selector: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """The DECLARED `analog_device_params` for the family matching `selector`.
    READ, never retyped — `analog-topology-select` forbids restating these.

    The selector->family match itself lives in `pdk_analog_layout_minima`
    (one matcher, shared): the electrical constants and the layout minima are
    two records of the SAME registry entry, and resolving them through two
    copies of the ladder is how one of them silently ends up read off a
    different family than the other.

    vibe-ic#1962 — the MEASURED sub-record is deliberately NOT returned here.
    It is a different kind of fact (a number taken off this PDK's own models at
    a stated bias, with a fit residual) and it is quoted in its own section
    with its own provenance; folding it into this dict would print a nested
    record as a row in the constants table and would let a measured number be
    mistaken for a declared one.
    """
    return _pdp.declared_params(selector)


def pdk_measured_params(selector: str, project: Optional[Path] = None
                        ) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """`(the flat measured constants, their provenance)` for `selector`.

    vibe-ic#1962. `({}, {"measured": False, ...})` is the honest answer for a
    family nobody has characterized yet: the artefact then STATES that it
    quoted no measured constant, which a reader cannot confuse with a family
    whose constants happened to be zero. `project` lets a PDK staged into the
    design outrank the shipped record, because the staged PDK is the one the
    design's decks load.

    The corner is left unspecified, so the record's own NOMINAL corner answers.
    A2 selects a topology; picking a process corner is a sizing decision and
    belongs to the pass that makes it, which reads the other corners by name.
    """
    return (_pdp.measured_values(selector, None, None, project),
            _pdp.measured_provenance(selector, None, None, project))


def bound_spec_values(project: Path, block: str) -> Tuple[Dict[str, float],
                                                          Optional[str]]:
    """Numeric spec values from the A1 artefact, keyed by spec name. Returns
    ({}, None) when no spec.json exists — the block then gets a topology whose
    `selection_basis` says so."""
    p = project / _CANONICAL_ANALOG / block / "spec.json"
    if not p.is_file():
        p = project / _DECLARED_ANALOG / block / "spec.json"
        if not p.is_file():
            return {}, None
    data = _read_json(p)
    out: Dict[str, float] = {}
    if isinstance(data, dict):
        specs = data.get("specs")
        if isinstance(specs, list):
            for s in specs:
                if not isinstance(s, dict) or not s.get("name"):
                    continue
                for k in ("target", "typ", "value", "min", "max"):
                    v = s.get(k)
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        out[str(s["name"])] = float(v)
                        break
    return out, str(p)


# ── spec-bound admission ──────────────────────────────────────────────────
def _unit_token(unit: Any) -> str:
    """A spec row's declared unit, normalised for comparison. Dimensionless
    spellings all collapse to the empty string; everything else keeps its own
    token, so `V` and `mV` stay DIFFERENT and a mis-united row is refused
    rather than silently scaled by a factor nobody wrote down."""
    tok = str(unit or "").strip().lower().rstrip(".")
    return "" if tok in DIMENSIONLESS_UNITS else tok


def bound_spec_units(project: Path, block: str) -> Dict[str, str]:
    """The DECLARED unit of every spec row, keyed as `bound_spec_values` keys
    it.

    A separate function rather than a wider return type from
    `bound_spec_values`, because that value map is passed straight into
    `_safe_eval` as the expression environment and a unit belongs nowhere near
    it. `analog_a1_spec_emit` carries the unit through from L5 for every row
    it binds, so this reads a field that is already there.
    """
    p = project / _CANONICAL_ANALOG / block / "spec.json"
    if not p.is_file():
        p = project / _DECLARED_ANALOG / block / "spec.json"
        if not p.is_file():
            return {}
    data = _read_json(p)
    out: Dict[str, str] = {}
    if isinstance(data, dict) and isinstance(data.get("specs"), list):
        for s in data["specs"]:
            if isinstance(s, dict) and s.get("name"):
                for key in ("units", "unit"):
                    if key in s:
                        out[str(s["name"])] = str(s.get(key) or "")
                        break
    return out


def admission_env(lib: Dict[str, Any], spec_values: Dict[str, float],
                  measured: Dict[str, float]) -> Dict[str, float]:
    """The environment an entry's OWN expressions resolve in, seeded exactly
    as `analog_a3_netlist_emit._resolve_params` seeds it — measured process
    constants first, then library constants, then the bound spec. Sharing the
    seeding order is the point: an admission bound evaluated in a different
    environment from the one the expression will finally run in would pass
    something that later resolves to a different number."""
    env: Dict[str, float] = {}
    env.update({k: float(v) for k, v in (measured or {}).items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)})
    env.update({k: float(v) for k, v in (lib.get("constants") or {}).items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)})
    env.update(spec_values)
    return env


def entry_admission(lib: Dict[str, Any], spec_values: Dict[str, float],
                    spec_units: Dict[str, str],
                    measured: Dict[str, float]) -> List[Dict[str, Any]]:
    """Every reason this library entry may NOT be selected for this block.

    An empty list means admitted. Each refusal NAMES the requirement and what
    was found instead, because `topology_gap.json` saying WHICH input is
    missing is the difference between a document a reader can act on and one
    that only says something was wrong. An entry declaring no requirement is
    admitted unconditionally, which is every entry that predates this.

    DECLARED BLOCKING at the producer's own tier: a refusal here means the
    block gets `topology_gap.json` and rc 2 (`RC_HONEST_GAP`) and NO
    `topology.md`, so the A2 gate keeps reporting the block uncovered. It
    never downgrades to a topology emitted on a default.
    """
    refusals: List[Dict[str, Any]] = []
    for name, req in sorted((lib.get(REQUIRES_BOUND_KEY) or {}).items()):
        req = req if isinstance(req, dict) else {}
        if name not in spec_values:
            refusals.append({
                "requirement": "spec_bound", "field": name,
                "declared_unit": None,
                "why": req.get("why"),
                "detail": (f"the A1 spec artefact binds no numeric value for "
                           f"`{name}`")})
            continue
        want = _unit_token(req.get("unit"))
        got = _unit_token(spec_units.get(name))
        if want != got:
            refusals.append({
                "requirement": "spec_unit", "field": name,
                "expected_unit": req.get("unit"),
                "declared_unit": spec_units.get(name),
                "why": req.get("why"),
                "detail": (
                    f"`{name}` is bound but declares unit "
                    f"{spec_units.get(name)!r}, and this entry's expressions "
                    f"are written for {req.get('unit')!r}. The expression "
                    f"environment carries no units, so binding it anyway "
                    f"would scale the result by a factor nobody wrote down")})
    for name, req in sorted((lib.get(SIZING_UNIT_CONTRACT_KEY)
                             or {}).items()):
        req = req if isinstance(req, dict) else {}
        if name not in spec_values:
            # A row the declaration does not carry is not a violation: the
            # expression over it drops and the device keeps its library
            # nominal, which A3 discloses. Only a BOUND row can be mis-united.
            continue
        want = _unit_token(req.get("unit"))
        got = _unit_token(spec_units.get(name))
        if want != got:
            refusals.append({
                "requirement": "spec_unit", "field": name,
                "expected_unit": req.get("unit"),
                "declared_unit": spec_units.get(name),
                "why": req.get("why"),
                "detail": (
                    f"`{name}` is bound and declares unit "
                    f"{spec_units.get(name)!r}, and this entry's device "
                    f"expressions are written for {req.get('unit')!r}. The "
                    f"expression environment carries no units, so sizing "
                    f"from it would scale the geometry by a factor nobody "
                    f"wrote down")})
    for name in (lib.get(REQUIRES_PDK_MEASURED_KEY) or []):
        if name not in (measured or {}):
            refusals.append({
                "requirement": "pdk_measured", "field": name,
                "detail": (
                    f"this entry sizes a device from the measured process "
                    f"constant `{name}`, and the target family carries no "
                    f"measured record for it. `analog_a3_netlist_emit` drops "
                    f"an expression over an unknown name SILENTLY, so "
                    f"emitting here would produce a library nominal with "
                    f"nothing saying it was not sized"),
                "remedy": "programs/pdk_analog_characterize.py"})
    for name, allowed in sorted((lib.get(REQUIRES_DOMAIN_KEY) or {}).items()):
        got = spec_values.get(name)
        if got is None:
            continue
        if not any(abs(float(got) - float(a)) < 1e-9 for a in allowed):
            refusals.append({
                "requirement": "domain", "field": name, "value": got,
                "admitted": list(allowed),
                "detail": (
                    f"`{name}` is bound to {got:g}, and this entry carries a "
                    f"structure only for {list(allowed)}. Selecting the "
                    f"nearest admitted value would emit a document that "
                    f"reads as this design's and is another one's")})
    env = admission_env(lib, spec_values, measured)
    for spec in (lib.get(REQUIRES_DERIVED_KEY) or []):
        if not isinstance(spec, dict):
            continue
        try:
            val = _safe_eval(str(spec.get("expr")), env)
        except Exception as exc:                                # noqa: BLE001
            refusals.append({
                "requirement": "derived_unresolvable",
                "field": spec.get("name"), "expr": spec.get("expr"),
                "detail": (f"the derived value `{spec.get('name')}` does not "
                           f"resolve in this block's environment: {exc}")})
            continue
        lo, hi = spec.get("min"), spec.get("max")
        if ((lo is not None and val < float(lo))
                or (hi is not None and val > float(hi))):
            refusals.append({
                "requirement": "derived_range", "field": spec.get("name"),
                "value": val, "min": lo, "max": hi,
                "why": spec.get("why"),
                "detail": (f"this declaration derives "
                           f"`{spec.get('name')}` = {val:g}, outside the "
                           f"admitted [{lo}, {hi}]")})
    return refusals


class LibraryEntryError(ValueError):
    """A LIBRARY-AUTHORING mistake, not a defect in any design's inputs.

    Separated from every other failure in this module on purpose: everything
    else here is a statement about the block being processed, and this one is
    a statement about the entry that was written to process it. A reader who
    cannot tell those apart goes looking for a missing spec row that is not
    missing. `library_invariants` catches every instance before it ships.
    """


def library_invariants(library: Optional[Dict[str, Any]] = None
                       ) -> List[str]:
    """Every authoring mistake in the topology library, as readable strings.

    Held by a test rather than by a reviewer remembering. Both rules below
    exist because breaking either one turns a REFUSAL into something worse:
    the first into a crash mid-run, the second into a silent default — an
    order emitted with a coefficient set that is not its own.
    """
    lib_map = LIBRARY if library is None else library
    problems: List[str] = []
    for btype, entry in sorted(lib_map.items()):
        st = entry.get(STAGE_KEY)
        if not isinstance(st, dict):
            continue
        count_from = st.get("count_from")
        required = entry.get(REQUIRES_BOUND_KEY) or {}
        if count_from not in required:
            problems.append(
                f"{btype}: stage count_from={count_from!r} is not in "
                f"{REQUIRES_BOUND_KEY}, so a block that does not bind it "
                f"reaches expansion instead of being refused")
        sets = entry.get(COEFFICIENT_SETS_KEY) or {}
        admitted = (entry.get(REQUIRES_DOMAIN_KEY) or {}).get(count_from)
        if admitted is None:
            problems.append(
                f"{btype}: stage count_from={count_from!r} has no "
                f"{REQUIRES_DOMAIN_KEY} entry, so an order with no "
                f"coefficient set is not excluded")
            continue
        for value in admitted:
            n = int(round(float(value)))
            got = sets.get(str(n))
            if got is None:
                problems.append(
                    f"{btype}: {count_from}={n} is admitted by "
                    f"{REQUIRES_DOMAIN_KEY} but has no "
                    f"{COEFFICIENT_SETS_KEY} entry")
            elif len(got) != n:
                problems.append(
                    f"{btype}: {count_from}={n} has a coefficient set of "
                    f"length {len(got)}; one coefficient per stage is "
                    f"required")
    return problems


# ── the repeated-stage template ───────────────────────────────────────────
def expand_stages(lib: Dict[str, Any], spec_values: Dict[str, float]
                  ) -> Tuple[List[Dict[str, Any]], List[str],
                             List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Flatten an entry's repeated stage into the plain device / net /
    expression lists the IR already carries.

    Returns `(devices, internal_nets, device_param_exprs, record)`; *record*
    is None for an entry that declares no stage, and those entries come back
    with their own lists unchanged.

    THE EXPANSION HAPPENS HERE, IN PYTHON, AND NOT IN THE IR'S EXPRESSION
    GRAMMAR. Two reasons, both load-bearing:

      * `analog_a3_netlist_emit` then needs no knowledge of stages at all —
        it renders a flat device list exactly as it always has, so the IR
        schema is unchanged and every consumer of it keeps working.
      * the flattened devices go through `floor_geometry_to_pdk` with
        everything else, so a stage device is floored to the target process's
        drawn minimum like any other. An expansion done downstream of that
        floor would step over it.

    The chain is explicit rather than inferred: stage 1's input is
    `first_in`, stage i's input is stage i-1's output, and the LAST stage's
    output is `last_out` — which is a declared PORT, so the block's output is
    a port on every order and not a net whose name depends on the count.
    """
    st = lib.get(STAGE_KEY)
    devices = [dict(d) for d in (lib.get("devices") or [])]
    nets = list(lib.get("internal_nets") or [])
    exprs = [dict(e) for e in (lib.get("device_param_exprs") or [])]
    if not isinstance(st, dict):
        return devices, nets, exprs, None

    # An entry declaring a stage MUST declare its count field in
    # `requires_bound`, so admission has already refused the block before this
    # runs. `library_invariants` proves that for every shipped entry and a
    # test holds the library to it — but the runtime path still has to say
    # WHICH authoring mistake was made rather than raise a bare KeyError from
    # a dict lookup ten frames down.
    count_from = st["count_from"]
    if count_from not in spec_values:
        raise LibraryEntryError(
            f"stage template declares count_from={count_from!r}, which is not "
            f"bound for this block. An entry with a `{STAGE_KEY}` must also "
            f"declare {count_from!r} in `{REQUIRES_BOUND_KEY}` so admission "
            f"refuses the block BEFORE expansion; see `library_invariants`.")
    count = int(round(float(spec_values[count_from])))
    coeff_set = (lib.get(COEFFICIENT_SETS_KEY) or {}).get(str(count))
    if coeff_set is None:
        raise LibraryEntryError(
            f"no `{COEFFICIENT_SETS_KEY}` entry for {count_from}={count}. An "
            f"order the library carries no coefficient set for must be "
            f"excluded by `{REQUIRES_DOMAIN_KEY}`, not defaulted here — "
            f"defaulting is how one design's coefficients end up under "
            f"another design's name.")
    coeffs = [float(c) for c in coeff_set]
    for i in range(1, count + 1):
        sub = {
            "i": i,
            "in": (st["first_in"] if i == 1
                   else st["inner_out"].format(i=i - 1)),
            "out": (st["last_out"] if i == count
                    else st["inner_out"].format(i=i)),
            "coeff": repr(coeffs[i - 1]),
        }
        for n in st.get("internal_nets") or []:
            nets.append(n.format(**sub))
        if i < count:
            nets.append(st["inner_out"].format(i=i))
        for d in st.get("devices") or []:
            nd = dict(d)
            nd["name"] = str(d["name"]).format(**sub)
            nd["function"] = str(d.get("function", "")).format(**sub)
            nd["nets"] = [str(n).format(**sub) for n in d.get("nets") or []]
            devices.append(nd)
        for e in st.get("param_exprs") or []:
            ne = dict(e)
            ne["device"] = str(e["device"]).format(**sub)
            ne["expr"] = str(e["expr"]).format(**sub)
            ne["stage"] = i
            ne["coefficient"] = coeffs[i - 1]
            exprs.append(ne)
    record = {
        "stages": count,
        "count_from": st["count_from"],
        "count_value_source": "spec",
        "coefficients": coeffs,
        "coefficient_set_key": str(count),
        "chain": ([st["first_in"]]
                  + [st["inner_out"].format(i=i)
                     for i in range(1, count)]
                  + [st["last_out"]]),
        "note": ("the device count and the per-stage coefficients BOTH "
                 "follow from the bound `%s`; nothing here is a library "
                 "default" % st["count_from"]),
    }
    return devices, nets, exprs, record


# ── artefacts ─────────────────────────────────────────────────────────────
def floor_geometry_to_pdk(lib: Dict[str, Any], constants: Dict[str, Any],
                          devices: List[Dict[str, Any]],
                          role_minima: Dict[str, Any]
                          ) -> List[Dict[str, Any]]:
    """Raise every DRAWN WIDTH in this IR to the target family's minimum.

    Mutates `constants` and `devices` in place and returns one record per
    clamp that FIRED — never a record for a value that was already legal, so
    an empty list means the library geometry was drawable as written and not
    that nothing was checked (that case is the `minima_available` flag on the
    provenance block).

    Two things are floored, and both have to be, because they reach the
    netlist by different routes: `analog_a3_netlist_emit` renders each
    device's own `w` (`d.get("w")`), and it also evaluates
    `device_param_exprs` in an environment seeded from `constants` — so a
    constant left un-floored would re-introduce the illegal width through any
    expression that reads it.
    """
    clamps: List[Dict[str, Any]] = []
    for cname, role in (lib.get(CONSTANT_ROLES_KEY) or {}).items():
        if cname not in constants:
            continue
        lo = _minima.min_width_um(role_minima, role)
        new, was = _minima.floor_width(constants[cname], lo)
        if was is None:
            continue
        constants[cname] = new
        clamps.append({"target": f"constants.{cname}", "role": role,
                       "library_value": was, "pdk_minimum": lo,
                       "value": new,
                       "rule": (role_minima.get(role) or {}).get("rule"),
                       "rule_text": (role_minima.get(role)
                                     or {}).get("rule_text")})
    for d in devices:
        role = d.get("role")
        lo = _minima.min_width_um(role_minima, str(role))
        new, was = _minima.floor_width(d.get("w"), lo)
        if was is None:
            continue
        d["w"] = new
        clamps.append({"target": f"devices.{d.get('name')}.w", "role": role,
                       "library_value": was, "pdk_minimum": lo,
                       "value": new,
                       "rule": (role_minima.get(role) or {}).get("rule"),
                       "rule_text": (role_minima.get(role)
                                     or {}).get("rule_text")})
    return clamps


def build_ir(block: str, btype: str, entry: Dict[str, Any],
             lib: Dict[str, Any], spec_values: Dict[str, float],
             spec_path: Optional[str], project: Path,
             pdk_family: Optional[str],
             pdk_params: Dict[str, Any],
             role_minima: Optional[Dict[str, Any]] = None,
             minima_source: Optional[str] = None,
             measured_params: Optional[Dict[str, float]] = None,
             measured_provenance: Optional[Dict[str, Any]] = None,
             ) -> Dict[str, Any]:
    knobs: Dict[str, Any] = {}
    knob_sources: Dict[str, str] = {}
    defaulted: List[str] = []
    for k in lib.get("spec_knobs", []):
        names = [t for t in _expr_names(k["expr"])]
        if all(n in spec_values for n in names):
            try:
                knobs[k["name"]] = _safe_eval(k["expr"], dict(spec_values))
                knob_sources[k["name"]] = "spec"
                continue
            except Exception:
                pass
        knobs[k["name"]] = k.get("default")
        knob_sources[k["name"]] = "library_default"
        defaulted.append(k["name"])

    role_minima = dict(role_minima or {})
    constants = dict(lib.get("constants") or {})
    # An entry with no `stage` key comes back with its own lists untouched,
    # so every pre-existing entry takes the identical path it always did.
    devices, internal_nets, param_exprs, stage_rec = expand_stages(
        lib, spec_values)
    clamps = floor_geometry_to_pdk(lib, constants, devices, role_minima)

    ir: Dict[str, Any] = {
        "ir_schema": IR_SCHEMA,
        "block": block,
        "block_type": btype,
        "topology": (lib["topology"].format(stages=stage_rec["stages"])
                     if stage_rec else lib["topology"]),
        "circuit_class_citation": lib["circuit_class_citation"],
        "ports": list(lib["ports"]),
        "rails": dict(lib["rails"]),
        "internal_nets": internal_nets,
        # Taken from the EXPANDED device list, not from the library's own:
        # a stage template may introduce a role the shared devices do not
        # use, and a role missing from `role_terminals` turns off the net-
        # count validation `analog_a3_netlist_emit._validate_ir` does before
        # it emits.
        "role_terminals": {r: ROLE_TERMINALS[r] for r in
                           sorted({d["role"] for d in devices})},
        "constants": constants,
        "devices": devices,
        "spec_knobs": [dict(k) for k in lib.get("spec_knobs", [])],
        "knobs": knobs,
        "knob_sources": knob_sources,
        "device_param_exprs": param_exprs,
        # None for an entry with no repeated stage. Present, it is the record
        # of a structure that FOLLOWED FROM THE DECLARATION: how many stages,
        # which spec row said so, and the coefficient each stage got.
        "stage_expansion": stage_rec,
        # vibe-ic#1962 — the target process's MEASURED electrical constants,
        # carried into the IR so a `device_param_exprs` entry can be written
        # against a sheet resistance or a transconductance the PDK's own models
        # were measured for, instead of against a number a sizing pass
        # re-derives by hand every time. Empty for a family nobody has
        # characterized; `_provenance.pdk_constants_source.measured` says which
        # of the two it is.
        "pdk_measured_params": dict(measured_params or {}),
        "analyses_implied": list(lib.get("analyses_implied") or []),
        # Carried into the IR so `analog_a3_netlist_emit` renders the stimulus
        # generically instead of holding a second per-type table.
        "testbench": (dict(lib["testbench"]) if isinstance(
            lib.get("testbench"), dict) else None),
        "selection_basis": ("block_type_and_spec" if spec_values
                            else "block_type_only"),
        "design_inputs_bound": sorted(spec_values.keys()),
        "_provenance": {
            "schema": PROVENANCE_SCHEMA,
            "producer": PRODUCER,
            "produced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "derived_from": "block_type_topology_library",
            "library_entry": btype,
            "inputs": [
                {"path": spec_path, "sha256": _sha256(Path(spec_path))}
                if spec_path else
                {"path": None, "note": "no A1 spec.json for this block"},
            ],
            "pdk_constants_source": {
                "path": "programs/pdk_registry.json",
                "family": pdk_family,
                "analog_device_params": pdk_params or None,
                # vibe-ic#1962 — the MEASURED half, and how it was measured.
                # `measured: false` is a POSITIVE statement that this family
                # has not been characterized, so a reader can tell "quoted
                # nothing" from "quoted a zero".
                "measured": dict(measured_provenance or {"measured": False}),
            },
            # vibe-ic#1952. `minima_available` is the honest distinction
            # between "checked, nothing was below the floor" (clamps == [])
            # and "this family declares no measured minimum, so NOTHING was
            # floored" — a reader that cannot tell those apart will read the
            # second as the first.
            "layout_minima": {
                "path": "programs/pdk_registry.json",
                "field": "analog_device_layout_minima",
                "reader": "programs/pdk_analog_layout_minima.py",
                "family": pdk_family,
                "minima_available": bool(role_minima),
                "measured_from": minima_source,
                "roles": role_minima or None,
                "clamps": clamps,
                "note": (
                    "drawn widths are FLOORED to the target PDK's own rule, "
                    "not set from it: a family whose minimum sits below the "
                    "library nominal leaves the geometry unchanged."
                    if role_minima else
                    "this family declares no measured device minimum in the "
                    "registry, so NO width was floored — the geometry below "
                    "is the library nominal and has not been checked against "
                    "any layout rule."),
            },
            # A stage count read from a bound spec row is a field bound
            # FROM THE SPEC in exactly the sense this list means, and it does
            # not pass through `spec_knobs`. Leaving it out reported a
            # topology whose device count came from the declaration as one
            # with nothing bound.
            "fields_bound": sorted(
                [n for n, s in knob_sources.items() if s == "spec"]
                + ([stage_rec["count_from"]] if stage_rec else [])),
            "stage_expansion": stage_rec,
            "admission": {
                "requires_bound": sorted(
                    (lib.get(REQUIRES_BOUND_KEY) or {}).keys()),
                "requires_pdk_measured": list(
                    lib.get(REQUIRES_PDK_MEASURED_KEY) or []),
                "requires_domain": {k: list(v) for k, v in
                                    (lib.get(REQUIRES_DOMAIN_KEY)
                                     or {}).items()},
                "admitted": True,
            },
            "fields_defaulted": sorted(defaulted),
            "defaults_used": bool(defaulted),
            "fields_clamped": sorted(c["target"] for c in clamps),
            "clamped_to_pdk_minimum": bool(clamps),
            "sizing_handoff": lib.get("sizing_handoff"),
            "ai_handoff": (
                {"track": "skill", "skill": "analog-sizing",
                 "reason": lib["sizing_handoff"]}
                if lib.get("sizing_handoff") else None),
            "limits": (
                "the topology is a circuit-CLASS selection. Device geometry "
                "is the library nominal unless a device_param_expr bound it "
                "to a spec value or the target PDK's layout minimum floored "
                "it; see fields_bound / fields_defaulted / fields_clamped. A "
                "floor makes the geometry DRAWABLE, not correct: it is not a "
                "sizing solution and does not re-solve the block."),
        },
    }
    return ir


def _render_measured_section(ir: Dict[str, Any]) -> List[str]:
    """The MEASURED process constants, and what was measured to get them.

    vibe-ic#1962. Kept as its own section, and never folded into the declared
    table above, because the two are different kinds of fact: the declared
    constants are a hand-maintained record of the family, and these were taken
    off this PDK's OWN models at a stated bias, on a stated primitive, by a
    stated method, with a residual that says how well the model being fitted
    describes the device. A number quoted without those is exactly the
    re-derived-per-session constant this section replaces.
    """
    prov = (ir["_provenance"].get("pdk_constants_source") or {}).get(
        "measured") or {}
    values = ir.get("pdk_measured_params") or {}
    L: List[str] = ["## Measured process constants", ""]
    if not prov.get("measured"):
        L.append("This PDK family has NOT been characterized, so no measured "
                 "constant is quoted here. Run "
                 "`programs/pdk_analog_characterize.py --pdk <family>` to "
                 "measure them from the PDK's own models. "
                 f"({prov.get('reason') or 'no measured record resolves'})")
        L.append("")
        return L
    L.append(f"Measured from the target PDK's own models by "
             f"`{prov.get('generated_by')}` and read out of "
             f"`programs/pdk_registry.json` — not re-derived here, and not "
             f"restated from memory.")
    L.append("")
    L.append(f"- corner: `{prov.get('corner')}` at "
             f"{prov.get('temp_c')} °C, supply {prov.get('supply_v')} V")
    for role, dev in sorted((prov.get("devices") or {}).items()):
        L.append(f"- `{role}` measured on `{dev}`")
    for lib, section in (prov.get("sections") or []):
        L.append(f"- model section `{section}` of `{lib}`")
    L.append("")
    if values:
        L.append("| constant | value |")
        L.append("|---|---|")
        for k in sorted(values):
            L.append(f"| `{k}` | {values[k]:.6g} |")
        L.append("")
    for k, resid in sorted((prov.get("fit") or {}).items()):
        L.append(f"- fit witness `{k}`: {resid}")
    if prov.get("fit"):
        L.append("")
    nm = prov.get("not_measured") or {}
    if nm:
        L.append("NOT measured on this family, and therefore not quoted "
                 "anywhere downstream:")
        L.append("")
        for k in sorted(nm):
            L.append(f"- `{k}` — {nm[k]}")
        L.append("")
    return L


def render_md(ir: Dict[str, Any], lib: Dict[str, Any],
              pdk_family: Optional[str], pdk_params: Dict[str, Any]) -> str:
    prov = ir["_provenance"]
    L: List[str] = []
    L.append(f"# Topology selection — {ir['block']} "
             f"({ir['block_type']} class)")
    L.append("")
    L.append(f"**Selected topology:** {ir['topology']}")
    L.append("")
    L.append(f"Circuit class: {ir['circuit_class_citation']}")
    L.append("")
    L.append("## Ports")
    L.append("")
    L.append("| port | role |")
    L.append("|---|---|")
    rails = {v: k for k, v in ir["rails"].items()}
    for p in ir["ports"]:
        L.append(f"| `{p}` | {'supply rail' if p in rails else 'signal'} |")
    L.append("")
    L.append("## Devices and their function")
    L.append("")
    L.append("| device | device class | terminals | function |")
    L.append("|---|---|---|---|")
    for d in ir["devices"]:
        cls = {"nmos": "NMOS transistor", "pmos": "PMOS transistor",
               "res": "resistor", "cap": "capacitor"}.get(d["role"],
                                                          d["role"])
        L.append(f"| `{d['name']}` | {cls} | "
                 f"{', '.join(d['nets'])} | {d.get('function', '')} |")
    L.append("")
    if ir["internal_nets"]:
        L.append(f"Internal nets: {', '.join('`%s`' % n for n in ir['internal_nets'])}")
        L.append("")
    stage = ir.get("stage_expansion")
    if stage:
        L.append("## Loop structure — how many stages, and why")
        L.append("")
        L.append(f"The structure below is **not** a fixed library shape. "
                 f"The stage count came from the bound spec row "
                 f"`{stage['count_from']}` = {stage['stages']}, and each "
                 f"stage's coefficient came with it:")
        L.append("")
        L.append("| stage | input | output | coefficient (cs/ci) |")
        L.append("|---|---|---|---|")
        chain = stage.get("chain") or []
        for idx, coeff in enumerate(stage.get("coefficients") or [], start=1):
            src_net = chain[idx - 1] if idx - 1 < len(chain) else "?"
            dst_net = chain[idx] if idx < len(chain) else "?"
            L.append(f"| {idx} | `{src_net}` | `{dst_net}` | {coeff} |")
        L.append("")
        L.append("The capacitor ratio IS the loop coefficient, which is why "
                 "this circuit class was previously refused outright: a "
                 "structure with no bound sizing is not a structure. It is "
                 "emitted here because the declaration binds the inputs "
                 "that determine it — see **Spec binding** below.")
        L.append("")
    L.append("## Design trade-offs")
    L.append("")
    for t in lib.get("tradeoffs", []):
        L.append(f"- {t}")
    L.append("")
    L.append("## Process constants used")
    L.append("")
    if pdk_params:
        L.append(f"Read from `programs/pdk_registry.json` "
                 f"(`{pdk_family}.analog_device_params`) — not restated here "
                 f"from memory:")
        L.append("")
        L.append("| constant | value |")
        L.append("|---|---|")
        for k, v in pdk_params.items():
            if k == "note":
                continue
            L.append(f"| `{k}` | {v} |")
    else:
        L.append("No `analog_device_params` entry resolves for the requested "
                 "PDK family in `programs/pdk_registry.json`, so no threshold "
                 "or supply constant is quoted here. Quoting one from memory "
                 "is the failure this section exists to prevent.")
    L.append("")
    L.extend(_render_measured_section(ir))
    L.append("## Drawn-geometry minima of the target process")
    L.append("")
    lm = prov.get("layout_minima") or {}
    if lm.get("minima_available"):
        L.append(f"Read from `{lm['path']}` "
                 f"(`{lm.get('family')}.{lm['field']}`) via `{lm['reader']}`, "
                 f"which measured them from the PDK's own rule record:")
        L.append("")
        L.append("| device class | min drawn width (um) | rule |")
        L.append("|---|---|---|")
        for role in sorted(lm.get("roles") or {}):
            rec = (lm["roles"] or {})[role]
            L.append(f"| {role} | {rec.get(_minima.MIN_WIDTH_KEY)} | "
                     f"`{rec.get('rule')}` — {rec.get('rule_text')} |")
        L.append("")
        if lm.get("clamps"):
            L.append("The library nominal was below that minimum and has "
                     "been **floored to it**. A netlist that keeps a width "
                     "the process will not let the layout draw is the "
                     "device-property mismatch this floor exists to prevent:")
            L.append("")
            L.append("| geometry | library nominal | floored to | rule |")
            L.append("|---|---|---|---|")
            for c in lm["clamps"]:
                L.append(f"| `{c['target']}` | {c['library_value']} | "
                         f"{c['value']} | `{c.get('rule')}` |")
            L.append("")
            L.append("A floor makes the geometry drawable; it does not "
                     "re-solve the block. Whether the floored value still "
                     "meets the spec is an A4 corner-sweep question.")
        else:
            L.append("Every library nominal is already at or above this "
                     "process's minimum, so **no width was changed**.")
    else:
        L.append("`programs/pdk_registry.json` carries no measured "
                 "`analog_device_layout_minima` for the requested PDK "
                 "family, so **no width below was floored to any layout "
                 "rule**. The geometry is the library nominal and has not "
                 "been checked against this process.")
    L.append("")
    L.append("## Spec binding")
    L.append("")
    if ir["design_inputs_bound"]:
        L.append("Spec values bound from the A1 artefact: "
                 + ", ".join(f"`{n}`" for n in ir["design_inputs_bound"]))
    else:
        L.append("**No A1 spec was bound for this block.** "
                 "`selection_basis` is `block_type_only`: the topology below "
                 "follows from the circuit class alone and no number from "
                 "this design entered it.")
    L.append("")
    if ir["knobs"]:
        L.append("| knob | value | source |")
        L.append("|---|---|---|")
        for k, v in ir["knobs"].items():
            L.append(f"| `{k}` | {v} | {ir['knob_sources'].get(k)} |")
        L.append("")
    adm = (prov.get("admission") or {})
    if adm.get("requires_bound") or adm.get("requires_pdk_measured"):
        L.append("This entry is **spec-bound**: it is selectable only when "
                 "every input below is bound, and it refuses itself — "
                 "emitting `topology_gap.json` and no topology at all — when "
                 "one is not.")
        L.append("")
        if adm.get("requires_bound"):
            L.append("- required spec rows: "
                     + ", ".join(f"`{n}`" for n in adm["requires_bound"]))
        if adm.get("requires_pdk_measured"):
            L.append("- required MEASURED process constants: "
                     + ", ".join(f"`{n}`"
                                 for n in adm["requires_pdk_measured"]))
        if adm.get("requires_domain"):
            for k, v in adm["requires_domain"].items():
                L.append(f"- `{k}` is carried only for {v}")
        L.append("")
        L.append("Device parameters derived from those inputs, with the "
                 "expression that derived each one:")
        L.append("")
        L.append("| device.param | expression | why |")
        L.append("|---|---|---|")
        for e in ir.get("device_param_exprs") or []:
            L.append(f"| `{e.get('device')}.{e.get('param')}` | "
                     f"`{e.get('expr')}` | {e.get('rationale', '')} |")
        L.append("")
    L.append("## Provenance")
    L.append("")
    L.append(f"- producer: `{prov['producer']}` (schema {prov['schema']})")
    L.append(f"- produced at: {prov['produced_at']}")
    L.append(f"- derived from: {prov['derived_from']} "
             f"(entry `{prov['library_entry']}`)")
    L.append(f"- selection basis: `{ir['selection_basis']}`")
    L.append(f"- fields bound from spec: {prov['fields_bound'] or 'none'}")
    L.append(f"- fields taking a library default: "
             f"{prov['fields_defaulted'] or 'none'}")
    L.append(f"- geometry floored to the PDK layout minimum: "
             f"{prov['fields_clamped'] or 'none'}")
    if prov.get("ai_handoff"):
        L.append(f"- **handed off to the AI track**: skill "
                 f"`{prov['ai_handoff']['skill']}` — "
                 f"{prov['ai_handoff']['reason']}")
    else:
        L.append("- AI handoff: none")
    L.append(f"- limits: {prov['limits']}")
    L.append("")
    L.append("Machine-readable form of everything above: `topology.json` "
             "(the IR `analog_a3_netlist_emit` renders SPICE from).")
    L.append("")
    return "\n".join(L)


def _gap_body(block: str, btype: str, entry: Dict[str, Any],
              refusals: Optional[List[Dict[str, Any]]] = None,
              status: str = "NO_TOPOLOGY_IN_LIBRARY") -> Dict[str, Any]:
    """The honest-gap artefact. *refusals* is the list `entry_admission`
    returned — present when the library HAS an entry for this class and that
    entry declined for want of a bound input, absent when the class has no
    entry at all. A reader has to be able to tell those two apart: the first
    is fixed by binding a spec row, the second only by authoring a topology.
    """
    reason = LIBRARY_GAPS.get(btype)
    return {
        "block": block,
        "block_type": btype,
        "_provenance": {
            "schema": PROVENANCE_SCHEMA,
            "producer": PRODUCER,
            "produced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "derived_from": "block_type_topology_library",
            "fields_bound": [],
            "fields_defaulted": [],
            "defaults_used": False,
        },
        "status": status,
        "topology_md_written": False,
        "topology_json_written": False,
        "library_types": sorted(LIBRARY.keys()),
        "library_entry_exists": btype in LIBRARY,
        "admission_refusals": list(refusals or []),
        "unmet_requirements": sorted(
            {str(r.get("field")) for r in (refusals or [])
             if r.get("field")}),
        "reason": (
            reason or
            f"circuit class `{btype}` has no entry in the deterministic "
            f"topology library, and this producer does not synthesise one"),
        "why_not_defaulted": (
            "emitting the nearest library topology under this block's name "
            "would produce a document that reads as a selection and is a "
            "substitution; the A2 gate cannot tell them apart because it "
            "measures vocabulary, not structure"),
        "how_to_close": (
            ("bind the spec row(s) named in `unmet_requirements` in this "
             "block's Phase-1 declaration, or characterise the process "
             "constant named there with `programs/pdk_analog_characterize.py`"
             " — this circuit class HAS a deterministic entry and it "
             "declined only because an input it names is not bound")
            if refusals else
            ("author a library entry for this circuit class, or hand the "
             "block to the skill below")),
        "ai_handoff": {
            "track": "skill",
            "skill": SKILL,
            "required_output": f"{_CANONICAL_ANALOG}/{block}/topology.md",
            "reason": ("choosing a topology for a circuit class the "
                       "deterministic library does not carry is design "
                       "judgment"),
        },
    }


# ── a deliberately tiny, safe expression evaluator ────────────────────────
import ast as _ast


def _expr_names(expr: str) -> List[str]:
    try:
        return sorted({n.id for n in _ast.walk(_ast.parse(expr, mode="eval"))
                       if isinstance(n, _ast.Name)})
    except SyntaxError:
        return []


_ALLOWED_NODES = (_ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.Name,
                  _ast.Load, _ast.Constant, _ast.Add, _ast.Sub, _ast.Mult,
                  _ast.Div, _ast.Pow, _ast.USub, _ast.UAdd)


def _safe_eval(expr: str, env: Dict[str, float]) -> float:
    """Arithmetic over named spec values only. No calls, no attributes, no
    subscripts — the IR is data read off disk, so it must not be executable."""
    tree = _ast.parse(expr, mode="eval")
    for node in _ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"disallowed expression node "
                             f"{type(node).__name__} in {expr!r}")
        if isinstance(node, _ast.Name) and node.id not in env:
            raise KeyError(node.id)
    return float(eval(compile(tree, "<ir-expr>", "eval"),  # noqa: S307
                      {"__builtins__": {}}, dict(env)))


# ── per-block driver ──────────────────────────────────────────────────────
def emit_for_block(project: Path, entry: Dict[str, Any],
                   pdk: str) -> Dict[str, Any]:
    name = str(entry.get("name") or entry.get("block") or entry.get("type"))
    btype = _canonical_type(entry.get("type") or entry.get("block_type"))
    bdir = project / _CANONICAL_ANALOG / name
    md_path = bdir / "topology.md"
    ir_path = bdir / "topology.json"
    rec: Dict[str, Any] = {"block": name, "block_type": btype}

    if md_path.is_file():
        existing = md_path.read_text(encoding="utf-8", errors="replace")
        if f"producer: `{PRODUCER}`" not in existing:
            rec.update(action="kept_preexisting", emitted=False,
                       topology_md=str(md_path.relative_to(project)))
            return rec

    def _gap(status: str,
             refusals: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Write the honest-gap artefact and clear anything THIS producer
        emitted before. Shared by both decline paths so a refusal for want of
        a bound input leaves exactly the same shape on disk as a class with no
        entry — one `topology_gap.json`, no `topology.md`, no stale IR."""
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "topology_gap.json").write_text(
            json.dumps(_gap_body(name, btype, entry, refusals, status),
                       indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        for stale in (md_path, ir_path):
            if stale.is_file() and PRODUCER in stale.read_text(
                    encoding="utf-8", errors="replace"):
                stale.unlink()
        rec.update(action="gap", emitted=False, status=status,
                   admission_refusals=list(refusals or []),
                   gap_path=str((bdir / "topology_gap.json")
                                .relative_to(project)))
        return rec

    lib = LIBRARY.get(btype)
    if lib is None:
        return _gap("NO_TOPOLOGY_IN_LIBRARY")

    spec_values, spec_path = bound_spec_values(project, name)
    fam, params = pdk_device_params(pdk)
    # The SAME selector resolves all THREE records through the one shared
    # matcher, so a family whose Vth is quoted can never be a family whose
    # layout minima — or whose measured constants — were silently skipped.
    _minima_fam, role_minima = _minima.layout_minima(pdk)
    measured, measured_prov = pdk_measured_params(pdk, project)

    # An entry may refuse ITSELF. Checked BEFORE `build_ir`, because the
    # whole point is that a topology whose sizing inputs are not bound must
    # not reach disk at all: the A2 gate measures vocabulary, so a document
    # emitted on defaults would PASS it. Every pre-existing entry declares no
    # requirement and so returns [] here.
    refusals = entry_admission(lib, spec_values,
                               bound_spec_units(project, name), measured)
    if refusals:
        return _gap("ENTRY_REQUIREMENTS_NOT_MET", refusals)

    ir = build_ir(name, btype, entry, lib, spec_values, spec_path, project,
                  fam, params, role_minima, _minima.minima_source(pdk),
                  measured, measured_prov)
    md = render_md(ir, lib, fam, params)
    bdir.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    ir_path.write_text(json.dumps(ir, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    gap = bdir / "topology_gap.json"
    if gap.is_file():
        gap.unlink()
    rec.update(action="emitted", emitted=True,
               topology_md=str(md_path.relative_to(project)),
               topology_json=str(ir_path.relative_to(project)),
               selection_basis=ir["selection_basis"],
               fields_defaulted=ir["_provenance"]["fields_defaulted"],
               fields_clamped=ir["_provenance"]["fields_clamped"],
               layout_minima_available=(
                   ir["_provenance"]["layout_minima"]["minima_available"]))
    return rec


def run(project: Path, only: Optional[str], pdk: str
        ) -> Tuple[int, Dict[str, Any]]:
    entries, src = block_entries(project)
    if not entries:
        return 1, {"producer": PRODUCER, "verdict": "NO_INPUT",
                   "reason": "no analog block list and no L5 analog_blocks[]",
                   "records": []}
    if only:
        entries = [e for e in entries
                   if (e.get("name") or e.get("block") or e.get("type"))
                   == only]
        if not entries:
            return 1, {"producer": PRODUCER, "verdict": "NO_SUCH_BLOCK",
                       "reason": f"block `{only}` is not declared in {src}",
                       "records": []}
    records = [emit_for_block(project, e, pdk) for e in entries]
    emitted = [r for r in records if r.get("emitted")]
    kept = [r for r in records if r.get("action") == "kept_preexisting"]
    gaps = [r for r in records if r.get("action") == "gap"]
    report = {
        "producer": PRODUCER,
        "block_list_source": src,
        "verdict": "EMITTED" if (emitted or kept) else "ALL_GAP",
        "blocks_total": len(records),
        "blocks_emitted": len(emitted),
        "blocks_kept_preexisting": len(kept),
        "blocks_gap": len(gaps),
        "library_types": sorted(LIBRARY.keys()),
        "ai_handoff_blocks": [r["block"] for r in gaps],
        "suggested_skill": SKILL if gaps else None,
        "records": records,
    }
    return (0 if (emitted or kept) else 2), report


def main(argv: Optional[List[str]] = None) -> int:
    # A usage error exits `_pc.EX_USAGE`, never the honest-gap tier — see
    # `_analog_producer_common` for the measurement that forced the split.
    ap = _pc.ProducerArgumentParser(prog=PRODUCER, description=__doc__,
                                    formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--block", default=None)
    ap.add_argument("--pdk", default=None,
                    help="PDK selector whose analog_device_params are quoted "
                         "in topology.md (read from pdk_registry.json). "
                         "Default: the project's own L19-declared pdk_target; "
                         "'sky130' only when the project declares none. The "
                         "old static 'sky130' default silently quoted the "
                         "wrong family's Vth/rail into every topology on any "
                         "other PDK (measured: u_hawaii_adc / ihp-sg13g2).")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    project = args.project.resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 1
    if args.pdk:
        pdk, pdk_source = args.pdk, "cli"
    else:
        declared = _declared_pdk_target(project)
        pdk, pdk_source = ((declared, "l19_declared") if declared
                           else ("sky130", "static_default"))
    print(f"{PRODUCER}: pdk selector `{pdk}` ({pdk_source})", file=sys.stderr)
    rc, report = run(project, args.block, pdk)
    report["pdk_selector"] = pdk
    report["pdk_selector_source"] = pdk_source
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    if rc == 0:
        print(f"{PRODUCER}: {report['blocks_emitted']} topology emitted, "
              f"{report['blocks_gap']} honest gap(s) "
              f"(hand off to `{SKILL}`)")
    elif rc == _pc.RC_HONEST_GAP:
        print(_pc.honest_gap_line(
            PRODUCER,
            f"NO block type is in the topology library — "
            f"{report['blocks_gap']} topology_gap.json written; "
            f"invoke skill `{SKILL}`"), file=sys.stderr)
    else:
        print(f"{PRODUCER}: {report.get('verdict')} — "
              f"{report.get('reason')}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
