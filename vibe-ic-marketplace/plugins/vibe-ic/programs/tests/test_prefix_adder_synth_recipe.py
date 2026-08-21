#!/usr/bin/env python3
"""prefix_adder_synth_recipe.py — parallel-prefix adder QoR recipe.

Captured from the vibeic-eda abc/yosys port (2026-07-08): the shipped yosys
already delivers parallel-prefix carry-lookahead (Brent-Kung default + Kogge-
Stone / Han-Carlson / Sklansky choices); this program makes the synth flow
invoke it correctly and CEC-gates the result. Verified in vibeic-eda:0.2.3
(32-bit a+b: ripple 128 -> Kogge-Stone 72, CEC proven).

Covered:
  * known_topologies / build_techmap_step: default(brent-kung)==bare techmap;
    non-default puts the choice map FIRST then +/techmap.v in ONE call (the
    silent-fall-through-to-Brent-Kung gotcha); unknown topology raises.
  * build_prefix_adder_recipe: alumacc + techmap + (default) a real CEC block;
    --no-cec omits the proof.
  * parse_cec_verdict: EQUIVALENT only on a real non-vacuous proof; UNPROVEN ->
    NOT_EQUIVALENT; garbage -> UNKNOWN (never a silent pass).
  * CLI: --list ok; --emit ok; unknown topology -> arg/2.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import prefix_adder_synth_recipe as P  # noqa: E402


# ---- topology selection ---------------------------------------------------
def test_known_topologies():
    t = P.known_topologies()
    for name in ("brent-kung", "kogge-stone", "han-carlson", "sklansky"):
        assert name in t, name


def test_default_topology_is_bare_techmap():
    # Brent-Kung is the built-in $lcu map -> a bare techmap selects it.
    assert P.build_techmap_step("brent-kung") == "techmap"


def test_choice_map_ordering_choice_first():
    # The gotcha: choice map must precede +/techmap.v in ONE techmap call,
    # else $alu never lowers to $lcu (silent fall-through to Brent-Kung).
    step = P.build_techmap_step("kogge-stone")
    assert "+/choices/kogge-stone.v" in step and "+/techmap.v" in step
    assert step.index("+/choices/kogge-stone.v") < step.index("+/techmap.v")
    assert step.count("techmap -map") == 1  # ONE call, not two


def test_unknown_topology_raises():
    try:
        P.build_techmap_step("carry-skip")
    except ValueError as e:
        assert "unknown" in str(e).lower()
    else:
        raise AssertionError("expected ValueError on unknown topology")


# ---- recipe ---------------------------------------------------------------
def test_recipe_has_alumacc_and_cec_by_default():
    ys = P.build_prefix_adder_recipe("add32.v", "dut", topology="kogge-stone")
    assert "alumacc" in ys
    assert "techmap -map +/choices/kogge-stone.v -map +/techmap.v" in ys
    # CEC block present by default (QoR must not trade correctness)
    for cmd in ("equiv_make gold gate equiv", "equiv_induct", "equiv_status"):
        assert cmd in ys, cmd


def test_recipe_no_cec_omits_proof():
    ys = P.build_prefix_adder_recipe("add32.v", "dut",
                                     topology="sklansky", cec=False)
    assert "alumacc" in ys and "stat" in ys
    assert "equiv_make" not in ys


# ---- gate-level ripple recovery (lift_adder) ------------------------------
def test_gate_level_recovers_before_alumacc():
    # gate_level must run extract_fa -> opt_clean -> lift_adder BEFORE alumacc,
    # in that order, so a gate-level ripple is lifted to $add first.
    ys = P.build_prefix_adder_recipe("ripple32.v", "dut",
                                     topology="kogge-stone", gate_level=True)
    for step in ("extract_fa -fa -ha", "opt_clean", "lift_adder", "alumacc"):
        assert step in ys, step
    assert ys.index("extract_fa -fa -ha") < ys.index("opt_clean") \
        < ys.index("lift_adder") < ys.index("alumacc")
    # the prefix choice map still fires after the lift
    assert "techmap -map +/choices/kogge-stone.v -map +/techmap.v" in ys


def test_gate_level_cec_gold_is_plain_ripple_not_lifted():
    # The CEC reference for a gate-level input is the SAME netlist at gate level
    # WITHOUT the lift; the lift/prefix must appear only ONCE (the gate track),
    # never in the gold track.
    ys = P.build_prefix_adder_recipe("ripple32.v", "dut",
                                     topology="kogge-stone", gate_level=True)
    assert "equiv_make gold gate equiv" in ys
    assert ys.count("lift_adder") == 1          # only the gate track lifts
    assert ys.count("extract_fa -fa -ha") == 1


def test_gate_level_default_rtl_path_has_no_lift():
    # The ordinary RTL path must NOT emit lift_adder (no gate-level recovery).
    ys = P.build_prefix_adder_recipe("add32.v", "dut", topology="kogge-stone")
    assert "lift_adder" not in ys and "extract_fa" not in ys


def test_cli_gate_level_ok():
    assert P.main(["--emit", "ripple32.v", "--top", "dut",
                   "--topology", "kogge-stone", "--gate-level"]) == 0


# ---- CEC verdict ----------------------------------------------------------
def test_cec_verdict_equivalent():
    assert P.parse_cec_verdict(
        "Of those cells 33 are proven and 0 are unproven.") == P.V_EQUIV
    assert P.parse_cec_verdict("Equivalence successfully proven!") == P.V_EQUIV


def test_cec_verdict_not_equivalent_on_unproven():
    assert P.parse_cec_verdict(
        "Of those cells 30 are proven and 3 are unproven.") == P.V_NONEQUIV


def test_cec_verdict_unknown_on_garbage():
    assert P.parse_cec_verdict("yosys crashed\n") == P.V_UNKNOWN


# ---- CLI ------------------------------------------------------------------
def test_cli_list_ok():
    assert P.main(["--list"]) == 0


def test_cli_emit_ok():
    assert P.main(["--emit", "add32.v", "--top", "dut",
                   "--topology", "kogge-stone"]) == 0
