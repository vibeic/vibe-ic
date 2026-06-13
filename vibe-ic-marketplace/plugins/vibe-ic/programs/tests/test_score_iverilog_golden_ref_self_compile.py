"""Tests for the golden-ref self-compile dataset-defect gate in score_iverilog_tb.py.

Bucket-A capture (benchmark-enhancement-capture): when a Shape-C problem fails,
the scorer also compiles the golden RefModule + the hidden TB WITHOUT the
candidate (aliasing the ref to the DUT module name as a stand-in). If even that
golden-vs-golden compile fails, the problem is an irreducible benchmark defect
(the official reference cannot satisfy its own testbench — e.g. the TB wires
ports neither module declares) and is flagged dataset_defect=true. The verdict is
NOT changed (dual report only); never inflate the pass rate.

The pure-python helper is gated on iverilog (skips when absent). Corpus-sweep
result that motivated it: across all 156 VerilogEval-v2 + 156 Human problems the
gate fired on exactly one (the Y2/Y4-vs-Y1/Y3 defect) and zero false positives.
"""
import importlib.util
import shutil
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark" / "score_iverilog_tb.py")

LAYOUT = {
    "ref_suffix": "_ref.sv",
    "tb_suffix": "_test.sv",
    "prompt_suffix": "_prompt.txt",
    "module_name_strategy": "always_TopModule",
}


def _load():
    spec = importlib.util.spec_from_file_location("score_iverilog_tb", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _need_iverilog():
    if not shutil.which("iverilog"):
        pytest.skip("iverilog not installed")


_REF = "module RefModule(input a, output y);\n  assign y = a;\nendmodule\n"

# Well-formed TB: instantiates BOTH the golden RefModule and the candidate
# TopModule with ports that both declare.
_TB_OK = (
    "module tb;\n"
    "  reg a; wire y_ref, y_dut;\n"
    "  RefModule good1(.a(a), .y(y_ref));\n"
    "  TopModule dut(.a(a), .y(y_dut));\n"
    "  initial begin a=0; #1 $display(\"Mismatches: 0 in 1 samples\"); $finish; end\n"
    "endmodule\n"
)

# Defective TB: wires .z() to the golden module, which has no port z — even the
# golden reference cannot elaborate against this TB (Prob099-class defect).
_TB_DEFECT = (
    "module tb;\n"
    "  reg a; wire y_ref, y_dut;\n"
    "  RefModule good1(.a(a), .z(y_ref));\n"
    "  TopModule dut(.a(a), .y(y_dut));\n"
    "  initial begin a=0; #1 $display(\"Mismatches: 0 in 1 samples\"); $finish; end\n"
    "endmodule\n"
)


def _mk(ds: Path, prob: str, ref: str, tb: str):
    (ds / f"{prob}_ref.sv").write_text(ref)
    (ds / f"{prob}_test.sv").write_text(tb)


def test_well_formed_golden_ref_compiles_true(tmp_path):
    _need_iverilog()
    mod = _load()
    _mk(tmp_path, "ProbX", _REF, _TB_OK)
    assert mod._golden_ref_self_compiles("ProbX", tmp_path, LAYOUT) is True


def test_defective_tb_golden_ref_fails_false(tmp_path):
    """TB wires a port the golden ref never declares -> even golden ref+alias
    cannot compile -> irreducible defect -> False."""
    _need_iverilog()
    mod = _load()
    _mk(tmp_path, "ProbX", _REF, _TB_DEFECT)
    assert mod._golden_ref_self_compiles("ProbX", tmp_path, LAYOUT) is False


def test_returns_none_when_not_always_topmodule(tmp_path):
    """Scoped to the always_TopModule strategy; any other strategy -> None (no
    determination, no flag) without even invoking iverilog."""
    mod = _load()
    _mk(tmp_path, "ProbX", _REF, _TB_OK)
    layout = dict(LAYOUT, module_name_strategy="from_description_module_name_line")
    assert mod._golden_ref_self_compiles("ProbX", tmp_path, layout) is None


def test_returns_none_when_ref_or_tb_missing(tmp_path):
    mod = _load()
    # only the ref exists, no _test.sv
    (tmp_path / "ProbX_ref.sv").write_text(_REF)
    assert mod._golden_ref_self_compiles("ProbX", tmp_path, LAYOUT) is None


def test_returns_none_when_ref_module_already_named_topmodule(tmp_path):
    """If the ref's own module is already 'TopModule' we cannot build a distinct
    alias -> None (avoid a spurious duplicate-module compile error)."""
    mod = _load()
    _mk(tmp_path, "ProbX",
        "module TopModule(input a, output y);\n  assign y=a;\nendmodule\n", _TB_OK)
    assert mod._golden_ref_self_compiles("ProbX", tmp_path, LAYOUT) is None
