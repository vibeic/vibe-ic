#!/usr/bin/env python3
"""Regression test for CLUSTER R12C1 (ORGANIC #809) —
latency_conformance_check.py false LATENCY-TIMEOUT on a correct SR flip-flop.

ROOT CAUSE: the canonical measurement TB pins EVERY non-event input to the
all-ones data constant. For a sequential primitive (SR/JK flip-flop) the
measured event (`i_S`) has a MUTUALLY-EXCLUSIVE partner (`i_R`) that is then
held =1, driving the DUT into its spec INVALID state ({i_S,i_R}=2'b11 -> o_Q<=0),
so the output can never assert -> a FALSE TIMEOUT (rc=1) on correct, spec-faithful
RTL. `_looks_like_reset`/`_looks_like_clear` do not match the bit name `i_R`.

FIX (chip-agnostic, no-leak — Step-2.7 §4.05 remediated form):
  The set/reset-bit handling is a SINGLE mechanism: a TIMEOUT-gated retry that is
  NARROWLY NAME-ANCHORED. On a plain (non-arbiter, non-datapath) TIMEOUT, retry
  driving each held 1-bit input WHOSE NAME IS A CONVENTIONAL SET/RESET-BIT
  SPELLING (`i_S`/`i_R`, `S`/`R`, `sd`/`rd`, `set_i`/`reset_i`) INACTIVE one at a
  time; adopt the first clean measurement. Fires ONLY on status=='timeout'.

  Step-2.7 §4.05 NOTE — two earlier forms were §4.05 LEAKS and were removed:
    * an UNCONDITIONAL classify-time reclassification of a set/reset-bit as a
      reset (held inactive for the CANONICAL measurement) — that MASKED a real
      off-by-N bug that only manifests at the bit's canonical (all-ones) value,
      because a name like `set` is ALSO a legitimate functional control;
    * a GENERIC retry that probed EVERY 1-bit input and adopted any clean
      result — that masked real bugs gated by a generic control (`en`/`cfg`).
  The discriminator is TIMEOUT (invalid-state never-asserts) vs MISMATCH (wrong
  but present latency); only a TIMEOUT on a CONVENTIONALLY-named set/reset bit is
  retried. An unconventionally-named mutex partner is a DELIBERATE under-fix
  (false-timeout) — far safer than masking a real functional-control bug.

This test:
  POSITIVE — the affected correct SR flip-flop now PASSES (rc=0, measured==spec)
      via the timeout-gated retry holding its CONVENTIONALLY-named partner `i_R`
      inactive.
  UNDER-FIX (§4.05 tradeoff) — an UNCONVENTIONALLY-named mutex partner is NOT
      auto-recovered (it still TIMES OUT, rc=1): the narrow name-anchored retry
      never deactivates an arbitrary 1-bit input, so it can never mask an
      `en`/`cfg`-style functional-control bug.
  NEGATIVE (§4.05 no-leak) — a genuine 2-cycle SET latency vs spec=1 STILL
      MISMATCHes (rc=1), and a genuinely mis-latching SR-FF whose output never
      asserts STILL TIMES OUT (rc=1) after the retry exhausts.

Self-contained: inline RTL fixtures; the program is imported from
$VIBE_PROGRAMS (default: the round12 programs dir) so it runs in CI.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_DEFAULT_PROGRAMS = __import__("pathlib").Path(__file__).resolve().parent.parent
PROGRAMS = Path(os.environ.get("VIBE_PROGRAMS", _DEFAULT_PROGRAMS))
PROG = PROGRAMS / "latency_conformance_check.py"

pytestmark = pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp unavailable — latency measurement cannot run")


def _load():
    if not PROG.is_file():
        pytest.skip(f"program not found: {PROG}")
    sys.path.insert(0, str(PROGRAMS))
    spec = importlib.util.spec_from_file_location("latency_conformance_check_r12c1",
                                                  str(PROG))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── inline RTL fixtures ──────────────────────────────────────────────────────
SR_CORRECT = """\
module SR_flipflop(
    input  i_S, input  i_R, input  i_clk, input  i_rst_b,
    output reg o_Q, output reg o_Q_b
);
    always @(posedge i_clk or negedge i_rst_b) begin
        if (!i_rst_b) begin o_Q <= 1'b0; o_Q_b <= 1'b1; end
        else begin
            case ({i_S, i_R})
                2'b00: begin o_Q <= o_Q;   o_Q_b <= o_Q_b; end
                2'b01: begin o_Q <= 1'b0;  o_Q_b <= 1'b1;  end
                2'b10: begin o_Q <= 1'b1;  o_Q_b <= 1'b0;  end
                2'b11: begin o_Q <= 1'b0;  o_Q_b <= 1'b0;  end
                default: begin o_Q <= 1'b0; o_Q_b <= 1'b1; end
            endcase
        end
    end
endmodule
"""

# same correct design but the mutex partner has an UNCONVENTIONAL name the
# set/reset-bit NAME recogniser does NOT match (exercises the generic backstop).
SR_CORRECT_UNCONV = SR_CORRECT.replace("i_R", "xyz_part")

# genuine off-by-one: SET takes 2 cycles (extra pipeline reg). Must MISMATCH.
SR_BUGGY_2CYC = """\
module SR_flipflop(
    input  i_S, input  i_R, input  i_clk, input  i_rst_b,
    output reg o_Q, output reg o_Q_b
);
    reg q1;
    always @(posedge i_clk or negedge i_rst_b) begin
        if (!i_rst_b) begin q1 <= 0; o_Q <= 0; o_Q_b <= 1; end
        else begin
            case ({i_S, i_R})
                2'b00: begin q1 <= q1; o_Q <= q1; o_Q_b <= ~q1; end
                2'b01: begin q1 <= 0;  o_Q <= q1; o_Q_b <= ~q1; end
                2'b10: begin q1 <= 1;  o_Q <= q1; o_Q_b <= ~q1; end
                2'b11: begin q1 <= 0;  o_Q <= q1; o_Q_b <= 0;   end
                default: begin q1 <= 0; o_Q <= q1; o_Q_b <= 1;  end
            endcase
        end
    end
