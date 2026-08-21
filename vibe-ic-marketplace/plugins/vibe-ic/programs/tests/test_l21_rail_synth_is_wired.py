#!/usr/bin/env python3
"""l21_macro_supply_rail_synth must be REACHED by the flow, not just present.

The program landed as a producer with **zero callers** — no runner, no flow
step, no gate imported it. Its own unit tests passed the whole time, because
they invoke it directly. So the suite proved the program WORKS and proved
nothing about whether it ever RUNS, and the consumer
(`l21_macro_supply_rail_declared_check`, an advisory in flow step D1) kept
failing for want of rails that only a human running the synth by hand supplied.

`test_l21_macro_supply_rail_synth.py` covers the program's behaviour. This file
covers the two ways that behaviour can be true and still never reach a design:

  1. NOT CALLED — nothing in the flow invokes it.
  2. CALLED, BUT LOOKING ELSEWHERE — it is invoked, but its default LEF roots
     do not cover the roots its consumer harvests macros from, so it reports
     NOT_APPLICABLE on a design whose macros the gate can plainly see.

Both are the same failure to the user: the gate stays red and the program that
exists to make it green has, in effect, not run.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
GATE = PROG / "l21_macro_supply_rail_declared_check.py"

sys.path.insert(0, str(PROG))

# A hard macro carrying a dedicated programming supply the core rail does not
# cover, plus a std cell that must NOT be mistaken for a hard macro.
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


def _project(tmp_path: Path, lef_subdir: str) -> Path:
    """A design whose macro LEF sits under `lef_subdir`."""
    d = tmp_path / lef_subdir
    d.mkdir(parents=True)
    (d / "m.lef").write_text(_LEF)
    g = tmp_path / "phase1" / "generated_docs"
    g.mkdir(parents=True)
    (g / "L21_POWER_INTENT.json").write_text(json.dumps(_L21, indent=2))
    return tmp_path


def _gate(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), str(project)],
        capture_output=True, text=True)


# ---------------------------------------------------------------------------
# 1. The producer's reach must cover the consumer's reach.
# ---------------------------------------------------------------------------
def test_default_lef_roots_cover_every_root_the_consumer_searches(tmp_path):
    """A property, so it cannot rot when someone adds a sixth root.

    The consumer harvests hard macros from five roots. Whatever that list
    becomes, the producer's default must search all of them -- otherwise there
    is a design shape where the gate sees a macro the producer never looks for,
    and the gate can never be satisfied automatically.
    """
    from l21_macro_supply_rail_declared_check import _MACRO_LEF_GLOBS
    from l21_macro_supply_rail_synth import _default_lef_roots

    proj = tmp_path
    searched = {p.resolve() for p in _default_lef_roots(proj)}
    for pat in _MACRO_LEF_GLOBS:
        root = (proj / pat.split("/**", 1)[0]).resolve()
        assert root in searched, (
            f"the consumer harvests macros from {pat!r} but the producer's "
            f"default never looks in {root}; a design with its macros there "
            f"fails the gate forever")


@pytest.mark.parametrize("lef_subdir", [
    "input/pdk_local/vendor",
    "input/macros",
    "input/hardmacro",
    "phase3/analog/hardmacro",
    "phase2/analog/hardmacro",
])
def test_gate_recovers_wherever_the_design_keeps_its_macro_lefs(
        tmp_path, lef_subdir):
    """Same design, five legal homes for the LEF. Before the fix only the
    `input/pdk_local` case recovered; the other four reported NOT_APPLICABLE
    while the gate failed on the very macro they had declined to look for."""
    from l21_macro_supply_rail_synth import main as synth

    p = _project(tmp_path, lef_subdir)
    assert _gate(p).returncode == 1, (
        "fixture must start FAILING or it proves nothing")

    assert synth([str(p), "--apply"]) == 0

    after = _gate(p)
    assert after.returncode == 0, (
        f"macros under {lef_subdir} were not recovered:\n"
        f"{after.stdout}\n{after.stderr}")


# ---------------------------------------------------------------------------
# 2. The flow step that OWNS the consumer must invoke the producer.
# ---------------------------------------------------------------------------
def test_step_d1_actually_runs_the_synth(tmp_path):
    """End-to-end through the runner function that IS flow step D1.

    Deliberately not a source grep: an import statement in the file proves the
    text is there, not that the call is reached. This drives the real D1 L-doc
    emit and then asks the real gate.
    """
    from phase1_doc_one_shot_runner import _emit_l19_to_l23_skeletons

    p = _project(tmp_path, "input/macros")
    assert _gate(p).returncode == 1

    _emit_l19_to_l23_skeletons(p)

    after = _gate(p)
    assert after.returncode == 0, (
        "flow step D1 emitted the power-intent layer and left the macro "
        f"supply rails underived:\n{after.stdout}\n{after.stderr}")


def test_d1_derives_only_what_the_macros_evidence(tmp_path):
    """The synth may only ADD rails its LEF evidence supports.

    Deliberately NOT asserting that a pre-existing `power_domains` entry
    survives D1: measuring that here would be measuring the wrong step. D1
    (re)emits the L21 SKELETON as its job -- in a real run D1 is what puts the
    layer on disk in the first place, and extraction populates it afterwards --
    so a populated L21 sitting there before D1 runs is a state the flow never
    produces. The program-level "never rewrites what the design already said"
    property is pinned where it is real, in
    test_l21_macro_supply_rail_synth.py::
    test_existing_declarations_are_preserved_byte_identically.

    What D1 owes is this: every rail present after the step traces to a PG pin
    of a hard macro, and the std cell contributes nothing.
    """
    from phase1_doc_one_shot_runner import _emit_l19_to_l23_skeletons

    p = _project(tmp_path, "input/macros")
    _emit_l19_to_l23_skeletons(p)

    doc = json.loads((p / "phase1" / "generated_docs"
                      / "L21_POWER_INTENT.json").read_text())
    container = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
    nets = {d.get("power_net") for d in container["power_domains"]}
    assert {"VDDC", "VPPROG"} <= nets, (
        f"a hard-macro supply pin went underived: {nets}")
    assert not (nets - {"VDDC", "VPPROG", "VSSC", None}), (
        f"invented a rail no macro declares: {nets}")


def test_d1_is_fail_open_when_there_is_nothing_to_derive(tmp_path):
    """No macro LEF anywhere: the emit must complete normally and leave a
    usable layer. A producer that takes the whole L-doc emit down when a design
    simply has no hard macros would be a worse defect than the one being
    fixed."""
    from phase1_doc_one_shot_runner import _emit_l19_to_l23_skeletons

    g = tmp_path / "phase1" / "generated_docs"
    g.mkdir(parents=True)

    _emit_l19_to_l23_skeletons(tmp_path)   # must not raise

    doc = json.loads((g / "L21_POWER_INTENT.json").read_text())
    container = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
    assert container.get("power_domains") == [], (
        "no macro evidence exists, so no rail may be asserted")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
