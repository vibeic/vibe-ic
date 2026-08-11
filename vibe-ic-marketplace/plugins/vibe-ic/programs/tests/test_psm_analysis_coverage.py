"""A net whose analysis failed must not make the result look better.

Synthetic logs throughout — generic rail names, no design or process is named.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from psm_analysis_coverage import (analysis_coverage, ir_verdict,  # noqa: E402
                                   verdict_basis)

CLEAN = """=== PSM_NET VPWR ===
[INFO PSM-0073] single bump
Worst IR drop  : 0.021 V
=== PSM_NET VGND ===
Worst IR drop  : 0.018 V
"""

WRAPPER_FAILED = CLEAN + """=== PSM_NET VPROG ===
PSM_NONFATAL VPROG: PSM-0069
"""

TOOL_FAILED = CLEAN + """=== PSM_NET VPROG ===
[ERROR PSM-0069] Check connectivity failed on VPROG.
"""

CONNECTIVITY = CLEAN + """[WARNING PSM-0038] Unconnected shape on net VPWR at (239.720um, 152.860um), layer: MET3.
[WARNING PSM-0039] Unconnected instance u_x/VPWR at location (330.630um, 106.090um).
"""

NETS = ["VPWR", "VGND", "VPROG"]


def test_a_clean_log_analyses_everything_it_was_asked_about():
    c = analysis_coverage(CLEAN, ["VPWR", "VGND"])
    assert c["analysed"] == ["VGND", "VPWR"]
    assert c["analysis_failed"] == []


def test_the_wrappers_own_marker_is_read():
    """`PSM_NONFATAL` appeared once in the whole tree — on the line writing it."""
    c = analysis_coverage(WRAPPER_FAILED, NETS)
    assert c["analysis_failed"] == ["VPROG"]
    assert "VPROG" not in c["analysed"]


def test_the_tools_own_line_is_a_second_independent_witness():
    """A wrapper that stopped emitting its marker must not restore the defect."""
    c = analysis_coverage(TOOL_FAILED, NETS)
    assert c["analysis_failed"] == ["VPROG"]


def test_a_failed_analysis_cannot_pass_however_good_the_number_is():
    """THE defect. A failed net contributes no IR line, so the worst-case is the
    worst of the nets that WORKED — the failure makes the number smaller."""
    assert ir_verdict(worst_ir_uv=1.0, budget_uv=180000.0,
                      analysis_failed=["VPROG"],
                      unreached_terminals=[]) == "FAIL"


def test_a_complete_analysis_within_budget_passes():
    assert ir_verdict(1.0, 180000.0, [], []) == "PASS"


def test_a_complete_analysis_over_budget_still_fails():
    """The budget rule is unchanged for the case it was written for."""
    assert ir_verdict(200000.0, 180000.0, [], []) == "FAIL"


def test_the_basis_says_the_number_is_not_about_the_design():
    b = verdict_basis(["VPROG"], [])
    assert "VPROG" in b and "not a statement about the design" in b
    assert "all nets analysed" in verdict_basis([], [])


def test_an_unconnected_shape_is_reported_and_does_not_decide():
    """"the grid has unconnected shapes" is a different question from "did the
    analysis run"; conflating them fires on grids that are merely imperfect.

    The boundary MOVED and this test states where it now is. PSM-0038 — an
    island of supply metal — still decides nothing. PSM-0039 — an instance
    terminal no conductor reaches — now does, because it is a consumer and not
    an imperfection; see test_psm_unreached_terminal_decides.py."""
    c = analysis_coverage(CONNECTIVITY, ["VPWR", "VGND"])
    assert len(c["connectivity"]) == 2, "both lines are still REPORTED"
    assert c["analysis_failed"] == []
    shape_only = "\n".join(l for l in CONNECTIVITY.splitlines()
                           if "PSM-0039" not in l)
    c2 = analysis_coverage(shape_only, ["VPWR", "VGND"])
    assert c2["unconnected_instances"] == []
    assert ir_verdict(1.0, 180000.0, c2["analysis_failed"],
                      c2["unconnected_instances"]) == "PASS"


def test_a_net_the_tool_names_but_the_run_did_not_list_is_still_a_failure():
    """The run's net list can be wrong; the tool's line cannot be about a net
    that does not exist."""
    c = analysis_coverage(TOOL_FAILED, ["VPWR", "VGND"])
    assert "VPROG" in c["analysis_failed"]


def test_an_empty_log_fails_nothing_and_analyses_nothing():
    c = analysis_coverage("", ["VPWR"])
    assert c["analysis_failed"] == [] and c["analysed"] == ["VPWR"]
