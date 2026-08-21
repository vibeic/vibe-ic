#!/usr/bin/env python3
"""The producer for the physical / reliability / equivalence feasibility axes.

Positive, NEGATIVE and VACUOUS for every axis. Weighted towards the negatives on
purpose: this program's failure mode is not "it computes the wrong number", it
is "it writes a zero for something nobody measured", and a suite of only
positive fixtures is a gate that is always green.

The DRC tests are driven by the SHIPPED fixture tree
(`fixtures/ppa/drc/zero_three_ways/`) rather than by numbers written here, so
that the discriminator this program implements is demonstrably the one the
fixture states and not an eleventh near-miss of it.
"""
import json
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import metrics as M      # noqa: E402
from _ppa import signoff as S      # noqa: E402

CLI = _PROGRAMS / "ppa_signoff_records.py"
ZERO_THREE_WAYS = _PROGRAMS / "tests" / "fixtures" / "ppa" / "drc" / "zero_three_ways"


# --------------------------------------------------------------------------
# a run tree
# --------------------------------------------------------------------------
def _write(root: pathlib.Path, rel: str, doc) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2) + "\n")


def clean_run(tmp_path, **overrides):
    """A run whose every sign-off artefact says the design closed."""
    root = tmp_path / "run"
    docs = {
        S.DRC_SIGNOFF_REL: {"summary": {"categories_found": ["a", "b", "c"],
                                        "real_violation_total": 0}},
        S.DRC_VACUITY_REL: {"summary": {"per_file": [
            {"file": "x.gds", "layout_measures": [{"shapes": 41231}]}]}},
        S.LVS_REL: {"status": "PASS", "result": "PASS", "top_cell": "core",
                    "finding": "LVS_MATCH"},
        S.ANTENNA_REL: {"tool": "openroad", "mode": "antenna_check",
                        "net_violations": 0, "pin_violations": 0,
                        "clean": True, "verdict": "PASS"},
        S.IR_REL: {"worst_ir_uv": 432.0, "supply_voltage_v": 1.8,
                   "supply_measured": True, "worst_ir_pct_vdd": 0.024,
                   "budget_pct_vdd": 10.0, "budget_basis": "declared"},
        S.EM_REL: {"segments_analysed": 2431,
                   "max_segment_current_A": 0.0001951, "verdict": "MEASURED"},
        S.EM_SCREEN_RELS[0]: {"verdict": "PASS", "margin": 0.1,
                              "summary": {"segments_total": 2431,
                                          "segments_screened": 2431,
                                          "segments_unscreened": 0,
                                          "worst_utilization": 0.0031}},
        S.LEC_REL: {"verdict": "PASS", "equivalent": True,
                    "gate": "core_pnr.v (post_route)", "golden": "rtl"},
    }
    docs.update(overrides)
    for rel, doc in docs.items():
        if doc is not None:
            _write(root, rel, doc)
    return root


def by_metric(records, name):
    return [r for r in records if r["metric"] == name]


def one(records, name):
    hits = by_metric(records, name)
    assert len(hits) == 1, f"{name}: expected 1 record, got {len(hits)}"
    return hits[0]


# --------------------------------------------------------------------------
# POSITIVE
# --------------------------------------------------------------------------
def test_a_closed_run_produces_a_measured_record_on_every_axis(tmp_path):
    """The defect this program exists for: the run measured all of it and the
    gate could read none of it."""
    recs = S.bundle(clean_run(tmp_path))["records"]
    for name, want in (("physical.drc.violations", 0),
                       ("physical.lvs.verdict", "MATCH"),
                       ("physical.antenna.violations", 0),
                       ("power.ir.violations", 0),
                       ("reliability.em.violations", 0),
                       ("equivalence.verdict", "PROVEN")):
        r = one(recs, name)
        assert r["status"] == S.MEASURED, (name, r.get("reason"))
        assert r["value"] == want, name


def test_every_record_is_a_valid_canonical_metric_record(tmp_path):
    """A record the canonical index refuses is a record the gate cannot read,
    which is the whole failure this program is fixing one layer up."""
    for rec in S.bundle(clean_run(tmp_path))["records"]:
        assert M.validate(rec) == [], (rec["metric"], M.validate(rec))


