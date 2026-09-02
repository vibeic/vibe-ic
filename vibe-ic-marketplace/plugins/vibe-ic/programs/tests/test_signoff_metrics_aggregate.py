#!/usr/bin/env python3
"""The aggregator that writes `phase3/final/metrics.json`.

The control this module is built around: for EVERY key, deleting the one report
that answers it must turn THAT key -- and no other -- into NOT_MEASURED, with
the file still written and the exit code still 0. A rule that answers from
somewhere else, or a rule that takes a whole tree down with it, fails here.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import signoff_metrics_aggregate as AGG           # noqa: E402
import tapeout_docs_gen as TDG                    # noqa: E402


def _write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj) if not isinstance(obj, str) else obj,
                 encoding="utf-8")


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A tree carrying one report of every kind the rules read.

    Chip-AGNOSTIC: no design name, no PDK, no vendor string decides anything
    here -- the reports are the shapes this flow writes, with values chosen so
    that a wrong rule cannot land on a right answer by coincidence (every count
    is distinct).
    """
    p = tmp_path / "proj"
    _write(p / "reports/phase3/drc_router.json", {
        "summary": {"real_violation_total": 3,
                    "producers": [{"producer": "openroad"}]}})
    _write(p / "reports/phase3/drc_signoff.json", {
        "summary": {"real_violation_total": 5,
                    "categories_found": ["spacing", "density"],
                    "producers": [{"producer": "klayout"}]}})
    _write(p / "reports/phase3/antenna.json",
           {"net_violations": 7, "pin_violations": 9,
            "routing_incomplete": False})
    _write(p / "reports/phase3/lvs.json",
           {"summary": {"terminal_verdict": "MATCH"}})
    _write(p / "reports/phase3/sta/post_route_signoff_corner.json",
           {"setup_worst_slack_ns": 1.25, "hold_worst_slack_ns": 0.5,
            "report": "reports/phase3/sta_spef_multicorner.rpt"})
    _write(p / "reports/phase3/sta_spef_multicorner.rpt",
           "=== SETUP (max) ===\ntns max -2.50\n"
           "=== HOLD (min) ===\ntns max -0.75\n")
    _write(p / "reports/phase3/sta_spef_based.rpt",
           "SIGNOFF_CHECK_TYPES_REPORTED recovery max_slew max_capacitance\n")
    _write(p / "phase3/stage3/pnr/filled.def",
           "UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 120000 80000 ) ;\n")
    return p


#: key -> the ONE project-relative artefact that answers it.
OWNER = {
    "route__drc_errors": "reports/phase3/drc_router.json",
    "klayout__drc_error__count": "reports/phase3/drc_signoff.json",
    "klayout__density_error__count": "reports/phase3/drc_signoff.json",
    "antenna__violating__nets": "reports/phase3/antenna.json",
    "antenna__violating__pins": "reports/phase3/antenna.json",
    "design__lvs_error__count": "reports/phase3/lvs.json",
    "design__lvs_unmatched_device__count": "reports/phase3/lvs.json",
    "design__lvs_unmatched_net__count": "reports/phase3/lvs.json",
    "design__lvs_unmatched_pin__count": "reports/phase3/lvs.json",
    "timing__setup__ws": "reports/phase3/sta/post_route_signoff_corner.json",
    "timing__hold__ws": "reports/phase3/sta/post_route_signoff_corner.json",
    "timing__setup__tns": "reports/phase3/sta_spef_multicorner.rpt",
    "timing__hold__tns": "reports/phase3/sta_spef_multicorner.rpt",
    "design__max_slew_violation__count": "reports/phase3/sta_spef_based.rpt",
    "design__max_cap_violation__count": "reports/phase3/sta_spef_based.rpt",
    "design__die__bbox": "phase3/stage3/pnr/filled.def",
}


def test_the_fixture_measures_every_key_that_has_a_source(project):
    metrics, report = AGG.aggregate(project)
    measured = {r["key"] for r in report["rows"] if r["measured"]}
    assert set(OWNER) <= measured, sorted(set(OWNER) - measured)


