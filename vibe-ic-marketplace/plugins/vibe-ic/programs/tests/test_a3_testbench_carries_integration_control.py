"""An A3 testbench carried NO `.options` card, so every deck this producer
verified was integrated on the simulator's own default step control.

MEASURED (lane czdsm, 2026-09-07, 8HD-6, vibeic-eda 0.3.47
sha256:8da785a8…, ngspice-47). The `delta_sigma` block of a real project
rendered a netlist that passed ALL FIVE static checkers — `a3_gate`, `pdk`,
`connectivity`, `include_order`, `path_lint` — and then died inside the
transient:

    doAnalyses: TRAN: Timestep too small; time = 2.61293e-05,
    timestep = 4.87367e-21: trouble with node "xdut.nbias"

A3 read that as a property of the netlist, deleted the `.sp`, wrote
`netlist_gap.json` with `NETLIST_NOT_SIMULATABLE`, and A4..A7 then reported
BLOCKED on "no *.sp". Four flow steps were closed by an integration setting.

THE NODE IN THE MESSAGE IS THE MESSENGER, NOT THE FAULT — and this test
exists because that took measuring:

  * isolated and in circuit, `nbias` carries 41.13 uA from a 17.32 kohm bias
    resistor into the diode-connected mirror reference and sits at
    0.487795 V, about 830 ohm of small-signal impedance;
  * across the 33 clock cycles before the abort it moves 2.6 mV;
  * held at that potential by an ideal source, the SAME abort reappears on a
    different node (`xdut.ntail_cm`).

So no netlist change reaches it, and the four idioms that could HIDE a
floating node all fail as well: `rshunt=1e12` -> 143.1 us, `gmin=1e-9` ->
87.3 us, `method=gear` -> 38.2 us, `itl4=100` -> byte-identical to the
default. Loosening the accuracy tolerances (`reltol=1e-2 abstol=1e-10
vntol=1e-5`) fails SOONER, at 14.05 us.

WHAT IS BEING ASSERTED, AND WHY IT IS NOT A RELABEL. `trtol` scales the local
truncation error bound the next timestep is chosen from, so a SMALLER value
asks for a SMALLER step and holds a TIGHTER error — the opposite direction
from every knob above. Under the default the abort time is not a property of
the circuit at all (maximum step halved -> 203.54 us, quartered -> 145.44 us,
non-monotonic); under `trtol=1` the run COMPLETES at both steps and answers
the same, density 0.434376 against 0.436314 and swing 1.06594 against
1.06597, with every quiescent node agreeing with the default-trtol run to
five decimals over the window that run reached.

BOTH DIRECTIONS. The emitted card is held STRICTLY BELOW the simulator's
shipped default rather than to the literal value that was measured: a card at
or above the default asks for a step at least as large as the default and
verifies nothing, so a value that has been quietly raised back is a red here,
and tightening it further stays legal.

POPULATION, NOT A SPECIMEN. The check runs over EVERY circuit class in the A2
topology library that declares a testbench, so a class added later without
the card is a red, and a card emitted for the measured class alone would not
pass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import analog_a2_topology_emit as A2LIB          # noqa: E402
import analog_a3_netlist_emit as A3MOD           # noqa: E402
from _analog_producer_fixture import (           # noqa: E402
    A1, A2, A3, block, make_project, run_prog)

#: ngspice / SPICE3 ship this. Stated HERE, not imported from the producer, so
#: that editing the producer's own copy of the default cannot move the bound
#: this file holds it to.
NGSPICE_DEFAULT_TRTOL = 7.0

#: The UNION of the sizing rows the topology library's classes bind, so one
#: synthetic block per class is admissible and the population below is the
#: whole library rather than the class that happened to be measured. Rows a
#: class does not name are dropped by `normalize_spec_label`, so this list
#: does not have to be split per class. `fclk` carries its range because a
#: switched-capacitor class is held to the fastest clock its declaration
#: admits and refuses a declaration that states none.
SPECS = [
    {"name": "Vout", "target": 1.8, "unit": "V"},
    {"name": "Vin", "target": 3.0, "unit": "V"},
    {"name": "Vref", "target": 0.9, "unit": "V"},
    {"name": "Reff", "target": 50000.0, "unit": "ohm"},
    {"name": "ENOB", "target": 14.0, "unit": "bit"},
    {"name": "fclk", "target": 1.0, "min": 0.1, "max": 1.2, "unit": "MHz"},
    {"name": "OSR", "target": 256.0, "unit": "-"},
    {"name": "Order", "target": 2.0, "unit": "-"},
    {"name": "Vdd (core)", "target": 1.2, "unit": "V"},
    {"name": "Vin (diff)", "target": 1.0, "unit": "V"},
]

#: An OPEN PDK, named because the switched-capacitor class sizes a device from
#: a MEASURED process constant and refuses a family that carries no record of
#: it — so a family without one would silently shrink this file's population
#: to the four classes that do not need it. The membership guard below is what
#: makes that shrink a red instead of a quieter pass.
PDK = "ihp-sg13g2"


def _classes_with_a_testbench():
    return sorted(k for k, v in A2LIB.LIBRARY.items()
                  if isinstance(v.get("testbench"), dict))


def _emit(tmp_path):
    """Drive A1 -> A2 -> A3 for one synthetic block of every class that
    declares a testbench. No container: `--verify-sim` is NOT passed, so every
    assertion here is about what was WRITTEN and none of them can turn on
    whether a simulator was reachable."""
    classes = _classes_with_a_testbench()
    assert classes, "the topology library declares no testbench at all"
    blocks = [block(f"blk_{i}", btype, specs=SPECS)
              for i, btype in enumerate(classes)]
    project = make_project(tmp_path, blocks)
    run_prog(A1, project)
    run_prog(A2, project, "--pdk", PDK)
    run_prog(A3, project, "--pdk", PDK)
    decks, why = {}, {}
    for i, btype in enumerate(classes):
        d = project / "phase3/analog" / f"blk_{i}"
        tb = d / f"tb_blk_{i}.sp"
        if tb.exists():
            decks[btype] = tb.read_text(encoding="utf-8")
            continue
        for gap in ("topology_gap.json", "netlist_gap.json"):
            g = d / gap
            if g.exists():
                why[btype] = json.loads(g.read_text(
                    encoding="utf-8")).get("status")
                break
        else:
            why[btype] = "NOTHING WRITTEN"
    return classes, decks, why


def _options_cards(text):
    """Every `.options` card at TOP LEVEL. A `.options` inside a `.control`
    block is an ngspice interactive command, not a circuit option, and the
    analysis that follows would still run on the simulator default."""
    out, in_control = [], False
    for raw in text.splitlines():
        ln = raw.strip()
        low = ln.lower()
        if low.startswith(".control"):
            in_control = True
        elif low.startswith(".endc"):
            in_control = False
        elif low.startswith(".options") and not in_control:
            out.append(ln)
    return out


def _trtol_in(cards):
    for c in cards:
        for tok in c.split():
            if tok.lower().startswith("trtol="):
                try:
                    return float(tok.split("=", 1)[1])
                except ValueError:
                    return None
    return None


def test_every_class_that_declares_a_testbench_wrote_one(tmp_path):
    """THE POPULATION GUARD, and it is deliberately separate from every value
    guard below. Without it a fixture that admits no block at all would make
    each of those pass over an empty set — which is how they read on the first
    run of this file, four green rows over zero decks."""
    classes, decks, why = _emit(tmp_path)
    assert set(decks) == set(classes), (
        f"classes declaring a testbench: {classes}; decks written: "
        f"{sorted(decks)}; refusal recorded for the rest: {why}")


def test_a3_testbench_carries_a_top_level_integration_control(tmp_path):
    classes, decks, why = _emit(tmp_path)
    assert decks, f"no deck to grade; refusals: {why}"
    missing = sorted(b for b, t in decks.items() if not _options_cards(t))
    assert not missing, (
        "these A3 testbenches carry no top-level `.options` card, so the "
        "producer verifies them on the simulator's default step control: "
        f"{missing}")


def test_the_emitted_step_control_is_tighter_than_the_default(tmp_path):
    classes, decks, why = _emit(tmp_path)
    assert decks, f"no deck to grade; refusals: {why}"
    bad = {b: _trtol_in(_options_cards(t)) for b, t in decks.items()
           if _trtol_in(_options_cards(t)) is None
           or _trtol_in(_options_cards(t)) >= NGSPICE_DEFAULT_TRTOL}
    assert not bad, (
        "a `trtol` at or above the simulator's shipped default "
        f"({NGSPICE_DEFAULT_TRTOL}) asks for a timestep at least as large as "
        f"the default and therefore verifies nothing: {bad}")


def test_the_card_is_above_the_control_block(tmp_path):
    """The direction a careless move breaks: the same text one line lower
    parses, prints nothing and changes no analysis."""
    classes, decks, why = _emit(tmp_path)
    assert decks, f"no deck to grade; refusals: {why}"
    for b, t in sorted(decks.items()):
        halves = t.split(".control", 1)
        assert len(halves) == 2, f"{b}: no `.control` block in the testbench"
        assert ".options" in halves[0].lower(), (
            f"{b}: the `.options` card is not above `.control`")


def test_the_producer_declares_the_card_it_emits(tmp_path):
    """The classes a synthetic fixture can admit are not the classes the
    producer serves. This grades the DECLARATION the emitter appends
    unconditionally, so a class this file cannot drive is still covered.

    `getattr` with an empty default, not an import of the name: a control arm
    that raises AttributeError observes nothing and reports a missing symbol
    instead of the behaviour."""
    declared = getattr(A3MOD, "_TB_INTEGRATION_OPTIONS", ())
    cards = _options_cards("\n".join(declared))
    v = _trtol_in(cards)
    assert v is not None and v < NGSPICE_DEFAULT_TRTOL, (
        "the producer declares no integration control below the simulator "
        f"default; it declares {tuple(declared)!r}")