endmodule
"""

# genuinely broken: SET is wired to 0, o_Q never asserts. Must TIMEOUT even after
# the retry exhausts every 1-bit deactivation.
SR_BROKEN = """\
module SR_flipflop(
    input  i_S, input  i_R, input  i_clk, input  i_rst_b,
    output reg o_Q, output reg o_Q_b
);
    always @(posedge i_clk or negedge i_rst_b) begin
        if (!i_rst_b) begin o_Q <= 0; o_Q_b <= 1; end
        else begin o_Q <= 1'b0; o_Q_b <= 1'b1; end
    end
endmodule
"""


def _write(tmp_path, text, name="SR_flipflop.sv"):
    p = tmp_path / name
    p.write_text(text)
    return p


def _run(m, rtl):
    rc, rep = m.run_latency_conformance(
        rtl_path=rtl, top="SR_flipflop", event="i_S", output="o_Q", expect="1",
        params_override={}, reset_override="i_rst_b", reset_active_low_flag=None,
        input_const=-1, max_cycles_override=None, mode="latency",
        allow_no_handshake=False, context_files=None)
    return rc, rep


# ── POSITIVE: affected correct SR flip-flop now PASSES ───────────────────────
def test_positive_sr_flipflop_passes(tmp_path):
    m = _load()
    rtl = _write(tmp_path, SR_CORRECT)
    rc, rep = _run(m, rtl)
    assert rc == 0, f"expected rc=0 (PASS), got rc={rc} verdict={rep.get('verdict')}"
    assert rep["verdict"] == "PASS"
    assert rep["measured_latency"] == 1
    # §4.05-remediated: the conventionally-named partner i_R is recovered by the
    # TIMEOUT-gated retry (held inactive ONLY after the canonical measurement
    # timed out), NOT by an unconditional classify-time reclassification.
    assert rep.get("measured_with_inactive_bit") == "i_R"
    # it is NOT pre-classified as a reset (that would mask canonical-value bugs).
    assert "i_R" not in rep.get("resets", [])


# ── UNDER-FIX (§4.05 tradeoff): an unconventionally-named partner is NOT
#    auto-recovered — the narrow name-anchored retry never deactivates an
#    arbitrary 1-bit input, so it can never mask an en/cfg-style functional bug.
def test_unconventional_mutex_name_is_not_auto_recovered(tmp_path):
    m = _load()
    # the unconventional name is NOT matched by any reset/clear/set-reset-bit
    assert not m._looks_like_reset("xyz_part")
    assert not m._looks_like_clear("xyz_part")
    assert not m._looks_like_setreset_bit("xyz_part")
    rtl = _write(tmp_path, SR_CORRECT_UNCONV)
    rc, rep = _run(m, rtl)
    # DELIBERATE under-fix: a false-timeout on a correct-but-oddly-named SR-FF is
    # far safer than masking a real functional-control bug; the design needs a
    # conventional set/reset-bit name or an explicit --reset override.
    assert rc == 1, f"expected rc=1 (deliberate under-fix), got rc={rc}"
    assert rep["verdict"] == "TIMEOUT"
    assert rep.get("measured_with_inactive_bit") is None
    # xyz_part must NOT be among the retry candidates (name-anchored, not generic)
    assert "xyz_part" not in rep.get("mutex_bit_retry_candidates", [])


# ── NEGATIVE (§4.05 no-leak): genuine off-by-one STILL MISMATCHes ────────────
def test_negative_genuine_offbyone_still_blocks(tmp_path):
    m = _load()
    rtl = _write(tmp_path, SR_BUGGY_2CYC)
    rc, rep = _run(m, rtl)
    assert rc == 1, f"a genuine 2-cycle latency must hard-block, got rc={rc}"
    assert rep["verdict"] == "MISMATCH"
    assert rep["measured_latency"] == 2  # measured the real (wrong) latency


# ── NEGATIVE (§4.05 no-leak): genuinely mis-latching design STILL TIMES OUT ──
def test_negative_broken_output_still_times_out(tmp_path):
    m = _load()
    rtl = _write(tmp_path, SR_BROKEN)
    rc, rep = _run(m, rtl)
    assert rc == 1, f"an output that never asserts must hard-block, got rc={rc}"
    assert rep["verdict"] == "TIMEOUT"
    # the retry exhausted every 1-bit deactivation without a clean measurement
    assert rep.get("measured_with_inactive_bit") is None


# ── CLI smoke (the shipped invocation path) ──────────────────────────────────
def test_cli_positive(tmp_path):
    if not PROG.is_file():
        pytest.skip(f"program not found: {PROG}")
    rtl = _write(tmp_path, SR_CORRECT)
    r = subprocess.run(
        [sys.executable, str(PROG), "--rtl", str(rtl), "--top", "SR_flipflop",
         "--event", "i_S", "--output", "o_Q", "--expect", "1",
         "--reset", "i_rst_b"],
        capture_output=True, text=True)
    assert r.returncode == 0, f"CLI rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "latency-conformance ok" in r.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
