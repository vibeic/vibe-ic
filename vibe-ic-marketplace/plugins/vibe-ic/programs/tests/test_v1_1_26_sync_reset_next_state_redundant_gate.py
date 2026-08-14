"""v1.1.26 sync-reset-next-state-redundant-gate rule regressions.

Pins the ORGANIC-20260618-sync-reset-next-state-redundant-gate
lesson->program promotion, from VerilogEval-Human Prob139_2013_q2bfsm.

A SYNCHRONOUS-reset sequential block already holds the FSM in its reset state
whenever the reset is asserted; gating the COMBINATIONAL next-state of that
reset state on the SAME reset signal double-counts the reset and slips the
post-reset launch timing.  NEW ERROR rule in spec_conformance_check +
emit-block wiring in gates_atomic.

Guards (per the filing): ONLY a purely-synchronous reset qualifies (async is
out of scope); the gated arm must reference the SAME reset signal; gating on a
DIFFERENT control (enable/start) never fires; the canonical unconditional
reset-state transition is clean.  Empirical false-positive surface over all
156 VerilogEval-Human golden references is EMPTY.

chip-AGNOSTIC: fixtures use generic TopModule/clk/resetn/state shapes only.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import spec_conformance_check as scc  # noqa: E402
from _specrtl_common import (extract_spec_contract, parse_rtl_ports,  # noqa: E402
                             strip_comments)
from _sim_tools import NEEDS_IVERILOG  # noqa: E402

HARNESS = Path(__file__).resolve().parent.parent.parent / "benchmark"
GATES = HARNESS / "gates_atomic.py"
RULE = "sync-reset-next-state-redundant-gate"

_SPEC = ("A Moore FSM motor controller.\n\n - input  clk\n - input  resetn\n"
         " - input  x\n - output f\n\nWhile reset (active-low synchronous) is\n"
         "asserted, stay in state A. After reset is de-asserted, set f=1 for\n"
         "one cycle, then idle.\n")

# the recovered bug form: reset-state next gated on the sync reset (ternary)
_BUG_TERNARY = (
    "module TopModule(input clk, input resetn, input x, output f);\n"
    "  localparam A=0, B=1;\n"
    "  reg state, next;\n"
    "  always @(*) begin\n"
    "    case (state)\n"
    "      A: next = resetn ? B : A;\n"   # BUG
    "      B: next = B;\n"
    "      default: next = A;\n"
    "    endcase\n"
    "  end\n"
    "  always @(posedge clk) if (!resetn) state <= A; else state <= next;\n"
    "  assign f = (state == B);\n"
    "endmodule\n")

# canonical clean form: reset-state next is UNCONDITIONAL
_CLEAN = _BUG_TERNARY.replace("A: next = resetn ? B : A;", "A: next = B;")


def _findings(spec_text, rtl, rule=RULE):
    spec = extract_spec_contract(spec_text, confirm=False)
    src = strip_comments(rtl)
    nm, ports = parse_rtl_ports(src, "TopModule")
    fs = scc.check(spec, nm, ports, scc.classify_rtl_resets(src),
                   scc._rtl_output_is_registered(src, ports), "t.sv", src,
                   spec_text=spec_text)
    return [f for f in fs if f.rule == rule]


# ── unit: fires on the bug, clean on canonical ──────────────────────────────

def test_rule_fires_on_reset_gated_next_state_ternary():
    fs = _findings(_SPEC, _BUG_TERNARY)
    assert [f.severity for f in fs] == ["ERROR"]
    assert fs[0].symbol == "A"
    assert "double-counts" in fs[0].message


def test_rule_clean_on_canonical_unconditional_transition():
    assert _findings(_SPEC, _CLEAN) == []


def test_rule_fires_on_if_form():
    rtl = (
        "module TopModule(input clk, input resetn, output f);\n"
        "  localparam A=0, B=1;\n"
        "  reg state, next;\n"
        "  always @(*) begin\n"
        "    next = state;\n"
        "    if (!resetn) next = A; else if (state==A) next = B;\n"
        "  end\n"
        "  always @(posedge clk) if (!resetn) state <= A; else state <= next;\n"
        "  assign f = (state == B);\n"
        "endmodule\n")
    fs = _findings(_SPEC, rtl)
    assert [f.severity for f in fs] == ["ERROR"]


# ── §4.05 no-leak guards (boundary-outside must NOT fire) ────────────────────

def test_async_reset_is_skipped():
    # async reset legitimately appears in/around comb logic — out of scope
    rtl = (
        "module TopModule(input clk, input rst, output f);\n"
        "  localparam A=0, B=1;\n"
        "  reg state, next;\n"
        "  always @(*) begin\n"
        "    case (state)\n"
        "      A: next = rst ? A : B;\n"
        "      B: next = B;\n"
        "      default: next = A;\n"
        "    endcase\n"
        "  end\n"
        "  always @(posedge clk or posedge rst)\n"
        "    if (rst) state <= A; else state <= next;\n"
        "  assign f = (state == B);\n"
        "endmodule\n")
    assert _findings(_SPEC, rtl) == []


def test_gated_on_enable_not_reset_is_clean():
    # transition gated on a DIFFERENT control (enable) — legitimate
    rtl = (
        "module TopModule(input clk, input resetn, input en, output f);\n"
        "  localparam A=0, B=1;\n"
        "  reg state, next;\n"
        "  always @(*) begin\n"
        "    case (state)\n"
        "      A: next = en ? B : A;\n"
        "      B: next = B;\n"
        "      default: next = A;\n"
        "    endcase\n"
        "  end\n"
        "  always @(posedge clk) if (!resetn) state <= A; else state <= next;\n"
        "  assign f = (state == B);\n"
        "endmodule\n")
    assert _findings(_SPEC, rtl) == []


# ── §4.05 round-2 (Step-2.7): bind the arm to the next-state register ────────

def test_output_decode_referencing_reset_does_not_false_fire():
    # Step-2.7 HIGH#1: a SEPARATE output-decode block where the reset-state arm
    # legitimately references the reset as a release-from-reset status output
    # (`IDLE: out_valid = resetn;`) must NOT fire — its LHS is an OUTPUT, not the
    # next-state register. The next-state logic is clean/unconditional.
    rtl = (
        "module TopModule(input clk, input resetn, input go,\n"
        "                 output reg out_valid, output reg [1:0] state_o);\n"
        "  localparam IDLE=2'd0, RUN=2'd1, DONE=2'd2;\n"
        "  reg [1:0] state, next_state;\n"
        "  always @(*) begin\n"
        "    case (state)\n"
        "      IDLE: out_valid = resetn;\n"          # status output, not next-state
        "      RUN:  out_valid = 1'b1;\n"
        "      default: out_valid = 1'b0;\n"
        "    endcase\n"
        "  end\n"
        "  always @(*) begin\n"
        "    case (state)\n"
        "      IDLE: next_state = go ? RUN : IDLE;\n"  # clean, no reset gate
        "      RUN:  next_state = DONE;\n"
        "      default: next_state = IDLE;\n"
        "    endcase\n"
        "  end\n"
        "  always @(posedge clk) if (!resetn) state <= IDLE; else state <= next_state;\n"
        "  always @(*) state_o = state;\n"
        "endmodule\n")
    assert _findings(_SPEC, rtl) == []


def test_unrelated_sel_decoder_does_not_false_fire():
    # Step-2.7 HIGH#2: an independent combinational decoder selected by `sel`
    # (not the FSM state) whose reset-value-named case label samples reset as
    # data (`RST_ST: dout = resetn ? din : RST_ST;`) must NOT fire — its LHS is
    # `dout`, not the next-state register, and the seq block's next state is
    # computed inline (`state <= state + 1`), so there is no redundant comb gate.
    rtl = (
        "module TopModule(input clk, input resetn, input [1:0] sel,\n"
        "                 input [1:0] din, output reg [1:0] dout,\n"
        "                 output [1:0] state_o);\n"
        "  localparam [1:0] RST_ST=2'd0, S1=2'd1, S2=2'd2;\n"
        "  reg [1:0] state;\n"
        "  always @(posedge clk)\n"
        "    if (!resetn) state <= RST_ST; else state <= state + 2'd1;\n"
        "  always @(*) begin\n"
        "    case (sel)\n"
        "      RST_ST: dout = resetn ? din : RST_ST;\n"
        "      S1:     dout = S2;\n"
        "      default: dout = RST_ST;\n"
        "    endcase\n"
        "  end\n"
        "  assign state_o = state;\n"
        "endmodule\n")
    assert _findings(_SPEC, rtl) == []


def test_rule_fires_on_begin_end_wrapped_arm_no_false_skip():
    # Step-2.7 MED: the genuinely-redundant reset-state next-state, wrapped in a
    # begin/end case-item body, must STILL fire (was a false-skip).
    rtl = _BUG_TERNARY.replace(
        "      A: next = resetn ? B : A;\n",
        "      A: begin next = resetn ? B : A; end\n")
    fs = _findings(_SPEC, rtl)
    assert [f.severity for f in fs] == ["ERROR"]


# ── §4.05 round-3 (Step-2.7): consistency — same shape must fire regardless ──

def test_rule_fires_on_numeric_literal_reset_value():
    # round-3 LOW false-skip: a reset value written as a NUMERIC literal (`2'd0`)
    # rather than a named param must fire identically to the named-param shape.
    rtl = (
        "module fsm(input clk, input resetn, output reg out);\n"
        "  reg [1:0] state, next;\n"
        "  always @(*) begin\n"
        "    case (state)\n"
        "      2'd0: next = resetn ? 2'd1 : 2'd0;\n"   # redundant reset gate
        "      2'd1: next = 2'd2;\n"
        "      default: next = 2'd0;\n"
        "    endcase\n"
        "  end\n"
        "  always @(posedge clk)\n"
        "    if (!resetn) state <= 2'd0; else state <= next;\n"
        "endmodule\n")
    fs = _findings(_SPEC, rtl)
    assert [f.severity for f in fs] == ["ERROR"]


def test_rule_fires_on_begin_end_less_case_non_first_arm():
    # round-3 LOW false-skip: a begin/end-LESS `always @(*) case(…) endcase`
    # whose redundant reset-state arm is NOT the first case item must fire (the
    # _blk-truncation-at-first-semicolon gap is closed by _comb_body).
    rtl = (
        "module TopModule(input clk, input resetn, output f);\n"
        "  localparam S0=0, S1=1, S2=2, RST=3;\n"
        "  reg [1:0] state, next;\n"
        "  always @(*)\n"
        "    case (state)\n"
        "      S0: next = S1;\n"
        "      S1: next = S2;\n"
        "      S2: next = RST;\n"
        "      RST: next = resetn ? S0 : RST;\n"       # redundant, non-first arm
        "      default: next = RST;\n"
        "    endcase\n"
        "  always @(posedge clk)\n"
        "    if (!resetn) state <= RST; else state <= next;\n"
        "  assign f = (state == S2);\n"
        "endmodule\n")
    fs = _findings(_SPEC, rtl)
    assert [f.severity for f in fs] == ["ERROR"]


def test_rule_fires_on_second_same_reset_fsm():
    # round-3 LOW false-skip: two FSMs share one sync reset; the FIRST is clean,
    # the SECOND carries the redundant arm — must still fire (gate iterates all
    # same-reset sequential blocks, no early break).
    rtl = (
        "module two(input clk, input resetn, output reg oa, output reg ob);\n"
        "  parameter A=0, B=1, C=2;\n"
        "  reg [1:0] sa, na, sb, nb;\n"
        "  always @(*) begin\n"
        "    case (sa)\n"
        "      A: na = B; B: na = C; C: na = A; default: na = A;\n"
        "    endcase\n"
        "  end\n"
        "  always @(*) begin\n"
        "    case (sb)\n"
        "      A: nb = B; C: nb = resetn ? A : C; default: nb = A;\n"  # redundant
        "    endcase\n"
        "  end\n"
        "  always @(posedge clk) if (!resetn) sa <= A; else sa <= na;\n"
        "  always @(posedge clk) if (!resetn) sb <= C; else sb <= nb;\n"
        "endmodule\n")
    fs = _findings(_SPEC, rtl)
    assert [f.severity for f in fs] == ["ERROR"]


# ── gates_atomic end-to-end: BLOCK the bug, emit the canonical ───────────────

def _stage(tmp_path, prompt_text, sample_body):
    ds = tmp_path / "ds"; ds.mkdir(exist_ok=True)
    (ds / "ProbP_prompt.txt").write_text(prompt_text)
    wd = tmp_path / "run" / "work" / "ProbP"
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "spec.yaml").write_text("design:\n  name: TopModule\n")
    (wd / "sample.sv").write_text(sample_body)
    return ds, tmp_path / "run"


def _run_gate(ds, run):
    return subprocess.run(
        [sys.executable, str(GATES), "--prob", "ProbP",
         "--workdir", str(run / "work"), "--dataset", str(ds),
         "--prompt-suffix", "_prompt.txt", "--top-module", "TopModule"],
        capture_output=True, text=True, timeout=60)


def _block_rules(run):
    gates = json.loads((run / "work" / "ProbP" / "gates.json").read_text())
    blk = gates["steps"].get("structural_emit_block", {})
    return gates, {f["rule"] for f in blk.get("findings", [])}


@NEEDS_IVERILOG
def test_gate_blocks_bug_form(tmp_path):
    ds, run = _stage(tmp_path, _SPEC, _BUG_TERNARY)
    r = _run_gate(ds, run)
    assert r.returncode == 1, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is False
    assert RULE in rules
    assert not (run / "samples" / "ProbP_sample01.sv").exists()


@NEEDS_IVERILOG
def test_gate_emits_canonical_form(tmp_path):
    ds, run = _stage(tmp_path, _SPEC, _CLEAN)
    r = _run_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is True
    assert RULE not in rules
    assert (run / "samples" / "ProbP_sample01.sv").exists()
