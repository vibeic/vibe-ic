"""ORGANIC #713 — reused-IP nested-`include` closure gap.

DEFECT (round-10 v1.0.73 6-IC clean-room; lowRISC-derived REUSED-IP SoC):
  The SV-frontend synth fallback AND the reference-TB sv2v pre-pass staged a
  closure built from HEADER globs only (*.svh / *.vh / *.h / *_pkg.*) and passed
  a SINGLE `-I` at the rtl ROOT. A vendor IP `include`s a sibling .sv that lives
  ONLY in a NESTED rtl/**/ subdir (e.g. `include "prim_assert.sv"`, with
  prim_assert.sv at rtl/vendor/lowrisc_ip/prim/rtl/) → the `include`d .sv was
  never staged and the nested dir was on no `-I` path → slang/sv2v
  'Lexical error: Could not find file "prim_assert.sv"'. (The .svh dummy-macros
  WAS root-staged by the header rglob — the exact header-vs-.sv asymmetry.)

FIX (chip-AGNOSTIC, pure path/grammar — no chip/vendor literal):
  (1) `_v713_includable_sv_closure` collects nested rtl/**/*.sv whose basename is
      `` `include ``d somewhere under rtl/ but is NOT read-as-source → STAGED flat
      so a basename `include` resolves; wired into BOTH the synth fallback
      closure_extra and the TB sv2v pre-pass closure_extra.
  (2) `_v713_include_dirs` → a SEPARATE `-I` per rtl/**/ subdir holding an
      include-able file (mounted-tree synth path).
  (3) `_v713_mk_include_dirs` parses input/reference_flow/**/*.mk
      VERILOG_INCLUDE_DIRS and adds those dirs to `-I`.

§4.05 NO-LEAK: a nested .sv that is NOT `` `include ``d anywhere is never staged
  (only genuine include-candidates are added); a .sv already in the read-as-
  source list is never double-staged; `_v713_rtl_root_of` returns the PROJECT
  rtl root (phase2/stage1/rtl), never a vendor IP's own nested rtl/ subdir.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


















def test_synth_fallback_wires_helper():
    """The synth fallback references the #713 closure helper (regression guard
    that the wiring is not silently removed)."""
    src = (_PROGRAMS / "design_one_shot_runner.py").read_text()
    assert "_v713_includable_sv_closure" in src
    assert "inc_flag" in src
    # both -I sites use the multi-dir flag, not the old single inc_dir
    assert "-DSYNTHESIS -DYOSYS {inc_flag}" in src  # #115: synth-bound frontends define YOSYS
    assert "sv2v -DSYNTHESIS -DYOSYS {inc_flag}" in src  # #115


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
