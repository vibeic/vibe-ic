#!/usr/bin/env python3
"""A staged recipe file the ingest READ and recognised NOTHING in must say so
(#198 Branch 1).

The sibling files cover which knobs are ingested, that each names its source
file, that the denominator exists, and that it balances. This file covers the
one thing none of them could see: whether the denominator is honest about the
files it was computed FROM.

THE DEFECT, reproduced on a real staged config before the fix
-------------------------------------------------------------
`opentitan_aes` stages `input/reference_flow/pre_syn/aes_lr_synth_conf.tcl`,
which declares six settings in a lowercase-Tcl flow-variable dialect —
including a CLOCK PERIOD. Every one of them was discarded: the ingest's
assignment patterns require a SCREAMING_CASE name, so not one line matched.
The audit then reported, over that file:

    Assignments declared by the staged config: 0
    Config files parsed: 1 (unreadable: 0, not examined: 0)
    Ingest complete: True
    status: no-knobs
    "A config IS staged but declares none of the recognized ORFS knobs
     ... Nothing was silently ignored."

Byte-identical to what an EMPTY staged file produces, and the closing sentence
asserts the exact opposite of what happened. The scan already separated three
ways of not-reading a file — `unreadable` (could not open), `unscanned`
(extension not parsed) and `excluded_oracle` (deliberately not read, §4.05) —
and had no way to state the fourth: opened, parsed, nothing understood.

An ingester that quietly drops what it does not understand is indistinguishable
from one that was never wired. That is the property pinned here.

WHAT IS DELIBERATELY *NOT* FIXED
--------------------------------
The dialect is still not SPOKEN. Nothing here teaches the ingest to read
lowercase Tcl flow variables, and no test asserts a value extracted from one.
Recognising a new dialect is a separate change with a knob->parameter mapping
to justify; admitting that this one was not recognised is owed to the reader
unconditionally and costs no vocabulary at all. Conflating the two is how a
report ends up claiming an effect the flow never produced.

chip-AGNOSTIC: every fixture is synthetic. The unrecognised-dialect fixtures use
invented lowercase flow-variable names; the recognised fixtures use the
reference FLOW's own variable names. No design / vendor / PDK-SKU literal
appears anywhere, and no fixture is keyed on a design that motivated the fix.
"""
from __future__ import annotations

import importlib
from pathlib import Path

mod = importlib.import_module("phase3_one_shot_runner")
_pl = importlib.import_module("_path_layout")

# The sentence that must never be printed over a file nothing was recognised in.
_FALSE_CLAIM = "Nothing was silently ignored"

# A lowercase-Tcl flow-variable dialect: real `set NAME value` declarations that
# this ingest's SCREAMING_CASE patterns do not match. Invented names.
_UNRECOGNISED_TCL = (
    "# Flow configuration\n"
    "set flow_clk_period 8000.0\n"
    "set flow_abc_clk_uprate 4000.0\n"
    "set flow_clk_input clk_i\n"
    "set_flow_bool_var flatten 1 \"flatten\"\n"
)

# The same dialect in a Make-suffixed file — lowercase names the Make assignment
# pattern also refuses, so the flag is not a Tcl-only artefact.
_UNRECOGNISED_MK = (
    "# Flow configuration\n"
    "flow_core_util = 50\n"
    "flow_tns_end_percent = 100\n"
)

# A config the ingest DOES recognise (the reference flow's own knob names).
_RECOGNISED_MK = "export CORE_UTILIZATION = 50\nexport TNS_END_PERCENT = 100\n"


def _stage(project: Path, files: dict) -> Path:
    rf = project / "input" / "reference_flow"
    rf.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        p = rf / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content)
    return rf


def _render(project: Path, audit) -> str:
    mod._write_reference_flow_pnr_report(project, audit)
    return _pl.report_path(project, "reference_flow_knobs.md").read_text()


