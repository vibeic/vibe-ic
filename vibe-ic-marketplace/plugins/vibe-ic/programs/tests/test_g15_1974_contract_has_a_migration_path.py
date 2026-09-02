#!/usr/bin/env python3
"""G15 — #1974's completion contract shipped without a migration path, so a
manifest written before it was relabelled FAIL for its spelling.

`2a9d21368d` (#1974) added the Step-5 COMPLETION contract to
`formal_proof_evidence_check.audit()` and migrated the EMITTER in the same
commit. It migrated nothing that had already been WRITTEN. Measured at the live
tip `871270067a` (v1.15.94) with the corpus materialised, all four published
cells carrying a `formal/` audited FAIL on four findings each.

Three of the four were the gate reading a NAME. `formal_property_run.
_attach_property_contract` ends::

    results["elaborated_sby"]             = results.get("sby")
    results["proof_transcript"]           = results.get("evidence")
    results["bounded_vs_unbounded_scope"] = list(bounded_vs_unbounded)

— unconditional aliases. A manifest that states the fact once, under the older
name, has stated it, and the gate's own docstring words those three obligations
as AGREEMENT ("`elaborated_sby` agreeing with `sby`"). That is the defect.

The fourth is not a defect and is deliberately left alone.
`property_denominator` is read from the harness and the obligation contract and
has no predecessor field (`property_count` is the .sby TASK count). A gate
cannot READ a denominator that was never written; a grandfather clause could
only ASSUME one, which invents a measurement. "Proof evidence without a
denominator is a claim about a subset nobody stated" is a fact about the
manifest, not about its date, so it keeps deciding the verdict for old cells.

The negative arm below is the whole point: the contract must still bite for
everything it bit before, and a fix that reached green by no longer reading the
contract would take #1974 with it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import corpus_guard as CG  # noqa: E402
import formal_proof_evidence_check as FPC  # noqa: E402

_SBY_PASS_LOG = """\
SBY 12:00:00 [t] engine_0: starting process "smtbmc yices"
SBY 12:00:09 [t] summary: Elapsed clock time [H:MM:SS (secs)]: 0:00:09
SBY 12:00:09 [t] DONE (PASS, rc=0)
"""
_SBY_REL = "phase2/stage1/formal/c.sby"
_LOG_REL = "phase2/stage1/formal/c.sby.log"


def _cell(tmp_path, results: dict) -> Path:
    f = tmp_path / "phase2" / "stage1" / "formal"
    f.mkdir(parents=True)
    (f / "a.sv").write_text("module a; assert property (1); endmodule\n")
    (f / "c.sby").write_text("[script]\nread -formal a.sv\nprep -top a\n")
    (f / "c.sby.log").write_text(_SBY_PASS_LOG)
    (f / "results.json").write_text(json.dumps(results))
    return tmp_path


def _pre_1974(**over) -> dict:
    """The shape every cell published before `2a9d21368d` carries."""
    base = {"program": "formal_property_run", "verdict": "PASS",
            "all_proved": True, "property_count": 2, "proved": 2, "failed": 0,
            "bounded_vs_unbounded": ["property PROVED UNBOUNDED: safety"],
            "sby": _SBY_REL, "evidence": _LOG_REL}
    base.update(over)
    return base


def _tags(rep, only_1974=True):
    return sorted(f.split(" ")[0] for f in rep["findings"]
                  if not only_1974 or "#1974" in f)


# --- the defect ------------------------------------------------------------

def test_a_pre_contract_manifest_is_not_failed_for_its_spelling(tmp_path):
    """THE DEFECT. Three obligations cited under the pre-#1974 name were
    reported as not cited at all. RED before the fix (three findings), green
    after (none of the three)."""
    rep = FPC.audit(_cell(tmp_path, _pre_1974()))
    assert "PROOF_SCOPE_MISSING" not in _tags(rep), rep["findings"]
    assert "ELABORATED_SBY_MISSING" not in _tags(rep), rep["findings"]
    assert "PROOF_TRANSCRIPT_MISSING" not in _tags(rep), rep["findings"]


def test_the_denominator_is_the_only_thing_such_a_manifest_still_lacks(tmp_path):
    """Its paired half: the fix is scoped to the aliases and nothing else."""
    rep = FPC.audit(_cell(tmp_path, _pre_1974()))
    assert _tags(rep) == ["PROPERTY_DENOMINATOR_MISSING"], rep["findings"]
    assert rep["verdict"] == "FAIL" and rep["rc"] == 1, rep


def test_a_pre_contract_manifest_that_also_states_a_denominator_passes(tmp_path):
    """The alias reading is complete, not partial: once the ONE fact no older
    field carried is supplied, an otherwise pre-#1974 manifest satisfies (d)
    without being rewritten into #1974's spelling."""
    rep = FPC.audit(_cell(tmp_path, _pre_1974(
        property_denominator=1, authored_property_count=1,
        unresolved_obligations=[])))
    assert rep["verdict"] == "PASS" and rep["rc"] == 0, rep["findings"]


# --- the negative arm: the contract must still bite ------------------------

