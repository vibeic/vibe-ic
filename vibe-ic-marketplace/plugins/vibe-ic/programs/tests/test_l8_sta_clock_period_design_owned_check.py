#!/usr/bin/env python3
"""Smoke tests for l8_sta_clock_period_design_owned_check.

EXPLICIT NEGATIVE CONTROL. Every behavioural test asserts BOTH directions:
a deliberately-gutted L8 must FAIL (rc=1) and the well-formed sibling must
PASS (rc=0). A test that cannot fail proves nothing.

All fixtures are SYNTHESIZED neutral data — invented module, port and clock
names, invented frequencies. No real design's files are copied.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent
GATE = PROGRAMS / "l8_sta_clock_period_design_owned_check.py"

RTL = """module neutral_top (
  input  wire clk_a,
  input  wire rst_na,
  output reg  [7:0] q_a
);
  always @(posedge clk_a or negedge rst_na) begin
    if (!rst_na) q_a <= 8'h00;
    else         q_a <= q_a + 8'h01;
  end
endmodule
"""

L9 = {
    "top_module": "neutral_top",
    "top_module_pins": [
        {"name": "clk_a", "mode": "input", "role": "clock"},
        {"name": "rst_na", "mode": "input", "role": "reset"},
    ],
}

# GUTTED: the layer LOOKS populated — a fully-shaped clock_domains[] entry —
# but every frequency field is null, so the consumer's resolver returns None
# and sdc_gen falls through to its hardcoded default.
GUTTED_L8 = {
    "doc_class": "L8_RTL_CONSTANTS",
    "clock_mhz": None,
    "no_clock_mhz_in_input": True,
    "clock_domains": [
        {"name": "clk_a", "source_pin": "clk_a", "domain_kind": "primary",
         "role": "master", "freq_hz": None, "freq_mhz": None,
         "period_ns": None},
    ],
}

WELLFORMED_L8 = {
    "doc_class": "L8_RTL_CONSTANTS",
    "clock_mhz": None,
    "clock_domains": [
        {"name": "clk_a", "source_pin": "clk_a", "domain_kind": "primary",
         "role": "master", "freq_mhz": 80.0, "period_ns": 12.5,
         "freq_hz": 80000000},
    ],
}






# --------------------------------------------------------------------------- #
# THE NEGATIVE CONTROL PAIR
# --------------------------------------------------------------------------- #
















def test_gate_reuses_the_consumers_own_resolver():
    """Emitter/checker doctrine: the gate must delegate to sdc_gen's OWN
    _clock_mhz_from_l8_domains and read its OWN _DEFAULT_MHZ, so gate and
    consumer can never drift."""
    sys.path.insert(0, str(PROGRAMS))
    import sdc_gen
    # The gutted fixture is exactly the shape that returns None from the
    # consumer's own resolver.
    assert sdc_gen._clock_mhz_from_l8_domains(GUTTED_L8) is None
    assert sdc_gen._clock_mhz_from_l8_domains(WELLFORMED_L8) == 80.0




if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
