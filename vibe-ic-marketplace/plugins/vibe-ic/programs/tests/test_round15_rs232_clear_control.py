#!/usr/bin/env python3
"""Regression test for ORGANIC #810 — STRUCTURAL synchronous-clear-equivalent.

CONFIRMED FALSE-POSITIVE (CVDP round-15, plugin v1.1.12,
``cvdp_copilot_rs_232_0001``): ``latency_conformance_check.py`` pins every
non-event input to the all-ones data constant. An active-HIGH synchronous-CLEAR
/ FLUSH-equivalent control (here spelled ``Present_Processing_Completed``) that
the NAME allowlist ``_CLEAR_NAME_EXACT`` misses is then held ACTIVE — it
unconditionally forces the FSM ``State`` register to 0 every clock, so the
measured output ``tx_transmitter_valid = (State != 0)`` can NEVER assert → a
FALSE ``LATENCY-TIMEOUT`` (rc=1) on correct RTL. The gate's own diagnostic
``--input-const 0`` (which holds the control LOW/inactive) already measured
``measured=1 == spec 1`` rc=0, proving the RTL is correct and the gate's
stimulus is the bug.

THE FIX (structural, no-leak): a TIMEOUT-gated STRUCTURAL detector
(``detect_structural_clear_equiv``) recognises a 1-bit input that, when asserted
at its inferred active polarity, DOMINATINGLY drives the state/output
register(s) to a ZERO constant every clock (the ``if (S) State <= '0;``
signature with a constant-only branch body), and HOLDS it in its NON-clearing
(inactive) value during measurement — exactly the way an explicit clear is held
inactive.

POSITIVE  : the rs_232-shape flush control no longer false-TIMEOUTs (rc 0).
§4.05 NEG : (a) a GENUINE timeout (real bug, no clear) still rc 1;
            (b) a GENUINE mismatch (measured != expect) still rc 1;
            (c) an ordinary DATA/ENABLE input is still pinned to the all-ones
                constant — its latency is still measured correctly (the detector
                must NOT mis-classify it as a clear and hold it inactive).

This test MUST PASS against the PATCHED program and the POSITIVE case MUST FAIL
against the shipped (unpatched) program.

CI layout: this test lives at ``programs/tests/<test>.py`` so the program-under-
test resolves via ``Path(__file__).resolve().parent.parent`` (= ``programs/``),
with a ``VIBE_PROGRAMS`` env override for non-standard layouts.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

# ─── locate the program-under-test ───────────────────────────────────────────
_ENV = os.environ.get("VIBE_PROGRAMS")
if _ENV:
    PROGRAMS_DIR = Path(_ENV).resolve()
else:
    PROGRAMS_DIR = Path(__file__).resolve().parent.parent
GATE = PROGRAMS_DIR / "latency_conformance_check.py"

# iverilog/vvp are required to MEASURE; without them the gate SKIPs (rc 0) and
# the verdicts under test do not occur — skip the whole module honestly.
_HAVE_IVERILOG = bool(shutil.which("iverilog") and shutil.which("vvp"))

pytestmark = pytest.mark.skipif(
    not GATE.is_file(),
    reason=f"latency_conformance_check.py not found under {PROGRAMS_DIR}")


# ─── inline RTL fixtures ─────────────────────────────────────────────────────
# POSITIVE — the rs_232-shape flush control. `flush_done` (a non-allowlist
# spelling) is an active-HIGH synchronous-CLEAR-equivalent: HIGH forces the FSM
# State to 0 every clock, so `busy = (State != 0)` can never assert when the
# all-ones constant pins it ACTIVE. Correct RTL: with flush_done LOW (inactive)
# the busy flag asserts the cycle after `start` ⇒ latency 1.
RTL_POSITIVE_FLUSH = """
module flush_ctrl_dut (
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire flush_done,          // active-HIGH sync-clear-equivalent
    input  wire [7:0] data,
    output wire busy
);
    parameter HIGH = 1'b1;
    reg [3:0] State;
    assign busy = (State != 4'b0000);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)                     State <= 4'b0000;
        else if (flush_done == HIGH)    State <= 4'b0000;   // dominating clear
        else case (State)
            4'b0000: if (start) State <= 4'b0001;
            4'b0001:            State <= 4'b0010;
            4'b0010:            State <= 4'b0000;
            default:            State <= 4'b0000;
        endcase
    end
endmodule
"""

# §4.05 (a) GENUINE TIMEOUT — `valid` is hard-wired LOW (a real bug). NO
# clear-equivalent exists; the structural retry must NOT recover it.
RTL_GENUINE_TIMEOUT = """
module genuine_timeout (
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire [7:0] data,
    output reg  valid
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) valid <= 1'b0;
        else        valid <= 1'b0;   // BUG: never asserts
    end
endmodule
"""

# §4.05 (b) GENUINE MISMATCH — a 2-stage pipeline measures latency 2; with
# --expect 1 it MISMATCHes (rc 1). A measured-but-wrong latency must NEVER be
# relaxed by any retry.
RTL_MISMATCH = """
module mismatch_dut (
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire [7:0] data,
    output reg  valid
);
    reg r;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin r <= 1'b0; valid <= 1'b0; end
        else        begin r <= start; valid <= r; end
    end
endmodule
"""

# §4.05 (c) ORDINARY DATA/ENABLE input still pinned all-ones. `en` is a real
# functional enable (its branch LOADS signals / advances, never a constant-zero
# clear) and `data` is a real data bus; both must stay pinned to the all-ones
# constant so the genuine 3-cycle latency is measured. The structural detector
# must NOT flag `en`/`data` as a clear and hold them inactive (which would stall
# or change the measured latency). Correct latency = 3 with en HIGH (all-ones).
RTL_DATA_DEP = """
module data_dep_dut (
    input  wire clk,
    input  wire rst_n,
    input  wire trig,
    input  wire en,
    input  wire [7:0] data,
    output reg  done
);
    reg s1, s2;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s1 <= 1'b0; s2 <= 1'b0; done <= 1'b0;
        end else if (en) begin                 // functional enable (not a clear)
            s1   <= trig & (data != 8'h00);
            s2   <= s1;
            done <= s2;
        end
    end
endmodule
"""


# ─── helpers ─────────────────────────────────────────────────────────────────
def _write_rtl(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / f"{name}.sv"
    p.write_text(text)
    return p


def _run_gate(gate: Path, rtl: Path, top: str, event: str, output: str,
              expect: str, *extra: str):
    cmd = [sys.executable, str(gate), "--rtl", str(rtl), "--top", top,
           "--event", event, "--output", output, "--expect", expect,
           "--reset", "rst_n", "--reset-active-low", "--max-cycles", "48",
           *extra]
    env = dict(os.environ)
    env.setdefault("PATH", os.environ.get("PATH", ""))
    # make the gate's sibling modules importable (CI runs it in-place; here we
    # explicitly add the programs dir so a copied-out gate still imports them).
    env["PYTHONPATH"] = (str(PROGRAMS_DIR) + os.pathsep
                         + env.get("PYTHONPATH", ""))
    return _pr.run(cmd, capture_output=True, text=True, env=env)


# ─── POSITIVE ────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _HAVE_IVERILOG,
                    reason="iverilog/vvp absent (gate SKIPs; verdict not exercised)")
def test_positive_flush_control_no_false_timeout(tmp_path):
    """The rs_232-shape active-HIGH flush control must NOT false-TIMEOUT: with
    the structural clear-equivalent detector the gate holds it inactive and
    measures latency 1 == spec 1 (rc 0). This case FAILS on the shipped program
    (it false-TIMEOUTs rc 1)."""
    rtl = _write_rtl(tmp_path, "flush_ctrl_dut", RTL_POSITIVE_FLUSH)
    r = _run_gate(GATE, rtl, "flush_ctrl_dut", "start", "busy", "1")
    assert r.returncode == 0, (
        "structural clear-equivalent flush control still false-TIMEOUTs "
        f"(rc={r.returncode})\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")
    assert "ok" in r.stdout.lower()


# ─── §4.05 NEGATIVE (a) — genuine timeout still blocks ───────────────────────
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp absent")
def test_negative_genuine_timeout_still_blocks(tmp_path):
    """A real bug whose output truly never asserts (NO clear-equivalent) must
    STILL TIMEOUT rc 1 — the structural retry must not mask it."""
    rtl = _write_rtl(tmp_path, "genuine_timeout", RTL_GENUINE_TIMEOUT)
    r = _run_gate(GATE, rtl, "genuine_timeout", "start", "valid", "1")
    assert r.returncode == 1, (
        f"genuine TIMEOUT no longer blocks (rc={r.returncode}) — §4.05 LEAK\n"
        f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")
    assert "timeout" in (r.stdout + r.stderr).lower()


# ─── §4.05 NEGATIVE (b) — genuine mismatch still blocks ──────────────────────
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp absent")
def test_negative_genuine_mismatch_still_blocks(tmp_path):
    """A measured-but-wrong latency (2 != expect 1) must STILL MISMATCH rc 1 —
    no retry may relax a measured mismatch."""
    rtl = _write_rtl(tmp_path, "mismatch_dut", RTL_MISMATCH)
    r = _run_gate(GATE, rtl, "mismatch_dut", "start", "valid", "1")
    assert r.returncode == 1, (
        f"genuine MISMATCH no longer blocks (rc={r.returncode}) — §4.05 LEAK\n"
        f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")
    assert "mismatch" in (r.stdout + r.stderr).lower()


# ─── §4.05 NEGATIVE (c) — ordinary data/enable input still pinned all-ones ───
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp absent")
def test_negative_ordinary_data_input_still_pinned(tmp_path):
    """An ordinary functional enable (`en`) + data bus (`data`) must stay pinned
    to the all-ones constant; the genuine latency (3) is still measured (rc 0
    with --expect 3). The structural detector must NOT flag `en`/`data` as a
    clear and hold them inactive (which would change/stall the latency)."""
    rtl = _write_rtl(tmp_path, "data_dep_dut", RTL_DATA_DEP)
    # correct spec literal: 3 ⇒ rc 0 (the data input is correctly held all-ones)
    r_ok = _run_gate(GATE, rtl, "data_dep_dut", "trig", "done", "3")
    assert r_ok.returncode == 0, (
        "ordinary data/enable input is no longer pinned all-ones — the genuine "
        f"3-cycle latency was not measured (rc={r_ok.returncode})\n"
        f"STDOUT:\n{r_ok.stdout}\nSTDERR:\n{r_ok.stderr}")
    # and the WRONG literal still hard-blocks (latency unchanged by the patch)
    r_bad = _run_gate(GATE, rtl, "data_dep_dut", "trig", "done", "1")
    assert r_bad.returncode == 1, (
        f"data-dependent latency mis-measured (rc={r_bad.returncode}) — the "
        f"enable/data was wrongly held inactive\nSTDOUT:\n{r_bad.stdout}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
