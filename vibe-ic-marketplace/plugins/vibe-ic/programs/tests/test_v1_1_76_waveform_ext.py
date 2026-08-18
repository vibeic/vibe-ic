"""v1.1.76 completeness wave-2 — waveform_ext_synth.py (COMPLEMENT to
waveform_truth_table_synth.py).

The companion synth closes two waveform variants the canonical sibling SKIPs:

  Path 1 — COMBINATIONAL-BY-CONSISTENCY: a purely-combinational truth table whose
    prose lacks the literal word "combinational" (Prob083_mt2015_q4b: z = ~(x^y)).
    The sibling's combinational path requires that keyword, so it SKIPs; this one
    fires on no-clock-column + no-seq-idiom + self-consistent tables.

  Path 2 — GENERAL SINGLE-POSEDGE-FF: a plain single-flip-flop circuitN problem
    whose prose lacks the sibling's "...observable through the output <name>"
    phrase (Prob098_circuit7: q <= ~a). The sibling's sequential path requires that
    phrase, so it SKIPs; this one reads the registered next-state across posedges.

§4.05 no-leak: the synth FIRES only inside the proven-faithful envelope and SKIPs
everywhere else — it can never emit a wrong sample. These tests pin BOTH halves:
the positives (fires + emits correct RTL + host-scores 0 mismatches on the real
dataset) AND ≥4 no-leak negatives (multi-bit/hex table, negedge/latch, sub-module-
attributed table, contradiction, no-table, no-ports, sibling-owned cases deferred).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import waveform_ext_synth as X  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DS = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")
_HAVE_TOOLS = bool(shutil.which("iverilog") and shutil.which("vvp"))
_HAVE_DS = _DS.is_dir()


def _read(prob: str, suffix: str) -> str:
    return (_DS / f"{prob}_{suffix}").read_text()


def _host_score(prob: str, dut_text: str) -> int:
    """iverilog + vvp the DUT against the dataset ref+test; return mismatch count.
    AUTHORITATIVE per the task: 0 == clean. Raises on compile failure."""
    with tempfile.TemporaryDirectory() as d:
        dut = Path(d) / "dut.sv"
        dut.write_text(dut_text)
        vvp = Path(d) / "s.vvp"
        c = subprocess.run(
            ["iverilog", "-g2012", "-o", str(vvp), str(dut),
             str(_DS / f"{prob}_ref.sv"), str(_DS / f"{prob}_test.sv")],
            capture_output=True, text=True)
        assert c.returncode == 0, f"compile failed:\n{c.stderr}"
        r = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True)
        out = r.stdout
        import re
        m = re.search(r"Mismatches:\s*(\d+)\s+in\s+\d+\s+samples", out)
        if m:
            return int(m.group(1))
        # Fall back to the dataset harness's own "no mismatches" hint.
        if "Total mismatched samples is 0" in out:
            return 0
        raise AssertionError(f"could not parse mismatch count from:\n{out}")


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic in-test fixtures (no dataset / no tools required) — pin the envelope
# ─────────────────────────────────────────────────────────────────────────────

# Path 1 — combinational table, prose says "described by", NOT "combinational".
_COMB_BYCONSISTENCY = """
I would like you to implement a module named TopModule.

 - input  x
 - input  y
 - output z

The module can be described by the following simulation waveform:

  time  x  y  z
  0ns   0  0  1
  5ns   1  0  0
  10ns  0  1  0
  15ns  1  1  1
"""

# Path 2 — single posedge FF, prose says "sequential ... positive edge", NOT
# "observable through the output". q registers ~a.
_POSEDGE_1FF = """
I would like you to implement a module named TopModule.

 - input  clk
 - input  a
 - output q

This is a sequential circuit. Read the simulation waveforms to determine what
the circuit does, then implement it.

  time  clk a   q
  0ns   0   x   x
  5ns   1   0   x
  10ns  0   0   x
  15ns  1   0   1
  20ns  0   0   1
  25ns  1   1   1
  30ns  0   1   1
  35ns  1   1   0
  40ns  0   1   0

Assume all sequential logic is triggered on the positive edge of the clock.
"""


# ── POSITIVES (synthetic) ────────────────────────────────────────────────────
def test_path1_combinational_byconsistency_fires():
    rtl = X.synth(_COMB_BYCONSISTENCY, "TopModule")
    assert rtl is not None, "no-keyword combinational table must synthesize"
    assert "module TopModule" in rtl and "assign z" in rtl
    # z = XNOR: 1-rows are (x=0,y=0) and (x=1,y=1)
    assert "(~x & ~y)" in rtl and "(x & y)" in rtl
    assert "always" not in rtl  # combinational -> no clocked block


def test_path2_posedge_1ff_fires_nextstate_is_not_a():
    rtl = X.synth(_POSEDGE_1FF, "TopModule")
    assert rtl is not None, "general single-posedge-FF must synthesize"
    assert "always @(posedge clk)" in rtl
    assert "q <=" in rtl
    # next-state q = ~a: the a=0 edges -> q=1, the a=1 edges -> q=0  =>  q <= ~a
    assert "~a" in rtl


def test_sibling_owned_combinational_keyword_is_deferred():
    # If the literal word "combinational" is present, this module DEFERS (the
    # sibling owns it) -> None, so there is no double-fire / tie-steal.
    p = _COMB_BYCONSISTENCY.replace("can be described by the following",
                                    "is combinational and is described by the")
    assert X.synth(p, "TopModule") is None


def test_sibling_owned_observable_ff_is_deferred():
    p = _POSEDGE_1FF.replace(
        "This is a sequential circuit.",
        "One bit of memory has been made observable through the output q.")
    assert X.synth(p, "TopModule") is None


# ── §4.05 NO-LEAK NEGATIVES (≥4) — every one MUST return None ─────────────────
def test_negative_multibit_hex_value_column_skips():
    # Multi-bit decimal output column (Prob117-style counter) -> out of envelope.
    p = """
 - input  clk
 - input  a
 - output q (3 bits)

