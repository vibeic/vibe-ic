#!/usr/bin/env python3
"""Regression test for ORGANIC #744 round-17 — author-declared latency origin.

CVDP round-17 false-positive (cvdp_copilot_gaussian_rounding_div_0003): a divider
whose spec states latency INCLUSIVELY as WIDTH+2 ("1 cycle registering inputs +
WIDTH cycles compute + 1 cycle asserting valid") was BLOCKED by
latency_conformance_check.py because the gate MEASURES with an EXCLUSIVE origin
(posedges strictly after the event-latch edge), reading WIDTH+1. The author
faithfully transcribed the inclusive literal WIDTH+2 into --expect.

The §4.05-safe resolution is an AUTHOR-DECLARED counting origin:
`--latency-origin inclusive` makes the gate compare `measured + 1` against
--expect. This is a DECLARED convention, NOT a +-1 tolerance — under the fixed
declared origin a real 1-cycle-early/late latency bug STILL mismatches, so the
gate's purpose (catching +-1 latency errors) is preserved.

Asserts, with an INLINE Verilog shift-register fixture and the patched gate:
  POSITIVE   the inclusive-declared correct design (exclusive measured 3, spec
             literal WIDTH+2=4) PASSES under `--latency-origin inclusive`.
  NO-LEAK    a 1-cycle-EARLY (stages 2), 1-cycle-LATE (stages 4) and >=2-off
             (stages 1) bug all stay rc=1 MISMATCH under the SAME declared
             inclusive origin (the declared origin never relaxes a real bug).
  UNCHANGED  an exclusive-convention correct design PASSES under the default
             origin (byte-for-byte behaviour preserved).
  FLAG       the gate under test exposes --latency-origin (guards against the
             test silently passing on an unpatched gate).

Resolves the programs dir via Path(__file__).resolve().parent.parent (= programs/)
with a VIBE_PROGRAMS env override (CI layout: programs/tests/<this>). Skips
honestly when iverilog/vvp are unavailable.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_DEFAULT_PROGRAMS = Path(__file__).resolve().parent.parent
PROGRAMS = Path(os.environ.get("VIBE_PROGRAMS", str(_DEFAULT_PROGRAMS)))
GATE = PROGRAMS / "latency_conformance_check.py"

_HAVE_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_skip_no_iverilog = pytest.mark.skipif(
    not _HAVE_IVERILOG, reason="iverilog/vvp unavailable")

# A parametric delay: after `start` is sampled HIGH at the event-latch edge E,
# `valid` asserts exactly STAGES posedges later (exclusive measured == STAGES).
_DELAY_SV = """\
module delay #(parameter STAGES = 3)
(
  input  wire clk,
  input  wire rst_n,
  input  wire start,
  output wire valid
);
  reg [STAGES-1:0] sh;
  integer i;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) sh <= {STAGES{1'b0}};
    else begin
      sh[0] <= start;
      for (i = 1; i < STAGES; i = i + 1) sh[i] <= sh[i-1];
    end
  end
  assign valid = sh[STAGES-1];
endmodule
"""


@pytest.fixture(scope="module")
def rtl(tmp_path_factory):
    d = tmp_path_factory.mktemp("r17_lat")
    p = d / "delay.sv"
    p.write_text(_DELAY_SV)
    return p


def _run(rtl_path, stages, expect, *extra):
    cmd = [sys.executable, str(GATE), "--rtl", str(rtl_path), "--top", "delay",
           "--event", "start", "--output", "valid", "--expect", expect,
           "--reset", "rst_n", "--reset-active-low",
           "--param", f"STAGES={stages}", *extra]
    return subprocess.run(cmd, capture_output=True, text=True).returncode


def test_gate_supports_latency_origin():
    """The gate under test must expose --latency-origin; otherwise the
    positive/no-leak assertions would silently pass on an unpatched gate."""
    assert GATE.is_file(), f"gate not found: {GATE}"
    out = subprocess.run([sys.executable, str(GATE), "--help"],
                         capture_output=True, text=True)
    assert "--latency-origin" in (out.stdout + out.stderr), \
        "gate does not expose --latency-origin (unpatched?)"


# Convention reference: intended INCLUSIVE spec literal = 4 -> a CORRECT design
# measures exclusive 3 (STAGES=3). bug_early=stages 2, bug_late=stages 4,
# bug_two_early=stages 1.
@_skip_no_iverilog
def test_positive_inclusive_declared_correct_passes(rtl):
    """A correct design under a DECLARED inclusive origin (measured 3, --expect
    WIDTH+2=4) now PASSES (rc=0)."""
    rc = _run(rtl, 3, "4", "--latency-origin", "inclusive")
    assert rc == 0, f"inclusive-declared correct design rc={rc} != 0"


@_skip_no_iverilog
@pytest.mark.parametrize("label,stages", [
    ("bug_early", 2), ("bug_late", 4), ("bug_two_early", 1)])
def test_noleak_declared_inclusive_real_bug_still_blocks(rtl, label, stages):
    """§4.05: under the SAME declared inclusive origin (--expect 4), a real
    1-cycle-early / 1-cycle-late / >=2-off latency bug STILL hard-blocks rc=1.
    The declared origin is a fixed convention, NOT a +-1 tolerance."""
    rc = _run(rtl, stages, "4", "--latency-origin", "inclusive")
    assert rc == 1, (f"NO-LEAK[{label}]: rc={rc} != 1 — declared inclusive origin "
                     f"must not relax a real latency bug")


@_skip_no_iverilog
def test_unchanged_exclusive_default_correct_passes(rtl):
    """The default (exclusive) origin is byte-for-byte preserved: an
    exclusive-convention correct design (--expect 3, no flag) PASSES rc=0."""
    rc = _run(rtl, 3, "3")
    assert rc == 0, f"exclusive-default correct design rc={rc} != 0"


@_skip_no_iverilog
def test_optin_default_origin_still_blocks_inclusive_literal(rtl):
    """The fix is OPT-IN: the inclusive literal WIDTH+2=4 under the DEFAULT
    (exclusive) origin still mismatches (measured 3) rc=1 — the FP stands until
    the author DECLARES inclusive (guard that the fix did not change the default)."""
    rc = _run(rtl, 3, "4")
    assert rc == 1, (f"opt-in: inclusive literal under default origin rc={rc} != 1 "
                     f"(default exclusive behaviour must be unchanged)")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
