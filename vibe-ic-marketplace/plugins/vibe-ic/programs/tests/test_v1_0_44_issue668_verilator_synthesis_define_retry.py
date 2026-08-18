"""ORGANIC #668 — SIM-path verilator escape hardcoded -DSIMULATION, elaborating
dead sim-only `ifdef SIMULATION arms.

A REUSED-IP closure contains a primitive-library module with an `ifdef SIMULATION
arm using sim-only constructs (std::randomize()/$urandom) and a synthesizable
`else passthrough. `_verilator_sim_escape` built the TB+RTL with a hardcoded
-DSIMULATION, so verilator compiled the sim-only arm and died on a
sim-only-construct error (e.g. "Duplicate declaration of signal: stdrand"), even
though that arm is functionally DEAD and the IDENTICAL closure elaborates + runs
to $finish under -DSYNTHESIS (the SAME define the synth slang path already uses).
`decide_sv2v_tb_define` only flips to SYNTHESIS on an include HOLE, and the #657
escape only fires on an SVA signature; neither covered this, and the escape never
tried -DSYNTHESIS.

Fix: `synth_frontend.verilator_should_retry_synthesis_define` returns True iff
verilator's stderr carries a sim-only-construct signature; `_verilator_sim_escape`
then retries the SAME closure under -DSYNTHESIS before declaring the honest FAIL.

Positive: a std::randomize / $urandom failure under -DSIMULATION → retry.
NO-LEAK: an SVA / generic / real-RTL-defect failure (the #657 positive case
included) does NOT trigger the retry; a closure that ALSO fails under -DSYNTHESIS
keeps the honest FAIL. The escape's build/run path is structured so the
SIMULATION build is tried FIRST and a clean build returns immediately (the #657
SVA closure path is unchanged).

chip-AGNOSTIC: verilator tool error-token + the standard randomisation-helper
vocabulary + the standard SIMULATION/SYNTHESIS define names; no chip/vendor/file
literal.
"""
import inspect
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import synth_frontend as SF  # noqa: E402
import design_one_shot_runner as R  # noqa: E402


# the field-agent's EXACT verilator stderr (round-4 reproduction):
SIMONLY_ERR = ("%Error: prim_cdc_rand_delay.sv:17:8: Duplicate declaration of "
               "signal: stdrand")

# v1.4.x — the retry is now decided by the OBSERVABLE (no output produced) plus
# the DESIGN PROPERTY (the closure branches on the define set), NOT by the tool's
# phrasing. These tests supply the RTL that MAKES the scenario real; the error
# string is passed for the log line only. See synth_frontend's doctrine block.
_SIMONLY_RTL = (
    "module prim_cdc_rand_delay(input clk, input d, output q);\n"
    "`ifdef SIMULATION\n"
    "  int dly;\n"
    "  always_ff @(posedge clk) dly <= $urandom_range(0, 3);\n"
    "  assign q = d ^ (dly == 0);\n"
    "`else\n"
    "  logic qq; always_ff @(posedge clk) qq <= d; assign q = qq;\n"
    "`endif\n"
    "endmodule\n")
_PLAIN_TB = ("module tb; initial begin #10; $display(\"TB_DONE\"); $finish; "
             "end endmodule\n")



# ── classifier: fires on sim-only constructs only ───────────────────────────

def test_retry_on_duplicate_stdrand():
    ok, reason = SF.verilator_should_retry_synthesis_define(
        SIMONLY_ERR, rtl_text_blob=_SIMONLY_RTL, tb_text=_PLAIN_TB)
    assert ok is True, reason


def test_retry_on_urandom_unsupported():
    ok, _ = SF.verilator_should_retry_synthesis_define(
        "%Error: foo.sv:10: Unsupported: $urandom",
        rtl_text_blob=_SIMONLY_RTL, tb_text=_PLAIN_TB)
    assert ok is True


def test_retry_on_std_randomize():
    ok, _ = SF.verilator_should_retry_synthesis_define(
        "%Error: bar.sv: std::randomize is not supported",
        rtl_text_blob=_SIMONLY_RTL, tb_text=_PLAIN_TB)
    assert ok is True


def test_no_retry_on_sva_parse_error():
    # NO-LEAK: an SVA / sequence parse failure (the #657 family) is NOT a
    # define-set mismatch → no -DSYNTHESIS retry.
    ok, reason = SF.verilator_should_retry_synthesis_define(
        "%Error: m.sv:5: Syntax error, unexpected 'sequence'")
    assert ok is False, reason


def test_no_retry_on_generic_missing_module():
    ok, _ = SF.verilator_should_retry_synthesis_define(
        "%Error: Cannot find file containing module: some_missing_mod")
    assert ok is False


def test_no_retry_on_empty_err():
    ok, _ = SF.verilator_should_retry_synthesis_define("")
    assert ok is False


def test_custom_define_names_honoured():
    rtl = _SIMONLY_RTL.replace("SIMULATION", "SIM")
    ok, reason = SF.verilator_should_retry_synthesis_define(
        SIMONLY_ERR, rtl_text_blob=rtl, tb_text=_PLAIN_TB,
        sim_define="SIM", synth_define="SYN")
    assert ok is True, reason
    assert "SIM" in reason and "SYN" in reason


# ── the escape wires the retry into the build path ──────────────────────────

def test_escape_source_retries_under_synthesis_define():
    src = inspect.getsource(R._verilator_sim_escape)
    # the escape must call the new classifier and rebuild under SYNTHESIS.
    assert "verilator_should_retry_synthesis_define" in src
    assert '_vl_build_run("SYNTHESIS")' in src
    # and it must still try SIMULATION first (no behaviour change for #657).
    assert '_vl_build_run("SIMULATION")' in src
    # the SIMULATION clean-build path still returns verilator_sva immediately.
    assert "verilator_sva" in src


def test_escape_keeps_honest_fail_when_both_arms_fail():
    # Structural: the function returns iverilog_g2012 (honest FAIL) at its tail,
    # so a closure failing under BOTH defines is never reported as a pass.
    src = inspect.getsource(R._verilator_sim_escape)
    tail = src.rstrip().splitlines()[-1]
    assert '"iverilog_g2012"' in tail
