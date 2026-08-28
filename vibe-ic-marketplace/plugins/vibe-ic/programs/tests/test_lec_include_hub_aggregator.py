#!/usr/bin/env python3
"""Include-hub aggregators must not double-define the gold (LEC + phase-3 synth).

FIELD REPORT (ChipFoundry/eFabless caravel_user_project, top user_project_wrapper):
the design's own `verilog/rtl/` ships `uprj_netlists.v`, whose whole body is a
roll-up of `` `include ``s of its SIBLINGS (`defines.v`, `user_project_wrapper.v`,
`user_proj_example.v`) — a file meant to be compiled ALONE. Both the LEC gold
read and phase-3 synth globbed the directory, so they fed the hub AND the files
it includes to ONE read. Every included module was defined twice:

    error: duplicate definition of 'user_project_wrapper' [-Wduplicate-definition]
    error: duplicate definition of 'user_proj_example'
    error: duplicate definition of 'counter'

The read ABORTS, so the LEC built 0 compared points and phase-3 synth produced no
netlist (then SKIPped DRC and WAIVEd LVS for want of a GDS) — on a design that is
correct and synthesises cleanly.

SCOPE NOTE — the VERDICT half needs no change and none is made here. A zero-
compared-points run is ALREADY reported honestly: #192's stage-progress
observable (`frontend_aborted_before_elaboration`) classifies a stopped-at-the-
read run as INCONCLUSIVE, not a false NOT_EQUIVALENT, and #208's follow-up
exits 3 so it is booked WAIVED-DEFERRED rather than a bare PASS. Verified
against a REAL yosys log in `test_zero_point_hub_abort_is_inconclusive_not_fail`
below. What was missing is that the comparison never HAPPENED — this change is
what turns the honest non-result into an actual comparison.

chip-AGNOSTIC: every fixture is a synthetic 2-module design; the predicate is
pure `` `include ``/`module`/`` `define `` grammar with no chip, vendor, path or
SKU literal.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _rtl_include_hub as hub  # noqa: E402
import lec_run  # noqa: E402

import _progress_run as _pr  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
_DEFINES = "`define WIDTH 8\n"
_COUNTER = ("module counter(input clk, input rst, output reg [`WIDTH-1:0] q);\n"
            "  always @(posedge clk) if (rst) q <= 0; else q <= q + 1;\n"
            "endmodule\n")
_TOP = ("module top(input clk, input rst, output [`WIDTH-1:0] q);\n"
        "  counter u(.clk(clk), .rst(rst), .q(q));\n"
        "endmodule\n")
# The aggregator: `include`s siblings that are ALSO staged standalone.
_HUB = ('`include "defines.v"\n`include "counter.v"\n`include "top.v"\n')


def _hub_design(root: Path) -> Path:
    """A caravel-shaped gold dir: hub + the standalone siblings it includes."""
    d = root / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    (d / "defines.v").write_text(_DEFINES)
    (d / "counter.v").write_text(_COUNTER)
    (d / "top.v").write_text(_TOP)
    (d / "uprj_netlists.v").write_text(_HUB)
    return d


def _plain_design(root: Path) -> Path:
    """CONTROL: the same design with NO aggregator at all."""
    d = root / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    (d / "defines.v").write_text(_DEFINES)
    (d / "counter.v").write_text(_COUNTER)
    (d / "top.v").write_text(_TOP)
    return d


# ---------------------------------------------------------------------------
# 1. the aggregator is dropped from the gold read
# ---------------------------------------------------------------------------
def test_gold_files_drop_the_include_hub_aggregator(tmp_path):
    got = [Path(p).name for p in lec_run._resolve_gold_files(_hub_design(tmp_path))]
    assert "uprj_netlists.v" not in got, (
        "the hub was fed alongside the siblings it includes -> every included "
        "module is defined twice and the read aborts at 0 compared points")
    assert set(got) == {"defines.v", "counter.v", "top.v"}


# ---------------------------------------------------------------------------
# 2. REGRESSION CONTROL — a design WITHOUT an aggregator is untouched.
#    This is the regression the file-list change could plausibly cause: an
#    over-eager filter that drops real RTL leaves the design unsynthesisable.
# ---------------------------------------------------------------------------
def test_design_without_aggregator_keeps_every_file(tmp_path):
    got = [Path(p).name for p in lec_run._resolve_gold_files(_plain_design(tmp_path))]
    assert set(got) == {"defines.v", "counter.v", "top.v"}, (
        "no file in this set includes a sibling, so nothing may be dropped")


def test_leaf_including_a_pure_macro_header_is_never_dropped(tmp_path):
    """#614 preservation. A real RTL leaf that `include`s a MACRO HEADER
    sibling (no `module` decl) is ordinary composition, NOT an aggregator.
    Dropping it removes a real module and synth dies "unknown module"."""
    d = tmp_path / "rtl"
    d.mkdir(parents=True)
    (d / "prim_assert.svh.v").write_text("`define ASSERT(x)\n")   # header, no module
    (d / "leaf.v").write_text('`include "prim_assert.svh.v"\n' + _COUNTER)
    got = [Path(p).name for p in lec_run._resolve_gold_files(d)]
    assert "leaf.v" in got, "a leaf including a module-less header is not a hub"


def test_commented_out_include_is_not_an_aggregator_signal(tmp_path):
    d = tmp_path / "rtl"
    d.mkdir(parents=True)
    (d / "counter.v").write_text(_COUNTER)
    (d / "top.v").write_text('// `include "counter.v"\n' + _TOP)
    got = [Path(p).name for p in lec_run._resolve_gold_files(d)]
    assert set(got) == {"counter.v", "top.v"}


def test_degenerate_all_hubs_falls_back_to_the_full_list(tmp_path):
    """An empty source list is worse than a duplicate definition: the caller
    must still read something and emit an honest verdict."""
    d = tmp_path / "rtl"
    d.mkdir(parents=True)
    (d / "a.v").write_text('`include "b.v"\nmodule a; endmodule\n')
    (d / "b.v").write_text('`include "a.v"\nmodule b; endmodule\n')
    got = [Path(p).name for p in lec_run._resolve_gold_files(d)]
    assert set(got) == {"a.v", "b.v"}


# ---------------------------------------------------------------------------
# 3. single-unit ordering — macro headers must precede their users
# ---------------------------------------------------------------------------
def test_macro_headers_are_ordered_first(tmp_path):
    """`read_slang --single-unit` concatenates the CLI files IN ORDER, so a
    macro used before its defining header is still an unknown directive.
    Alphabetically `counter.v` < `defines.v`, so plain sorting is NOT enough —
    this is exactly the case the field patch would still have failed."""
    got = [Path(p).name for p in lec_run._resolve_gold_files(_hub_design(tmp_path))]
    assert got[0] == "defines.v", (
        f"the pure macro header must be concatenated first, got order {got}")


def test_macro_header_ordering_is_a_noop_without_headers(tmp_path):
    d = tmp_path / "rtl"
    d.mkdir(parents=True)
    (d / "b.v").write_text("module b; endmodule\n")
    (d / "a.v").write_text("module a; endmodule\n")
    got = [Path(p).name for p in lec_run._resolve_gold_files(d)]
    assert got == ["a.v", "b.v"], "plain alphabetical order is preserved"


def test_single_unit_flag_is_emitted_on_the_slang_gold_read():
    s = lec_run.build_equiv_script(["/g.sv"], "/n.v", "top", None,
                                   gold_frontend="slang")
    assert "read_slang --single-unit /g.sv" in s


# ---------------------------------------------------------------------------
# 4. NO-LEAK — the whole risk of this change is weakening a real detector.
# ---------------------------------------------------------------------------
def test_genuine_non_equivalence_still_reports_not_equivalent():
    """A COMPLETED miter that left points unproven is a real FAIL and must be
    entirely untouched by the file-list / single-unit change."""
    log = (
        "1. Executing SLANG frontend.\n"
        "2. Executing HIERARCHY pass.\n"
        "3. Executing EQUIV_MAKE pass.\n"
        "4. Executing EQUIV_STATUS pass.\n"
        "Found 120 $equiv cells in equiv:\n"
        "  Of those cells 118 are proven and 2 are unproven.\n"
        "  Unproven $equiv cells: $equiv$\\q[3]\n"
    )
    p = lec_run.parse_equiv_output(log)
    assert p["verdict"] == "FAIL"
    assert p["equivalent"] is False


def test_zero_point_hub_abort_is_inconclusive_not_fail():
    """#192/#208 ALREADY cover the zero-compared-points path — this pins that
    coverage so the LEC half of the field report stays fixed.

    The log is the REAL yosys transcript shape of the duplicate-definition
    abort: the SLANG frontend pass announced, and NO design-building pass ever
    ran. Zero evidence in either direction must never be asserted as
    NOT_EQUIVALENT."""
    log = (
        "1. Executing SLANG frontend.\n"
        "in file included from uprj_netlists.v:2:\n"
        "counter.v:1:8: error: duplicate definition of 'counter' "
        "[-Wduplicate-definition]\n"
        "Build failed: 4 errors, 0 warnings\n"
    )
    aborted, _why = lec_run.frontend_aborted_before_elaboration(log)
    assert aborted is True
    p = lec_run.parse_equiv_output(log)
    assert p["verdict"] == "INCONCLUSIVE", (
        "a run that stopped AT the read compared 0 points and carries no "
        "equivalence evidence — it must never be booked NOT_EQUIVALENT")
    assert p["equivalent"] is False    # and never a vacuous PASS


# ---------------------------------------------------------------------------
# 5. phase-3 synth applies the same exclusion
# ---------------------------------------------------------------------------
def test_phase3_synth_shares_the_same_aggregator_filter(tmp_path):
    import phase3_one_shot_runner as p3
    d = _hub_design(tmp_path)
    silicon = sorted(d.glob("*.sv")) + sorted(d.glob("*.v"))
    kept = [p.name for p in p3._drop_include_hubs(silicon)]
    assert "uprj_netlists.v" not in kept
    assert set(kept) == {"defines.v", "counter.v", "top.v"}
    # and the no-aggregator control is untouched
    plain = _plain_design(tmp_path / "ctl")
    kept2 = [p.name for p in
             p3._drop_include_hubs(sorted(plain.glob("*.v")))]
    assert set(kept2) == {"defines.v", "counter.v", "top.v"}


def test_phase2_selector_delegates_to_the_same_predicate(tmp_path):
    """The three selectors must not drift apart — phase-2's board-wrapper
    signal 1 is now the SAME function the gold read and phase-3 call."""
    import design_one_shot_runner as p2
    d = _hub_design(tmp_path)
    sibs = {p.name for p in d.iterdir()}
    assert p2._is_fpga_board_wrapper(d / "uprj_netlists.v", sibs) is True
    assert p2._is_fpga_board_wrapper(d / "top.v", sibs) is False


# ---------------------------------------------------------------------------
# 6. INTEGRATION — the fixture must actually ELABORATE and compare >0 points.
#    Skips when no path-visible vibeic-eda container is available.
# ---------------------------------------------------------------------------
def _yosys_available() -> bool:
    try:
        r = _pr.run(
            ["docker", "exec", "vibeic-eda", "bash", "-lc", "which yosys"],
            capture_output=True, text=True)
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


@pytest.mark.skipif(not _yosys_available(),
                    reason="no path-visible vibeic-eda container")
def test_single_unit_does_not_break_a_macro_redefining_design():
    """CONTROL for the `--single-unit` half. Collapsing per-file compilation
    units means two files that each `` `define `` the SAME macro now share one
    preprocessor scope. Measured in-container: slang emits a `-Wredef-macro`
    WARNING, NOT an error — the build still succeeds and the top elaborates.
    So single-unit does not regress a design that read cleanly before."""
    import tempfile
    import shutil
    work = Path(tempfile.mkdtemp(prefix=".lec_su_it_", dir=str(Path.home())))
    try:
        d = work / "rtl"
        d.mkdir(parents=True)
        (d / "a.v").write_text(
            "`define W 8\nmodule a(output [`W-1:0] o); assign o=0; endmodule\n")
        (d / "b.v").write_text(
            "`define W 4\nmodule b(output [`W-1:0] o); assign o=0; endmodule\n")
        (d / "top.v").write_text(
            "module top(output [7:0] x, output [3:0] y);\n"
            "  a ia(.o(x)); b ib(.o(y));\nendmodule\n")
        files = " ".join(lec_run._resolve_gold_files(d))
        cmd = (f"export PATH=/foss/tools/yosys/bin:$PATH && "
               f"yosys -p 'read_slang --single-unit {files} --top top; "
               f"hierarchy -check -top top' 2>&1")
        r = _pr.run(
            ["docker", "exec", "vibeic-eda", "bash", "-lc", cmd],
            capture_output=True, text=True)
        out = r.stdout or ""
        assert "Build succeeded" in out, out[-1500:]
        assert "Top module:  \\top" in out, out[-1500:]
    finally:
        shutil.rmtree(work, ignore_errors=True)


@pytest.mark.skipif(not _yosys_available(),
                    reason="no path-visible vibeic-eda container")
def test_hub_design_elaborates_after_the_fix(tmp_path):
    """END-TO-END: the selected file list must elaborate a top module, where
    the unfiltered glob aborted with duplicate definitions."""
    import tempfile
    import shutil
    work = Path(tempfile.mkdtemp(prefix=".lec_hub_it_", dir=str(Path.home())))
    try:
        d = _hub_design(work)
        files = " ".join(lec_run._resolve_gold_files(d))
        cmd = (f"export PATH=/foss/tools/yosys/bin:$PATH && "
               f"yosys -p 'read_slang --single-unit {files} --top top; "
               f"hierarchy -check -top top' 2>&1")
        r = _pr.run(
            ["docker", "exec", "vibeic-eda", "bash", "-lc", cmd],
            capture_output=True, text=True)
        out = r.stdout or ""
        assert "duplicate definition" not in out, out[-1500:]
        assert "unknown macro" not in out, out[-1500:]
        assert "Top module:  \\top" in out, out[-1500:]
    finally:
        shutil.rmtree(work, ignore_errors=True)
