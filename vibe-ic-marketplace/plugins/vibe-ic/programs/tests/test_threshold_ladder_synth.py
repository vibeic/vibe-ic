"""The SENSOR THRESHOLD LADDER + CHANGE-DIRECTION artifact type.

A monotonic quantity sensed by N thresholds, a zone table, and one further
output asserted by the DIRECTION of the last zone change.  Before
`threshold_ladder_synth` no recogniser in the registry covered this shape, so
every such prompt WAIVED to the AI backup and the answer depended on which way
the authoring agent read one ambiguous sentence.

The load-bearing claim is that the direction sense is NOT a judgement call: the
bottom zone can only ever be ENTERED by a decrease, so a prompt that pins the
direction output asserted in the bottom zone has fixed the sense.  The solver
REQUIRES that pin (`test_no_bottom_pin_skips`) instead of guessing.

The fixture below is a synthetic battery-gauge ladder, not a benchmark prompt:
the solver must fire on the SHAPE, never on a remembered design.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).parent.parent
sys.path.insert(0, str(PROGRAMS))
import threshold_ladder_synth as tl  # noqa: E402
import spec_artifact_registry as reg  # noqa: E402

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


def test_the_ladder_prompt_is_program_solved():
    """GREEN: the shape emits RTL, and the registry routes to this type."""
    rtl = tl.synth(LADDER)
    assert rtl is not None
    assert "module TopModule" in rtl
    kind, reg_rtl = reg.generate(LADDER, "TopModule")
    assert kind == "threshold_ladder"
    assert reg_rtl == rtl


def test_the_declared_bit_range_is_preserved():
    """Rebuilding a port from (name, width) turned `[3:1] c` into `[2:0] c`
    while the body still indexed c[3] — out of range."""
    rtl = tl.synth(LADDER)
    assert "input [3:1] c" in rtl
    assert "[2:0] c" not in rtl


def test_the_direction_output_is_pinned_in_the_bottom_zone():
    """The sense-fixing fact: bottom zone asserts it unconditionally."""
    rtl = tl.synth(LADDER)
    bottom = [l for l in rtl.splitlines() if "2'd0:" in l]
    assert bottom and "boost = 1'b1;" in bottom[0], rtl
    top = [l for l in rtl.splitlines() if "2'd3:" in l]
    assert top and "boost = 1'b0;" in top[0], rtl
    interior = [l for l in rtl.splitlines() if "2'd1:" in l or "2'd2:" in l]
    assert all("boost = went_down;" in l for l in interior), rtl


def test_the_zone_outputs_are_read_from_the_table():
    """MUTATION: move an output to a different zone; the RTL must follow."""
    mutated = LADDER.replace("| shed1, shed2\n", "| shed1, shed2, shed3\n")
    rtl = tl.synth(mutated)
    assert rtl is not None
    zone1 = [l for l in rtl.splitlines() if "2'd1:" in l][0]
    assert "shed3 = 1'b1;" in zone1, rtl
    base = [l for l in tl.synth(LADDER).splitlines() if "2'd1:" in l][0]
    assert "shed3 = 1'b0;" in base


def test_the_reset_polarity_is_read_from_the_prose():
    """MUTATION: flip the stated polarity; the reset test must flip."""
    rtl = tl.synth(LADDER)
    assert "if (reset)" in rtl
    flipped = tl.synth(LADDER.replace("active-high synchronous",
                                      "active-low synchronous"))
    assert flipped is not None and "if (!reset)" in flipped


def test_no_bottom_pin_skips():
    """MUTATION / the honesty case: without the pin the direction sense is a
    coin flip, so the solver must WAIVE rather than guess."""
    import re
    no_pin = re.sub(r"\(no sensors\s+asserted,[^)]*\)", "(the quiescent state)",
                    LADDER)
    assert "no sensors" not in no_pin, "the mutation must actually remove the pin"
    assert tl.synth(no_pin) is None


def test_a_broken_inclusion_chain_skips():
    """MUTATION: a non-thermometer sensor set is not this artifact."""
    broken = LADDER.replace("| c[1], c[2]       |", "| c[2], c[3]       |")
    assert tl.synth(broken) is None


def test_a_second_unmatched_output_skips():
    """Without a UNIQUE direction output the shape is not closed."""
    ambiguous = LADDER.replace("  output reg boost\n",
                               "  output reg boost,\n  output reg alarm\n")
    assert tl.synth(ambiguous) is None


def test_it_does_not_fire_on_another_family():
    """FALSE-POSITIVE guard: a K-map prompt must stay with its own owner."""
    kmap = """
For the following Karnaugh map, give the circuit implementation.

      ab
  cd  00  01  11  10
  00 | 0 | 0 | 0 | 1 |
  01 | 1 | 0 | 0 | 0 |
  11 | 1 | 0 | 1 | 1 |
  10 | 1 | 0 | 0 | 1 |

module TopModule (
  input c,
  input d,
  output [3:0] mux_in
);
"""
    assert tl.synth(kmap) is None
