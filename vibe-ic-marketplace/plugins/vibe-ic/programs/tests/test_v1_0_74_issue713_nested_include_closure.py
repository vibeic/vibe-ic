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

import design_one_shot_runner as P  # noqa: E402

BT = chr(96)  # backtick


def _mk_reused_ip_tree(root: Path):
    """A lowRISC-shaped reused-IP rtl tree: a source .sv in one vendor subdir
    that `` `include ``s prim_assert.sv living ONLY in a different nested dir."""
    rtl = root / "phase2" / "stage1" / "rtl"
    prim = rtl / "vendor" / "lowrisc_ip" / "prim" / "rtl"
    ibex = rtl / "vendor" / "ibex" / "rtl"
    prim.mkdir(parents=True)
    ibex.mkdir(parents=True)
    src = ibex / "ibex_compressed_decoder.sv"
    src.write_text(f'{BT}include "prim_assert.sv"\nmodule ibex_compressed_decoder; '
                   f'endmodule\n')
    (prim / "prim_assert.sv").write_text("// assertion macros\n")
    (prim / "prim_assert_dummy_macros.svh").write_text("// dummy svh\n")
    (rtl / "top_pkg.sv").write_text("package top_pkg; endpackage\n")
    return rtl, src, (prim / "prim_assert.sv")


def test_rtl_root_is_project_root_not_vendor_nested(tmp_path):
    """`_v713_rtl_root_of` must return the PROJECT rtl root, NOT the nearest
    vendor `rtl/` ancestor (the IP nests its own rtl/ subdirs)."""
    rtl, src, _ = _mk_reused_ip_tree(tmp_path)
    root = P._v713_rtl_root_of([str(src)])
    assert root is not None
    assert str(root).endswith("phase2/stage1/rtl"), str(root)


def test_nested_included_sv_is_in_closure(tmp_path):
    """END-STATE: the nested `` `include ``d prim_assert.sv (in a DIFFERENT subdir
    than the source) is collected for staging."""
    rtl, src, prim_assert = _mk_reused_ip_tree(tmp_path)
    closure = P._v713_includable_sv_closure(rtl, [str(src)])
    names = [p.name for p in closure]
    assert "prim_assert.sv" in names, names
    # the source file itself is never re-staged as a closure include
    assert "ibex_compressed_decoder.sv" not in names


def test_noleak_non_included_sv_not_staged(tmp_path):
    """§4.05: a nested .sv that is `` `include ``d by NOTHING is not staged."""
    rtl, src, _ = _mk_reused_ip_tree(tmp_path)
    (rtl / "vendor" / "ibex" / "rtl" / "standalone_unit.sv").write_text(
        "module standalone_unit; endmodule\n")
    closure = P._v713_includable_sv_closure(rtl, [str(src)])
    assert "standalone_unit.sv" not in [p.name for p in closure]


def test_include_dirs_cover_nested_subdir(tmp_path):
    """`_v713_include_dirs` returns a SEPARATE dir for the nested prim/rtl so a
    mounted-tree `-I` per dir resolves the nested `include`."""
    rtl, _, _ = _mk_reused_ip_tree(tmp_path)
    dirs = [str(d) for d in P._v713_include_dirs(rtl)]
    assert any(d.endswith("lowrisc_ip/prim/rtl") for d in dirs), dirs
    # the rtl root itself (holds top_pkg.sv) is also an include dir
    assert any(d.endswith("phase2/stage1/rtl") for d in dirs), dirs


def test_mk_verilog_include_dirs_parsed(tmp_path):
    """`_v713_mk_include_dirs` extracts VERILOG_INCLUDE_DIRS from an ORFS .mk
    and resolves it to the existing nested dir."""
    rtl, _, _ = _mk_reused_ip_tree(tmp_path)
    rf = tmp_path / "input" / "reference_flow"
    rf.mkdir(parents=True)
    # relative path resolvable against the project rtl dir
    (rf / "orfs_config.mk").write_text(
        "VERILOG_INCLUDE_DIRS = vendor/lowrisc_ip/prim/rtl/\n")
    dirs = [str(d) for d in P._v713_mk_include_dirs(tmp_path)]
    assert any(d.endswith("lowrisc_ip/prim/rtl") for d in dirs), dirs


def test_mk_skips_unresolved_make_vars(tmp_path):
    """§4.05: a `$(VAR)`-style make reference we cannot resolve is skipped,
    not emitted as a bogus dir."""
    _mk_reused_ip_tree(tmp_path)
    rf = tmp_path / "input" / "reference_flow"
    rf.mkdir(parents=True)
    (rf / "config.mk").write_text(
        "VERILOG_INCLUDE_DIRS = $(PLATFORM_DIR)/include\n")
    dirs = P._v713_mk_include_dirs(tmp_path)
    assert dirs == [], dirs


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
