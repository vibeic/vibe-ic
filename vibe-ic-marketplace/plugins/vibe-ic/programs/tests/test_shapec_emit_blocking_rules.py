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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import spec_conformance_check as scc  # noqa: E402
from _specrtl_common import Port, extract_spec_contract, parse_rtl_ports, strip_comments  # noqa: E402

HARNESS = Path(__file__).resolve().parent.parent.parent / "benchmark"
GATES = HARNESS / "gates_atomic.py"

#: Same shape, same reason, same wording as the already-gated sibling
#: `test_v0_2_50_msbfirst_direction_rule`: the tests below RUN `gates_atomic.py`
#: and then read the `gates.json` it writes. Without iverilog the harness dies at
#: `run(["iverilog", ...])` and writes no report, so the read fails with
#: `FileNotFoundError` on `.../gates.json` — a failure whose text names an absent
#: ARTEFACT and never the absent TOOL, so a reader triaging it reasonably
#: concludes a producer defect (vibe-ic#1357). The rule-function tests in the
#: first half of this file are pure and need no toolchain, so this is applied per
#: test and never as `pytestmark`.
_HAS_IVERILOG = shutil.which("iverilog") is not None
_needs_gate = pytest.mark.skipif(
    not _HAS_IVERILOG,
    reason="runs gates_atomic.py and reads the gates.json it writes; without "
           "iverilog the harness cannot run and writes nothing")


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
        capture_output=True, text=True, timeout=60)


@_needs_gate
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


@_needs_gate
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


# ── ORGANIC-20260605-boundary-fold-or-form-escalation ────────────────────

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rtl_hygiene_lint as rhl  # noqa: E402


def test_fold_or_form_is_error_xor_and_form_are_warn():
    # ORGANIC-20260723: `^` demoted ERROR->WARN. `x^(x<<1)` is the standard
    # edge/transition/first-difference idiom (leading-one detect, contiguous-ones
    # $countones()<=2, delta encode) — the boundary bit through x[0] is correct-
    # by-construction, not a leak. Only `|` (OR-form, VerilogEval-v2 Prob092 +
    # two clean-room campaigns) is a real-bug signal and stays ERROR.
    mk = lambda op: (f"module t(input [3:0] vec, output [3:0] y);\n"  # noqa: E731
                     f"  assign y = vec {op} {{1'b0, vec[3:1]}};\nendmodule\n")
    for op, sev in (("|", "ERROR"), ("^", "WARN"), ("&", "WARN")):
        fs = rhl.rule_vector_self_shift_fold(mk(op), "t.sv")
        assert [f.severity for f in fs] == [sev], (op, fs)
        assert fs[0].rule == "vector-self-shift-fold"


_FOLD_PROMPT_REQZERO = (
    "Build a neighbour gate.\n\n - input  vec (4 bits)\n - output y (4 bits)\n\n"
    "y[i] should indicate whether either vec[i] or its left neighbour is 1.\n"
    "There is no vec[4], so simply set y[3] to be zero.\n")
_FOLD_PROMPT_DONTCARE = (
    "Build a neighbour gate.\n\n - input  vec (4 bits)\n - output y (4 bits)\n\n"
    "y[i] should indicate whether either vec[i] or its left neighbour is 1.\n"
    "The answer for y[3] is obvious so we don't need to know y[3].\n")
_FOLD_BUG_RTL = ("module TopModule(input [3:0] vec, output [3:0] y);\n"
                 "  assign y = vec | {1'b0, vec[3:1]};\n"   # OR 形：邊界位洩漏
                 "endmodule\n")
_FOLD_GOOD_RTL = ("module TopModule(input [3:0] vec, output [3:0] y);\n"
                  "  assign y = {1'b0, (vec[2:0] | vec[3:1])};\n"
                  "endmodule\n")


def _stage_fold(tmp_path, prompt_text, sample_body):
    ds = tmp_path / "ds"; ds.mkdir(exist_ok=True)
    (ds / "ProbF_prompt.txt").write_text(prompt_text)
    wd = tmp_path / "run" / "work" / "ProbF"
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "spec.yaml").write_text("design:\n  name: TopModule\n")
    (wd / "sample.sv").write_text(sample_body)
    return ds, tmp_path / "run"


