#!/usr/bin/env python3
"""Serial-parallel declared-function functional-golden oracle (repo-gatekeeper).

Pins the general IC-expert convention added to arith_oracle_tb_gen (+ its L10
per-case wiring in testbench_gen): for a SERIAL-PARALLEL arithmetic datapath
(one parallel operand + one bit-serial operand + one bit-serial result + clock),
author a functional-TB golden by driving the DECLARED operands, computing the
golden from the design's DECLARED function (a OP b mod 2^N — INDEPENDENTLY, in
Python) and comparing the reassembled DUT stream against it. The serial FRAMING
(serial-input order, serial-output order, output latency) is SELF-CALIBRATED —
discovered from the DUT stream vs the independent golden — so the oracle is
robust across RTL variants (any latency / bit-order) and needs no declared
framing. This is the shape the closed-form COMBINATIONAL oracle legitimately
DEFERS.

Contract halves pinned here:
  (a) POSITIVE — a serial-parallel multiplier gets a REAL self-checking oracle
      (ORACLE_TB_DONE) that COMPILES + PASSES against a correct DUT and FAILS
      against a broken one (falsifiable — not a rubber stamp), with NO
      declaration needed.  Generalises: the DUT here is a textbook carry-save
      serial-parallel multiplier, NOT any benchmark chip.
  (b) §4.05 FAIL-CLOSED — when the FUNCTION is not derivable (no recognised
      closed-form operator) or the SHAPE is wrong (non-arith class), the
      generator DEFERS (no fabricated golden) and the L10 per-case producer
      keeps the substance-floor (ORACLE_NONE) scaffold, so a case nobody can
      verify still fails the Step-4 gate honestly.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import arith_oracle_tb_gen as aotg  # noqa: E402
import testbench_gen as tbg  # noqa: E402

# A GENERIC (chip-AGNOSTIC) textbook carry-save serial-parallel multiplier —
# parallel operand `a`, bit-serial operand `b` (LSB-first), bit-serial result
# `y` (LSB-first), synchronous active-high reset, latency 2. NOT any benchmark
# design; proves the convention fires on the interface SHAPE, not a SKU.
_GENERIC_DUT = r"""
`default_nettype none
module serpar_mul #( parameter W = 8 ) (
    input  wire         clk,
    input  wire         rst,
    input  wire [W-1:0] a,
    input  wire         b,
    output wire         y
);
    reg  [W-1:0] s, c;
    reg          br, yr;
    wire [W-1:0] m  = a & {W{br}};
    wire [W-1:0] so = m ^ s ^ c;
    wire [W-1:0] co = (m & s) | (m & c) | (s & c);
    always @(posedge clk) begin
        if (rst) begin s<=0; c<=0; br<=0; yr<=0; end
        else begin
            br <= b;
            s  <= {1'b0, so[W-1:1]};
            c  <= co;
            yr <= so[0];
        end
    end
    assign y = yr;
endmodule
`default_nettype wire
"""

# A BROKEN variant (product forced to 0) — the oracle MUST catch it.
_BROKEN_DUT = _GENERIC_DUT.replace("a & {W{br}}", "a & {W{br}} & {W{1'b0}}")

_L10 = {
    "ic_name": "serpar_mul",
    "test_cases": [
        {"name": "random_multiplication_functional_equivalence",
         "kind": "functional_vector",
         "expected": "random (a,b) all match golden model"},
        {"name": "corner_operand", "kind": "functional_vector",
         "expected": "a=0, b=0, a=MAX, b=MAX"},
        {"name": "reset", "kind": "functional_vector",
         "expected": "reset behaviour"},
    ],
}


def _mk_project(tmp: Path, *, declare: bool, bit_order: str = "LSB_first",
                encoding: str = "unsigned", dut: str = _GENERIC_DUT,
                with_l10: bool = False) -> Path:
    root = tmp / "serpar_mul"
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "serpar_mul",
        "frs_sections": [{"content":
                          "y = (a * b) mod 2^W  serial-parallel multiplier"}]}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "serpar_mul",
        "top_ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "rst", "direction": "input", "width": 1},
            {"name": "a", "direction": "input", "width": "W",
             "msb": "W-1", "lsb": "0"},
            {"name": "b", "direction": "input", "width": 1},
            {"name": "y", "direction": "output", "width": 1}]}))
    rtl = root / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "serpar_mul.v").write_text(dut)
    if declare:
        (root / "plugin_output").mkdir()
        (root / "plugin_output" / "declaration.json").write_text(json.dumps({
            "bit_order": bit_order, "latency_cycles": 2,
            "integer_encoding": encoding, "reset_polarity": "active_high",
            "size_param": 8}))
    if with_l10:
        (gd / "L10_TEST_CASES.json").write_text(
            json.dumps(_L10, ensure_ascii=False))
    return root


# ── (a) POSITIVE: declared framing → real serial oracle ──────────────────────
def test_serial_spec_extracted_from_declaration(tmp_path):
    proj = _mk_project(tmp_path, declare=True)
    spec, reason = aotg.extract_serial_arith_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is not None, reason
    assert spec["topology"] == "serial_parallel"
    assert spec["operator"] == "*"
    assert spec["parallel"] == "a"
    assert spec["serial_in"] == "b" and spec["serial_out"] == "y"
    # declared conventions are read as INFORMATIONAL annotations (the oracle
    # self-calibrates framing and does not depend on them being correct).
    assert spec["declared_bit_order"] == "LSB" and spec["declared_latency"] == 2


def test_conventions_read_from_rtl_header_when_no_declaration_json(tmp_path):
    # Declaration lives ONLY in the RTL header 'DECLARED CHOICES' block.
    proj = _mk_project(tmp_path, declare=False)
    hdr = ("// DECLARED CHOICES\n//   bit_order = LSB_first\n"
           "//   latency_cycles = 2\n//   integer_encoding = unsigned\n"
           "//   reset_polarity = active_high\n")
    dutf = proj / "phase2" / "stage1" / "rtl" / "serpar_mul.v"
    dutf.write_text(hdr + dutf.read_text())
    conv = aotg.read_declared_conventions(proj, [])
    assert conv is not None
    assert conv["bit_order"] == "LSB" and conv["latency"] == 2


def test_generate_emits_self_calibrating_serial_oracle(tmp_path):
    proj = _mk_project(tmp_path, declare=True)
    rep, rc = aotg.generate(proj, "digital_arithmetic_primitive")
    assert rc == 0 and rep["verdict"] == "TB_EMITTED"
    assert rep["topology"] == "serial_parallel"
    tb = (proj / rep["tb"]).read_text()
    assert "ORACLE_TB_DONE pass=" in tb
    # NON-VACUOUS: real datapath width, several distinct goldens.
    assert "localparam integer N      = 8;" in tb
    assert tb.count("_gv[") >= 8
    # SELF-CALIBRATING: drives both serial-input orders and searches
    # (in_order x out_order x offset) — never trusts a declared latency/order.
    assert "_drive_capture(0)" in tb and "_drive_capture(1)" in tb
    assert "MAXOFF" in tb and "_best" in tb
    # golden computed independently, framing discovered — never read from DUT.
    assert "DISCOVERED from the DUT stream" in tb


def test_no_declaration_still_emits_self_calibrating(tmp_path):
    # CAPABILITY: the self-calibrating oracle needs NO declaration — the serial
    # framing is discovered, not read. So a project without declaration.json
    # (and no RTL-header framing) STILL emits a real oracle.
    proj = _mk_project(tmp_path, declare=False)
    spec, _ = aotg.extract_serial_arith_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is not None
    rep, rc = aotg.generate(proj, "digital_arithmetic_primitive")
    assert rc == 0 and rep["verdict"] == "TB_EMITTED"


# ── (b) §4.05 FAIL-CLOSED: undecidable FUNCTION or wrong SHAPE → DEFER ────────
def test_unrecognised_operator_defers_fail_closed(tmp_path):
    # No recognised closed-form operator in the spec → the FUNCTION is not
    # derivable → DEFER (never fabricate a golden).
    proj = _mk_project(tmp_path, declare=True)
    (proj / "phase1" / "generated_docs" / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "serpar_mul",
        "frs_sections": [{"content": "a bit-serial scrambler of x and y"}]}))
    spec, reason = aotg.extract_serial_arith_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is None and "operator" in reason.lower()
    _, rc = aotg.generate(proj, "digital_arithmetic_primitive")
    assert rc == 2


def test_non_arith_class_defers_fail_closed(tmp_path):
    proj = _mk_project(tmp_path, declare=True)
    _, rc = aotg.generate(proj, "processor_cpu")
    assert rc == 2


# ── L10 per-case wiring (testbench_gen) ──────────────────────────────────────
def test_testbench_gen_emits_per_case_golden_oracles(tmp_path):
    proj = _mk_project(tmp_path, declare=True, with_l10=True)
    report: dict = {}
    n = tbg.emit_unit_tbs(proj, "serpar_mul", kind="functional_vector",
                          report=report)
    assert n == 3
    tb_dir = proj / "phase2" / "stage1" / "sim" / "tb"
    for case in ("random_multiplication_functional_equivalence",
                 "corner_operand", "reset"):
        txt = (tb_dir / f"{case}.v").read_text()
        assert "VIBEIC_TB_ORACLE: NONE" not in txt, case  # real oracle
        assert "ORACLE_TB_DONE" in txt, case              # golden compare
    assert sorted(report.get("golden_oracle_cases", [])) == sorted(
        ["random_multiplication_functional_equivalence", "corner_operand",
         "reset"])


def test_testbench_gen_fail_closed_keeps_scaffold_when_function_undecidable(
        tmp_path):
    # §4.05 FAIL-CLOSED: when the FUNCTION is not derivable (no recognised
    # closed-form operator), no golden oracle can be authored, so every L10
    # functional_vector case keeps the substance-floor (ORACLE_NONE) scaffold —
    # an unverifiable case still fails the Step-4 gate honestly.
    proj = _mk_project(tmp_path, declare=True, with_l10=True)
    (proj / "phase1" / "generated_docs" / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "serpar_mul",
        "frs_sections": [{"content": "a bit-serial scrambler of x and y"}]}))
    tbg.emit_unit_tbs(proj, "serpar_mul", kind="functional_vector", report={})
    tb_dir = proj / "phase2" / "stage1" / "sim" / "tb"
    for case in ("random_multiplication_functional_equivalence",
                 "corner_operand", "reset"):
        txt = (tb_dir / f"{case}.v").read_text()
        assert "VIBEIC_TB_ORACLE: NONE" in txt, case


# ── falsifiability (iverilog-gated) ──────────────────────────────────────────
def _run_oracle(tb: Path, dut_text: str, tmp: Path) -> int:
    tmp.mkdir(parents=True, exist_ok=True)
    dutf = tmp / "dut.v"
    dutf.write_text(dut_text)
    out = tmp / "o.out"
    rc = subprocess.run(
        ["iverilog", "-g2012", "-o", str(out), str(tb), str(dutf)],
        capture_output=True, text=True)
    if rc.returncode != 0:
        return -1
    run = subprocess.run(["vvp", str(out)], capture_output=True, text=True)
    import re
    m = re.search(r"ORACLE_TB_DONE pass=(\d+)/(\d+)", run.stdout)
    assert m, run.stdout + run.stderr
    return 0 if m.group(1) == m.group(2) else 1


@pytest.mark.skipif(not shutil.which("iverilog"),
                    reason="iverilog not available")
def test_oracle_passes_correct_dut_fails_broken_dut(tmp_path):
    proj = _mk_project(tmp_path, declare=True)
    rep, rc = aotg.generate(proj, "digital_arithmetic_primitive")
    assert rc == 0
    tb = proj / rep["tb"]
    assert _run_oracle(tb, _GENERIC_DUT, tmp_path / "ok") == 0     # all pass
    assert _run_oracle(tb, _BROKEN_DUT, tmp_path / "bad") == 1     # falsified


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
