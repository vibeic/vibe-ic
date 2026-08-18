"""Unit tests for assertion_property_check.py.

Tests verify correct detection of valid SVA files, missing assertion files,
missing property declarations, stub files, and empty directories.
"""
import sys
from pathlib import Path

import pytest
import sys

PROG_DIR = Path(__file__).resolve().parent.parent

SCRIPT = Path(__file__).parent.parent / 'assertion_property_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import assertion_property_check as apc  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: a valid SVA file with property + assert property (>10 lines)
# ---------------------------------------------------------------------------
VALID_SVA = """\
// SystemVerilog Assertions for UART TX
module uart_tx_sva (
    input wire clk,
    input wire rst_n,
    input wire tx_start,
    input wire tx_busy,
    input wire tx_done
);

    // Property: tx_busy must assert within 2 cycles of tx_start
    property p_tx_busy_after_start;
        @(posedge clk) disable iff (!rst_n)
        tx_start |-> ##[1:2] tx_busy;
    endproperty

    // Property: tx_done must eventually follow tx_busy
    property p_tx_done_after_busy;
        @(posedge clk) disable iff (!rst_n)
        tx_busy |-> ##[1:100] tx_done;
    endproperty

    assert property (p_tx_busy_after_start)
        else $error("tx_busy did not assert after tx_start");

    assert property (p_tx_done_after_busy)
        else $error("tx_done did not follow tx_busy");

endmodule
"""


# ---------------------------------------------------------------------------
# Test 1: Valid SVA file → PASS
# ---------------------------------------------------------------------------
def test_valid_sva_pass(tmp_path):
    (tmp_path / "uart_tx_sva.sv").write_text(VALID_SVA)

    result = apc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["valid_files"] >= 1


# ---------------------------------------------------------------------------
# Test 2: No .sv/.sva files → FAIL
# ---------------------------------------------------------------------------
def test_no_assertion_files_fail(tmp_path):
    # Create a non-assertion file
    (tmp_path / "design.v").write_text("module top(); endmodule")

    result = apc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_ASSERTION_FILE" for f in errors)


# ---------------------------------------------------------------------------
# Test 3: .sv file with assert but no property declaration → FAIL
# ---------------------------------------------------------------------------
def test_no_property_decl_fail(tmp_path):
    sv_content = """\
// Assertions without property declarations
module check_sva (
    input wire clk,
    input wire rst_n,
    input wire data_valid,
    input wire data_ready,
    input wire ack,
    input wire req,
    input wire busy,
    input wire done,
    input wire error
);

    // Immediate assertions only (no property keyword)
    always @(posedge clk) begin
        assert (data_valid || !data_ready)
            else $error("data not valid when ready");
        assert (req |-> !error)
            else $error("error during request");
    end

endmodule
"""
    (tmp_path / "check_sva.sv").write_text(sv_content)

    result = apc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_PROPERTY_DECL" or f.rule == "NO_ASSERT_PROPERTY"
               for f in errors)


# ---------------------------------------------------------------------------
# Test 4: Stub file → FAIL. A stub is a file that ASSERTS NOTHING.
#
# EXPECTATION DELIBERATELY CHANGED, and this is the honest record of it.
# This test used to assert that the file below — which declares a property,
# asserts it, and closes its module — must FAIL as a STUB_FILE, purely because
# it is 7 non-empty lines and the rule was `<= 10 lines`. That fixture is a
# COMPLETE assertions file; it is merely a small one.
#
# The rule was measuring the wrong thing. professional_tb_gen emitted 2 lines
# per output port, so line count = 2 + n_outputs, and STUB_FILE was really
# reporting "this design has fewer than 9 outputs". A real 5-output design
# (subservient) was failed by it. The test encoded that proxy rather than the
# property, so keeping it would have pinned the defect in place.
#
# What replaces it is stricter in the case that matters: a file that asserts
# nothing now fails AT ANY LENGTH, where before a 40-line file of comments and
# TODOs passed this check.
# ---------------------------------------------------------------------------
def test_stub_file_fail(tmp_path):
    """Asserts nothing → STUB_FILE, however long it is."""
    # Contains the word "property" so the audit DISCOVERS it as an assertion
    # file (discovery keys on 'assert'/'property'); it just never asserts one.
    # This is the real shape professional_tb_gen emits for prose it could not
    # formalise: `// TODO(spec-to-assertion): ...`.
    stub_sv = """\
// Assertion file for foo -- TODO(spec-to-assertion): formalise these.
module foo_asserts;
    // TODO(spec-to-assertion): property -- reset implies outputs known
    // TODO(spec-to-assertion): property -- handshake never deadlocks
    // TODO(spec-to-assertion): property -- fifo never overflows
    initial begin
        $display("placeholder");
    end
endmodule
"""
    (tmp_path / "stub_sva.sv").write_text(stub_sv)

    result = apc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "STUB_FILE" for f in errors)


