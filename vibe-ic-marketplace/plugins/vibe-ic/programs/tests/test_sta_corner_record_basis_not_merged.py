#!/usr/bin/env python3
"""A per-corner record must not merge datapoints across the PnR boundary.

`sta_corner_record_completeness_check` keyed its records on (axis, corner) and
merged every datapoint for that key with `min()`. A PRE-PnR estimate and a
post-route SPEF measurement of the SAME corner are two measurements of two
different things, so the merge reported the pre-layout number as the corner's
SIGN-OFF slack — wrong by as much as the resizer is effective.

Measured on a two-report fixture: a corner whose post-route setup slack is
-0.50 ns was reported as -50.00 ns, a 100x error, on a row that cited BOTH
reports as its source.

The rules here are the contract, and the reverse cases are the load-bearing
half: a project with only pre-layout evidence must be COMPLETELY unaffected.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / "sta_corner_record_completeness_check.py"
STA = "phase3/stage3/sta/"

# A post-route multi-corner OCV report. The flow's emitter stamps no
# STA_BASIS on this one; its sections carry the SPEF in the header.
OCV_VIOLATES = (
    "=== SETUP corner: process=SS liberty=/pdk/lib/slow.lib, SPEF=top.spef ===\n"
    "worst slack max -0.50\n"
    "tns max -1.00\n"
)
OCV_MEETS = (
    "=== SETUP corner: process=SS liberty=/pdk/lib/slow.lib, SPEF=top.spef ===\n"
    "worst slack max 1.75\n"
    "tns max 0.00\n"
)
# A pre-layout sweep report. This one DISCLOSES ITS OWN BASIS, and that
# self-disclosure is the only thing the fix keys on.
PRELAYOUT_VIOLATES = (
    "Startpoint: ff1\n"
    "          -50.00   slack (VIOLATED)\n"
    "tns max -9000.00\n"
    "wns max -50.00\n"
    "STA_BASIS: PRE_LAYOUT_ESTIMATE\n"
    "STA_BASIS_NOTE: PRE-PnR netlist, NO parasitics. NOT post-route sign-off.\n"
)
PRELAYOUT_MEETS = (
    PRELAYOUT_VIOLATES.replace("-50.00", "5.00").replace("-9000.00", "0.00")
)


def _run(tmp_path, files):
    proj = tmp_path / "project"
    proj.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    out = proj / "out.json"
    res = _pr.run([sys.executable, str(PROG), ".", "--json", str(out)],
                         cwd=str(proj), capture_output=True, text=True)
    rows = {}
    if out.exists():
        for c in json.loads(out.read_text()).get("corners", []):
            rows[f"{c['axis']}:{c['corner']}"] = c
    return res.returncode, rows


def test_signoff_supersedes_prelayout_for_the_same_corner(tmp_path):
    """FORWARD: the sign-off datapoint is the one the corner row reports."""
    rc, rows = _run(tmp_path, {STA + "sta_mcorner_ocv.rpt": OCV_VIOLATES,
                               STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    ss = rows["process:SS"]
    assert ss["setup_wns_ns"] == -0.50, (
        "the corner's sign-off setup slack must come from the post-route "
        f"report, not the pre-layout estimate; got {ss['setup_wns_ns']}")
    # Still a violation: correcting the number must not clear the finding.
    assert rc == 1


def test_superseded_prelayout_value_is_disclosed_not_discarded(tmp_path):
    """The pre-layout estimate stays ON the row. A silent correction is a
    different defect from the one being fixed."""
    _, rows = _run(tmp_path, {STA + "sta_mcorner_ocv.rpt": OCV_VIOLATES,
                              STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    ss = rows["process:SS"]
    assert ss["basis_used"]["setup_wns_ns"] == "SIGNOFF"
    assert ss["pre_layout_superseded_ns"]["setup_wns_ns"] == -50.00


def test_prelayout_ONLY_project_is_unchanged(tmp_path):
    """REVERSE — the load-bearing case, and it asserts BEHAVIOUR ONLY.

    With no sign-off datapoint available the pre-layout number is still the
    record and still violates. This test must pass against the PRE-FIX file
    too: that is what makes it a control rather than a restatement of the fix.
    """
    rc, rows = _run(tmp_path, {STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    assert rows["process:SS"]["setup_wns_ns"] == -50.00
    assert rc == 1


def test_prelayout_only_row_is_labelled_prelayout(tmp_path):
    """The disclosure half of the case above, kept SEPARATE so the control
    above stays a pure behaviour assertion."""
    _, rows = _run(tmp_path, {STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    assert rows["process:SS"]["basis_used"]["setup_wns_ns"] == "PRE_LAYOUT"


def test_prelayout_only_and_meeting_is_unchanged(tmp_path):
    """REVERSE — the fix must not invent a violation either."""
    _, rows = _run(tmp_path, {STA + "per_corner/sta_SS.rpt": PRELAYOUT_MEETS})
    assert rows["process:SS"]["setup_wns_ns"] == 5.00


def test_signoff_only_project_is_unchanged(tmp_path):
    """REVERSE — an unstamped/post-route report keeps exactly its old standing."""
    rc, rows = _run(tmp_path, {STA + "sta_mcorner_ocv.rpt": OCV_VIOLATES})
    assert rows["process:SS"]["setup_wns_ns"] == -0.50
    assert rc == 1


def test_a_violating_signoff_corner_is_never_cleared_by_the_fix(tmp_path):
    """REVERSE — the anti-greening case. When BOTH bases violate, the corner
    stays violated. Tightening a filter until the count reaches zero is how a
    real defect gets swallowed; this is the test that would catch it."""
    rc, rows = _run(tmp_path, {STA + "sta_mcorner_ocv.rpt": OCV_VIOLATES,
                               STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    assert rows["process:SS"]["setup_wns_ns"] < 0
    assert rc == 1


def test_setup_and_hold_of_different_bases_are_labelled(tmp_path):
    """A row fed a pre-layout SETUP and a post-route HOLD must say so. Before
    the fix nothing on the row recorded that its two numbers came from
    opposite sides of place-and-route."""
    ocv_hold = ("=== HOLD corner: process=SS liberty=/pdk/lib/fast.lib, "
                "SPEF=top.spef ===\nworst slack min 0.20\ntns max 0.00\n")
    _, rows = _run(tmp_path, {STA + "sta_mcorner_ocv.rpt": ocv_hold,
                              STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    basis = rows["process:SS"]["basis_used"]
    assert basis["setup_wns_ns"] == "PRE_LAYOUT"
    assert basis["hold_wns_ns"] == "SIGNOFF"


def test_mixed_basis_row_keeps_both_numbers(tmp_path):
    """REVERSE, behaviour-only companion to the test above: labelling the row
    must not change either number it already carried."""
    ocv_hold = ("=== HOLD corner: process=SS liberty=/pdk/lib/fast.lib, "
                "SPEF=top.spef ===\nworst slack min 0.20\ntns max 0.00\n")
    _, rows = _run(tmp_path, {STA + "sta_mcorner_ocv.rpt": ocv_hold,
                              STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    ss = rows["process:SS"]
    assert ss["setup_wns_ns"] == -50.00   # no sign-off SETUP exists -> unchanged
    assert ss["hold_wns_ns"] == 0.20
