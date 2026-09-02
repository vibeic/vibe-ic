"""#662's macro-dependency pool never looked at the tree a REUSED-IP design uses.

MEASURED (opentitan_aes, plugin v1.15.78, pristine benchmark-data corpus): synth
aborted and the remediation hint said

    `ASSERT` is undefined and no defining file was found under
    input/design_src/**/rtl/ — provide the file that `define`s it

while `input/vendor_rtl/prim/prim_assert.sv` and its three
`prim_assert_*_macros.svh` sat staged in that same project carrying exactly
those `define`s. The project has no `input/design_src/` at all, so the pool was
empty and EVERY macro reported not-found.

This is the same discriminator #499/#38 settled for Phase 1, applied to a second
consumer: PROVENANCE, not path spelling. `input/vendor_rtl/` is the other tree a
design stages its inputs in.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as R  # noqa: E402


def _vendor_project(tmp_path: Path) -> Path:
    """A REUSED-IP layout: input/vendor_rtl/<ip>/<file>, with NO rtl/ level."""
    proj = tmp_path / "proj"
    prim = proj / "input" / "vendor_rtl" / "prim"
    prim.mkdir(parents=True)
    (prim / "prim_assert.sv").write_text(
        "`define ASSERT(name, prop) initial begin end\n"
        "`define ASSERT_INIT(name, prop) initial begin end\n")
    (proj / "input" / "vendor_rtl" / "aes").mkdir(parents=True)
    (proj / "input" / "vendor_rtl" / "aes" / "aes.sv").write_text(
        "module aes; `ASSERT(a, 1) endmodule\n")
    return proj


def _design_src_project(tmp_path: Path) -> Path:
    """The layout the helper already supported: .../<ip>/rtl/<file>."""
    proj = tmp_path / "proj"
    rtl = proj / "input" / "design_src" / "core" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "defines.v").write_text("`define ASSERT(name, prop) initial begin end\n")
    return proj


def test_the_pool_finds_a_definer_staged_under_vendor_rtl(tmp_path):
    """THE FALSIFIER. Red while the pool knows only input/design_src/."""
    proj = _vendor_project(tmp_path)
    pool = R._v662_design_src_rtl_files(proj)
    names = {p.name for p in pool}
    assert "prim_assert.sv" in names, (
        "the staged vendor tree carries the file that `define`s the missing "
        f"macro, and the pool did not find it: pool={sorted(names)}")


def _staged_rtl_using_the_macro(proj: Path) -> Path:
    """A compile set that USES `ASSERT` without defining it — the real shape."""
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "chip_top.sv").write_text("module chip_top; `ASSERT(a, 1) endmodule\n")
    return rtl


def test_the_hint_names_the_definer_instead_of_saying_it_does_not_exist(tmp_path):
    """THE OPERATOR-FACING FALSIFIER, through the public entry point.

    Asserted on `hints` from `_v662_resolve_dependency_files`, which exists in
    both arms, so this is a behavioural red and not an AttributeError.
    """
    proj = _vendor_project(tmp_path)
    _staged_rtl_using_the_macro(proj)
    res = R._v662_resolve_dependency_files(proj, auto_stage=False)
    hints = " ".join(res.get("hints") or [])
    assert "ASSERT" in hints, f"the pre-check said nothing about ASSERT: {res}"
    assert "prim_assert.sv" in hints, (
        "the file that `define`s the missing macro is staged in this project "
        f"under input/vendor_rtl/, and the hint does not name it: {hints}")
    assert "no defining file was found" not in hints, (
        f"reported as missing while it is present and merely unsearched: {hints}")


def test_the_oracle_side_of_a_staged_tree_is_never_taken(tmp_path):
    """DIRECTIONAL CONTROL. Broadening the pool must not start reading golden/tb."""
    proj = _vendor_project(tmp_path)
    for bad in ("golden", "tb", "dv", "verif"):
        d = proj / "input" / "vendor_rtl" / "aes" / bad
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{bad}_ref.sv").write_text("`define SHOULD_NOT_BE_SEEN 1\n")
    pool = R._v662_design_src_rtl_files(proj)
    leaked = [str(p) for p in pool
              if {"golden", "tb", "dv", "verif"} & {q.name for q in p.parents}]
    assert leaked == [], f"oracle-side files entered the pool: {leaked}"


def test_design_src_still_works_and_still_requires_the_rtl_level(tmp_path):
    """DIRECTIONAL CONTROL — passes in BOTH arms, and must.

    The `rtl/` restriction is what keeps design_src's own tb/ out; it is kept
    for that root and must not be dropped while broadening.
    """
    proj = _design_src_project(tmp_path)
    stray = proj / "input" / "design_src" / "core" / "tb"
    stray.mkdir(parents=True)
    (stray / "tb_core.sv").write_text("`define TB_ONLY 1\n")
    pool = R._v662_design_src_rtl_files(proj)
    names = {p.name for p in pool}
    assert "defines.v" in names
    assert "tb_core.sv" not in names


def test_a_project_with_neither_tree_yields_an_empty_pool(tmp_path):
    """Control: no staged pool, no invention. Passes in BOTH arms."""
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    _staged_rtl_using_the_macro(proj)
    assert R._v662_design_src_rtl_files(proj) == []
    res = R._v662_resolve_dependency_files(proj, auto_stage=False)
    assert res.get("staged") in (None, [], ())