# ---------------------------------------------------------------------------
# The pure predicates, exercised directly.
# ---------------------------------------------------------------------------
class TestRecipeRecognitionPredicates:

    def test_unrecognised_dialect_is_unrecognised(self):
        assert mod._rf_recipe_is_unrecognised(_UNRECOGNISED_TCL, True) is True
        assert mod._rf_recipe_is_unrecognised(_UNRECOGNISED_MK, False) is True

    def test_recognised_config_is_not_unrecognised(self):
        assert mod._rf_recipe_is_unrecognised(_RECOGNISED_MK, False) is False

    def test_empty_and_comments_only_are_not_flagged(self):
        # An honestly-empty file declares nothing. Flagging it would make the
        # honest case indistinguishable from the defective one — the very
        # failure this predicate exists to remove, with its sign flipped.
        assert mod._rf_recipe_is_unrecognised("", False) is False
        assert mod._rf_recipe_is_unrecognised("\n\n   \n", False) is False
        assert mod._rf_recipe_is_unrecognised(
            "# just a comment\n#  and another\n", False) is False
        assert mod._rf_recipe_is_unrecognised(
            "# a Tcl comment\n", True) is False

    def test_one_recognised_line_clears_the_whole_file(self):
        # HONEST SCOPE, pinned as a test so the boundary is not mistaken for a
        # bug later: this flags a WHOLLY unrecognised file, never an
        # unrecognised LINE inside a file the ingest partly understood.
        mixed = _UNRECOGNISED_TCL + "set ::env(CORE_UTILIZATION) 50\n"
        assert mod._rf_recipe_is_unrecognised(mixed, True) is False

    def test_fastroute_statement_counts_as_recognition(self):
        # LOAD-BEARING (mutation control). A routing-adjust file carries NO
        # assignment at all — it is read by the SIBLING ingest
        # (`_reference_flow_qor_knobs`), not by the PnR assignment scan. Judging
        # recognition by the assignment patterns alone flags a file the flow
        # fully understands, which is a FALSE alarm in the report that exists to
        # be trusted. This is the same cross-subsystem blind spot #503 fixed one
        # level up, and it is why `_rf_recipe_line_recognised` is a UNION.
        fastroute = (
            # A deprecated ORFS spelling, QUOTED AS INPUT: this fixture
            # exists to prove our ingest READS that line, and the flow
            # never emits it. The deprecation gate scans the whole plugin
            # tree, so without saying so here it reads an input we parse
            # as an output we produce.
            "set_global_routing_layer_adjustment "  # deprecated ORFS spelling, quoted as INPUT
            "$::env(MIN_ROUTING_LAYER)-$::env(MAX_ROUTING_LAYER) 0.2\n"
            "set_routing_layers -signal "
            "$::env(MIN_ROUTING_LAYER)-$::env(MAX_ROUTING_LAYER)\n")
        assert mod._rf_recipe_line_recognised(
            fastroute.splitlines()[0], True) is True
        assert mod._rf_recipe_is_unrecognised(fastroute, True) is False

    def test_line_predicate_accepts_each_assignment_form(self):
        assert mod._rf_recipe_line_recognised("CORE_UTILIZATION = 50", False)
        assert mod._rf_recipe_line_recognised("export ADDER_MAP_FILE :=", False)
        assert mod._rf_recipe_line_recognised(
            "set ::env(TNS_END_PERCENT) 100", True)
        assert mod._rf_recipe_line_recognised("setenv CTS_CLUSTER_SIZE 20", True)
        assert mod._rf_recipe_line_recognised("set CTS_CLUSTER_SIZE 20", True)

    def test_line_predicate_rejects_the_unrecognised_dialect(self):
        assert not mod._rf_recipe_line_recognised("set flow_clk_period 8000", True)
        assert not mod._rf_recipe_line_recognised("flow_core_util = 50", False)


