"""v0.2.50 msbfirst-direction-mismatch rule regressions.

Pins the #420 lesson→program promotion
(ORGANIC-20260605-msbfirst-direction-conformance-rule): the shift-direction
expert lesson (anti-pattern block + numeric trace) cut the inversion rate
from 2/2 relevant agents to 1/32 across a fully-audited campaign, but prose
cannot reach zero. The residual wrong form is a STRUCTURAL signature — the
prompt carries an MSB-first serial-load phrase while the RTL inserts the new
bit at the MSB end of a parallel-consumed register
(`vec <= {bit, vec[W-1:1]}`), assembling the word bit-REVERSED. NEW ERROR
rule in spec_conformance_check + emit-block wiring in gates_atomic.

Conservative guards each pinned below (every one kills a real legitimate
idiom): LSB-first / dual-direction prompts, rotates, arithmetic shifts,
runtime-muxed dual-direction RTL, and single-bit-tap delay lines.

chip-AGNOSTIC: fixtures use generic TopModule/clk/serial_in/q shapes only.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import spec_conformance_check as scc  # noqa: E402
from _specrtl_common import extract_spec_contract, parse_rtl_ports, strip_comments  # noqa: E402
from _sim_tools import NEEDS_IVERILOG  # noqa: E402

HARNESS = Path(__file__).resolve().parent.parent.parent / "benchmark"
GATES = HARNESS / "gates_atomic.py"

import pytest  # noqa: E402

#: These tests RUN `gates_atomic.py` and then read the `gates.json` it writes.
#: Without iverilog the gate refuses to run — correctly — and writes no report,
#: so the read dies with FileNotFoundError on a path that was never meant to
#: exist. A gate that REFUSED and a gate that produced a bad report are not the
#: same result, and a traceback cannot tell them apart. Every other test in this
#: file calls pure rule functions and needs no toolchain.
_HAS_IVERILOG = shutil.which("iverilog") is not None
_needs_gate = pytest.mark.skipif(
    not _HAS_IVERILOG,
    reason="runs gates_atomic.py and reads the gates.json it writes; without "
           "iverilog the gate refuses and writes nothing")


RULE = "msbfirst-direction-mismatch"


def _findings(spec_text: str, rtl: str, rule: str = RULE):
    spec = extract_spec_contract(spec_text, confirm=False)
    src = strip_comments(rtl)
    nm, ports = parse_rtl_ports(src, "TopModule")
    fs = scc.check(spec, nm, ports, scc.classify_rtl_resets(src),
                   scc._rtl_output_is_registered(src, ports), "t.sv", src,
                   spec_text=spec_text)
    return [f for f in fs if f.rule == rule]


# the audited campaign's residual failure shape: MSB-first serial-load prompt,
# RTL enters the new bit at the MSB end → parallel word comes out bit-reversed.
_MSBFIRST_SPEC = ("Build a shift register that captures a serial bit stream.\n\n"
                  " - input  clk\n - input  serial_in\n"
                  " - output q (8 bits)\n\n"
                  "The data arrives MSB first; after 8 clocks q holds the "
                  "received byte.\n")
_WRONG_RTL = ("module TopModule(input clk, input serial_in,\n"
              "                 output reg [7:0] q);\n"
              "  initial q = 0;\n"
              "  always @(posedge clk) q <= {serial_in, q[7:1]};\n"
              "endmodule\n")
_CORRECT_RTL = ("module TopModule(input clk, input serial_in,\n"
                "                 output reg [7:0] q);\n"
                "  initial q = 0;\n"
                "  always @(posedge clk) q <= {q[6:0], serial_in};\n"
                "endmodule\n")


# ── unit: the rule fires on the anti-pattern, never on the idiom ──────────

def test_rule_fires_on_msb_entry_under_msbfirst_prompt():
    fs = _findings(_MSBFIRST_SPEC, _WRONG_RTL)
    assert [f.severity for f in fs] == ["ERROR"]
    assert fs[0].symbol == "q"
    assert "bit-REVERSED" in fs[0].message
    assert "{q[W-2:0], serial_in}" in fs[0].message  # repair idiom named


def test_rule_clean_on_leftshift_idiom():
    assert _findings(_MSBFIRST_SPEC, _CORRECT_RTL) == []


def test_rule_fires_on_most_significant_bit_spelling():
    spec = _MSBFIRST_SPEC.replace("MSB first",
                                  "most significant bit first")
    fs = _findings(spec, _WRONG_RTL)
    assert [f.severity for f in fs] == ["ERROR"]


def test_rule_fires_on_first_dot_dot_msb_word_order():
    spec = _MSBFIRST_SPEC.replace(
        "The data arrives MSB first",
        "The first bit received is the MSB of the byte")
    fs = _findings(spec, _WRONG_RTL)
    assert [f.severity for f in fs] == ["ERROR"]


# ── unit: prompt-side guards ───────────────────────────────────────────────

def test_rule_silent_under_lsbfirst_prompt():
    # under LSB-first reception the MSB-entry right shift IS the correct idiom
    spec = _MSBFIRST_SPEC.replace("MSB first", "LSB first")
    assert _findings(spec, _WRONG_RTL) == []


def test_rule_silent_on_dual_direction_prompt():
    # configurable direction (both phrases present) is ambiguous — stay silent
    spec = _MSBFIRST_SPEC.replace(
        "The data arrives MSB first",
        "A mode pin selects whether data arrives MSB first or LSB first")
    assert _findings(spec, _WRONG_RTL) == []


def test_rule_silent_without_serial_vocabulary():
    # "MSB ... first" prose in a non-serial-load context must not arm the rule
    spec = ("Build a comparator.\n\n - input  clk\n - input  serial_in\n"
            " - output q (8 bits)\n\nThe MSB is compared first when ranking "
            "two operands.\n")
    assert _findings(spec, _WRONG_RTL) == []


# ── unit: RTL-side guards ──────────────────────────────────────────────────

def test_rule_silent_on_rotate():
    rtl = _WRONG_RTL.replace("{serial_in, q[7:1]}", "{q[0], q[7:1]}")
    assert _findings(_MSBFIRST_SPEC, rtl) == []


def test_rule_silent_on_arithmetic_shift():
    rtl = _WRONG_RTL.replace("{serial_in, q[7:1]}", "{q[7], q[7:1]}")
    assert _findings(_MSBFIRST_SPEC, rtl) == []


def test_rule_silent_on_literal_fill_shift():
    rtl = _WRONG_RTL.replace("{serial_in, q[7:1]}", "{1'b0, q[7:1]}")
    assert _findings(_MSBFIRST_SPEC, rtl) == []


def test_rule_silent_on_runtime_muxed_dual_direction_rtl():
    rtl = ("module TopModule(input clk, input dir, input serial_in,\n"
           "                 output reg [7:0] q);\n"
           "  initial q = 0;\n"
           "  always @(posedge clk)\n"
           "    if (dir) q <= {serial_in, q[7:1]};\n"
           "    else     q <= {q[6:0], serial_in};\n"
           "endmodule\n")
    assert _findings(_MSBFIRST_SPEC, rtl) == []


def test_rule_silent_on_delay_line_single_bit_tap():
    # a delay line re-emits bits in arrival order — entry end is immaterial
    rtl = ("module TopModule(input clk, input serial_in, output out);\n"
           "  reg [7:0] line;\n"
           "  initial line = 0;\n"
           "  always @(posedge clk) line <= {serial_in, line[7:1]};\n"
           "  assign out = line[0];\n"
           "endmodule\n")
    spec = ("Implement an 8-stage delay line for a serial bit stream that is "
            "transmitted MSB first.\n\n - input  clk\n - input  serial_in\n"
            " - output out\n")
    assert _findings(spec, rtl) == []


def test_rule_fires_on_internal_reg_assigned_to_word_output():
    # whole-vector consumption through an internal register still fires
    rtl = ("module TopModule(input clk, input serial_in,\n"
           "                 output [7:0] q);\n"
           "  reg [7:0] sr;\n"
           "  initial sr = 0;\n"
           "  always @(posedge clk) sr <= {serial_in, sr[7:1]};\n"
           "  assign q = sr;\n"
           "endmodule\n")
    fs = _findings(_MSBFIRST_SPEC, rtl)
    assert [f.severity for f in fs] == ["ERROR"]
    assert fs[0].symbol == "sr"


# ── gates_atomic end-to-end: BLOCK on the anti-pattern, emit on the idiom ──

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
@NEEDS_IVERILOG
def test_gate_blocks_msb_entry_form(tmp_path):
    ds, run = _stage(tmp_path, _MSBFIRST_SPEC, _WRONG_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 1, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is False
    assert RULE in rules
    assert not (run / "samples" / "ProbP_sample01.sv").exists()


@_needs_gate
@NEEDS_IVERILOG
def test_gate_emits_leftshift_idiom(tmp_path):
    ds, run = _stage(tmp_path, _MSBFIRST_SPEC, _CORRECT_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is True
    assert rules == set()
    assert (run / "samples" / "ProbP_sample01.sv").exists()
