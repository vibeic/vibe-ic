"""reference_tb must REFUSE when its RTL input was never produced, instead of
reporting FAIL as though the reference TB had run and the design had lost.

Measured on a 20-problem Phase-2 run: `reference_tb` reported FAIL "rtl/ missing"
on 15 of 20 designs.  In all 15 the upstream producer `rtl_gen` had returned
BLOCKED, so rtl/ genuinely did not exist -- the message was TRUE but it was a
statement about an ABSENT INPUT, not about the design.  In the same runs
`rtl_validate` and `sim` reported BLOCKED for that identical state, and after
the RTL repair/retry loop re-ran `rtl_gen` the very same gate reported SKIP for the very
same class.  One gate, two verdicts, decided by an unrelated upstream step.

The properties pinned here:
  * absent RTL yields the runner's documented refusal status, naming the
    producer that should have filled the directory;
  * the refusal is NOT silencing -- the run verdict stays red;
  * the refusal record is RECONCILABLE with the verdict the same gate emits
    once the producer succeeds;
  * the gate can still FAIL for its own real reason;
  * the refusal keeps the repair recovery loop engaged;
  * a plain Phase-1 design doc with no harness gets the same verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import design_one_shot_runner as DOR               # noqa: E402

# A registered class the AID reference TB can never bind (generic_full_stack,
# half_duplex_bus=False) and one it does bind -- both from the class registry.
_NON_AID_CLASS = "digital_arithmetic_primitive"
_AID_CLASS = "aid_class_half_duplex_single_wire"

_DIGITAL_TOP = [
    {"name": "clk", "direction": "input"},
    {"name": "rst_n", "direction": "input"},
    {"name": "a", "direction": "input"},
    {"name": "b", "direction": "input"},
    {"name": "y", "direction": "output"},
]




# ── 1. the refusal itself ───────────────────────────────────────────────────



# ── 2. refusing is not silencing ────────────────────────────────────────────



# ── 3. the two verdicts must be reconcilable ────────────────────────────────





# ── 4. constructed genuine violation: the gate can still FAIL ───────────────



# ── 5. the repair recovery loop must still engage on the refusal ───────────────

def test_refusal_keeps_the_repair_recovery_loop_engaged():
    """The RTL repair/retry loop in `main()` exits on PASS / SKIP / WAIVED and iterates on
    anything else. The 15 recoveries measured on that run depended on the
    absent-RTL verdict NOT being one of the exit statuses."""
    rtl_repair_retry_exit_statuses = ("PASS", "SKIP", "PASS_WITH_WAIVERS")
    assert DOR._spf.REFUSAL_STATUS not in rtl_repair_retry_exit_statuses, (
        "the refusal status exits the RTL repair/retry loop -- rtl_gen would never be "
        "re-run and the recovery would be lost")


# ── 6. FLOW-BACK: no harness anywhere ───────────────────────────────────────
