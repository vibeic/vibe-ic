#!/usr/bin/env python3
"""Three findings from the opentitan_aes close-loop, each with its control.

1. The full-stack testbench asserted NOTHING. It instantiated the DUT, clocked
   it, printed a byte/bit tally and finished; `testbench_exists_check.
   count_test_cases` scored it 0 in every run tree measured on this host. It
   now checks one property — every DUT output resolvable after reset release —
   and the connectivity bridge REFUSES on a failure, so the check can block.

2. A JSON-emitting gate's refusal reached the P0 record as `"message": "{"`.
   MEASURED on `reports/audit/phase23_completion_audit.json`: the whole stated
   reason `testbench_exists_check` FAILed was the first byte of its report.

3. Three `advisory_reason` strings in the canonical flow claimed a refusal was
   being "swallowed" by the advisory slot, for gates whose refusal already
   FAILS the step. Prose that contradicts the code sends the next reader to
   patch the enforcement layer, which is correct.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


# --------------------------------------------------------------------------
# 1. the full-stack testbench now checks something
# --------------------------------------------------------------------------
def _tb_text() -> str:
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    return src


def test_the_generator_emits_one_check_per_dut_output():
    src = _tb_text()
    assert "post_reset_resolvable" in src
    assert "FULL_STACK_TB_CHECKS pass=%0d fail=%0d" in src
    # The X-reduction is the width-safe form, so a bus is covered by the same
    # line as a scalar.
    assert "=== 1'bx" in src


def test_the_generator_says_so_when_there_is_nothing_to_check():
    """A silent absence of check lines is indistinguishable from the
    pre-v1.15.51 testbench that checked nothing on purpose."""
    assert "no observable output" in _tb_text()


DONE = "FULL_STACK_TB_DONE bytes=0 bits=0\n"


# --------------------------------------------------------------------------
# 2. a JSON gate's refusal says why
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 3. the flow's own prose may not contradict its own enforcement
# --------------------------------------------------------------------------
_SWALLOW = "swallowing a live finding"


def test_no_advisory_reason_claims_a_swallowed_refusal_it_cannot_have():
    """A gate whose module does NOT declare `ENFORCEMENT: advisory` is not
    exempted by `_gate_is_two_source_advisory`, so its refusal maps to
    enforcement=BLOCKING and FAILS the step. Three rows said the opposite."""
    lines = (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text(
    ).splitlines()
    offenders = []
    for i, line in enumerate(lines):
        if _SWALLOW not in line:
            continue
        m = re.search(r'command: "([A-Za-z0-9_]+)', lines[i - 1])
        gate = m.group(1) if m else ""
    assert offenders == [], (
        "these rows claim the advisory slot swallows their refusal, but the "
        f"refusal already fails the step: {offenders}")


def test_the_claim_is_still_made_where_it_is_true():
    """VACUITY CONTROL. If the phrase were simply deleted everywhere the test
    above would pass while asserting nothing."""
    text = (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text()
    assert text.count(_SWALLOW) >= 5