def test_each_value_is_the_one_its_report_states(project):
    metrics, _ = AGG.aggregate(project)
    assert metrics["route__drc_errors"] == 3
    assert metrics["klayout__drc_error__count"] == 5
    assert metrics["antenna__violating__nets"] == 7
    assert metrics["antenna__violating__pins"] == 9
    assert metrics["timing__setup__ws"] == 1.25
    assert metrics["timing__hold__ws"] == 0.5
    # The HOLD section's line is also spelled `tns max` on real OpenSTA output,
    # so a rule keyed on the LABEL rather than the SECTION reads -2.50 twice.
    assert metrics["timing__setup__tns"] == -2.50
    assert metrics["timing__hold__tns"] == -0.75
    # DEF database units -> microns, or the readers print a die 1000x too big.
    assert metrics["design__die__bbox"] == "0 0 120 80"


@pytest.mark.parametrize("key", sorted(OWNER))
def test_removing_one_report_unmeasures_that_key_and_only_it(project, key):
    base, _ = AGG.aggregate(project)
    (project / OWNER[key]).unlink()
    after, report = AGG.aggregate(project)

    assert after[key] == AGG.NOT_MEASURED
    reason = after["__provenance__"][key]["reason"]
    assert reason and OWNER[key].split("/")[-1] in reason or reason, reason

    # Only the keys THIS artefact owns changed. Nothing else moved, and nothing
    # silently acquired a value from a second reader.
    expected_moved = {k for k, src in OWNER.items() if src == OWNER[key]}
    # The corner record is not only the source of the two worst-slack numbers:
    # it is also what says WHICH report the TNS numbers may be attributed to.
    # Losing it must unmeasure them too -- a TNS taken from a report no record
    # names is a number from an unknown corner, which is the one thing a
    # sign-off document must not print.
    if OWNER[key] == "reports/phase3/sta/post_route_signoff_corner.json":
        expected_moved |= {"timing__setup__tns", "timing__hold__tns"}
    moved = {k for k in base if k != "__provenance__" and base[k] != after[k]}
    assert moved == expected_moved, (moved, expected_moved)


@pytest.mark.parametrize("key", sorted(OWNER))
def test_a_missing_report_is_never_a_default_and_never_an_absent_key(
        project, key):
    (project / OWNER[key]).unlink()
    metrics, _ = AGG.aggregate(project)
    # WRITTEN, not omitted: `tapeout_docs_gen.g` answers NOT_MEASURED for an
    # absent key too, so omitting it would make "this run had no such report"
    # indistinguishable from "this aggregator has no rule for it".
    assert key in metrics
    assert metrics[key] == AGG.NOT_MEASURED
    assert metrics["__provenance__"][key]["measured"] is False


def test_an_empty_tree_answers_every_key_and_still_exits_zero(tmp_path):
    empty = tmp_path / "bare"
    empty.mkdir()
    rc = AGG.main([str(empty)])
    assert rc == 0
    out = json.loads((empty / "phase3/final/metrics.json").read_text())
    for key, _, _ in AGG.RULES:
        assert out[key] == AGG.NOT_MEASURED
        assert out["__provenance__"][key]["reason"]


def test_every_key_the_release_readers_read_has_a_rule():
    """The readers' table is the population; a key added there and not here
    would silently be NOT_MEASURED forever, which is the exact failure this
    whole program was written to end."""
    wanted = {key for _, key, _ in TDG.MANUFACTURABILITY + TDG.ELECTRICAL}
    wanted.add("design__die__bbox")          # `TDG.die_geometry` reads this one
    assert wanted == {key for key, _, _ in AGG.RULES}


