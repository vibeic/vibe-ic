"""v1.1.76 — mealy_sequence_synth deterministic SOLVER (bucket-② -> bucket-①).

The Mealy twin of full_moore_fsm_synth. A fully-specified MEALY machine — output a
function of (state, input) — is mechanical to emit; a blind author only adds
single-shot variance. Two written forms:

  (a) Mealy transition+output table  `state --in=V (out=V)--> next`  (the output
      annotation sits on the TRANSITION — Prob088_ece241_2014_q5b, 2's complementer).
  (b) stated target sequence + stated overlap semantics + a Mealy pulse output, built
      as the standard KMP prefix-matching automaton (Prob129_ece241_2013_q8, "101").

Real proof of correctness (host scorer, when the dataset is present): both targets
program-generated → 0 mismatches.

§4.05 load-bearing half (≥5 negatives below): SKIP on a Moore-named prompt (never
steal the Moore solver's problem), an incomplete table, an unstated overlap, an
unstated reset, a latched 'forever' output, a multi-bit non-clk/reset port, or a
non-FSM prompt — never guessing.
"""
import shutil
import subprocess
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import mealy_sequence_synth as M  # noqa: E402
import full_moore_fsm_synth as F  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

import pytest

#: The repo's existing tool gate (197 files use this shape). Without
#: it this module raises FileNotFoundError on a host that lacks the
#: tool, instead of disclosing a skip.
_HAVE_TOOLS = bool(shutil.which("iverilog") and shutil.which("vvp"))

_DS = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")

_HDR = (
    "I would like you to implement a module named TopModule with the following\n"
    "interface. All input and output ports are one bit unless otherwise specified.\n\n")

# ---- FORM (a) positive: a complete Mealy transition+output table -------------
MEALY_TABLE = _HDR + (
    " - input  clk\n - input  areset\n - input  x\n - output z\n\n"
    "The module should implement the following Mealy finite-state machine.\n"
    "Resets into state A and reset is asynchronous active-high.\n\n"
    "  A --x=0 (z=0)--> A\n"
    "  A --x=1 (z=1)--> B\n"
    "  B --x=0 (z=1)--> B\n"
    "  B --x=1 (z=0)--> B\n\n"
    "Assume all sequential logic is triggered on the positive edge of the clock.\n")

# ---- FORM (b) positive: stated sequence, overlapping, Mealy ------------------
MEALY_SEQ = _HDR + (
    " - input  clk\n - input  aresetn\n - input  x\n - output z\n\n"
    "The module should implement a Mealy-type finite state machine that recognizes\n"
    'the sequence "101" on an input signal named x. z is asserted to logic-1 when\n'
    "the \"101\" sequence is detected. Negative edge triggered asynchronous reset.\n"
    "Your FSM should recognize overlapping sequences. Assume all sequential logic\n"
    "is triggered on the positive edge of the clock.\n")


# --------------------------------------------------------------------------- #
def _compiles(rtl, tmp_path):
    if not _HAVE_TOOLS:
        pytest.skip("iverilog/vvp not installed on this host")
    f = tmp_path / "m.sv"
    f.write_text(rtl)
    cp = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "a.out"), str(f)],
                        capture_output=True, text=True)
    return cp.returncode == 0, cp.stderr


