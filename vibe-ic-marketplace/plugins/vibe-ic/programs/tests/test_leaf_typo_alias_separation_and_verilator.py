#!/usr/bin/env python3
"""Two defects in the shipped canonical-spelling alias emitter.

1. WORD SEPARATION IS NOT A MISSPELLING. `barrel_shifter` is one `_`-deletion
   from the canonical `barrelshifter`, so the edit-distance test read the
   STANDARD separated spelling as a typo and proposed an alias for it. Measured
   over 302 officially-passing CVDP deliveries: it fired on 4 files, every one
   of them a correctly-named `barrel_shifter`, and on nothing else.

   The downstream guards do not catch it. shape_b_sample_export's INSTANTIATES
   guard (PR #33) admits any canonical module that instantiates the leaf, and
   this wrapper does exactly that — so the spurious module ships. PR #33's own
   comment already recorded that `detect_leaf_typo` "over-fires on legitimate
   alternate spellings"; it was worked around at the consumer instead of fixed
   at the producer, and this is a case the workaround cannot see.

2. THE WRAPPER WAS NOT HIDDEN FROM VERILATOR. `tb_toplevel_alias.alias_wrapper`
   has emitted its wrapper inside an `ifndef VERILATOR guard since 2026-08-25,
   for the stated reason that an uninstantiated wrapper is MULTITOP under
   `--lint-only -Wall` and verilator exits non-zero on any warning. This
   emitter is the other half of that pair and never got the guard.

   The condition is precise, and worth stating because a single-module test
   CANNOT show it: the wrapper instantiates the leaf, so in a one-module
   delivery the wrapper is the only top and lints clean. MULTITOP appears as
   soon as the delivery has any OTHER top-level module — the normal
   multi-module shape — because then there are two.
"""
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
from leaf_typo_alias_emit import detect_leaf_typo  # noqa: E402


def test_a_separated_canonical_term_is_not_a_typo():
    assert detect_leaf_typo("barrel_shifter") is None, (
        "`barrel_shifter` is the standard spelling; proposing a `barrelshifter` "
        "alias for it ships an off-design module")


@pytest.mark.parametrize("leaf,canonical", [
    ("substractor", "subtractor"),
    ("multipler", "multiplier"),
])
def test_real_typos_are_still_corrected(leaf, canonical):
    """The separation guard must not silence what the emitter exists for."""
    assert detect_leaf_typo(leaf) == canonical


@pytest.mark.parametrize("leaf", ["counter", "ripple_carry_adder", "my_block"])
def test_correct_names_stay_silent(leaf):
    assert detect_leaf_typo(leaf) is None


def _wrapper(tmp_path):
    src = tmp_path / "substractor.v"
    src.write_text(
        "module substractor #(parameter W=8) "
        "(input [W-1:0] a, input [W-1:0] b, output [W-1:0] y);\n"
        "  assign y = a - b;\n"
        "endmodule\n"
        # a sibling top: without one the wrapper is the ONLY top and MULTITOP
        # cannot fire, which is why this fixture has two modules
        "module datapath (input [7:0] p, input [7:0] q, output [7:0] r);\n"
        "  substractor #(.W(8)) u (.a(p), .b(q), .y(r));\n"
        "endmodule\n")
    return src


def test_the_wrapper_is_hidden_from_verilator(tmp_path):
    src = _wrapper(tmp_path)
    out = subprocess.run(
        [sys.executable, str(PLUGIN / "programs" / "leaf_typo_alias_emit.py"),
         "--rtl", str(src), "--leaf", "substractor",
         "--out", str(tmp_path / "subtractor.v")],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    text = (tmp_path / "subtractor.v").read_text()
    assert "`ifndef VERILATOR" in text and "`endif" in text, (
        "the wrapper ships unguarded; verilator counts it as a second top "
        "module and fails the lint on the wrapper alone:\n" + text)


@pytest.mark.skipif(not __import__("shutil").which("verilator"),
                    reason="verilator not installed")
def test_verilator_accepts_the_guarded_wrapper_and_rejects_the_bare_one(tmp_path):
    src = _wrapper(tmp_path)
    guarded = tmp_path / "subtractor.v"
    subprocess.run(
        [sys.executable, str(PLUGIN / "programs" / "leaf_typo_alias_emit.py"),
         "--rtl", str(src), "--leaf", "substractor", "--out", str(guarded)],
        capture_output=True, text=True, timeout=60)
    bare = tmp_path / "subtractor_bare.v"
    bare.write_text("\n".join(
        l for l in guarded.read_text().splitlines()
        if l.strip() not in ("`ifndef VERILATOR", "`endif")))

    def multitop(extra):
        cp = subprocess.run(["verilator", "--lint-only", "-Wall",
                             str(src), str(extra)],
                            capture_output=True, text=True, timeout=120)
        return "MULTITOP" in cp.stdout + cp.stderr

    assert multitop(bare), (
        "expected the unguarded wrapper to raise MULTITOP — if this stops "
        "being true the guard's justification has changed, not just its effect")
    assert not multitop(guarded), (
        "the guard did not suppress MULTITOP")


def test_a_misspelled_qualifier_is_corrected():
    """The term set held only agent-NOUN device names.

    A misspelled ADJECTIVE inside a compound was therefore invisible, while the
    hidden harness elaborates the correctly-spelled form. Verified end to end
    through the official scorer, not by elaboration argument: the delivery
    scores FAIL on its own (`iverilog -s binary_to_one_hot_decoder_sequential`
    against a module declared `..._sequencial`) and PASSes with the emitted
    wrapper appended.
    """
    assert (detect_leaf_typo("binary_to_one_hot_decoder_sequencial")
            == "binary_to_one_hot_decoder_sequential")


@pytest.mark.parametrize("leaf", [
    "fifo_depth_controler",       # -> controller, a pre-existing noun term
    "spi_master_sequencial_fsm",  # -> sequential, entirely different vocabulary
    "dma_hierarchial_mux",        # -> hierarchical
])
def test_the_qualifier_rule_is_not_tied_to_one_design(leaf):
    assert detect_leaf_typo(leaf) is not None


@pytest.mark.parametrize("leaf", [
    "pipeline_mac",               # `pipelined` would make this a 1-char typo
    "registered_output",          # same trap via `registered`
    "combinatorial_alu",          # d=3 from `combinational`, must stay silent
    "unidirectional_bridge",      # d=2 from `bidirectional` — a d=1 here would
                                  # have INVERTED the design's intent
    "parallel_in_serial_out",     # exact term, not a typo
])
def test_the_qualifier_rule_stays_silent_on_legitimate_neighbours(leaf):
    assert detect_leaf_typo(leaf) is None


def test_terms_whose_misspellings_the_inflection_guard_eats_are_not_listed():
    """Do not list a term that can never fire — it reads as coverage.

    Every realistic misspelling of `synchronous` / `asynchronous` ends in `s`,
    and the `-s` arm of the inflection guard returns None before the distance
    test runs. Listing them would be dead code.
    """
    import leaf_typo_alias_emit as L
    dead = [t for t in L._CANONICAL_HW_TERMS
            if t.endswith(L._INFLECTION_SUFFIXES)]
    assert not dead, (
        f"these canonical terms can never be matched — every misspelling of "
        f"them is eaten by the inflection guard first: {sorted(dead)}")
    for m in ("syncronous", "synchronus", "asyncronous"):
        assert detect_leaf_typo(m) is None
