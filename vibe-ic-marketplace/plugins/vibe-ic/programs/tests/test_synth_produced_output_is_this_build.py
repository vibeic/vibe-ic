#!/usr/bin/env python3
"""A netlist left by an EARLIER build is not this build's output.

MEASURED (opentitan_aes x sky130A, 2026-09-15). `step_synth` asks four times
whether the build produced a netlist, and answered with `netlist.is_file()`.
Phase 3 synthesises into the directory phase 2 already wrote `<top>_synth.v`
to, so that predicate is true before the build even starts.

The consequence was not cosmetic. `synth_frontend_should_retry_under_synthesis`
takes `produced_output` as its anti-verdict-shopping guard — "a real result
must not be re-read under -DSYNTHESIS". Handed a STALE file it refused the
retry, and the retry it refused is the one the runner ships for exactly this
failure (its own comment: "a vendor primitive whose `ifdef SIMULATION DV-only
arm ($urandom / std::randomize / $value$plusargs-in-a-constant-context) ...
FAIL - even though the IDENTICAL closure elaborates under -DSYNTHESIS").
The run failed `synth rc=1 ... synth_frontend: "none"` with a 5,276,402-byte
netlist from four hours earlier sitting beside it.

The same predicate also gated the three SUCCESS checks, where a stale netlist
beside an rc=0 build that wrote nothing would CERTIFY a frontend that produced
nothing - the same defect with a false PASS instead of a false FAIL.

These tests are about the OBSERVABLE, not about any chip: they use a synthetic
`fixture_top_synth.v` and assert only on the stamp helper's answers.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import synth_frontend as SF              # noqa: E402

#: Resolved lazily and tolerantly ON PURPOSE. A module-level attribute
#: access would turn the pre-fix tree into a COLLECTION ERROR, which takes the
#: whole file down — including the structural test below, the one that has to
#: keep working against pre-fix source to be worth anything. Absent, every test
#: here fails on its own assertion with the reason named.




# ───────────────────────────── the stamp itself ──────────────────────────────











# ───────────── the consequence the defect actually had (the retry) ───────────
# A design-property blob that genuinely branches on the define set, so the
# retry's OTHER precondition is satisfied and `produced_output` is the only
# variable under test.

_ARMED_RTL = """
module fixture_prim ();
`ifdef SIMULATION
  initial begin
    if (!$value$plusargs("fixture_seed=%0d", seed)) begin end
  end
`elsif SYNTHESIS
  // synthesizable passthrough
`endif
endmodule
"""


def test_stale_artifact_would_suppress_the_retry(tmp_path):
    """NEGATIVE CONTROL for the defect: this is what went wrong.

    Not a test of new code — a statement of the mechanism, so a future change
    that re-introduces `is_file()` semantics fails here with the reason named.
    """
    suppressed, why = SF.synth_frontend_should_retry_under_synthesis(
        "$value$plusargs", rtl_text_blob=_ARMED_RTL, produced_output=True)
    assert suppressed is False
    assert "no retry" in why


def test_the_same_closure_retries_when_nothing_was_produced(tmp_path):
    """And this is what should happen once `produced_output` means produced."""
    allowed, why = SF.synth_frontend_should_retry_under_synthesis(
        "$value$plusargs", rtl_text_blob=_ARMED_RTL, produced_output=False)
    assert allowed is True
    assert "SYNTHESIS" in why