def test_every_record_carries_real_provenance(tmp_path):
    """`_ppa/feasibility._record_defect` refuses a MEASURED record with no path
    or no well-formed digest. A producer that cannot satisfy that is a producer
    whose output the gate silently drops."""
    for rec in S.bundle(clean_run(tmp_path))["records"]:
        if rec["status"] != S.MEASURED:
            continue
        src = rec["source"]
        assert src["path"].strip()
        assert src["sha256"].startswith("sha256:") and len(src["sha256"]) == 71
        assert src["sha256"] != S.ABSENT_DIGEST
        assert src["parser"] == S.PARSER and src["parser_sha256"]


def test_a_measurement_is_emitted_ONCE_and_not_once_per_corner(tmp_path):
    """Corner-independent facts get ONE record.

    The reference bridge this program replaces emitted each physical fact once
    per required timing view, all carrying one source hash, purely because
    `required_views` was global. That is N records claiming to be the same fact
    in an index whose job is to notice exactly that. Per-axis required views
    removed the need; this test is what stops it coming back."""
    recs = S.bundle(clean_run(tmp_path))["records"]
    assert len(recs) == len(S.SOURCES)
    for src in S.SOURCES:
        assert len(by_metric(recs, src.metric)) == 1, src.metric


def test_the_stage_is_stated_with_the_basis_it_rests_on(tmp_path):
    """`scope.stage` is required and no artefact states one. It is declared per
    source WITH the reason, so a reader can check the claim instead of
    discovering later that it was a guess."""
    for rec in S.bundle(clean_run(tmp_path))["records"]:
        assert rec["scope"]["stage"]
        assert len(rec["provenance"]["stage_basis"]) > 20


def test_no_scope_field_is_ever_null_or_empty(tmp_path):
    """Two records with an unknown corner would otherwise compare as the SAME
    corner. `_ppa/metrics` calls that a sentinel and refuses it."""
    for rec in S.bundle(clean_run(tmp_path))["records"]:
        for k, v in rec["scope"].items():
            assert v is not None and v != "", (rec["metric"], k)


# --------------------------------------------------------------------------
# NEGATIVE -- DRC, driven by the shipped three-way fixture
# --------------------------------------------------------------------------
def _fixture_cases():
    doc = json.loads((ZERO_THREE_WAYS / "expected.json").read_text())
    return {c["dir"]: c for c in doc["cases"]}


def _drc_run(tmp_path, case):
    """A run tree carrying the fixture case's own numbers and nothing else."""
    return clean_run(
        tmp_path,
        **{S.DRC_SIGNOFF_REL: {"summary": {
               "categories_found": ["r%d" % i
                                    for i in range(case["categories_in_report"])],
               "real_violation_total": case["items_in_report"]}},
           S.DRC_VACUITY_REL: {"summary": {"per_file": [
               {"file": "layout.gds", "layout_measures": [
                   {"shapes": case["shapes_in_layout"]}]}]}}})


@pytest.mark.parametrize("case_dir", ["ran_and_found_none",
                                      "ran_on_empty_layout",
                                      "deck_never_ran"])
def test_the_drc_discriminator_is_the_fixture_s_table(tmp_path, case_dir):
    """All three cases report ZERO violations. Exactly one is entitled to say
    the design is clean, and the other two are the easiest lie in the system."""
    case = _fixture_cases()[case_dir]
    rec = one(S.bundle(_drc_run(tmp_path, case))["records"],
              "physical.drc.violations")
    if case["expected_verdict"]["status"] == "PASS":
        assert rec["status"] == S.MEASURED
        assert rec["value"] == 0
    else:
        # rc=2 / UNDETERMINED in the fixture's verdict vocabulary is
        # NOT_MEASURED here: this program produces evidence, not verdicts, and
        # a record the gate cannot use is how it says "I could not check".
        assert rec["status"] == S.NOT_MEASURED, case_dir
        assert "value" not in rec
        assert case_dir in rec["reason"]


