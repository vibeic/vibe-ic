"""Unit tests for synth_wrapper_check.py.

Tests verify correct detection of valid wrappers, missing wrappers with/without
inout ports, stub wrappers, and wrappers without module declarations.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'synth_wrapper_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import synth_wrapper_check as swc  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: valid wrapper with module declaration and DUT instantiation
# ---------------------------------------------------------------------------
VALID_WRAPPER = """\
module synth_wrapper (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  data_in,
    output wire [7:0]  data_out,
    inout  wire        sda
);

    wire sda_oe, sda_out, sda_in;

    assign sda    = sda_oe ? sda_out : 1'bz;
    assign sda_in = sda;

    my_design u_dut (
        .clk      (clk),
        .rst_n    (rst_n),
        .data_in  (data_in),
        .data_out (data_out),
        .sda_oe   (sda_oe),
        .sda_out  (sda_out),
        .sda_in   (sda_in)
    );

endmodule
"""


# ---------------------------------------------------------------------------
# Test 1: Valid wrapper → PASS
# ---------------------------------------------------------------------------
def test_valid_wrapper_pass(tmp_path):
    (tmp_path / "synth_wrapper.v").write_text(VALID_WRAPPER)

    result = swc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["valid_wrappers"] >= 1
    assert result.summary["errors"] == 0


# ---------------------------------------------------------------------------
# Test 2: No wrapper files, no inout in design → PASS (INFO)
# ---------------------------------------------------------------------------
def test_no_wrapper_no_inout_pass(tmp_path):
    design = """\
module simple_design (
    input  wire       clk,
    input  wire       rst_n,
    output wire [7:0] data_out
);
    assign data_out = 8'hFF;
endmodule
"""
    (tmp_path / "simple_design.v").write_text(design)

    result = swc.audit(str(tmp_path))
    assert result.passed is True
    infos = [f for f in result.findings if f.severity == "INFO"]
    assert any(f.rule == "NO_INOUT_DESIGN" for f in infos)


# ---------------------------------------------------------------------------
# Test 3: No wrapper but design has inout → FAIL
# ---------------------------------------------------------------------------
def test_no_wrapper_with_inout_fail(tmp_path):
    design = """\
module i2c_master (
    input  wire clk,
    input  wire rst_n,
    inout  wire sda,
    output wire scl
);
    assign sda = 1'bz;
    assign scl = 1'b1;
endmodule
"""
    (tmp_path / "i2c_master.v").write_text(design)

    result = swc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_WRAPPER" for f in errors)


# ---------------------------------------------------------------------------
# Test 4: Stub wrapper (< 5 code lines) → FAIL
# ---------------------------------------------------------------------------
def test_stub_wrapper_fail(tmp_path):
    stub = """\
// TODO: implement wrapper
module synth_wrapper;
endmodule
"""
    (tmp_path / "synth_wrapper.v").write_text(stub)

    result = swc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "STUB_FILE" for f in errors)


# ---------------------------------------------------------------------------
# Test 5: Wrapper without module keyword → FAIL
# ---------------------------------------------------------------------------
def test_no_module_decl_fail(tmp_path):
    no_module = """\
// This file has no valid top-level block
wire clk;
wire rst_n;
wire [7:0] data_in;
wire [7:0] data_out;
wire sda;
assign data_out = data_in;
assign sda = 1'bz;
// Just loose wires, not a proper wrapper
wire extra1;
wire extra2;
"""
    (tmp_path / "synth_wrapper.v").write_text(no_module)

    result = swc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_MODULE_DECL" for f in errors)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


# --- the exit code, and the argv that made it undrivable

def test_main_takes_argv_at_all():
    """`gate_cli_mutation_probe` reported this gate SILENT, and the cause was
    that no test COULD drive it: `def main():` read `sys.argv` unconditionally.

    Third instance today, after `dispatcher_awake_gate_check` and
    `foundry_signoff_plan_check`, out of the 48 gates here declaring main that
    way.
    """
    import inspect
    import synth_wrapper_check as S
    assert "argv" in inspect.signature(S.main).parameters


def test_main_exits_non_zero_on_a_failing_audit(tmp_path, monkeypatch):
    """`main()` calls `sys.exit()` rather than returning, so the exit code is
    raised — and a test that ignores SystemExit measures nothing."""
    import pytest
    import synth_wrapper_check as S

    class _R:
        passed = False
        findings = []
        summary = "wrapper missing"
    monkeypatch.setattr(S, "audit", lambda d: _R())
    with pytest.raises(SystemExit) as e:
        S.main([str(tmp_path)])
    assert e.value.code == 1


def test_main_exits_zero_when_the_audit_passes(tmp_path, monkeypatch):
    """The other direction, or the test above is met by always failing."""
    import pytest
    import synth_wrapper_check as S

    class _R:
        passed = True
        findings = []
        summary = "ok"
    monkeypatch.setattr(S, "audit", lambda d: _R())
    with pytest.raises(SystemExit) as e:
        S.main([str(tmp_path)])
    assert e.value.code == 0
