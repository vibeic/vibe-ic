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
import math
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _analog_producer_common as _pc  # noqa: E402
import pdk_analog_device_params as _pdp  # noqa: E402
import pdk_analog_layout_minima as _minima  # noqa: E402

PRODUCER = "analog_a2_topology_emit"


def producer_fingerprint() -> str:
    """A digest of THIS producer's own source, stamped into every artefact.

    MEASURED (round 23): a topology.json emitted by an older build of this
    file is indistinguishable from a current one — `_provenance` names the
    producer but not WHICH producer. So a run whose gate found the stale
    artefact passed, the producer was never invoked, and the netlist that
    reached the simulator was the old one: old comparator, 4 um keeper, 181 um
    bias, ci 6.949 um, while the library had long since been fixed. From the
    outside that run is indistinguishable from a successful one.

    The fingerprint is derived from the artefact's own producer, not from
    mtime (which a copy or a checkout resets) and not from a file name (one
    spelling defines a blind population).
    """
    import hashlib
    try:
        return hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest()[:16]
    except OSError:                                     # pragma: no cover
        return ""
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

# Library key: an entry's own statement of what its circuit must be SHOWN to
# do, and whether that has been shown. OPTIONAL — an entry that omits it is
# unaffected in every path. It exists because "renders and simulates" is not
# the same claim as "works": a delta-sigma loop can converge in the simulator
# and emit a full-swing bitstream while converting nothing, and no gate in
# this flow measured the difference. Read by
# `analog_topology_behaviour_check`.
BEHAVIOUR_RECORD_KEY = "behaviour_record"

#: Stage-group key: the stage count is the number of divide-by-two stages
#: whose period reaches this bound spec row, not the row's value itself. A
#: conversion-window counter has `count_bits_for: "osr"` where an integrator
#: cascade has `count_from: "order"`.
COUNT_BITS_KEY = "count_bits_for"

#: Stage-group key, default True: whether this group draws a coefficient from
#: `coefficient_sets`. A counter has no loop coefficients and must not be
#: refused for want of a set that would mean nothing.
COEFFICIENTS_KEY = "coefficients"

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
#: A stage group that declares this gets its feedback reference end DERIVED
#: from the integrator polarity it emits, instead of taking it from a fixed
#: per-stage table. `{"pos": <suffix>, "neg": <suffix>}` names which selector
#: feeds back the POSITIVE reference when the decision is asserted.
FEEDBACK_SELECTORS_KEY = "feedback_selectors"
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

#: An entry may DERIVE its coefficients instead of tabulating them.
COEFFICIENT_DERIVATION_KEY = "coefficient_derivation"

#: {role: net name} — the nets that say whether this block's loop was LIVE
#: over a measured window. An arm runner cannot ask that question without
#: them, and a null measured over a dead loop certifies nothing: rounds 18-20
#: closed two mechanisms on such nulls (`the auto-zero node does not walk`,
#: `range is refuted`) and both had to be reopened when the same probes on a
#: live loop returned twelve times the drift and a de-saturating loop filter.
#: Consumed by `analog_loop_liveness_check`; the roles are that program's.
LIVENESS_NODES_KEY = "liveness_nodes"


def _incremental_cifb_coefficients(order, spec_values, consts):
    """Equal per-stage coefficients for an INCREMENTAL cascade of integrators.

    WHY A DERIVATION AND NOT A TABLE. An incremental converter is reset at the
    start of every conversion window and accumulates from ZERO for `osr`
    clocks; a free-running modulator's state is bounded by its own feedback in
    steady state. Those are different design problems, and the free-running
    second-order set a1 = a2 = 1/2 (Boser & Wooley, JSSC 23(6), 1988) answers
    the other one. MEASURED (order 2, osr 256, vref 1.0, vdd 1.2): with that
    set one DAC decision moves the loop filter by half the reference and the
    first integrator SATURATES IN TWO CLOCKS of a 256-clock window, so the
    loop never leaves a rail and the bitstream carries no code at any input.

    THE BOUND. In an Lth-order cascade run for N cycles from reset the ideal
    ramp response of the last integrator grows as N**L / L!, so keeping it
    inside the usable output swing requires

        prod(a_i) * vref * N**L / L!  <=  usable_swing

    and, for equal per-stage coefficients,

        a = ( usable_swing * L! / (vref * N**L) ) ** (1 / L)

    (Markus, Silva & Temes, "Theory and Applications of Incremental Delta-
    Sigma Converters", IEEE TCAS-I 51(4), 2004 -- the regime this converter is
    actually in.) At order 1 it reduces to a = usable_swing / (N * vref), the
    textbook first-order result, which is an independent check on the form.

    `osr` and `order` are BOUND spec rows, so the emitted set is a function of
    the declaration: change the declared OSR and the coefficients change. The
    tabulated set could not, and that is the defect.

    WHAT THIS DERIVATION CLAIMS, AND WHAT IT DOES NOT.

    IT BOUNDS OVERFLOW. That claim is measured: with the tabulated
    free-running set the first integrator saturated in TWO clocks of a
    256-clock window and the loop filter sat at a rail for the whole window;
    with a set from this derivation the loop filter stays inside the rails and
    centred near the common mode. That is the condition this bound exists to
    enforce, and it enforces it.

    IT DOES NOT SET THE GAIN. Measured end to end on a real declaration
    (order 2, osr 256, u_hawaii_adc / ihp-sg13g2), with the bias derived to
    match and the window verified LIVE before any number was read:

        coefficient          density at mid-scale     ideal
        1/8   (hand-chosen)        0.1288              0.5
        1/181 (this derivation)    0.0325              0.5

    The derived set is FURTHER from the transfer, not closer: 1/181 costs
    enough loop gain that the modulator is worse, while still not overflowing.
    So an overflow bound is NECESSARY and is not SUFFICIENT, and a design that
    satisfies it is not thereby a converter. Setting the gain is a separate
    question — loop-filter synthesis against the declared resolution — and it
    is NOT answered here. Do not read a passing overflow bound as a validated
    converter.

    (An earlier landing message credited this derivation with the 0.1288
    figure. That number came from a hand-chosen 1/8 coefficient running with a
    bias sized for 1/181 — an arm internally inconsistent by 22.6x. Recorded
    so the claim is not inherited.)
    """
    import math
    n = float(spec_values.get("osr") or 0.0)
    vref = float(spec_values.get("vref") or 0.0)
    vdd = float(spec_values.get("vdd") or 0.0)
    if order < 1 or n <= 0 or vref <= 0 or vdd <= 0:
        raise LibraryEntryError(
            f"an incremental coefficient set is DERIVED from the declaration "
            f"and needs order>=1, osr>0, vref>0, vdd>0; got order={order}, "
            f"osr={n}, vref={vref}, vdd={vdd}. A coefficient this program "
            f"cannot derive is ABSENT, never defaulted -- defaulting is how "
            f"one design's coefficients end up under another design's name.")
    swing = vdd * float(consts["integrator_swing_fraction_of_vdd"])
    a = (swing * math.factorial(order) / (vref * n ** order)) ** (1.0 / order)
    return [a] * order


#: {name: callable(order, spec_values, consts) -> [per-stage coefficient]}
COEFFICIENT_DERIVATIONS = {
    "incremental_cifb": _incremental_cifb_coefficients,
}

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
#: The generic role token a capacitor carries in this library's device
#: records. One spelling, shared by the split above and the registry's own
#: role map, so neither can drift from the other.
CAP_ROLE = "cap"

SAMPLING_CAP_L_EXPR = (
    "(" + SAMPLING_CAP_FF_EXPR + ") / (cap_area_ff_per_um2 * w_cap)")

#: The OTA's load, in farads: the integrating and compensation capacitors,
#: expressed against the sampling capacitor the noise budget already fixed.
#: The OTA load ratio for an entry whose coefficients are DERIVED. The shared
#: bias branch states the load as one ratio against the sampling capacitor;
#: once the coefficient follows `osr` that ratio does too, and stating it as a
#: constant is the same defect as tabulating the coefficient.
#: `factorial(order)` is written `order` because `requires_domain` admits only
#: orders 1 and 2, where they are equal -- an entry admitting order >= 3 must
#: state the factorial explicitly.
_LOAD_OVER_CS_DERIVED_EXPR = (
    "(1 + miller_fraction_of_load) / "
    "((vdd * integrator_swing_fraction_of_vdd * order "
    "/ (vref * osr ** order)) ** (1.0 / order))")
#: The OTA's load, in farads.
_LOAD_F_EXPR = ("(" + SAMPLING_CAP_FF_EXPR + ") * ("
                + _LOAD_OVER_CS_DERIVED_EXPR + ") / farad_to_ff")
#: The tail current the DRAWN bias resistor delivers, in amperes. The drawn
#: resistor is a length of sheet; the current follows from the supply left
#: over the mirror diode's gate voltage. Every term is either a MEASURED
#: process constant or a stated bias condition — no number is retyped from a
#: datasheet.
#: The DRAWN LENGTH of the bias-setting resistor, in microns — derived from
#: the slew the declaration asks for, not held at a library nominal.
#:
#: MEASURED (round 20): held at a nominal 181 um it delivered a tail current
#: 6x short of what the integrating capacitor needs, and `slew_margin` read
#: 0.167 against a floor of 1.0. A bias that is CHECKED against the slew but
#: never DERIVED from it is a number waiting to be wrong the moment any of
#: order, osr, enob, vref or fclk moves — and all five are bound spec rows.
#:
#:   I_slew = C_load * vref * slew_design_margin / t_settle       [A]
#:   I_bias = I_slew / mirror_ratio_tail_to_bias                  [A]
#:   R_bias = (vdd - vth - overdrive) / I_bias                    [Ohm]
#:   L      = R_bias * w_res / rsheet_ohm_per_sq                  [um]  sheet
#:
#: Two BOUND spec rows (vref, fclk) reach it directly, three more through the
#: load; the rest are MEASURED process constants and the two stated design
#: conditions already declared above. Same shape as the LDO entry's divider,
#: which derives its drawn length from a bound output voltage and a bound
#: quiescent budget.
_R_IB_L_UM_EXPR = (
    "((vdd - vth_n_extracted_v - bias_overdrive_v) "
    "* mirror_ratio_tail_to_bias * settle_periods_available "
    "/ (fclk * hz_per_mhz) "
    "/ ((" + _LOAD_F_EXPR + ") * vref * slew_design_margin)) "
    "* w_res / rsheet_ohm_per_sq")
_TAIL_I_EXPR = ("mirror_ratio_tail_to_bias * (vdd - vth_n_extracted_v "
                "- bias_overdrive_v) / (rsheet_ohm_per_sq * ("
                + _R_IB_L_UM_EXPR + ") / w_res)")
#: How many times over the drawn bias covers the slew the declaration asks
#: for. Below 1 the entry refuses itself by name.
SLEW_MARGIN_EXPR = (
    "(" + _TAIL_I_EXPR + ") * settle_periods_available "
    "/ (fclk * hz_per_mhz) / ((" + _LOAD_F_EXPR + ") * vref)")

#: SMALL-SIGNAL SETTLING — the question `slew_margin` above does not ask.
#: Slewing is the LARGE-signal race (can the bias move a full reference step
#: at all); settling is the exponential that follows it, and a block can slew
#: to the answer and never settle on it.
#:
#:     gm   = I_tail / V_ov                     (input pair carrying I_tail)
#:     tau  = C_load / gm
#:     n    = t_available / tau                 [time constants]
#:
#: WHAT CANCELS, AND WHY IT IS WRITTEN DOWN. Substituting `_TAIL_I_EXPR` —
#: which is itself DERIVED from the slew requirement — gives, exactly:
#:
#:     n = (fclk / fclk_max) * vref * slew_design_margin
#:             / integrator_input_overdrive_v
#:
#: What is left is the real question: DOES SIZING THE BIAS FOR SLEW, AT THE
#: CLOCK IT IS SIZED AT, BUY THE SETTLING THE DECLARED RESOLUTION NEEDS AT
#: THE CLOCK THE BLOCK IS RUN AT? Two bound spec rows reach the value
#: (`vref`, and the clock RATIO) and one reaches the requirement (`enob`), so
#: it is lost on a design's own numbers -- vref 0.8 with enob 16 at matched
#: clocks gives 10.67 against 11.78 and is refused, and this design's decade
#: of stated clock range gives 1.33 against 10.40 and is refused.
#:
#: `C_load` CANCELS, and with it `sampling_cap_ff`, `osr`, `enob`, `order` and
#: every process constant. That is real physics rather than a modelling slip:
#: the slew current and the settling current are BOTH proportional to the
#: load, so sizing the bias for slew pins the settling time-constant COUNT no
#: matter how large the capacitor is. VERIFIED against this module's own
#: expressions at eight declarations (osr 64/256/512, enob 10/14, order 1/2,
#: vdd 1.2/1.3, vref 0.8/1.0): the closed form above and the evaluated
#: expression agree to 1e-9 in every one.
#:
#: This is recorded for the reason `slew_margin`'s own constancy is recorded
#: two hundred lines below: a reader who believes this number responds to the
#: capacitor will read a bound that moved for the wrong reason. What it DOES
#: respond to is `vref`, the two stated design conditions, and — the term that
#: dominates here — the RATIO of the clock the circuit is SIZED at to the
#: clock it is EVALUATED at.
#: EVALUATED AT `fclk_max`, THE CLOCK THE EMITTED TESTBENCH ACTUALLY RUNS AT.
#: Not a free choice, and MEASURED rather than argued: the only deck that
#: exists for this block runs the modulator at `fclk_max` -- the deck says so
#: itself, "the modulator clock runs at the FASTEST rate the declaration
#: admits (100 ns period), which is the binding settling corner" -- and at
#: that clock it produces a density of 0.462028 where its own condition line
#: requires 0.6 (input held one tenth of the reference above mid-scale;
#: `swing` 1.04976, so the quantiser is toggling and not latched at a rail).
#: Reproduced to six decimals on two hosts by two lanes.
#:
#: The bias is DERIVED from `fclk` (see `_R_IB_L_UM_EXPR`), so reporting the
#: verdict at `fclk` instead would read 13.33 and PASS -- beside a deck that
#: measures a bitstream carrying no code. That is a false green, whatever the
#: bound's name means in isolation, and no deck runs this block at `fclk` for
#: the passing reading to describe. The clock a design is HELD to is the one
#: it is exercised at.
_SETTLING_TC_EXPR = (
    "(settle_periods_available / (fclk_max * hz_per_mhz)) "
    "/ ((" + _LOAD_F_EXPR + ") "
    "/ ((" + _TAIL_I_EXPR + ") / integrator_input_overdrive_v))")
