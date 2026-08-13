"""Step 1's gate must measure all three deliverables it claims. 63x9 d4.

`test_d4_gate_measures_what_it_claims[step1]` was the only d4 failure on main
and the last red node in that dimension:

    step 1 / d4 criteria_match: 2 of 3 declared required_outputs ENTRIES are
    read by no clause of this step's gate. The gate checks
    ['phase2/stage1/rtl/*.sv', 'phase2/stage1/rtl/*.v']; the step claims to
    deliver [...rtl..., 'reports/phase1/extraction_coverage_report.md',
    'reports/phase1/extraction_coverage_report.json'].

d4 states it "does not choose which side is wrong". The CORPUS chooses: d3
derives its manifest from the PUBLISHED runs, and removing the two entries from
the declaration made d3 report `required_outputs drifted from the measured
manifest: -[...extraction_coverage_report...]`. Published runs produced those
files attributed to this step, so the claim is right and the gate was the side
not measuring it. (Both declaration-side repairs were measured and both made the
matrix WORSE: moving the entries to D1 gave 21 failed, deleting them 20, against
a 19 baseline at the time.)

WHY THE SHAPE, NOT JUST THE PATHS
=================================
`any_of: true` is a MODIFIER on a files_exist block, not a nested gate list
(`flow_compliance_check.py:7538`, `:7596`). Appending the two reports to step 1's
existing any-of list would have made the gate pass when ANY ONE of four files
exists — a WEAKER gate wearing the shape of a fix, and exactly the "make it green
by asserting less" move. Nested `all_of` sub-gates keep the RTL pair any-of (one
entry, two accepted spellings) while requiring both reports, which
`required_outputs` declares as separate entries and the checker treats as ALL-of
across entries.

These tests exist because d4 alone cannot tell those two shapes apart: it asks
whether the declared paths are READ, and both spellings read them. Only
evaluating the gate distinguishes stronger from weaker, so that is what is
asserted here.
"""
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN = Path(__file__).resolve().parent.parent.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PLUGIN / "programs"))
import flow_compliance_check as F  # noqa: E402

RTL_SV = "phase2/stage1/rtl/top.sv"
RTL_V = "phase2/stage1/rtl/top.v"
REP_MD = "reports/phase1/extraction_coverage_report.md"
REP_JS = "reports/phase1/extraction_coverage_report.json"


def _step1_gate():
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    found = []

    def walk(n):
        if isinstance(n, dict):
            if str(n.get("id")) == "1" and "name" in n:
                found.append(n)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(doc)
    assert found, "step 1 not found in the flow"
    return found[0]["gate"]


def _project(tmp_path, *rels):
    for rel in rels:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n")
    return tmp_path


def _passes(tmp_path, *rels):
    ok, _reasons = F._evaluate_gate(_project(tmp_path, *rels), _step1_gate())
    return ok


# ---------------------------------------------------------------------------
# the property: every claimed deliverable is required
# ---------------------------------------------------------------------------
def test_all_three_deliverables_present_passes(tmp_path):
    assert _passes(tmp_path, RTL_SV, REP_MD, REP_JS)


def test_rtl_without_the_reports_FAILS(tmp_path):
    """THE POINT. Before this change the gate passed here, so a run that never
    produced the extraction-coverage report was certified by a step that
    declares it as a deliverable."""
    assert not _passes(tmp_path, RTL_SV), (
        "the gate passed with both declared reports absent — it is still not "
        "measuring what the step claims")


@pytest.mark.parametrize("missing,present", [
    (REP_JS, (RTL_SV, REP_MD)),
    (REP_MD, (RTL_SV, REP_JS)),
])
def test_either_report_missing_alone_FAILS(tmp_path, missing, present):
    """ALL-of across entries: one report is not an alternative spelling of the
    other. A gate that accepted either would be any-of in disguise."""
    assert not _passes(tmp_path, *present), f"passed without {missing}"


def test_reports_without_rtl_FAILS(tmp_path):
    assert not _passes(tmp_path, REP_MD, REP_JS)


# ---------------------------------------------------------------------------
# the anti-weakening arm: the RTL pair must STAY any-of
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rtl", [RTL_SV, RTL_V])
def test_either_rtl_spelling_alone_still_passes(tmp_path, rtl):
    """`*.sv OR *.v` is ONE declared entry with two accepted spellings. If this
    reddens, the repair turned a legitimate any-of into an all-of and every
    SystemVerilog-only or Verilog-only run now fails a gate it used to pass."""
    assert _passes(tmp_path, rtl, REP_MD, REP_JS), (
        f"a run delivering only {rtl} was refused; the RTL entry's any-of was "
        f"lost in the reshape")


def test_the_gate_is_not_one_flat_any_of_list():
    """Structural guard against the weaker spelling of this same fix. A single
    `files_exist` list carrying all four paths under `any_of: true` satisfies d4
    — the paths are read — while passing on ANY ONE of them."""
    gate = _step1_gate()
    if "files_exist" in gate and gate.get("any_of"):
        files = gate["files_exist"]
        assert not any("extraction_coverage_report" in str(f) for f in files), (
            "the reports were folded into the top-level any_of block, so the "
            "gate now passes when any single one of four files exists — "
            "weaker than before the repair")


def test_the_claim_the_gate_answers_is_still_declared():
    """The gate clause is only a repair while the declaration it answers
    exists. If the required_outputs entries are removed later, these clauses
    become unexplained constraints rather than a measured claim."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    found = []

    def walk(n):
        if isinstance(n, dict):
            if str(n.get("id")) == "1" and "name" in n:
                found.append(n)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(doc)
    outs = [str(o) for o in (found[0].get("required_outputs") or [])]
    assert any("extraction_coverage_report.md" in o for o in outs), outs
    assert any("extraction_coverage_report.json" in o for o in outs), outs
