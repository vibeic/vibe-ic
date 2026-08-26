"""Two pin-list repairs measured on a 4-channel PWM with an SPI interface.

Both were found the same way: a plain-English spec was driven from
`/vibe-ic-phase1` through `design_one_shot_runner`, and `spec_conformance_check`
was then pointed at the emitted L9. It reported an ERROR on a CORRECT design —
twice, for two unrelated reasons — and a blocking gate that fails correct work
is the mirror of a vacuous PASS, not a lesser problem.

The two are tested together because the first HID the second: L9 carried seven
`top_ports` entries for six distinct names, so the count looked right while
`sclk` was already missing. Removing the duplicate is what surfaced it.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


# ── 1. the width-less duplicate that shadows a real bus ──────────────────────
def _scrub(pins):
    from phase1_post_process import scrub_l_doc
    obj = {"pin_table": [dict(p) for p in pins]}
    scrub_l_doc(obj, "L1_DATASHEET.json")
    return [p["name"] for p in obj["pin_table"]]


_REAL_BUS = {"name": "pwm", "mode": "output",
             "function": "the four PWM outputs", "width": 4, "msb": 3, "lsb": 0}
#: The shape measured in the emitted L1: an uppercase prose token, no width,
#: and a `function` that is nothing but the direction word echoed back.
_ECHO_DUP = {"name": "PWM", "mode": "output", "function": "output",
             "rtl_name": "pwm"}
_ECHO_SOLO = {"name": "SPI", "mode": "input", "function": "input",
              "rtl_name": "spi"}
_CLK = {"name": "clk", "mode": "input", "function": "system clock, 25 MHz",
        "width": 1, "msb": 0, "lsb": 0}


def test_the_echoed_duplicate_is_dropped():
    """It is strictly less informative than the row it shadows, and it is what
    made the gate report `port-width-mismatch: RTL=4 vs spec=1` on correct RTL:
    the reader took the width-less row and defaulted its width to 1."""
    assert _scrub([_REAL_BUS, _ECHO_DUP, _CLK]) == ["pwm", "clk"]


def test_an_echoed_entry_that_duplicates_nothing_is_KEPT():
    """`SPI` is as content-free as `PWM` was, and it still stays. Dropping it
    would assert that no real pin is ever named after its bus — a claim about
    naming conventions this predicate cannot support. The duplicate needed no
    such claim: a same-named sibling already carried the width."""
    assert _scrub([_CLK, _ECHO_SOLO]) == ["clk", "SPI"]


def test_a_real_width_less_pin_is_KEPT():
    """Absence of a width is not the signal. `tdo` has no width here and says
    what it does, so it carries information the direction word does not."""
    real = {"name": "tdo", "mode": "output", "function": "JTAG test data out"}
    assert _scrub([_CLK, real]) == ["clk", "tdo"]


def test_a_namesake_that_says_something_is_KEPT():
    """Same name, no width — but its `function` is not its `mode`, so it is a
    second declared tap rather than an echo, and the predicate leaves it."""
    tap = {"name": "pwm", "mode": "output",
           "function": "alternate PWM tap for the test mux"}
    assert _scrub([_REAL_BUS, tap]) == ["pwm", "pwm"]


# ── 2. the fuzzy typo-dedup that ate a real port ─────────────────────────────
def _dedupe(names):
    import phase1_doc_one_shot_runner as R
    out = R._dedupe_typo_against_canonical(
        [{"name": n, "mode": "input"} for n in names])
    return [p["name"] for p in out]


def test_the_original_typo_is_still_dropped():
    """The case v1.6.87 was written for: `iid_bus` beside `id_bus`, an inserted
    character that DUPLICATES its neighbour. This repair must not undo it."""
    assert _dedupe(["id_bus", "iid_bus"]) == ["id_bus"]


def test_sclk_survives_beside_clk():
    """`sclk` is one insertion from `clk`, and `clk` is in a canonical set of
    six — so edit-distance alone deleted the SPI clock. Every SPI device has
    both. Measured consequence before the repair: L1.pin_table carried all
    seven pins, L9.top_ports carried six, and spec_conformance_check answered
    `[ERROR] port-extra: RTL port 'sclk' is not declared in the spec` —
    blaming the RTL for a port the spec dropped."""
    assert _dedupe(["clk", "sclk"]) == ["clk", "sclk"]


def test_the_prefixed_clock_convention_survives_generally():
    """Not a one-name exemption. The same shape covers a FIFO's write and read
    clocks and an active-low reset spelled with a leading `n`."""
    assert _dedupe(["clk", "wclk", "rclk"]) == ["clk", "wclk", "rclk"]
    assert _dedupe(["reset_n", "nreset"]) == ["reset_n", "nreset"]


def test_substitution_and_deletion_remain_typos():
    """Only INSERTION is reclassified, and only when the inserted character
    repeats its neighbour. A slipped key and a dropped key are still typos —
    no naming convention produces them."""
    assert _dedupe(["clk", "cll"]) == ["clk"]        # substitution
    assert _dedupe(["clk", "ck"]) == ["clk"]         # deletion


def test_an_unrelated_port_is_untouched():
    """`vbg` beside `vdd` is edit-distance 2 and was never in scope; pinned so
    a future widening of the predicate has to notice it."""
    assert _dedupe(["vdd", "vbg"]) == ["vdd", "vbg"]
