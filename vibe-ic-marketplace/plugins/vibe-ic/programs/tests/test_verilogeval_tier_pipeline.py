#!/usr/bin/env python3
"""Tests for verilogeval_tier_pipeline.py + moore_arrow_fsm_synth.py.

Pins:
  * the gate/classification logic (positive + §4.05 negative — no false-reject,
    no demanded-unstated-fact, no over-broad emit),
  * the iverilog verdict logic (the TIMEOUT-watchdog must NOT false-floor a passing
    run; a degenerate 0-sample run is not a pass),
  * the arrow-Moore-FSM solver envelope (emits the right machine; SKIPs every out-
    of-envelope spec).

The iverilog-dependent end-to-end checks are SKIPPED automatically when iverilog
is not installed or the VerilogEval dataset is not present, so the suite stays
green on a host without either.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import verilogeval_tier_pipeline as P   # noqa: E402
import moore_arrow_fsm_synth as M       # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DATASET = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")
_HAVE_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_HAVE_DATASET = _DATASET.is_dir()

_needs_iv = pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
_needs_ds = pytest.mark.skipif(not _HAVE_DATASET, reason="VerilogEval dataset absent; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")


# Arrow-Moore-FSM prompt fixtures (self-contained — no dataset needed).
_PROB136_PROMPT = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  clk
 - input  reset
 - input  w
 - output z

The module should implement the state machine shown below:

  A (0) --0--> B
  A (0) --1--> A
  B (0) --0--> C
  B (0) --1--> D
  C (0) --0--> E
  C (0) --1--> D
  D (0) --0--> F
  D (0) --1--> A
  E (1) --0--> E
  E (1) --1--> D
  F (1) --0--> C
  F (1) --1--> D

Assume all sequential logic is triggered on the positive edge of the
clock.
"""

# An ASYNCHRONOUS-reset arrow FSM — OUT of envelope (solver emits sync only).
_ASYNC_PROMPT = _PROB136_PROMPT.replace(" - input  reset", " - input  areset") + \
    "\nIt should asynchronously reset into state A.\n"

# A non-FSM combinational prompt — must SKIP.
_NOTGATE_PROMPT = """
I would like you to implement a module named TopModule.
 - input  in
 - output out
The module should implement a NOT gate.
"""


# --------------------------------------------------------------------------- #
# moore_arrow_fsm_synth — positive + §4.05 negative
# --------------------------------------------------------------------------- #
def test_arrow_fsm_emits_for_complete_arrow_diagram():
    rtl = M.synth(_PROB136_PROMPT, "TopModule")
    assert rtl is not None
    assert "module TopModule" in rtl
    # Moore output: z high only in states E,F (the two `(1)` states).
    assert "state == E" in rtl and "state == F" in rtl
    # synchronous reset to the first/leftmost state A.
    assert "posedge clk" in rtl
    assert "if (reset)" in rtl and "state <= A" in rtl
    # transition: from A, input 1 -> A, input 0 -> B.
    assert "A: next = w ? A : B;" in rtl


def test_arrow_fsm_skips_async_reset():
    # §4.05: an asynchronous-reset spec is out of the sync-only envelope.
    assert M.synth(_ASYNC_PROMPT, "TopModule") is None


def test_arrow_fsm_skips_non_fsm():
    assert M.synth(_NOTGATE_PROMPT, "TopModule") is None


def test_arrow_fsm_skips_when_arrows_incomplete():
    # Drop two arrow lines so not every (state,input) is covered -> SKIP.
    lines = _PROB136_PROMPT.splitlines()
    trimmed = "\n".join(l for l in lines if "F (1) --" not in l)
    assert M.synth(trimmed, "TopModule") is None


def test_arrow_fsm_honors_explicit_reset_state():
    prompt = _PROB136_PROMPT + "\nResets into state D.\n"
    rtl = M.synth(prompt, "TopModule")
    assert rtl is not None
    # explicit reset sentence overrides the first-state convention.
    assert "state <= D" in rtl


