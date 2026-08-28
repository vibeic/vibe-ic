#!/usr/bin/env python3
"""ORGANIC #787 — latency_conformance_check.py multi-bit DATAPATH output.

THE RESIDUAL FP (complex_multiplier_0001)
=========================================
The canonical latency TB models the --output as a 1-BIT done/valid PULSE: it
counts posedges from the event to the first `out === 1'b1`. That convention is
only meaningful for a 1-bit handshake flag. A MULTI-BIT DATAPATH result bus
(e.g. `result_real[31:0]`, `result_imag[31:0]`) is NOT a 1-bit pulse:
`out === 1'b1` matches ONLY when the WHOLE bus equals exactly 1, so a correct
1-cycle registered datapath either:
  * never "asserts" (the bus settles to a value != 1) → a false LATENCY-TIMEOUT
    (rc 1) on correct, simulation-PASS RTL, OR
  * its quiescent post-reset value coincidentally equals 1 → a false
    LATENCY_PRECONDITION_HIGH (rc 2).
Both HARD-BLOCK correct RTL.

THE FIX
=======
When the PRIMARY --output is a resolved width>1 bus that is NOT named like a
handshake flag (done/valid/ready/ack/...), MEASURE the latency the faithful way:
the SAME posedge-counting simulation, but the assertion is the FIRST CHANGE of
the bus away from its settled post-reset value (`out !== <captured baseline>`)
instead of `out === 1'b1`. Two helpers gate this: `_resolved_output_width`
(concrete bit-width via the safe arithmetic evaluator) and
`_looks_like_pulse_output` (narrow, word-anchored handshake-name guard).

§4.05 NO-LEAK (load-bearing)
============================
The relaxation only changes the ASSERT PREDICATE for a genuine multi-bit
datapath bus; the latency is STILL measured by simulation, so:
  * a genuine 2-cycle datapath vs spec=1 → measures 2 → still MISMATCH (rc 1);
  * a bus that never changes from its reset value → still TIMEOUT (rc 1);
  * a 1-bit output (width==1) → datapath_mode False → unchanged pulse model;
  * a wide output NAMED like a handshake (`data_valid[3:0]`) → pulse model kept;
  * an FSM/enable-gated multi-cycle datapath → measures its TRUE latency (the
    structural register-chain walk mis-counts it, which is why the fix is
    simulation-based change-detection, not structural inference).

chip-AGNOSTIC: pure structural/grammar (output width + handshake-name guard), no
chip/vendor/SKU literal (enforced by source_chip_agnostic_check).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "latency_conformance_check.py"

_spec = importlib.util.spec_from_file_location("latency_conformance_check",
                                               str(_PROG))
lcc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lcc)

_HAVE_IVERILOG = (shutil.which("iverilog") is not None
                  and shutil.which("vvp") is not None)
_skip_no_iv = pytest.mark.skipif(
    not _HAVE_IVERILOG, reason="iverilog/vvp unavailable")


# ── fixtures ──────────────────────────────────────────────────────────────────
# A 1-cycle REGISTERED multi-bit datapath (complex-multiplier shape). Under the
# canonical all-ones SIGNED stimulus (a=b=-1):
#   result_real = (a_re*b_re) - (a_im*b_im) = 1 - 1 = 0   (never changes → TIMEOUT)
#   result_imag = (a_re*b_im) + (a_im*b_re) = 1 + 1 = 2   (changes 0→2 at E+1)
# True latency = 1 for BOTH. `out === 1'b1` mis-reads both.
_CMULT = """
module cmult #(
    parameter OUT_WIDTH = 32
)(
    input  wire                        clk,
    input  wire                        rst_n,
    input  wire                        start,
    input  wire signed [15:0]          a_re,
    input  wire signed [15:0]          a_im,
    input  wire signed [15:0]          b_re,
    input  wire signed [15:0]          b_im,
    output reg  signed [OUT_WIDTH-1:0] result_real,
    output reg  signed [OUT_WIDTH-1:0] result_imag
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            result_real <= {OUT_WIDTH{1'b0}};
            result_imag <= {OUT_WIDTH{1'b0}};
        end else if (start) begin
            result_real <= (a_re * b_re) - (a_im * b_im);
            result_imag <= (a_re * b_im) + (a_im * b_re);
        end
    end
endmodule
"""

# A correct 1-cycle datapath whose QUIESCENT (post-reset) value happens to == 1.
# `data_out === 1'b1` matches the quiescent bus → false PRECONDITION_HIGH (rc 2).
# True behaviour: holds 1 until start, then loads a+b (!= 1) one cycle later.
_SETTLE1 = """
module settle1 #(
    parameter W = 8
)(
    input  wire           clk,
    input  wire           rst_n,
    input  wire           start,
    input  wire [W-1:0]   a,
    input  wire [W-1:0]   b,
    output reg  [W-1:0]   data_out
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            data_out <= {{(W-1){1'b0}}, 1'b1};
        else if (start)
            data_out <= a + b;
    end
endmodule
"""

# §4.05 negative — a GENUINE 2-cycle pipelined datapath. True latency = 2.
_MULT2 = """
module mult2 #(
    parameter W = 16
)(
    input  wire           clk,
    input  wire           rst_n,
    input  wire           start,
    input  wire [W-1:0]   a,
    input  wire [W-1:0]   b,
    output reg  [2*W-1:0] prod
);
    reg [2*W-1:0] stage1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            stage1 <= {(2*W){1'b0}};
            prod   <= {(2*W){1'b0}};
        end else if (start) begin
            stage1 <= a * b;
            prod   <= stage1;
        end else begin
            prod   <= stage1;
        end
    end
endmodule
"""

# §4.05 negative — a 1-bit done PULSE output, UNAFFECTED by the fix.
_DONE = """
module donepulse (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    output reg         done
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)      done <= 1'b0;
        else if (start)  done <= 1'b1;
        else             done <= 1'b0;
    end
endmodule
"""

# FSM/enable-gated MULTI-CYCLE datapath: a naive register-chain structural walk
# infers depth 1, but the TRUE latency is DELAY+1 cycles. Datapath change-detect
# SIMULATION measures the true latency.
_FSM_BLEND = """
module fsm_blend #(
    parameter W = 8,
    parameter DELAY = 4
)(
    input  wire         clk,
    input  wire         rst_n,
    input  wire         start,
    input  wire [W-1:0] pix,
    output reg  [W-1:0] blended_out
);
    reg [7:0] cnt;
    reg       running;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt         <= 8'd0;
            running     <= 1'b0;
            blended_out <= {W{1'b0}};
        end else if (start && !running) begin
            running <= 1'b1;
            cnt     <= 8'd1;
        end else if (running) begin
            if (cnt == DELAY) begin
                blended_out <= pix;
                running     <= 1'b0;
            end
            cnt <= cnt + 8'd1;
        end
    end
endmodule
"""

# §4.05 negative — a WIDE output NAMED like a handshake (`data_valid`). Even at
# width>1 the pulse model is kept by `_looks_like_pulse_output`.
_WIDE_VALID = """
module wide_valid (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       start,
    output reg [3:0]  data_valid
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)      data_valid <= 4'b0000;
        else if (start)  data_valid <= 4'b0001;   // === 1'b1 on the low bit only
        else             data_valid <= 4'b0000;
    end
endmodule
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def _run_cli(rtl: Path, top: str, event: str, output: str, expect: str,
             tmp_path: Path, extra=None):
    """Run the real program end-to-end; return (rc, report_dict)."""
    jpath = tmp_path / f"{output}.json"
    cmd = [sys.executable, str(_PROG), "--rtl", str(rtl), "--top", top,
           "--event", event, "--output", output, "--expect", expect,
           "--reset", "rst_n", "--reset-active-low", "--json", str(jpath)]
    cmd += extra or []
    cp = _pr.run(cmd, capture_output=True, text=True)
    report = json.loads(jpath.read_text()) if jpath.exists() else {}
    return cp.returncode, report


# ── helper unit tests (no iverilog needed) ───────────────────────────────────
def test_resolved_output_width_numeric():
    assert lcc._resolved_output_width("[31:0]", {}) == 32
    assert lcc._resolved_output_width("[7:0]", {}) == 8


def test_resolved_output_width_param_substituted():
    # caller substitutes params via _concretise_width inside the helper.
    assert lcc._resolved_output_width("[OUT_WIDTH-1:0]", {"OUT_WIDTH": 32}) == 32
    assert lcc._resolved_output_width("[2*W-1:0]", {"W": 16}) == 32


def test_resolved_output_width_scalar_is_one():
    assert lcc._resolved_output_width("", {}) == 1


def test_resolved_output_width_unresolved_is_none():
    # an unresolved bound stays None → caller conservatively keeps the pulse TB.
    assert lcc._resolved_output_width("[WIDTH-1:0]", {}) is None


def test_pulse_name_guard_matches_handshakes():
    for n in ("done", "valid", "data_valid", "m0_ready", "irq", "tx_busy",
              "grant0", "rx_empty", "ack_o", "intr", "overflow_flag"):
        assert lcc._looks_like_pulse_output(n), n


def test_pulse_name_guard_rejects_datapath_names():
    # datapath buses must NOT match → they are measured by change-detection.
    for n in ("result_real", "result_imag", "data_out", "sum", "q", "prod",
              "blended_out", "accumulator", "y", "dout", "pixel", "quotient"):
        assert not lcc._looks_like_pulse_output(n), n


# ── POSITIVE: the FP now PASSes ──────────────────────────────────────────────
@_skip_no_iv
def test_multibit_datapath_imag_now_passes(tmp_path):
    """A correct 1-cycle multi-bit datapath bus that settles != reset value now
    MEASURES latency 1 instead of a false TIMEOUT/PRECONDITION block."""
    rtl = _write(tmp_path, "cmult.sv", _CMULT)
    rc, rep = _run_cli(rtl, "cmult", "start", "result_imag", "1", tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS", rep
    assert rep["measured_latency"] == 1, rep
    assert rep["datapath_output"] is True, rep
    assert rep["output_width"] == 32, rep


@_skip_no_iv
def test_multibit_datapath_quiescent_one_now_passes(tmp_path):
    """A correct datapath whose QUIESCENT value == 1 no longer false-fires
    PRECONDITION_HIGH (rc 2); it measures its true 1-cycle latency."""
    rtl = _write(tmp_path, "settle1.sv", _SETTLE1)
    rc, rep = _run_cli(rtl, "settle1", "start", "data_out", "1", tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS", rep
    assert rep["measured_latency"] == 1, rep
    assert rep["datapath_output"] is True, rep


@_skip_no_iv
def test_fsm_gated_multicycle_measures_true_latency(tmp_path):
    """An FSM/enable-gated multi-cycle datapath measures its TRUE latency via
    simulation — the structural register-chain walk would mis-count it as 1."""
    rtl = _write(tmp_path, "fsm_blend.sv", _FSM_BLEND)
    # E latches start (running<=1,cnt<=1); cnt reaches DELAY=4 at E+4; blended_out
    # registers pix there → first CHANGE read at E+5.
    rc, rep = _run_cli(rtl, "fsm_blend", "start", "blended_out", "5", tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS", rep
    assert rep["measured_latency"] == 5, rep
    assert rep["datapath_output"] is True, rep


# ── §4.05 NO-LEAK negatives: genuine defects STILL hard-block ────────────────
@_skip_no_iv
def test_noleak_genuine_latency_mismatch_still_blocks(tmp_path):
    """A genuine 2-cycle pipelined datapath vs spec=1 MEASURES 2 → still
    MISMATCH (rc 1). The relaxation never masks a real timing miss."""
    rtl = _write(tmp_path, "mult2.sv", _MULT2)
    rc, rep = _run_cli(rtl, "mult2", "start", "prod", "1", tmp_path)
    assert rc == 1, rep
    assert rep["verdict"] == "MISMATCH", rep
    assert rep["measured_latency"] == 2, rep
    assert rep["datapath_output"] is True, rep


@_skip_no_iv
def test_noleak_correct_pipelined_spec_passes(tmp_path):
    """The SAME 2-cycle datapath with the CORRECT spec=2 PASSes — the change-
    detect measurement is faithful for a pipelined datapath too."""
    rtl = _write(tmp_path, "mult2.sv", _MULT2)
    rc, rep = _run_cli(rtl, "mult2", "start", "prod", "2", tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS", rep
    assert rep["measured_latency"] == 2, rep


@_skip_no_iv
def test_noleak_never_changing_bus_still_timeouts(tmp_path):
    """A datapath bus that never changes from its post-reset value (result_real
    settles to 0 and stays 0 under all-ones) still TIMEs out (rc 1) — a bus
    that never asserts is NOT relaxed to a PASS."""
    rtl = _write(tmp_path, "cmult.sv", _CMULT)
    rc, rep = _run_cli(rtl, "cmult", "start", "result_real", "1", tmp_path)
    assert rc == 1, rep
    assert rep["verdict"] == "TIMEOUT", rep
    assert rep["datapath_output"] is True, rep


@_skip_no_iv
def test_noleak_one_bit_done_pulse_unchanged(tmp_path):
    """A 1-bit done PULSE output keeps the unchanged `out===1'b1` model
    (datapath_mode False) and measures 1 cycle → PASS."""
    rtl = _write(tmp_path, "donepulse.sv", _DONE)
    rc, rep = _run_cli(rtl, "donepulse", "start", "done", "1", tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS", rep
    assert rep["measured_latency"] == 1, rep
    assert rep["datapath_output"] is False, rep
    assert rep["output_width"] == 1, rep


@_skip_no_iv
def test_noleak_wide_handshake_named_keeps_pulse_model(tmp_path):
    """A WIDE output NAMED like a handshake (`data_valid[3:0]`) keeps the pulse
    model (`_looks_like_pulse_output`): it asserts 4'b0001 (=== 1'b1) at E+1 →
    measures 1 under the UNCHANGED pulse convention, datapath_mode stays False."""
    rtl = _write(tmp_path, "wide_valid.sv", _WIDE_VALID)
    rc, rep = _run_cli(rtl, "wide_valid", "start", "data_valid", "1", tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS", rep
    assert rep["measured_latency"] == 1, rep
    assert rep["datapath_output"] is False, rep  # name guard kept pulse model
    assert rep["output_width"] == 4, rep


# ── report-shape regression (no iverilog needed for the keys to appear) ──────
def test_report_carries_datapath_metadata(tmp_path):
    """Even without iverilog the orchestrator annotates the datapath decision
    (the keys are computed before the sim drive). Robust to SKIP."""
    rtl = _write(tmp_path, "cmult.sv", _CMULT)
    rc, rep = _run_cli(rtl, "cmult", "start", "result_imag", "1", tmp_path)
    assert "datapath_output" in rep
    assert "output_width" in rep
    assert rep["output_width"] == 32


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
