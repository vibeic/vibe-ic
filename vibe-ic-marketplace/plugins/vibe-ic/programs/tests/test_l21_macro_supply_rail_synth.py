#!/usr/bin/env python3
"""l21_macro_supply_rail_synth — remove the CAUSE of the L21-1 route abort.

`l21_macro_supply_rail_declared_check` is deliberately ADVISORY: promoting it to
blocking would redden already-published cells, which is a flow-owner decision.
This program attacks the other end — it derives the missing rails from the
design's OWN macro LEFs so the clause is satisfied without anyone flipping
enforcement, and a blind run recovers with no agent involved.

The consequence chain it prevents, quoted from the gate: an undeclared supply
pin becomes HARDMACRO_SUPPLY_UNCONNECTED, synthesis ties the terminal off with
TIEHI/TIELO, a SIGNAL net lands on a POWER-typed terminal, and TritonRoute
aborts the WHOLE detailed route.

The end-to-end test below is the one that matters: gate rc=1 -> synth -> rc=0.
It is what caught a real defect in the first version of this program, which
fixed L21-1 and simultaneously tripped L21-2 by emitting a ground entry with a
null power net — a different failure, not a fix.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
SYNTH = PROG / "l21_macro_supply_rail_synth.py"
GATE = PROG / "l21_macro_supply_rail_declared_check.py"

# A hard macro with a dedicated programming supply, plus an ordinary core cell.
# No part number, no chip class — the shape is what matters.
_LEF = """MACRO a_hard_macro
  CLASS BLOCK ;
  PIN VDDC
    DIRECTION INOUT ;
    USE POWER ;
  END VDDC
  PIN VPPROG
    DIRECTION INOUT ;
    USE POWER ;
  END VPPROG
  PIN VSSC
    DIRECTION INOUT ;
    USE GROUND ;
  END VSSC
  PIN DOUT
    DIRECTION OUTPUT ;
    USE SIGNAL ;
  END DOUT
END a_hard_macro
MACRO an_ordinary_cell
  CLASS CORE ;
  PIN VDDC
    DIRECTION INOUT ;
    USE POWER ;
  END VDDC
END an_ordinary_cell
"""

_L21 = {"doc_id": "L21",
        "power_domains": [{"name": "core", "power_net": "VDDC",
                           "ground_net": "VSSC"}]}


def _project(tmp_path):
    (tmp_path / "input" / "macros").mkdir(parents=True)
    (tmp_path / "input" / "macros" / "m.lef").write_text(_LEF)
    d = tmp_path / "phase1" / "generated_docs"
    d.mkdir(parents=True)
    (d / "L21_POWER_INTENT.json").write_text(json.dumps(_L21, indent=2))
    return tmp_path


def _run(prog, *args):
    return subprocess.run([sys.executable, str(prog), *map(str, args)],
                          capture_output=True, text=True)


def _l21(p):
    return json.loads((p / "phase1" / "generated_docs"
                       / "L21_POWER_INTENT.json").read_text())


def test_end_to_end_the_gate_goes_from_fail_to_pass(tmp_path):
    """THE TEST THAT MATTERS: the gate must actually go green, not swap which
    rule it fails on."""
    p = _project(tmp_path)
    before = _run(GATE, p)
    assert before.returncode == 1, "fixture must start FAILING or it proves nothing"
    assert "L21-1" in before.stdout + before.stderr

    _run(SYNTH, p, "--lef", p / "input" / "macros", "--apply")

    after = _run(GATE, p)
    assert after.returncode == 0, (
        f"gate still fails after synth:\n{after.stdout}\n{after.stderr}")


def test_dry_run_does_not_touch_the_document(tmp_path):
    """Editing a design document is opt-in. Default must be read-only."""
    p = _project(tmp_path)
    doc = p / "phase1" / "generated_docs" / "L21_POWER_INTENT.json"
    before = doc.read_bytes()
    r = _run(SYNTH, p, "--lef", p / "input" / "macros")
    assert r.returncode == 0
    assert doc.read_bytes() == before


def test_a_dedicated_supply_is_not_folded_onto_the_core_rail(tmp_path):
    """The refusal that matters most. Folding a programming supply onto the
    core rail is functionally wrong AND a reliability hazard — exactly the
    guess a deriving program must not make."""
    p = _project(tmp_path)
    _run(SYNTH, p, "--lef", p / "input" / "macros", "--apply")
    nets = {d.get("power_net") for d in _l21(p)["power_domains"]}
    assert "VPPROG" in nets, "the dedicated supply lost its own rail"


def test_no_voltage_is_invented(tmp_path):
    """A voltage is recorded only when the design's own documents state one.
    Here nothing does, so every derived supply must say so rather than guess."""
    p = _project(tmp_path)
    _run(SYNTH, p, "--lef", p / "input" / "macros", "--apply")
    for d in _l21(p)["power_domains"]:
        if d.get("derived_by") and d.get("power_net") != d.get("ground_net"):
            v = d.get("voltage_v")
            assert v is None or d.get("voltage_status") != "stated", (
                f"invented a voltage for {d.get('name')}: {v}")


def test_existing_declarations_are_preserved_byte_identically(tmp_path):
    """It ADDS what is missing; it never rewrites what the design already said."""
    p = _project(tmp_path)
    _run(SYNTH, p, "--lef", p / "input" / "macros", "--apply")
    core = [d for d in _l21(p)["power_domains"] if d.get("name") == "core"]
    assert core == [_L21["power_domains"][0]]


def test_applying_twice_adds_nothing_the_second_time(tmp_path):
    """Idempotent — a producer that runs every pass must not accumulate."""
    p = _project(tmp_path)
    _run(SYNTH, p, "--lef", p / "input" / "macros", "--apply")
    first = _l21(p)["power_domains"]
    _run(SYNTH, p, "--lef", p / "input" / "macros", "--apply")
    assert _l21(p)["power_domains"] == first


def test_everything_added_carries_its_provenance(tmp_path):
    """A derived declaration must say it was derived, and from what — otherwise
    a reader cannot tell a measured rail from a stated one."""
    p = _project(tmp_path)
    _run(SYNTH, p, "--lef", p / "input" / "macros", "--apply")
    for d in _l21(p)["power_domains"]:
        if d.get("name") != "core":
            assert d.get("derived_by") == "l21_macro_supply_rail_synth"
            assert d.get("derived_from", {}).get("macro_lef_pin_use")


def test_signal_pins_never_become_rails(tmp_path):
    """NEGATIVE CONTROL: only USE POWER / USE GROUND pins are rails. A SIGNAL
    pin becoming one would declare a rail the design does not have."""
    p = _project(tmp_path)
    _run(SYNTH, p, "--lef", p / "input" / "macros", "--apply")
    blob = json.dumps(_l21(p))
    assert "DOUT" not in blob