def _run_fold_gate(ds, run):
    return subprocess.run(
        [sys.executable, str(GATES), "--prob", "ProbF",
         "--workdir", str(run / "work"), "--dataset", str(ds),
         "--prompt-suffix", "_prompt.txt", "--top-module", "TopModule"],
        capture_output=True, text=True, timeout=60)


@_needs_gate
def test_gate_blocks_or_fold_when_prompt_requires_zero_boundary(tmp_path):
    ds, run = _stage_fold(tmp_path, _FOLD_PROMPT_REQZERO, _FOLD_BUG_RTL)
    r = _run_fold_gate(ds, run)
    assert r.returncode == 1, r.stdout + r.stderr
    gates = json.loads((run / "work" / "ProbF" / "gates.json").read_text())
    blk = gates["steps"]["structural_emit_block"]
    assert any(f["rule"] == "vector-self-shift-fold" for f in blk["findings"])
    assert not (run / "samples" / "ProbF_sample01.sv").exists()


@_needs_gate
def test_gate_advisory_not_block_when_boundary_dontcare(tmp_path):
    # OR 形 fire，但 prompt 宣告邊界 don't-care → advisory、照常 emit
    ds, run = _stage_fold(tmp_path, _FOLD_PROMPT_DONTCARE, _FOLD_BUG_RTL)
    r = _run_fold_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates = json.loads((run / "work" / "ProbF" / "gates.json").read_text())
    assert "structural_emit_block" not in gates["steps"]
    advs = gates["steps"].get("structural_advisories", [])
    assert any(a["rule"] == "vector-self-shift-fold" for a in advs)
    assert (run / "samples" / "ProbF_sample01.sv").exists()


@_needs_gate
def test_gate_emits_correct_fold_fix(tmp_path):
    # 正確寫法（兩運算元皆移位、邊界顯式擺 0）→ 不 fire、emit
    ds, run = _stage_fold(tmp_path, _FOLD_PROMPT_REQZERO, _FOLD_GOOD_RTL)
    r = _run_fold_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (run / "samples" / "ProbF_sample01.sv").exists()


# ── ORGANIC-20260605-boundary-fold-commutative-match ─────────────────────

_FOLD_BUG_RTL_MIRRORED = ("module TopModule(input [3:0] vec, output [3:0] y);\n"
                          "  assign y = {1'b0, vec[3:1]} | vec;\n"  # 鏡像 OR 形
                          "endmodule\n")


def test_fold_mirrored_operand_order_same_severities():
    # 鏡像寫法（concat 在左、整向量在右）同樣分級：| 仍 ERROR、^ 與 & 皆 WARN
    # （ORGANIC-20260723：^ 為 edge/transition idiom，boundary 正確、非 bug）。
    mk = lambda op: (f"module t(input [3:0] vec, output [3:0] y);\n"  # noqa: E731
                     f"  assign y = {{1'b0, vec[3:1]}} {op} vec;\nendmodule\n")
    for op, sev in (("|", "ERROR"), ("^", "WARN"), ("&", "WARN")):
        fs = rhl.rule_vector_self_shift_fold(mk(op), "t.sv")
        assert [f.severity for f in fs] == [sev], (op, fs)


def test_fold_mirrored_sliced_ident_not_matched():
    # 右運算元被切片（非整向量）→ 不是 self-fold，不 fire
    src = ("module t(input [3:0] v, output [3:0] y);\n"
           "  assign y = {1'b0, v[3:1]} | v[2:0];\nendmodule\n")
    assert rhl.rule_vector_self_shift_fold(src, "t.sv") == []


@_needs_gate
def test_gate_blocks_mirrored_or_fold_when_required_zero(tmp_path):
    ds, run = _stage_fold(tmp_path, _FOLD_PROMPT_REQZERO, _FOLD_BUG_RTL_MIRRORED)
    r = _run_fold_gate(ds, run)
    assert r.returncode == 1, r.stdout + r.stderr
    gates = json.loads((run / "work" / "ProbF" / "gates.json").read_text())
    blk = gates["steps"]["structural_emit_block"]
    assert any(f["rule"] == "vector-self-shift-fold" for f in blk["findings"])
    assert not (run / "samples" / "ProbF_sample01.sv").exists()