def test_two_byte_identical_reports_get_opposite_answers(tmp_path):
    """`ran_and_found_none/drc.xml` and `ran_on_empty_layout/drc.xml` are the
    same 702 bytes. If this program decided from the report alone it could not
    tell them apart, so this asserts it does not."""
    cases = _fixture_cases()
    a = (ZERO_THREE_WAYS / "ran_and_found_none" / "drc.xml").read_bytes()
    b = (ZERO_THREE_WAYS / "ran_on_empty_layout" / "drc.xml").read_bytes()
    assert a == b, "the fixture's premise no longer holds"
    ra = one(S.bundle(_drc_run(tmp_path / "a", cases["ran_and_found_none"]))
             ["records"], "physical.drc.violations")
    rb = one(S.bundle(_drc_run(tmp_path / "b", cases["ran_on_empty_layout"]))
             ["records"], "physical.drc.violations")
    assert ra["status"] == S.MEASURED and rb["status"] == S.NOT_MEASURED


def test_a_drc_report_with_no_vacuity_artefact_is_not_a_clean(tmp_path):
    """The shape count is not in the report and never can be. Without it there
    is no third fact and no earned clean."""
    run = clean_run(tmp_path, **{S.DRC_VACUITY_REL: None})
    rec = one(S.bundle(run)["records"], "physical.drc.violations")
    assert rec["status"] == S.NOT_MEASURED
    assert "could not be measured" in rec["reason"]


def test_a_real_drc_violation_count_is_reported_whatever_the_vacuity_says(tmp_path):
    """Items cannot be reported by a deck that never ran, so a measured count
    is a fact about the design and stands."""
    run = clean_run(tmp_path, **{
        S.DRC_SIGNOFF_REL: {"summary": {"categories_found": [],
                                        "real_violation_total": 17}},
        S.DRC_VACUITY_REL: None})
    rec = one(S.bundle(run)["records"], "physical.drc.violations")
    assert rec["status"] == S.MEASURED and rec["value"] == 17


# --------------------------------------------------------------------------
# NEGATIVE -- the other axes
# --------------------------------------------------------------------------
def test_an_antenna_check_over_an_unrouted_design_is_not_a_zero(tmp_path):
    run = clean_run(tmp_path, **{S.ANTENNA_REL: {
        "net_violations": 0, "pin_violations": 0, "routing_incomplete": True,
        "verdict": "PASS"}})
    rec = one(S.bundle(run)["records"], "physical.antenna.violations")
    assert rec["status"] == S.NOT_MEASURED
    assert "incompletely routed" in rec["reason"]


def test_null_antenna_counts_are_not_read_as_zero(tmp_path):
    """The runner writes null for both when it could not read the tool log."""
    run = clean_run(tmp_path, **{S.ANTENNA_REL: {
        "net_violations": None, "pin_violations": None, "verdict": "PASS"}})
    rec = one(S.bundle(run)["records"], "physical.antenna.violations")
    assert rec["status"] == S.NOT_MEASURED and "value" not in rec


def test_ir_with_no_declared_budget_supports_no_violation_count(tmp_path):
    """A default budget invented here would be a design-specific number in
    chip-agnostic source, and would turn every unmeasured supply into a pass."""
    run = clean_run(tmp_path, **{S.IR_REL: {
        "worst_ir_uv": 432.0, "supply_measured": True,
        "worst_ir_pct_vdd": 0.024, "budget_pct_vdd": None}})
    recs = S.bundle(run)["records"]
    assert one(recs, "power.ir.violations")["status"] == S.NOT_MEASURED
    # ...and the drop itself is STILL measured, for the contract-limit proof.
    drop = one(recs, "power.ir.worst_drop_v")
    assert drop["status"] == S.MEASURED and drop["value"] == pytest.approx(432e-6)


def test_an_ir_drop_over_its_budget_is_one_violation(tmp_path):
    run = clean_run(tmp_path, **{S.IR_REL: {
        "worst_ir_uv": 400000.0, "supply_measured": True,
        "worst_ir_pct_vdd": 22.2, "budget_pct_vdd": 10.0}})
    assert one(S.bundle(run)["records"], "power.ir.violations")["value"] == 1


def test_the_em_measurement_artefact_alone_supports_no_count(tmp_path):
    """`em.json` carries a segment count and a peak current and NO violation
    count and NO limit. 'The tool reported no violations' is not what it says,
    and a zero here is exactly the vacuous pass the fixture tree prevents."""
    run = clean_run(tmp_path, **{S.EM_SCREEN_RELS[0]: None})
    recs = S.bundle(run)["records"]
    v = one(recs, "reliability.em.violations")
    assert v["status"] == S.NOT_MEASURED and "value" not in v
    assert "NO violation count" in v["reason"]
    assert one(recs, "reliability.em.worst_ratio")["status"] == S.NOT_MEASURED


