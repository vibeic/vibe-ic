#!/usr/bin/env python3
"""Round-13 cluster R13C2 regression test for fsm_error_invariant.py.

Bug: the SIGNAL-NAME error-vocabulary locator regex
    \\b(\\w*(?:error|err|fail|abort|timeout|reject|invalid)\\w*)\\s*<=\\s*1...
is a SUBSTRING match, so the whole `interrupt_*` family ("int-ERR-upt" embeds
`err`) tripped a hard rc=1 on spec-faithful RTL (cpu_interrupt / interrupt_valid
latched to 1). The whole-TOKEN fix already applied to the STATE-LABEL matcher
(#786 r2) was NOT applied to the SIGNAL-NAME matcher.

Fix: confirm the assignment LHS is a GENUINE error signal by underscore/camelCase
segment membership (an exact segment must be one of {error,err,fail,abort,
timeout,reject,invalid}); names that only EMBED an error word (interrupt) are
exempt, while real flags (err_o/o_error/timeout_err/rx_error/fail_flag) still fire.

Asserts:
  (a) POSITIVE — the affected interrupt-controller RTL now passes (rc 0).
  (b) §4.05 NEGATIVE — genuine mid-FSM error flags still hard-block (rc 1).
  (c) NO-LEAK token coverage — every real error-vocabulary signal still fires;
      the interrupt family stays exempt.

Self-contained: inline fixtures, resolves the programs dir via
Path(__file__).resolve().parent.parent so it runs in CI (repo programs/).
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import os
_DEFAULT_PROGRAMS = Path(__file__).resolve().parent.parent
PROGRAMS = Path(os.environ.get("VIBE_PROGRAMS", _DEFAULT_PROGRAMS))
PROG = PROGRAMS / "fsm_error_invariant.py"


def _run(rtl_text: str, tmp_path: Path, name: str = "dut.sv"):
    f = tmp_path / name
    f.write_text(textwrap.dedent(rtl_text))
    p = subprocess.run(
        [sys.executable, str(PROG), str(f)],
        capture_output=True, text=True)
    return p.returncode, p.stdout


# ---------------------------------------------------------------------------
# (a) POSITIVE — the affected spec-faithful interrupt-controller RTL.
# cpu_interrupt / interrupt_valid asserted in a normal operational state must
# NOT be flagged (they only embed `err` in "int-ERR-upt").
# ---------------------------------------------------------------------------
POSITIVE_CPU_INTERRUPT = """\
    module interrupt_controller(input clk, input rst_n,
                                input sel_valid, input cpu_ack,
                                output logic cpu_interrupt,
                                output logic [1:0] interrupt_idx);
      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
          cpu_interrupt <= 1'b0;
          interrupt_idx <= '0;
        end else if (!cpu_interrupt && sel_valid) begin
          cpu_interrupt <= 1'b1;
          interrupt_idx <= 2'b10;
        end
      end
    endmodule
"""

POSITIVE_INTERRUPT_VALID = """\
    module interrupt_controller(input clk, input rst_n,
                                output logic interrupt_valid);
      typedef enum logic [1:0] {IDLE, SERVICE_PREP} state_t;
      state_t state;
      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
          interrupt_valid <= 1'b0;
          state <= IDLE;
        end else begin
          case (state)
            IDLE: state <= SERVICE_PREP;
            SERVICE_PREP: interrupt_valid <= 1'b1;
          endcase
        end
      end
    endmodule
"""


def test_positive_cpu_interrupt_not_flagged(tmp_path):
    rc, out = _run(POSITIVE_CPU_INTERRUPT, tmp_path)
    assert rc == 0, f"cpu_interrupt wrongly hard-blocked:\n{out}"
    assert "cpu_interrupt" not in out
    assert "0 error-assertion sites" in out


def test_positive_interrupt_valid_not_flagged(tmp_path):
    rc, out = _run(POSITIVE_INTERRUPT_VALID, tmp_path)
    assert rc == 0, f"interrupt_valid wrongly hard-blocked:\n{out}"
    assert "interrupt_valid" not in out


# ---------------------------------------------------------------------------
# (b) §4.05 NEGATIVE — genuine mid-FSM error flags must STILL hard-block.
# ---------------------------------------------------------------------------
NEGATIVE_REAL_ERRORS = """\
    module rx_phy(input clk, input rst_n, input bad,
                  output logic timeout_err, output logic fail_flag,
                  output logic abort, output logic o_error);
      always_ff @(posedge clk) begin
        if (bad) begin
          timeout_err <= 1'b1;
          fail_flag   <= 1'b1;
          abort       <= 1'b1;
          o_error     <= 1'b1;
        end
      end
    endmodule
"""


def test_negative_real_errors_still_block(tmp_path):
    rc, out = _run(NEGATIVE_REAL_ERRORS, tmp_path)
    assert rc == 1, f"real mid-FSM error flags must still hard-block:\n{out}"
    for sig in ("timeout_err", "fail_flag", "abort", "o_error"):
        assert sig in out, f"no-leak FAIL: {sig} not flagged:\n{out}"


# ---------------------------------------------------------------------------
# (c) NO-LEAK token coverage — exhaustive over the error vocabulary + the
# exempt interrupt family. Uses non-reset, non-comment assignment so only the
# whole-token guard governs the result.
# ---------------------------------------------------------------------------
ERR_SIGNALS = ["rx_error", "err_o", "o_error", "timeout_err", "fail_flag",
               "err", "bus_error", "fsm_err", "invalid_addr", "reject_o",
               "abort_req", "crc_err_o", "timeout", "invalid", "reject", "fail",
               # ORGANIC #804 — pslverr (APB slave-error) is `err` as a segment
               # SUFFIX and MUST still fire (do not regress the shipped detection).
               "pslverr"]
# `terror` (ends with `error`) intentionally NOT exempt: the segment-SUFFIX rule
# required to keep `pslverr` (#804) firing necessarily catches `terror` too —
# benign, no real non-error signal is named `terror`. `merrily` (m-ERR-ily, error
# word strictly INTERNAL to the segment) stays exempt — the real false-positive
# class is the `interrupt_*` family, all of which remain exempt.
EXEMPT_SIGNALS = ["cpu_interrupt", "interrupt_valid", "interrupt_idx",
                  "interrupt_requests", "interrupt_status", "nvic_interrupt",
                  "ext_interrupt", "data_valid", "ready", "cpu_ack",
                  "merrily"]


def _one_sig_module(sig: str) -> str:
    return f"""\
    module m(input clk, output logic {sig});
      always_ff @(posedge clk) begin
        {sig} <= 1'b1;
      end
    endmodule
"""


@pytest.mark.parametrize("sig", ERR_SIGNALS)
def test_no_leak_real_error_signals_fire(sig, tmp_path):
    rc, out = _run(_one_sig_module(sig), tmp_path, name=f"{sig}.sv")
    assert rc == 1, f"NO-LEAK FAIL: real error signal '{sig}' did not fire:\n{out}"
    assert sig in out


@pytest.mark.parametrize("sig", EXEMPT_SIGNALS)
def test_exempt_substring_signals_do_not_fire(sig, tmp_path):
    rc, out = _run(_one_sig_module(sig), tmp_path, name=f"{sig}.sv")
    assert rc == 0, f"'{sig}' wrongly flagged (substring match leaked):\n{out}"
    assert "0 error-assertion sites" in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
