"""Step-2.7 §4.05 guard for the R12C1 latency set/reset-mutex relaxation (PR #3).

The original relaxation had two §4.05 leaks (both reproduced by Step-2.7 against
real RTL): (1) `classify_ports` UNCONDITIONALLY reclassified a named set/reset
bit as a reset, so a functional control like `set` was held inactive for the
CANONICAL measurement — masking a genuine off-by-N latency bug at its all-ones
value; (2) the on-timeout retry probed EVERY 1-bit input and adopted any clean
result — masking real bugs gated by a generic control (`en`/`cfg`).

FIX: the set/reset handling is ONLY a TIMEOUT-gated, NAME-ANCHORED retry. A
MISMATCH (wrong-but-present latency) is never retried; a TIMEOUT is retried ONLY
by deactivating a conventionally-named set/reset bit — never a generic control.
This file PINS the three reviewer attacks (all must FAIL) and the motivating
correct SR-flop (must PASS via the named-partner retry).

chip-AGNOSTIC; requires iverilog/vvp (skipped otherwise).
"""
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

pytestmark = pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp unavailable — latency measurement cannot run")

import latency_conformance_check as L  # noqa: E402


def _run(rtl_text, tmp_path, *, top, event, output, expect="1", reset="rst_n"):
    p = tmp_path / "dut.v"
    p.write_text(rtl_text)
    return L.run_latency_conformance(
        rtl_path=p, top=top, event=event, output=output, expect=expect,
        params_override={}, reset_override=reset, reset_active_low_flag=None,
        input_const=-1, max_cycles_override=None, mode="latency",
        allow_no_handshake=False, context_files=None)


# attack 1 — `set` is a named set/reset bit BUT a real functional control with an
# off-by-two bug at its canonical (all-ones) value. Canonical measures at set=1
# (asserts, just LATE) → MISMATCH, never retried → must FAIL.
_MISMATCH_SET = """\
module dut3(input trig, input set, input clk, input rst_n, output reg out);
  reg p1, p2;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin out<=0; p1<=0; p2<=0; end
    else begin p1<=trig; p2<=p1; out <= set ? p2 : trig; end
endmodule
"""

# attack 2 — `cfg` is a GENERIC control (not a set/reset name). Output gated off
# at cfg=1 (canonical) → TIMEOUT, but cfg is NOT a named retry candidate → the
# timeout stands → must FAIL.
_BUGGY_CFG = """\
module dut(input start, input cfg, input clk, input rst_n, output reg done);
  always @(posedge clk or negedge rst_n)
    if(!rst_n) done<=0; else done <= start & ~cfg;
endmodule
"""

# attack 3 — `en` enable gated bug (fires only when en LOW; canonical en=HIGH).
_BUGGY_EN = """\
module dut(input wire clk,input wire rst_n,input wire start,input wire en,output reg done);
  always @(posedge clk or negedge rst_n)
    if(!rst_n) done<=1'b0; else if(start && !en) done<=1'b1; else done<=1'b0;
endmodule
"""

# motivating correct case — SR flip-flop: {s,r}=11 invalid→0. Canonical pins the
# named partner `r` active → set pulse hits invalid → false TIMEOUT → the retry
# holds the NAMED partner `r` inactive → recovers (PASS).
_SR_CORRECT = """\
module sr_ff(input clk, input rst_n, input s, input r, output reg q);
  always @(posedge clk or negedge rst_n)
    if(!rst_n) q<=1'b0;
    else case({s,r}) 2'b10:q<=1'b1; 2'b01:q<=1'b0; 2'b11:q<=1'b0; default:q<=q; endcase
endmodule
"""


def test_named_setreset_bit_with_canonical_mismatch_still_fails(tmp_path):
    rc, rep = _run(_MISMATCH_SET, tmp_path, top="dut3", event="trig", output="out")
    assert rc == 1, rep.get("verdict")
    assert rep["verdict"] == "MISMATCH"      # measured the real (wrong) latency


def test_generic_cfg_gated_timeout_bug_still_fails(tmp_path):
    rc, rep = _run(_BUGGY_CFG, tmp_path, top="dut", event="start", output="done")
    assert rc == 1, rep.get("verdict")
    # cfg is NOT a named set/reset bit → never a retry candidate
    assert "cfg" not in rep.get("mutex_bit_retry_candidates", [])
    assert rep.get("measured_with_inactive_bit") is None


def test_generic_en_gated_timeout_bug_still_fails(tmp_path):
    rc, rep = _run(_BUGGY_EN, tmp_path, top="dut", event="start", output="done")
    assert rc == 1, rep.get("verdict")
    assert "en" not in rep.get("mutex_bit_retry_candidates", [])
    assert rep.get("measured_with_inactive_bit") is None


def test_sr_flop_false_timeout_recovered_via_named_partner(tmp_path):
    rc, rep = _run(_SR_CORRECT, tmp_path, top="sr_ff", event="s", output="q")
    assert rc == 0, rep.get("verdict")
    assert rep["measured_latency"] == 1
    assert rep.get("measured_with_inactive_bit") == "r"   # named partner


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
