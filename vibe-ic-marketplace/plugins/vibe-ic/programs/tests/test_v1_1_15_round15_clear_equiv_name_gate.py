"""Step-2.7 §4.05 guard for PR #10 (ORGANIC #810 structural clear-equivalent).

PR #10 held a structurally-detected clear-equivalent control INACTIVE during the
canonical latency measurement. But the detection was PURELY structural (`if(ctrl)
reg<=const-zero`), which also matches a load-bearing functional control
(capture/mode/hold) buggy at its canonical (active) value — so a real
canonical-value latency bug was MASKED (Step-2.7 2×HIGH; the exact failure class
PR #3 removed for set/reset bits, reproduced on origin/main as a hard TIMEOUT).

FIX: require a NAME carrying clear/flush/completion semantics
(`_looks_like_clear_equiv_name`) IN ADDITION to the structural shape. The
motivating `Present_Processing_Completed` matches via `complete`; the reviewer's
`capture`/`mode`/`hold` do not, so their canonical-value bugs hard-block. + a
comment strip so a commented-out branch assign is not parsed as a real clear.

chip-AGNOSTIC; the end-to-end cases need iverilog/vvp (skipped otherwise).
"""
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import latency_conformance_check as L  # noqa: E402


# ── name-gate unit (no sim) ───────────────────────────────────────────────────
@pytest.mark.parametrize("name", [
    "Present_Processing_Completed", "clear", "rx_flush", "frame_done",
    "init", "sync_reset", "buf_purge", "txAbort", "eot"])
def test_clear_equiv_names_accepted(name):
    assert L._looks_like_clear_equiv_name(name) is True


@pytest.mark.parametrize("name", [
    "capture", "mode", "hold", "enable", "cfg", "select", "start", "valid",
    "abandoned"])  # 'abandoned' contains 'done' but only as an internal fragment
def test_load_bearing_controls_rejected(name):
    assert L._looks_like_clear_equiv_name(name) is False


def test_structural_detector_requires_name_gate():
    # `capture` has the clear-equivalent STRUCTURAL shape but a non-clear name →
    # must NOT be detected as clear-equivalent.
    rtl = ("module dut3 (input clk, input rst_n, input start, input capture,\n"
           "  output reg valid);\n  reg [2:0] cnt;\n"
           "  always @(posedge clk) begin\n"
           "    if (!rst_n) begin cnt<=3'd0; valid<=1'b0; end\n"
           "    else if (capture) begin cnt<=3'd0; valid<=1'b0; end\n"
           "    else begin if (start) valid<=1'b1; else valid<=1'b0; end\n"
           "  end\nendmodule\n")
    assert L.detect_structural_clear_equiv(rtl, "dut3", {"start", "capture"}) == {}
    # a clear-NAMED control with the same shape IS detected.
    rtl2 = rtl.replace("capture", "flush_req")
    assert "flush_req" in L.detect_structural_clear_equiv(
        rtl2, "dut3", {"start", "flush_req"})


# ── end-to-end (§4.05 no-leak): load-bearing control bug hard-blocks ──────────
_NEED_SIM = pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp unavailable")


def _run(tmp_path, rtl, *, top, event, output):
    p = tmp_path / "d.v"
    p.write_text(rtl)
    return L.run_latency_conformance(
        rtl_path=p, top=top, event=event, output=output, expect="1",
        params_override={}, reset_override="rst_n", reset_active_low_flag=True,
        input_const=-1, max_cycles_override=None, mode="latency",
        allow_no_handshake=False, context_files=None)


@_NEED_SIM
@pytest.mark.parametrize("ctrl", ["capture", "mode", "hold"])
def test_load_bearing_control_bug_still_times_out(tmp_path, ctrl):
    rtl = (f"module dut(input clk, input rst_n, input start, input {ctrl},\n"
           "  output reg valid);\n  reg [2:0] cnt;\n"
           "  always @(posedge clk) begin\n"
           "    if (!rst_n) begin cnt<=3'd0; valid<=1'b0; end\n"
           f"    else if ({ctrl}) begin cnt<=3'd0; valid<=1'b0; end\n"
           "    else begin if (start) valid<=1'b1; else valid<=1'b0; end\n"
           "  end\nendmodule\n")
    rc, rep = _run(tmp_path, rtl, top="dut", event="start", output="valid")
    assert rc == 1, rep.get("verdict")
    assert rep["verdict"] == "TIMEOUT"


@_NEED_SIM
def test_named_flush_false_timeout_is_recovered(tmp_path):
    # a clear-NAMED flush genuinely should be held inactive → recovered (rc=0).
    rtl = ("module dut(input clk, input rst_n, input start, input frame_flush,\n"
           "  output reg valid);\n"
           "  always @(posedge clk) begin\n"
           "    if (!rst_n) valid<=1'b0;\n"
           "    else if (frame_flush) valid<=1'b0;\n"
           "    else valid <= start;\n"
           "  end\nendmodule\n")
    rc, rep = _run(tmp_path, rtl, top="dut", event="start", output="valid")
    assert rc == 0, rep.get("verdict")
    assert rep.get("measured_with_inactive_clear_equiv") == "frame_flush"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
