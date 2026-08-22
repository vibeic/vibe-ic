#!/usr/bin/env python3
"""The reference-flow knob audit must BALANCE against its own buckets (#503).

The sibling files cover WHICH knobs are ingested (`..._pnr_qor_knobs`), that
each names its source file (`..._pnr_knob_audit`), and that the denominator
exists at all (`..._ingest_coverage`). This file covers whether the denominator
is TRUE — whether every name it counts is actually reported somewhere.

Three defects are pinned here, all reproduced against the pre-fix tree:

  GAP-F  `declared_total` did not balance against `adopted` + `rejected` +
         `not_recognised`. A knob honoured by the SYNTH path is excluded from
         `not_recognised` (it IS recognised) and can never reach
         `adopted`/`rejected` (only the PnR ingest feeds those), so it
         landed in NO bucket: counted in the denominator, listed in no
         section. Measured on a real staged config: declared_total=16 while
         the buckets summed to 14, with
         SWAP_ARITH_OPERATORS and REMOVE_ABC_BUFFERS reported nowhere.

  GAP-G  a config declaring ONLY synth-side knobs reported `status="no-knobs"`,
         whose headline ends "Nothing was silently ignored" — while both knobs
         were recognized and both steered the run. The report stated the
         opposite of the truth.

  GAP-H  an EMPTY declared value was invisible. `ADDER_MAP_FILE :=` is how a
         Make config states "this knob is deliberately off"; the assignment
         regex required a non-empty right-hand side, so a deliberate clear was
         indistinguishable from a knob the design never mentioned.

§4.05 fail-safe (LOAD-BEARING negative control): none of this changes a flow
parameter. The disclosure gets richer; the run does not get configured
differently. Proven here at the emission layer — the `pnr.tcl` a no-config
project produces is compared byte-for-byte against the legacy build.

chip-AGNOSTIC: every fixture is synthetic and every recognised name is the
reference FLOW's own variable name, never a design / vendor / PDK-SKU literal.
The identity test iterates the honoured SET rather than naming knobs, so a knob
added to either ingest in future is covered without editing this file.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

mod = importlib.import_module("phase3_one_shot_runner")
_pl = importlib.import_module("_path_layout")

_APPLIED_KEYS = ("place_density", "die_target_util", "repair_tns_percent",
                 "cts_cluster_size", "cts_cluster_diameter",
                 # the step-32 area ceiling + the power-recovery move
                 "resizer_setup_max_util_pct", "resizer_hold_max_util_pct",
                 "recover_power_pct")

# The exact shape of the staged config that produced the measured 16-vs-14
# imbalance: PnR knobs, synth knobs, a deliberately EMPTY declaration, and
# names no ingest reads — all in one file, which is what a real reference flow
# looks like.
_IMBALANCED_MK = (
    "export DESIGN_NICKNAME = someblock\n"
    "export PLATFORM = sky130hd\n"
    "export SDC_FILE = $(DESIGN_HOME)/constraint.sdc\n"
    "# Adders degrade this design's setup repair\n"
    "export ADDER_MAP_FILE :=\n"
    "export CORE_UTILIZATION = 50\n"
    "export PLACE_DENSITY_LB_ADDON = 0.25\n"
    "export TNS_END_PERCENT = 100\n"
    "export REMOVE_ABC_BUFFERS = 1\n"
    "export CTS_CLUSTER_SIZE = 20\n"
    "export CTS_CLUSTER_DIAMETER = 50\n"
    "export SWAP_ARITH_OPERATORS = 1\n"
    "export OPENROAD_HIERARCHICAL = 1\n"
)


def _stage(project: Path, files: dict) -> Path:
    rf = project / "input" / "reference_flow"
    rf.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        p = rf / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return rf


def _bucket_names(audit) -> dict:
    """EVERY bucket as a name-set, read from the AUDIT the flow produces.

    DERIVED from `_RF_PNR_BUCKETS` rather than listed by hand. When this helper
    named its four buckets literally, adding a fifth (`withheld`, #541) made
    every identity assertion below fail against a correct audit — the helper,
    not the producer, was the thing that had drifted. Deriving it means a
    bucket added to the producer is covered here with no edit, which is exactly
    the property these tests exist to guarantee for the report itself."""
    return {b: {e["knob"] for e in audit.get(b, [])}
            for b in mod._RF_PNR_BUCKETS}


def _render(project: Path, audit) -> str:
    mod._write_reference_flow_pnr_report(project, audit)
    return _pl.report_path(project, "reference_flow_knobs.md").read_text()


# ---------------------------------------------------------------------------
# GAP-F — the accounting identity
# ---------------------------------------------------------------------------
class TestAccountingIdentity:
    def test_every_declared_name_lands_in_exactly_one_bucket(self, tmp_path):
        # GENERIC, and deliberately so: the config is built by ITERATING the
        # honoured set, so a knob added to EITHER ingest in future is covered
        # without touching this test. That is the property that keeps the hole
        # from silently re-opening.
        lines = [f"{k} = 1\n" for k in sorted(mod._ORFS_HONOURED_KNOBS)]
        lines += ["SOME_UNREAD_NAME = x\n", "ANOTHER_UNREAD_NAME = y\n"]
        _stage(tmp_path, {"flow.mk": "".join(lines)})
        a = mod._reference_flow_pnr_audit(tmp_path)
        scan = mod._rf_pnr_scan(tmp_path)
        declared = set(scan["all_declared"])
        assert declared, "fixture declared nothing"

        buckets = _bucket_names(a)
        union = set().union(*buckets.values())
        # (1) nothing falls between the buckets …
        assert declared - union == set(), (
            "declared names in NO bucket: %s" % sorted(declared - union))
        # (2) … and no bucket invents a name the config never declared.
        assert union - declared == set()
        # (3) exactly one bucket each.
        for n in sorted(declared):
            holders = [b for b, names in buckets.items() if n in names]
            assert len(holders) == 1, f"{n} in buckets {holders}"

    def test_each_honoured_knob_individually_reaches_a_bucket(self, tmp_path):
        # The set-level test above could pass while one specific knob is
        # rescued by another name's bucket membership. Drive each on its own.
        for i, knob in enumerate(sorted(mod._ORFS_HONOURED_KNOBS)):
            proj = tmp_path / f"p{i}"
            _stage(proj, {"flow.mk": f"{knob} = 1\n"})
            a = mod._reference_flow_pnr_audit(proj)
            union = set().union(*_bucket_names(a).values())
            assert knob in union, f"{knob} reached no bucket"

    def test_measured_imbalance_case_now_balances(self, tmp_path):
        # The reproduction from the issue: pre-fix this config counted 16 and
        # its buckets summed to 14, with two knobs reported nowhere.
        _stage(tmp_path, {"orfs_config.mk": _IMBALANCED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        buckets = _bucket_names(a)
        total = sum(len(v) for v in buckets.values())
        assert total == a["declared_total"], (
            f"declared_total={a['declared_total']} but buckets sum to {total}")
        # the two names that were in no bucket at all
        assert {"SWAP_ARITH_OPERATORS", "REMOVE_ABC_BUFFERS"} <= \
            buckets["honoured_elsewhere"]

    def test_audit_carries_the_balance_proof(self, tmp_path):
        _stage(tmp_path, {"orfs_config.mk": _IMBALANCED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        acct = a["accounting"]
        assert acct["balanced"] is True
        assert acct["unaccounted"] == []
        assert acct["total"] == a["declared_total"]
        assert sum(acct["counts"].values()) == acct["total"]

    def test_balance_proof_is_machine_readable_in_the_json(self, tmp_path):
        _stage(tmp_path, {"orfs_config.mk": _IMBALANCED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        mod._write_reference_flow_pnr_report(tmp_path, a)
        data = json.loads(
            _pl.report_path(tmp_path, "reference_flow_knobs.json").read_text())
        assert data["accounting"]["balanced"] is True
        assert set(data["accounting"]["counts"]) == set(mod._RF_PNR_BUCKETS)

    def test_report_shows_where_every_declared_name_went(self, tmp_path):
        _stage(tmp_path, {"orfs_config.mk": _IMBALANCED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        txt = _render(tmp_path, a)
        assert "Where every declared name went" in txt
        assert "exactly one bucket" in txt

    def test_accounting_checker_detects_a_name_in_no_bucket(self):
        # NEGATIVE CONTROL for the checker itself: `balanced` must be computed,
        # not asserted. Hand it the pre-fix shape — a declared name none of the
        # buckets claims — and it must say so.
        acct = mod._rf_pnr_accounting(
            ["A", "B", "ORPHAN"],
            {"adopted": ["A"], "rejected": [], "honoured_elsewhere": [],
             "not_recognised": ["B"]})
        assert acct["balanced"] is False
        assert acct["unaccounted"] == ["ORPHAN"]

    def test_accounting_resolves_a_name_claimed_twice(self):
        # A knob declared twice (once unusable, once usable) reaches two lists.
        # The partition must stay a partition: first bucket in precedence wins.
        acct = mod._rf_pnr_accounting(
            ["A"], {"adopted": ["A"], "rejected": ["A"],
                    "honoured_elsewhere": [], "not_recognised": []})
        assert acct["balanced"] is True
        assert acct["buckets"]["adopted"] == ["A"]
        assert acct["buckets"]["rejected"] == []

    def test_unbalanced_report_says_so_instead_of_showing_a_clean_table(self):
        # If the identity ever breaks again, the reader must SEE it.
        audit = {
            "status": "knobs-adopted", "config_dir": "input/reference_flow",
            "config_files": ["input/reference_flow/f.mk"], "unreadable": [],
            "unscanned": [], "excluded_oracle": [], "ingest_complete": True,
            "declared_total": 3, "not_recognised": [],
            "honoured_elsewhere": [],
            "adopted": [], "rejected": [],
            "accounting": mod._rf_pnr_accounting(
                ["A", "B", "ORPHAN"],
                {"adopted": ["A"], "rejected": [], "honoured_elsewhere": [],
                 "not_recognised": ["B"]}),
            "applied": {k: None for k in _APPLIED_KEYS}, "notes": [],
        }
        txt = mod._render_reference_flow_pnr_report(audit)
        assert "does NOT balance" in txt
        assert "ORPHAN" in txt


# ---------------------------------------------------------------------------
# GAP-F/2 — the new bucket carries PROVENANCE and is distinct from `adopted`
# ---------------------------------------------------------------------------
class TestHonouredElsewhereProvenance:
    def test_entry_carries_knob_value_and_declaring_file(self, tmp_path):
        _stage(tmp_path, {"nested/vendor.mk": "SWAP_ARITH_OPERATORS = 1\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        e = {h["knob"]: h for h in a["honoured_elsewhere"]}
        assert e["SWAP_ARITH_OPERATORS"]["value"] == "1"
        assert (e["SWAP_ARITH_OPERATORS"]["source"]
                == "input/reference_flow/nested/vendor.mk")

    def test_entry_names_the_subsystem_that_honoured_it(self, tmp_path):
        _stage(tmp_path, {"flow.mk": "REMOVE_ABC_BUFFERS = 1\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        h = a["honoured_elsewhere"][0]
        assert h["honoured_by"] == "synth"
        assert "synth" in h["honoured_by_label"]
        assert "CARRIED" in h["effect"]

    def test_bucket_is_distinct_from_adopted(self, tmp_path):
        # All three kinds in one config: the reader must be able to tell which
        # subsystem honoured which knob, and which knob was understood and
        # declined. Merging any two would lose that.
        _stage(tmp_path, {"flow.mk": ("TNS_END_PERCENT = 100\n"
                                      "CORE_UTILIZATION = 50\n"
                                      "SWAP_ARITH_OPERATORS = 1\n")})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert {x["knob"] for x in a["adopted"]} == {"TNS_END_PERCENT"}
        assert {x["knob"] for x in a["withheld"]} == {"CORE_UTILIZATION"}
        assert {x["knob"] for x in a["honoured_elsewhere"]} == {
            "SWAP_ARITH_OPERATORS"}

    def test_effect_follows_the_honouring_ingest_not_a_guess(self, tmp_path):
        # An explicitly falsy boolean is NOT requested. Reporting it as
        # "carried" would be the same over-claim this report exists to prevent.
        _stage(tmp_path, {"flow.mk": "SWAP_ARITH_OPERATORS = 0\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        h = a["honoured_elsewhere"][0]
        assert "NOT REQUESTED" in h["effect"]
        assert "CARRIED" not in h["effect"]
        # …and the honouring ingest agrees.
        assert "SWAP_ARITH_OPERATORS" not in mod._reference_flow_qor_knobs(
            tmp_path)

    def test_report_renders_the_section_with_value_and_source(self, tmp_path):
        _stage(tmp_path, {"flow.mk": "SWAP_ARITH_OPERATORS = 1\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        txt = _render(tmp_path, a)
        assert "Honoured by another phase-3 subsystem" in txt
        assert "SWAP_ARITH_OPERATORS" in txt
        assert "input/reference_flow/flow.mk" in txt

    def test_last_assignment_wins_in_the_reported_value(self, tmp_path):
        # The value shown must be the one that steers the run.
        _stage(tmp_path, {"a.mk": "ADDER_MAP_FILE = first.v\n",
                          "z.mk": "ADDER_MAP_FILE = second.v\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        h = {x["knob"]: x for x in a["honoured_elsewhere"]}["ADDER_MAP_FILE"]
        assert h["value"] == "second.v"
        assert h["source"] == "input/reference_flow/z.mk"


# ---------------------------------------------------------------------------
# GAP-H — a deliberate EMPTY declaration is a declaration
# ---------------------------------------------------------------------------
class TestEmptyDeclarationIsADeclaration:
    def test_empty_value_is_counted_in_the_denominator(self, tmp_path):
        _stage(tmp_path, {"flow.mk": ("# deliberately off\n"
                                      "export ADDER_MAP_FILE :=\n"
                                      "export CORE_UTILIZATION = 50\n")})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["declared_total"] == 2
        assert "ADDER_MAP_FILE" in {h["knob"] for h in a["honoured_elsewhere"]}

    def test_empty_value_renders_as_a_deliberate_clear(self, tmp_path):
        _stage(tmp_path, {"flow.mk": "export ADDER_MAP_FILE :=\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        h = a["honoured_elsewhere"][0]
        assert h["value"] == ""
        assert "DECLARED EMPTY" in h["effect"]
        assert "NOT a missing declaration" in h["effect"]
        txt = _render(tmp_path, a)
        assert "(empty)" in txt
        assert "deliberate clear" in txt

    def test_empty_value_clears_an_earlier_declaration(self, tmp_path):
        # Make's last-assignment-wins, which the ingest already intended (its
        # empty-value branch existed) but could not reach: the regex never
        # matched the clearing line.
        _stage(tmp_path, {"flow.mk": ("ADDER_MAP_FILE = adders.v\n"
                                      "ADDER_MAP_FILE :=\n")})
        assert "ADDER_MAP_FILE" not in mod._reference_flow_qor_knobs(tmp_path)
        a = mod._reference_flow_pnr_audit(tmp_path)
        h = {x["knob"]: x for x in a["honoured_elsewhere"]}["ADDER_MAP_FILE"]
        assert h["value"] == ""

    def test_empty_value_does_not_clear_a_later_declaration(self, tmp_path):
        _stage(tmp_path, {"flow.mk": ("ADDER_MAP_FILE :=\n"
                                      "ADDER_MAP_FILE = adders.v\n")})
        assert mod._reference_flow_qor_knobs(tmp_path)["ADDER_MAP_FILE"] == \
            "adders.v"

    def test_empty_numeric_declaration_is_disclosed_not_applied(
            self, tmp_path):
        # An empty PnR knob is a declaration we cannot use. It must be
        # DISCLOSED, and it must not fabricate or clobber a valid value.
        # (Vehicle is an APPLIED knob — since #541 a supply-class knob is not
        # value-judged at all, so it cannot exercise last-valid-wins.)
        _stage(tmp_path, {"flow.mk": ("TNS_END_PERCENT = 100\n"
                                      "TNS_END_PERCENT :=\n")})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["applied"]["repair_tns_percent"] == 100  # last VALID kept
        assert any(r["knob"] == "TNS_END_PERCENT" for r in a["rejected"])
        assert a["accounting"]["balanced"] is True

    def test_empty_withheld_knob_is_still_on_the_record(self, tmp_path):
        # #541 — an empty declaration of a WITHHELD knob must not vanish. It is
        # withheld (that is the fact that decided the run) and its declared
        # value is carried verbatim, so a malformed/empty declaration is still
        # visible to the reader.
        _stage(tmp_path, {"flow.mk": "CORE_UTILIZATION :=\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["applied"]["die_target_util"] is None
        held = {x["knob"]: x for x in a["withheld"]}
        assert set(held) == {"CORE_UTILIZATION"}
        assert held["CORE_UTILIZATION"]["value"] == ""
        assert a["rejected"] == []
        assert a["accounting"]["balanced"] is True

    def test_malformed_withheld_knob_outranks_honoured_elsewhere(self,
                                                                 tmp_path):
        """A MALFORMED withheld knob leaves the numerically-valid set empty, so
        the verdict ladder falls through to the `not declared and not rejected`
        branches. `knobs-honoured-elsewhere` must not claim it: that headline
        asserts the config declares NO floorplan/place/CTS/timing knob, and
        here it declares one this ingest read and declined."""
        _stage(tmp_path, {"flow.mk": ("CORE_UTILIZATION = $(SOME_VAR)\n"
                                      "REMOVE_ABC_BUFFERS = 1\n")})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "knobs-withheld"
        assert [w["knob"] for w in a["withheld"]] == ["CORE_UTILIZATION"]
        assert [h["knob"] for h in a["honoured_elsewhere"]] == [
            "REMOVE_ABC_BUFFERS"]
        assert a["applied"]["die_target_util"] is None
        assert a["accounting"]["balanced"] is True
        txt = _render(tmp_path, a)
        assert "declares NO floorplan" not in txt

    def test_bare_tcl_set_is_a_read_not_an_empty_assignment(self, tmp_path):
        # NEGATIVE CONTROL on the regex relaxation: `set NAME` (and
        # `set ::env(NAME)`) READ a Tcl variable. Admitting them as
        # assignments-to-empty would invent a declaration the config never
        # made — and would let a bare read clear a real value.
        _stage(tmp_path, {"flow.tcl": ("set ::env(TNS_END_PERCENT) 100\n"
                                       "set TNS_END_PERCENT\n"
                                       "set ::env(ADDER_MAP_FILE)\n")})
        scan = mod._rf_pnr_scan(tmp_path)
        assert set(scan["all_declared"]) == {"TNS_END_PERCENT"}
        assert mod._reference_flow_pnr_audit(
            tmp_path)["applied"]["repair_tns_percent"] == 100


# ---------------------------------------------------------------------------
# GAP-G — the status, and its headline, in lockstep
# ---------------------------------------------------------------------------
class TestStatusAndHeadlineLockstep:
    def test_synth_only_config_is_not_reported_as_no_knobs(self, tmp_path):
        _stage(tmp_path, {"orfs_config.mk": (
            "export ADDER_MAP_FILE := adders/kogge_stone.v\n"
            "export SWAP_ARITH_OPERATORS := 1\n")})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "knobs-honoured-elsewhere"
        txt = _render(tmp_path, a)
        # the sentence that stated the opposite of the truth
        assert "Nothing was silently ignored" not in txt
        assert "was NOT ignored" in txt
        assert "ADDER_MAP_FILE" in txt and "SWAP_ARITH_OPERATORS" in txt

    def test_genuinely_knobless_config_still_says_no_knobs(self, tmp_path):
        # The old verdict must NOT be lost — it is correct when it is true.
        _stage(tmp_path, {"flow.mk": "SOME_FLOW_VAR = 42\nPLATFORM = x\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "no-knobs"
        assert "Nothing was silently ignored" in _render(tmp_path, a)

    def test_status_set_and_headline_map_are_the_same_set(self):
        assert set(mod._RF_PNR_STATUSES) == set(mod._RF_PNR_STATUS_HEADLINE)
        assert "knobs-honoured-elsewhere" in mod._RF_PNR_STATUSES

    def test_every_status_the_producer_emits_has_a_headline(self, tmp_path):
        # Drive the PRODUCER over fixtures covering every status it can reach,
        # and require a registered, non-empty, non-defect headline for each.
        fixtures = {
            "no-config": None,
            "no-knobs": {"flow.mk": "SOME_FLOW_VAR = 42\n"},
            "knobs-honoured-elsewhere": {
                "flow.mk": "REMOVE_ABC_BUFFERS = 1\n"},
            "knobs-rejected": {"flow.mk": "TNS_END_PERCENT = 400\n"},
            "knobs-adopted": {"flow.mk": "TNS_END_PERCENT = 100\n"},
            # #541 — the two verdicts a withheld supply-class knob can reach.
            "knobs-withheld": {"flow.mk": "CORE_UTILIZATION = 50\n"},
            "knobs-adopted-some-withheld": {
                "flow.mk": "CORE_UTILIZATION = 50\nTNS_END_PERCENT = 100\n"},
            # A recipe file this ingest opens, parses, and recognises NOTHING
            # in — a lowercase-Tcl flow-variable dialect. Distinct from
            # "no-knobs" (`SOME_FLOW_VAR = 42` above), which IS recognised as
            # an assignment and merely names a knob nothing honours.
            "config-dialect-unrecognised": {
                "flow.tcl": "set flow_clk_period 8000.0\n"},
        }
        seen = set()
        for i, (expect, files) in enumerate(sorted(fixtures.items())):
            proj = tmp_path / f"s{i}"
            proj.mkdir()
            if files:
                _stage(proj, files)
            a = mod._reference_flow_pnr_audit(proj)
            assert a["status"] == expect
            assert a["status"] in mod._RF_PNR_STATUSES
            head = mod._rf_pnr_status_headline(a["status"])
            assert head and "INTERNAL DEFECT" not in head
            seen.add(a["status"])
        # config-unreadable needs a permission failure; it is exercised by the
        # sibling coverage suite. Everything else must be covered right here.
        assert seen == set(mod._RF_PNR_STATUSES) - {"config-unreadable"}

    def test_unregistered_status_renders_loudly_not_blank(self, tmp_path):
        # NEGATIVE CONTROL for the lockstep: a status with no headline used to
        # render as an empty line — drift the reader could not notice.
        head = mod._rf_pnr_status_headline("some-future-status")
        assert "INTERNAL DEFECT" in head
        a = mod._reference_flow_pnr_audit(tmp_path)
        a["status"] = "some-future-status"
        assert "INTERNAL DEFECT" in mod._render_reference_flow_pnr_report(a)


# ---------------------------------------------------------------------------
# §4.05 NEGATIVE CONTROL — richer disclosure, identical flow
# ---------------------------------------------------------------------------
class TestFlowBehaviourUnchanged:
    def test_no_config_is_still_no_config(self, tmp_path):
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "no-config"
        assert a["honoured_elsewhere"] == []
        assert a["accounting"]["balanced"] is True
        assert all(a["applied"][k] is None for k in _APPLIED_KEYS)

    def test_no_config_pnr_tcl_is_byte_identical_to_legacy(self, tmp_path):
        a = mod._reference_flow_pnr_audit(tmp_path)
        base = dict(
            tech_lef_c="t.lef", cell_lef_c="c.lef", macro_lefs_tcl="",
            liberty_c="l.lib", macro_libs_tcl="", netlist_c="n.v", top="top",
            sdc_c="c.sdc", dont_use_block="", metal_prefix="met", die_w=100,
            die_h=100, core_pad=10, core_w=80, core_h=80, site="unit",
            out_dir_c="/out", tapcell_block="", pdn_block="", util=0.30,
            spare_protection_tcl="", spare_postfix_tcl="", clk_buf="clkbuf_4",
            clk_buf_root="clkbuf_16", routing_constraint_tcl="",
            pg_cleanup_block="", spef_repair_block="", antenna_repair_block="",
            filler_block="")
        legacy = mod._build_pnr_tcl_text(**base)
        from_audit = mod._build_pnr_tcl_text(
            **base,
            repair_tns_percent=a["applied"]["repair_tns_percent"],
            cts_cluster_size=a["applied"]["cts_cluster_size"],
            cts_cluster_diameter=a["applied"]["cts_cluster_diameter"])
        assert legacy == from_audit

    def test_honoured_elsewhere_reaches_no_pnr_parameter(self, tmp_path):
        # Giving a synth knob a bucket must not give it a PnR effect.
        _stage(tmp_path, {"flow.mk": ("SWAP_ARITH_OPERATORS = 1\n"
                                      "REMOVE_ABC_BUFFERS = 1\n"
                                      "ADDER_MAP_FILE = adders.v\n")})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert all(a["applied"][k] is None for k in _APPLIED_KEYS)
        assert a["adopted"] == []

    def test_pnr_parameters_are_unchanged_by_the_new_bucket(self, tmp_path):
        # The OPTIMIZATION class is applied; the SUPPLY class is withheld
        # (#541), so the two floorplan parameters stay at the phase-3 default.
        _stage(tmp_path, {"orfs_config.mk": _IMBALANCED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        # The three `resizer_*` / `recover_power_pct` entries joined the
        # vocabulary with the step-32 area ceiling (2026-08-20) and are None
        # here because this fixture declares none of them — which is the whole
        # point of restating the dict by hand: a NEW parameter has to make
        # somebody look at what it is worth on a config that never mentions it.
        assert a["applied"] == {
            "place_density": None, "die_target_util": None,
            "repair_tns_percent": 100, "cts_cluster_size": 20,
            "cts_cluster_diameter": 50.0,
            "cts_distance_between_buffers": None,
            "resizer_setup_max_util_pct": None,
            "resizer_hold_max_util_pct": None,
            "recover_power_pct": None}

    def test_two_projects_same_config_served_identically(self, tmp_path):
        # chip-AGNOSTIC: the verdict follows the staged config, nothing else.
        for name in ("designA", "designB"):
            _stage(tmp_path / name, {"orfs_config.mk": _IMBALANCED_MK})
        (tmp_path / "designB" / "rtl").mkdir()
        (tmp_path / "designB" / "rtl" / "u.v").write_text(
            "module u; endmodule\n")
        aa = mod._reference_flow_pnr_audit(tmp_path / "designA")
        bb = mod._reference_flow_pnr_audit(tmp_path / "designB")
        assert aa["applied"] == bb["applied"]
        assert aa["status"] == bb["status"]
        assert aa["accounting"] == bb["accounting"]
        assert aa["honoured_elsewhere"] == bb["honoured_elsewhere"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