def test_a_skipped_density_screen_is_not_a_clean(tmp_path):
    """Report present, Jmax present, nothing mapped. SKIPPED is a
    could-not-judge and the screen is careful to say so; so is this."""
    run = clean_run(tmp_path, **{S.EM_SCREEN_RELS[0]: {
        "verdict": "SKIPPED", "summary": {"segments_screened": 0},
        "findings": [{"message": "none could be screened against the Jmax "
                                 "reference"}]}})
    rec = one(S.bundle(run)["records"], "reliability.em.violations")
    assert rec["status"] == S.NOT_MEASURED
    assert "SKIPPED" in rec["reason"] and "never a clean" in rec["reason"]


def test_em_offenders_are_reported_as_the_count(tmp_path):
    run = clean_run(tmp_path, **{S.EM_SCREEN_RELS[0]: {
        "verdict": "FAIL", "offender_count": 4,
        "summary": {"segments_screened": 2431, "worst_utilization": 1.7}}})
    recs = S.bundle(run)["records"]
    assert one(recs, "reliability.em.violations")["value"] == 4
    assert one(recs, "reliability.em.worst_ratio")["value"] == 1.7


def test_a_pre_layout_lec_proof_is_not_post_route_equivalence(tmp_path):
    """Measured on a real run: `reports/lec.json` proved RTL against a post-DFT
    SYNTHESIS netlist while the run's own post-layout LEC step failed. A PROVEN
    read off that file is a claim about a different netlist."""
    run = clean_run(tmp_path, **{S.LEC_REL: {
        "verdict": "PASS", "equivalent": True,
        "gate": "post_dft_netlist.v (synth)"}})
    rec = one(S.bundle(run)["records"], "equivalence.verdict")
    assert rec["status"] == S.NOT_MEASURED
    assert "names no post-layout netlist" in rec["reason"]
    assert "post_dft_netlist.v (synth)" in rec["reason"]


def test_a_failed_lec_is_a_measured_verdict_and_not_a_could_not_check(tmp_path):
    """Reporting a real failure as NOT_MEASURED hides a finding behind 'I could
    not look'."""
    run = clean_run(tmp_path, **{S.LEC_REL: {
        "verdict": "FAIL", "equivalent": False, "gate": "core_pnr.v"}})
    rec = one(S.bundle(run)["records"], "equivalence.verdict")
    assert rec["status"] == S.MEASURED and rec["value"] == "FAIL"


@pytest.mark.parametrize("status,expect", [("PASS", "MATCH"),
                                           ("FAIL", "FAIL"),
                                           ("INCOMPLETE", "INCOMPLETE"),
                                           ("WARN", "WARN")])
def test_the_lvs_verdict_is_reported_verbatim_and_never_as_a_count(
        tmp_path, status, expect):
    """INCOMPLETE and WARN are not failures and must not be mapped to one; they
    are verdicts the axis does not accept, which is a different fix."""
    run = clean_run(tmp_path, **{S.LVS_REL: {"status": status,
                                             "top_cell": "core"}})
    rec = one(S.bundle(run)["records"], "physical.lvs.verdict")
    assert rec["status"] == S.MEASURED
    assert rec["value"] == expect
    assert not isinstance(rec["value"], (int, float))
    assert rec["unit"] == M.VERDICT_UNIT
    assert rec["provenance"]["top_cell"] == "core"


# --------------------------------------------------------------------------
# VACUOUS
# --------------------------------------------------------------------------
def test_an_absent_artefact_is_a_row_and_not_an_omission(tmp_path):
    """§2: a report prints the literal NOT_MEASURED row; it does not omit it.
    An omitted row and a met row look the same to anything that scans a table
    for violations and finds none."""
    empty = tmp_path / "empty"
    empty.mkdir()
    doc = S.bundle(empty)
    assert doc["census"]["records"] == len(S.SOURCES)
    assert doc["census"]["measured"] == 0
    for rec in doc["records"]:
        assert rec["status"] == S.NOT_MEASURED
        assert "value" not in rec
        assert "not a zero" in rec["reason"]
        assert rec["source"]["sha256"] == S.ABSENT_DIGEST


