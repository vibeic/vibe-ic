"""v1.1.85 — RTLLM-prose FSM-detector dialect FOLDED into the two canonical solvers.

mealy_sequence_synth.synth and behavioral_fsm_synth.synth now try their NATIVE
VE-phrasing forms FIRST (byte-identical) and only fall through to a GATED RTLLM-prose
dialect that reads ports through rtllm_port_bridge and recognizes:

  * mealy_sequence_synth: the RTLLM `fsm` Mealy detector of a STATED bit sequence
    ("When the input is 10011, output MATCH is 1") -> KMP/overlap Mealy automaton,
    output asserted on the (state,input) that completes the target.
  * behavioral_fsm_synth: the RTLLM `sequence_detector` Moore detector of a STATED
    4-bit sequence (1001) with `reset_n` (active-low via `_n`). GENERAL latch rule:
    "forever / until reset" -> ABSORBING accept state; else ordinary OVERLAPPING.

The dialect is GATED to the structured-prose form (REQUIRES a literal "Module name:"
+ "Input ports:" header) so it never re-fires on a VE bullet prompt. Every dialect
fact is PARSED from the prose; an unstated sequence/reset SKIPs (§4.05). No design-name
keys. Host-verify is GATED on iverilog + the RTLLM dataset; the structural + negative
assertions run anywhere.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import mealy_sequence_synth as M  # noqa: E402
import behavioral_fsm_synth as B  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_HAVE_IV = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_RT = corpus_path("_extbench/RTLLM/Control/Finite State Machine")
_VE = str(corpus_path("_extbench/verilog-eval"))


# A synthetic RTLLM-prose Mealy detector (different sequence from the real one, so
# the test proves the machine is BUILT FROM THE PROSE, not a hardcoded automaton).
def _mealy_prose(seq, rst_name="RST", rst_prose=""):
    return (
        "Please act as a professional verilog designer.\n\n"
        f"Implement a Mealy FSM detection circuit that detects a single-bit input IN.\n"
        f"When the input is {seq}, output MATCH is 1, and MATCH is 0 in other cases.\n"
        "Support for continuous input and loop detection.\n\n"
        "Module name:\n    fsm\n"
        "Input ports:\n"
        "    IN: Input signal to the FSM.\n"
        "    CLK: Clock signal used for synchronous operation.\n"
        f"    {rst_name}: Reset signal to initialize the FSM. {rst_prose}\n"
        "Output ports:\n"
        "    MATCH: Output signal indicating a match condition.\n")


def _moore_prose(seq, rst_name="reset_n", forever=False):
    tail = ("Once the sequence is found, set sequence_detected to 1, forever, "
            "until reset.\n") if forever else ""
    return (
        "Please act as a professional Verilog designer.\n\n"
        f"Implement a module of a sequence detector to detect a specific "
        f"{len(seq)}-bit binary sequence {seq}.\n\n"
        "Module name:\n    sequence_detector\n\n"
        "Input ports:\n"
        "    clk: Clock signal to synchronize the detector.\n"
        f"    {rst_name}: Reset signal to initialize the state machine.\n"
        "    data_in: 1-bit binary input signal to feed the bitstream.\n\n"
        "Output ports:\n"
        "    sequence_detected: 1-bit output set high when the sequence is detected.\n"
        f"{tail}")


# ============================ DIALECT POSITIVES ============================= #
def test_mealy_dialect_fires_and_is_mealy():
    rtl = M.synth(_mealy_prose("10011"), "fsm")
    assert rtl is not None
    assert "module fsm(" in rtl            # binds to the prose Module name:
    # Mealy: output depends on the INPUT (asserted on the completing bit).
    assert "MATCH = IN ?" in rtl
    # async active-high reset (RST), KMP for 10011: accept on P4 with IN=1.
    assert "posedge CLK or posedge RST" in rtl
    assert "S_P4: MATCH = IN ? 1'b1 : 1'b0;" in rtl


def test_moore_dialect_fires_overlapping_nonabsorbing():
    rtl = B.synth(_moore_prose("1001"), "sequence_detector")
    assert rtl is not None
    assert "module sequence_detector(" in rtl
    # Moore: output a function of STATE only.
    assert "assign sequence_detected = (state == ACCEPT);" in rtl
    # active-low reset (reset_n -> canonical rst_n binding for the TB).
    assert "input rst_n" in rtl and "negedge rst_n" in rtl and "if (!rst_n)" in rtl
    # OVERLAPPING: accept state 4 is NON-absorbing (steps to 1/2, not self-loop).
    assert "3'd4: nstate = data_in ? 3'd1 : 3'd2;" in rtl


# ===================== GENERAL (not hardcoded) =========================== #
def test_mealy_different_sequence_emits_that_sequence():
    # "101" (a different, self-overlapping target) must build ITS automaton, not a
    # hardcoded 10011 machine. KMP("101") overlapping: P0,P1,P2; accept on P2 in=1.
    rtl = M.synth(_mealy_prose("101"), "fsm")
    assert rtl is not None
    assert "S_P2: MATCH = IN ? 1'b1 : 1'b0;" in rtl     # completes on the final '1'
    assert "S_P0:" in rtl and "S_P1:" in rtl and "S_P2:" in rtl
    assert "S_P3:" not in rtl                            # only len(101)=3 states
    # and it differs from the 10011 machine -> built from the prose, not hardcoded.
    assert rtl != M.synth(_mealy_prose("10011"), "fsm")


def test_mealy_one_to_zero_to_one_distinct_machine():
    # a "1 to 0 to 1" / "101" prompt emits THAT detector, distinct from "110".
    a = M.synth(_mealy_prose("101"), "fsm")
    b = M.synth(_mealy_prose("110"), "fsm")
    assert a is not None and b is not None and a != b


def test_moore_active_low_reset_emits_negedge():
    # an `_n`-suffixed reset name -> active-low -> negedge / !rst edge, PARSED.
    rtl = B.synth(_moore_prose("1001", rst_name="reset_n"), "sequence_detector")
    assert "negedge rst_n" in rtl and "if (!rst_n)" in rtl


def test_mealy_active_low_reset_from_n_suffix():
    rtl = M.synth(_mealy_prose("1011", rst_name="rst_n"), "fsm")
    assert rtl is not None
    assert "negedge rst_n" in rtl and "if (!rst_n)" in rtl


def test_moore_latched_forever_is_absorbing():
    # the GENERAL latch rule: "forever / until reset" -> ABSORBING accept (self-loop).
    rtl = B.synth(_moore_prose("1001", forever=True), "sequence_detector")
    assert rtl is not None
    # accept state 4 self-loops on BOTH inputs (latched, never leaves before reset).
    assert "3'd4: nstate = data_in ? 3'd4 : 3'd4;" in rtl


# ============================ §4.05 NEGATIVES ============================== #
def test_skip_unstated_sequence():
    # an RTLLM-prose detector with NO stated binary target sequence -> SKIP.
    p = (_mealy_prose("10011")
         .replace("When the input is 10011, output MATCH is 1, and MATCH is 0 "
                  "in other cases.", "It detects a sequence on IN."))
    assert M.synth(p, "fsm") is None


def test_skip_two_distinct_sequences_ambiguous():
    p = _mealy_prose("10011").replace(
        "Support for continuous input and loop detection.",
        "It also detects the sequence 1101.")
    assert M.synth(p, "fsm") is None


def test_dialect_gate_requires_structured_headers():
    # a VE-bullet prompt (no "Module name:"/"Input ports:" header) never reaches the
    # dialect -> the native path SKIPs it and the dialect does NOT re-fire.
    ve = (" - input  clk\n - input  reset\n - input  x\n - output z\n\n"
          "Implement a Mealy FSM. When the input is 10011, output z is 1.\n")
    assert M.synth(ve, "TopModule") is None          # no headers -> dialect gate shut
    ve2 = (" - input  clk\n - input  rst_n\n - input  data_in\n"
           " - output sequence_detected\n\n"
           "Detect the sequence 1001.\n")
    assert B.synth(ve2, "TopModule") is None


def test_moore_dialect_skips_mealy_named_prose():
    # a Mealy-named structured prompt is the Mealy family's, not the Moore solver's.
    p = _moore_prose("1001").replace(
        "Implement a module of a sequence detector",
        "Implement a Mealy module of a sequence detector")
    assert B.synth(p, "sequence_detector") is None


def test_mealy_dialect_skips_moore_named_prose():
    p = _mealy_prose("10011").replace(
        "Implement a Mealy FSM detection circuit",
        "Implement a Moore FSM detection circuit")
    assert M.synth(p, "fsm") is None


# =================== NATIVE VE PATH BYTE-IDENTICAL ======================== #
def test_native_ve_fire_sets_unchanged():
    # Across the VE corpus the native solvers fire on EXACTLY their known
    # targets, including the directional bump/fall family added after the
    # detector-fold dialect, and NO VE prompt opens the dialect header gate.
    import glob
    import os
    base = Path(_VE)
    if not base.is_dir():
        pytest.skip("VE dataset not present")
    m_fire, b_fire, gate_open = set(), set(), set()
    for ds in ("dataset_code-complete-iccad2023", "dataset_spec-to-rtl"):
        d = base / ds
        if not d.is_dir():
            continue
        for pf in glob.glob(os.path.join(str(d), "*_prompt.txt")):
            t = Path(pf).read_text(errors="replace")
            nm = os.path.basename(pf).replace("_prompt.txt", "")
            if M.synth(t, "TopModule"):
                m_fire.add(nm)
            if B.synth(t, "TopModule"):
                b_fire.add(nm)
            if (M._DIA_MODNAME_RE.search(t) and M._DIA_INPORTS_RE.search(t)):
                gate_open.add(nm)
    assert m_fire == {"Prob088_ece241_2014_q5b", "Prob129_ece241_2013_q8"}, m_fire
    assert b_fire == {"Prob095_review2015_fsmshift",
                      "Prob096_review2015_fsmseq",
                      "Prob142_lemmings2"}, b_fire
    assert gate_open == set(), gate_open    # the dialect gate never opens on VE


# ===================== HOST-SCORE the RTLLM targets ====================== #
def _host_pass(synmod, design, top):
    d = _RT / design
    if not (d / "design_description.txt").is_file():
        pytest.skip("RTLLM dataset not present")
    rtl = synmod.synth((d / "design_description.txt").read_text(errors="replace"), top)
    assert rtl is not None, "dialect did not fire on the RTLLM prose"
    with tempfile.TemporaryDirectory() as td:
        dut = Path(td) / f"{top}.v"
        dut.write_text(rtl)
        vvp = Path(td) / "a.vvp"
        ce = subprocess.run(["iverilog", "-g2012", "-o", str(vvp),
                             "testbench.v", str(dut)],
                            capture_output=True, text=True, cwd=str(d))
        assert ce.returncode == 0, ce.stderr[:300]
        r = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True,
                           timeout=60, cwd=str(d))
        assert "passed" in (r.stdout + r.stderr).lower(), (r.stdout + r.stderr)[:300]


@pytest.mark.skipif(not _HAVE_IV, reason="iverilog not installed")
def test_host_fsm_mealy_passes():
    _host_pass(M, "fsm", "fsm")


@pytest.mark.skipif(not _HAVE_IV, reason="iverilog not installed")
def test_host_sequence_detector_moore_passes():
    _host_pass(B, "sequence_detector", "sequence_detector")
