#!/usr/bin/env python3
"""ORGANIC #761 [P2, chip-AGNOSTIC] — spec_coverage_check's worked-example
extractor treated a bare `=` as an input->output separator, so an encoding
LEGEND on a port comment ("00=90 CW, 01=180, 10=270 CW, 11=0") was misparsed as
worked-example DATA pairs and emitted as phantom worked_example checklist items
that hard-blocked a correct design under --strict.

Fix: distinguish the OVERLOADED bare `=` (assignment / arithmetic / encoding
legend) from the unambiguous worked-example arrows (-> => →). A bare-`=` match is
suppressed when its source line is a control-code encoding legend (>=2
comma-separated "N=label" entries on the line); genuine arrow examples and an
isolated bare-`=` data pair are preserved.

§4.05 NO-LEAK: a GENUINE worked example — arrow form (5 -> 12) OR an isolated
bare-`=` data pair (7 = 49) — that the TB does not cover must STILL be derived
and BLOCK; the suppression is surgical to the multi-entry legend line only.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

_PROG = _PROGRAMS / "spec_coverage_check.py"

_TB_MODE = (
    "module tb; reg [1:0] mode; wire [8:0] q; dut u(mode, q);\n"
    "initial begin mode=2'b00; #1; mode=2'b01; #1; $finish; end\n"
    "endmodule\n")


def _run(tmp_path, spec_text, tb_text=_TB_MODE):
    sp = tmp_path / "spec.md"
    tb = tmp_path / "tb.sv"
    sp.write_text(spec_text)
    tb.write_text(tb_text)
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--spec", str(sp), "--tb", str(tb),
         "--strict"], capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# ── (a) NEW-PATH: an encoding legend is not a worked example ──────────────────
def test_761_encoding_legend_no_phantom_worked_example(tmp_path):
    rc, out = _run(
        tmp_path,
        "# Rotary encoder\nThe 2-bit `mode` selects rotation: 00=90 CW, 01=180, "
        "10=270 CW, 11=0. The output `q` reflects the selected mode.\n")
    assert rc == 0, out
    assert "spec-coverage ok" in out
    assert "worked" not in out.lower()


# ── (b) §4.05 NEGATIVE NO-LEAK: genuine worked examples still BLOCK ───────────
def test_761_noleak_arrow_worked_example_uncovered_still_blocks(tmp_path):
    rc, out = _run(
        tmp_path,
        "# Squarer\nFor example, input 5 -> output 25. Another: 9 => 81.\n",
        tb_text=("module tb; reg [7:0] x; wire [15:0] y; dut u(x, y);\n"
                 "initial begin x=3; #1; $finish; end endmodule\n"))
    assert rc == 1, out
    assert "worked" in out.lower() and "GAP" in out


def test_761_noleak_isolated_bare_eq_data_pair_uncovered_still_blocks(tmp_path):
    # numbers chosen to NOT appear in the TB's width literals (else a coincidental
    # substring match would mark the example covered).
    rc, out = _run(
        tmp_path,
        "# Squarer\nWorked example: 33 = 1089.\n",
        tb_text=("module tb; reg [3:0] x; wire [11:0] y; dut u(x, y);\n"
                 "initial begin x=2; #1; $finish; end endmodule\n"))
    assert rc == 1, out
    assert "worked" in out.lower() and "GAP" in out


# ── (d) #478 END-STATE: direct tmp_path artifact + real program, returncode ───
def test_761_endstate_legend_pass_strict(tmp_path):
    """#478 end-state: a spec whose ONLY '=' usage is an encoding legend, with a
    TB driving the mode, exits 0 under --strict (no phantom worked-example)."""
    (tmp_path / "spec.md").write_text(
        "# Rotary encoder\nThe 2-bit `mode` selects rotation: 00=90 CW, "
        "01=180, 10=270 CW, 11=0. The output `q` reflects the selected mode.\n")
    (tmp_path / "tb.sv").write_text(_TB_MODE)
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--spec", str(tmp_path / "spec.md"),
         "--tb", str(tmp_path / "tb.sv"), "--strict"],
        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "spec-coverage ok" in cp.stdout


def test_761_endstate_real_worked_example_blocks_strict(tmp_path):
    """#478 end-state NO-LEAK: a genuine arrow worked-example the TB does not
    cover exits 1 and names the worked_example GAP."""
    (tmp_path / "spec.md").write_text(
        "# Squarer\nWorked example: 5 -> 25.\n")
    (tmp_path / "tb.sv").write_text(
        "module tb; reg [3:0] x; wire [11:0] y; dut u(x, y);\n"
        "initial begin x=2; #1; $finish; end endmodule\n")
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--spec", str(tmp_path / "spec.md"),
         "--tb", str(tmp_path / "tb.sv"), "--strict"],
        capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "worked" in cp.stdout.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
