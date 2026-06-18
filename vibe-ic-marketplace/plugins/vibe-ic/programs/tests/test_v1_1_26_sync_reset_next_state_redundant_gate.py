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
        capture_output=True, text=True, timeout=300)


def _block_rules(run):
    gates = json.loads((run / "work" / "ProbP" / "gates.json").read_text())
    blk = gates["steps"].get("structural_emit_block", {})
    return gates, {f["rule"] for f in blk.get("findings", [])}


def test_gate_blocks_bug_form(tmp_path):
    ds, run = _stage(tmp_path, _SPEC, _BUG_TERNARY)
    r = _run_gate(ds, run)
    assert r.returncode == 1, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is False
    assert RULE in rules
    assert not (run / "samples" / "ProbP_sample01.sv").exists()


def test_gate_emits_canonical_form(tmp_path):
    ds, run = _stage(tmp_path, _SPEC, _CLEAN)
    r = _run_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is True
    assert RULE not in rules
    assert (run / "samples" / "ProbP_sample01.sv").exists()
