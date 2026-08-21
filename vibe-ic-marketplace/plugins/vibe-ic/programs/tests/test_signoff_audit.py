"""Unit tests for signoff_audit.py.

Tests verify correct detection of tapeout evidence and flow stage evidence.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'signoff_audit.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(Path(__file__).parent))
import signoff_audit as sa  # noqa: E402
import _gdsii  # noqa: E402
import _si_signoff_fixture  # noqa: E402

# 2026-07-27 (review follow-up): the tape-out GDS slot is credited ONLY by the
# flow's declared stream-out artefact (`phase3/stage4/gds/*.gds`) carrying real
# GDSII substance. These fixtures used to drop `"binary gds data"` into a
# root-level `chip.gds` and expect a certificate — which is exactly the
# "existence-only" shape the slot was tightened to refuse. They now write a
# real minimal stream at the declared path; nothing about what each test is
# ABOUT changes, only that its tape-out artefact is now a tape-out artefact.

# 2026-07-27: tapeout mode gained a FIFTH evidence pillar (LVS). These
# fixtures predate it and asserted a tape-out could be signed off with no
# layout-vs-schematic evidence at all — that was the defect, not the intent
# of these tests, so the fixtures now carry a genuine netgen match and the
# threshold assertions were updated 4 → 5. See
# test_signoff_audit_tapeout_signoff_first.py for the pillar's own tests.
_LVS_MATCH = ("Subcircuit summary:\n"
              "Circuit 1: top                  |Circuit 2: top\n"
              "Netlists match uniquely.\n"
              "Final result: Circuits match uniquely.\n")


def _lvs_signoff(proj):
    """Write the canonical genuine-match LVS sign-off report."""
    (proj / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "phase3" / "lvs.rpt").write_text(_LVS_MATCH)


# 2026-07-28: tapeout mode gained an SI (crosstalk-delay) blocking condition —
# a verdict that proved nothing (or no verdict at all) refuses to certify. The
# fixtures below are about the EVIDENCE PILLARS, so the ones that mean "every
# pillar is present" now also carry a PROVED SI verdict. Fixtures that mean
# "a pillar is missing" are untouched: they must still FAIL, and they do.
def _si_proved(proj):
    """Write the SI verdict a genuinely-checked run produces."""
    _si_signoff_fixture.write_proved_si_report(proj)


# ---------------------------------------------------------------------------
# Tapeout mode
# ---------------------------------------------------------------------------
def test_tapeout_all_evidence_pass(tmp_path):
    _gdsii.write_declared_streamout(tmp_path, "chip.gds")
    (tmp_path / "netlist_mapped.v").write_text("module top(); endmodule")
    (tmp_path / "timing_final.rpt").write_text("timing report")
    (tmp_path / "drc_clean.rpt").write_text("Total violations: 0\n")  # parseable count (#437a)
    _lvs_signoff(tmp_path)
    _si_proved(tmp_path)

    result = sa._check_tapeout(tmp_path)
    assert result.passed is True
    assert result.summary["evidence_count"] == 5


def test_tapeout_3_of_4_strict_fails(tmp_path):
    """Default (strict) threshold requires EVERY slot. Missing DRC must FAIL.
    Regression: prior threshold 3/4 let 7-of-28-step designs pass as
    'signed off' (see LL feedback_plugin_usage_discipline.md, 2026-04-21).
    2026-07-27: the denominator is 5 (LVS pillar added); this fixture has
    gds + netlist + timing = 3, so it is now 3-of-5 and still FAILs.
    """
    _gdsii.write_declared_streamout(tmp_path, "chip.gds")
    (tmp_path / "synth_netlist.v").write_text("module top(); endmodule")
    (tmp_path / "sta_report.rpt").write_text("timing report")
    # No DRC report, no LVS report — 3 evidence slots

    # Ensure strict mode (_LENIENT off) — this is the default
    sa._LENIENT = False
    result = sa._check_tapeout(tmp_path)
    assert result.passed is False  # strict: 3 < 5
    assert result.summary["evidence_count"] == 3
    assert result.summary["threshold"] == 5


def test_tapeout_3_of_4_strict_fail(tmp_path):
    """v1.6.21: lenient mode removed — partial evidence must FAIL strictly.
    2026-07-27: denominator 4 → 5 (LVS pillar)."""
    _gdsii.write_declared_streamout(tmp_path, "chip.gds")
    (tmp_path / "synth_netlist.v").write_text("module top(); endmodule")
    (tmp_path / "sta_report.rpt").write_text("timing report")

    result = sa._check_tapeout(tmp_path)
    assert result.passed is False
    assert result.summary["evidence_count"] == 3
    assert result.summary["threshold"] == 5


def test_tapeout_4_of_5_without_lvs_fails(tmp_path):
    """2026-07-27: the four legacy slots complete, LVS absent → still FAIL.
    A tape-out is DEFINED by a genuine layout-vs-schematic match."""
    _gdsii.write_declared_streamout(tmp_path, "chip.gds")
    (tmp_path / "netlist_mapped.v").write_text("module top(); endmodule")
    (tmp_path / "timing_final.rpt").write_text("timing report")
    (tmp_path / "drc_clean.rpt").write_text("Total violations: 0\n")

    result = sa._check_tapeout(tmp_path)
    assert result.passed is False
    assert result.summary["evidence_count"] == 4
    assert result.summary["threshold"] == 5
    assert result.summary["evidence"]["lvs"] is False


def test_tapeout_1_of_4_fail(tmp_path):
    _gdsii.write_declared_streamout(tmp_path, "chip.gds")
    # Only 1 evidence file

    result = sa._check_tapeout(tmp_path)
    assert result.passed is False
    assert result.summary["evidence_count"] == 1


# ---------------------------------------------------------------------------
# Flow mode
# ---------------------------------------------------------------------------
def test_flow_all_stages_pass(tmp_path):
    (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (tmp_path / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (tmp_path / "sta_timing.rpt").write_text("sta report")

    result = sa._check_flow(tmp_path)
    assert result.passed is True
    assert result.summary["stage_count"] == 4


def test_flow_empty_fail(tmp_path):
    result = sa._check_flow(tmp_path)
    assert result.passed is False
    assert result.summary["stage_count"] == 0


# ---------------------------------------------------------------------------
# Edge case: non-existent directory via CLI
# ---------------------------------------------------------------------------
def test_empty_dir_fail(tmp_path):
    nonexistent = tmp_path / "does_not_exist"
    rc = sa.main([str(nonexistent), "--mode", "tapeout"])
    assert rc == 1


# ---------------------------------------------------------------------------
# v0.52: input/pdk/ exclusion (regression test for the phase2+3_v051 bug)
# ---------------------------------------------------------------------------
def test_tapeout_pdk_gds_does_not_count_as_design_gds(tmp_path):
    """Regression: 2026-04-24 v0.51 fresh-agent shipped only PDK standard
    cell GDS under input/pdk/gds/ and tapeout_signoff_check returned PASS.
    PDK files are inputs, not design output — must be excluded from
    evidence search."""
    pdk_gds_dir = tmp_path / "input" / "pdk" / "gds"
    pdk_gds_dir.mkdir(parents=True)
    (pdk_gds_dir / "stdcell.gds").write_text("pdk stdcell binary")
    pdk_v_dir = tmp_path / "input" / "pdk" / "verilog"
    pdk_v_dir.mkdir(parents=True)
    (pdk_v_dir / "stdcell_synth.v").write_text("module sky130_fd_sc(); endmodule")
    # No design output anywhere

    sa._LENIENT = False
    result = sa._check_tapeout(tmp_path)
    assert result.passed is False, ("PDK files under input/pdk/ must NOT count "
                                    "as design tapeout evidence")
    assert result.summary["evidence_count"] == 0
    assert result.summary["evidence"]["gds"] is False
    assert result.summary["evidence"]["netlist"] is False


def test_tapeout_design_gds_outside_input_passes(tmp_path):
    """Mirror test: same project layout but the design GDS sits at the flow's
    declared stream-out path, phase3/stage4/gds/<top>.gds — that one counts."""
    pdk_gds_dir = tmp_path / "input" / "pdk" / "gds"
    pdk_gds_dir.mkdir(parents=True)
    (pdk_gds_dir / "stdcell.gds").write_text("pdk stdcell binary")
    # Design output at the proper location
    design_gds_dir = tmp_path / "phase3" / "stage4" / "gds"
    design_gds_dir.mkdir(parents=True, exist_ok=True)
    _gdsii.write_gdsii(design_gds_dir / "chip_top.gds")
    (tmp_path / "synth_netlist.v").write_text("module chip_top(); endmodule")
    (tmp_path / "timing_final.rpt").write_text("timing report")
    (tmp_path / "drc_clean.rpt").write_text("Total violations: 0\n")  # parseable count (#437a)
    _lvs_signoff(tmp_path)
    _si_proved(tmp_path)

    sa._LENIENT = False
    result = sa._check_tapeout(tmp_path)
    assert result.passed is True
    assert result.summary["evidence"]["gds"] is True


def test_is_input_path_helper(tmp_path):
    """Direct unit test of the input-path classifier."""
    proj = tmp_path
    cases = [
        (proj / "input" / "pdk" / "gds" / "x.gds", True),
        (proj / "input" / "docs" / "spec.pdf", True),
        (proj / "pdk" / "liberty" / "x.lib", True),
        (proj / "vendor_ref" / "hid_tool", True),
        (proj / "references" / "vendor-rtl" / "x.v", True),
        (proj / "phase3" / "stage4" / "gds" / "chip.gds", False),
        (proj / "phase2" / "stage2" / "synth" / "netlist.v", False),
        (proj / "phase2" / "stage1" / "rtl" / "input_decoder.v", False),  # 'input' as filename, not dir
    ]
    for path, expected in cases:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        assert sa._is_input_path(path, proj) is expected, (
            f"{path.relative_to(proj)} expected is_input={expected}")


def test_has_files_exclude_inputs_default_on(tmp_path):
    """Default behaviour of _has_files excludes input paths."""
    (tmp_path / "input" / "pdk" / "gds").mkdir(parents=True)
    (tmp_path / "input" / "pdk" / "gds" / "stdcell.gds").write_text("x")
    (tmp_path / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (tmp_path / "phase3" / "stage4" / "gds" / "design.gds").write_text("x")

    found_default = sa._has_files(tmp_path, ["*.gds"])
    assert len(found_default) == 1
    # Compare path segments under tmp_path, not the absolute path
    rel_default = found_default[0].relative_to(tmp_path)
    assert "input" not in rel_default.parts and "pdk" not in rel_default.parts

    found_with_inputs = sa._has_files(tmp_path, ["*.gds"], exclude_inputs=False)
    assert len(found_with_inputs) == 2
