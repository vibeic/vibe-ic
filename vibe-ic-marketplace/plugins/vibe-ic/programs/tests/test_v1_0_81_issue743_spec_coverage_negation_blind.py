"""ORGANIC #743 [P1] — spec_coverage_check._has_reset() was negation-blind: it
matched the bare `reset` keyword with no negation handling, so a purely
combinational prompt whose ONLY reset/clock mention is the NEGATED phrase
"operates entirely combinationally, with no clock or reset inputs" derived a
PHANTOM reset-behavior requirement and HARD-BLOCKED the correct design under
--strict (exit 1).

Fix: requirement derivation for reset/clock detects NEGATED-feature phrasing
("no clock or reset inputs", "no reset", "without a reset", "combinational …
no clock") and SUPPRESSES the derived requirement; a real reset mention still
derives it. chip-AGNOSTIC (pure negation grammar).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import spec_coverage_check as S  # noqa: E402

_PROG = _PROGRAMS / "spec_coverage_check.py"

# the issue's 驗收 verbatim shape.
_COMB_SPEC = ("The module operates entirely combinationally, with no clock or "
              "reset inputs. Output y = a & b.\n")
_COMB_RTL = "module m(input a,b, output y); assign y=a&b; endmodule\n"


# ── unit: negation-aware presence ────────────────────────────────────────────
def test_has_reset_suppressed_on_negated_mention():
    assert S._has_reset("with no clock or reset inputs") is False
    assert S._has_reset("the module has no reset") is False
    assert S._has_reset("operates without a reset") is False
    assert S._has_reset("combinational logic; no reset, no clock") is False


def test_has_clock_suppressed_on_negated_mention():
    assert S._has_clock("with no clock or reset inputs") is False
    assert S._has_clock("purely combinational, no clock") is False


def test_real_reset_still_detected():
    assert S._has_reset("On reset the counter clears to 0") is True
    assert S._has_reset("an active-low reset clears the register") is True
    # mixed: a negated mention AND a real one → present (the real one wins).
    assert S._has_reset(
        "There is no power-on reset, but a synchronous reset clears X") is True


def test_real_clock_still_detected():
    assert S._has_clock("On the rising edge of clk the output updates") is True


def test_noleak_negation_does_not_cross_comma_into_real_reset():
    """§4.05 (adversarial-review HIGH) — a negation in one clause must NOT drop a
    real reset in a comma-joined sibling clause. Each of these is a genuinely
    sequential reset design that MUST keep its reset requirement."""
    for c in (
        "There is no enable input, the reset clears X",
        "there is no halt signal, reset returns the core to idle",
        "no clock gating, reset is active low",
        # the issue's OWN cited counter-example that must not be suppressed:
        "without waiting, the module asserts reset",
        "regardless of the lack of an enable, reset clears X",
    ):
        assert S._has_reset(c) is True, c


def test_suppress_post_keyword_negation():
    """The over-derive residual: a negation AFTER the keyword in the same clause
    (a reset is not required / never present / none) must also suppress."""
    for c in ("A reset is not required.", "reset is never present",
              "reset: none", "the reset is not applicable here"):
        assert S._has_reset(c) is False, c


# ── end-state via the real program (the issue's 驗收) ─────────────────────────
def _run_strict(tmp_path, spec, rtl):
    sp = tmp_path / "spec.txt"
    rp = tmp_path / "rtl.sv"
    sp.write_text(spec)
    rp.write_text(rtl)
    return subprocess.run(
        [sys.executable, str(_PROG), "--spec", str(sp), "--rtl", str(rp),
         "--strict"], capture_output=True, text=True)


def test_acceptance_combinational_not_blocked_strict(tmp_path):
    """END-STATE via the real program on a tmp_path defect artifact: the negated
    'no clock or reset inputs' prompt no longer derives a phantom reset
    requirement, so --strict exits 0 for the correct combinational design."""
    cp = _run_strict(tmp_path, _COMB_SPEC, _COMB_RTL)
    assert cp.returncode == 0, (cp.returncode, cp.stdout, cp.stderr)
    assert "reset behavior" not in cp.stdout, cp.stdout


def test_noleak_real_reset_still_blocks_strict_without_tb(tmp_path):
    """§4.05 no-leak: a real 'reset clears X' prompt STILL derives the reset
    requirement, so --strict with no TB still BLOCKs (rc=1)."""
    spec = ("On posedge clk, an active-low reset clears the counter to 0. "
            "Output count[7:0].\n")
    rtl = ("module m(input clk, rst_n, output reg [7:0] count); "
           "always @(posedge clk) if(!rst_n) count<=0; else count<=count+1; "
           "endmodule\n")
    cp = _run_strict(tmp_path, spec, rtl)
    assert cp.returncode == 1, (cp.returncode, cp.stdout)
    assert "reset behavior" in cp.stdout


# ── #478 defect-artifact + end-state: shape the issue's ## 驗收 artifact DIRECTLY
# in tmp_path (not via a helper) and assert the END state via the real program.
# Mirrors the issue body verbatim:
#   printf 'The module operates entirely combinationally, with no clock or reset inputs. Output y = a & b.' > comb.txt
#   printf 'module m(input a,b, output y); assign y=a&b; endmodule' > comb.sv
#   python3 programs/spec_coverage_check.py --spec comb.txt --rtl comb.sv --strict
def test_acceptance_endstate_direct_artifact(tmp_path):
    """END-STATE: the negated-phrase combinational design exits 0 under --strict
    (no phantom reset requirement), proving the #743 false-block is gone."""
    (tmp_path / "comb.txt").write_text(_COMB_SPEC)
    (tmp_path / "comb.sv").write_text(_COMB_RTL)
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--spec", str(tmp_path / "comb.txt"),
         "--rtl", str(tmp_path / "comb.sv"), "--strict"],
        capture_output=True, text=True)
    assert cp.returncode == 0, (cp.returncode, cp.stdout, cp.stderr)
    assert "reset behavior" not in cp.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