def test_long_file_that_asserts_nothing_is_still_a_stub(tmp_path):
    """The strictening: 40 lines of TODOs used to PASS the <=10-line rule."""
    body = "\n".join(f"    // TODO({i}): formalise property {i}" for i in range(40))
    (tmp_path / "long_stub.sv").write_text(
        f"module long_stub;\n{body}\nendmodule\n")
    result = apc.audit(str(tmp_path))
    assert result.passed is False
    assert any(f.rule == "STUB_FILE" and f.severity == "ERROR"
               for f in result.findings)


def test_small_but_complete_assertion_file_is_not_a_stub(tmp_path):
    """The old fixture, and the exact shape a few-output design produces.

    A complete assertions file must not be failed for the design having had
    few output ports."""
    complete_sv = """\
// Assertion file for a design with one output
module small_sva;
    property p1;
        @(posedge clk) 1;
    endproperty
    assert property (p1);
endmodule
"""
    (tmp_path / "small_sva.sv").write_text(complete_sv)

    result = apc.audit(str(tmp_path))
    assert not [f for f in result.findings
                if f.severity == "ERROR" and f.rule == "STUB_FILE"]
    assert result.passed is True


# ---------------------------------------------------------------------------
# Test 5: Empty directory → FAIL
# ---------------------------------------------------------------------------
def test_empty_dir_fail(tmp_path):
    result = apc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_ASSERTION_FILE" for f in errors)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


# ---------------------------------------------------------------------------
# END-TO-END: professional_tb_gen's output must satisfy assertion_property_check
#
# These are the plugin's own SVA producer and its own SVA checker, and they
# DISAGREED. The generator emitted the inline form
#     A_x_known: assert property (@(posedge clk) disable iff (r) !$isunknown(x));
# while the checker looks for a declaration via `\bproperty\s+\w+`. In
# `assert property (` the token after `property` is `(`, so the checker could
# never match the generator — every design failed NO_PROPERTY_DECL while the
# SAME file's ASSERT_COUNT cheerfully reported the assertions it had just
# refused to see. Nothing tested the two together, which is why it survived.
# ---------------------------------------------------------------------------
def _gen_asserts(tmp_path, n_outputs):
    """Emit assertions the way professional_tb_gen does, for n outputs."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ptg", str(PROG_DIR / "professional_tb_gen.py"))
    ptg = importlib.util.module_from_spec(spec)
    sys.modules["ptg"] = ptg
    spec.loader.exec_module(ptg)
    shape = {
        "top": "dut",
        "cr": {"clk": "clk", "rst": "rst_n", "edge": "posedge",
               "active_high": False},
        "ports": ([{"name": "clk", "dir": "input"},
                   {"name": "rst_n", "dir": "input"}]
                  + [{"name": f"o{i}", "dir": "output"}
                     for i in range(n_outputs)]),
    }
    text, _l29 = ptg.build_assertions(tmp_path, shape)
    return text


@pytest.mark.parametrize("n_outputs", [1, 3, 5, 20])
def test_generated_assertions_satisfy_the_checker(tmp_path, n_outputs):
    """At ANY output count -- 5 is subservient, the design this was found on."""
    out = tmp_path / "gen"
    out.mkdir()
    try:
        text = _gen_asserts(tmp_path, n_outputs)
    except Exception as exc:                      # pragma: no cover
        pytest.skip(f"generator not callable in isolation: {exc}")
    (out / "dut_asserts.sva").write_text(text)

    result = apc.audit(str(out))
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert not errors, f"{n_outputs} outputs -> {[(f.rule, f.message) for f in errors]}"
    assert result.passed is True
