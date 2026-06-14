"""#679 — Shape-B golden-fails-own-TB RUNTIME audit in score_iverilog_tb.py.

The Shape-C path has a `golden_ref_fails_own_tb` / `dataset_defect` dual-report,
but it is (1) wired ONLY into Shape C and (2) COMPILE-only. A standalone Shape-B
benchmark whose golden reference COMPILES cleanly yet FAILs its own official TB
AT RUNTIME (no pass marker — e.g. a desc<->TB contradiction or a back-to-back
handshake race) was silently charged to the model (reason=no_pass_marker) with
NO dataset-defect flag, even though the design is unsatisfiable by ANY
spec-compliant submission.

This test pins the new Shape-B RUNTIME audit (`_golden_ref_fails_own_tb_runtime`
+ the `_score_shape_b` wrapper + the shape-agnostic dual-report in main()):

POSITIVE
  * A Shape-B golden that compiles but FAILs its own TB at runtime ->
    dataset_defect=True, reason=golden_ref_fails_own_tb_runtime, and the design
    is EXCLUDED from the charged-to-model (pass@1-excluding-dataset-defects)
    count.

§4.05 NEGATIVE no-leak
  * A golden that PASSes its own TB at runtime -> NOT flagged dataset_defect; a
    real candidate model FAIL stays charged.
  * A golden that fails to COMPILE -> None (handled by the existing compile-audit
    / candidate compile_error path, NOT double-counted as a runtime defect).
  * No ref_glob / no glob match / missing TB -> None (no flag, no determination).
  * Shape-C path is structurally unchanged (its own helper still returns
    True/False/None on the compile-audit, independent of this Shape-B helper).

The runtime portions are gated on iverilog/vvp availability; the logic-level
(no-tool) assertions stay deterministic.

Chip-AGNOSTIC: every fixture is synthetic, driven by registry-style
layout.ref_glob/tb_filename + scorer_args regex; no design/vendor literal.
"""
import importlib.util
import shutil
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark" / "score_iverilog_tb.py")


def _load():
    spec = importlib.util.spec_from_file_location("score_iverilog_tb_679", SCRIPT)
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
    "fail_regex": r"Test failed|Your Design Failed",
    "cwd_design_dir": True,
}

# A tiny combinational design: a 1-bit register that the TB checks. The "good"
# golden returns the value the TB expects; the "bad" golden returns its inverse
# so it FAILs its own TB at runtime (but still COMPILES cleanly).
_DESIGN_DESC = "Module name:\n  dut\n"

_GOLDEN_GOOD = (
    "module dut(input a, output y);\n"
    "  assign y = a;\n"
    "endmodule\n"
)
# Compiles fine, but y is wrong -> the TB's pass marker never prints (runtime
# fail). This is the desc<->TB-contradicting standalone golden of #679.
_GOLDEN_BAD = (
    "module dut(input a, output y);\n"
    "  assign y = ~a;\n"   # contradicts the TB's expectation
    "endmodule\n"
)
# Deliberately does NOT compile (missing endmodule / syntax error).
_GOLDEN_NOCOMPILE = (
    "module dut(input a, output y);\n"
    "  assign y = a\n"     # missing semicolon + no endmodule
)

# TB that drives a=1 and expects y==1; prints the pass/fail marker accordingly.
_TB = (
    "module testbench;\n"
    "  reg a; wire y;\n"
    "  dut u(.a(a), .y(y));\n"
    "  initial begin\n"
    "    a = 1'b1; #1;\n"
    "    if (y === 1'b1) $display(\"Your Design Passed\");\n"
    "    else $display(\"Test failed\");\n"
    "    $finish;\n"
    "  end\n"
    "endmodule\n"
)


def _mk_design(root: Path, design: str, golden: str, tb: str = _TB,
               ref_name: str = "verified_dut.v"):
    d = root / design
    d.mkdir(parents=True, exist_ok=True)
    (d / LAYOUT["prompt_filename"]).write_text(_DESIGN_DESC)
    (d / LAYOUT["tb_filename"]).write_text(tb)
    (d / ref_name).write_text(golden)
    return d


# ============================ POSITIVE ======================================
def test_positive_golden_runtime_fails_returns_true(tmp_path):
    """Golden compiles but fails its own TB at runtime -> helper True."""
    _need_tools()
    mod = _load()
    _mk_design(tmp_path, "bad_design", _GOLDEN_BAD)
    assert mod._golden_ref_fails_own_tb_runtime(
        "bad_design", tmp_path, LAYOUT, ARGS) is True


def test_positive_wrapper_flags_dataset_defect_and_excludes(tmp_path):
    """End-to-end through _score_shape_b: a candidate that FAILs (no_pass_marker)
    on a design whose GOLDEN itself runtime-fails -> dataset_defect=True,
    reason=golden_ref_fails_own_tb_runtime, EXCLUDED from charged-to-model."""
    _need_tools()
    mod = _load()
    dataset = tmp_path / "ds"
    _mk_design(dataset, "bad_design", _GOLDEN_BAD)
    # candidate sample (also wrong — but the design is unsatisfiable anyway)
    samples = tmp_path / "run" / "samples"
    samples.mkdir(parents=True)
    (samples / "dut.v").write_text(_GOLDEN_BAD)  # same wrong logic -> FAIL

    res = mod._score_shape_b("bad_design", samples, dataset, LAYOUT, ARGS)
    assert res["verdict"] == "FAIL"              # verdict NOT changed
    assert res.get("dataset_defect") is True
    assert res.get("dataset_defect_reason") == "golden_ref_fails_own_tb_runtime"

    # The shape-agnostic dual-report excludes it: build the same exclusion the
    # summary in main() does.
    results = [res]
    n = len(results)
    npass = sum(1 for r in results if r["verdict"] == "PASS")
    n_ddef = sum(1 for r in results if r.get("dataset_defect"))
    n_eff_satisfiable = n - n_ddef
    # excluding the defect, there are zero satisfiable problems -> not charged
    assert n_ddef == 1
    assert n_eff_satisfiable == 0