# --------------------------------------------------------------------------- #
# gate construction + gate_check — positive + §4.05 negative
# --------------------------------------------------------------------------- #
def _gate_for(ports, module="TopModule", fsm_states=None):
    spec = {"module_name": module, "ports": ports,
            "structures": {"fsm_states": fsm_states or []}}
    return P.build_gate(spec)


def test_gate_check_accepts_conformant_header():
    gate = _gate_for([{"name": "in", "dir": "input", "width": 1},
                      {"name": "out", "dir": "output", "width": 1}])
    rtl = "module TopModule(input in, output out); assign out=~in; endmodule"
    res = P.gate_check(gate, rtl)
    assert res["pass"], res["violations"]


def test_gate_check_rejects_wrong_module_name():
    gate = _gate_for([{"name": "out", "dir": "output", "width": 1}])
    rtl = "module Wrong(output out); assign out=0; endmodule"
    res = P.gate_check(gate, rtl)
    assert not res["pass"]
    assert any(v["kind"] == "module_name" for v in res["violations"])


def test_gate_check_rejects_missing_and_wrong_width_port():
    gate = _gate_for([{"name": "a", "dir": "input", "width": 3},
                      {"name": "y", "dir": "output", "width": 3}])
    rtl = "module TopModule(input [1:0] a); endmodule"  # wrong width, missing y
    res = P.gate_check(gate, rtl)
    kinds = {v["kind"] for v in res["violations"]}
    assert "port_width" in kinds
    assert "missing_port" in kinds


def test_gate_check_does_not_demand_unstated_width():
    # §4.05: a spec port whose width is None (unresolved) must NOT be width-checked.
    gate = _gate_for([{"name": "d", "dir": "input", "width": None}])
    rtl = "module TopModule(input [7:0] d); endmodule"
    res = P.gate_check(gate, rtl)
    assert not any(v["kind"] == "port_width" for v in res["violations"])


def test_gate_check_allows_extra_candidate_ports():
    # §4.05: candidate may carry ports the spec did not list (e.g. clk).
    gate = _gate_for([{"name": "out", "dir": "output", "width": 1}])
    rtl = "module TopModule(input clk, output out); endmodule"
    assert P.gate_check(gate, rtl)["pass"]


def test_gate_check_no_module_header():
    gate = _gate_for([{"name": "out", "dir": "output", "width": 1}])
    res = P.gate_check(gate, "// no module here")
    assert not res["pass"]
    assert res["violations"][0]["kind"] == "no_module"


# --------------------------------------------------------------------------- #
# iverilog verdict logic — the TIMEOUT watchdog must NOT false-floor a pass
# --------------------------------------------------------------------------- #
class _FakeRun:
    def __init__(self, stdout):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


def _score_with_output(monkeypatch, sim_output):
    """Drive iverilog_score with a fabricated vvp stdout (compile always OK)."""
    import subprocess

    def fake_run(cmd, **kw):
        if cmd and cmd[0] == "iverilog":
            return _FakeRun("")            # compile OK
        return _FakeRun(sim_output)        # vvp output
    monkeypatch.setattr(subprocess, "run", fake_run)
    prob = P.Problem(Path("/tmp/_x_prompt.txt"))
    # ref/test paths don't need to exist — subprocess.run is faked.
    return P.iverilog_score(prob, "module TopModule(output o); assign o=0; endmodule")


def test_verdict_timeout_watchdog_with_zero_mismatches_is_pass(monkeypatch):
    # The real bug: a passing run also prints the `#1000000 $display("TIMEOUT")`
    # watchdog. `Mismatches: 0` is authoritative -> PASS.
    out = ("TIMEOUT\n"
           "Hint: Output 'q' has no mismatches.\n"
           "Mismatches: 0 in 200000 samples\n")
    ok, detail = _score_with_output(monkeypatch, out)
    assert ok, detail


def test_verdict_nonzero_mismatch_is_fail(monkeypatch):
    ok, detail = _score_with_output(monkeypatch, "Mismatches: 5 in 200 samples\n")
    assert not ok
    assert "5" in detail