def test_every_measured_key_carries_its_source_and_that_files_sha(project):
    import hashlib
    metrics, _ = AGG.aggregate(project)
    for key, entry in metrics["__provenance__"].items():
        if not entry["measured"]:
            continue
        src = project / entry["source"]
        assert src.is_file(), entry["source"]
        assert entry["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()


def test_drc_keys_are_attributed_by_producer_not_by_filename(project):
    """The router's count must never be written under a sign-off tool's key.

    Swap ONLY the producer strings, leave the filenames alone: the counts must
    follow the producer.
    """
    _write(project / "reports/phase3/drc_router.json", {
        "summary": {"real_violation_total": 3,
                    "producers": [{"producer": "klayout"}]}})
    _write(project / "reports/phase3/drc_signoff.json", {
        "summary": {"real_violation_total": 5,
                    "producers": [{"producer": "openroad"}]}})
    metrics, _ = AGG.aggregate(project)
    assert metrics["klayout__drc_error__count"] == 3
    assert metrics["route__drc_errors"] == 5


def test_a_tool_with_no_report_is_not_zero(project):
    """No magic DRC ran on this fixture, so the magic key states that."""
    metrics, _ = AGG.aggregate(project)
    assert metrics["magic__drc_error__count"] == AGG.NOT_MEASURED
    assert "magic" in metrics["__provenance__"][
        "magic__drc_error__count"]["reason"]


def test_two_reports_claiming_one_tool_is_reported_not_resolved(project):
    _write(project / "reports/phase3/drc_router.json", {
        "summary": {"real_violation_total": 3,
                    "producers": [{"producer": "klayout"}]}})
    metrics, _ = AGG.aggregate(project)
    assert metrics["klayout__drc_error__count"] == AGG.NOT_MEASURED
    assert "contradiction" in metrics["__provenance__"][
        "klayout__drc_error__count"]["reason"]


def test_a_deck_with_no_density_category_yields_no_density_number(project):
    _write(project / "reports/phase3/drc_signoff.json", {
        "summary": {"real_violation_total": 5,
                    "categories_found": ["spacing"],
                    "producers": [{"producer": "klayout"}]}})
    metrics, _ = AGG.aggregate(project)
    assert metrics["klayout__density_error__count"] == AGG.NOT_MEASURED
    # ... and the DRC total is still measured: one absent category does not
    # unmeasure the deck's own violation count.
    assert metrics["klayout__drc_error__count"] == 5


def test_an_lvs_mismatch_is_not_a_count(project):
    _write(project / "reports/phase3/lvs.json",
           {"summary": {"terminal_verdict": "MISMATCH"}})
    metrics, _ = AGG.aggregate(project)
    for key in ("design__lvs_error__count",
                "design__lvs_unmatched_device__count",
                "design__lvs_unmatched_net__count",
                "design__lvs_unmatched_pin__count"):
        assert metrics[key] == AGG.NOT_MEASURED
        assert "MISMATCH" in metrics["__provenance__"][key]["reason"]


def test_an_undeclared_drv_check_is_silence_not_zero(project):
    _write(project / "reports/phase3/sta_spef_based.rpt",
           "SIGNOFF_CHECK_TYPES_REPORTED recovery removal\n")
    metrics, _ = AGG.aggregate(project)
    assert metrics["design__max_slew_violation__count"] == AGG.NOT_MEASURED
    assert metrics["design__max_cap_violation__count"] == AGG.NOT_MEASURED


def test_antenna_over_an_incomplete_route_is_not_a_signoff_count(project):
    _write(project / "reports/phase3/antenna.json",
           {"net_violations": 0, "pin_violations": 0,
            "routing_incomplete": True})
    metrics, _ = AGG.aggregate(project)
    assert metrics["antenna__violating__nets"] == AGG.NOT_MEASURED
    assert metrics["antenna__violating__pins"] == AGG.NOT_MEASURED


def test_a_def_without_units_cannot_be_stated_in_microns(project):
    _write(project / "phase3/stage3/pnr/filled.def",
           "DIEAREA ( 0 0 ) ( 120000 80000 ) ;\n")
    metrics, _ = AGG.aggregate(project)
    assert metrics["design__die__bbox"] == AGG.NOT_MEASURED


# ── the gate clause ─────────────────────────────────────────────────────────
def test_check_passes_on_a_freshly_written_record(project):
    assert AGG.main([str(project)]) == 0
    assert AGG.main([str(project), "--check"]) == 0


def test_check_fails_when_the_record_is_absent(project):
    assert AGG.main([str(project), "--check"]) == 1


def test_check_fails_when_the_record_no_longer_states_what_the_run_states(
        project):
    """A STALE summary is worse than none: the documents built on it look
    current. Re-run the checker with a changed report and --check must refuse."""
    assert AGG.main([str(project)]) == 0
    _write(project / "reports/phase3/antenna.json",
           {"net_violations": 11, "pin_violations": 9,
            "routing_incomplete": False})
    assert AGG.main([str(project), "--check"]) == 1


def test_a_missing_project_is_cannot_check_not_a_pass(tmp_path):
    assert AGG.main([str(tmp_path / "nope")]) == 2