#: ...and HOW MANY time constants the DECLARATION asks for. Settling to within
#: half an LSB of full scale is `exp(-n) <= 2 ** -(enob + 1)`, so
#: `n >= (enob + 1) * ln2`. DERIVED from a bound spec row, never tabulated: a
#: flat floor is a hidden resolution assumption, and the retired branch's flat
#: 7.0 is exactly that — it is the ~10-bit answer (7.62) carried against a
#: declaration that asks for 14 bits (10.40). Deriving it is STRICTER here,
#: not looser.
_SETTLING_TC_REQUIRED_EXPR = "(enob + settling_lsb_fraction_bits) * ln2"


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
    # the WHOLE modulator — a cascade of `order` switched-capacitor
    # integrators, a clocked 1-bit quantiser, and the 1-bit DAC that feeds
    # the quantiser's decision back into every summing node. Until this
    # round only the forward path was emitted, and the quantiser was carried
    # as a handoff; the loop is now closed HERE, which is what makes the
    # block's declared output a DECISION and not an integrator voltage.
    #
    # WHY THE BOUNDARY CHANGED (u_hawaii_adc, ihp-sg13g2, measured):
    # the entry used to draw `vdd vss vin vcm rst vout` and the DESIGN
    # declares `vdd vss vin vrefp vrefn clk bit_out` — every pin citing its
    # document line. Three of those four disagreements were not naming at
    # all, they were STRUCTURE:
    #   * `vcm` was a pin because nothing on the block generated a
    #     common-mode reference. The design declares the reference as a
    #     DIFFERENTIAL PAIR (`vrefp`/`vrefn`, "the reference is the VHI/VLO
    #     PAIR"), and the midpoint of a declared pair is generated on-chip
    #     by two matched resistors. So `vcm` becomes an internal net.
    #   * `clk` was absent because the forward path had no switches: the
    #     sampling capacitor sat wired between two nodes. A switched-
    #     capacitor integrator that never switches is a capacitor. With the
    #     sampling and charge-transfer switches drawn, the modulator clock
    #     is a pin because the circuit uses it.
    #   * `vout` was the last integrator's output because there was no
    #     quantiser. `bit_out` is declared as a "1-bit serial digital
    #     bitstream", which is the quantiser's decision — a different node,
    #     not a different name for the same one. Renaming the integrator
    #     output to `bit_out` would have closed the interface gate while
    #     shipping an analog voltage under the name of a bitstream: the
    #     substitution this file refuses everywhere else.
    #   * `rst` leaves the boundary because the corpus declaration states
    #     that it is internal to the topology, and the auto-zero phase of
    #     the SC integrator — which the clock now drives — is what defines
    #     the summing node's DC operating point. See `boundary_notes`.
    "delta_sigma": {
        "topology": ("second-order-capable cascade of {stages} "
                     "auto-zeroed switched-capacitor integrator(s) around "
                     "two-stage Miller NMOS-input OTAs, closed by a clocked "
                     "StrongARM quantiser and its set-reset output latch "
                     "through a 1-bit switched-capacitor feedback DAC into "
                     "every summing node — a complete "
                     "cascade-of-integrators-feedback (CIFB) delta-sigma "
                     "modulator. Each stage's sampling / integrating "
                     "capacitor RATIO is that stage's loop coefficient and "
                     "the absolute value is the sampled-noise budget of the "
                     "declared resolution; the feedback capacitor equals "
                     "the sampling capacitor, so the DAC's full scale IS "
                     "the declared reference"),
        "circuit_class_citation": (
            "switched-capacitor delta-sigma modulator in the "
            "cascade-of-integrators feedback form with a single-bit "
            "quantiser and single-bit capacitive feedback DAC; "
            "per-stage coefficients DERIVED for INCREMENTAL operation from "
            "the declared order and OSR (Markus, Silva & Temes, IEEE "
            "TCAS-I 51(4), 2004) rather than taken from the free-running "
            "second-order set a1 = a2 = 1/2 (Boser & Wooley, JSSC 23(6), "
            "1988), which answers a different regime; "
            "sampled kT/C noise budgeted against the "
            "quantisation floor (Schreier & Temes, Understanding "
            "Delta-Sigma Data Converters, ch.2-3); the quantiser is the "
            "StrongARM / sense-amplifier latch (Kobayashi et al., JSSC "
            "1993; Razavi, IEEE SSC Magazine 2015) with a NAND set-reset "
            "latch holding the decision across the reset phase"),
        "ports": ["vdd", "vss", "vin", "vrefp", "vrefn", "clk", "bit_out"],
        "rails": {"vdd": "vdd", "vss": "vss"},
        # `vcm` and the last integrator's output `vint` are INTERNAL — they
        # were pins only for as long as nothing on the block generated the
        # first and nothing consumed the second.
        "internal_nets": ["nbias", "vcm", "nclkb", "vint", "ndac", "ndacb",
                          "nq_p", "nq_n", "nqtail", "nsrq", "nsrqb",
                          "nn1", "nn2", "nqb",
                          # the conversion-window generator
                          "nall", "nallc", "nrm", "nrmb", "nrstb",
                          # the auto-zeroed quantiser input
                          "nqz"],
        # Stated in the artefact so a reader is told what LEFT the boundary
        # and on whose authority, instead of finding two fewer pins.
        "boundary_notes": [
            "`vcm` is not a pin: the common-mode reference is generated on "
            "the block as the midpoint of the DECLARED differential "
            "reference pair (r_cm1/r_cm2). A block that took vcm from "
            "outside would be asking the chip for a potential it can "
            "derive, and the design's interface declaration lists no such "
            "pin.",
            "`rst` is not a pin: the summing node's DC operating point is "
            "defined every clock cycle by the auto-zero switch (mn_az{i}) "
            "that the modulator clock already drives. The per-conversion "
            "reset of an INCREMENTAL converter is a different signal from "
            "this per-cycle auto-zero, it needs a start-of-conversion the "
            "declared boundary does not carry, and it is therefore closed "
            "on the DIGITAL side of `bit_out` by resetting the decimator's "
            "accumulator each conversion window. That is a real "
            "architectural choice and it is recorded here rather than "
            "implied: see `tradeoffs`.",
            "`bit_out` is the quantiser's decision, not the loop filter's "
            "output. The last integrator's output is the internal net "
            "`vint`.",
        ],
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
            "hz_per_mhz": 1.0e6,
            # Miller compensation sized against the LOAD, not held at a
            # constant. The classic starting point for a two-stage Miller
            # amplifier is Cc about a third of the load it has to dominate.
            "miller_fraction_of_load": 0.3,
            # The OTA's load is its own compensation capacitor plus the
            # integrating capacitor: (1 + miller_fraction_of_load) / coeff
            # times the sampling capacitor. Stated as ONE constant because
            # the bias branch is SHARED by every stage and cannot see a
            # per-stage coefficient; `library_invariants` refuses an entry
            # whose coefficient sets make this number too small.
            # How much of the supply an integrator output may actually use.
            # Both rails cost an output device's saturation headroom. Stated
            # once, by name, because the incremental coefficient derivation
            # divides by it.
            "integrator_swing_fraction_of_vdd": 0.833,
            # How much of a clock period the output has to slew a full
            # reference step in. A quarter: the transfer happens on one
            # phase, and half of that phase is a working margin.
            "settle_periods_available": 0.25,
            # mn_tail (w 8) against mn_bias (w 4), at the same length.
            "mirror_ratio_tail_to_bias": 2.0,
            # The gate overdrive the diode-connected mirror reference sits
            # at. A stated bias condition, used ONLY to turn the drawn
            # resistor into a current for the admission bound below — never
            # to size a device.
            "bias_overdrive_v": 0.15,
            # The auto-zero capacitor has to DOMINATE the quantiser's input
            # capacitance, or the level it stores reaches the latch through
            # a capacitive divider. MEASURED on this block with it drawn at
            # the sampling capacitor's size: the loop filter's output moved
            # +-60 mV across a conversion window and the latch's input moved
            # +-8 mV — a transfer of 0.13, against a residual offset of
            # 21 mV, so the decision never changed. A StrongARM's input pair
            # is a large device and its regenerative nodes couple back into
            # it; ten sampling capacitors is the stated answer and the
            # measurement above is why the number is not one.
            "autozero_over_sampling_cap": 10.0,
            # The DRAWN length of `r_ib`, named so the admission bound above
            # can read the resistor the library actually draws instead of a
            # number retyped beside it. `library_invariants` holds the two
            # to each other.
            # How many times over the drawn bias must cover the slew the
            # declaration asks for. A STATED design margin — the bias is
            # sized to deliver twice the current the worst transfer needs —
            # not a number lifted from any datasheet.
            "slew_design_margin": 2.0,
            # The gate overdrive the INTEGRATOR'S INPUT PAIR is biased at,
            # which is what turns its tail current into a transconductance.
            # Stated separately from `bias_overdrive_v` on purpose: that one
            # is the MIRROR DIODE's overdrive and its own comment forbids
            # using it to size or characterise a device, so reading `gm` off
            # it would be borrowing a constant against its stated meaning.
            # MEASURED corroboration (round 31, `.op` on the emitted
            # netlist): gm 697 uS at 43 uA per side is an overdrive of
            # 2 * 43u / 697u = 0.123 V. The stated 0.15 V is the
            # CONSERVATIVE side of that — a larger overdrive is less gm per
            # amp, so the settling count below comes out SMALLER (13.3
            # against 16.2) and the bound is harder to pass, not easier.
            "integrator_input_overdrive_v": 0.15,
            # Settling to within HALF an LSB, not a whole one: one extra bit
            # of headroom on the exponential. Stated as a constant because
            # the fraction is a design convention, not a process number.
            "settling_lsb_fraction_bits": 1.0,
            # The natural logarithm of 2 — a universal mathematical constant,
            # a library constant for the same reason `kt_j_300k` is one, and
            # present as a NAME because `_safe_eval` admits arithmetic over
            # named values only and permits no function calls.
            "ln2": 0.6931471805599453,
        },
        "constant_roles": {"w_cap": "cap", "w_res": "res"},
        # SHARED by every stage: the bias branch, the on-chip common-mode
        # reference, the clock complement, the quantiser, its output latch
        # and the 1-bit feedback DAC.
        "devices": [
            {"name": "r_ib", "role": "res", "function":
             "bias-setting resistor from the supply into the mirror diode",
             "nets": ["vdd", "nbias", "vss"], "w": 0.35, "l": 181.0},
            {"name": "mn_bias", "role": "nmos", "function":
             "diode-connected reference of the tail current mirror, shared "
             "by every integrator stage",
             "nets": ["nbias", "nbias", "vss", "vss"], "w": 4.0, "l": 1.0},
            # ── the on-chip common-mode reference ────────────────────────
            # ── the common-mode reference has to BE a reference ─────────
            # MEASURED (round 26, OSR 64, five inputs, one full window each).
            # `vcm` is generated by a matched resistive divider and loaded by
            # TEN switched device terminals -- counted in the emitted netlist,
            # not from the entry: both halves of each sampling and DAC return
            # gate on every stage, plus the auto-zero clamp, each dumping its
            # charge onto this node once per clock. At the instant the
            # quantiser decides, the node is not a reference at all:
            #
            #   vin       0.30    0.40    0.50    0.60    0.70
            #   vcm     0.5024  0.5336  0.5643  0.5934  0.6220
            #
            # It moves 0.1196 V across the input range -- a slope of 0.299
            # V/V -- against a declared value of (vrefp+vrefn)/2 = 0.600 V
            # and a signal differential whose whole variation is 0.004 to
            # 0.024 V. The comparator's REFERENCE tracks the thing being
            # compared, six times harder than the signal does, so the
            # decision cannot carry information no matter how good the latch
            # is. (Measured after the latch itself was made to resolve
            # (v1.16.18) and its strobe moved off the clock edge (v1.16.41):
            # the differential at the decision instant does now change sign
            # with the input, 16..32 of 63, and the output still never flips.)
            #
            # The decoupling capacitor is sized from the SWITCHED CHARGE, not
            # from a preference: four sampling/DAC capacitors of the same
            # unit size commutate onto this node every clock, so holding the
            # disturbance to a tenth of the signal needs about forty of those
            # units. It is expressed against the sampling capacitor the noise
            # budget already fixed, so it follows the declaration.
            # ── the divider now sets a REFERENCE, and a buffer drives it ─
            # MEASURED (round 26): decoupling alone got the decision-instant
            # swing from 0.1196 V to 0.0367 V and stopped there, and the
            # extrapolation closed that route -- reaching a tenth of the
            # signal would need ~734 unit capacitors, about 0.10 mm^2.
            #
            # THE SPEC, back-derived from the switched charge rather than
            # preferred: four unit sampling/DAC capacitors commutate between
            # vcm and the signal every clock, so they draw
            #     I_avg = 4 * C_unit * dV_switch * f_clk
            #           = 4 * 277.97 fF * 0.5 V * 10 MHz = 5.56 uA
            # and holding the offset under a tenth of the signal (0.0020 V)
            # needs an output impedance below 0.0020 / 5.56u = 360 ohm. The
            # divider alone is 67.2 kohm (two 181 um rppd arms in parallel at
            # the registry's measured sheet), i.e. 187x too high -- which is
            # why no capacitor closes it.
            #
            # THE TOPOLOGY IS NOT INVENTED. This design already contains two
            # of exactly the amplifier this needs: the integrator OTA, a
            # differential pair on a mirrored tail into a current-mirror load
            # with a Miller-compensated output stage. It is instantiated a
            # third time, at the SAME geometry, closed in unity gain -- the
            # inverting input IS the output -- with the divider midpoint on
            # the non-inverting input. Nothing here is a width somebody chose
            # for this block; every one of them is the integrator's own, and
            # the tail hangs off the same already-derived `nbias`.
            {"name": "mn_cmtail", "role": "nmos", "function":
             "common-mode buffer tail, mirrored from the same bias branch "
             "the integrators use",
             "nets": ["ntail_cm", "nbias", "vss", "vss"], "w": 8.0, "l": 1.0},
            # POLARITY, taken from this very OTA rather than assumed.
            # In the integrator, the device on the DIODE side (nd1) is the
            # INVERTING input: its gate rising pulls nd1 down, the mirror
            # pulls nd2 up, the output pmos turns off and the output falls.
            # The device on the mirror side (nd2) is NON-inverting. So the
            # unity-gain feedback belongs on the DIODE side and the reference
            # on the mirror side. MEASURED with them the other way round: the
            # loop is positive feedback and the buffer drives vcm to 1.11 V
            # against a divider midpoint of 0.60 V -- it pins to the rail.
            {"name": "mn_cmfb", "role": "nmos", "function":
             "common-mode buffer input pair, FEEDBACK side (inverting, the "
             "diode side of the mirror) — the output IS this input, which is "
             "what makes it unity gain",
             "nets": ["nd1_cm", "vcm", "ntail_cm", "vss"],
             "w": 16.0, "l": 0.5},
            {"name": "mn_cmin", "role": "nmos", "function":
             "common-mode buffer input pair, REFERENCE side (non-inverting, "
             "the mirror side): the divider midpoint is what this buffer "
             "reproduces",
             "nets": ["nd2_cm", "nvcmr", "ntail_cm", "vss"],
             "w": 16.0, "l": 0.5},
            {"name": "mp_cmld1", "role": "pmos", "function":
             "common-mode buffer current-mirror load, diode side",
             "nets": ["nd1_cm", "nd1_cm", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            {"name": "mp_cmld2", "role": "pmos", "function":
             "common-mode buffer current-mirror load, mirror side",
             "nets": ["nd2_cm", "nd1_cm", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            # OUTPUT STAGE SIZED FROM A MEASURED CURVE — the one place this
            # buffer departs from the integrator it copies, and the departure
            # is measured, not preferred.
            #
            # The spec is R_out < 360 ohm (back-derived from the switched
            # charge). BOTH routes were measured on the buffer alone, driven
            # by the same 5.56 uA switched current:
            #
            #   3x the tail current (tail 8u -> 24u)
            #       R_out 1249 -> 24399 ohm, output swinging 0.27 V: it makes
            #       the node TWENTY TIMES worse and the stage rings. The
            #       route is rejected by its own measurement.
            #   widen the output stage (tail unchanged at 8u)
            #       out_p/out_n   R_out      Idd      vcm centre
            #        16 /  8      1249 ohm   224 uA    0.598
            #        32 / 16       951       347       0.586
            #       256 / 16       607       347       0.591
            #       256 / 24       468       484       0.587
            #        64 / 32       387       617       0.524
            #       256 / 32       383       627       0.583
            #       512 / 28       388       555       0.590   <- CHOSEN
            #       512 / 32       357       628       0.589
            #        96 / 48       279       899       0.474
            #
            # AND THE TWO DECLARATIONS DO NOT BOTH FIT. Measured on the whole
            # block, not the bench: at 512/32 the modulator draws 1.037 mA
            # against this design's own Iout MAXIMUM of 1.0 mA (L5, L22) --
            # over the ceiling, not merely over the 0.5 mA target. At 512/28
            # it draws about 0.964 mA and R_out is 388 ohm, 7.8% above the
            # 360 ohm this round derived. Widening the pull-up further does
            # not buy it back: 1024/24 is 416 ohm against 512/24's 427, so
            # that axis has converged.
            #
            # 512/28 is chosen, and the reason is which declaration outranks
            # which. The current ceiling is the DESIGN's own stated maximum;
            # 360 ohm is an intermediate target this analysis back-derived to
            # hold vcm steady. Breaking a number the design declares is worse
            # than missing one I derived, so the derived one gives way and
            # says so. Closing both needs a topology whose output impedance
            # is not paid for in static current -- a class-AB or a switched
            # bias that is only strong at the decision instant -- and that is
            # a sizing question, not a width in this table.
            #
            # Widening both halves in proportion ALSO drags the operating
            # point off the reference (0.598 -> 0.474 as it grows), because
            # `mn_cmo` is a fixed mirror outside the feedback: raising its
            # sink current pulls the output down. So the pull-up carries the
            # width and the pull-down carries only what the impedance needs.
            #
            # The current cost is DECLARED rather than hidden: 628 uA against
            # this design's own Iout budget of 0.5 mA target / 1.0 mA maximum
            # (L5, L22) -- 26% over target, 63% of the ceiling. The PDK sets
            # only a minimum width (wmin 0.15 um, and
            # analog_a5_pdk_device_limits reports 512 um PERMITTED); a device
            # this wide is drawn multi-finger, which is A5's `m`, not A2's.
            {"name": "mp_cmo", "role": "pmos", "function":
             "common-mode buffer output stage pull-up — the device that "
             "actually makes the node low-impedance; its width comes from "
             "the measured R_out curve, not from the integrator it copies",
             "nets": ["vcm", "nd2_cm", "vdd", "vdd"], "w": 512.0, "l": 0.5},
            {"name": "mn_cmo", "role": "nmos", "function":
             "common-mode buffer output stage pull-down, mirrored from the "
             "same bias branch. It sets the stage's static current, so it "
             "carries only the width the impedance needs: widening it "
             "further buys impedance and spends the operating point",
             "nets": ["vcm", "nbias", "vss", "vss"], "w": 28.0, "l": 1.0},
            {"name": "c_cmc", "role": "cap", "function":
             "common-mode buffer Miller compensation — the same role, and "
             "the same derived size, as each integrator's own",
             "nets": ["nd2_cm", "vcm"], "w": 10.0, "l": 1.0},
            {"name": "c_vcm", "role": "cap", "function":
             "common-mode reference decoupling: the divider alone cannot "
             "hold this node against the charge ten switched terminals "
             "commutate onto it every clock",
             "nets": ["vcm", "vss"], "w": 10.0, "l": 555.9},
            {"name": "r_cm1", "role": "res", "function":
             "upper half of the matched divider that generates the "
             "common-mode reference as the midpoint of the DECLARED "
             "differential reference pair — the reason vcm is not a pin",
             "nets": ["vrefp", "nvcmr", "vss"], "w": 0.35, "l": 181.0},
            {"name": "r_cm2", "role": "res", "function":
             "lower half of the same matched divider; r_cm1/r_cm2 must "
             "MATCH, because their ratio error appears directly as a "
             "common-mode offset on every integrator",
             "nets": ["nvcmr", "vrefn", "vss"], "w": 0.35, "l": 181.0},
            # ── the clock complement (the second SC phase) ───────────────
            {"name": "mp_ckb", "role": "pmos", "function":
             "clock-complement inverter, pull-up: the charge-transfer "
             "phase is the sampling phase inverted",
             "nets": ["nclkb", "clk", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            {"name": "mn_ckb", "role": "nmos", "function":
             "clock-complement inverter, pull-down",
             "nets": ["nclkb", "clk", "vss", "vss"], "w": 4.0, "l": 0.5},
            # ── the 1-bit quantiser: a clocked StrongARM latch ───────────
            # THE QUANTISER EVALUATES ON THE CHARGE-TRANSFER PHASE, not on
            # the sampling phase. MEASURED: with the latch strobed by `clk`
            # the decision was being formed at the same time the feedback
            # DAC was sampling the reference it selects, and the modulator
            # sat in a 0.5 bitstream limit cycle whose density did not move
            # at all across a 0.40 -> 0.80 V input (0.5123 / 0.5133 /
            # 0.5135). Strobed by the complement, the decision is settled
            # and held by the set-reset latch before the DAC samples it,
            # and the density becomes input-dependent.
            # ── the quantiser strobe is DELAYED off the clock edge ──────
            # MEASURED (round 25, OSR 64, five inputs, one full window each).
            # The latch was strobed by `nclkb`, i.e. it began evaluating on
            # the very edge the sampling and DAC switches fire on, and a
            # StrongARM commits within ~1.5 ns of its tail turning on. At
            # that instant the differential it is handed is a
            # clock-injection transient, not the signal:
            #
            #   offset from the tail turning on   nqz - vcm, mean over a window
            #     1.5 ns   +0.098 .. +0.153 V at EVERY input, sign 63/63
            #    40   ns   -0.033 .. +0.033 V, and it TRACKS the input
            #
            # The transient is 3-5x the signal and is the same at every
            # input, so the decision carried no information. The loop filter
            # itself was fine: vint's window mean moves monotonically with
            # the input, 0.5668 -> 0.6122 V over vin 0.30 -> 0.70, about
            # 11.4 mV per 100 mV.
            #
            # It is a PHASE defect, not a settling-budget one: the signal is
            # already there before the edge and is there again after it, and
            # only the 1-3 ns window around the edge is corrupted. So the
            # strobe is moved off the edge rather than the settling budget
            # being enlarged.
            {"name": "mp_qdly1", "role": "pmos", "function":
             "quantiser strobe delay, stage 1 pull-up — the latch must not "
             "begin evaluating on the same edge the switches fire on",
             "nets": ["nqd1", "nclkb", "vdd", "vdd"], "w": 1.0, "l": 0.5},
            {"name": "mn_qdly1", "role": "nmos", "function":
             "quantiser strobe delay, stage 1 pull-down",
             "nets": ["nqd1", "nclkb", "vss", "vss"], "w": 0.5, "l": 0.5},
            {"name": "c_qdly", "role": "cap", "function":
             "the delay itself: the load this weak stage has to drive. Sized "
             "from the MEASURED decay of the clock-injection transient (gone "
             "by 10 ns of a 100 ns period), not from a preference",
             "nets": ["nqd1", "vss"], "w": 10.0, "l": 60.0},
            {"name": "mp_qdly2", "role": "pmos", "function":
             "quantiser strobe delay, stage 2 pull-up — restores the edge "
             "and the polarity, so the tail still evaluates on the "
             "charge-transfer phase, only later within it",
             "nets": ["nqstb", "nqd1", "vdd", "vdd"], "w": 4.0, "l": 0.5},
            {"name": "mn_qdly2", "role": "nmos", "function":
             "quantiser strobe delay, stage 2 pull-down",
             "nets": ["nqstb", "nqd1", "vss", "vss"], "w": 2.0, "l": 0.5},
            {"name": "mn_qtail", "role": "nmos", "function":
             "quantiser clocked tail switch: it evaluates on the "
             "CHARGE-TRANSFER phase, when the last integrator carries the "
             "value just integrated, so the decision is settled before the "
             "feedback DAC samples the reference it selects — and it is "
             "strobed by the DELAYED copy of that phase, so it does not "
             "commit inside the edge's own injection transient",
             "nets": ["nqtail", "nqstb", "vss", "vss"], "w": 16.0,
             "l": 0.5},
            # ── the quantiser's input is AUTO-ZEROED ────────────────────
            # `caz` stands between the loop filter's output and the latch,
            # and its far plate is tied to the common-mode reference while
            # the block is in reset. The capacitor therefore stores the
            # integrator's OWN reset level, and what reaches the latch after
            # the reset opens is the common mode plus the CHANGE the
            # integrator has accumulated since. The comparison is against
            # zero accumulated charge, which is what a conversion actually
            # asks.
            #
            # MEASURED, and this is why it is here rather than in a list of
            # refinements. Comparing `vint` against `vcm` directly compares
            # two nodes that are only equal if the amplifier's output
            # equilibrium equals its input equilibrium, and a real two-stage
            # amplifier's does not: on this block the loop filter reset to
            # 0.507 V against a 0.610 V reference, so the quantiser read
            # "below threshold" on every one of the 256 clocks of the
            # window and the bitstream never left 0 — with the counter, the
            # reset, the latch and the DAC all working. An incremental
            # converter cannot out-run that offset, because the reset
            # re-imposes it at the start of every window.
            {"name": "caz", "role": "cap", "function":
             "auto-zero capacitor: stores the loop filter's reset level so "
             "the quantiser compares the CHANGE since reset, not two "
             "equilibria that are not the same voltage",
             "nets": ["vint", "nqz"], "w": 10.0, "l": 2.6},
            {"name": "mn_azq", "role": "nmos", "function":
             "auto-zero switch (n-side): ties the latch's input to the "
             "common-mode reference while the block is in reset",
             "nets": ["nqz", "nall", "vcm", "vss"], "w": 2.0, "l": 0.15},
            {"name": "mp_azq", "role": "pmos", "function":
             "auto-zero switch (p-side of the transmission gate)",
             "nets": ["nqz", "nrstb", "vcm", "vdd"], "w": 4.0, "l": 0.15},
            # MEASURED (round 21, the quantiser extracted and driven by
            # ideal sources): with the input pair's drains ON the latch
            # nodes and NO cross-coupled nmos pair, this is not a StrongARM
            # and does not regenerate. During evaluate both cross-coupled
            # PMOS sit in SATURATION at |Vgs| 1.039 / |Vth| 0.367, both
            # input devices in TRIODE (Vds 0.106 < 0.299 overdrive) and the
            # tail in deep triode (Vds 0.054) — a static resistive path from
            # vdd to vss that clamps BOTH outputs at 0.1605 V. The output
            # separation was then LINEAR in the input, 0.0025 V at 2 mV and
            # 0.0255 V at 20 mV: a ~1.3 V/V amplifier, not a comparator.
            # The input pair therefore drains to INTERMEDIATE nodes and the
            # latch gets its missing nmos half.
            {"name": "mn_qin", "role": "nmos", "function":
             "quantiser input pair, signal side — the auto-zeroed image of "
             "the last integrator's output is what gets compared. Its drain "
             "is the INTERMEDIATE node, not the latch node: a StrongARM "
             "separates the input stage from the regenerative nodes",
             "nets": ["ndi_n", "nqz", "nqtail", "vss"], "w": 16.0, "l": 0.5},
            {"name": "mn_qref", "role": "nmos", "function":
             "quantiser input pair, reference side: the threshold is the "
             "on-chip common mode, i.e. the midpoint of the declared "
             "reference pair",
             "nets": ["ndi_p", "vcm", "nqtail", "vss"], "w": 16.0, "l": 0.5},
            {"name": "mn_qlat1", "role": "nmos", "function":
             "quantiser cross-coupled regenerative latch, NMOS half, plus "
             "side. Without it the pmos pair is a cross-coupled LOAD and "
             "the loop gain never exceeds one",
             "nets": ["nq_n", "nq_p", "ndi_n", "vss"], "w": 8.0, "l": 0.5},
            {"name": "mn_qlat2", "role": "nmos", "function":
             "quantiser cross-coupled regenerative latch, NMOS half, minus "
             "side",
             "nets": ["nq_p", "nq_n", "ndi_p", "vss"], "w": 8.0, "l": 0.5},
            {"name": "mp_qlat1", "role": "pmos", "function":
             "quantiser cross-coupled regenerative latch, PMOS half, plus "
             "side",
             "nets": ["nq_p", "nq_n", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            {"name": "mp_qlat2", "role": "pmos", "function":
             "quantiser cross-coupled regenerative latch, PMOS half, minus "
             "side",
             "nets": ["nq_n", "nq_p", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            {"name": "mp_qrsti1", "role": "pmos", "function":
             "pre-charge for the INTERMEDIATE node, plus side. The latch "
             "nodes' own pre-charge does not reach these, and an "
             "intermediate node that never resets carries the previous "
             "decision into the next one",
             "nets": ["ndi_p", "nqstb", "vdd", "vdd"], "w": 4.0, "l": 0.5},
            {"name": "mp_qrsti2", "role": "pmos", "function":
             "pre-charge for the INTERMEDIATE node, minus side",
             "nets": ["ndi_n", "nqstb", "vdd", "vdd"], "w": 4.0, "l": 0.5},
            {"name": "mp_qrst1", "role": "pmos", "function":
             "quantiser pre-charge switch, plus side (pre-charge is "
             "the SAMPLING phase — see the tail switch). Strobed by the "
             "DELAYED phase for the same reason the tail is: a PMOS "
             "pre-charge and an NMOS tail from one net are opposite phase "
             "by device type, and delaying only one of them leaves them "
             "both conducting for the length of the delay",
             "nets": ["nq_p", "nqstb", "vdd", "vdd"], "w": 4.0, "l": 0.5},
            {"name": "mp_qrst2", "role": "pmos", "function":
             "quantiser pre-charge switch, minus side",
             "nets": ["nq_n", "nqstb", "vdd", "vdd"], "w": 4.0, "l": 0.5},
            # ── the set-reset latch that HOLDS the decision ──────────────
            # A StrongARM latch pre-charges BOTH outputs high while the
            # clock is low, so its own outputs carry no decision for half
            # of every cycle. The DAC branch and the block's declared
            # output both need the decision to stand for the WHOLE cycle,
            # which is what this pair of cross-coupled NANDs does.
            {"name": "mp_n1a", "role": "pmos", "function":
             "output latch NAND-1 pull-up driven by the quantiser's minus "
             "output (active-low set)",
             "nets": ["nsrq", "nq_n", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            {"name": "mp_n1b", "role": "pmos", "function":
             "output latch NAND-1 pull-up driven by the latch's own "
             "complement (the cross-coupling)",
             "nets": ["nsrq", "nsrqb", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            {"name": "mn_n1a", "role": "nmos", "function":
             "output latch NAND-1 pull-down, upper series device",
             "nets": ["nsrq", "nq_n", "nn1", "vss"], "w": 8.0, "l": 0.5},
            {"name": "mn_n1b", "role": "nmos", "function":
             "output latch NAND-1 pull-down, lower series device",
             "nets": ["nn1", "nsrqb", "vss", "vss"], "w": 8.0, "l": 0.5},
            {"name": "mp_n2a", "role": "pmos", "function":
             "output latch NAND-2 pull-up driven by the quantiser's plus "
             "output (active-low reset)",
             "nets": ["nsrqb", "nq_p", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            {"name": "mp_n2b", "role": "pmos", "function":
             "output latch NAND-2 pull-up driven by the latch's own true "
             "side (the cross-coupling)",
             "nets": ["nsrqb", "nsrq", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            {"name": "mn_n2a", "role": "nmos", "function":
             "output latch NAND-2 pull-down, upper series device",
             "nets": ["nsrqb", "nq_p", "nn2", "vss"], "w": 8.0, "l": 0.5},
            {"name": "mn_n2b", "role": "nmos", "function":
             "output latch NAND-2 pull-down, lower series device",
             "nets": ["nn2", "nsrq", "vss", "vss"], "w": 8.0, "l": 0.5},
            # ── the declared output and its complement ───────────────────
            {"name": "mp_obuf", "role": "pmos", "function":
             "output driver pull-up: the block's DECLARED 1-bit output, "
             "held for the whole clock cycle by the latch above",
             "nets": ["bit_out", "nsrqb", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            {"name": "mn_obuf", "role": "nmos", "function":
             "output driver pull-down",
             "nets": ["bit_out", "nsrqb", "vss", "vss"], "w": 4.0, "l": 0.5},
            {"name": "mp_bbuf", "role": "pmos", "function":
             "complement of the decision, pull-up — the 1-bit DAC needs "
             "both polarities to steer the reference",
             "nets": ["nqb", "bit_out", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            {"name": "mn_bbuf", "role": "nmos", "function":
             "complement of the decision, pull-down",
             "nets": ["nqb", "bit_out", "vss", "vss"], "w": 4.0, "l": 0.5},
            # ── the CONVERSION WINDOW ───────────────────────────────────
            # `nall` is high when EVERY counter bit is high — the AND the
            # counter group accumulates down its own chain. One state out of
            # the window's 2**N is all-ones, so `nall` IS the per-conversion
            # reset: exactly one clock period in every window.
            #
            # ALL-ONES AND NOT ALL-ZEROS, and this was MEASURED, not chosen.
            # A transmission-gate flip-flop powers up with its internal latch
            # node low, so its output inverter drives the bit HIGH: at t=0
            # every stage of this chain reads 1. An all-ZEROS decode is
            # therefore not satisfied until the counter has walked all the
            # way round — measured on this block, the reset was still low at
            # 0.5, 1.5 and 2.5 us and the first integrator's output sat at
            # 0.828 V, never having been reset, for the whole of the window
            # the testbench was measuring. Decoding all-ONES makes the block
            # start IN reset, which is also what a converter should do on
            # power-up.
            # It is generated HERE, on the block, from the declared clock:
            # the design's interface carries no reset and no
            # start-of-conversion pin, and L5 declares the converter
            # "resets/accumulates per conversion window", so the window has
            # to come from inside.
            #
            # `nall` is already the active-high reset, so only its
            # complement costs an inverter.
            # ── the all-ones decode is REGISTERED before it resets anything ─
            # MEASURED (round 20, and still true at v1.16.67 because that
            # round's fix lived in a hand-edited netlist and never reached
            # this file): `nallc` is a combinational AND over an
            # ASYNCHRONOUS ripple counter, so it glitches on every carry
            # propagation — 5 to 6 pulses of about 0.6 ns per conversion
            # window, at 2, 4, 8 and 16 clocks after each reset. Wired
            # straight to the integrator shorts and the auto-zero clamp, each
            # glitch closes them for 0.6 ns, which is far too short for the
            # clamp to pull nqz to vcm: measured, the reset leaves
            # nqz - vcm = +0.0261 V where it should leave 0, and the
            # quantiser then carries that as a standing offset all window.
            #
            # The counter advances on the RISING edge, so the ripple settles
            # during the LOW phase. A transparent-LOW latch samples there and
            # HOLDS through the HIGH phase, and no hazard is observable. The
            # keeper is deliberately weak (1.0/0.5 um against a 4/2 um
            # forward inverter) — round 19 measured what a keeper drawn at
            # the forward inverter's own geometry does: the pass gate cannot
            # overwrite it and the latch never changes state.
            {"name": "mn_rtg", "role": "nmos", "function":
             "reset-decode register pass gate (n-side): open while the "
             "counter's ripple has settled",
             "nets": ["nallc", "nclkb", "nrm", "vss"], "w": 2.0, "l": 0.15},
            {"name": "mp_rtg", "role": "pmos", "function":
             "reset-decode register pass gate (p-side)",
             "nets": ["nallc", "clk", "nrm", "vdd"], "w": 4.0, "l": 0.15},
            {"name": "mp_rinv", "role": "pmos", "function":
             "reset-decode register storage inverter, pull-up",
             "nets": ["nrmb", "nrm", "vdd", "vdd"], "w": 4.0, "l": 0.5},
            {"name": "mn_rinv", "role": "nmos", "function":
             "reset-decode register storage inverter, pull-down",
             "nets": ["nrmb", "nrm", "vss", "vss"], "w": 2.0, "l": 0.5},
            {"name": "mp_rkp", "role": "pmos", "function":
             "reset-decode register keeper, pull-up — WEAK against the pass "
             "gate on purpose; drawn at the forward inverter's own geometry "
             "it becomes a latch the pass gate cannot overwrite",
             "nets": ["nrm", "nrmb", "vdd", "vdd"], "w": 1.0, "l": 0.5},
            {"name": "mn_rkp", "role": "nmos", "function":
             "reset-decode register keeper, pull-down",
             "nets": ["nrm", "nrmb", "vss", "vss"], "w": 0.5, "l": 0.5},
            {"name": "mp_rout", "role": "pmos", "function":
             "reset-decode register output inverter, pull-up — THIS is what "
             "drives the integrator shorts and the auto-zero clamp",
             "nets": ["nall", "nrmb", "vdd", "vdd"], "w": 4.0, "l": 0.5},
            {"name": "mn_rout", "role": "nmos", "function":
             "reset-decode register output inverter, pull-down",
             "nets": ["nall", "nrmb", "vss", "vss"], "w": 2.0, "l": 0.5},
            {"name": "mp_rstinv", "role": "pmos", "function":
             "complement of the conversion-window reset, pull-up: the "
             "p-side of every reset transmission gate takes it",
             "nets": ["nrstb", "nall", "vdd", "vdd"], "w": 8.0, "l": 0.5},
            {"name": "mn_rstinv", "role": "nmos", "function":
             "complement of the conversion-window reset, pull-down",
             "nets": ["nrstb", "nall", "vss", "vss"], "w": 4.0, "l": 0.5},
            # ── the 1-bit feedback DAC ───────────────────────────────────
            # The whole feedback path of a CIFB modulator: the decision
            # selects one END of the DECLARED reference pair onto `ndac`,
            # and every stage samples `ndac` onto its own feedback
            # capacitor. This is what makes vrefp and vrefn load-bearing.
            # THE SIGN IS THE WHOLE POINT. A decision of 1 means the loop
            # filter has integrated too far UP, so the branch it selects
            # must pull the summing node DOWN on the next transfer — which
            # is why a decision of 1 selects the NEGATIVE end of the
            # declared pair. Selecting the positive end would be positive
            # feedback: the modulator would latch at a rail and the
            # bitstream density would read 0 or 1 whatever the input did
            # (measured, before this sign was fixed: density 3.6e-7 on a
            # mid-scale input).
            #
            # Every switch in this block that passes an ANALOG level is a
            # CMOS transmission gate, never a lone NMOS. An n-channel pass
            # device driven from a 1.2 V rail cannot pass 1.1 V at all
            # (Vgs = 0.1 V, below threshold) and passes the 0.6 V common
            # mode only weakly, so an NMOS-only reference selector delivers
            # nothing on the positive end and an RC-limited edge on the
            # other. Both polarities are drawn for every gate below.
            {"name": "mn_dac1", "role": "nmos", "function":
             "feedback DAC, decision-1 branch (n-side): steers the "
             "NEGATIVE end of the declared reference pair onto the DAC "
             "node, which is the SUBTRACTING branch of the loop",
             "nets": ["ndac", "bit_out", "vrefn", "vss"], "w": 4.0,
             "l": 0.15},
            {"name": "mp_dac1", "role": "pmos", "function":
             "feedback DAC, decision-1 branch (p-side of the transmission "
             "gate) — without it the branch cannot pass a level near the "
             "positive rail",
             "nets": ["ndac", "nqb", "vrefn", "vdd"], "w": 8.0, "l": 0.15},
            {"name": "mn_dac0", "role": "nmos", "function":
             "feedback DAC, decision-0 branch (n-side): steers the "
             "POSITIVE end of the declared reference pair onto the DAC "
             "node, the ADDING branch",
             "nets": ["ndac", "nqb", "vrefp", "vss"], "w": 4.0, "l": 0.15},
            {"name": "mp_dac0", "role": "pmos", "function":
             "feedback DAC, decision-0 branch (p-side of the transmission "
             "gate)",
             "nets": ["ndac", "bit_out", "vrefp", "vdd"], "w": 8.0,
             "l": 0.15},
            # THE INVERTED FEEDBACK NODE. Each integrator inverts, so the
            # branch that subtracts at stage 1 ADDS at stage 2. The
            # coefficient's sign is realised by which END of the declared
            # reference pair the stage's branch samples, and the stage
            # template picks between the two by parity (`ndac{alt}`).
            {"name": "mn_dacb1", "role": "nmos", "function":
             "inverted feedback DAC, decision-1 branch (n-side): the "
             "opposite end from `mn_dac1`, for the stages an odd number of "
             "inversions away from the quantiser",
             "nets": ["ndacb", "bit_out", "vrefp", "vss"], "w": 4.0,
             "l": 0.15},
            {"name": "mp_dacb1", "role": "pmos", "function":
             "inverted feedback DAC, decision-1 branch (p-side)",
             "nets": ["ndacb", "nqb", "vrefp", "vdd"], "w": 8.0, "l": 0.15},
            {"name": "mn_dacb0", "role": "nmos", "function":
             "inverted feedback DAC, decision-0 branch (n-side)",
             "nets": ["ndacb", "nqb", "vrefn", "vss"], "w": 4.0, "l": 0.15},
            {"name": "mp_dacb0", "role": "pmos", "function":
             "inverted feedback DAC, decision-0 branch (p-side)",
             "nets": ["ndacb", "bit_out", "vrefn", "vdd"], "w": 8.0,
             "l": 0.15},
        ],
        "spec_knobs": [],
        "device_param_exprs": [
            {"device": "caz", "param": "l",
             "expr": ("autozero_over_sampling_cap * ("
                      + SAMPLING_CAP_L_EXPR + ")"),
             "rationale": ("the auto-zero capacitor has to DOMINATE the "
                           "quantiser's input capacitance or the level it "
                           "stores reaches the latch divided down. Measured "
                           "at one sampling capacitor: a transfer of 0.13, "
                           "and a decision that never changed")},
            {"device": "c_cmc", "param": "l",
             "expr": ("miller_fraction_of_load * ("
                      + SAMPLING_CAP_L_EXPR + ") * "
                      + _LOAD_OVER_CS_DERIVED_EXPR),
             "rationale": ("the buffer is the integrator OTA instantiated a "
                           "third time, so its compensation is the same "
                           "quantity the integrators' own is — derived, not "
                           "the number that happened to be right for an "
                           "earlier declaration")},
            {"device": "c_vcm", "param": "l",
             "expr": "40.0 * (" + SAMPLING_CAP_L_EXPR + ")",
             "rationale": ("four unit sampling/DAC capacitors commutate onto "
                           "vcm every clock; holding the disturbance to a "
                           "tenth of the signal takes about forty of those "
                           "units. Measured undecoupled: vcm moves 0.1196 V "
                           "over the input range, 6x the signal's own "
                           "variation, and the decision cannot carry "
                           "information while that is true")},
            {"device": "r_ib", "param": "l",
             "expr": _R_IB_L_UM_EXPR,
             "rationale": ("the bias-setting resistor DELIVERS the slew, so "
                           "its drawn length follows the load the "
                           "coefficient implies and the clock the "
                           "declaration binds. Measured held at a library "
                           "nominal: a tail current 6x short of the "
                           "integrating capacitor's need, and slew_margin "
                           "0.167 against a floor of 1.0 — the entry "
                           "correctly refusing a design nothing had sized")},
        ],
        "requires_bound": {
            "order": {"unit": "", "why":
                      "the loop order fixes BOTH the number of integrator "
                      "stages and which coefficient set applies; with no "
                      "order there is no device count"},
            "vdd": {"unit": "V", "why":
                    "the incremental coefficient set is derived against the "
                    "swing an integrator output actually has, and that swing "
                    "is a fraction of the CORE SUPPLY. With no supply bound "
                    "there is no swing, and a coefficient derived against an "
                    "assumed one is one design's number under another "
                    "design's name"},
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
                     "against, and — now that the loop is closed — it is "
                     "also the span the 1-bit DAC feeds back"},
            # THE TOP OF THE DECLARED CLOCK RANGE. The amplifier is hardest
            # at the fastest clock the declaration admits, so that is the
            # corner both the slew bound and this entry's own testbench are
            # evaluated at. Required, not defaulted: a declaration that
            # states a clock TARGET and no range has not said what the block
            # must work over, and refusing is the honest answer to that.
            "fclk_max": {"unit": "MHz", "why":
                         "an integrator that settles at the target clock "
                         "may not settle at the fastest one the declaration "
                         "admits, and the fastest is the one the block is "
                         "held to. A declaration with no stated range does "
                         "not say what has to be met"},
        },
        # The slew bound below is evaluated against the process's OWN
        # measured constants, so the entry names them and refuses a family
        # that has not been characterised for them rather than sizing
        # against a number from somewhere else. `pdk_analog_characterize.py`
        # is what closes that, and the gap artefact says so.
        "requires_pdk_measured": ["cap_area_ff_per_um2",
                                  "rsheet_ohm_per_sq",
                                  "vth_n_extracted_v"],
        "requires_domain": {
            # An order nobody authored a coefficient set for is refused by
            # name. A third-order single-bit loop is stable only under a
            # coefficient set that is a design solution rather than a fixed
            # structure, so it is absent here for the same reason the whole
            # class used to be.
            "order": [1, 2],
        },
        "requires_derived": [
            # WHAT THIS BOUND ACTUALLY MEASURES, since its name suggests
            # something it stopped measuring in v1.16.10.
            #
            # MEASURED (round 33, v1.17.12 / 626809984241): it reads 2.0000 at
            # fclk = 0.1, 1.0 and 10.0 MHz alike -- it is IDENTICALLY
            # `slew_design_margin`, for every declaration. `fclk` appears once
            # in the time available (1/fclk) and once inside the bias length
            # this entry derives FROM the slew requirement, so
            # I_tail ∝ fclk cancels it:
            #
            #     fclk   r_ib_l_um   I_tail      C_load     slew_margin
            #      0.1    150.889     9.81 uA   12.267 pF     2.0000
            #      1.0     15.089    98.14      12.267        2.0000
            #     10.0      1.509   981.37      12.267        2.0000
            #
            # So it cannot fail on a design's numbers, and reading it as
            # "this block has 2x the slew it needs" is reading a constant.
            # It is retained as a CONSISTENCY check and nothing more: it moves
            # only if `_LOAD_F_EXPR` and `_R_IB_L_UM_EXPR` are edited apart,
            # which is a real regression and the reason not to delete it.
            #
            # Changing it to read `fclk_max` -- the clock the emitted
            # testbench actually uses -- was tried and MEASURED to change
            # nothing, for the same cancellation. The clock mismatch is real
            # but it is not here: see the note on `bias_resistor_l_um`.
            {"name": "slew_margin", "expr": SLEW_MARGIN_EXPR,
             "min": 1.0, "max": 1.0e9,
             "why": ("the integrator's output has to move a full reference "
                     "step within the part of a clock period this entry "
                     "budgets for it. That is a race between the BIAS the "
                     "library draws and the CLOCK and CAPACITANCE the "
                     "declaration asks for, and the declaration can lose "
                     "it: a fast enough clock, or a resolution that budgets "
                     "a large enough sampling capacitor, makes this entry's "
                     "amplifier too slow for its own loop. A margin below 1 "
                     "is that statement, and it is the answer — sizing the "
                     "bias silently to whatever the declaration asked for "
                     "would report a converter that does not settle as one "
                     "that does. MEASURED at the declaration in hand "
                     "(fclk 1 MHz, ENOB 14, OSR 256, vref 1 V, "
                     "ihp-sg13g2): about 23, so the nominal bias is carried "
                     "and this bound is what says it was checked")},
            # THE CLOCK MISMATCH, recorded where it lives and NOT fixed
            # here. This entry binds `fclk_max` (see requires_bound), builds
            # its testbench from `fclk_max` --
            #     tper_ns   = 1000 / fclk_max
            #     thigh_ns  = 1000 / fclk_max / 2 - 1
            #     tmeas_ns  = window_clocks * 1000 / fclk_max * 1.02
            #     tstop_ns  = window_clocks * 2000 / fclk_max
            # -- and then derives the CIRCUIT from `fclk`: this expression,
            # `_TAIL_I_EXPR`, and the `r_ib` length that follows from it. On
            # the declaration in hand that is 1.0 MHz against a 10 MHz
            # testbench, so the bias is sized for a clock ten times slower
            # than the one it is simulated at: 98 uA where fclk_max would ask
            # for 981 uA.
            #
            # It is NOT changed here, deliberately. Deriving the bias at
            # fclk_max multiplies the integrator tail current by ten and
            # lands directly on the current ceiling that is already the
            # subject of an open decision -- see
            # docs/research/2026-09-03-u-hawaii-adc-delta-sigma-three-way-
            # constraint-conflict.md. Which declaration gives way is not this
            # file's call to make silently.
            {"name": "bias_resistor_l_um", "expr": _R_IB_L_UM_EXPR,
             "min": 1.0, "max": 2000.0,
             "why": ("the bias resistor is now DERIVED from the slew the "
                     "declaration asks for, so `slew_margin` below is met by "
                     "construction and this is the check that actually "
                     "binds: a declaration whose slew needs a resistor "
                     "shorter than the PDK can draw or longer than the die "
                     "can hold is a statement that the converter cannot be "
                     "biased this way, and saying so IS the answer. "
                     "`slew_margin` is retained as a CONSISTENCY check: it "
                     "can still fail if the load expression and this "
                     "derivation are edited apart, which is a real "
                     "regression and the reason it is not deleted")},
            # THE COMPANION BOUND `slew_margin` NEVER WAS. `slew_margin`
            # above asks whether the bias can MOVE a full reference step in
            # the time budgeted; this asks whether the loop then SETTLES on
            # it to the resolution the declaration asks for. Different
            # questions, different answers: a converter can slew to the
            # answer and never settle on it, and the bitstream it emits
            # carries no code.
            #
            # MEASURED, END TO END, AND THAT IS WHY THIS ENTRY REFUSES.
            # The emitted deck holds the input one tenth of the reference
            # above mid-scale and states its own acceptance in the deck:
            # the mean of the 1-bit output "must be 0.5 plus the input's
            # fraction of the reference span -- 0.6 here". It measures
            #
            #     density 0.462028   against 0.6 required
            #     swing   1.04976    (so the quantiser IS toggling, not
            #                         latched at a rail, and it is not the
            #                         0.5 of a loop ignoring its input)
            #
            # -- below mid-scale for an input above it, i.e. moving the
            # WRONG WAY. Reproduced to six decimals on two hosts by two
            # independent lanes on the same A3 netlist.
            #
            # WHAT CAN AND CANNOT MOVE IT, stated because `slew_margin` two
            # entries below had to learn the same lesson. The bias is DERIVED
            # from the slew requirement, so substituting that derivation
            # collapses the value to
            #
            #     n = (fclk / fclk_max) * vref * slew_design_margin
            #             / integrator_input_overdrive_v
            #
            # and `C_load` cancels, taking `sampling_cap_ff`, `osr`, `order`
            # and every process constant with it. Real physics, not a
            # modelling slip: the slew current and the settling current are
            # BOTH proportional to the load, so sizing for slew pins the
            # settling COUNT however large the capacitor is. It is NOT the
            # `slew_margin` defect, because two bound spec rows reach the
            # value (`vref`, and the clock RATIO) and one reaches the
            # requirement (`enob`):
            #
            #     vref 1.0, enob 14, fclk_max == fclk -> 13.33 vs 10.40  ok
            #     vref 0.8, enob 16, fclk_max == fclk -> 10.67 vs 11.78  REFUSED
            #     this declaration (fclk 1.0, fclk_max 10) ->  1.33 vs 10.40  REFUSED
            #
            # NOT CLOSEABLE BY SIZING, WHICH IS WHY IT IS LEFT TO REFUSE.
            # The only knobs are the clock ratio and the stated ratio
            # vref*slew_design_margin/integrator_input_overdrive_v. Buying
            # the missing 7.8x through the bias raises the tail current
            # 98 uA -> 766 uA against a block already measured at 0.947 mA of
            # a declared 1.0 mA ceiling -- and it does not even buy the gm:
            # MEASURED `.ac` at the emitted amplifier's own operating point
            # gives DC gain 50.3 dB -> 22.4 dB at 5x and 19.3 dB at 10x as
            # the mirror-side input device leaves saturation (Vds 0.289 ->
            # 0.024 -> 0.014 V). Nor may this file close it by re-sizing the
            # amplifier: THIS ENTRY ITSELF hands that trade away, in the
            # provenance it writes into every deck -- "the OTA inside each
            # integrator is carried at the reference geometry: its
            # transconductance sets whether the stage settles inside the
            # clock phase, and trading that against current is sizing
            # judgment owned by skill `analog-sizing`".
            #
            # SO WHAT WOULD HAVE TO CHANGE IS A DECLARATION, and by a stated
            # amount: `fclk_max` down to 1.2824 MHz (= fclk * 13.33 / 10.40),
            # or the current ceiling up from the declared 1.0 mA. Which one
            # gives way is a decision about the design; this entry's job is
            # to say that one of them must, and it says it by refusing.
            {"name": "settling_time_constants", "expr": _SETTLING_TC_EXPR,
             "min_expr": _SETTLING_TC_REQUIRED_EXPR, "max": 1.0e9,
             "why": ("the summing node has to SETTLE inside the part of the "
                     "clock this entry budgets for the transfer, not merely "
                     "slew across it. Settling to within half an LSB of full "
                     "scale takes (enob + 1) * ln2 time constants of "
                     "C_load/gm — DERIVED from the declared resolution, "
                     "because a flat floor is a hidden resolution "
                     "assumption. Fewer than that and the charge stays on "
                     "the summing node instead of reaching the integrating "
                     "capacitor, which is a converter that does not "
                     "integrate. A count below the requirement is that "
                     "statement, and saying so IS the answer")},
            {"name": "sampling_cap_ff", "expr": SAMPLING_CAP_FF_EXPR,
             "min": 1.0, "max": 100000.0,
             "why": ("the noise budget derived from this declaration has to "
                     "land on a capacitor that can actually be drawn. A "
                     "resolution / reference / OSR triple that asks for one "
                     "outside this range is a statement that the converter "
                     "cannot be built this way, and saying so IS the "
                     "answer — rendering it anyway is not")},
        ],
        # The nets an arm runner reads to decide whether a measured window
        # is evidence at all. `reset` released, `feedback` taking BOTH
        # reference states, `decision` leaving precharge — measured, not
        # assumed. A window failing any of them is NOT_MEASURED.
        "liveness_nodes": {"reset": "nall", "feedback": "ndac",
                           "decision": "nq_n"},
        # DERIVED from the declaration, not tabulated: this converter resets
        # every window and accumulates from zero for `osr` clocks, and the
        # tabulated free-running set saturated its first integrator in TWO
        # clocks of a 256-clock window (measured, round 20).
        "coefficient_derivation": "incremental_cifb",
        "stage": [{
            "count_from": "order",
            "first_in": "vin",
            # NOT a port. The last integrator drives the QUANTISER, and the
            # block's declared output is the quantiser's decision.
            "last_out": "vint",
            "inner_out": "vo{i}",
            # Each integrator INVERTS, so the feedback branch has to sample
            # the opposite end of the reference pair one stage further from
            # the quantiser. `{alt}` selects `ndac` / `ndacb`.
            #
            # WHICH ONE IS NOT WRITTEN DOWN HERE ANY MORE, and that is the
            # repair. It used to be a fixed per-stage table justified by "each
            # integrator INVERTS" — a CLAIM ABOUT THIS CIRCUIT, kept where
            # nothing re-derives it. When the branches below were given their
            # summing-node switches the claim went false (a branch that samples
            # on one phase and transfers on the other is DELAYING and
            # NON-INVERTING), the table put stage 2's feedback in positive sign,
            # and the loop latched: density 1.0000 and ZERO bit transitions at
            # every input. With the same branches and the selector derived, the
            # modulator converts — monotonic over ten inputs, 9 of 9 PVT
            # corners. `derived_feedback_suffixes` computes it from the
            # polarity the emitted branches actually have.
            #
            # `alternates` is RETAINED as the declaration of which two
            # selectors exist, and as the fallback for any entry that does not
            # declare `feedback_selectors`. It is no longer consulted here.
            "alternates": ["", "b"],
            # WHICH PORT IS THE POSITIVE REFERENCE IS A DECLARED FACT, not a
            # topological one, so it stays declared. `mn_dac1` ties `ndac` to
            # `vrefn` when the decision is asserted and `mn_dacb1` ties `ndacb`
            # to `vrefp`, so `b` is the selector that feeds the POSITIVE end
            # back. The integrator's SIGN is topological and is derived; only
            # separating those two makes the parity a consequence instead of
            # an assumption.
            "feedback_selectors": {"neg": "", "pos": "b"},
            "internal_nets": ["ntail{i}", "nd1_{i}", "nd2_{i}", "vsum{i}",
                              "nsmp{i}", "ndacs{i}",
                              # the SUMMING-NODE plate of each switched
                              # capacitor is a node of its own, because it
                              # is switched too. See `mn_cstv{i}` below.
                              "ncst{i}", "ncft{i}"],
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
                 "stage {i} input pair, common-mode reference side — the "
                 "reference is the on-chip midpoint of the declared pair",
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
                # SYSTEMATIC-OFFSET-FREE SIZING, and it is load-bearing
                # here rather than a refinement. For a two-stage Miller
                # amplifier the second stage's input device must be sized so
                # that the mirror load's balanced output voltage is exactly
                # the gate voltage that stage needs:
                #     (W/L)_mp_o / (W/L)_mp_ld2 = 2 * I_out / I_tail
                # mn_o and mn_tail are the same device off the same mirror,
                # so I_out = I_tail and the ratio is 2 — mp_o is twice
                # mp_ld2, not four times it.
                #
                # MEASURED at w=32 (a ratio of 4): the amplifier's own
                # unity-gain equilibrium sat at 0.747 V against a 0.633 V
                # reference. In an INCREMENTAL converter that offset is not
                # a small error — the reset leaves every integrator AT the
                # equilibrium, so a systematic offset becomes the second
                # stage's input step at the start of every conversion, and
                # the loop filter railed within a few clocks with the
                # bitstream stuck at 0.
                {"name": "mp_o{i}", "role": "pmos", "function":
                 "stage {i} second-stage common-source driver, sized twice "
                 "the mirror load so the stage's balanced input voltage IS "
                 "the mirror's balanced output voltage",
                 "nets": ["{out}", "nd2_{i}", "vdd", "vdd"],
                 "w": 16.0, "l": 0.5},
                {"name": "mn_o{i}", "role": "nmos", "function":
                 "stage {i} second-stage current-source load",
                 "nets": ["{out}", "nbias", "vss", "vss"],
                 "w": 8.0, "l": 1.0},
                {"name": "cc{i}", "role": "cap", "function":
                 "stage {i} Miller compensation across the second stage",
                 "nets": ["nd2_{i}", "{out}"], "w": 10.0, "l": 25.0},
                # ── the switched-capacitor input branch ─────────────────
                # A sampling capacitor with no switches is a capacitor.
                # These two are why `clk` is a pin.
                # Both phases of both branches are CMOS TRANSMISSION
                # GATES. See the note on the feedback DAC above: a lone
                # n-channel pass device cannot carry a level near the
                # positive rail, and every node these switches move sits
                # at or above the common mode.
                {"name": "mn_smp{i}", "role": "nmos", "function":
                 "stage {i} SAMPLING switch (n-side): on the clock-high "
                 "phase the stage input is sampled onto the bottom plate "
                 "of cs{i}",
                 "nets": ["nsmp{i}", "clk", "{in}", "vss"],
                 "w": 2.0, "l": 0.15},
                {"name": "mp_smp{i}", "role": "pmos", "function":
                 "stage {i} SAMPLING switch (p-side of the transmission "
                 "gate)",
                 "nets": ["nsmp{i}", "nclkb", "{in}", "vdd"],
                 "w": 4.0, "l": 0.15},
                {"name": "mn_smpb{i}", "role": "nmos", "function":
                 "stage {i} CHARGE-TRANSFER switch (n-side): on the "
                 "clock-low phase the bottom plate is driven to the "
                 "common-mode reference and the sampled charge moves "
                 "into ci{i}",
                 "nets": ["nsmp{i}", "nclkb", "vcm", "vss"],
                 "w": 2.0, "l": 0.15},
                {"name": "mp_smpb{i}", "role": "pmos", "function":
                 "stage {i} CHARGE-TRANSFER switch (p-side of the "
                 "transmission gate)",
                 "nets": ["nsmp{i}", "clk", "vcm", "vdd"],
                 "w": 4.0, "l": 0.15},
                {"name": "cs{i}", "role": "cap", "function":
                 "stage {i} SAMPLING capacitor — the absolute value is the "
                 "sampled-noise budget of the declared resolution",
                 "nets": ["nsmp{i}", "ncst{i}"], "w": 10.0, "l": 2.6},
                # ── the SUMMING-NODE plate is switched as well ──────────
                # A switched-capacitor integrator switches BOTH plates.
                # This branch used to hard-wire cs{i}'s upper plate to
                # `vsum{i}` and switch only the bottom one, and that is
                # not an integrator at all: with the upper plate welded to
                # the virtual ground, the bottom plate going `{in}` ->
                # `vcm` pushes +cs*({in}-vcm) into ci{i}, and the bottom
                # plate coming BACK to `{in}` on the next half cycle pulls
                # exactly the same charge out of it again. The net
                # transfer per clock PERIOD is zero, up to second-order
                # asymmetry, so the loop filter does not accumulate.
                #
                # MEASURED on the deck this producer emits, the first
                # stage's output sampled at one fixed clock phase over the
                # first 16 clocks of every conversion window: the
                # integrator moved -2.1 uV per clock where this deck's
                # capacitor ratio and common mode demand +2431 uV. The
                # load-bearing figure is the DIFFERENTIAL one, because the
                # absolute step also carries the feedback branch's charge:
                # d(step)/d(vin) measured -0.1 % of the ratio before these
                # devices and +100.8 % after them, at three input pairs
                # agreeing to 0.2 %, with the per-window slopes repeating
                # to 0.1 uV.
                #
                # The prior-round figures for the same defect — -20.3 uV
                # per clock against +1932 demanded, and +247.8 with the
                # switches hand-patched into the deck — are NOT this
                # measurement and are not quoted as one: they were taken
                # over clocks 60-199 on an older emitted artefact whose
                # common mode is 0.6125 V and which carries neither the
                # driven `vcm` nor the registered reset decode this entry
                # now emits. Same defect, different deck; the numbers
                # above are this one's.
                #
                # The upper plate therefore sits on the common-mode
                # reference while the capacitor SAMPLES (clock high, the
                # same phase `mn_smp{i}` connects the bottom plate to the
                # stage input) and reaches the virtual ground only on the
                # CHARGE-TRANSFER phase (clock low, the same phase
                # `mn_smpb{i}` returns the bottom plate to `vcm`). That is
                # the parasitic-insensitive arrangement, and it is why the
                # top-plate parasitic no longer lands on the summing node
                # during sampling. Same transmission-gate style and same
                # device geometry as the bottom-plate switches above: a
                # lone n-channel pass device cannot carry a level near the
                # positive rail, and both of these nodes sit at or above
                # the common mode.
                {"name": "mn_cstv{i}", "role": "nmos", "function":
                 "stage {i} sampling-capacitor SUMMING-NODE switch "
                 "(n-side): on the charge-transfer phase cs{i}'s upper "
                 "plate reaches the virtual ground and the sampled charge "
                 "moves into ci{i}",
                 "nets": ["ncst{i}", "nclkb", "vsum{i}", "vss"],
                 "w": 2.0, "l": 0.15},
                {"name": "mp_cstv{i}", "role": "pmos", "function":
                 "stage {i} sampling-capacitor SUMMING-NODE switch "
                 "(p-side of the transmission gate)",
                 "nets": ["ncst{i}", "clk", "vsum{i}", "vdd"],
                 "w": 4.0, "l": 0.15},
                {"name": "mn_cstc{i}", "role": "nmos", "function":
                 "stage {i} sampling-capacitor UPPER-PLATE reference "
                 "switch (n-side): while cs{i} samples, its upper plate "
                 "is held at the common-mode reference and OFF the "
                 "summing node, so the sample is taken against `vcm` and "
                 "the charge already on ci{i} is not disturbed",
                 "nets": ["ncst{i}", "clk", "vcm", "vss"],
                 "w": 2.0, "l": 0.15},
                {"name": "mp_cstc{i}", "role": "pmos", "function":
                 "stage {i} sampling-capacitor UPPER-PLATE reference "
                 "switch (p-side of the transmission gate)",
                 "nets": ["ncst{i}", "nclkb", "vcm", "vdd"],
                 "w": 4.0, "l": 0.15},
                {"name": "ci{i}", "role": "cap", "function":
                 "stage {i} INTEGRATING capacitor — cs{i}/ci{i} IS this "
                 "stage's loop coefficient",
                 "nets": ["vsum{i}", "{out}"], "w": 10.0, "l": 5.2},
                # ── the per-conversion reset: what makes it INCREMENTAL ──
                # L5 Block A declares the converter "resets/accumulates per
                # conversion window". These two switches ARE that sentence.
                # Closed together they discharge ci{i} and hold the summing
                # node at the common-mode reference, so the integrator
                # starts every conversion from a KNOWN state and its output
                # common mode is re-established once per window.
                #
                # This is the difference between a modulator that converts
                # and the one round 17 measured. Without them the output
                # common mode of a single-ended integrator is a free state —
                # whatever charge history left on ci{i} — while the
                # quantiser's threshold is fixed, so the input-referred
                # offset is unbounded and swamps the signal. Measured, round
                # 17: the bitstream density sat at 0.51 and did not move at
                # all across the input's full range.
                {"name": "mn_rsti{i}", "role": "nmos", "function":
                 "stage {i} conversion reset across ci{i} (n-side): "
                 "discharges the integrating capacitor at the start of every "
                 "conversion window",
                 "nets": ["vsum{i}", "nall", "{out}", "vss"],
                 "w": 4.0, "l": 0.15},
                {"name": "mp_rsti{i}", "role": "pmos", "function":
                 "stage {i} conversion reset across ci{i} (p-side of the "
                 "transmission gate)",
                 "nets": ["vsum{i}", "nrstb", "{out}", "vdd"],
                 "w": 8.0, "l": 0.15},
                # AND NOTHING TIES THE SUMMING NODE TO `vcm` DIRECTLY.
                # An earlier arm of this round did, on the reasoning that
                # the reset should force the node to the reference. It also
                # connects the OTA's OUTPUT to the reference through two
                # switches, and the output stage sources far more current
                # than the on-chip divider that makes `vcm` — so the
                # amplifier drags the reference instead of following it.
                # MEASURED: during reset, `vcm`, `vsum1` and `vo1` all sat
                # at 0.035 V against a 0.6 V reference, and the whole block
                # reset to the wrong voltage. The unity-gain short above is
                # sufficient BY ITSELF: with the input pair's other gate on
                # `vcm`, the amplifier's own equilibrium IS the reference,
                # and it drives its output there without loading it.
                # THERE IS NO CLAMP ON THE SUMMING NODE, deliberately.
                # An earlier arm of this round tied vsum{i} to the common
                # mode through a switch to give the node a DC path. It does
                # give it one, and it also takes the OTA OUT OF FEEDBACK
                # for half of every clock cycle: measured on this block,
                # both integrator outputs sat at a rail (0.196 V and
                # 0.013 V against a 0.600 V common mode) and the bitstream
                # never left zero. The summing node of a switched-capacitor
                # integrator is a virtual ground held by the OTA through
                # ci{i}; it is capacitive by construction, and the
                # testbench states an initial condition rather than the
                # circuit carrying a device that exists only for the
                # solver.
                # ── the DAC feedback branch into this summing node ──────
                # This is the branch whose absence made the old entry a
                # forward path rather than a modulator.
                # The DAC branch is sampled and transferred on the SAME
                # two phases as the input branch, so the two charges meet
                # at the summing node in the same transfer. The
                # subtraction is done by the DECISION's polarity at the
                # reference selector, not by running this branch on the
                # opposite phase — and WHICH selector this stage samples
                # alternates with the stage's parity, because each
                # integrator inverts. See the two selectors above.
                {"name": "mn_dacs{i}", "role": "nmos", "function":
                 "stage {i} DAC SAMPLING switch (n-side): on the "
                 "clock-high phase the selected reference end is sampled "
                 "onto the bottom plate of cf{i}",
                 "nets": ["ndacs{i}", "clk", "ndac{alt}", "vss"],
                 "w": 2.0, "l": 0.15},
                {"name": "mp_dacs{i}", "role": "pmos", "function":
                 "stage {i} DAC SAMPLING switch (p-side of the "
                 "transmission gate) — the reference ends sit at the "
                 "extremes of the declared span, so this half is what "
                 "carries the positive one at all",
                 "nets": ["ndacs{i}", "nclkb", "ndac{alt}", "vdd"],
                 "w": 4.0, "l": 0.15},
                {"name": "mn_dacr{i}", "role": "nmos", "function":
                 "stage {i} DAC RETURN switch (n-side): on the "
                 "charge-transfer phase cf{i}'s bottom plate returns to "
                 "the common-mode reference, so what the branch injects "
                 "is the reference DIFFERENCE and not its absolute level",
                 "nets": ["ndacs{i}", "nclkb", "vcm", "vss"],
                 "w": 2.0, "l": 0.15},
                {"name": "mp_dacr{i}", "role": "pmos", "function":
                 "stage {i} DAC RETURN switch (p-side of the transmission "
                 "gate)",
                 "nets": ["ndacs{i}", "clk", "vcm", "vdd"],
                 "w": 4.0, "l": 0.15},
                {"name": "cf{i}", "role": "cap", "function":
                 "stage {i} FEEDBACK DAC capacitor. It equals cs{i}, so "
                 "the fed-back charge is one full reference step against "
                 "one full input sample: the modulator's full scale IS the "
                 "declared reference",
                 "nets": ["ndacs{i}", "ncft{i}"], "w": 10.0, "l": 2.6},
                # The DAC branch is a switched capacitor for exactly the
                # same reason the input branch is, and it had exactly the
                # same defect: its upper plate was welded to `vsum{i}`, so
                # the reference charge it injected on one half cycle it
                # took straight back on the next. It runs on the SAME two
                # phases as the input branch, so the input charge and the
                # fed-back charge meet at the summing node in one
                # transfer and the subtraction happens there.
                {"name": "mn_cftv{i}", "role": "nmos", "function":
                 "stage {i} DAC-capacitor SUMMING-NODE switch (n-side): "
                 "on the charge-transfer phase cf{i}'s upper plate "
                 "reaches the virtual ground and the fed-back charge "
                 "moves into ci{i}",
                 "nets": ["ncft{i}", "nclkb", "vsum{i}", "vss"],
                 "w": 2.0, "l": 0.15},
                {"name": "mp_cftv{i}", "role": "pmos", "function":
                 "stage {i} DAC-capacitor SUMMING-NODE switch (p-side of "
                 "the transmission gate)",
                 "nets": ["ncft{i}", "clk", "vsum{i}", "vdd"],
                 "w": 4.0, "l": 0.15},
                {"name": "mn_cftc{i}", "role": "nmos", "function":
                 "stage {i} DAC-capacitor UPPER-PLATE reference switch "
                 "(n-side): while cf{i} samples the selected reference "
                 "end, its upper plate is held at the common-mode "
                 "reference and OFF the summing node",
                 "nets": ["ncft{i}", "clk", "vcm", "vss"],
                 "w": 2.0, "l": 0.15},
                {"name": "mp_cftc{i}", "role": "pmos", "function":
                 "stage {i} DAC-capacitor UPPER-PLATE reference switch "
                 "(p-side of the transmission gate)",
                 "nets": ["ncft{i}", "nclkb", "vcm", "vdd"],
                 "w": 4.0, "l": 0.15},
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
                {"device": "cc{i}", "param": "l",
                 "expr": ("miller_fraction_of_load * ("
                          + SAMPLING_CAP_L_EXPR + ") / {coeff}"),
                 "rationale": ("Miller compensation is a fraction of the "
                               "LOAD it has to dominate, and the load is "
                               "this stage's integrating capacitor. Held at "
                               "a library constant it was 25 um long "
                               "against a 3.5 um sampling capacitor — five "
                               "times the load, which is compensation for a "
                               "circuit that is not this one")},
                {"device": "cf{i}", "param": "l",
                 "expr": SAMPLING_CAP_L_EXPR,
                 "rationale": ("the 1-bit DAC's feedback capacitor is drawn "
                               "EQUAL to the sampling capacitor, so the "
                               "loop's full scale is the declared "
                               "reference and not a library constant")},
            ],
        }, {
            # ══ GROUP 2 — THE CONVERSION-WINDOW COUNTER ══════════════
            # L5 Block A: the converter "resets/accumulates per conversion
            # window". The design's own interface declaration carries no
            # `rst` and no start-of-conversion pin, and states that `rst` is
            # "INTERNAL to the block's chosen topology". So the window is
            # generated HERE, on the block, from the one timing signal the
            # boundary does declare: `clk`.
            #
            # A ripple chain of divide-by-two stages, `count_bits_for: osr`
            # of them, so the window is the fewest powers of two that reach
            # the declared oversampling ratio. Its period is 2**N clocks,
            # which is >= osr and is recorded as `window_clocks` — a ripple
            # divider cannot have a period that is not a power of two, and
            # saying so beats implying the modulus is exact.
            #
            # WHY A SECOND CHAIN. The reset is "the counter reads zero", and
            # the counter's bits are named per stage, so nothing outside the
            # group can name them all. Each stage therefore ORs its own bit
            # into a running accumulator, and the group ends that chain on
            # the fixed name `nall`. `nall` high == every bit high == reset,
            # for exactly one clock period in every window — and it is the
            # state the chain powers up in, so the block starts in reset
            # instead of a whole window later.
            "role": "conversion_window_counter",
            "count_bits_for": "osr",
            "coefficients": False,
            "first_in": "clk",
            "inner_out": "q{i}",
            # The accumulator starts from the supply rail: the AND of no
            # bits is true, and each stage can only take it away.
            "first_in2": "vdd",
            "inner_out2": "nall{i}",
            # NOT `nall`. The combinational AND over a RIPPLE counter
            # glitches on every carry, and that glitch used to BE the
            # reset — see the register at the top level.
            "last_out2": "nallc",
            "internal_nets": ["nib{i}", "nm{i}", "nmb{i}", "ns{i}",
                              "nqb{i}", "nnand{i}", "nnandp{i}"],
            "devices": [
                # ── the stage's own clock complement ──────────────────────
                {"name": "mp_cki{i}", "role": "pmos", "function":
                 "counter stage {i} input-clock inverter, pull-up: a "
                 "transmission-gate flip-flop needs both phases of the edge "
                 "it divides",
                 "nets": ["nib{i}", "{in}", "vdd", "vdd"],
                 "w": 4.0, "l": 0.5},
                {"name": "mn_cki{i}", "role": "nmos", "function":
                 "counter stage {i} input-clock inverter, pull-down",
                 "nets": ["nib{i}", "{in}", "vss", "vss"],
                 "w": 2.0, "l": 0.5},
                # ── master latch ─────────────────────────────────────────
                {"name": "mn_mtg{i}", "role": "nmos", "function":
                 "counter stage {i} master pass gate (n-side): open while "
                 "the stage's input clock is LOW, so the master follows the "
                 "fed-back complement",
                 "nets": ["nqb{i}", "nib{i}", "nm{i}", "vss"],
                 "w": 2.0, "l": 0.15},
                {"name": "mp_mtg{i}", "role": "pmos", "function":
                 "counter stage {i} master pass gate (p-side)",
                 "nets": ["nqb{i}", "{in}", "nm{i}", "vdd"],
                 "w": 4.0, "l": 0.15},
                {"name": "mp_minv{i}", "role": "pmos", "function":
                 "counter stage {i} master inverter, pull-up",
                 "nets": ["nmb{i}", "nm{i}", "vdd", "vdd"],
                 "w": 4.0, "l": 0.5},
                {"name": "mn_minv{i}", "role": "nmos", "function":
                 "counter stage {i} master inverter, pull-down",
                 "nets": ["nmb{i}", "nm{i}", "vss", "vss"],
                 "w": 2.0, "l": 0.5},
                # THE KEEPER, and it is not an optimisation. Without it the
                # latch node is DYNAMIC: held only by its own parasitic
                # capacitance while the pass gate is open, and driven by
                # nothing at all at t=0. A circuit simulator has no leakage
                # to settle such a node with, so the flip-flop has NO
                # DEFINED STATE — measured on this block, every one of the
                # eight counter bits sat at 0.06 V, the all-ones decode was
                # never satisfied, and the conversion reset never fired in
                # any window. Deliberately WEAK — narrow, at a length this
                # block already draws — so the pass gate overrides it when
                # the stage is written: (W/L) 1 against the pass gate's 13.
                #
                # AND AT A GEOMETRY THE FLOW CAN DRAW. Two arms were
                # stopped by the A5 layout generator on exactly this
                # device — "mp_mkp1, no leg tap level" — first at
                # l = 2.0 um and then at w = 1.0 um, neither of which any
                # other device in this entry draws. A geometry nothing else
                # in the block uses is one the layout instrument has never
                # been asked for.
                #
                # ROUND 19 — THE COMMENT ABOVE WAS RIGHT AND THE NUMBERS
                # BELOW DID NOT IMPLEMENT IT. "The counter's OWN inverter
                # geometry" is w=4.0/2.0 at l=0.5, i.e. (W/L) 8 and 4 against
                # the pass gate's 13.3 — a margin of 3.3x, not the "five to
                # ten times weaker" this comment claimed and not the "(W/L) 1"
                # it claimed above. A keeper at the forward inverter's own
                # size is a SYMMETRIC back-to-back latch, and MEASURED on
                # this block it could not be written: the master node tracked
                # the CLOCK instead of the data, reverting to the keeper's
                # state every time the pass gate closed, so the slave sampled
                # the same value on all 254 clocks and q1 never toggled once.
                # The all-ones decode was therefore satisfied PERMANENTLY,
                # `nall` averaged 1.19999 of a 1.2 V supply, and both
                # integrators were held in unity gain for the whole of every
                # conversion window (vsum1 and vo1 agreed to 0.35 mV). A loop
                # that is never let out of reset cannot integrate, which is
                # why the modulator produced a DC bitstream at every input.
                #
                # The keeper is now drawn at the (W/L) this comment always
                # said it wanted. MEASURED with it: q1 divides the clock by
                # two, the counter's eight bits average half the supply, the
                # reset fires instead of sticking, and vsum1 - vo1 opens to
                # 58 mV — the unity-gain short is released.
                {"name": "mp_mkp{i}", "role": "pmos", "function":
                 "counter stage {i} master keeper, pull-up: makes the latch "
                 "static, so the stage has a state at power-up",
                 "nets": ["nm{i}", "nmb{i}", "vdd", "vdd"],
                 "w": 1.0, "l": 0.5},
                {"name": "mn_mkp{i}", "role": "nmos", "function":
                 "counter stage {i} master keeper, pull-down",
                 "nets": ["nm{i}", "nmb{i}", "vss", "vss"],
                 "w": 0.5, "l": 0.5},
                # ── slave latch ──────────────────────────────────────────
                {"name": "mn_stg{i}", "role": "nmos", "function":
                 "counter stage {i} slave pass gate (n-side): open while "
                 "the input clock is HIGH, so the bit changes once per "
                 "rising edge — which is what makes the stage divide by two",
                 "nets": ["nmb{i}", "{in}", "ns{i}", "vss"],
                 "w": 2.0, "l": 0.15},
                {"name": "mp_stg{i}", "role": "pmos", "function":
                 "counter stage {i} slave pass gate (p-side)",
                 "nets": ["nmb{i}", "nib{i}", "ns{i}", "vdd"],
                 "w": 4.0, "l": 0.15},
                {"name": "mp_sinv{i}", "role": "pmos", "function":
                 "counter stage {i} slave inverter, pull-up — its output IS "
                 "this stage's counter bit and the next stage's clock",
                 "nets": ["{out}", "ns{i}", "vdd", "vdd"],
                 "w": 4.0, "l": 0.5},
                {"name": "mn_sinv{i}", "role": "nmos", "function":
                 "counter stage {i} slave inverter, pull-down",
                 "nets": ["{out}", "ns{i}", "vss", "vss"],
                 "w": 2.0, "l": 0.5},
                {"name": "mp_skp{i}", "role": "pmos", "function":
                 "counter stage {i} slave keeper, pull-up — see the master "
                 "keeper: a dynamic latch node has no state to power up in",
                 "nets": ["ns{i}", "{out}", "vdd", "vdd"],
                 "w": 1.0, "l": 0.5},
                {"name": "mn_skp{i}", "role": "nmos", "function":
                 "counter stage {i} slave keeper, pull-down",
                 "nets": ["ns{i}", "{out}", "vss", "vss"],
                 "w": 0.5, "l": 0.5},
                {"name": "mp_finv{i}", "role": "pmos", "function":
                 "counter stage {i} feedback inverter, pull-up: the "
                 "complement of the bit is what the master samples, and "
                 "that feedback is the divide-by-two",
                 "nets": ["nqb{i}", "{out}", "vdd", "vdd"],
                 "w": 4.0, "l": 0.5},
                {"name": "mn_finv{i}", "role": "nmos", "function":
                 "counter stage {i} feedback inverter, pull-down",
                 "nets": ["nqb{i}", "{out}", "vss", "vss"],
                 "w": 2.0, "l": 0.5},
                # ── the AND accumulator: "is every bit high so far?" ──────
                # A CMOS NAND2: the pull-downs are in SERIES (both inputs
                # high to pull low) and the pull-ups in PARALLEL. Wiring the
                # pull-downs in parallel would make it an inverter of one
                # input and the accumulator would forget every earlier bit —
                # the reset would fire on half the counts instead of one.
                {"name": "mn_nanda{i}", "role": "nmos", "function":
                 "counter stage {i} accumulator NAND, upper series "
                 "pull-down (the running accumulator's input)",
                 "nets": ["nnand{i}", "{in2}", "nnandp{i}", "vss"],
                 "w": 4.0, "l": 0.5},
                {"name": "mn_nandb{i}", "role": "nmos", "function":
                 "counter stage {i} accumulator NAND, lower series "
                 "pull-down (this stage's own bit)",
                 "nets": ["nnandp{i}", "{out}", "vss", "vss"],
                 "w": 4.0, "l": 0.5},
                {"name": "mp_nanda{i}", "role": "pmos", "function":
                 "counter stage {i} accumulator NAND, pull-up on the "
                 "running accumulator",
                 "nets": ["nnand{i}", "{in2}", "vdd", "vdd"],
                 "w": 4.0, "l": 0.5},
                {"name": "mp_nandb{i}", "role": "pmos", "function":
                 "counter stage {i} accumulator NAND, pull-up on this "
                 "stage's own bit",
                 "nets": ["nnand{i}", "{out}", "vdd", "vdd"],
                 "w": 4.0, "l": 0.5},
                {"name": "mp_andinv{i}", "role": "pmos", "function":
                 "counter stage {i} accumulator inverter, pull-up — NAND "
                 "then invert is AND, and the AND is what travels down the "
                 "chain to `nall`",
                 "nets": ["{out2}", "nnand{i}", "vdd", "vdd"],
                 "w": 4.0, "l": 0.5},
                {"name": "mn_andinv{i}", "role": "nmos", "function":
                 "counter stage {i} accumulator inverter, pull-down",
                 "nets": ["{out2}", "nnand{i}", "vss", "vss"],
                 "w": 2.0, "l": 0.5},
            ],
            "param_exprs": [],
        }],
        "sizing_handoff": (
            "the OTA inside each integrator is carried at the reference "
            "geometry: its transconductance sets whether the stage settles "
            "inside the clock phase, and trading that against current is "
            "sizing judgment owned by skill `analog-sizing`. The CAPACITORS "
            "are not part of that handoff — they are derived above. The "
            "quantiser's input-referred offset is likewise a sizing "
            "question: in a second-order loop it is shaped by the first "
            "integrator's gain and is not a first-order error, which is "
            "why the latch is carried at the library geometry."),
        "tradeoffs": [
            "The sampling capacitor is set by the sampled kT/C noise "
            "budget, so each extra bit of declared resolution asks for four "
            "times the capacitance; oversampling is what buys it back, "
            "which is why the absolute value falls as OSR rises.",
            "The capacitor RATIO is the loop coefficient. Raising it raises "
            "the loop gain and the integrator's output swing together, so "
            "the coefficient set is bounded by the headroom the supply "
            "leaves and not by stability alone.",
            "The feedback capacitor equals the sampling capacitor, so the "
            "modulator's full scale is the declared reference span. Making "
            "it smaller would buy input range at the cost of loop gain, "
            "and it is a coefficient choice rather than a free parameter.",
            "The per-cycle auto-zero defines the summing node without a "
            "reset pin, but it is NOT the per-conversion reset of an "
            "incremental converter: that reset is applied to the "
            "decimator's accumulator on the digital side of `bit_out`. "
            "Resetting the integrators instead would need a "
            "start-of-conversion pin, which the declared boundary does not "
            "carry, and would buy a shorter settling tail at the cost of "
            "that pin.",
            "A larger sampling capacitor lowers the sampled noise and "
            "raises the load the amplifier has to settle within one clock "
            "phase, so noise trades directly against amplifier current.",
        ],
        # ── WHAT THIS ENTRY HAS AND HAS NOT BEEN SHOWN TO DO ────────────
        # The library's standing claim is that every entry "has been
        # rendered and simulated end-to-end". For a MODULATOR that claim is
        # not enough: a loop can render, converge, and produce a
        # full-swing 1-bit output while converting nothing. So the claim is
        # written down here as a record with a verdict, and
        # `analog_topology_behaviour_check` reads it. An entry that carries
        # no `behaviour_record` is unaffected — the key is optional and
        # every other entry in this library omits it.
        "behaviour_record": {
            "claim": ("the mean of the 1-bit output over one conversion "
                      "window (its bitstream density) moves monotonically "
                      "with the analogue input, which is the whole function "
                      "of an incremental delta-sigma converter"),
            "verified": False,
            "measured_on": "u_hawaii_adc, ihp-sg13g2, 2026-09-02",
            "how": ("the entry's own testbench, ngspice in the pinned EDA "
                    "image: TWO conversion windows of 256 clocks at the "
                    "fastest clock the declaration admits, density averaged "
                    "over the second; the DC input swept 0.40 / 0.60 / "
                    "0.80 V against a 0.6 V common mode and a 1.0 V declared "
                    "reference span, for which the correct densities are "
                    "0.30 / 0.50 / 0.70"),
            # WHAT IS WORKING IS AS IMPORTANT AS WHAT IS NOT. A reader who
            # sees only "not demonstrated" will re-derive all of this.
            "subsystems_demonstrated": [
                "the conversion-window counter: the reset asserts for "
                "exactly one clock in every 256 (nall duty 0.00469 V of a "
                "1.2 V supply = 1/256), so the window IS the declared OSR",
                "the counter divides: q1 and q8 both average half the "
                "supply",
                "the on-chip common mode, generated from the declared "
                "reference pair: vcm = 0.610 V",
                "the integrators are alive and near the common mode, not "
                "railed: vo1 = 0.559 V, vint = 0.507 V — where round 17's "
                "railed",
                "the quantiser resolves rail to rail: nq_p spans -0.03 to "
                "1.24 V",
                "the set-reset latch toggles: nsrq spans -0.06 to 1.21 V",
            ],
            "arms": [
                "ROUND 17, open loop with no per-conversion reset: density "
                "0.5123 / 0.5133 / 0.5135 — a limit cycle that ignored the "
                "input, over eight structural variants",
                "ROUND 18, counter + per-conversion reset, quantiser "
                "referenced to vcm: density 6.5e-7 / 2.7e-7 / 2.8e-7, "
                "output swing 0.016 of the supply — the bitstream never "
                "leaves 0",
                "+ the auto-zeroed quantiser input at ONE sampling "
                "capacitor: density 3.4e-7 / 3.4e-7 / 3.4e-7, swing 0.003 "
                "— unchanged",
                "+ the auto-zero capacitor at TEN sampling capacitors: "
                "density 0.0082 at the LOW input with a full-swing "
                "bitstream (1.04 of the supply), and -1.5e-6 / -1.5e-6 at "
                "the other two — the output finally toggles, and it "
                "responds in the WRONG DIRECTION",
            ],
            # A HYPOTHESIS THIS ROUND RULED OUT BY MEASUREMENT, recorded so
            # the next reader does not spend a window re-testing it.
            "refuted": [
                "THE FEEDBACK SIGN was refuted on the PREVIOUS circuit "
                "and that refutation does NOT carry to this one. On the "
                "circuit as it stood before the sampling and feedback "
                "capacitors got their summing-node switches, both "
                "polarities were measured — shipped gave density 0.0082 / "
                "-1.5e-6 / -1.5e-6 and swapped gave 2.9e-5 / 0.042 / "
                "2.4e-5, neither converting, each full-swing at exactly "
                "ONE input level and dead at the others. That was a loop "
                "responding in a narrow band, not a sign error, AND IT "
                "WAS MEASURED ON A LOOP THAT TRANSFERRED ~0 CHARGE PER "
                "CLOCK: with the branch welded to the summing node the "
                "feedback polarity could not have shown itself either "
                "way. Now that the branch transfers its full designed "
                "charge the question is OPEN again, and the measurement "
                "since says the sign IS implicated: the corrected branch "
                "is a DELAYING, NON-INVERTING integrator, so this entry's "
                "stage-parity alternation of the reference end — which "
                "assumes each integrator inverts — makes the second "
                "stage's feedback positive. Do not read this entry as "
                "telling you the sign is settled",
                "CHARGE KICKED BACK from the StrongARM into the auto-zero "
                "node does NOT accumulate here. Probed across a whole "
                "conversion window, the latch's input sat at 0.586 / 0.591 "
                "/ 0.602 / 0.592 / 0.590 / 0.586 / 0.596 V — it does not "
                "walk. What that probe DID show is a capacitive divider: "
                "the loop filter's output moved +-60 mV over the same "
                "window and the latch's input moved +-8 mV, a transfer of "
                "0.13, which is why the auto-zero capacitor is now drawn "
                "ten times larger",
            ],
            "diagnosis": (
                "every SUBSYSTEM is demonstrated and the LOOP still does not "
                "close. Three causes were found and fixed in order — the "
                "quantiser referenced to a voltage the loop filter does not "
                "reset to, then the auto-zero capacitor losing a divider "
                "against the latch's input, and the systematic offset of "
                "the amplifier's second stage — and the bitstream went from "
                "DC to full-swing over that sequence. What remains is a "
                "RANGE, not sign. Both feedback polarities were "
                "measured and neither converts; in each the output is "
                "full-swing at exactly ONE input level and dead at the "
                "others. That is the signature of an integrator that "
                "SATURATES, not one wired backwards: with "
                "cs/ci = cf/ci = 1/2, a single DAC decision moves the "
                "loop filter's output by half the reference — 0.25 V "
                "of a 1.2 V rail — so three same-sign decisions after "
                "a reset exhaust the swing and the loop cannot come "
                "back. The set this entry ships (a1 = a2 = 1/2, Boser "
                "& Wooley) is the IDEAL-INTEGRATOR set and assumes an "
                "output range the supply does not give. This entry's "
                "own tradeoffs already say the coefficient set is "
                "bounded by the headroom the supply leaves and not by "
                "stability alone — that sentence is the unmet "
                "condition"),
            "next": ("SCALE THE LOOP COEFFICIENTS to the output range "
                     "the supply actually gives. Every measured symptom "
                     "is saturation, not inversion. `coefficient_sets` "
                     "carries the ideal-integrator pair 1/2, 1/2; a real "
                     "single-bit second-order loop on a 1.2 V rail needs "
                     "a smaller a1, so that one decision cannot move the "
                     "integrator a quarter of its range. That is a "
                     "change to the COEFFICIENT SET — a design solution "
                     "and not a geometry — so it belongs to "
                     "`analog-topology-select`. If range is not it "
                     "either, the remaining textbook answer is the fully "
                     "differential loop filter with common-mode "
                     "feedback, which doubles the available swing and "
                     "removes the single-ended offset that made the "
                     "auto-zero necessary at all"),
        },
        "analyses_implied": ["tran"],
        "testbench": {
            "supply_exprs": ["vdd", "nominal_supply_v"],
            "env_exprs": {
                "vcm_v": "supply / 2",
                # The DECLARED reference is a differential PAIR spanning
                # `vref`, centred on the common mode.
                "vrefp_v": "supply / 2 + vref / 2",
                "vrefn_v": "supply / 2 - vref / 2",
                # A DC input one tenth of full scale above mid-scale, for
                # which a modulator that converts must return a bitstream
                # density of 0.6 — neither 0, nor 1, nor 1/2.
                "vstep_v": "supply / 2 + vref / 10",
                # The declared clock, as a period in nanoseconds.
                # THE FASTEST CLOCK THE DECLARATION ADMITS, not its
                # target. The amplifier is hardest at the top of the
                # declared range, so that is the corner worth exercising —
                # and it is a DECLARED fact, from the same spec row.
                "tper_ns": "1000 / fclk_max",
                "thigh_ns": "1000 / fclk_max / 2 - 1",
                # ONE CONVERSION WINDOW, in nanoseconds. `window_clocks` is
                # the counter group's own period, published into the
                # constants during expansion because the expression grammar
                # has no logarithm and nothing else could derive it.
                "twin_ns": "window_clocks * 1000 / fclk_max",
                # The measurement starts after the reset clock and three
                # more, so the reset itself and the first transfers are not
                # counted as conversion samples.
                # THE SECOND WINDOW. The counter's power-up state is not
                # defined — it is a latch, and which way a bistable falls at
                # t=0 is not something the block declares — so the first
                # reset can land anywhere in the first window and the first
                # window is not a conversion. The second one is: it begins
                # at a reset the counter itself produced.
                "tmeas_ns": "window_clocks * 1000 / fclk_max * 1.02",
                "twin2_ns": "window_clocks * 2000 / fclk_max",
                "tstop_ns": "window_clocks * 2000 / fclk_max",
                "tstep_ns": "1000 / fclk_max / 200",
            },
            "conditions": [
                "supply = {supply} V (the bound core supply when the spec "
                "carries one, else the PDK's nominal)",
                "the declared reference pair is driven to {vrefp_v} / "
                "{vrefn_v} V — a span of the bound reference centred on "
                "half the supply; the block generates its own common mode "
                "from it",
                "the modulator clock runs at the FASTEST rate the "
                "declaration admits ({tper_ns} ns period), which is the "
                "binding settling corner, and the block's own counter makes "
                "the conversion window {twin_ns} ns long. The run is TWO "
                "windows and only the second is measured: an incremental "
                "converter's answer is one window's worth of bits, and the "
                "first window is not one, because the counter's power-up "
                "state is not declared and its first reset can fall "
                "anywhere inside it",
                "the input is held at {vstep_v} V, one tenth of the bound "
                "reference above mid-scale. The reported measurement is the "
                "MEAN of the 1-bit output over the conversion phase of that "
                "window, which for a converter must be 0.5 plus the input's "
                "fraction of the reference span — 0.6 here — and not the "
                "0.5 of a loop that is ignoring its input nor the 0 or 1 of "
                "one latched at a rail",
            ],
            "stimulus": [
                "v_vdd vdd 0 {supply}",
                "v_vrefp vrefp 0 {vrefp_v}",
                "v_vrefn vrefn 0 {vrefn_v}",
                "v_clk clk 0 pulse(0 {supply} 0n 1n 1n {thigh_ns}n "
                "{tper_ns}n)",
                "v_in vin 0 {vstep_v}",
            ],
            "cards": [],
            # Every node named here is a declared PORT. The measurement that
            # says whether the loop converts must not depend on an internal
            # net the emitter is free to rename, nor on the instance path it
            # chooses for the device under test.
            "control": [
                # NO `uic`. MEASURED (round 22, the quantiser on its own
                # bench, ideal differential sources): with `uic` the latch
                # decides on whatever the UNSOLVED initial node voltages
                # happen to be and the set-reset latch then HOLDS that
                # decision, so the whole bitstream inherits it. At an input
                # of -40 mV the `uic` run decides POSITIVE (wrong) and the
                # same deck without `uic` decides NEGATIVE (right) — an
                # apparent 42.5 mV input-referred offset that is entirely an
                # artefact of the initial condition, not of the circuit.
                # A clocked regenerative latch has no defined state until
                # something defines it, so the transient must start from a
                # solved operating point. Checked by run: the full 260-device
                # loop converges its `.op` with zero convergence errors.
                "tran {tstep_ns}n {tstop_ns}n",
                "meas tran vavg avg v(bit_out) from={tmeas_ns}n "
                "to={twin2_ns}n",
                "meas tran vmax max v(bit_out) from={tmeas_ns}n "
                "to={twin2_ns}n",
                "meas tran vmin min v(bit_out) from={tmeas_ns}n "
                "to={twin2_ns}n",
                "let dens = vavg / {supply}",
                "let swing = (vmax - vmin) / {supply}",
                "echo \"MEAS density=\" $&dens \" swing=\" $&swing",
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
    out = spec_row_values(data.get("specs") if isinstance(data, dict) else [])
    return out, str(p)


def spec_row_values(specs: Any) -> Dict[str, float]:
    """The numeric values a list of A1 spec rows binds, keyed by row name.

    ONE COPY OF THIS RULE. `analog_a3_netlist_emit` reads the same rows to
    build the environment its `device_param_exprs` and testbench resolve in,
    and it held a second, identical loop. MEASURED: this function was
    extended to publish the ends of a declared range and the entry began
    using one; A2 admitted the block and A3 then reported `tper_ns needs
    1000 / fclk_max, which the bound spec does not supply` — one declaration,
    two readers, two answers. A3 now calls this.
    """
    out: Dict[str, float] = {}
    if not isinstance(specs, list):
        return out
    for s in specs:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        for k in ("target", "typ", "value", "min", "max"):
            v = s.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[str(s["name"])] = float(v)
                break
        # THE ENDS OF A DECLARED RANGE ARE ALSO DECLARED FACTS. A spec row
        # that states min and max is stating the whole operating range the
        # block has to work over, and the binding corner is usually an END
        # of it, not the target: an amplifier is hardest at the FASTEST
        # clock the declaration admits. Published as `<name>_min` /
        # `<name>_max` so an entry can size for, or exercise at, the corner
        # it is actually held to — and so a declaration that states no range
        # simply does not offer the key, and an entry that needs one is
        # refused by `requires_bound` rather than quietly falling back to
        # the target.
        for k, suffix in (("min", "_min"), ("max", "_max")):
            v = s.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[str(s["name"]) + suffix] = float(v)
    return out


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
                        unit = str(s.get(key) or "")
                        out[str(s["name"])] = unit
                        # The ENDS of a declared range carry the ROW's unit —
                        # they are the same quantity, stated at its limits.
                        # `bound_spec_values` publishes `<name>_min` /
                        # `<name>_max`, and a key with no unit beside it is
                        # refused by the unit guard, correctly: MEASURED, the
                        # guard stopped `fclk_max` as "bound but declares
                        # unit None" the first time it was offered.
                        for suffix in ("_min", "_max"):
                            if isinstance(s.get(suffix[1:]), (int, float)) \
                                    and not isinstance(s.get(suffix[1:]),
                                                       bool):
                                out[str(s["name"]) + suffix] = unit
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
        # THREE STATES, and the third is not an error dressed as a verdict.
        # A bound whose expression cannot be RESOLVED has not been evaluated,
        # and the honest report of that is neither "satisfied" nor "not
        # satisfied" but "not measured, and here is the name that was
        # missing". `_safe_eval` raises KeyError carrying the unresolved name
        # itself, so the name is reported rather than a repr of the
        # exception: a reader who is told `integrator_input_overdrive_v` can
        # go and bind it, and a reader told "KeyError" cannot.
        unresolved: List[str] = []
        vals: Dict[str, float] = {}
        for key, ex in (("value", spec.get("expr")),
                        ("min", spec.get("min_expr")),
                        ("max", spec.get("max_expr"))):
            if ex is None:
                continue
            try:
                vals[key] = _safe_eval(str(ex), env)
            except KeyError as exc:
                unresolved.append(str(exc.args[0] if exc.args else exc))
            except Exception as exc:                            # noqa: BLE001
                unresolved.append(f"{type(exc).__name__}: {exc}")
        if unresolved:
            refusals.append({
                "requirement": "derived_unresolvable",
                "field": spec.get("name"), "expr": spec.get("expr"),
                "missing": sorted(set(unresolved)),
                "detail": (f"the derived value `{spec.get('name')}` was NOT "
                           f"EVALUATED: this block's environment binds no "
                           f"value for {', '.join(sorted(set(unresolved)))}. "
                           f"That is not the same statement as the bound "
                           f"having been checked and failed")})
            continue
        val = vals["value"]
        # A floor may itself be DERIVED from the declaration — a resolution
        # bound whose requirement is a fixed number is a hidden assumption
        # about the resolution. `min_expr` wins over `min` when both are
        # present, and the resolved number is reported so the refusal names
        # the requirement it was held to rather than only the value.
        lo = vals.get("min", spec.get("min"))
        hi = vals.get("max", spec.get("max"))
        if ((lo is not None and val < float(lo))
                or (hi is not None and val > float(hi))):
            refusals.append({
                "requirement": "derived_range", "field": spec.get("name"),
                "value": val, "min": lo, "max": hi,
                "min_expr": spec.get("min_expr"),
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
        # A behaviour record that says "not verified" and does not say WHAT
        # was measured, what it means and what would close it is a blank
        # refusal: the reader learns the entry is unproven and nothing
        # about how to prove it. `analog_topology_behaviour_check` prints
        # these fields verbatim, so an empty one produces an empty verdict.
        br = entry.get(BEHAVIOUR_RECORD_KEY)
        if isinstance(br, dict) and not br.get("verified"):
            for field in ("claim", "diagnosis", "next"):
                if not str(br.get(field) or "").strip():
                    problems.append(
                        f"{btype}: `{BEHAVIOUR_RECORD_KEY}` is not verified "
                        f"and declares no `{field}`, so the refusal cannot "
                        f"be acted on")
            if not (br.get("arms") or br.get("how")):
                problems.append(
                    f"{btype}: `{BEHAVIOUR_RECORD_KEY}` is not verified and "
                    f"records no measurement — a verdict with no evidence")
        required = entry.get(REQUIRES_BOUND_KEY) or {}
        consts = entry.get("constants") or {}
        # A constant that RESTATES a drawn geometry is a second copy of one
        # number, and the copy is the one an expression reads. Hold them to
        # each other: `<name>_l_um` must be the drawn length of `<name>`.
        by_name = {d.get("name"): d for d in (entry.get("devices") or [])}
        for cname, cval in sorted(consts.items()):
            if not str(cname).endswith("_l_um"):
                continue
            dev = by_name.get(str(cname)[:-len("_l_um")])
            if dev is None:
                problems.append(
                    f"{btype}: constant `{cname}` names no device, so "
                    f"nothing holds it to a drawn length")
            elif float(dev.get("l") or 0.0) != float(cval):
                problems.append(
                    f"{btype}: constant `{cname}` is {cval} and device "
                    f"`{dev['name']}` is drawn l={dev.get('l')} — one "
                    f"number, two places, and the expression reads the copy")
        # The SHARED bias branch cannot see a per-stage coefficient, so the
        # entry states the load as one ratio against the sampling capacitor.
        # It has to cover the WORST stage of every admitted order, or the
        # slew bound is evaluated against a load smaller than the one the
        # amplifier actually drives.
        if entry.get(COEFFICIENT_DERIVATION_KEY) and \
                "load_over_sampling_cap" in consts:
            problems.append(
                f"{btype}: coefficients are DERIVED but "
                f"`load_over_sampling_cap` is stated as a constant. The OTA "
                f"load is (1 + miller) / coefficient, so once the "
                f"coefficient follows `osr` the ratio does too. MEASURED: at "
                f"order 2 / osr 256 the derived coefficient is 0.0055 and "
                f"the ratio is 236, against a stated 2.6.")
        if "load_over_sampling_cap" in consts:
            sets = entry.get(COEFFICIENT_SETS_KEY) or {}
            coeffs = [float(c) for v in sets.values() for c in v]
            if coeffs:
                need = ((1.0 + float(consts.get("miller_fraction_of_load",
                                                0.0)))
                        / min(coeffs))
                if float(consts["load_over_sampling_cap"]) + 1e-9 < need:
                    problems.append(
                        f"{btype}: `load_over_sampling_cap` is "
                        f"{consts['load_over_sampling_cap']} and the "
                        f"smallest admitted coefficient {min(coeffs)} makes "
                        f"the real load {need:.3f} sampling capacitors — "
                        f"the slew bound would be evaluated against a load "
                        f"the amplifier does not drive")
        for st in _stage_groups(entry):
            problems.extend(_group_invariants(btype, entry, st, required))
        continue

    return problems


def _group_invariants(btype: str, entry: Dict[str, Any],
                      st: Dict[str, Any],
                      required: Dict[str, Any]) -> List[str]:
    """Every authoring mistake in ONE stage group. Split out because an entry
    may now declare several and each has to be held to the same rules."""
    problems: List[str] = []
    if st.get(COUNT_BITS_KEY):
        name = st[COUNT_BITS_KEY]
        if name not in required:
            problems.append(
                f"{btype}: stage {COUNT_BITS_KEY}={name!r} is not in "
                f"{REQUIRES_BOUND_KEY}, so a block that does not bind it "
                f"reaches expansion instead of being refused")
        if st.get(COEFFICIENTS_KEY, True):
            problems.append(
                f"{btype}: a `{COUNT_BITS_KEY}` group counts divide-by-two "
                f"stages and has no loop coefficients, so it must declare "
                f"`{COEFFICIENTS_KEY}: False` rather than be handed a set "
                f"that would mean nothing")
    else:
        count_from = st.get("count_from")
        if count_from not in required:
            problems.append(
                f"{btype}: stage count_from={count_from!r} is not in "
                f"{REQUIRES_BOUND_KEY}, so a block that does not bind it "
                f"reaches expansion instead of being refused")
        live = entry.get(LIVENESS_NODES_KEY) or {}
        if live:
            drawn = set()
            for d in (entry.get("devices") or []):
                drawn.update(str(x) for x in (d.get("nets") or []))
            for group in _stage_groups(entry):
                for d in (group.get("devices") or []):
                    drawn.update(str(x).replace("{i}", "1").replace(
                        "{alt}", "") for x in (d.get("nets") or []))
            for role, net in sorted(live.items()):
                if role not in ("reset", "feedback", "decision"):
                    problems.append(
                        f"{btype}: {LIVENESS_NODES_KEY} role {role!r} is not "
                        f"one an arm runner knows (reset/feedback/decision)")
                elif net not in drawn:
                    problems.append(
                        f"{btype}: {LIVENESS_NODES_KEY}[{role}] names net "
                        f"{net!r}, which this entry never draws — a liveness "
                        f"probe pointed at a net that does not exist reports "
                        f"ABSENT and every window reads as dead")
        deriv_name = entry.get(COEFFICIENT_DERIVATION_KEY)
        if st.get(COEFFICIENTS_KEY, True) and not deriv_name \
                and not entry.get(COEFFICIENT_SETS_KEY):
            problems.append(
                f"{btype}: the stage draws coefficients but the entry has "
                f"NEITHER a `{COEFFICIENT_SETS_KEY}` table NOR a "
                f"`{COEFFICIENT_DERIVATION_KEY}`, so expansion would reach a "
                f"set that does not exist")
        if deriv_name and deriv_name not in COEFFICIENT_DERIVATIONS:
            problems.append(
                f"{btype}: {COEFFICIENT_DERIVATION_KEY}={deriv_name!r} names "
                f"no derivation this program carries "
                f"({sorted(COEFFICIENT_DERIVATIONS)})")
        if st.get(COEFFICIENTS_KEY, True) and not deriv_name:
            # An entry that DERIVES has a set for every admitted order by
            # construction; the per-order table check applies to an entry
            # that tabulates.
            sets = entry.get(COEFFICIENT_SETS_KEY) or {}
            admitted = (entry.get(REQUIRES_DOMAIN_KEY) or {}).get(count_from)
            if admitted is None:
                problems.append(
                    f"{btype}: stage count_from={count_from!r} has no "
                    f"{REQUIRES_DOMAIN_KEY} entry, so an order with no "
                    f"coefficient set is not excluded")
            else:
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
                            f"{btype}: {count_from}={n} has a coefficient "
                            f"set of length {len(got)}; one coefficient per "
                            f"stage is required")
    # `last_out` used to be documented as "a declared PORT". It is not: a
    # stage cascade whose last output feeds another shared device on the same
    # block — a quantiser, say — must end on an INTERNAL net, or the block
    # exposes the loop filter's output as a pin. What has to hold either way
    # is that the name RESOLVES: an unlisted one reaches
    # `analog_a3_netlist_emit._validate_ir` as a net that is neither port nor
    # internal, and the netlist ships a dangling node.
    known = set(entry.get("ports") or []) | set(
        entry.get("internal_nets") or [])
    for key in ("last_out", "last_out2"):
        name = st.get(key)
        if name is not None and name not in known:
            problems.append(
                f"{btype}: stage {key}={name!r} is neither a declared port "
                f"nor a declared internal net, so the last stage drives a "
                f"node nothing else on the block resolves")
    if st.get("inner_out2") and not st.get("first_in2"):
        problems.append(
            f"{btype}: the group declares `inner_out2` and no `first_in2`, "
            f"so the second chain's stage 1 has no input")
    return problems




# ── the repeated-stage template ───────────────────────────────────────────
def _bits_to_cover(value: float) -> int:
    """The fewest divide-by-two stages whose period reaches *value*.

    A ripple divider's period is a POWER OF TWO, so a window of `osr` clocks
    is realised by `ceil(log2(osr))` stages and the window it actually gives
    is `2 ** that` — greater than or equal to the declared value, never less.
    Written out as a loop rather than a log so the answer is exact for every
    integer and so the expression grammar (which has no calls) is not asked to
    carry it.
    """
    n, span = 0, 1
    while span < value:
        span *= 2
        n += 1
    return max(n, 1)


def _stage_groups(lib: Dict[str, Any]) -> List[Dict[str, Any]]:
    """An entry's repeated groups, oldest form first.

    `stage` may be a single dict — every entry that had one keeps that exact
    shape and takes the identical path — or a LIST of them. A modulator needs
    two: the integrator cascade, whose count is the declared loop ORDER, and
    the conversion-window counter, whose count is the number of divide-by-two
    stages the declared OSR asks for. One `count_from` cannot express both.
    """
    st = lib.get(STAGE_KEY)
    if isinstance(st, dict):
        return [st]
    if isinstance(st, list):
        return [g for g in st if isinstance(g, dict)]
    return []


def _group_count(st: Dict[str, Any], spec_values: Dict[str, float]) -> int:
    """This group's stage count, and WHICH declared row it came from."""
    if st.get(COUNT_BITS_KEY):
        name = st[COUNT_BITS_KEY]
        if name not in spec_values:
            raise LibraryEntryError(
                f"stage group declares {COUNT_BITS_KEY}={name!r}, which is "
                f"not bound for this block. A group with a "
                f"`{COUNT_BITS_KEY}` must also declare {name!r} in "
                f"`{REQUIRES_BOUND_KEY}` so admission refuses the block "
                f"BEFORE expansion; see `library_invariants`.")
        return _bits_to_cover(float(spec_values[name]))
    count_from = st["count_from"]
    if count_from not in spec_values:
        raise LibraryEntryError(
            f"stage template declares count_from={count_from!r}, which is not "
            f"bound for this block. An entry with a `{STAGE_KEY}` must also "
            f"declare {count_from!r} in `{REQUIRES_BOUND_KEY}` so admission "
            f"refuses the block BEFORE expansion; see `library_invariants`.")
    return int(round(float(spec_values[count_from])))


# ── the feedback selector, DERIVED from the integrator the entry emits ─────
# WHAT WAS WRONG. A cascade entry used to name the feedback reference end per
# stage with a fixed table (`"alternates": ["", "b"]`) whose stated reason was
# "each integrator INVERTS". That is not a convention — it is a CLAIM ABOUT THE
# CIRCUIT THIS FILE EMITS, and once the switched-capacitor branches were given
# their summing-node switches the claim stopped being true: a branch that
# samples on one clock phase and transfers on the other is a DELAYING,
# NON-INVERTING integrator. The table then put the second stage's feedback in
# POSITIVE sign and the loop latched with the bitstream stuck.
#
# So the defect was never the value in the table. It was that a property of the
# emitted topology was written down as a constant, where nothing re-derives it
# when the topology changes. These functions derive it.
#
# MEASURED, and it is why the derivation is worth the code: with the branches
# switched and the table left alone, the modulator does not convert at any
# input (density 1.0000, ZERO bit transitions). With the same branches and the
# selector derived, it converts — monotonic over ten inputs and at 9 of 9 PVT
# corners.
#
# A SECOND, LATENT BUG THE TABLE HID, and the reason this is not just a value
# change: `alternates[(i - 1) % len(alternates)]` gives stage 1 the FIRST entry
# whatever the integrator is. For a first-order loop that is the only stage, so
# an entry whose integrators really did invert would have taken the wrong
# reference end at order 1 and the table could never have said so.
_SC_RAIL_NETS = frozenset({"vdd", "vss", "0"})
#: stands in for `{alt}` while the polarity is being derived, so the FEEDBACK
#: branch is identifiable before the suffix it is waiting for exists. The
#: polarity depends on gate nets only, so nothing here is circular.
_SC_ALT_SENTINEL = "\u0001alt\u0001"


def _sc_groups(devices: Sequence[Dict[str, Any]]
               ) -> Dict[frozenset, Dict[str, str]]:
    """`{frozenset(drain, source): {gate: body}}` for the PASS devices only.

    A pass device has BOTH ends off the rails. Excluding the rest is what keeps
    an amplifier output — whose source IS a rail — from being read as a
    switched node. The gate is kept with its BODY because both halves of a CMOS
    transmission gate carry the same pair of gate nets; the n-channel half's
    gate is the one that names the phase the throw conducts on."""
    out: Dict[frozenset, Dict[str, str]] = {}
    for d in devices:
        nets = [str(n) for n in (d.get("nets") or [])]
        if len(nets) != 4 or nets[0] in _SC_RAIL_NETS or nets[2] in _SC_RAIL_NETS:
            continue
        out.setdefault(frozenset((nets[0], nets[2])), {})[nets[1]] = nets[3]
    return out


def _sc_n_gate(throw: Dict[str, str]) -> Optional[str]:
    """The gate of a throw's n-channel half, by this file's own body rule
    (`NMOS_BODY_TO_VDD` / `PMOS_BODY_TO_VSS` — n bodies to ground)."""
    ns = [g for g, body in throw.items() if body == "vss"]
    return ns[0] if len(ns) == 1 else None


def _sc_throws(node: str, groups: Dict[frozenset, Dict[str, str]]
               ) -> Dict[str, Optional[str]]:
    """`{far node: n-channel gate}` for every non-rail throw of `node`, or {}
    when `node` has fewer than two and is therefore not a switch at all."""
    t: Dict[str, Optional[str]] = {}
    for k, gates in groups.items():
        if node not in k:
            continue
        far = next(iter(k - {node}), None)
        if far is None or far in _SC_RAIL_NETS:
            continue
        t[far] = _sc_n_gate(gates)
    return t if len(t) >= 2 else {}


def sc_branch_polarities(devices: Sequence[Dict[str, Any]]
                         ) -> Dict[str, Dict[str, Any]]:
    """`{branch capacitor: {"polarity": +1 delaying / -1 delay-free,
    "source": the node it samples}}` for one stage.

    The SOURCE is returned with the polarity because the caller has to tell a
    forward branch from a feedback one, and the only thing that distinguishes
    them is which node the bottom plate samples. It is not on the capacitor —
    it is on the switch that drives the capacitor's bottom plate — which is
    why this function reports it rather than leaving the caller to re-derive
    it from device names.

    STRUCTURAL, and it is the whole point of this function: the polarity of a
    switched-capacitor branch is decided by WHEN its two plates move, and by
    nothing else. If the plate that carries the input and the plate that
    reaches the virtual ground close on the SAME phase, the branch delivers
    `-C(V-ref)/ci` into the integrator — delay-free, INVERTING. If they close
    on OPPOSITE phases the branch samples first and transfers after, and
    delivers `+C(V-ref)/ci` — delaying, NON-INVERTING. Charge conservation at
    the summing node gives both; nothing here is a convention.

    A capacitor with either plate welded, or with no throw onto a summing node,
    has NO polarity and is absent from the result rather than defaulted — a
    branch that cannot transfer charge has no sign to get right.
    """
    caps = [d for d in devices if len(d.get("nets") or []) == 2]
    mos = [d for d in devices if len(d.get("nets") or []) == 4]
    gates = {str(d["nets"][1]) for d in mos}
    groups = _sc_groups(devices)

    # the summing node, found the same way the emitted-deck check finds it: a
    # transistor GATE that is also a plate of a capacitor whose other plate is
    # NOT a gate, and is shorted to that other plate by a switch — the
    # per-conversion reset across the integrating capacitor.
    summing = set()
    for c in caps:
        a, b = (str(x) for x in c["nets"])
        for S, O in ((a, b), (b, a)):
            if S in _SC_RAIL_NETS or O in _SC_RAIL_NETS:
                continue
            if S in gates and O not in gates and frozenset((S, O)) in groups:
                summing.add(S)

    pol: Dict[str, Dict[str, Any]] = {}
    for c in caps:
        a, b = (str(x) for x in c["nets"])
        if a in _SC_RAIL_NETS or b in _SC_RAIL_NETS or {a, b} & summing:
            continue
        ta, tb = _sc_throws(a, groups), _sc_throws(b, groups)
        if not ta or not tb:
            continue
        top, bot, tt, bt = ((b, a, tb, ta) if set(tb) & summing
                            else (a, b, ta, tb))
        reach = set(tt) & summing
        if not reach:
            continue
        # the SOURCE is the bottom plate's throw that is not the reference the
        # summing-node plate also returns to.
        ref = set(tt) - summing
        src = [n for n in bt if n not in ref]
        if len(src) != 1 or len(reach) != 1:
            continue
        g_src = bt[src[0]]
        g_sum = tt[next(iter(reach))]
        if g_src is None or g_sum is None:
            continue
        pol[str(c["name"])] = {"polarity": (-1 if g_src == g_sum else +1),
                               "source": src[0], "top_plate": top,
                               "bottom_plate": bot,
                               "summing_node": next(iter(reach))}
    return pol


def derived_feedback_suffixes(st: Dict[str, Any], count: int,
                              selectors: Dict[str, str],
                              probe: Dict[str, Any]
                              ) -> Optional[Tuple[List[str], str]]:
    """`([suffix per stage 1..count], the selector net template)`, or None.

    The template is returned so the caller can name the selector nets without
    re-deriving which node the feedback branch samples; it carries
    `_SC_ALT_SENTINEL` where the suffix goes.

    `selectors` names which suffix feeds back the POSITIVE reference end when
    the decision is asserted (`"pos"`) and which feeds back the negative one
    (`"neg"`). WHICH PORT IS THE POSITIVE REFERENCE IS A DECLARED FACT, not a
    topological one, so it stays declared; the INTEGRATOR'S SIGN is topological
    and is derived. Separating those two is the actual repair.

    The rule: stage `i`'s fed-back charge reaches the quantiser through its own
    branch (`q`) and then through every later stage's forward branch, so its
    sign at the comparator is `q * prod(p_j for j > i)`. Feedback must OPPOSE
    the decision, so the selector must carry the opposite sign to that product.
    """
    probe_devs = []
    for d in st.get("devices") or []:
        nd = dict(d)
        nd["nets"] = [str(n).format(**probe) for n in d.get("nets") or []]
        nd["name"] = str(d["name"]).format(**probe)
        probe_devs.append(nd)
    pol = sc_branch_polarities(probe_devs)
    if not pol:
        return None
    # the FEEDBACK branch is the one that SAMPLES the selector net. That node
    # carries the sentinel because `{alt}` has not been chosen yet; every other
    # switched branch is a forward one.
    fb = [n for n, b in pol.items() if _SC_ALT_SENTINEL in str(b["source"])]
    fwd = [n for n in pol if n not in fb]
    if len(fb) != 1 or len(fwd) != 1:
        return None
    q, p = pol[fb[0]]["polarity"], pol[fwd[0]]["polarity"]
    out: List[str] = []
    for i in range(1, count + 1):
        chain = q * (p ** (count - i))
        out.append(selectors["neg"] if chain > 0 else selectors["pos"])
    return out, str(pol[fb[0]]["source"])


def expand_stages(lib: Dict[str, Any], spec_values: Dict[str, float]
                  ) -> Tuple[List[Dict[str, Any]], List[str],
                             List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Flatten an entry's repeated stage groups into the plain device / net /
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

    Each group carries up to TWO chained signals. The first is explicit rather
    than inferred: stage 1's input is `first_in`, stage i's input is stage
    i-1's output, and the last stage's output is `last_out` — a name the entry
    DECLARES, as a port or as an internal net, or, when `last_out` is omitted,
    simply `inner_out` for the last index. `library_invariants` refuses a
    declared `last_out` that is neither.

    The SECOND chain (`{in2}` / `{out2}`, from `first_in2` / `inner_out2` /
    `last_out2`) exists because a repeated group often has to accumulate
    something alongside the signal it passes along. MEASURED: the conversion-
    window counter's reset is "every counter bit is low", and the bits are
    named per stage, so nothing outside the group can name them all. Running
    an OR down the chain lets the group end on ONE fixed name that the shared
    devices can read. A group that declares no second chain never sees the
    keys.
    """
    groups = _stage_groups(lib)
    devices = [dict(d) for d in (lib.get("devices") or [])]
    nets = list(lib.get("internal_nets") or [])
    exprs = [dict(e) for e in (lib.get("device_param_exprs") or [])]
    if not groups:
        return devices, nets, exprs, None

    records: List[Dict[str, Any]] = []
    for st in groups:
        count = _group_count(st, spec_values)
        coeff_key = st.get("count_from")
        coeffs: List[float]
        if st.get(COEFFICIENTS_KEY, True) and coeff_key:
            deriv = lib.get(COEFFICIENT_DERIVATION_KEY)
            if deriv:
                fn = COEFFICIENT_DERIVATIONS.get(deriv)
                if fn is None:
                    raise LibraryEntryError(
                        f"`{COEFFICIENT_DERIVATION_KEY}` names {deriv!r}, "
                        f"which is not a derivation this program carries")
                coeff_set = fn(count, spec_values, lib.get("constants") or {})
            else:
                coeff_set = (lib.get(COEFFICIENT_SETS_KEY) or {}).get(
                    str(count))
            if coeff_set is None:
                raise LibraryEntryError(
                    f"no `{COEFFICIENT_SETS_KEY}` entry for "
                    f"{coeff_key}={count}. An order the library carries no "
                    f"coefficient set for must be excluded by "
                    f"`{REQUIRES_DOMAIN_KEY}`, not defaulted here — "
                    f"defaulting is how one design's coefficients end up "
                    f"under another design's name.")
            coeffs = [float(c) for c in coeff_set]
        else:
            # A group that carries no coefficients (a counter has none) says
            # so, and is not asked for a set that would mean nothing.
            coeffs = [1.0] * count
        alternates = [str(x) for x in (st.get("alternates") or [""])]
        # DERIVED, not tabulated. See `derived_feedback_suffixes`: which
        # reference end each stage feeds back is a consequence of the
        # integrator this entry emits, and an entry that declares its two
        # selectors gets it computed from the topology. `alternates` remains
        # the fallback for an entry that declares no selectors, so every other
        # entry expands exactly as it did.
        derived_alts = None
        _sel = st.get(FEEDBACK_SELECTORS_KEY)
        if isinstance(_sel, dict) and {"pos", "neg"} <= set(_sel):
            _derived = derived_feedback_suffixes(
                st, count, {k: str(v) for k, v in _sel.items()},
                {"i": 1, "i1": 2, "in": "\u0001in\u0001",
                 "out": "\u0001out\u0001", "coeff": "1.0",
                 "alt": _SC_ALT_SENTINEL,
                 "in2": "\u0001in2\u0001", "out2": "\u0001out2\u0001"})
            derived_alts = None if _derived is None else _derived[0]
            if _derived is not None:
                _sel_template = _derived[1]
                _sel_suffixes = sorted({str(v) for v in _sel.values()})
            if derived_alts is None:
                raise LibraryEntryError(
                    "this entry declares `" + FEEDBACK_SELECTORS_KEY + "` so "
                    "the feedback reference end is DERIVED from the integrator "
                    "it emits — and the derivation did not resolve, which "
                    "means the stage does not emit one forward and one "
                    "feedback switched-capacitor branch with both plates "
                    "switched. Falling back to a tabulated parity here would "
                    "restore the exact defect this replaces: a claim about the "
                    "circuit, written down where nothing re-derives it.")
        for i in range(1, count + 1):
            sub = {
                "i": i,
                "i1": i + 1,
                "in": (st["first_in"] if i == 1
                       else st["inner_out"].format(i=i - 1)),
                "out": (st["last_out"]
                        if (i == count and st.get("last_out"))
                        else st["inner_out"].format(i=i)),
                "coeff": repr(coeffs[i - 1]),
                "alt": (derived_alts[i - 1] if derived_alts is not None
                        else alternates[(i - 1) % len(alternates)]),
            }
            if st.get("inner_out2"):
                sub["in2"] = (st["first_in2"] if i == 1
                              else st["inner_out2"].format(i=i - 1))
                sub["out2"] = (st["last_out2"]
                               if (i == count and st.get("last_out2"))
                               else st["inner_out2"].format(i=i))
            for n in st.get("internal_nets") or []:
                nets.append(n.format(**sub))
            if i < count or not st.get("last_out"):
                nets.append(st["inner_out"].format(i=i))
            if st.get("inner_out2") and (i < count
                                         or not st.get("last_out2")):
                nets.append(st["inner_out2"].format(i=i))
            for d in st.get("devices") or []:
                nd = dict(d)
                nd["name"] = str(d["name"]).format(**sub)
                nd["function"] = str(d.get("function", "")).format(**sub)
                nd["nets"] = [str(n).format(**sub)
                              for n in d.get("nets") or []]
                devices.append(nd)
            for e in st.get("param_exprs") or []:
                ne = dict(e)
                ne["device"] = str(e["device"]).format(**sub)
                ne["expr"] = str(e["expr"]).format(**sub)
                ne["stage"] = i
                ne["coefficient"] = coeffs[i - 1]
                exprs.append(ne)
        chain = ([st["first_in"]]
                 + [st["inner_out"].format(i=i) for i in range(1, count)]
                 + [st["last_out"] if st.get("last_out")
                    else st["inner_out"].format(i=count)])
        rec: Dict[str, Any] = {
            "stages": count,
            "count_from": st.get(COUNT_BITS_KEY) or st.get("count_from"),
            "count_value_source": "spec",
            "coefficients": coeffs,
            "coefficient_set_key": str(count),
            "chain": chain,
            "role": st.get("role", "cascade"),
            "note": ("the device count and the per-stage coefficients BOTH "
                     "follow from the bound `%s`; nothing here is a library "
                     "default" % (st.get(COUNT_BITS_KEY)
                                  or st.get("count_from"))),
        }
        if st.get(COUNT_BITS_KEY):
            rec["window_clocks"] = 2 ** count
            rec["note"] = (
                "the stage count is the fewest divide-by-two stages whose "
                "period reaches the bound `%s`, so the window this counter "
                "gives is %d clocks — greater than or equal to the declared "
                "value, and stated because a ripple divider's period is a "
                "power of two" % (st[COUNT_BITS_KEY], 2 ** count))
        # A SELECTOR NO STAGE SAMPLES IS NOT EMITTED. Which reference ends the
        # cascade actually uses is now a CONSEQUENCE of the integrator (see
        # `derived_feedback_suffixes`), so which selector legs are live is a
        # consequence too, and hard-coding either would put the same class of
        # claim back. A first-order loop uses ONE end; a second-order delaying
        # cascade uses one; a second-order delay-free cascade uses both. So the
        # unsampled legs are pruned HERE, from what the expansion actually
        # referenced — never from a table of which entry has how many.
        #
        # Without this the deck carries a driven-but-unloaded node. MEASURED:
        # A3 emits it, all four netlist checkers PASS it and the A3 gate PASSES
        # it, so nothing downstream would have said so.
        if derived_alts is not None and _sel_template:
            # LOADED, not merely mentioned. A selector's own legs name the net
            # at their DRAIN; a stage that samples it names it at a pass
            # device's SOURCE. Testing for any mention at all would find the
            # net alive in its own drivers and prune nothing — which is the
            # bug this comment exists because I wrote.
            loaded = {str(n) for d in devices
                      for n in (d.get("nets") or [])[1:]}
            for suf in _sel_suffixes:
                net = _sel_template.replace(_SC_ALT_SENTINEL, suf)
                if net in loaded:
                    continue
                devices[:] = [d for d in devices
                              if net not in (d.get("nets") or [])]
                nets[:] = [n for n in nets if n != net]
                rec.setdefault("pruned_selectors", []).append(net)
        records.append(rec)

    # The FIRST group's record stays under the old key and the old shape, so
    # every reader of `stage_expansion` keeps working; the full list is
    # published beside it.
    primary = dict(records[0])
    if len(records) > 1:
        primary["groups"] = records
    return devices, nets, exprs, primary


# ── artefacts ─────────────────────────────────────────────────────────────
# ── unit capacitors: a device the PDK cannot draw becomes N that it can ──
#
# THE DEFECT THIS CLOSES, MEASURED (u_hawaii_adc / ihp-sg13g2 / image 0.3.46).
# This library sized `delta_sigma`'s capacitors from the noise budget and got
# lengths of 34.75 to 629.08 um. The PDK's own gencell states `lmax 30.0`, and
# a magic gencell asked for more does not refuse the way one below `lmin`
# does: it CLAMPS to the maximum and draws. So twelve netlist capacitors came
# back as TWO drawn cells, the largest device 21x smaller than the netlist
# asks for; DRC was clean, the A5 gate passed, and the only artefact that
# noticed was the sign-off LVS six steps later, whose cross-reference named
# exactly those eight devices as differing in `l` alone.
#
# A capacitor above the gencell's maximum is not a broken design. It is the
# ordinary analog answer — N unit devices in parallel — and the place to say
# so is HERE, where the netlist is still being decided, so that the netlist
# and the layout agree device for device instead of disagreeing at LVS.
#
# The unit length is solved against the PDK's OWN measured capacitance
# constants, area AND perimeter, because N units do not have the same
# perimeter as one: splitting 10 x 629.08 into 21 x 29.96 adds 400 um of edge.
# Solving on area alone (`l/N`, which is what this library's own sizing
# expression uses) would move the realised value by the whole fringe term.
#
#   C(w, l)      = carea * w * l + 2 * cperi * (w + l)
#   N * C(w, lu) = C(w, l)
#   =>  lu = (C(w, l)/N - 2*cperi*w) / (carea*w + 2*cperi)
#
# `lu` falls as N rises, so the smallest legal N is the first one whose `lu`
# is at or under the maximum; a `lu` under the PDK's own MINIMUM means no unit
# set exists and the block is refused BY NAME rather than drawn wrong.

#: The relative error this split is allowed to leave in a capacitor's value.
#: The solve above is exact in real arithmetic; what this bounds is the
#: rounding of the emitted length and any family whose constants make the
#: closed form degenerate. 0.1% is two orders of magnitude above what the
#: measured split actually leaves (below 1e-9 on every capacitor of
#: u_hawaii_adc's two blocks) and two orders BELOW the ~5% a MiM capacitor's
#: own process tolerance carries, so it is a real bound and not a ceremonial
#: one. Held in `tests/test_analog_a2_unit_capacitor_split.py`.
CAP_SPLIT_TOLERANCE = 1e-3


def capacitance_ff(w_um: float, l_um: float, carea: float, cperi: float
                   ) -> float:
    """The PDK's own two-term capacitance model, in fF for microns.

    Both constants come from `pdk_registry.json`'s measured record
    (`cap_area_ff_per_um2`, `cap_perim_ff_per_um`), which
    `pdk_analog_characterize` derives by simulating the PDK's own model at two
    sizes. A family that carries neither is not split — see `split_records`.
    """
    return carea * w_um * l_um + 2.0 * cperi * (w_um + l_um)


def unit_capacitor_split(w_um: float, l_um: float, *,
                         max_l: Optional[float], max_w: Optional[float],
                         min_l: Optional[float], carea: float, cperi: float,
                         tolerance: float = CAP_SPLIT_TOLERANCE,
                         limit: int = 4096
                         ) -> Tuple[Optional[int], Optional[float], str]:
    """`(n, unit_length_um, why)` for one capacitor.

    `(None, None, <reason>)` when no legal unit set reaches the value within
    `tolerance` — the caller REFUSES BY NAME on that; it never draws the
    nearest thing it can. `(1, l_um, "")` when the device is already legal, so
    a design that needs no split takes a path that changes nothing.
    """
    if max_w is not None and w_um > max_w + 1e-12:
        return None, None, (
            f"drawn width {w_um}u is above the PDK maximum {max_w}u and this "
            f"split divides LENGTH only; a width above the maximum is a "
            f"device this library cannot realise")
    if max_l is None or l_um <= max_l + 1e-12:
        return 1, l_um, ""
    target = capacitance_ff(w_um, l_um, carea, cperi)
    denom = carea * w_um + 2.0 * cperi
    if denom <= 0 or target <= 0:
        return None, None, (
            f"the family's measured capacitance constants (area {carea}, "
            f"perimeter {cperi}) do not define a length for this width")
    n = max(2, int(math.ceil(l_um / max_l)))
    while n <= limit:
        lu = (target / n - 2.0 * cperi * w_um) / denom
        if lu > max_l + 1e-12:
            n += 1
            continue
        if min_l is not None and lu < min_l - 1e-12:
            return None, None, (
                f"the smallest unit that stays under the PDK maximum "
                f"{max_l}u is {lu:.6g}u, below the PDK minimum {min_l}u: no "
                f"array of legal units realises {target:.6g}fF at width "
                f"{w_um}u")
        got = n * capacitance_ff(w_um, lu, carea, cperi)
        if abs(got - target) <= tolerance * target:
            return n, lu, ""
        return None, None, (
            f"{n} units of {lu:.6g}u realise {got:.6g}fF against a target of "
            f"{target:.6g}fF, outside the {tolerance:.3g} relative tolerance "
            f"this split holds")
    return None, None, (
        f"no array of at most {limit} units of at most {max_l}u realises "
        f"{target:.6g}fF at width {w_um}u")


def split_oversize_capacitors(devices: List[Dict[str, Any]],
                             param_exprs: List[Dict[str, Any]],
                             env: Dict[str, Any],
                             role_maxima: Dict[str, Any],
                             role_minima: Dict[str, Any],
                             measured: Dict[str, float],
                             ) -> Tuple[List[Dict[str, Any]],
                                        List[Dict[str, Any]],
                                        List[Dict[str, Any]],
                                        List[str]]:
    """Replace every capacitor the PDK cannot draw with N that it can.

    Returns `(devices, param_exprs, records, refusals)`. `records` is one
    entry per device that was split, with N, the unit length, the constants it
    was solved against and the relative value error left — the artefact then
    STATES the array instead of a reader having to notice N identical devices.
    `refusals` are devices no legal unit set realises; the caller refuses the
    block by name on those and emits nothing.

    A family whose registry record carries no capacitor maximum, or no
    measured capacitance constants, is NOT SPLIT and is not silently passed
    either: `records` is empty and the caller's provenance says the maxima
    were unavailable, the same way it already says whether the minima were.
    """
    lmax = _minima.max_length_um(role_maxima, CAP_ROLE)
    wmax = _minima.max_width_um(role_maxima, CAP_ROLE)
    lmin = _minima.min_width_um(role_minima, CAP_ROLE)
    carea = measured.get("cap_area_ff_per_um2")
    cperi = measured.get("cap_perim_ff_per_um")
    if lmax is None or not isinstance(carea, (int, float)) or carea <= 0:
        return devices, param_exprs, [], []
    cperi = float(cperi) if isinstance(cperi, (int, float)) else 0.0

    by_dev: Dict[str, Dict[str, Any]] = {}
    for e in param_exprs:
        if e.get("param") == "l":
            by_dev[str(e.get("device"))] = e

    out_devs: List[Dict[str, Any]] = []
    out_exprs = [e for e in param_exprs]
    records: List[Dict[str, Any]] = []
    refusals: List[str] = []
    for d in devices:
        expr = by_dev.get(str(d.get("name")))
        w = d.get("w")
        if d.get("role") != CAP_ROLE or expr is None \
                or not isinstance(w, (int, float)):
            out_devs.append(d)
            continue
        try:
            l_um = float(_safe_eval(str(expr["expr"]), dict(env)))
        except Exception:
            # NOT MEASURED, never a default: an expression this pass cannot
            # resolve is one it has nothing to say about, and it is left
            # exactly as it was for the pass that can.
            out_devs.append(d)
            continue
        n, lu, why = unit_capacitor_split(
            float(w), l_um, max_l=lmax, max_w=wmax, min_l=lmin,
            carea=float(carea), cperi=cperi)
        if n is None:
            refusals.append(f"{d.get('name')}: {why}")
            out_devs.append(d)
            continue
        if n == 1:
            out_devs.append(d)
            continue
        # THE UNIT LENGTH STAYS DERIVED FROM THE SPEC. The original length
        # expression is kept whole inside the closed form, so a reader can
        # still follow the capacitor back to the noise budget that sized it;
        # only the PDK constants are substituted numerically, because they are
        # what this pass has already measured the split against and a NAME
        # that a family does not carry would resolve to nothing downstream.
        base = str(expr["expr"])
        wt = repr(float(w))
        at, bt = repr(float(carea)), repr(cperi)
        lu_expr = (f"(({at} * {wt} * ({base}) + 2 * {bt} * ({wt} + ({base}))) "
                   f"/ {n} - 2 * {bt} * {wt}) / ({at} * {wt} + 2 * {bt})")
        out_exprs = [e for e in out_exprs if e is not expr]
        for i in range(n):
            unit = dict(d)
            unit["name"] = f"{d['name']}_u{i}"
            out_devs.append(unit)
            e = dict(expr)
            e["device"] = unit["name"]
            e["expr"] = lu_expr
            e["rationale"] = (
                f"unit {i + 1} of {n} in parallel — the drawn length this "
                f"block's sizing asks for is above the PDK's stated maximum "
                f"for this device, so the capacitor is realised as {n} legal "
                f"units and the unit length is solved from the PDK's own "
                f"area and perimeter capacitance so the total is preserved"
                + (f"; {expr.get('rationale')}" if expr.get("rationale")
                   else ""))
            out_exprs.append(e)
        target = capacitance_ff(float(w), l_um, float(carea), cperi)
        got = n * capacitance_ff(float(w), lu, float(carea), cperi)
        records.append({
            "device": d.get("name"), "role": CAP_ROLE,
            "units": n, "unit_w_um": float(w), "unit_l_um": lu,
            "library_l_um": l_um,
            "pdk_max_l_um": lmax, "pdk_max_w_um": wmax,
            "target_ff": target, "realised_ff": got,
            "relative_value_error": (abs(got - target) / target
                                     if target else None),
            "tolerance": CAP_SPLIT_TOLERANCE,
            "cap_area_ff_per_um2": float(carea),
            "cap_perim_ff_per_um": cperi,
        })
    return out_devs, out_exprs, records, refusals


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


def declared_interface_pins(project: Path, block: str) -> List[str]:
    """The block's DESIGN-DECLARED pin names, from the A1 artefact
    (`spec.json:interface.pins[].name`). [] when the design declares none —
    the topology library's own names then stand, exactly as before."""
    for base in (_CANONICAL_ANALOG, _DECLARED_ANALOG):
        p = project / base / block / "spec.json"
        if not p.is_file():
            continue
        data = _read_json(p)
        if not isinstance(data, dict):
            continue
        iface = data.get("interface")
        pins = (iface or {}).get("pins") if isinstance(iface, dict) else None
        if isinstance(pins, list):
            out = [str(x.get("name")) for x in pins
                   if isinstance(x, dict) and x.get("name")]
            if out:
                return out
    return []


def bind_ports_to_declaration(lib_ports: Sequence[str],
                              declared: Sequence[str]
                              ) -> Tuple[Dict[str, str], Optional[str]]:
    """``({library_name: declared_name}, refusal)`` — the topology library's
    port names bound to the names the DESIGN declares for this block.

    WHY. The topology library names a block's ports after the CIRCUIT it
    draws; the design declares them after the ROLE they play at chip level,
    and the two are not always the same word. MEASURED (u_hawaii_adc,
    ihp-sg13g2): the `ldo` entry names its supply input `vdd`, the design's
    own interface declaration (staged, every pin citing its document line)
    names it `vin`, and the chip RTL instantiates `.vin(...)`. Nothing
    reconciled them, so the emitted hardmacro's LEF, GDS labels and Verilog
    view all said `vdd`, and the post-layout LEC — the last gate before the
    sign-off tail — stopped on `Module 'ldo' ... does not have a port named
    'vin'`, on a die whose DRC was 0 and whose LVS matched.

    The rule is deliberately narrow, because a rename that guesses is worse
    than no rename: bind every name that matches EXACTLY, and then, only if
    exactly ONE name is left unbound on each side, bind that pair (there is
    no other candidate it could be) and record it. Any other leftover shape —
    two-and-two, three-and-four, a declaration for a block the library gives
    fewer ports than — is REFUSED by name and nothing is renamed; the
    interface gate then reports the disagreement instead of a silent guess.
    Case-insensitive on the exact pass: LEF/Verilog/SPICE all round-trip case
    differently and `VDD` vs `vdd` is not a disagreement about ROLE.
    """
    lib_ports = [str(p) for p in (lib_ports or [])]
    declared = [str(p) for p in (declared or [])]
    if not declared or not lib_ports:
        return {}, None
    dmap = {d.lower(): d for d in declared}
    mapping: Dict[str, str] = {}
    lib_left: List[str] = []
    for lp in lib_ports:
        d = dmap.get(lp.lower())
        if d is not None:
            mapping[lp] = d
        else:
            lib_left.append(lp)
    bound = {v.lower() for v in mapping.values()}
    dec_left = [d for d in declared if d.lower() not in bound]
    if not lib_left and not dec_left:
        return mapping, None
    if len(lib_left) == 1 and len(dec_left) == 1:
        mapping[lib_left[0]] = dec_left[0]
        return mapping, None
    return {}, (
        f"PORT_BINDING_AMBIGUOUS: the topology names {sorted(lib_left)} that "
        f"the design's interface declaration does not, and the declaration "
        f"names {sorted(dec_left)} that the topology does not. A rename is "
        f"only unambiguous when exactly one is left on each side; nothing "
        f"was renamed.")


def _rename_nets(obj: Any, mapping: Dict[str, str]) -> Any:
    """Apply a net rename map to an IR fragment. A net name is a WHOLE TOKEN,
    never a substring: `vdda` must not become `vina`, and the SPICE source
    NAME in `v_vdd vdd 0 {supply}` must not change while the NODE it drives
    does (measured: renaming only whole-string entries left the testbench
    driving a node the DUT no longer has, and the A4 corner sweep failed on a
    floating input)."""
    if isinstance(obj, str):
        if obj in mapping:
            return mapping[obj]
        out = obj
        for old_n, new_n in mapping.items():
            out = re.sub(r"(?<![0-9A-Za-z_])" + re.escape(old_n)
                         + r"(?![0-9A-Za-z_])", new_n, out)
        return out
    if isinstance(obj, list):
        return [_rename_nets(x, mapping) for x in obj]
    if isinstance(obj, dict):
        return {k: _rename_nets(v, mapping) for k, v in obj.items()}
    return obj


def build_ir(block: str, btype: str, entry: Dict[str, Any],
             lib: Dict[str, Any], spec_values: Dict[str, float],
             spec_path: Optional[str], project: Path,
             pdk_family: Optional[str],
             pdk_params: Dict[str, Any],
             role_minima: Optional[Dict[str, Any]] = None,
             minima_source: Optional[str] = None,
             measured_params: Optional[Dict[str, float]] = None,
             measured_provenance: Optional[Dict[str, Any]] = None,
             role_maxima: Optional[Dict[str, Any]] = None,
             maxima_source: Optional[str] = None,
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
    # A counter group's WINDOW — the number of clock periods its ripple chain
    # takes to come back to zero — is computed during expansion and is not
    # otherwise nameable: the expression grammar has no logarithm, so nothing
    # downstream could derive it. Published as a constant so the entry's own
    # testbench can say "measure the bitstream over one conversion window"
    # instead of a number typed beside it.
    for _grec in ([stage_rec] + list((stage_rec or {}).get("groups") or [])
                  if stage_rec else []):
        if isinstance(_grec, dict) and _grec.get("window_clocks"):
            constants["window_clocks"] = float(_grec["window_clocks"])
    clamps = floor_geometry_to_pdk(lib, constants, devices, role_minima)

    # A DEVICE THE PDK CANNOT DRAW BECOMES N THAT IT CAN — see
    # `split_oversize_capacitors`. Run AFTER the widths are floored, because
    # the split solves the unit length AT the drawn width and a width the
    # floor was about to raise would be solved against the wrong one. The
    # environment is the one `analog_a3_netlist_emit` resolves these same
    # expressions in, seeded in the same order, so the length this pass reads
    # is the length that pass will render.
    role_maxima = dict(role_maxima or {})
    split_env: Dict[str, Any] = {}
    split_env.update({k: v for k, v in (measured_params or {}).items()
                      if isinstance(v, (int, float))
                      and not isinstance(v, bool)})
    split_env.update(constants)
    split_env.update({k: v for k, v in knobs.items()
                      if isinstance(v, (int, float))})
    split_env.update(spec_values)
    devices, param_exprs, splits, split_refusals = split_oversize_capacitors(
        devices, param_exprs, split_env, role_maxima, role_minima,
        dict(measured_params or {}))

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
        # Optional, and None for every entry that declares none. When an
        # entry states what its circuit must be SHOWN to do, the statement
        # and its verdict travel with the IR so that A5/A8 and the gate that
        # reads it (`analog_topology_behaviour_check`) see the same words the
        # library author wrote — never a summary of them.
        "behaviour_record": (dict(lib["behaviour_record"])
                             if isinstance(lib.get("behaviour_record"), dict)
                             else None),
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
        "producer_fingerprint": producer_fingerprint(),
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
            # The OTHER end of the same statement. A gencell below its
            # minimum refuses; one ABOVE its maximum clamps and draws, so a
            # reader must be able to tell "checked, nothing was above the
            # ceiling" from "this family declares no ceiling, so nothing was
            # checked" — the same distinction `minima_available` makes.
            "layout_maxima": {
                "path": "programs/pdk_registry.json",
                "field": "analog_device_layout_maxima",
                "reader": "programs/pdk_analog_layout_minima.py",
                "family": pdk_family,
                "maxima_available": bool(role_maxima),
                "measured_from": maxima_source,
                "roles": role_maxima or None,
                "capacitor_arrays": splits,
                "refusals": split_refusals,
                "note": (
                    "a capacitor whose drawn length is above the PDK's own "
                    "stated maximum is realised as N unit devices in "
                    "parallel, N and the unit length solved from the PDK's "
                    "measured area AND perimeter capacitance so the total "
                    "value is preserved; a device no legal unit set realises "
                    "is refused by name, never drawn at the maximum"
                    if role_maxima else
                    "this family declares no measured device maximum in the "
                    "registry, so NOTHING was checked against one and no "
                    "capacitor was split"),
            },
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
    # THE DESIGN'S OWN PORT NAMES, when it declares them. The library names
    # ports after the circuit; the design declares them after the role they
    # play at chip level. Binding here — before the IR reaches A3, A5, A6 and
    # A8 — is what makes the emitted netlist, the layout labels, the LEF, the
    # GDS text and the Verilog view all say the SAME word as the RTL that
    # instantiates the block. See `bind_ports_to_declaration` for the rule and
    # for the measured failure that motivated it.
    _declared = declared_interface_pins(project, block)
    _pmap, _prefusal = bind_ports_to_declaration(ir["ports"], _declared)
    _renames = {k: v for k, v in _pmap.items() if k != v}
    if _renames:
        for _key in ("ports", "rails", "internal_nets", "devices",
                     "constants", "device_param_exprs", "measurements",
                     "testbench", "stimulus"):
            if _key in ir:
                ir[_key] = _rename_nets(ir[_key], _renames)
    ir["port_binding"] = {
        "declared_pins": list(_declared),
        "library_ports": list(lib["ports"]),
        "renamed": _renames,
        "refusal": _prefusal,
        "source": ("design-declared interface (spec.json:interface.pins[])"
                   if _declared else
                   "topology library (the design declares no interface)"),
    }
    return ir


def _render_behaviour_section(ir: Dict[str, Any]) -> List[str]:
    """What the entry claims its circuit does, and whether that was shown.

    Empty for an entry that declares no `behaviour_record`, so every
    pre-existing topology.md is byte-identical. Present, it is placed ABOVE
    the process-constant sections on purpose: a reader who stops after the
    first screen must have seen the verdict, not the device table.
    """
    br = ir.get("behaviour_record")
    if not isinstance(br, dict):
        return []
    ok = bool(br.get("verified"))
    L: List[str] = ["## What this topology has been SHOWN to do", ""]
    L.append(f"**Claim.** {br.get('claim')}")
    L.append("")
    caveat = "" if ok else (
        " — this topology renders, converges in the simulator and drives "
        "its declared output rail to rail, and the claim above is still "
        "NOT shown. Those are different statements, and this section "
        "exists so they cannot be read as one.")
    L.append("**Verdict: "
             + ("DEMONSTRATED" if ok else "NOT DEMONSTRATED")
             + "**" + caveat)
    L.append("")
    if br.get("measured_on"):
        L.append(f"Measured on: {br['measured_on']}")
        L.append("")
    if br.get("how"):
        L.append(f"**How.** {br['how']}")
        L.append("")
    if br.get("arms"):
        L.append("**Arms, one variable at a time:**")
        L.append("")
        for a in br["arms"]:
            L.append(f"  * {a}")
        L.append("")
    if br.get("diagnosis"):
        L.append(f"**Diagnosis.** {br['diagnosis']}")
        L.append("")
    if br.get("next"):
        L.append(f"**What would close it.** {br['next']}")
        L.append("")
    return L


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
    L.extend(_render_behaviour_section(ir))
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
    _maxima_fam, role_maxima = _minima.layout_maxima(pdk)
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
                  measured, measured_prov,
                  role_maxima, _minima.maxima_source(pdk))
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
