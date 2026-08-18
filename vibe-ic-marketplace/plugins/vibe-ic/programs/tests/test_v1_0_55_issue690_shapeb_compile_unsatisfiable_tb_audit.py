"""#690 — Shape-B COMPILE-level unsatisfiable-TB / spec-absent-port audit.

The Shape-B scorer charges a plain model `compile_error` when the hidden TB
instantiates a DUT port the prose spec NEVER declares. Every spec-faithful
submission then fails iverilog elaboration with `port 'X' is not a port of uut`,
while the verification golden (resolved via ref_glob, e.g. verified_*.v) DOES
declare X — so golden+TB compiles. But:

  * the RUNTIME golden-fails-own-TB audit (#679) is gated to run only when
    verdict==FAIL AND reason!='compile_error' — so it NEVER fires on this case;
  * the COMPILE audit `_golden_ref_self_compiles` was scoped to
    module_name_strategy=='always_TopModule' with ref_suffix/tb_suffix set, which
    the Shape-B / RTLLM layout (from_description_module_name_line + ref_glob,
    ref_suffix=None) lacks — so it returned None and never fired.

Net before the fix: dataset_defect_count stayed 0 and the case was charged as a
plain model compile_error.

This test pins the new COMPILE-level audit that runs PRECISELY on the
compile_error path the runtime audit excludes:

POSITIVE
  (b) a candidate compile_error where the TB binds a GOLDEN-declared, SPEC-ABSENT
      port (the real radix2_div `res_ready` handshake shape) → dataset_defect=True,
      reason='tb_requires_spec_absent_port', EXCLUDED from charged-to-model.
  (a) a golden(aliased)+TB that ALSO fails to elaborate → dataset_defect=True,
      reason='golden_ref_fails_own_tb_compile'.
  Plus: _golden_ref_self_compiles now ALSO makes a determination on the
  ref_glob / from_description layout (no longer always_TopModule-only).

§4.05 NEGATIVE no-leak — a GENUINE model compile_error stays charged:
  * a real candidate SYNTAX error (golden+TB compiles fine, error is not a missing
    port) → still charged, dataset_defect False, verdict FAIL.
  * a candidate that omits a port the SPEC DOES declare → still charged
    (golden+TB compiles AND the missing port is named in the spec) → dataset_defect
    False.
  * verdict never flips to PASS; the #679 RUNTIME audit path is unchanged (a
    non-compile FAIL still routes to the runtime helper, not the compile audit);
    the always_TopModule VerilogEval compile-audit path still works.

The live-compile portions are gated on iverilog/vvp availability; the no-tool
logic assertions stay deterministic.

Chip-AGNOSTIC: every fixture is synthetic (radix2_div res_ready *shape*, not the
real file), driven by registry-style layout.ref_glob/tb_filename + scorer_args
regex + the spec's own Module-name line; no design-id branch in the scorer.
"""
import importlib.util
import shutil
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark" / "score_iverilog_tb.py")


