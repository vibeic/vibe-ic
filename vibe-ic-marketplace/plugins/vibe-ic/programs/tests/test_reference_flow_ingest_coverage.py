#!/usr/bin/env python3
"""Coverage disclosure for the Phase-3 reference-flow knob ingest (issue #198).

The sibling audit tests cover WHICH knobs are adopted and that each names its
source file. This file covers the DENOMINATOR — whether a finished run can be
audited for how much of the design's declaration it actually acted on.

Two gaps are pinned here, both reproduced against tracked corpus configs before
the fix, and both the same failure shape: NOT EXAMINED rendering exactly like
NOTHING TO EXAMINE.

  GAP-D  the audit reported an adopted-knob list with no denominator. A config
         declaring 16 assignments of which phase-3 honours 7 produced the same
         shape of report as a config declaring exactly those 7 — the names no
         phase-3 ingest reads were never counted and never listed, so a reader
         could not tell the run was configured differently from what the design
         declares.

  GAP-E  a staged config that could NOT be read reported `status="no-knobs"`,
         whose headline asserts "Nothing was silently ignored" — a clean
         verdict resting on files that were never opened. Likewise a staged
         file whose extension the scanner does not parse was neither adopted
         nor rejected nor mentioned: it simply vanished from the walk.

§4.05 fail-safe (LOAD-BEARING negative control): none of this changes a flow
parameter. A project with no staged config, and a project whose config is fully
read, must produce exactly the applied values they produce today — the ingest
DISCLOSES more, it does not decide differently.

chip-AGNOSTIC: every fixture below is synthetic. The recognised names are the
reference flow's OWN variable names, never a design/vendor/PDK-SKU literal.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

mod = importlib.import_module("phase3_one_shot_runner")
_pl = importlib.import_module("_path_layout")
_rfb = importlib.import_module("_reference_flow_boundary")
_fc = importlib.import_module("floorplan_contract")

# A QoR-RULES artifact: metric -> expected value + comparison operator, plus a
# golden netlist hash. This is what the known-good run ACHIEVED, not how to
# configure a run — the oracle half of a mixed reference flow.
_ORACLE_RULES = json.dumps({
    "synth__netlist__hash": {"value": "0" * 40, "compare": "=="},
    "finish__timing__setup__ws": {"value": -0.5, "compare": ">="},
    "finish__design__instance__area": {"value": 177762, "compare": "<="},
    "detailedroute__route__drc_errors": {"value": 0, "compare": "<="},
})


def _stage(project: Path, files: dict) -> Path:
    rf = project / "input" / "reference_flow"
    rf.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        p = rf / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return rf


# Three names phase-3 honours (two back-end, one synth-side) and four it
# honours nowhere — a realistic reference flow declares both kinds in one file.
_MIXED_MK = (
    "export CORE_UTILIZATION = 50\n"
    "export TNS_END_PERCENT = 100\n"
    "export SWAP_ARITH_OPERATORS = 1\n"
    "export SOME_FRONTEND_SELECT = alt\n"
    "export SOME_HIER_MODE = 1\n"
    "export SOME_ROUTE_TCL = $(FLOW_HOME)/r.tcl\n"
    "export SOME_SOURCE_LIST = $(wildcard src/*.v)\n"
)
_APPLIED_KEYS = ("place_density", "die_target_util", "repair_tns_percent",
                 "cts_cluster_size", "cts_cluster_diameter")


# ---------------------------------------------------------------------------
# GAP-D — the denominator
# ---------------------------------------------------------------------------
class TestDeclarationDenominator:
    def test_declared_total_counts_every_assignment(self, tmp_path):
        # The numerator ("5 adopted") is unauditable without this.
        _stage(tmp_path, {"flow.mk": _MIXED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["declared_total"] == 7

    def test_names_honoured_nowhere_are_listed_with_their_source(self, tmp_path):
        _stage(tmp_path, {"flow.mk": _MIXED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        names = {r["knob"] for r in a["not_recognised"]}
        assert names == {"SOME_FRONTEND_SELECT", "SOME_HIER_MODE",
                         "SOME_ROUTE_TCL", "SOME_SOURCE_LIST"}
        assert all(r["source"] == "input/reference_flow/flow.mk"
                   for r in a["not_recognised"])

    def test_synth_side_knobs_count_as_honoured_not_ignored(self, tmp_path):
        # A knob applied by the SYNTH step must not be reported as "honoured
        # nowhere" just because the PnR audit does not apply it — that would
        # make the denominator lie in the opposite direction.
        _stage(tmp_path, {"flow.mk": _MIXED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert "SWAP_ARITH_OPERATORS" not in {r["knob"]
                                              for r in a["not_recognised"]}

    def test_every_declared_name_is_either_honoured_or_disclosed(self, tmp_path):
        # No assignment may fall between the two buckets and disappear.
        _stage(tmp_path, {"flow.mk": _MIXED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        honoured = a["declared_total"] - len(a["not_recognised"])
        assert honoured == 3
        assert honoured + len(a["not_recognised"]) == a["declared_total"]

    def test_report_states_the_denominator_not_just_the_adopted_list(
            self, tmp_path):
        _stage(tmp_path, {"flow.mk": _MIXED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        mod._write_reference_flow_pnr_report(tmp_path, a)
        txt = _pl.report_path(tmp_path, "reference_flow_knobs.md").read_text()
        assert "Ingest coverage" in txt
        assert "of 7" in txt          # a PASS discloses its denominator
        assert "SOME_HIER_MODE" in txt

    def test_denominator_is_machine_readable(self, tmp_path):
        _stage(tmp_path, {"flow.mk": _MIXED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        mod._write_reference_flow_pnr_report(tmp_path, a)
        data = json.loads(
            _pl.report_path(tmp_path, "reference_flow_knobs.json").read_text())
        assert data["declared_total"] == 7
        assert len(data["not_recognised"]) == 4
        assert data["ingest_complete"] is True


# ---------------------------------------------------------------------------
# GAP-E — an incomplete read must never render as a clean one
# ---------------------------------------------------------------------------
class TestIncompleteReadIsNeverClean:
    def test_unreadable_only_config_is_not_reported_as_no_knobs(self, tmp_path):
        rf = _stage(tmp_path, {"flow.mk": "CORE_UTILIZATION = 50\n"})
        (rf / "flow.mk").chmod(0o000)
        try:
            a = mod._reference_flow_pnr_audit(tmp_path)
        finally:
            (rf / "flow.mk").chmod(0o644)
        if not a["unreadable"]:
            return                     # running as root: cannot make it unreadable
        assert a["status"] == "config-unreadable"
        assert a["ingest_complete"] is False

    def test_unreadable_config_report_makes_no_clean_claim(self, tmp_path):
        rf = _stage(tmp_path, {"flow.mk": "CORE_UTILIZATION = 50\n"})
        (rf / "flow.mk").chmod(0o000)
        try:
            a = mod._reference_flow_pnr_audit(tmp_path)
        finally:
            (rf / "flow.mk").chmod(0o644)
        if not a["unreadable"]:
            return
        mod._write_reference_flow_pnr_report(tmp_path, a)
        txt = _pl.report_path(tmp_path, "reference_flow_knobs.md").read_text()
        assert "Nothing was silently ignored" not in txt
        assert "INCOMPLETE" in txt

    def test_staged_file_with_unparsed_extension_is_disclosed(self, tmp_path):
        rf = _stage(tmp_path, {"flow.mk": "CORE_UTILIZATION = 50\n"})
        (rf / "rules.json").write_text('{"a": 1}\n')
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["unscanned"] == ["input/reference_flow/rules.json"]
        assert a["ingest_complete"] is False

    def test_unexamined_file_is_named_in_the_report(self, tmp_path):
        rf = _stage(tmp_path, {"flow.mk": "CORE_UTILIZATION = 50\n"})
        (rf / "rules.json").write_text('{"a": 1}\n')
        a = mod._reference_flow_pnr_audit(tmp_path)
        mod._write_reference_flow_pnr_report(tmp_path, a)
        txt = _pl.report_path(tmp_path, "reference_flow_knobs.md").read_text()
        assert "NOT EXAMINED" in txt
        assert "rules.json" in txt

    def test_incomplete_ingest_states_its_figures_are_a_floor(self, tmp_path):
        rf = _stage(tmp_path, {"flow.mk": _MIXED_MK})
        (rf / "rules.json").write_text('{"a": 1}\n')
        a = mod._reference_flow_pnr_audit(tmp_path)
        mod._write_reference_flow_pnr_report(tmp_path, a)
        txt = _pl.report_path(tmp_path, "reference_flow_knobs.md").read_text()
        assert "floor, not a total" in txt

    def test_dangling_symlink_is_counted_as_staged_not_invisible(self, tmp_path):
        # A staged entry that resolves to nothing is neither a directory nor a
        # readable file. It must still be counted, or the walk under-reports
        # what the design shipped.
        rf = _stage(tmp_path, {"flow.mk": "CORE_UTILIZATION = 50\n"})
        (rf / "linked.json").symlink_to(rf / "does_not_exist.json")
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert "input/reference_flow/linked.json" in a["unscanned"]
        assert a["ingest_complete"] is False

    def test_fully_read_config_reports_complete(self, tmp_path):
        _stage(tmp_path, {"flow.mk": _MIXED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["ingest_complete"] is True
        assert a["unreadable"] == [] and a["unscanned"] == []

    def test_readable_config_declaring_nothing_recognised_stays_no_knobs(
            self, tmp_path):
        # Complete read + no recognised knob is a genuine clean verdict and
        # must NOT be downgraded — the new status is for incompleteness only.
        _stage(tmp_path, {"flow.mk": "SOME_FLOW_VAR = 42\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "no-knobs"
        assert a["ingest_complete"] is True
        assert a["declared_total"] == 1


# ---------------------------------------------------------------------------
# §4.05 NEGATIVE CONTROL — disclosure changes no flow parameter
# ---------------------------------------------------------------------------
class TestDisclosureChangesNothing:
    def test_no_config_project_is_complete_and_empty(self, tmp_path):
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "no-config"
        assert a["declared_total"] == 0
        assert a["not_recognised"] == []
        assert a["ingest_complete"] is True
        assert all(a["applied"][k] is None for k in _APPLIED_KEYS)

    def test_no_config_report_has_no_coverage_section(self, tmp_path):
        # Nothing was staged, so there is no denominator to state; the report
        # must not manufacture a "0 of 0" coverage claim.
        a = mod._reference_flow_pnr_audit(tmp_path)
        mod._write_reference_flow_pnr_report(tmp_path, a)
        txt = _pl.report_path(tmp_path, "reference_flow_knobs.md").read_text()
        assert "Ingest coverage" not in txt
        assert "no-config" in txt

    def test_unrecognised_names_never_reach_applied_parameters(self, tmp_path):
        # Counting a name in the denominator must not admit it to the flow.
        _stage(tmp_path, {"flow.mk": _MIXED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["applied"]["repair_tns_percent"] == 100  # from TNS_END_PERCENT
        # #541 — CORE_UTILIZATION is withheld, so NEITHER floorplan parameter
        # is set. Neither is set by any of the four unrecognised names either,
        # which is what this test is here to prove.
        assert a["applied"]["die_target_util"] is None
        assert a["applied"]["place_density"] is None
        # nothing declared CTS clustering, so it stays at the generic default
        assert a["applied"]["cts_cluster_size"] is None
        assert a["applied"]["cts_cluster_diameter"] is None

    def test_unexamined_file_contents_never_reach_applied_parameters(
            self, tmp_path):
        rf = _stage(tmp_path, {"flow.mk": "TNS_END_PERCENT = 100\n"})
        (rf / "rules.json").write_text('{"TNS_END_PERCENT": 90}\n')
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["applied"]["repair_tns_percent"] == 100   # the .mk value, not 90


# ---------------------------------------------------------------------------
# §4.05 BOUNDARY — a staged reference flow is MIXED. Recipe is design input;
# a QoR-rules artifact is the oracle and is off-limits. Declining to read the
# oracle is COMPLIANCE and must never be reported as a coverage gap.
# ---------------------------------------------------------------------------
class TestOracleBoundary:
    def test_qor_rules_artifact_is_classified_oracle(self, tmp_path):
        _stage(tmp_path, {"flow.mk": "CORE_UTILIZATION = 50\n",
                          "rules.json": _ORACLE_RULES})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["excluded_oracle"] == ["input/reference_flow/rules.json"]
        assert a["unscanned"] == []

    def test_oracle_exclusion_does_not_count_against_completeness(self, tmp_path):
        # Reporting compliance as incompleteness would push the next reader
        # toward closing the "gap" by parsing the known-good result.
        _stage(tmp_path, {"flow.mk": "CORE_UTILIZATION = 50\n",
                          "rules.json": _ORACLE_RULES})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["ingest_complete"] is True

    def test_report_states_oracle_exclusion_as_compliance_not_gap(self, tmp_path):
        _stage(tmp_path, {"flow.mk": "CORE_UTILIZATION = 50\n",
                          "rules.json": _ORACLE_RULES})
        a = mod._reference_flow_pnr_audit(tmp_path)
        mod._write_reference_flow_pnr_report(tmp_path, a)
        txt = _pl.report_path(tmp_path, "reference_flow_knobs.md").read_text()
        assert "OFF-LIMITS" in txt
        assert "NOT a coverage gap" in txt
        assert "NOT EXAMINED" not in txt

    def test_no_oracle_value_reaches_the_flow(self, tmp_path):
        # The classifier must never become an extractor.
        _stage(tmp_path, {"flow.mk": "TNS_END_PERCENT = 100\n",
                          "rules.json": _ORACLE_RULES})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["applied"]["repair_tns_percent"] == 100
        blob = json.dumps(a)
        for leaked in ("177762", "-0.5", "drc_errors", "netlist__hash"):
            assert leaked not in blob

    def test_recipe_json_is_not_misread_as_oracle(self, tmp_path):
        # A flat settings file states values, never thresholds — it must stay
        # in the ordinary unexamined bucket, not be waved through as oracle.
        rf = _stage(tmp_path, {"flow.mk": "CORE_UTILIZATION = 50\n"})
        (rf / "settings.json").write_text('{"A": 1, "B": "x"}\n')
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["excluded_oracle"] == []
        assert a["unscanned"] == ["input/reference_flow/settings.json"]

    def test_classifier_needs_the_shape_to_dominate(self, tmp_path):
        assert _rfb.is_oracle_qor_rules(_ORACLE_RULES) is True
        assert _rfb.is_oracle_qor_rules('{"A": 1, "B": 2}') is False
        assert _rfb.is_oracle_qor_rules('not json') is False
        assert _rfb.is_oracle_qor_rules('{}') is False
        # one nested dict among many plain settings is a config, not a rules file
        assert _rfb.is_oracle_qor_rules(json.dumps({
            "A": 1, "B": 2, "C": 3,
            "D": {"value": 1, "compare": "=="}})) is False

    def test_reference_flow_is_not_in_the_shared_oracle_vocabulary(self):
        # The tree is MIXED, so its name must not be a blanket oracle marker;
        # the oracle subset is identified on content instead.
        assert "reference_flow" not in _rfb.ORACLE_TREE_SEGMENTS
        assert {"golden", "oracle", "ground_truth"} <= _rfb.ORACLE_TREE_SEGMENTS

    def test_contract_gate_stays_stricter_and_shares_the_vocabulary(self):
        # The sibling gate deliberately skips the whole tree (it has an
        # independent source). That is allowed, but both programs must agree on
        # what "oracle" means, so its set is built FROM the shared vocabulary.
        assert _rfb.ORACLE_TREE_SEGMENTS <= _fc._OFF_LIMITS_SEGMENTS
        assert "reference_flow" in _fc._OFF_LIMITS_SEGMENTS
