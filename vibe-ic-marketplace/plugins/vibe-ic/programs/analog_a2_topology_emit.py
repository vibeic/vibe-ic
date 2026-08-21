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

PRODUCER = "analog_a2_topology_emit"
PROVENANCE_SCHEMA = 1
SKILL = "analog-topology-select"
IR_SCHEMA = 1

_CANONICAL_ANALOG = "phase3/analog"
_DECLARED_ANALOG = "phase1/analog"
_REGISTRY = Path(__file__).resolve().parent / "pdk_registry.json"

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
        "constants": {"l_unit": 20.0, "w_res": 0.35},
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
            {"device": "r1", "param": "l",
             "expr": "l_unit * (divider_ratio - 1)",
             "rationale": "r1/r2 = divider_ratio - 1 at equal sheet width"},
            {"device": "r2", "param": "l", "expr": "l_unit",
             "rationale": "divider lower leg is the unit element"},
        ],
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
    "delta_sigma": (
        "the switched-capacitor integrator's capacitor ratio IS the loop "
        "coefficient, so the structure is not separable from the sizing"),
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


def pdk_device_params(selector: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """`analog_device_params` for the registry family matching `selector`.
    READ, never retyped — `analog-topology-select` forbids restating these."""
    data = _read_json(_REGISTRY)
    if not isinstance(data, dict):
        return None, {}
    sel = str(selector or "").strip().lower()
    for ent in data.get("pdks") or []:
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("name") or "")
        if not name:
            continue
        if name.lower() == sel or name.lower().startswith(sel) \
                or sel.startswith(name.lower()):
            params = ent.get("analog_device_params")
            return name, (params if isinstance(params, dict) else {})
    return None, {}


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


# ── artefacts ─────────────────────────────────────────────────────────────
def build_ir(block: str, btype: str, entry: Dict[str, Any],
             lib: Dict[str, Any], spec_values: Dict[str, float],
             spec_path: Optional[str], project: Path,
             pdk_family: Optional[str],
             pdk_params: Dict[str, Any]) -> Dict[str, Any]:
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

    ir: Dict[str, Any] = {
        "ir_schema": IR_SCHEMA,
        "block": block,
        "block_type": btype,
        "topology": lib["topology"],
        "circuit_class_citation": lib["circuit_class_citation"],
        "ports": list(lib["ports"]),
        "rails": dict(lib["rails"]),
        "internal_nets": list(lib["internal_nets"]),
        "role_terminals": {r: ROLE_TERMINALS[r] for r in
                           sorted({d["role"] for d in lib["devices"]})},
        "constants": dict(lib.get("constants") or {}),
        "devices": [dict(d) for d in lib["devices"]],
        "spec_knobs": [dict(k) for k in lib.get("spec_knobs", [])],
        "knobs": knobs,
        "knob_sources": knob_sources,
        "device_param_exprs": [dict(e) for e in
                               lib.get("device_param_exprs", [])],
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
            },
            "fields_bound": sorted([n for n, s in knob_sources.items()
                                    if s == "spec"]),
            "fields_defaulted": sorted(defaulted),
            "defaults_used": bool(defaulted),
            "sizing_handoff": lib.get("sizing_handoff"),
            "ai_handoff": (
                {"track": "skill", "skill": "analog-sizing",
                 "reason": lib["sizing_handoff"]}
                if lib.get("sizing_handoff") else None),
            "limits": (
                "the topology is a circuit-CLASS selection. Device geometry "
                "is the library nominal unless a device_param_expr bound it "
                "to a spec value; see fields_bound / fields_defaulted."),
        },
    }
    return ir


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


def _gap_body(block: str, btype: str, entry: Dict[str, Any]) -> Dict[str, Any]:
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
        "status": "NO_TOPOLOGY_IN_LIBRARY",
        "topology_md_written": False,
        "topology_json_written": False,
        "library_types": sorted(LIBRARY.keys()),
        "reason": (
            reason or
            f"circuit class `{btype}` has no entry in the deterministic "
            f"topology library, and this producer does not synthesise one"),
        "why_not_defaulted": (
            "emitting the nearest library topology under this block's name "
            "would produce a document that reads as a selection and is a "
            "substitution; the A2 gate cannot tell them apart because it "
            "measures vocabulary, not structure"),
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

    lib = LIBRARY.get(btype)
    if lib is None:
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "topology_gap.json").write_text(
            json.dumps(_gap_body(name, btype, entry), indent=2,
                       ensure_ascii=False) + "\n", encoding="utf-8")
        for stale in (md_path, ir_path):
            if stale.is_file() and PRODUCER in stale.read_text(
                    encoding="utf-8", errors="replace"):
                stale.unlink()
        rec.update(action="gap", emitted=False,
                   status="NO_TOPOLOGY_IN_LIBRARY",
                   gap_path=str((bdir / "topology_gap.json")
                                .relative_to(project)))
        return rec

    spec_values, spec_path = bound_spec_values(project, name)
    fam, params = pdk_device_params(pdk)
    ir = build_ir(name, btype, entry, lib, spec_values, spec_path, project,
                  fam, params)
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
               fields_defaulted=ir["_provenance"]["fields_defaulted"])
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
    ap.add_argument("--pdk", default="sky130",
                    help="PDK selector whose analog_device_params are quoted "
                         "in topology.md (read from pdk_registry.json)")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    project = args.project.resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 1
    rc, report = run(project, args.block, args.pdk)
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