def _host_score(prob, tmp_path):
    """Emit from the real prompt, compile vs ref+test, return mismatch count (int)
    or None when the dataset isn't present / the problem doesn't emit."""
    if not _HAVE_TOOLS:
        pytest.skip("iverilog/vvp not installed on this host")
    pr = _DS / f"{prob}_prompt.txt"
    rf = _DS / f"{prob}_ref.sv"
    ts = _DS / f"{prob}_test.sv"
    if not (pr.is_file() and rf.is_file() and ts.is_file()):
        return None
    rtl = M.synth(pr.read_text(errors="replace"), "TopModule")
    if not rtl:
        return None
    dut = tmp_path / "dut.sv"
    dut.write_text(rtl)
    vvp = tmp_path / "sim.vvp"
    cp = subprocess.run(["iverilog", "-g2012", "-o", str(vvp), str(dut), str(rf), str(ts)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, f"compile failed: {cp.stderr}"
    run = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True)
    out = run.stdout + run.stderr
    import re
    m = re.search(r"Mismatches:\s*(\d+)\s+in", out)
    if m:
        return int(m.group(1))
    m = re.search(r"Total mismatched samples is\s*(\d+)", out)
    return int(m.group(1)) if m else None


# ============================== POSITIVES ================================== #
def test_form_a_table_fires_and_compiles(tmp_path):
    rtl = M.synth(MEALY_TABLE, "TopModule")
    assert rtl is not None
    ok, err = _compiles(rtl, tmp_path)
    assert ok, err
    # Mealy output: z depends on the INPUT, not state alone
    assert "z = x ?" in rtl
    # async active-high reset edge
    assert "posedge clk or posedge areset" in rtl
    assert "if (areset)" in rtl


def test_form_a_output_cells_are_mealy():
    # the 2's-complementer table: state A outputs z=x (A:0->0,1->1), state B z=~x
    rtl = M.synth(MEALY_TABLE, "TopModule")
    assert "S_A: z = x ? 1'b1 : 1'b0;" in rtl
    assert "S_B: z = x ? 1'b0 : 1'b1;" in rtl


def test_form_b_sequence_fires_and_compiles(tmp_path):
    rtl = M.synth(MEALY_SEQ, "TopModule")
    assert rtl is not None
    ok, err = _compiles(rtl, tmp_path)
    assert ok, err
    # KMP "101" automaton: 3 prefix states, neg-edge async reset
    assert "posedge clk or negedge aresetn" in rtl
    assert "if (!aresetn)" in rtl
    # the match completes in the longest-prefix state on the final bit -> z = x there
    assert "S_P2: z = x ? 1'b1 : 1'b0;" in rtl


def test_form_b_sequence_kmp_overlap_transitions():
    # "101" overlapping: P0-1->P1, P1-1->P1/0->P2, P2-1->P1(match,overlap)/0->P0
    rtl = M.synth(MEALY_SEQ, "TopModule")
    assert "S_P0: nstate = x ? S_P1 : S_P0;" in rtl
    assert "S_P1: nstate = x ? S_P1 : S_P2;" in rtl
    assert "S_P2: nstate = x ? S_P1 : S_P0;" in rtl


def test_form_b_nonoverlapping_changes_post_match():
    # non-overlapping "1010" restarts at state 0 after a match, whereas overlapping
    # reuses the "10" suffix (f[4]=2) — a self-overlapping pattern makes the two
    # semantics produce DIFFERENT automata, proving the overlap flag is load-bearing.
    base = (_HDR + " - input  clk\n - input  reset\n - input  x\n - output z\n\n"
            "Implement a Mealy-type FSM that detects the sequence \"1010\". Reset is\n"
            "active high synchronous. Assume all sequential logic is triggered on\n"
            "the positive edge of the clock. ")
    ov = M.synth(base + "Recognize overlapping sequences.\n", "TopModule")
    nov = M.synth(base + "It must be non-overlapping.\n", "TopModule")
    assert ov is not None and nov is not None
    assert ov != nov   # overlap semantics actually change the emitted automaton
    # non-overlapping: the match state (P3) restarts at P0 on the completing bit '0'
    assert "S_P3: nstate = x ? S_P1 : S_P0;" in nov


# ====================== §4.05 NEGATIVES (≥5) ============================== #
def test_skip_moore_named_prompt():
    # NEG-1: a "Moore-type" prompt belongs to the Moore solver — never steal it.
    p = MEALY_SEQ.replace("Mealy-type", "Moore-type")
    assert M.synth(p, "TopModule") is None


def test_skip_incomplete_mealy_table():
    # NEG-2: drop one arrow -> state A is missing its x=1 transition -> SKIP.
    p = MEALY_TABLE.replace("  A --x=1 (z=1)--> B\n", "")
    assert M.synth(p, "TopModule") is None


def test_skip_unstated_overlap():
    # NEG-3: a stated sequence with NO overlapping / non-overlapping statement -> SKIP.
    p = MEALY_SEQ.replace("Your FSM should recognize overlapping sequences. ", "")
    assert M.synth(p, "TopModule") is None


def test_skip_unstated_reset():
    # NEG-4: remove the sync/async + level statement -> reset under-specified -> SKIP.
    p = MEALY_TABLE.replace(
        "Resets into state A and reset is asynchronous active-high.\n", "")
    assert M.synth(p, "TopModule") is None


def test_skip_latched_forever_output():
    # NEG-5: 'set ... to 1, forever, until reset' is a Moore-style LATCHED recognizer,
    # not a Mealy pulse (Prob096_review2015_fsmseq) -> SKIP, not this family.
    p = (_HDR + " - input  clk\n - input  reset\n - input  data\n - output q\n\n"
         "Implement a Mealy finite-state machine that searches for the sequence 1101.\n"
         "When the sequence is found, set q to 1, forever, until reset. Reset is\n"
         "active high synchronous. Recognize overlapping sequences. Assume all\n"
         "sequential logic is triggered on the positive edge of the clock.\n")
    assert M.synth(p, "TopModule") is None


def test_skip_multibit_extra_port():
    # NEG-6: an extra multi-bit input would be silently dropped -> SKIP.
    p = MEALY_TABLE.replace(" - input  x\n", " - input  x\n - input  d (4 bits)\n")
    assert M.synth(p, "TopModule") is None


def test_skip_non_fsm_prompt():
    # NEG-7: a plain combinational/non-FSM prompt -> SKIP.
    p = (_HDR + " - input  a\n - input  b\n - output y\n\n"
         "Implement a 2-input AND gate: y = a & b.\n")
    assert M.synth(p, "TopModule") is None


def test_skip_unquoted_lone_bit_not_a_sequence():
    # NEG-8: a Mealy prompt that mentions logic-'1' but states NO multi-bit target
    # sequence must not invent one -> SKIP (no fabricated pattern).
    p = (_HDR + " - input  clk\n - input  reset\n - input  x\n - output z\n\n"
         "Implement a Mealy-type FSM. z is asserted to logic-1 sometimes. Reset is\n"
         "active high synchronous. Recognize overlapping sequences. Assume all\n"
         "sequential logic is triggered on the positive edge of the clock.\n")
    assert M.synth(p, "TopModule") is None


# ===================== NO-LEAK vs the Moore solver ======================== #
def test_does_not_steal_any_moore_solver_fire():
    """Every prompt the Moore solver fires on, the Mealy solver MUST skip."""
    if not _DS.is_dir():
        import pytest
        pytest.skip("dataset not present")
    stolen = []
    for pf in sorted(_DS.glob("*_prompt.txt")):
        txt = pf.read_text(errors="replace")
        if F.synth(txt, "TopModule") and M.synth(txt, "TopModule"):
            stolen.append(pf.name)
    assert not stolen, f"Mealy solver stole Moore problems: {stolen}"


# ===================== HOST-SCORE the real targets ======================= #
def test_host_score_prob088_zero_mismatch(tmp_path):
    n = _host_score("Prob088_ece241_2014_q5b", tmp_path)
    if n is None:
        import pytest
        pytest.skip("dataset not present / no emit")
    assert n == 0, f"Prob088 host mismatches: {n}"


def test_host_score_prob129_zero_mismatch(tmp_path):
    n = _host_score("Prob129_ece241_2013_q8", tmp_path)
    if n is None:
        import pytest
        pytest.skip("dataset not present / no emit")
    assert n == 0, f"Prob129 host mismatches: {n}"


def test_corpus_fire_list_is_exactly_two(tmp_path):
    """No-leak: across the whole corpus the solver fires on exactly the 2 known
    Mealy targets — every other prompt SKIPs."""
    if not _DS.is_dir():
        import pytest
        pytest.skip("dataset not present")
    fires = sorted(pf.name.replace("_prompt.txt", "")
                   for pf in _DS.glob("*_prompt.txt")
                   if M.synth(pf.read_text(errors="replace"), "TopModule"))
    assert fires == ["Prob088_ece241_2014_q5b", "Prob129_ece241_2013_q8"], fires
