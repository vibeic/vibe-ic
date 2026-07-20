"""Deterministic 1-D cellular-automaton (Wolfram "Rule N") -> RTL synth.

A STATED rule number (0..255) over a 3-cell neighbourhood with 0-valued off-array
boundaries is a CLOSED-FORM spec: bit (L<<2)|(C<<1)|R of the rule number is the
center cell's next value, with zero ambiguity and no oracle. A blind author can
flip the left/right neighbour wiring or mis-transcribe the 8-row table per round
(single-shot variance). cellular_automaton_synth absorbs it as a PROGRAM.

§4.05 no-leak: FIRES only on an unambiguous CA spec; SKIPs (returns None) when the
rule number is absent / out-of-range / conflicting, the boundary is wrap-around /
non-zero / unstated, the neighbourhood is not 3-cell, the interface is not the
canonical clk/load/data[W]/q[W], or the spec is a plain shift / non-CA. The
NEGATIVE cases below sit JUST OUTSIDE the boundary and MUST still skip.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import cellular_automaton_synth as C  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

# ---------------------------------------------------------------------------
# Real benchmark prompts (host-scored end-to-end further down if iverilog + the
# dataset are present); the unit assertions here are dataset-independent.
# ---------------------------------------------------------------------------
_DS = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")
_FIRING = ["Prob108_rule90", "Prob124_rule110"]

# A self-contained rule-90 prompt (matches the VerilogEval Prob108 wording) so the
# positive path is testable even without the external dataset.
_RULE90 = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  clk,
 - input  load,
 - input  data (512 bits)
 - output q    (512 bits)

The module should implement Rule 90, a one-dimensional cellular automaton.
At each time step, the next state of each cell is the XOR of the cell's two
current neighbours. In this circuit, create a 512-cell system (q[511:0]), and
advance by one time step each clock cycle. The load input indicates the state of
the system should be loaded with data[511:0]. Assume the boundaries (q[-1] and
q[512]) are both zero (off). Assume all sequential logic is triggered on the
positive edge of the clock.
"""


# ===========================================================================
# POSITIVE — the synth fires and is structurally correct
# ===========================================================================
def test_rule90_fires_and_wiring_is_correct():
    rtl = C.synth(_RULE90, "TopModule")
    assert rtl is not None
    # canonical CA interface + sequential load/advance
    assert "output reg [511:0] q" in rtl
    assert "q <= data" in rtl and "q <= nxt" in rtl
    # standard 0-boundary neighbour buses: left=q[i+1], right=q[i-1]
    assert "wire [511:0] l = {1'b0, q[511:1]}" in rtl
    assert "wire [511:0] r = {q[510:0], 1'b0}" in rtl


def test_rule90_lookup_matches_prompt_table():
    # Rule 90 prompt table -> next center value per (L,C,R).
    exp = {(1, 1, 1): 0, (1, 1, 0): 1, (1, 0, 1): 0, (1, 0, 0): 1,
           (0, 1, 1): 1, (0, 1, 0): 0, (0, 0, 1): 1, (0, 0, 0): 0}
    for (l, c, r), v in exp.items():
        assert C._next_bit(90, l, c, r) == v


def test_rule110_lookup_matches_prompt_table():
    # Rule 110 prompt table -> next center value per (L,C,R).
    exp = {(1, 1, 1): 0, (1, 1, 0): 1, (1, 0, 1): 1, (1, 0, 0): 0,
           (0, 1, 1): 1, (0, 1, 0): 1, (0, 0, 1): 1, (0, 0, 0): 0}
    for (l, c, r), v in exp.items():
        assert C._next_bit(110, l, c, r) == v


def test_rule_number_fully_determines_sop():
    # Different rule numbers must produce different next-state logic (general,
    # not name-keyed): rule 90 != rule 110 emitted SOP.
    r90 = C.synth(_RULE90, "TopModule")
    r110 = C.synth(_RULE90.replace("Rule 90", "Rule 110"), "TopModule")
    assert r90 is not None and r110 is not None
    n90 = re.search(r"wire \[511:0\] nxt = (.+);", r90).group(1)
    n110 = re.search(r"wire \[511:0\] nxt = (.+);", r110).group(1)
    assert n90 != n110


# ===========================================================================
# §4.05 NEGATIVE no-leak — JUST outside the boundary, MUST return None
# ===========================================================================
def test_skip_when_rule_number_absent():
    # CA family + interface present, but NO rule number stated -> under-determined.
    bad = _RULE90.replace("Rule 90, ", "")
    assert C.synth(bad, "TopModule") is None


