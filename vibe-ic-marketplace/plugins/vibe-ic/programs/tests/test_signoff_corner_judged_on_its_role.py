#!/usr/bin/env python3
"""A sign-off corner must be judged on the check its declared ROLE covers.

`sta_corner_record_completeness_check` R3 decided every sign-off corner with
`min(setup_wns, hold_wns)` over whatever fields the row carried, without
reading `basis_used` -- the field `_resolve` already fills in to record which
side of place-and-route each number came from.

A sign-off corner is declared for ONE check type: setup at the slow corner,
hold at the fast one. The post-route report therefore publishes that corner's
role field and no other, and `_resolve` back-fills the unpublished field from
the PRE_LAYOUT pool so the evidence table stays complete. R3 then judged the
back-filled ESTIMATE as if it were sign-off evidence. R1 already states this
for the nominal corner ("Demanding hold from it would be a FABRICATED
violation"); R3 did not state it for the roled corners.

MEASURED (sha256 x sky130A, 2026-08-10): corner FF, declared role HOLD, failed
R3 on `setup -14.030 ns` read from a report stamping itself
`STA_BASIS: PRE_LAYOUT_ESTIMATE`, while the same run's post-route report read
HOLD@FF +0.260 MET and SETUP@SS +1.810 MET.

The REVERSE cases are the load-bearing half. A field is excluded only when
BOTH its basis is PRE_LAYOUT and the corner's role does not cover it, so:
  * a real post-route violation of an off-role field still fails (basis guard);
  * a violation of the corner's OWN role still fails (role guard);
  * a pre-layout-ONLY project keeps exactly its old verdict.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "sta_corner_record_completeness_check.py"
STA = "phase3/stage3/sta/"

#: Post-route report that declares FF as the HOLD corner and publishes a hold
#: number for it -- and, being the hold corner, no setup number.
OCV_HOLD_AT_FF_MEETS = (
    "=== HOLD corner: process=FF liberty=/pdk/lib/fast.lib, SPEF=top.spef ===\n"
    "worst slack min 0.26\n"
    "tns max 0.00\n"
)
OCV_HOLD_AT_FF_VIOLATES = OCV_HOLD_AT_FF_MEETS.replace(
    "worst slack min 0.26", "worst slack min -0.26")

#: The pre-PnR sweep of the SAME corner. It DISCLOSES ITS OWN BASIS, and that
#: self-disclosure is the only thing this rule keys on.
PRELAYOUT_FF_SETUP_VIOLATES = (
    "Startpoint: ff1\n"
    "          -14.030   slack (VIOLATED)\n"
    "tns max 0.00\n"
    "wns max -14.030\n"
    "STA_BASIS: PRE_LAYOUT_ESTIMATE\n"
    "STA_BASIS_NOTE: PRE-PnR netlist, NO parasitics. NOT post-route sign-off.\n"
)
#: Byte-for-byte the same numbers, published on the post-route side.
POSTROUTE_FF_SETUP_VIOLATES = PRELAYOUT_FF_SETUP_VIOLATES.replace(
    "PRE_LAYOUT_ESTIMATE", "POST_ROUTE_SPEF")

#: A SETUP-role corner whose only evidence is pre-layout and which violates.
OCV_SETUP_AT_SS_MEETS = (
    "=== SETUP corner: process=SS liberty=/pdk/lib/slow.lib, SPEF=top.spef ===\n"
    "worst slack max 1.81\n"
    "tns max 0.00\n"
)
PRELAYOUT_SS_SETUP_VIOLATES = PRELAYOUT_FF_SETUP_VIOLATES.replace(
    "-14.030", "-93.550")


#: The stance file is what DECLARES which corner serves which role. Without a
#: declaration there are no roles, no `signoff` role_class and no R3 at all, so
#: every fixture here ships one -- the roles are the whole subject.
def _stance(setup_corner="SS", hold_corner="FF"):
    libs = {"SS": "/pdk/lib/slow.lib", "FF": "/pdk/lib/fast.lib"}
    corners = sorted({setup_corner, hold_corner})
    return json.dumps({
        "signoff_dimension": "multi_corner_ocv_process",
        "setup_process_corner": setup_corner,
        "hold_process_corner": hold_corner,
        "multi_process_corner": len(corners) > 1,
        "report": STA + "sta_mcorner_ocv.rpt",
        "corner_library_resolution": {
            "axis": "process",
            "liberty_by_corner": {c: libs[c] for c in corners},
            "distinct_library_count": len(corners),
            "reported_corner_count": len(corners),
            "collapsed": False,
            "unresolved_corners": [],
        },
    })


def _run(tmp_path, files, stance=None):
    proj = tmp_path / "project"
    proj.mkdir(parents=True, exist_ok=True)
    files = dict(files)
    files.setdefault("reports/phase3/mcorner_ocv_stance.json",
                     stance if stance is not None else _stance())
    for rel, body in files.items():
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    out = proj / "out.json"
    res = subprocess.run([sys.executable, str(PROG), ".", "--json", str(out)],
                         cwd=str(proj), capture_output=True, text=True, timeout=60)
    doc = json.loads(out.read_text()) if out.exists() else {}
    rows = {f"{c['axis']}:{c['corner']}": c for c in doc.get("corners", [])}
    return res.returncode, rows, doc


# ── FORWARD ─────────────────────────────────────────────────────────────────

def test_hold_corner_is_not_violated_by_a_prelayout_setup_estimate(tmp_path):
    """The defect, in its minimal shape."""
    _, rows, doc = _run(tmp_path, {
        STA + "sta_mcorner_ocv.rpt": OCV_HOLD_AT_FF_MEETS,
        STA + "per_corner/sta_FF.rpt": PRELAYOUT_FF_SETUP_VIOLATES})
    ff = rows["process:FF"]
    assert ff["roles"] == ["hold"], ff["roles"]
    assert ff["basis_used"]["setup_wns_ns"] == "PRE_LAYOUT"
    assert "R3_SIGNOFF_CORNER_VIOLATION" not in doc["rules_violated"], (
        "a hold corner must not be failed on a setup number its own producing "
        f"report calls PRE_LAYOUT_ESTIMATE; reasons={doc['reasons']}")


def test_the_excluded_number_is_disclosed_by_name_and_basis(tmp_path):
    """Excluded, never dropped: the estimate still reaches the operator, with
    the basis that disqualified it stated in the same sentence."""
    _, _rows, doc = _run(tmp_path, {
        STA + "sta_mcorner_ocv.rpt": OCV_HOLD_AT_FF_MEETS,
        STA + "per_corner/sta_FF.rpt": PRELAYOUT_FF_SETUP_VIOLATES})
    disclosed = [r for r in doc["reasons"]
                 if "PRE_LAYOUT" in r and "-14.030" in r and "role hold" in r]
    assert disclosed, doc["reasons"]


def test_the_disclosure_is_not_a_rule(tmp_path):
    """It is evidence about the RECORD, not a violation of the DESIGN, so it
    must not enter `rules_violated` and must not decide the verdict."""
    _, _rows, doc = _run(tmp_path, {
        STA + "sta_mcorner_ocv.rpt": OCV_HOLD_AT_FF_MEETS,
        STA + "per_corner/sta_FF.rpt": PRELAYOUT_FF_SETUP_VIOLATES})
    assert not any(r.startswith("R3") for r in doc["rules_violated"]), \
        doc["rules_violated"]


# ── REVERSE: the basis guard ────────────────────────────────────────────────

def test_the_same_number_on_a_postroute_basis_still_fails(tmp_path):
    """THE anti-greening case. The exclusion keys on BASIS, not on role, so a
    genuine post-route setup violation at the hold corner is still judged. If
    this ever passes, the rule has been narrowed into uselessness."""
    rc, _rows, doc = _run(tmp_path, {
        STA + "sta_mcorner_ocv.rpt": OCV_HOLD_AT_FF_MEETS,
        STA + "per_corner/sta_FF.rpt": POSTROUTE_FF_SETUP_VIOLATES})
    assert "R3_SIGNOFF_CORNER_VIOLATION" in doc["rules_violated"], doc["reasons"]
    assert rc == 1


# ── REVERSE: the role guard ────────────────────────────────────────────────

def test_a_hold_corner_violating_its_OWN_role_still_fails(tmp_path):
    rc, _rows, doc = _run(tmp_path, {
        STA + "sta_mcorner_ocv.rpt": OCV_HOLD_AT_FF_VIOLATES,
        STA + "per_corner/sta_FF.rpt": PRELAYOUT_FF_SETUP_VIOLATES})
    assert "R3_SIGNOFF_CORNER_VIOLATION" in doc["rules_violated"], doc["reasons"]
    assert rc == 1


def test_the_violation_text_names_only_what_it_decided_on(tmp_path):
    """The violation sentence must not quote the excluded estimate as if the
    rule had used it -- that would re-introduce the same false claim inside
    the finding that replaced it."""
    _, _rows, doc = _run(tmp_path, {
        STA + "sta_mcorner_ocv.rpt": OCV_HOLD_AT_FF_VIOLATES,
        STA + "per_corner/sta_FF.rpt": PRELAYOUT_FF_SETUP_VIOLATES})
    violated = [r for r in doc["reasons"] if "is VIOLATED" in r]
    assert violated, doc["reasons"]
    assert "hold -0.260 ns" in violated[0], violated[0]
    assert "-14.030" not in violated[0], violated[0]


# ── REVERSE: a pre-layout-only project keeps its old verdict ───────────────

def test_prelayout_only_setup_corner_still_fails(tmp_path):
    """`_resolve` promises a pre-layout-only project "keeps exactly today's
    numbers and today's verdict". Its role-COVERED field is pre-layout too,
    and is still judged. This test must pass against the PRE-FIX file as well:
    that is what makes it a control rather than a restatement of the fix."""
    rc, rows, doc = _run(tmp_path, {
        STA + "per_corner/sta_SS.rpt": PRELAYOUT_SS_SETUP_VIOLATES},
        stance=_stance(setup_corner="SS", hold_corner="SS"))
    assert rows["process:SS"]["basis_used"]["setup_wns_ns"] == "PRE_LAYOUT"
    assert rows["process:SS"]["setup_wns_ns"] == -93.550
    assert "R3_SIGNOFF_CORNER_VIOLATION" in doc["rules_violated"], doc["reasons"]
    assert rc == 1


def test_a_corner_declared_for_BOTH_roles_keeps_both_fields(tmp_path):
    """Narrowing uses a fact the record STATES. A corner declared for setup
    AND hold covers both fields, so neither is ever excluded."""
    both = (OCV_SETUP_AT_SS_MEETS.replace("process=SS", "process=FF")
            + OCV_HOLD_AT_FF_MEETS)
    _, rows, doc = _run(tmp_path, {
        STA + "sta_mcorner_ocv.rpt": both,
        STA + "per_corner/sta_FF.rpt": PRELAYOUT_FF_SETUP_VIOLATES},
        stance=_stance(setup_corner="FF", hold_corner="FF"))
    ff = rows["process:FF"]
    assert sorted(ff["roles"]) == ["hold", "setup"], ff["roles"]
    # setup is now role-covered, so the sign-off +1.81 supersedes and the
    # corner meets; nothing was excluded on role grounds.
    assert ff["setup_wns_ns"] == 1.81
    assert "R3_SIGNOFF_CORNER_VIOLATION" not in doc["rules_violated"], doc["reasons"]