The module implements a sequential circuit. Read the waveforms.

  time  clk a   q
  0ns   0   1   x
  5ns   1   1   4
  10ns  0   1   4
  15ns  1   0   5
  20ns  0   0   5
"""
    assert X.synth(p, "TopModule") is None


def test_negative_negedge_clock_skips():
    p = _POSEDGE_1FF.replace("positive edge", "negative edge")
    assert X.synth(p, "TopModule") is None


def test_negative_submodule_attributed_table_skips():
    # The table describes a named SUB-module B, not the top (Prob131-style).
    p = """
Module A implements the boolean function z = (x^y) & x.

Module B can be described by the following simulation waveform:

  time  x  y  z
  0ns   0  0  1
  5ns   1  0  0
  10ns  0  1  0
  15ns  1  1  1

Now consider a top-level module with the following interface:

 - input  x
 - input  y
 - output z

The module is implemented with two A submodules and two B submodules ...
"""
    assert X.synth(p, "TopModule") is None


def test_negative_combinational_contradiction_skips():
    # Same input combo (x=0,y=0) -> two different outputs => not a clean function.
    p = _COMB_BYCONSISTENCY + "  20ns  0  0  0\n"
    assert X.synth(p, "TopModule") is None


def test_negative_no_table_skips():
    p = """
 - input  a
 - output q

The module is combinational-ish but there is no embedded waveform table here.
"""
    assert X.synth(p, "TopModule") is None


def test_negative_no_ports_skips():
    p = """
The module can be described by the following simulation waveform:

  time  x  y  z
  0ns   0  0  1
  5ns   1  1  1
"""
    assert X.synth(p, "TopModule") is None


def test_negative_state_dependent_nextstate_skips():
    # A toggle FF: next q depends on current q (not on inputs alone) -> the
    # inputs-alone map is inconsistent -> SKIP (out of the single-bit observable
    # envelope). q toggles every posedge regardless of a.
    p = """
 - input  clk
 - input  a
 - output q

This is a sequential circuit. Read the simulation waveforms.

  time  clk a   q
  0ns   0   0   0
  5ns   1   0   1
  10ns  0   0   1
  15ns  1   0   0
  20ns  0   0   0
  25ns  1   0   1
  30ns  0   0   1

Assume all sequential logic is triggered on the positive edge of the clock.
"""
    assert X.synth(p, "TopModule") is None


def test_negative_clock_column_in_combinational_path_skips():
    # A clock column present but no seq-idiom prose -> NOT a clean combinational
    # table; the combinational path must refuse it.
    p = """
 - input  clk
 - input  a
 - output q

The module can be described by the following simulation waveform:

  time  clk a   q
  0ns   0   0   1
  5ns   1   1   0
"""
    # No posedge edge pairing either -> both paths SKIP.
    assert X.synth(p, "TopModule") is None


# ── AUTHORITATIVE HOST-SCORE on the REAL dataset (the task's gate) ────────────
@pytest.mark.skipif(not (_HAVE_TOOLS and _HAVE_DS),
                    reason="iverilog/vvp + verilog-eval dataset required; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_real_prob083_fires_and_host_scores_clean():
    prob = "Prob083_mt2015_q4b"
    rtl = X.synth(_read(prob, "prompt.txt"), "TopModule")
    assert rtl is not None, "Prob083 must fire (combinational-by-consistency)"
    assert _host_score(prob, rtl) == 0


@pytest.mark.skipif(not (_HAVE_TOOLS and _HAVE_DS),
                    reason="iverilog/vvp + verilog-eval dataset required; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_real_prob098_fires_and_host_scores_clean():
    prob = "Prob098_circuit7"
    rtl = X.synth(_read(prob, "prompt.txt"), "TopModule")
    assert rtl is not None, "Prob098 must fire (general single-posedge-FF)"
    assert _host_score(prob, rtl) == 0


@pytest.mark.skipif(not _HAVE_DS, reason="verilog-eval dataset required; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
@pytest.mark.parametrize("prob", ["Prob117_circuit9", "Prob145_circuit8",
                                  "Prob131_mt2015_q4"])
def test_real_honest_skip_members(prob):
    # Prob117 (multi-bit counter) + Prob145 (negedge + latch) are honestly SKIPped;
    # Prob131 (sub-module-attributed table) is the no-leak suppression.
    assert X.synth(_read(prob, "prompt.txt"), "TopModule") is None


@pytest.mark.skipif(not _HAVE_DS, reason="verilog-eval dataset required; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_real_no_overlap_with_sibling_fires():
    # The companion must NOT steal anything the canonical sibling already handles.
    import waveform_truth_table_synth as W
    for pf in sorted(_DS.glob("*_prompt.txt")):
        prompt = pf.read_text()
        if W.synth(prompt, "TopModule") is not None:
            assert X.synth(prompt, "TopModule") is None, (
                f"{pf.name}: ext fired on a sibling-owned case (tie-steal)")
