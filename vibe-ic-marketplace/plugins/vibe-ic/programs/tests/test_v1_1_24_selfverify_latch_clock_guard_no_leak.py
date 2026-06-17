"""Step-2.7 §4.05 guard for PR #19 harness_exact_selfverify transparent-latch relaxation.

PR #19 downgrades a verilator %Warning-LATCH for an INTENDED transparent latch
(the VerilogEval `always @(*) if(clock) p=a;` idiom) while still blocking an
ACCIDENTAL forgot-the-else latch. Step-2.7 reproduced 2 HIGH §4.05 leaks: the
intended-latch exemption keyed on the author-controlled guard NAME via an
over-broad `_CLOCK_GUARD_RE` that matched `g`, `clken`/`enclk`, `clk_en`,
`clkgate` — so an accidental data-latch was laundered to "intended" (emitted)
merely by naming its data-enable guard `g`/`clk_en`/etc., identical to the PR's
own ACCIDENTAL_DATAEN negative fixture except the guard name.

FIX: `_is_clock_guard` matches ONLY genuine clock names (clk/clock/ck family) and
denies any clock-ENABLE / clock-GATE-enable form (`clk_en`, `clken`, `clkgate`,
`clk_ce`, a bare `g`). A latch guarded by a non-clock signal keeps BLOCKING.

chip-AGNOSTIC: a clock-name vocabulary, no chip/vendor literal.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import harness_exact_selfverify as H  # noqa: E402


# ── _is_clock_guard: attack names block, genuine clocks allow ─────────────────
@pytest.mark.parametrize("name", [
    "g", "en", "enable", "valid", "sel", "clken", "enclk", "clk_en", "en_clk",
    "clkg", "clkgate", "clk_gate", "clk_ce", "clk_enable", "data_en"])
def test_enable_and_generic_guards_are_not_clock(name):
    assert H._is_clock_guard(name) is False


@pytest.mark.parametrize("name", [
    "clk", "clock", "ck", "hclk", "pclk", "sclk", "mclk", "aclk",
    "clk0", "clk1", "clk_main", "clock_a"])
def test_genuine_clock_names_are_clock(name):
    assert H._is_clock_guard(name) is True


# ── end-to-end _is_intended_transparent_latch ─────────────────────────────────
def _mod(guard):
    return (f"module TopModule(input {guard}, input d, output reg y);\n"
            f"  always @(*) begin if ({guard}) y = d; end\nendmodule\n")


@pytest.mark.parametrize("guard", ["g", "en", "clken", "enclk", "clk_en",
                                   "clkgate", "valid"])
def test_accidental_latch_with_nonclock_guard_not_intended(guard):
    # §4.05 NO-LEAK: an accidental forgot-the-else latch guarded by a
    # data-enable / clock-enable / generic signal must NOT be deemed intended.
    assert H._is_intended_transparent_latch(_mod(guard), "y") is False


@pytest.mark.parametrize("guard", ["clk", "clock", "ck", "hclk", "clk0"])
def test_intended_transparent_latch_with_clock_guard_is_intended(guard):
    # the genuine VerilogEval intended transparent latch idiom stays allowed.
    assert H._is_intended_transparent_latch(_mod(guard), "y") is True


def test_multiarm_clock_guarded_still_blocks():
    # even a clock guard does not exempt a multi-arm forgot-a-path latch.
    src = ("module TopModule(input clk, input s, input d, output reg y);\n"
           "  always @(*) begin if (clk) y = d; else if (s) y = 1'b0; end\n"
           "endmodule\n")
    assert H._is_intended_transparent_latch(src, "y") is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
