"""The coverage build never searched the directory its own RTL came from.

MEASURED, opentitan_aes at v1.15.80: `verilator_coverage` died with

    %Error: .../phase2/stage1/rtl/lc_ctrl_pkg.sv:6:10:
            Cannot find include file: 'prim_assert.sv'
    ... Looked in: .../sim_full_stack/ , .../sim/cov_build/ , and bare names

while `prim_assert.sv` was staged in `.../phase2/stage1/rtl/` — the same
directory as the file including it. `verilate_tb_and_run` passed only
`-I{tb.parent}`. Handing a file to the compiler does not make that file's own
directory searchable for its `` `include ``s.

CONSEQUENCE, which is why this is not cosmetic: `coverage_verilator.json` was
never produced, so `coverage_closure` and
`functional_state_transition_coverage_check` both returned rc=2
EXECUTION_ERROR. A missing TOOL INPUT was surfaced as if the design had no
coverage to measure.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import verilator_coverage_measure as V  # noqa: E402


def _capture_argv(tmp_path: Path, rtl_dirname: str = "rtl"):
    """Drive the real command builder; capture argv instead of running it."""
    tbdir = tmp_path / "sim"
    rtldir = tmp_path / rtl_dirname
    tbdir.mkdir(parents=True, exist_ok=True)
    rtldir.mkdir(parents=True, exist_ok=True)
    tb = tbdir / "tb_top.v"
    tb.write_text("module tb_top; endmodule\n")
    a = rtldir / "pkg_a.sv"
    a.write_text('`include "hdr_b.svh"\nmodule pkg_a; endmodule\n')
    (rtldir / "hdr_b.svh").write_text("`define X 1\n")
    seen = {}

    def exec_fn(argv, cwd):
        seen.setdefault("argv", list(argv))
        # Fail the BUILD the way a missing include does, so the function
        # raises before trying to read a coverage.dat that will not exist.
        return 1, "", "stub"

    try:
        V.verilate_tb_and_run([str(a)], str(tb), str(tmp_path / "b"),
                              str(tmp_path / "b"), exec_fn=exec_fn)
    except SystemExit:
        pass
    return seen.get("argv", []), tbdir, rtldir


def test_the_rtl_directory_is_an_include_path(tmp_path):
    """THE FALSIFIER. Red while only the TB directory is passed."""
    argv, _tbdir, rtldir = _capture_argv(tmp_path)
    assert argv, "the command was never built"
    assert f"-I{rtldir}" in argv, (
        "the RTL source's own directory is not on the include path, so a "
        "`include of a sibling header cannot resolve. argv="
        f"{[a for a in argv if a.startswith('-I')]}")


def test_the_testbench_directory_is_still_an_include_path(tmp_path):
    """DIRECTIONAL CONTROL — passes in BOTH arms, and must.

    The TB dir was the ONLY include path before; adding more must not drop it.
    """
    argv, tbdir, _rtldir = _capture_argv(tmp_path)
    assert f"-I{tbdir}" in argv


def test_a_shared_directory_is_not_passed_twice(tmp_path):
    """Control: TB and RTL in one directory yields ONE -I, not a duplicate."""
    argv, tbdir, rtldir = _capture_argv(tmp_path, rtl_dirname="sim")
    assert tbdir == rtldir
    incs = [a for a in argv if a.startswith("-I")]
    assert len(incs) == len(set(incs)), f"duplicate include paths: {incs}"


def test_every_distinct_rtl_directory_is_covered(tmp_path):
    """RTL split across two trees: both directories must be searchable."""
    tbdir = tmp_path / "sim"
    tbdir.mkdir(parents=True)
    tb = tbdir / "tb_top.v"
    tb.write_text("module tb_top; endmodule\n")
    d1, d2 = tmp_path / "r1", tmp_path / "r2"
    for d in (d1, d2):
        d.mkdir(parents=True)
    (d1 / "a.sv").write_text("module a; endmodule\n")
    (d2 / "b.sv").write_text("module b; endmodule\n")
    seen = {}

    def exec_fn(argv, cwd):
        seen.setdefault("argv", list(argv))
        return 1, "", "stub"

    try:
        V.verilate_tb_and_run([str(d1 / "a.sv"), str(d2 / "b.sv")], str(tb),
                              str(tmp_path / "b"), str(tmp_path / "b"),
                              exec_fn=exec_fn)
    except SystemExit:
        pass
    argv = seen.get("argv", [])
    assert f"-I{d1}" in argv and f"-I{d2}" in argv, (
        f"not every RTL directory is searchable: "
        f"{[a for a in argv if a.startswith('-I')]}")


def test_the_sources_are_still_passed_as_arguments(tmp_path):
    """Control: include paths ADD to the command, they do not replace the
    source list. Passes in both arms."""
    argv, _tbdir, rtldir = _capture_argv(tmp_path)
    assert str(rtldir / "pkg_a.sv") in argv