def test_a_manifest_citing_a_DIFFERENT_elaborated_sby_still_fails(tmp_path):
    """Absence is not disagreement — but disagreement still is. A manifest
    naming two different .sby tasks is making two claims, and (d) refuses it
    exactly as it did before."""
    rep = FPC.audit(_cell(tmp_path, _pre_1974(
        property_denominator=1, authored_property_count=1,
        elaborated_sby="phase2/stage1/formal/other.sby")))
    assert rep["verdict"] == "FAIL", rep["findings"]
    assert "ELABORATED_SBY_MISSING" in _tags(rep), rep["findings"]


def test_a_manifest_citing_a_DIFFERENT_transcript_still_fails(tmp_path):
    rep = FPC.audit(_cell(tmp_path, _pre_1974(
        property_denominator=1, authored_property_count=1,
        proof_transcript="phase2/stage1/formal/other.log")))
    assert rep["verdict"] == "FAIL", rep["findings"]
    assert "PROOF_TRANSCRIPT_MISSING" in _tags(rep), rep["findings"]


def test_a_manifest_stating_no_scope_under_either_name_still_fails(tmp_path):
    """The alias is a second NAME for a fact, never a substitute for it. This
    is subservient's real shape: it declares bounded/unbounded scope under
    neither name, and must keep failing."""
    m = _pre_1974(property_denominator=1, authored_property_count=1)
    del m["bounded_vs_unbounded"]
    rep = FPC.audit(_cell(tmp_path, m))
    assert rep["verdict"] == "FAIL", rep["findings"]
    assert "PROOF_SCOPE_MISSING" in _tags(rep), rep["findings"]


def test_an_empty_scope_list_is_not_a_stated_scope(tmp_path):
    rep = FPC.audit(_cell(tmp_path, _pre_1974(
        property_denominator=1, authored_property_count=1,
        bounded_vs_unbounded=[])))
    assert "PROOF_SCOPE_MISSING" in _tags(rep), rep["findings"]


def test_a_post_contract_cell_omitting_the_denominator_still_fails(tmp_path):
    """The arm that must be run in both directions. A cell produced AFTER
    #1974 that genuinely omits `property_denominator` FAILs — a fix reaching
    green by no longer reading the contract is the defect with the sign
    flipped, and would take #1974 with it. Mirrors
    `test_v0_2_80_formal_evidence_chain.py::
    test_completed_claim_without_property_denominator_fails`."""
    rep = FPC.audit(_cell(tmp_path, {
        "all_proved": True,
        "bounded_vs_unbounded_scope": ["unbounded prove"],
        "sby": _SBY_REL, "elaborated_sby": _SBY_REL,
        "evidence": _LOG_REL, "proof_transcript": _LOG_REL}))
    assert rep["verdict"] == "FAIL" and rep["rc"] == 1, rep
    assert "PROPERTY_DENOMINATOR_MISSING" in _tags(rep), rep["findings"]


def test_an_open_denominator_still_fails_after_the_alias_fix(tmp_path):
    """`authored < denominator` is the other half of the denominator clause
    and the aliases must not reach it."""
    rep = FPC.audit(_cell(tmp_path, _pre_1974(
        property_denominator=4, authored_property_count=1)))
    assert rep["verdict"] == "FAIL", rep["findings"]
    assert "PROPERTY_DENOMINATOR_OPEN" in _tags(rep), rep["findings"]


# --- the second control: a corpus guard that skipped must be able to shout --

def test_a_corpus_guard_skips_quietly_when_nothing_declared_a_corpus(tmp_path):
    """The default has to stay quiet: an ordinary clean checkout genuinely has
    no corpus since #2019 and must not go red for it."""
    with pytest.raises(BaseException) as ei:
        CG.require_corpus(tmp_path / "absent", "x", env={})
    assert ei.typename == "Skipped", ei.typename


def test_a_corpus_guard_that_skipped_under_a_declaration_FAILS(tmp_path):
    """THE SECOND DEFECT, and why G15 was found two campaigns late: a guard
    that skipped cannot be told apart from a guard that ran and agreed. Under
    either declaration the skip becomes a failure that names what went
    unmeasured."""
    for env in ({CG.REQUIRE_ENV: "1"}, {CG.CORPUS_ENV: str(tmp_path)}):
        with pytest.raises(BaseException) as ei:
            CG.require_corpus(tmp_path / "absent", "the published verdicts",
                              env=env)
        assert ei.typename == "Failed", (env, ei.typename)
        assert "CORPUS_GUARD_SKIPPED" in str(ei.value)
        assert "the published verdicts" in str(ei.value)


def test_a_present_corpus_is_returned_not_skipped(tmp_path):
    got = CG.require_corpus(tmp_path, "x", env={CG.REQUIRE_ENV: "1"})
    assert got == tmp_path


def test_falsey_declarations_do_not_arm_the_guard():
    for value in ("", "0", "false", "no", "off"):
        assert CG.armed({CG.REQUIRE_ENV: value}) is None, value
    assert CG.armed({}) is None
    assert CG.armed({CG.REQUIRE_ENV: "1"}) == CG.REQUIRE_ENV


def test_the_pointer_outranks_the_in_tree_path_for_the_root():
    """Matches `benchmark_evidence_structure_check`'s documented precedence —
    the pointer wins — so a guard reads the corpus the run pointed at."""
    assert CG.corpus_root(_PROGRAMS, env={CG.CORPUS_ENV: "/x/y"}) == Path("/x/y")
    assert CG.corpus_root(_PROGRAMS, env={}).name == "ic"
