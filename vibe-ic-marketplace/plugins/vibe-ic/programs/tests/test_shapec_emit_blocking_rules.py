"""ORGANIC-20260605-shapec-existing-guards-nonblocking regression tests.

Pins (a) the two corpus-swept rule TIGHTENINGS in spec_conformance_check and
(b) the Shape-C harness emit-blocking wiring in gates_atomic.py.

Corpus-sweep doctrine: the rules were promoted to emit-blocking ONLY after the
sweep over all 305 prior-PASSING samples of both 156-problem atomic suites came
back zero false fires — which required the tightenings pinned here. The third
candidate (vector-self-shift-fold) was NOT promoted: passing solutions
legitimately use the idiom it flags.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import spec_conformance_check as scc  # noqa: E402
from _specrtl_common import Port, extract_spec_contract, parse_rtl_ports, strip_comments  # noqa: E402

HARNESS = Path(__file__).resolve().parent.parent.parent / "benchmark-harness"
GATES = HARNESS / "gates_atomic.py"


# ── onebased-port-range tightenings ──────────────────────────────────────

_PORTS_X4 = [Port(name="x", direction="input", width=4)]
_RTL_X4 = "module TopModule(input [3:0] x, output f);\n  assign f = x[0];\nendmodule"


def test_onebased_true_positive_still_fires():
    spec = "The K-map below is indexed by x[1], x[2], x[3], x[4]."
    assert scc._onebased_index_warnings(spec, _RTL_X4, _PORTS_X4) == [("x", 4, 4)]


def test_onebased_assumed_zero_boundary_excluded():
    # rule90/rule110 shape: "(q[-1] and q[512]) are both zero (off)"
    ports = [Port(name="q", direction="output", width=512)]
    rtl = "module TopModule(output [511:0] q);\nendmodule"
    spec = "The boundary cells (q[-1] and q[512]) are both zero (off)."
    assert scc._onebased_index_warnings(spec, rtl, ports) == []


def test_onebased_not_needed_boundary_excluded():
    # human gatesv shape: "we don't need to know out_both[3]."
    ports = [Port(name="out_both", direction="output", width=3)]
    rtl = "module TopModule(output [2:0] out_both);\nendmodule"
    spec = "out_both[2] indicates in[2] and in[3]; we don't need to know out_both[3]."
    assert scc._onebased_index_warnings(spec, rtl, ports) == []


def test_onebased_set_to_zero_boundary_excluded():
    # v2 gatesv100 shape: "simply set out_both[99] to be zero."
    ports = [Port(name="out_both", direction="output", width=99)]
    rtl = "module TopModule(output [98:0] out_both);\nendmodule"
    spec = "There is no in[100], so simply set out_both[99] to be zero."
    assert scc._onebased_index_warnings(spec, rtl, ports) == []


def test_onebased_negative_index_reference_excludes_signal():
    ports = [Port(name="q", direction="output", width=8)]
    rtl = "module TopModule(output [7:0] q);\nendmodule"
    spec = "Treat q[-1] as zero. The cell q[8] follows the same rule as q[1]."
    assert scc._onebased_index_warnings(spec, rtl, ports) == []


# ── fsm-output-style-mismatch tightenings ────────────────────────────────

def _moore_findings(spec_text: str, rtl: str):
    spec = extract_spec_contract(spec_text, confirm=False)
    src = strip_comments(rtl)
    nm, ports = parse_rtl_ports(src, "TopModule")
    fs = scc.check(spec, nm, ports, scc.classify_rtl_resets(src),
                   scc._rtl_output_is_registered(src, ports), "t.sv", src,
                   spec_text=spec_text)
    return [f for f in fs if f.rule == "fsm-output-style-mismatch"]


_MOORE_SPEC = ("This is a Moore state machine with one input and one output.\n\n"
               " - input  clk\n - input  in\n - output out\n")


def test_moore_true_positive_still_fires():
    rtl = ("module TopModule(input clk, input in, output out);\n"
           "  reg state; initial state = 0;\n"
           "  always @(posedge clk) state <= in;\n"
           "  assign out = state & in;\n"   # Mealy
           "endmodule")
    assert [f.symbol for f in _moore_findings(_MOORE_SPEC, rtl)] == ["out"]


def test_moore_correct_design_clean():
    rtl = ("module TopModule(input clk, input in, output out);\n"
           "  reg state; initial state = 0;\n"
           "  always @(posedge clk) state <= in;\n"
           "  assign out = state;\n"
           "endmodule")
    assert _moore_findings(_MOORE_SPEC, rtl) == []


def test_moore_skipped_when_state_is_an_input():
    # fsm3comb / one-hot derive-by-inspection shape: the state register is
    # OUTSIDE the module; f(state-input) is the correct Moore output shape.
    spec = ("The following is the state transition table for a Moore state "
            "machine.\n\n - input  in\n - input  state (2 bits)\n"
            " - output next_state (2 bits)\n - output out\n")
    rtl = ("module TopModule(input in, input [1:0] state,\n"
           "                 output reg [1:0] next_state, output out);\n"
           "  always @(*) next_state = state + in;\n"
           "  assign out = (state == 2'd2);\n"
           "endmodule")
    assert _moore_findings(spec, rtl) == []


def test_moore_never_flags_next_state_like_outputs():
    # Moore-ness constrains the OUTPUT function, not next-state logic.
    spec = ("Implement the next-state logic of this Moore machine FSM.\n\n"
            " - input  clk\n - input  in\n - output S_next\n - output out\n")
    rtl = ("module TopModule(input clk, input in, output S_next, output out);\n"
           "  reg st; initial st = 0;\n"
           "  always @(posedge clk) st <= S_next;\n"
           "  assign S_next = st ^ in;\n"   # next-state: input-dependent, NEVER flagged
           "  assign out = st;\n"
           "endmodule")
    assert _moore_findings(spec, rtl) == []


# ── gates_atomic emit-blocking (end-to-end) ──────────────────────────────

def _stage(tmp_path, sample_body: str):
    ds = tmp_path / "ds"; ds.mkdir(exist_ok=True)
    (ds / "ProbT_prompt.txt").write_text(_MOORE_SPEC)
    wd = tmp_path / "run" / "work" / "ProbT"
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "spec.yaml").write_text("design:\n  name: TopModule\n")
    (wd / "sample.sv").write_text(sample_body)
    return ds, tmp_path / "run"


def _run_gate(ds, run):
    return subprocess.run(
        [sys.executable, str(GATES), "--prob", "ProbT",
         "--workdir", str(run / "work"), "--dataset", str(ds),
         "--prompt-suffix", "_prompt.txt", "--top-module", "TopModule"],
        capture_output=True, text=True, timeout=300)


def test_gate_blocks_mealy_under_moore_spec(tmp_path):
    ds, run = _stage(tmp_path,
        "module TopModule(input clk, input in, output out);\n"
        "  reg state; initial state = 0;\n"
        "  always @(posedge clk) state <= in;\n"
        "  assign out = state & in;\n"
        "endmodule\n")
    r = _run_gate(ds, run)
    assert r.returncode == 1, r.stdout + r.stderr
    gates = json.loads((run / "work" / "ProbT" / "gates.json").read_text())
    assert gates["hard_gates_pass"] is False
    blk = gates["steps"]["structural_emit_block"]
    assert blk["verdict"] == "BLOCK"
    assert any(f["rule"] == "fsm-output-style-mismatch" for f in blk["findings"])
    assert not (run / "samples" / "ProbT_sample01.sv").exists()


def test_gate_emits_after_fix(tmp_path):
    ds, run = _stage(tmp_path,
        "module TopModule(input clk, input in, output out);\n"
        "  reg state; initial state = 0;\n"
        "  always @(posedge clk) state <= in;\n"
        "  assign out = state;\n"
        "endmodule\n")
    r = _run_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates = json.loads((run / "work" / "ProbT" / "gates.json").read_text())
    assert gates["hard_gates_pass"] is True
    assert "structural_emit_block" not in gates["steps"]
    assert (run / "samples" / "ProbT_sample01.sv").exists()