def test_skip_when_rule_number_out_of_range():
    # "Rule 300" is not a valid 8-bit lookup -> SKIP (never guess / clamp).
    bad = _RULE90.replace("Rule 90", "Rule 300")
    assert C.synth(bad, "TopModule") is None


def test_skip_on_conflicting_rule_numbers():
    # Two DIFFERENT rule numbers stated -> ambiguous which lookup -> SKIP.
    bad = _RULE90.replace("implement Rule 90, a",
                          "implement Rule 90 or maybe Rule 110, a")
    assert C.synth(bad, "TopModule") is None


def test_skip_on_wraparound_boundary():
    # Cyclic / wrap-around boundary => off-array wiring is NOT the standard zeros.
    bad = _RULE90.replace(
        "Assume the boundaries (q[-1] and\nq[512]) are both zero (off).".replace("\n", " "),
        "Assume the array wraps around cyclically at both ends.")
    # the prompt above has the sentence on two lines; do a robust replace too:
    bad = re.sub(r"Assume the boundaries.*?\(off\)\.",
                 "Assume the array wraps around cyclically at both ends.",
                 bad, flags=re.S)
    assert C.synth(bad, "TopModule") is None


def test_skip_on_unstated_boundary():
    # Boundary convention simply not stated -> off-array cells unknown -> SKIP.
    bad = re.sub(r"Assume the boundaries.*?\(off\)\.", "", _RULE90, flags=re.S)
    assert C.synth(bad, "TopModule") is None


def test_skip_on_wrong_neighbourhood_size():
    # A 5-cell / wider neighbourhood is NOT the 3-cell rule-number lookup -> SKIP.
    bad = _RULE90.replace(
        "the XOR of the cell's two\ncurrent neighbours".replace("\n", " "),
        "a function of the cell's four nearest neighbours")
    bad = re.sub(r"the XOR of the cell's two\s+current neighbours",
                 "a function of the cell's four nearest neighbours", bad)
    assert C.synth(bad, "TopModule") is None


def test_skip_on_two_dimensional():
    bad = _RULE90.replace("one-dimensional cellular automaton",
                          "two-dimensional cellular automaton")
    assert C.synth(bad, "TopModule") is None


def test_skip_on_non_ca_shift_register():
    # A plain shift register is sequential with the same ports but NOT a CA.
    shift = """
    Implement a module named TopModule.
     - input  clk
     - input  load
     - input  data (512 bits)
     - output q    (512 bits)
    On each clock the register shifts left by one; load presets it to data.
    """
    assert C.synth(shift, "TopModule") is None


def test_skip_on_data_width_mismatch():
    # data width != q width -> not a well-posed single-array CA -> SKIP.
    bad = _RULE90.replace(" - input  data (512 bits)", " - input  data (256 bits)")
    assert C.synth(bad, "TopModule") is None


def test_skip_on_missing_load_port():
    bad = _RULE90.replace(" - input  load,\n", "")
    assert C.synth(bad, "TopModule") is None


def test_skip_on_extra_port():
    # An unexpected extra port means the interface isn't the canonical CA one.
    bad = _RULE90.replace(" - input  load,", " - input  load,\n - input  rst,")
    assert C.synth(bad, "TopModule") is None


# ===========================================================================
# HOST-SCORE — end-to-end iverilog 0-mismatch on the real prompts (skipped if
# iverilog or the dataset is unavailable).
# ===========================================================================
def _iverilog_available() -> bool:
    from shutil import which
    return which("iverilog") is not None and which("vvp") is not None


@pytest.mark.parametrize("prob", _FIRING)
def test_host_score_zero_mismatch(prob, tmp_path):
    if not _iverilog_available():
        pytest.skip("iverilog/vvp not available")
    prompt = _DS / f"{prob}_prompt.txt"
    ref = _DS / f"{prob}_ref.sv"
    tb = _DS / f"{prob}_test.sv"
    if not (prompt.exists() and ref.exists() and tb.exists()):
        pytest.skip(f"dataset files for {prob} not present")
    rtl = C.synth(prompt.read_text(errors="replace"), "TopModule")
    assert rtl is not None, f"{prob} must FIRE"
    dut = tmp_path / "dut.sv"
    dut.write_text(rtl)
    vvp = tmp_path / "a.vvp"
    comp = subprocess.run(
        ["iverilog", "-g2012", "-o", str(vvp), str(dut), str(ref), str(tb)],
        capture_output=True, text=True)
    assert comp.returncode == 0, f"compile failed:\n{comp.stderr}"
    run = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True)
    out = run.stdout + run.stderr
    m = re.search(r"mismatched samples is (\d+)", out)
    assert m is not None, f"no mismatch line in vvp output:\n{out}"
    assert int(m.group(1)) == 0, f"{prob} had {m.group(1)} mismatches:\n{out}"
