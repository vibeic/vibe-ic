#!/usr/bin/env python3
"""ORGANIC #760 [P1, chip-AGNOSTIC] — spec_coverage_check derived an OVER-STRICT
overflow checklist item. The overflow/signed/byteorder/handshake structural-
keyword loop did a bare `_OVERFLOW_RE.search(spec_text)` bypassing the #743
clause-scoped guard, so a WIDTH-SIZING note "sized to prevent overflow" (a
structural fact about how the design AVOIDS the condition, often carried verbatim
from an RTL inline comment) became a phantom behavioral requirement that
hard-BLOCKed a correct design under --strict.

Fix: `_is_preventive_structural_fact` + a clause-scoped guard on the overflow
kind — a bare preventive/width-sizing clause (prevent/avoid/sized-to/wide-enough
overflow|underflow noun) with NO co-occurring active-handling verb
(saturate/clamp/wrap/clip/round/correct/truncat) is skipped; a real
"saturate to prevent overflow and clamp" is KEPT (the active verb co-occurs).

§4.05 NO-LEAK: an ACTIVE overflow-handling requirement (saturate/clamp/...) whose
TB does not exercise the overflow region must STILL derive the item and BLOCK —
the relaxation suppresses ONLY a bare preventive width-note, never a behavioral
requirement.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import spec_coverage_check as M  # noqa: E402

_PROG = _PROGRAMS / "spec_coverage_check.py"

_TB_NO_OVERFLOW = (
    "module tb; reg clk; reg [7:0] start_val, step_val; wire [9:0] result;\n"
    "dut u(clk, start_val, step_val, result);\n"
    "initial begin clk=0; start_val=1; step_val=2; #1; $finish; end\n"
    "endmodule\n")


def _run(tmp_path, spec_text, tb_text=_TB_NO_OVERFLOW):
    sp = tmp_path / "spec.md"
    tb = tmp_path / "tb.sv"
    sp.write_text(spec_text)
    tb.write_text(tb_text)
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--spec", str(sp), "--tb", str(tb),
         "--strict"], capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# ── (a) NEW-PATH: a preventive width-sizing note is not a behavioral item ─────
def test_760_preventive_helper():
    assert M._is_preventive_structural_fact(
        "the output is sized to prevent overflow", "overflow") is True
    # an active-handling verb in the same clause keeps the requirement.
    assert M._is_preventive_structural_fact(
        "must saturate to prevent overflow and clamp", "overflow") is False


def test_760_sized_to_prevent_overflow_no_phantom(tmp_path):
    rc, out = _run(
        tmp_path,
        "# Arithmetic progression generator\nThe output `result` is "
        "WIDTH_OUT_VAL bits wide, sized to prevent overflow. The generator "
        "emits `result` = start + i*step for i in 0..SEQ_LEN-1.\n")
    assert rc == 0, out
    assert "spec-coverage ok" in out


# ── (b) §4.05 NEGATIVE NO-LEAK: active saturation uncovered still BLOCKs ──────
def test_760_noleak_active_saturate_uncovered_still_blocks(tmp_path):
    rc, out = _run(
        tmp_path,
        "# Saturating counter\nThe counter must saturate to prevent overflow "
        "and clamp `q` at the maximum value.\n")
    assert rc == 1, out
    assert "overflow" in out.lower() or "saturat" in out.lower()


def test_760_noleak_plain_overflow_requirement_uncovered_still_blocks(tmp_path):
    rc, out = _run(
        tmp_path,
        "# Adder\nOn overflow the output `sum` wraps around to zero. The design "
        "handles overflow by wrapping.\n")
    assert rc == 1, out
    assert "overflow" in out.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