@_needs_gate
def test_gate_emits_mirrored_and_fold(tmp_path):
    # 鏡像 AND 形 = 合法遮蔽 idiom → WARN-only、照常 emit
    rtl = ("module TopModule(input [3:0] vec, output [3:0] y);\n"
           "  assign y = {1'b0, vec[3:1]} & vec;\nendmodule\n")
    ds, run = _stage_fold(tmp_path, _FOLD_PROMPT_REQZERO, rtl)
    r = _run_fold_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates = json.loads((run / "work" / "ProbF" / "gates.json").read_text())
    assert "structural_emit_block" not in gates["steps"]
    assert (run / "samples" / "ProbF_sample01.sv").exists()


# ── ORGANIC-20260723-boundary-fold-xor-is-edge-idiom ─────────────────────────
# REPRODUCE: three silicon-proven OpenTitan XOR-fold idioms false-blocked the
# REUSED-IP AES flow (opentitan_aes × sky130A) as ERROR. They must be WARN.

def test_fold_xor_leading_one_detector_is_warn_not_error():
    # OpenTitan prim_leading_one_ppc.sv: isolate the single edge of a prefix-OR
    # thermometer vector. `ppc ^ {ppc[N-2:0],1'b0}` = ppc ^ (ppc<<1). Correct.
    src = ("module prim_leading_one_ppc #(parameter N=8)\n"
           "  (input [N-1:0] ppc_out, output [N-1:0] leading_one_o);\n"
           "  assign leading_one_o = ppc_out ^ {ppc_out[N-2:0], 1'b0};\n"
           "endmodule\n")
    fs = rhl.rule_vector_self_shift_fold(src, "prim_leading_one_ppc.sv")
    assert len(fs) == 1 and fs[0].rule == "vector-self-shift-fold"
    assert fs[0].severity == "WARN", fs


def test_fold_xor_contiguous_ones_assertion_is_warn_not_error():
    # OpenTitan prim_packer.sv / tlul_assert.sv contiguous-ones check:
    # $countones(mask ^ {mask[W-2:0],1'b0}) <= 2 counts the <=2 run boundaries.
    src = ("module t(input [7:0] mask_i);\n"
           "  wire ok = ($countones(mask_i ^ {mask_i[6:0],1'b0}) <= 2);\n"
           "endmodule\n")
    fs = rhl.rule_vector_self_shift_fold(src, "prim_packer.sv")
    assert len(fs) == 1 and fs[0].severity == "WARN", fs


@_needs_gate
def test_gate_emits_xor_leading_one_detector(tmp_path):
    # End-to-end: the XOR edge idiom must NOT block the structural-emit gate.
    rtl = ("module TopModule(input [3:0] vec, output [3:0] y);\n"
           "  assign y = vec ^ {vec[2:0], 1'b0};\nendmodule\n")
    ds, run = _stage_fold(tmp_path, _FOLD_PROMPT_REQZERO, rtl)
    r = _run_fold_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates = json.loads((run / "work" / "ProbF" / "gates.json").read_text())
    assert "structural_emit_block" not in gates["steps"]
    assert (run / "samples" / "ProbF_sample01.sv").exists()


@_needs_gate
def test_gate_still_blocks_or_fold_negative_control(tmp_path):
    # NEGATIVE CONTROL: the OR-form real bug (Prob092) MUST still block ERROR.
    ds, run = _stage_fold(tmp_path, _FOLD_PROMPT_REQZERO, _FOLD_BUG_RTL)
    r = _run_fold_gate(ds, run)
    assert r.returncode == 1, r.stdout + r.stderr
    gates = json.loads((run / "work" / "ProbF" / "gates.json").read_text())
    blk = gates["steps"]["structural_emit_block"]
    assert any(f["rule"] == "vector-self-shift-fold" for f in blk["findings"])