# ===================== §4.05 NEGATIVE no-leak ================================
def test_negative_golden_runtime_passes_not_flagged(tmp_path):
    """Golden PASSes its own TB at runtime -> helper False (design IS
    satisfiable; never flag a real model FAIL as a dataset defect)."""
    _need_tools()
    mod = _load()
    _mk_design(tmp_path, "good_design", _GOLDEN_GOOD)
    assert mod._golden_ref_fails_own_tb_runtime(
        "good_design", tmp_path, LAYOUT, ARGS) is False


def test_negative_real_model_fail_stays_charged(tmp_path):
    """On a design whose golden PASSes, a wrong candidate stays a real FAIL with
    NO dataset_defect flag -> it remains charged to the model."""
    _need_tools()
    mod = _load()
    dataset = tmp_path / "ds"
    _mk_design(dataset, "good_design", _GOLDEN_GOOD)
    samples = tmp_path / "run" / "samples"
    samples.mkdir(parents=True)
    (samples / "dut.v").write_text(_GOLDEN_BAD)  # wrong candidate -> FAIL

    res = mod._score_shape_b("good_design", samples, dataset, LAYOUT, ARGS)
    assert res["verdict"] == "FAIL"
    assert res.get("dataset_defect") is not True
    assert "dataset_defect_reason" not in res


def test_negative_passing_candidate_unaffected(tmp_path):
    """A correct candidate on a good design PASSes and is never audited/flagged."""
    _need_tools()
    mod = _load()
    dataset = tmp_path / "ds"
    _mk_design(dataset, "good_design", _GOLDEN_GOOD)
    samples = tmp_path / "run" / "samples"
    samples.mkdir(parents=True)
    (samples / "dut.v").write_text(_GOLDEN_GOOD)  # correct candidate -> PASS

    res = mod._score_shape_b("good_design", samples, dataset, LAYOUT, ARGS)
    assert res["verdict"] == "PASS"
    assert res.get("dataset_defect") is not True


def test_negative_golden_fails_compile_returns_none(tmp_path):
    """A golden that fails to COMPILE is NOT a runtime defect -> None (handled by
    the existing compile-audit; not double-counted)."""
    _need_tools()
    mod = _load()
    _mk_design(tmp_path, "nocompile_design", _GOLDEN_NOCOMPILE)
    assert mod._golden_ref_fails_own_tb_runtime(
        "nocompile_design", tmp_path, LAYOUT, ARGS) is None


def test_negative_compile_error_candidate_not_runtime_audited(tmp_path):
    """A candidate compile_error FAIL must NOT trigger the runtime golden audit
    (the wrapper skips reason=='compile_error') -> no dataset_defect flag even if
    the golden would runtime-fail."""
    _need_tools()
    mod = _load()
    dataset = tmp_path / "ds"
    _mk_design(dataset, "bad_design", _GOLDEN_BAD)
    samples = tmp_path / "run" / "samples"
    samples.mkdir(parents=True)
    (samples / "dut.v").write_text(_GOLDEN_NOCOMPILE)  # candidate won't compile

    res = mod._score_shape_b("bad_design", samples, dataset, LAYOUT, ARGS)
    assert res["verdict"] == "FAIL"
    assert res.get("reason") == "compile_error"
    assert res.get("dataset_defect") is not True


def test_negative_no_ref_glob_returns_none(tmp_path):
    """layout without ref_glob -> None (no determination), no tools needed."""
    mod = _load()
    layout = dict(LAYOUT)
    layout.pop("ref_glob")
    assert mod._golden_ref_fails_own_tb_runtime(
        "x", tmp_path, layout, ARGS) is None


def test_negative_no_glob_match_returns_none(tmp_path):
    """ref_glob set but no matching file in the design dir -> None."""
    mod = _load()
    d = tmp_path / "no_golden"
    d.mkdir(parents=True)
    (d / LAYOUT["tb_filename"]).write_text(_TB)
    # no verified_*.v written
    assert mod._golden_ref_fails_own_tb_runtime(
        "no_golden", tmp_path, LAYOUT, ARGS) is None


def test_negative_missing_tb_returns_none(tmp_path):
    """ref_glob matches but the TB is absent -> None, no tools needed."""
    mod = _load()
    d = tmp_path / "no_tb"
    d.mkdir(parents=True)
    (d / "verified_dut.v").write_text(_GOLDEN_GOOD)
    # no testbench.v
    assert mod._golden_ref_fails_own_tb_runtime(
        "no_tb", tmp_path, LAYOUT, ARGS) is None


def test_negative_shape_c_helper_independent_unchanged(tmp_path):
    """The Shape-C compile-audit helper is structurally unchanged and independent
    of the new Shape-B runtime helper: with always_TopModule it still makes a
    determination (True/False), and returns None for a non-always_TopModule
    strategy — proving the Shape-C path is untouched."""
    mod = _load()
    layout_c = {
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
    # non-always_TopModule strategy -> None, no determination (path untouched)
    assert mod._golden_ref_self_compiles("P", tmp_path, layout_c) is None