def test_verdict_no_verdict_line_is_fail(monkeypatch):
    # A genuine hang prints TIMEOUT but NEVER reaches the `final` Mismatches line.
    ok, detail = _score_with_output(monkeypatch, "TIMEOUT\n")
    assert not ok


def test_verdict_zero_samples_is_not_pass(monkeypatch):
    ok, detail = _score_with_output(monkeypatch, "Mismatches: 0 in 0 samples\n")
    assert not ok
    assert "0 samples" in detail


# --------------------------------------------------------------------------- #
# spec extraction — interface from the prompt bullets
# --------------------------------------------------------------------------- #
def test_named_module_is_topmodule_not_prose_artifact():
    # §4.05 gate-quality: "a module named TopModule" must extract module_name
    # `TopModule`, NOT the prose word `named` (which would false-reject a correct
    # TopModule candidate at the gate).
    assert P._named_module("implement a module named TopModule with") == "TopModule"
    assert P._named_module("module TopModule (\n  input a\n);") == "TopModule"
    assert P._named_module("no module name here at all") is None


@_needs_ds
def test_every_problem_gate_requires_topmodule():
    for p in P.discover(str(_DATASET)):
        spec = P.extract_spec(p)
        assert spec["module_name"] == "TopModule", p.stem


@_needs_ds
def test_extract_spec_recovers_interface():
    probs = {p.stem: p for p in P.discover(str(_DATASET))}
    p = probs["Prob044_vectorgates"]
    spec = P.extract_spec(p)
    names = {x["name"] for x in spec["ports"]}
    assert {"a", "b", "out_or_bitwise", "out_not"} <= names
    widths = {x["name"]: x["width"] for x in spec["ports"]}
    assert widths["a"] == 3 and widths["out_not"] == 6


# --------------------------------------------------------------------------- #
# end-to-end (iverilog + dataset) — the load-bearing verified claims
# --------------------------------------------------------------------------- #
@_needs_iv
@_needs_ds
def test_prob136_arrow_fsm_emit_passes_official_test():
    probs = {p.stem: p for p in P.discover(str(_DATASET))}
    p = probs["Prob136_m2014_q6"]
    rtl = M.synth(p.prompt_text, "TopModule")
    assert rtl is not None
    ok, detail = P.iverilog_score(p, rtl)
    assert ok, f"arrow-FSM emit must pass the official test: {detail}"


@_needs_iv
@_needs_ds
def test_prob136_classifies_tier1_with_verify():
    probs = {p.stem: p for p in P.discover(str(_DATASET))}
    assert P.classify(probs["Prob136_m2014_q6"], verify=True) == P.TIER_PROGRAM


@_needs_iv
@_needs_ds
def test_prob099_is_the_genuine_floor():
    # The golden ref declares Y1/Y3 but the testbench binds Y2/Y4 -> the golden
    # cannot compile against its own test -> a genuine Tier5 floor.
    probs = {p.stem: p for p in P.discover(str(_DATASET))}
    why = P.floor_evidence(probs["Prob099_m2014_q6c"])
    assert why is not None
    assert "fails its OWN" in why
    assert P.classify(probs["Prob099_m2014_q6c"], verify=True) == P.TIER_FLOOR


@_needs_iv
@_needs_ds
def test_sound_problem_is_not_a_floor():
    # A clean problem's golden passes its own test -> NOT a floor.
    probs = {p.stem: p for p in P.discover(str(_DATASET))}
    assert P.floor_evidence(probs["Prob005_notgate"]) is None


@_needs_iv
@_needs_ds
def test_timeout_watchdog_problem_is_not_a_floor():
    # Prob082/141/156 print the benign TIMEOUT watchdog yet score Mismatches:0.
    # They must NOT be floors (regression for the verdict fix).
    probs = {p.stem: p for p in P.discover(str(_DATASET))}
    for stem in ("Prob082_lfsr32", "Prob141_count_clock",
                 "Prob156_review2015_fancytimer"):
        assert P.floor_evidence(probs[stem]) is None, stem


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
