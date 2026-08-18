"""v0.2.53 moore-output-reset-gated rule regressions.

Pins the #423 lesson→program promotion
(ORGANIC-20260606-moore-output-reset-gated-rule), third in the series after
the MSB-first direction rule: a spec clause "when(ever) ... reset, assert
<sig> for N cycles" ties the assertion window to the reset STATE — the
canonical Moore reading asserts <sig> the cycle after any edge sampling
reset high, INCLUDING while reset is held. An RTL that conjoins that output
with the negated reset (`assign <sig> = <expr> && !<reset>`, or the same
RHS shape in an always block) loses an assertion cycle under a held or
re-asserted reset (contiguous window N-1 instead of N). NEW ERROR rule in
spec_conformance_check + emit-block wiring in gates_atomic.

Guards pinned below (per the filing): release-anchored spec wording never
fires; only the spec-NAMED asserted output is examined; async-reset specs
are skipped; the deferred-window mis-reading stays lesson-covered (no
negated-reset conjunction → out of this structural rule's scope).

chip-AGNOSTIC: fixtures use generic TopModule/clk/reset/shift_ena shapes only.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import spec_conformance_check as scc  # noqa: E402
from _specrtl_common import extract_spec_contract, parse_rtl_ports, strip_comments  # noqa: E402

import pytest  # noqa: E402

#: These tests RUN `gates_atomic.py` and then read the `gates.json` it writes.
#: Without iverilog the gate refuses to run — correctly — and writes no report,
#: so the read dies with FileNotFoundError on a path that was never meant to
#: exist. A gate that REFUSED and a gate that produced a bad report are not the
#: same result, and a traceback cannot tell them apart (#1430, #1433).
#:
#: Marked by CALL RELATIONSHIP, not by name. The `test_gate_*` prefix happens to
#: select the right set in these two files, but #1430 records that the same
#: shortcut would have silenced two tests needing no toolchain. The rule is
#: "its body reaches `_run_gate(` or `_block_rules(`", derived with `ast`.
_HAS_IVERILOG = shutil.which("iverilog") is not None
_needs_gate = pytest.mark.skipif(
    not _HAS_IVERILOG,
    reason="runs gates_atomic.py and reads the gates.json it writes; without "
           "iverilog the gate refuses and writes nothing")


HARNESS = Path(__file__).resolve().parent.parent.parent / "benchmark"
GATES = HARNESS / "gates_atomic.py"

RULE = "moore-output-reset-gated"


def _findings(spec_text: str, rtl: str, rule: str = RULE):
    spec = extract_spec_contract(spec_text, confirm=False)
    src = strip_comments(rtl)
    nm, ports = parse_rtl_ports(src, "TopModule")
    fs = scc.check(spec, nm, ports, scc.classify_rtl_resets(src),
                   scc._rtl_output_is_registered(src, ports), "t.sv", src,
                   spec_text=spec_text)
    return [f for f in fs if f.rule == rule]


# the audited campaign's failure class: reset-tied 4-cycle window prompt
_SPEC = ("Build the FSM for controlling a shift register.\n\n"
         " - input  clk\n - input  reset\n - output shift_ena\n\n"
         "Whenever the FSM is reset, assert shift_ena for 4 cycles, then 0\n"
         "forever (until reset). Reset should be active high synchronous.\n")

# canonical Moore form: output decoded from state alone — PASS
_CANONICAL_RTL = ("module TopModule(input clk, input reset, output shift_ena);\n"
                  "  reg [2:0] cnt;\n"
                  "  initial cnt = 0;\n"
                  "  always @(posedge clk)\n"
                  "    if (reset) cnt <= 3'd4;\n"
                  "    else if (cnt != 0) cnt <= cnt - 1;\n"
                  "  assign shift_ena = (cnt != 0);\n"
                  "endmodule\n")

# the recovered reset-gated variant: window AND-ed with !reset — ERROR
_GATED_RTL = _CANONICAL_RTL.replace(
    "assign shift_ena = (cnt != 0);",
    "assign shift_ena = (cnt != 0) && !reset;")

# deferred-window mis-reading: counter starts only after release — no
# negated-reset conjunction, stays lesson-covered (out of scope here)
_DEFERRED_RTL = ("module TopModule(input clk, input reset, output shift_ena);\n"
                 "  reg [2:0] cnt;\n"
                 "  reg armed;\n"
                 "  initial begin cnt = 0; armed = 0; end\n"
                 "  always @(posedge clk)\n"
                 "    if (reset) begin armed <= 1; cnt <= 0; end\n"
                 "    else if (armed) begin armed <= 0; cnt <= 3'd4; end\n"
                 "    else if (cnt != 0) cnt <= cnt - 1;\n"
                 "  assign shift_ena = (cnt != 0);\n"
                 "endmodule\n")


# ── unit: the rule fires on the gated form, never on the canonical form ───

def test_rule_fires_on_reset_gated_output():
    fs = _findings(_SPEC, _GATED_RTL)
    assert [f.severity for f in fs] == ["ERROR"]
    assert fs[0].symbol == "shift_ena"
    assert "N-1" in fs[0].message


def test_rule_clean_on_canonical_moore_form():
    assert _findings(_SPEC, _CANONICAL_RTL) == []


def test_rule_clean_on_deferred_window_form():
    # lesson-covered mis-reading, out of this structural rule's scope
    assert _findings(_SPEC, _DEFERRED_RTL) == []


def test_rule_fires_on_tilde_and_form():
    rtl = _CANONICAL_RTL.replace("assign shift_ena = (cnt != 0);",
                                 "assign shift_ena = (cnt != 0) & ~reset;")
    fs = _findings(_SPEC, rtl)
    assert [f.severity for f in fs] == ["ERROR"]


def test_rule_fires_on_always_block_rhs_form():
    rtl = ("module TopModule(input clk, input reset, output reg shift_ena);\n"
           "  reg [2:0] cnt;\n"
           "  initial begin cnt = 0; shift_ena = 0; end\n"
           "  always @(posedge clk) begin\n"
           "    if (reset) cnt <= 3'd4;\n"
           "    else if (cnt != 0) cnt <= cnt - 1;\n"
           "    shift_ena <= (cnt != 0) && !reset;\n"
           "  end\n"
           "endmodule\n")
    fs = _findings(_SPEC, rtl)
    assert [f.severity for f in fs] == ["ERROR"]


# ── unit: the filing's guards ──────────────────────────────────────────────

def test_release_anchored_spec_wording_never_fires():
    # guard (a): window anchored to reset RELEASE is a different contract
    spec = _SPEC.replace(
        "Whenever the FSM is reset, assert shift_ena for 4 cycles",
        "Whenever reset is deasserted, assert shift_ena for 4 cycles")
    assert _findings(spec, _GATED_RTL) == []


def test_only_spec_named_output_is_examined():
    # guard (b): some OTHER signal gated with !reset must not fire
    rtl = _CANONICAL_RTL.replace(
        "assign shift_ena = (cnt != 0);",
        "assign shift_ena = (cnt != 0);\n"
        "  wire dbg;\n  assign dbg = (cnt == 1) && !reset;")
    assert _findings(_SPEC, rtl) == []


def test_async_reset_spec_is_skipped():
    # guard (c): an async-clear contract is a different class
    spec = _SPEC.replace("Reset should be active high synchronous.",
                         "Reset is asynchronous and active high.")
    assert _findings(spec, _GATED_RTL) == []


def test_no_reset_tied_window_in_spec_never_fires():
    spec = ("A pulse generator.\n\n - input  clk\n - input  reset\n"
            " - output shift_ena\n\nAssert shift_ena every 8 cycles.\n")
    assert _findings(spec, _GATED_RTL) == []


# ── gates_atomic end-to-end: BLOCK the gated form, emit the canonical ─────

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


@_needs_gate
def test_gate_auto_corrects_reset_gated_form(tmp_path):
    # v1.1.76: the registry's `behavioral_fsm` solver fires on this reset-pulse spec
    # ("assert shift_ena for 4 cycles then 0 forever") and emits the correct
    # reset-pulse counter, REPLACING the author's wrong reset-gated read
    # (`shift_ena = (cnt!=0) && !reset`) BEFORE the gate runs. The safety invariant
    # "a wrong reset-gated read never ships" is preserved in its STRONGER form
    # (auto-corrected, not merely blocked) — behavioral_fsm is host-verified on the
    # real Prob095_review2015_fsmshift. The structural rule still fires STANDALONE
    # (test_rule_fires_on_reset_gated_output), guarding the cases the synth SKIPs.
    ds, run = _stage(tmp_path, _SPEC, _GATED_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates, _ = _block_rules(run)
    assert gates["steps"]["deterministic_synth"]["applied"] is True
    assert gates["steps"]["deterministic_synth"]["kind"] == "behavioral_fsm"
    # the wrong reset-gated read never ships — the correct auto-synthesized RTL does.
    emitted = (run / "samples" / "ProbP_sample01.sv").read_text()
    assert "&& !reset" not in emitted and "! reset" not in emitted
    assert "reset-pulse counter" in emitted


@_needs_gate
def test_gate_emits_canonical_form(tmp_path):
    ds, run = _stage(tmp_path, _SPEC, _CANONICAL_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is True
    assert rules == set()
    assert (run / "samples" / "ProbP_sample01.sv").exists()