def _load():
    spec = importlib.util.spec_from_file_location("score_iverilog_tb_690", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _need_tools():
    if not (shutil.which("iverilog") and shutil.which("vvp")):
        pytest.skip("iverilog/vvp not installed")


# ---- registry-style Shape-B layout + scorer_args (mirrors RTLLM) ------------
LAYOUT = {
    "prompt_filename": "design_description.txt",
    "tb_filename": "testbench.v",
    "ref_glob": "verified_*.v",
    "module_name_strategy": "from_description_module_name_line",
}
ARGS = {
    "pass_regex": r"Your Design Passed",
    "fail_regex": r"Failed",
    "cwd_design_dir": True,
}

# ============================================================================
# radix2_div res_ready SHAPE (synthetic, not the real file). The spec declares
# 8 ports — NO res_ready. The TB binds a 9th port .res_ready(...) onto `uut`.
# The golden DECLARES res_ready, so golden+TB compiles; a spec-faithful design
# (no res_ready) FAILs elaboration: "port 'res_ready' is not a port of uut".
# ============================================================================
_DESC_8PORTS = (
    "Implement a tiny divider.\n"
    "Module name:\n"
    "    div8\n"
    "Input ports:\n"
    "    clk: Clock signal.\n"
    "    rst: Reset signal.\n"
    "    sign: signed/unsigned select.\n"
    "    dividend: 8-bit dividend.\n"
    "    divisor: 8-bit divisor.\n"
    "    opn_valid: operation-valid request.\n"
    "Output ports:\n"
    "    res_valid: result is valid.\n"
    "    result: 16-bit quotient/remainder.\n"
    "Give me the complete code.\n"
)

# Golden declares the EXTRA res_ready handshake input that the TB wires.
_GOLDEN_WITH_RES_READY = (
    "module div8(\n"
    "  input clk, input rst, input sign,\n"
    "  input [7:0] dividend, input [7:0] divisor,\n"
    "  input opn_valid, input res_ready,\n"
    "  output res_valid, output [15:0] result\n"
    ");\n"
    "  assign res_valid = res_ready;\n"
    "  assign result = 16'd0;\n"
    "endmodule\n"
)

# A spec-faithful candidate: declares exactly the 8 spec ports (NO res_ready).
_CANDIDATE_SPEC_FAITHFUL = (
    "module div8(\n"
    "  input clk, input rst, input sign,\n"
    "  input [7:0] dividend, input [7:0] divisor,\n"
    "  input opn_valid,\n"
    "  output res_valid, output [15:0] result\n"
    ");\n"
    "  assign res_valid = 1'b1;\n"
    "  assign result = 16'd0;\n"
    "endmodule\n"
)

# TB binds the 9th port .res_ready(...) onto `uut` — the unsatisfiable-by-spec wire.
_TB_BINDS_RES_READY = (
    "module div8_tb;\n"
    "  reg clk, rst, sign, opn_valid, res_ready;\n"
    "  reg [7:0] dividend, divisor;\n"
    "  wire res_valid; wire [15:0] result;\n"
    "  div8 uut(\n"
    "    .clk(clk), .rst(rst), .sign(sign),\n"
    "    .dividend(dividend), .divisor(divisor),\n"
    "    .opn_valid(opn_valid), .res_ready(res_ready),\n"
    "    .res_valid(res_valid), .result(result));\n"
    "  initial begin\n"
    "    res_ready = 1'b1; #1;\n"
    "    if (res_valid === 1'b1) $display(\"Your Design Passed\");\n"
    "    else $display(\"Failed\");\n"
    "    $finish;\n"
    "  end\n"
    "endmodule\n"
)

# ============================================================================
# (a) shape — a TB that binds a port NEITHER the golden NOR any submission has:
# even golden(aliased)+TB cannot elaborate → unsatisfiable by anyone.
# ============================================================================
_DESC_2PORTS = (
    "A 1-bit buffer.\n"
    "Module name:\n"
    "    buf1\n"
    "Input ports:\n"
    "    a: input bit.\n"
    "Output ports:\n"
    "    y: output bit.\n"
)
_GOLDEN_BUF = (
    "module buf1(input a, output y);\n"
    "  assign y = a;\n"
    "endmodule\n"
)
# TB wires .ghost() — a port NO module (golden or candidate) declares.
_TB_GHOST_PORT = (
    "module buf1_tb;\n"
    "  reg a, ghost; wire y;\n"
    "  buf1 uut(.a(a), .ghost(ghost), .y(y));\n"
    "  initial begin a=1; #1;\n"
    "    if (y===1'b1) $display(\"Your Design Passed\");\n"
    "    else $display(\"Failed\"); $finish; end\n"
    "endmodule\n"
)


def _mk_design(root: Path, design: str, desc: str, golden: str, tb: str,
               golden_name: str):
    d = root / design
    d.mkdir(parents=True, exist_ok=True)
    (d / LAYOUT["prompt_filename"]).write_text(desc)
    (d / LAYOUT["tb_filename"]).write_text(tb)
    (d / golden_name).write_text(golden)
    return d


def _mk_run(root: Path, sample_name: str, sample_text: str):
    samples = root / "run" / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    (samples / sample_name).write_text(sample_text)
    return samples


# ====================== HELPER-LEVEL determinism (no tools) =================
def test_spec_declares_port_whole_word_noleak_guard(tmp_path):
    """§4.05 core guard: a port named in the spec is DECLARED (never flag);
    a port absent from the prose is spec-absent (eligible to flag)."""
    mod = _load()
    _mk_design(tmp_path, "div8", _DESC_8PORTS, _GOLDEN_WITH_RES_READY,
               _TB_BINDS_RES_READY, "verified_div8.v")
    assert mod._spec_declares_port("div8", tmp_path, LAYOUT, "res_valid") is True
    assert mod._spec_declares_port("div8", tmp_path, LAYOUT, "opn_valid") is True
    # the spec-absent handshake
    assert mod._spec_declares_port("div8", tmp_path, LAYOUT, "res_ready") is False


def test_spec_declares_port_failsafe_when_no_spec(tmp_path):
    """No spec file ⇒ cannot prove absence ⇒ treated as DECLARED (fail-safe;
    never flag a defect we cannot substantiate)."""
    mod = _load()
    assert mod._spec_declares_port("nope", tmp_path, LAYOUT, "res_ready") is True


def test_canonical_dut_name_from_module_line(tmp_path):
    mod = _load()
    _mk_design(tmp_path, "div8", _DESC_8PORTS, _GOLDEN_WITH_RES_READY,
               _TB_BINDS_RES_READY, "verified_div8.v")
    assert mod._canonical_dut_name_shape_b("div8", tmp_path, LAYOUT) == "div8"


def test_module_declared_ports_parses_golden_header():
    mod = _load()
    ports = mod._module_declared_ports(_GOLDEN_WITH_RES_READY)
    assert {"clk", "rst", "sign", "dividend", "divisor", "opn_valid",
            "res_ready", "res_valid", "result"} <= ports
    cand = mod._module_declared_ports(_CANDIDATE_SPEC_FAITHFUL)
    assert "res_ready" not in cand          # spec-faithful design lacks it


def test_audit_no_ref_glob_returns_no_defect(tmp_path):
    """layout without ref_glob ⇒ (False, None) — no determination, no flag,
    no tools needed."""
    mod = _load()
    layout = dict(LAYOUT)
    layout.pop("ref_glob")
    assert mod._unsatisfiable_tb_compile_audit_shape_b(
        "x", tmp_path, layout, "port `res_ready' is not a port of uut") == (False, None)


# ============================ POSITIVE (b) ===================================
def test_positive_b_helper_compiles_true_with_golden_ports(tmp_path):
    """golden(aliased)+TB DOES elaborate (golden has res_ready) → compiles True
    and the golden port set includes res_ready."""
    _need_tools()
    mod = _load()
    _mk_design(tmp_path, "div8", _DESC_8PORTS, _GOLDEN_WITH_RES_READY,
               _TB_BINDS_RES_READY, "verified_div8.v")
    compiles, ports = mod._golden_ref_compiles_with_tb_shape_b(
        "div8", tmp_path, LAYOUT)
    assert compiles is True
    assert "res_ready" in ports


def test_positive_b_audit_flags_spec_absent_port(tmp_path):
    """The candidate's compile error names a GOLDEN-declared, SPEC-ABSENT port
    → (True, 'tb_requires_spec_absent_port')."""
    _need_tools()
    mod = _load()
    _mk_design(tmp_path, "div8", _DESC_8PORTS, _GOLDEN_WITH_RES_READY,
               _TB_BINDS_RES_READY, "verified_div8.v")
    cand_log = "testbench.v:5: error: port ``res_ready'' is not a port of uut.\n"
    defect, reason = mod._unsatisfiable_tb_compile_audit_shape_b(
        "div8", tmp_path, LAYOUT, cand_log)
    assert defect is True
    assert reason == "tb_requires_spec_absent_port"


def test_positive_b_end_to_end_dataset_defect_excluded(tmp_path):
    """End-to-end through _score_shape_b: a spec-faithful candidate FAILs with
    compile_error (binds no res_ready) → dataset_defect=True,
    reason='tb_requires_spec_absent_port', EXCLUDED from charged-to-model. The
    verdict stays FAIL (never PASS)."""
    _need_tools()
    mod = _load()
    dataset = tmp_path / "ds"
    _mk_design(dataset, "div8", _DESC_8PORTS, _GOLDEN_WITH_RES_READY,
               _TB_BINDS_RES_READY, "verified_div8.v")
    samples = _mk_run(tmp_path, "div8.v", _CANDIDATE_SPEC_FAITHFUL)

    res = mod._score_shape_b("div8", samples, dataset, LAYOUT, ARGS)
    assert res["verdict"] == "FAIL"                       # NEVER flipped to PASS
    assert res.get("dataset_defect") is True
    assert res.get("dataset_defect_reason") == "tb_requires_spec_absent_port"
    assert res.get("reason") == "tb_requires_spec_absent_port"

    # the shape-agnostic dual-report excludes it from the charged-to-model count
    results = [res]
    npass = sum(1 for r in results if r["verdict"] == "PASS")
    n_ddef = sum(1 for r in results if r.get("dataset_defect"))
    n_eff_satisfiable = len(results) - n_ddef
    assert npass == 0 and n_ddef == 1 and n_eff_satisfiable == 0


# ============================ POSITIVE (a) ===================================
def test_positive_a_helper_compiles_false_when_tb_unsatisfiable(tmp_path):
    """A TB wiring a port NEITHER module declares → even golden(aliased)+TB
    fails to elaborate → compiles False."""
    _need_tools()
    mod = _load()
    _mk_design(tmp_path, "buf1", _DESC_2PORTS, _GOLDEN_BUF,
               _TB_GHOST_PORT, "verified_buf1.v")
    compiles, _ports = mod._golden_ref_compiles_with_tb_shape_b(
        "buf1", tmp_path, LAYOUT)
    assert compiles is False


def test_positive_a_audit_flags_golden_self_compile_defect(tmp_path):
    """golden+TB ALSO fails to elaborate → (True, 'golden_ref_fails_own_tb_compile')
    regardless of the candidate log content."""
    _need_tools()
    mod = _load()
    _mk_design(tmp_path, "buf1", _DESC_2PORTS, _GOLDEN_BUF,
               _TB_GHOST_PORT, "verified_buf1.v")
    cand_log = "testbench.v:3: error: port ``ghost'' is not a port of uut.\n"
    defect, reason = mod._unsatisfiable_tb_compile_audit_shape_b(
        "buf1", tmp_path, LAYOUT, cand_log)
    assert defect is True
    assert reason == "golden_ref_fails_own_tb_compile"


def test_positive_a_end_to_end_dataset_defect(tmp_path):
    """End-to-end: candidate compile_error on a buf1 whose own golden cannot
    satisfy the TB → dataset_defect=True, golden_ref_fails_own_tb_compile."""
    _need_tools()
    mod = _load()
    dataset = tmp_path / "ds"
    _mk_design(dataset, "buf1", _DESC_2PORTS, _GOLDEN_BUF,
               _TB_GHOST_PORT, "verified_buf1.v")
    samples = _mk_run(tmp_path, "buf1.v", _GOLDEN_BUF)  # no ghost port

    res = mod._score_shape_b("buf1", samples, dataset, LAYOUT, ARGS)
    assert res["verdict"] == "FAIL"
    assert res.get("reason") == "compile_error"          # reason kept for case (a)
    assert res.get("dataset_defect") is True
    assert res.get("dataset_defect_reason") == "golden_ref_fails_own_tb_compile"


# ===================== §4.05 NEGATIVE no-leak ===============================
def test_negative_genuine_syntax_error_stays_charged(tmp_path):
    """A genuine candidate SYNTAX error (golden+TB compiles fine; the error is NOT
    a missing port) → STILL charged: verdict FAIL, reason compile_error, NO
    dataset_defect flag."""
    _need_tools()
    mod = _load()
    dataset = tmp_path / "ds"
    _mk_design(dataset, "div8", _DESC_8PORTS, _GOLDEN_WITH_RES_READY,
               _TB_BINDS_RES_READY, "verified_div8.v")
    # candidate with a real syntax error (missing semicolon, no endmodule)
    broken = ("module div8(input clk, output res_valid);\n"
              "  assign res_valid = 1'b1\n")   # no ';' + no endmodule
    samples = _mk_run(tmp_path, "div8.v", broken)

    res = mod._score_shape_b("div8", samples, dataset, LAYOUT, ARGS)
    assert res["verdict"] == "FAIL"
    assert res.get("reason") == "compile_error"
    assert res.get("dataset_defect") is not True
    assert "dataset_defect_reason" not in res


def test_negative_audit_syntax_error_no_defect(tmp_path):
    """Helper-level: a candidate log that is NOT a 'port X is not a port of uut'
    error → (False, None) even though golden+TB compiles."""
    _need_tools()
    mod = _load()
    _mk_design(tmp_path, "div8", _DESC_8PORTS, _GOLDEN_WITH_RES_READY,
               _TB_BINDS_RES_READY, "verified_div8.v")
    cand_log = "div8.v:2: syntax error\ndiv8.v:2: error: malformed statement\n"
    assert mod._unsatisfiable_tb_compile_audit_shape_b(
        "div8", tmp_path, LAYOUT, cand_log) == (False, None)


def test_negative_missing_port_that_spec_declares_stays_charged(tmp_path):
    """A candidate that omits a port the SPEC DOES declare (res_valid) → the TB's
    missing-port error names a SPEC-DECLARED port → NOT a dataset defect → stays a
    model FAIL. (golden+TB compiles; the omission is the candidate's own bug.)"""
    _need_tools()
    mod = _load()
    _mk_design(tmp_path, "div8", _DESC_8PORTS, _GOLDEN_WITH_RES_READY,
               _TB_BINDS_RES_READY, "verified_div8.v")
    # res_valid IS in the spec ⇒ omitting it is the candidate's bug, not a defect
    cand_log = "testbench.v:5: error: port ``res_valid'' is not a port of uut.\n"
    defect, reason = mod._unsatisfiable_tb_compile_audit_shape_b(
        "div8", tmp_path, LAYOUT, cand_log)
    assert defect is False and reason is None


def test_negative_missing_port_not_in_golden_stays_charged(tmp_path):
    """If the candidate error names a port the GOLDEN does NOT declare (so the TB
    is not actually binding a golden-satisfiable port), it is NOT flagged — only a
    GOLDEN-declared, spec-absent port qualifies. Here the golden+TB DOES compile
    (TB binds res_ready which golden has); a bogus 'foo' port error is the
    candidate's own → (False, None)."""
    _need_tools()
    mod = _load()
    _mk_design(tmp_path, "div8", _DESC_8PORTS, _GOLDEN_WITH_RES_READY,
               _TB_BINDS_RES_READY, "verified_div8.v")
    cand_log = "testbench.v:5: error: port ``foo'' is not a port of uut.\n"
    defect, reason = mod._unsatisfiable_tb_compile_audit_shape_b(
        "div8", tmp_path, LAYOUT, cand_log)
    assert defect is False and reason is None


def test_negative_passing_candidate_unaffected(tmp_path):
    """A candidate that satisfies the TB (declares res_ready, drives res_valid)
    PASSes and is never audited/flagged."""
    _need_tools()
    mod = _load()
    dataset = tmp_path / "ds"
    _mk_design(dataset, "div8", _DESC_8PORTS, _GOLDEN_WITH_RES_READY,
               _TB_BINDS_RES_READY, "verified_div8.v")
    # a candidate that DOES expose res_ready and passes the TB
    good = (
        "module div8(\n"
        "  input clk, input rst, input sign,\n"
        "  input [7:0] dividend, input [7:0] divisor,\n"
        "  input opn_valid, input res_ready,\n"
        "  output res_valid, output [15:0] result\n"
        ");\n"
        "  assign res_valid = res_ready;\n"
        "  assign result = 16'd0;\n"
        "endmodule\n"
    )
    samples = _mk_run(tmp_path, "div8.v", good)
    res = mod._score_shape_b("div8", samples, dataset, LAYOUT, ARGS)
    assert res["verdict"] == "PASS"
    assert res.get("dataset_defect") is not True


def test_negative_runtime_path_unchanged_for_noncompile_fail(tmp_path):
    """§4.05: the #679 RUNTIME audit path is unchanged. A NON-compile FAIL
    (no_pass_marker) still routes to the runtime golden helper, NOT the compile
    audit. Here the golden PASSes its own TB at runtime, so a wrong candidate
    stays a real model FAIL with NO dataset_defect."""
    _need_tools()
    mod = _load()
    dataset = tmp_path / "ds"
    # a SATISFIABLE design: golden passes its own TB; candidate is just wrong.
    desc = "Module name:\n    dff\nInput ports:\n    a: in.\nOutput ports:\n    y: out.\n"
    golden = "module dff(input a, output y);\n  assign y = a;\nendmodule\n"
    tb = (
        "module dff_tb;\n  reg a; wire y;\n  dff uut(.a(a), .y(y));\n"
        "  initial begin a=1'b1; #1;\n"
        "    if (y===1'b1) $display(\"Your Design Passed\");\n"
        "    else $display(\"Failed\"); $finish; end\nendmodule\n"
    )
    d = dataset / "dff"
    d.mkdir(parents=True)
    (d / LAYOUT["prompt_filename"]).write_text(desc)
    (d / LAYOUT["tb_filename"]).write_text(tb)
    (d / "verified_dff.v").write_text(golden)
    # wrong candidate: compiles cleanly but y is inverted ⇒ no_pass_marker FAIL
    samples = _mk_run(tmp_path, "dff.v",
                      "module dff(input a, output y);\n  assign y = ~a;\nendmodule\n")

    res = mod._score_shape_b("dff", samples, dataset, LAYOUT, ARGS)
    assert res["verdict"] == "FAIL"
    assert res.get("reason") != "compile_error"     # runtime FAIL, not compile
    assert res.get("dataset_defect") is not True     # golden passes ⇒ real FAIL


def test_negative_always_topmodule_compile_audit_still_works(tmp_path):
    """The VerilogEval-class always_TopModule compile-audit path is untouched: a
    defective _test.sv (binds a port the golden ref never declares) still resolves
    to False; a well-formed one to True; the ref_glob generalization did not break
    the suffix layout."""
    _need_tools()
    mod = _load()
    layout_c = {
        "ref_suffix": "_ref.sv",
        "tb_suffix": "_test.sv",
        "prompt_suffix": "_prompt.txt",
        "module_name_strategy": "always_TopModule",
    }
    ref = "module RefModule(input a, output y);\n  assign y=a;\nendmodule\n"
    tb_ok = (
        "module tb;\n  reg a; wire yr, yd;\n"
        "  RefModule g(.a(a), .y(yr));\n  TopModule d(.a(a), .y(yd));\n"
        "  initial begin a=0; #1 $display(\"Mismatches: 0 in 1 samples\"); $finish; end\n"
        "endmodule\n"
    )
    tb_bad = tb_ok.replace(".y(yr)", ".z(yr)")  # golden has no port z
    (tmp_path / "P_ref.sv").write_text(ref)
    (tmp_path / "P_test.sv").write_text(tb_ok)
    assert mod._golden_ref_self_compiles("P", tmp_path, layout_c) is True
    (tmp_path / "P_test.sv").write_text(tb_bad)
    assert mod._golden_ref_self_compiles("P", tmp_path, layout_c) is False


def test_negative_self_compiles_none_for_suffix_layout_without_glob(tmp_path):
    """Backward-compat: a layout with ref_suffix/tb_suffix but a NON-always
    strategy and NO ref_glob → still None (the Shape-B branch requires ref_glob,
    so it does not hijack the existing suffix-layout None contract)."""
    mod = _load()
    layout = {
        "ref_suffix": "_ref.sv",
        "tb_suffix": "_test.sv",
        "prompt_suffix": "_prompt.txt",
        "module_name_strategy": "from_description_module_name_line",
    }
    (tmp_path / "P_ref.sv").write_text(
        "module RefModule(input a, output y);\n  assign y=a;\nendmodule\n")
    (tmp_path / "P_test.sv").write_text(
        "module tb;\n  reg a; wire y;\n  RefModule g(.a(a), .y(y));\n"
        "  initial begin a=0; #1 $finish; end\nendmodule\n")
    assert mod._golden_ref_self_compiles("P", tmp_path, layout) is None


def test_self_compiles_shape_b_layout_makes_determination(tmp_path):
    """The #690 generalization: _golden_ref_self_compiles now ALSO determines on
    the ref_glob / from_description Shape-B layout (no longer always_TopModule-
    only): True for a satisfiable golden+TB, False for the (a)-shape."""
    _need_tools()
    mod = _load()
    _mk_design(tmp_path, "div8", _DESC_8PORTS, _GOLDEN_WITH_RES_READY,
               _TB_BINDS_RES_READY, "verified_div8.v")
    assert mod._golden_ref_self_compiles("div8", tmp_path, LAYOUT) is True
    _mk_design(tmp_path, "buf1", _DESC_2PORTS, _GOLDEN_BUF,
               _TB_GHOST_PORT, "verified_buf1.v")
    assert mod._golden_ref_self_compiles("buf1", tmp_path, LAYOUT) is False