def test_a_present_but_unparseable_artefact_is_a_different_reason(tmp_path):
    """"the file is not there" and "the file is there and is not JSON" are two
    different facts and one reason for both is how a producer stops being
    fixable."""
    run = clean_run(tmp_path)
    (run / S.ANTENNA_REL).write_text("<html>not json</html>\n")
    rec = one(S.bundle(run)["records"], "physical.antenna.violations")
    assert rec["status"] == S.NOT_MEASURED
    assert "is not a JSON object" in rec["reason"]
    assert rec["source"]["sha256"] != S.ABSENT_DIGEST


# --------------------------------------------------------------------------
# THE CLI -- rc 0 / 2 / 3, and never rc 1
# --------------------------------------------------------------------------
def _run(*args):
    return subprocess.run([sys.executable, str(CLI), *map(str, args)],
                          capture_output=True, text=True)


def test_cli_rc0_on_a_run_that_measured_something(tmp_path):
    p = _run(clean_run(tmp_path), "--json", tmp_path / "out.json")
    assert p.returncode == 0, p.stderr
    doc = json.loads((tmp_path / "out.json").read_text())
    assert doc["schema"] == S.SCHEMA_BUNDLE
    assert doc["census"]["measured"] >= 6


def test_cli_rc2_and_a_marker_when_it_read_nothing(tmp_path):
    """A producer that reports success when it read nothing is the vacuous pass
    this repository has shipped before."""
    empty = tmp_path / "empty"
    empty.mkdir()
    p = _run(empty, "--json", tmp_path / "out.json")
    assert p.returncode == 2
    assert "[CANNOT CHECK]" in p.stderr
    # ...and the artefact it wrote is honest too, not just the exit code.
    doc = json.loads((tmp_path / "out.json").read_text())
    assert doc["census"]["measured"] == 0
    assert len(doc["records"]) == len(S.SOURCES)


def test_cli_rc3_on_a_bad_invocation(tmp_path):
    """3 and not 2: a path that is not there is the caller's error, and a 2
    would be indistinguishable from 'I looked and could not tell'."""
    assert _run(tmp_path / "nope").returncode == 3
    assert _run().returncode == 3


def test_cli_never_returns_rc1(tmp_path):
    """rc=1 is a finding about silicon. This program reports what artefacts
    state; `ppa_feasibility_check.py` is the thing entitled to make a finding."""
    dirty = clean_run(tmp_path, **{
        S.DRC_SIGNOFF_REL: {"summary": {"categories_found": ["a"],
                                        "real_violation_total": 91}}})
    p = _run(dirty)
    assert p.returncode == 0
    assert "[REFUSE]" not in p.stdout + p.stderr


# --------------------------------------------------------------------------
# the whole point: the gate can now adjudicate a closed run
# --------------------------------------------------------------------------
def test_the_gate_reaches_a_verdict_it_could_not_reach_before(tmp_path):
    """The end-to-end defect, in one assertion.

    Six axes MEASURED, adjudicated against the views each axis is measured at.
    Before this producer the same run gave `FEAS_METRIC_ABSENT` on every one of
    them, so no candidate could ever be FEASIBLE and no head-to-head could ever
    satisfy its 'both arms feasible' condition."""
    from _ppa import feasibility as F
    recs = S.bundle(clean_run(tmp_path))["records"]
    policy = F.policy_from_document({
        "required_views_by_axis": {
            "drc": [{"stage": "signed_off_gds"}],
            "lvs": [{"stage": "post_route_extracted"}],
            "antenna": [{"stage": "post_route"}],
            "ir": [{"stage": "post_route"}],
            "em": [{"stage": "post_route"}],
            "equivalence": [{"stage": "post_route"}],
        }})
    result = F.promotion_verdict({"candidate_id": "c", "metrics": recs}, policy)
    got = {a.name: a.status for a in result.axes}
    for axis in ("drc", "lvs", "antenna", "ir", "em", "equivalence"):
        assert got[axis] == F.AXIS_SATISFIED, (axis, got[axis])
    # setup / hold / drv are the timing lane's and are still UNDETERMINED here,
    # honestly: this producer emits no timing record and says so.
    assert result.verdict == F.UNDETERMINED
    assert {a.name for a in result.axes if a.status == F.AXIS_UNDETERMINED} == {
        "setup", "hold", "drv"}