# ---------------------------------------------------------------------------
# The audit and the report.
# ---------------------------------------------------------------------------
class TestAuditReportsTheUnrecognisedFile:

    def test_file_is_listed_and_ingest_is_incomplete(self, tmp_path):
        _stage(tmp_path, {"flow.tcl": _UNRECOGNISED_TCL})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["unrecognised_dialect"] == ["input/reference_flow/flow.tcl"]
        # It was OPENED, so it must still appear as a file we read — the point
        # is that both facts are now stated, not that one replaces the other.
        assert "input/reference_flow/flow.tcl" in a["config_files"]
        assert a["ingest_complete"] is False

    def test_status_is_not_no_knobs(self, tmp_path):
        _stage(tmp_path, {"flow.tcl": _UNRECOGNISED_TCL})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "config-dialect-unrecognised"
        assert a["status"] != "no-knobs"

    def test_report_never_claims_nothing_was_ignored(self, tmp_path):
        # The sharpest assertion in this file: the pre-fix report printed this
        # sentence over a file whose six declarations it had just discarded.
        _stage(tmp_path, {"flow.tcl": _UNRECOGNISED_TCL})
        a = mod._reference_flow_pnr_audit(tmp_path)
        txt = _render(tmp_path, a)
        assert _FALSE_CLAIM not in txt

    def test_report_names_the_file_and_the_floor(self, tmp_path):
        _stage(tmp_path, {"flow.tcl": _UNRECOGNISED_TCL})
        a = mod._reference_flow_pnr_audit(tmp_path)
        txt = _render(tmp_path, a)
        assert "input/reference_flow/flow.tcl" in txt
        assert "read but nothing recognised: 1" in txt
        assert "Ingest complete: **False**" in txt
        assert "NOTHING in them was recognised" in txt

    def test_make_suffixed_dialect_is_flagged_too(self, tmp_path):
        _stage(tmp_path, {"flow.mk": _UNRECOGNISED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["unrecognised_dialect"] == ["input/reference_flow/flow.mk"]
        assert a["ingest_complete"] is False
        assert _FALSE_CLAIM not in _render(tmp_path, a)

    def test_adopted_run_still_discloses_a_sibling_unrecognised_file(
            self, tmp_path):
        # The mixed case, which the status alone cannot express: knobs WERE
        # adopted from one file while another was not understood at all. The
        # verdict is an ADOPTED-family one and the disclosure must survive it,
        # because that is exactly the run whose report a reader trusts most.
        _stage(tmp_path, {"good.mk": _RECOGNISED_MK,
                          "other.tcl": _UNRECOGNISED_TCL})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "knobs-adopted-some-withheld"
        assert a["unrecognised_dialect"] == ["input/reference_flow/other.tcl"]
        assert a["ingest_complete"] is False
        txt = _render(tmp_path, a)
        assert "input/reference_flow/other.tcl" in txt
        assert "NOTHING in them was recognised" in txt


# ---------------------------------------------------------------------------
# §4.05 NEGATIVE CONTROLS — the fix must not disturb the recognised path, and a
# hostile file must not take the run down.
# ---------------------------------------------------------------------------
class TestNoLeakAndRobustness:

    def test_recognised_config_is_unaffected(self, tmp_path):
        _stage(tmp_path, {"flow.mk": _RECOGNISED_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["unrecognised_dialect"] == []
        assert a["ingest_complete"] is True
        assert a["status"] == "knobs-adopted-some-withheld"
        assert a["applied"]["repair_tns_percent"] == 100
        # #541 — the supply-class knob in the same file is withheld, and that
        # is a DECISION about the knob, not a failure to read the file: the
        # ingest is still complete and the dialect is still recognised.
        assert a["applied"]["die_target_util"] is None
        assert [w["knob"] for w in a["withheld"]] == ["CORE_UTILIZATION"]

    def test_no_config_project_is_unaffected(self, tmp_path):
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "no-config"
        assert a["unrecognised_dialect"] == []
        # No config staged => nothing to be incomplete ABOUT. A no-config
        # project must not be dragged to False by the new term.
        assert a["ingest_complete"] is True

    def test_comments_only_config_stays_no_knobs(self, tmp_path):
        # The honest-empty control. A file that genuinely declares nothing must
        # NOT be flagged, or the new signal is noise and the reader learns to
        # ignore it.
        _stage(tmp_path, {"flow.mk": "# nothing to declare here\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["unrecognised_dialect"] == []
        assert a["status"] == "no-knobs"
        assert a["ingest_complete"] is True

    def test_binary_and_hostile_content_does_not_raise(self, tmp_path):
        # A traceback is not a verdict. Each of these is a staged file with a
        # shape no parser should assume: NUL bytes, enormous single lines, and
        # a lone invalid-UTF-8 byte run.
        #
        # The UPPERCASE huge lines are the ones that matter. A lowercase giant
        # fails the name class immediately; a giant that DOES enter the name
        # group puts the trailing `(.+?)\s*$` of the assignment patterns on a
        # backtracking path, and a staged config is untrusted input. Measured
        # under 20 ms each — no timing assertion here, because a wall-clock
        # bound is a flaky test; the shapes are pinned so a future pattern
        # change that reintroduces the blowup is at least exercised.
        _stage(tmp_path, {
            "bin.mk": b"\x00\x01\x02\xff\xfe binary junk \x00\n",
            "huge_lower.tcl": "set " + ("x" * 200000) + " 1\n",
            "huge_upper.tcl": "set " + ("X" * 100000) + " " + ("v" * 100000),
            "huge_upper.mk": ("A" * 100000) + " = " + ("v" * 100000),
            "huge_trailws.tcl": "set NAME " + ("v" * 100000) + (" " * 50000),
            "weird.mk": b"\xc3\x28\xa0\xa1 = \xf0\x28\x8c\x28\n",
        })
        a = mod._reference_flow_pnr_audit(tmp_path)
        # The only requirement is that it produced a verdict at all.
        assert a["status"] in mod._RF_PNR_STATUSES
        _render(tmp_path, a)  # rendering must not raise either

    def test_every_scanned_file_lands_in_at_most_one_disclosure_bucket(
            self, tmp_path):
        # `unrecognised_dialect` must not double-count a file that is already
        # disclosed as unreadable — the buckets are a reader's map of what
        # happened to each file, and a file in two places makes the counts lie.
        _stage(tmp_path, {"good.mk": _RECOGNISED_MK,
                          "other.tcl": _UNRECOGNISED_TCL})
        a = mod._reference_flow_pnr_audit(tmp_path)
        unreadable_paths = {e.split(" (")[0] for e in a["unreadable"]}
        assert not (unreadable_paths & set(a["unrecognised_dialect"]))
        assert not (set(a["unscanned"]) & set(a["unrecognised_dialect"]))
        assert not (set(a["excluded_oracle"])
                    & set(a["unrecognised_dialect"]))
