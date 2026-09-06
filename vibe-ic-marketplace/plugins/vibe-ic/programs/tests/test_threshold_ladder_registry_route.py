"""The threshold-ladder shape must be REACHABLE through the registry.

Kept separate from `test_threshold_ladder_synth.py` on purpose: this file
imports only `spec_artifact_registry`, so it still COLLECTS and RUNS on a tree
that has no `threshold_ladder_synth` module at all.  A control that dies at
import time observes nothing; this one runs against the pre-fix code and gets
the wrong answer, which is what makes it a control.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).parent.parent
sys.path.insert(0, str(PROGRAMS))
import spec_artifact_registry as reg  # noqa: E402

# The fixture is INLINED, not imported from the sibling test: importing it
# would drag in `threshold_ladder_synth` and turn this control back into a
# collection error on the pre-fix tree.
LADDER = """
A battery gauge drives three load-shedding outputs and one boost output. Three
sensors are placed at equal charge intervals. When the charge is above the
highest sensor c[3], no load shedding is required. When it is below the lowest
sensor c[1], every load is shed and the boost converter is enabled.

  Charge Level          | Sensors Asserted | Outputs to be Asserted
  Above c[3]            | c[1], c[2], c[3] | None
  Between c[3] and c[2] | c[1], c[2]       | shed1
  Between c[2] and c[1] | c[1]             | shed1, shed2
  Below c[1]            | None             | shed1, shed2, shed3

If the sensor change indicates that the previous level was lower than the
current level, the boost converter (controlled by boost) should be enabled.

Also include an active-high synchronous reset that resets the state machine to
a state equivalent to if the charge had been low for a long time (no sensors
asserted, and all four outputs asserted).

module TopModule (
  input clk,
  input reset,
  input [3:1] c,
  output reg shed3,
  output reg shed2,
  output reg shed1,
  output reg boost
);
"""


def test_the_registry_solves_a_threshold_ladder_prompt():
    kind, rtl = reg.generate(LADDER, "TopModule")
    assert kind == "threshold_ladder", f"registry returned {kind!r}"
    assert rtl and "module TopModule" in rtl


def test_the_type_is_declared_in_the_registry():
    assert "threshold_ladder" in {a.key for a in reg.REGISTRY}
