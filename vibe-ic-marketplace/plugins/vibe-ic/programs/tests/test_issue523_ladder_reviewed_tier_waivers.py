"""#523 — a sign-off ladder tier that legitimately CANNOT run needs a reviewed
way out, and ONLY a reviewed one.

#520 made absent evidence non-releasing, which is right: a check nobody ran is
not a pass. It also made an existing gap load-bearing — the ladder had two
sources of `WAIVED`, both decided inside a tier, and no way for a reviewer to
say "this cannot run here, here is why". `T_AGING_STA` is the plain case: the
open PDK ships no foundry aging Liberty, so that tier was permanently
non-releasing for every project in the corpus.

These tests pin BOTH halves of the asymmetry the fix has to hold:

  * a DISCLOSED, reviewed capability-gap waiver defers a tier and releases;
  * silence, an incomplete attestation, a waiver aimed at a tier that RAN, and
    an attempt to reach `release_gating` from the document all fail — loudly.

They are written against the SAME fully-evidenced fixture the #520 positive
control uses, so the release they prove is a real one rather than an artefact
of a project with nothing in it. chip-AGNOSTIC throughout: every artefact is a
conventional report name carrying generic numbers.
"""
import importlib
import json

import pytest

mod = importlib.import_module("signoff_ladder_run")
_ladder = importlib.import_module("test_signoff_ladder_run")

_RATIONALE = ("the open PDK ships no foundry aging-derated Liberty, so no "
              "NBTI/PBTI/HCI corner can be characterised on this host; the "
              "deferral closes when a foundry aging library is staged")


def _entry(tier="T_AGING_STA", **over):
    """A COMPLETE, reviewable capability-gap waiver for one ladder tier."""
    entry = {
        "tier": tier,
        "verdict_tier": "ENV_UNAVAILABLE",
        "ticket": "CAPGAP-AGING-LIBERTY-1",
        "review_required": True,
        "evidence": ["reports/phase3/sta_signoff.rpt"],
        "rationale": _RATIONALE,
        "approver": "field-agent-attest (capability-gap tier)",
    }
    entry.update(over)
    return entry


def _write_waivers(project, entries, key="waivers"):
    (project / "waivers.json").write_text(
        json.dumps({"_schema_version": "1", key: list(entries)}, indent=1),
        encoding="utf-8")


def _signed_off_but_for_aging(root):
    """The #520 fully-evidenced project with the aging-STA evidence REMOVED —
    i.e. exactly the shape #523 describes: one release-gating tier that has no
    artefact, on a design that is otherwise completely signed off."""
    d = _ladder._build_fully_signed_off(root)
    (d / "reports" / "phase3" / "aging_sta.json").unlink()
    return d


def _tapeout(project, **kw):
    return mod.run_ladder(project, mode="tapeout", caravel=False, **kw)


# ---------------------------------------------------------------------------
# Fixture guards — if these stop holding, everything below stops proving
# anything.
# ---------------------------------------------------------------------------
class TestFixturePreconditions:
    def test_removing_the_aging_report_leaves_exactly_one_unrun_tier(
            self, tmp_path):
        rep = _tapeout(_signed_off_but_for_aging(tmp_path))
        assert [t.tier_id for t in mod.evidence_absent_tiers(rep.tiers)] == [
            "T_AGING_STA"]
        assert rep.overall_verdict == mod.NOT_RELEASED_EVIDENCE_ABSENT
        assert rep.released is False

    def test_the_unmodified_fixture_still_releases(self, tmp_path):
        rep = _tapeout(_ladder._build_fully_signed_off(tmp_path))
        assert rep.released is True


# ---------------------------------------------------------------------------
# The headline: disclosure buys deferral.
# ---------------------------------------------------------------------------
class TestReviewedCapabilityGapDefersATier:
    def test_a_reviewed_waiver_lets_the_aging_tier_release(self, tmp_path):
        d = _signed_off_but_for_aging(tmp_path)
        before = _tapeout(d)
        assert before.released is False

        _write_waivers(d, [_entry()])
        after = _tapeout(d)
        assert after.overall_verdict == "PASS_WITH_WAIVERS"
        assert after.released is True
        assert mod.evidence_absent_tiers(after.tiers) == []

    def test_the_deferred_tier_records_that_it_produced_nothing(self, tmp_path):
        # A honoured waiver must never read like a check that ran and passed.
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry()])
        tier = {t.tier_id: t for t in _tapeout(d).tiers}["T_AGING_STA"]
        assert tier.verdict == "WAIVED"
        assert tier.details["waiver"]["deferred_from"] == "NOT_RUN"
        assert tier.details["waiver"]["ticket"] == "CAPGAP-AGING-LIBERTY-1"
        assert tier.details["waiver"]["review_required"] is True
        assert "DEFERRED, not executed-PASS" in tier.notes

    def test_both_waiver_dialects_are_read_through_the_shared_reader(
            self, tmp_path):
        # #519 owns "where a project's waiver entries live" — the union of the
        # `waived_steps` and `waivers` keys. A ladder that read only one of
        # them would be the eighth private reader.
        for key in mod._we.WAIVER_LIST_KEYS:
            d = _signed_off_but_for_aging(tmp_path / key)
            _write_waivers(d, [_entry()], key=key)
            assert _tapeout(d).released is True, key

    def test_the_ladder_goes_THROUGH_the_shared_reader(self, tmp_path,
                                                       monkeypatch):
        # Stronger than "both keys work": redirect the shared reader and the
        # ladder must follow it. A private re-implementation would ignore this
        # and the test would fail.
        d = _signed_off_but_for_aging(tmp_path)
        assert _tapeout(d).released is False
        monkeypatch.setattr(mod._we, "read_document",
                            lambda *a, **k: {"waivers": [_entry()]})
        assert _tapeout(d).released is True

    def test_a_lowercase_tier_spelling_still_binds(self, tmp_path):
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry(tier="t_aging_sta")])
        assert _tapeout(d).released is True

    @pytest.mark.parametrize("key", ["tier", "step", "id"])
    def test_either_dialect_identity_key_may_name_the_tier(self, tmp_path,
                                                           key):
        # `tier` is the ladder-scoped spelling; `step` and `id` are the two
        # existing dialects' identity keys and bind when they literally name a
        # ladder tier. An author should not have to learn a third spelling.
        d = _signed_off_but_for_aging(tmp_path / key)
        entry = _entry()
        entry[key] = entry.pop("tier")
        _write_waivers(d, [entry])
        assert _tapeout(d).released is True, key

    def test_waived_steps_takes_precedence_over_waivers(self, tmp_path):
        # `_waiver_entries` documents the order — `waived_steps` first — so a
        # consumer that stops at the first match keeps the precedence the
        # majority of call sites already had. Pin it here rather than assume.
        d = _signed_off_but_for_aging(tmp_path)
        (d / "waivers.json").write_text(json.dumps({
            "waived_steps": [_entry(ticket="FROM-WAIVED-STEPS")],
            "waivers": [_entry(ticket="FROM-WAIVERS")]}), encoding="utf-8")
        tier = {t.tier_id: t for t in _tapeout(d).tiers}["T_AGING_STA"]
        assert tier.details["waiver"]["ticket"] == "FROM-WAIVED-STEPS"


# ---------------------------------------------------------------------------
# #520's constraint: WAIVED and NOT_RUN must stay opposite.
# ---------------------------------------------------------------------------
class TestWaivedStaysDistinctFromUnrun:
    def test_reviewed_waiver_releases_but_the_same_tier_unrun_does_not(
            self, tmp_path):
        # Same project, same tier, same neighbours — the ONLY difference is
        # whether somebody made and documented a decision.
        unrun = _signed_off_but_for_aging(tmp_path / "unrun")
        waived = _signed_off_but_for_aging(tmp_path / "waived")
        _write_waivers(waived, [_entry()])

        a, b = _tapeout(unrun), _tapeout(waived)
        assert a.overall_verdict == mod.NOT_RELEASED_EVIDENCE_ABSENT
        assert a.released is False
        assert b.overall_verdict == "PASS_WITH_WAIVERS"
        assert b.released is True
        assert a.overall_verdict != b.overall_verdict

    def test_a_waiver_on_one_tier_cannot_release_a_tier_nobody_ran(
            self, tmp_path):
        # Waive the aging tier, then take away a DIFFERENT tier's evidence.
        # The waiver must buy exactly what it names and nothing else.
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry()])
        assert _tapeout(d).released is True

        (d / "reports" / "phase3" / "lec_post_layout.json").unlink()
        rep = _tapeout(d)
        assert rep.overall_verdict == mod.NOT_RELEASED_EVIDENCE_ABSENT
        assert rep.released is False
        assert [t.tier_id for t in mod.evidence_absent_tiers(rep.tiers)] == [
            "T_LEC_POST"]

    def test_a_waived_tier_leaves_the_absent_evidence_list(self, tmp_path):
        d = _signed_off_but_for_aging(tmp_path)
        assert "T_AGING_STA" in _tapeout(d).as_dict()["evidence_absent_tiers"]
        _write_waivers(d, [_entry()])
        after = _tapeout(d).as_dict()
        assert after["evidence_absent_tiers"] == []
        assert [w["tier_id"] for w in after["waived_tiers"]] == ["T_AGING_STA"]


# ---------------------------------------------------------------------------
# No project may waive its own gating. Every refusal is reported.
# ---------------------------------------------------------------------------
class TestNoSelfWaiverWithoutReview:
    @pytest.mark.parametrize("missing,marker", [
        ({"ticket": ""}, "`ticket`"),
        ({"ticket": None}, "`ticket`"),
        ({"review_required": False}, "`review_required: true`"),
        ({"review_required": "yes"}, "`review_required: true`"),
        ({"evidence": []}, "`evidence` list"),
        ({"evidence": "reports/x.json"}, "`evidence` list"),
        ({"rationale": "no aging lib"}, "`rationale`"),
        ({"rationale": "", "reason": ""}, "`rationale`"),
        ({"verdict_tier": "WAIVED"}, "ENV_UNAVAILABLE"),
        ({"verdict_tier": None}, "ENV_UNAVAILABLE"),
    ])
    def test_an_incomplete_attestation_is_refused_and_named(
            self, tmp_path, missing, marker):
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry(**missing)])
        rep = _tapeout(d)
        assert rep.released is False
        assert rep.overall_verdict == mod.NOT_RELEASED_EVIDENCE_ABSENT
        assert mod.waived_tiers(rep.tiers) == []
        assert any(marker in line for line in rep.waiver_disclosures), \
            rep.waiver_disclosures

    def test_a_bare_self_written_waiver_buys_nothing(self, tmp_path):
        # The shape a project would reach for if it wanted its own gates off.
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [{"tier": "T_AGING_STA", "reason": "not needed"}])
        rep = _tapeout(d)
        assert rep.released is False
        assert rep.waiver_disclosures  # never silent

    def test_release_gating_cannot_be_reached_from_the_document(self, tmp_path):
        # `release_gating` is set in code so no project can opt its own gates
        # out. A waiver entry carrying it must change nothing at all.
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [{"tier": "T_AGING_STA", "release_gating": False}])
        rep = _tapeout(d)
        tier = {t.tier_id: t for t in rep.tiers}["T_AGING_STA"]
        assert tier.release_gating is True
        assert tier.verdict == "NOT_RUN"
        assert rep.released is False

    def test_release_gating_stays_true_even_on_an_honoured_waiver(
            self, tmp_path):
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry(release_gating=False)])
        tier = {t.tier_id: t for t in _tapeout(d).tiers}["T_AGING_STA"]
        assert tier.verdict == "WAIVED"
        assert tier.release_gating is True

    def test_a_rationale_must_be_substantive_not_merely_present(self, tmp_path):
        d = _signed_off_but_for_aging(tmp_path)
        short = "x" * (mod.TIER_WAIVER_MIN_RATIONALE_CHARS - 1)
        _write_waivers(d, [_entry(rationale=short)])
        assert _tapeout(d).released is False
        _write_waivers(d, [_entry(rationale="y" * (
            mod.TIER_WAIVER_MIN_RATIONALE_CHARS))])
        assert _tapeout(d).released is True

    def test_reason_is_accepted_where_rationale_is_written(self, tmp_path):
        # Waiver authors use the two keys interchangeably; a consumer reading
        # only one of them rejects a valid entry for a spelling.
        d = _signed_off_but_for_aging(tmp_path)
        entry = _entry()
        entry["reason"] = entry.pop("rationale")
        _write_waivers(d, [entry])
        assert _tapeout(d).released is True


# ---------------------------------------------------------------------------
# A waiver defers a check that could not run — it never overwrites one that did.
# ---------------------------------------------------------------------------
class TestAWaiverNeverOverwritesAResult:
    def test_a_waiver_cannot_convert_a_real_FAIL(self, tmp_path):
        d = _ladder._build_fully_signed_off(tmp_path)
        _ladder._write_json(d / "reports/phase3/tapcell_density.json",
                            {"tapcells_per_mm2": 1, "area_mm2": 1.0})
        assert _tapeout(d).overall_verdict == "FAIL"

        _write_waivers(d, [_entry(tier="T5_LATCHUP")])
        rep = _tapeout(d)
        assert rep.overall_verdict == "FAIL"
        assert rep.released is False
        assert mod.waived_tiers(rep.tiers) == []
        assert any("RAN and reported FAIL" in x
                   for x in rep.waiver_disclosures), rep.waiver_disclosures

    def test_a_waiver_on_a_passing_tier_is_refused_too(self, tmp_path):
        # Not harmful, but it would relabel a real pass as a waiver — the
        # report would understate what was actually proven.
        d = _ladder._build_fully_signed_off(tmp_path)
        _write_waivers(d, [_entry(tier="T1")])
        rep = _tapeout(d)
        assert rep.overall_verdict == "PASS"
        assert mod.waived_tiers(rep.tiers) == []
        assert any("RAN and reported PASS" in x
                   for x in rep.waiver_disclosures)

    def test_a_waiver_cannot_rescue_a_waived_pending_lvs(self, tmp_path):
        # WAIVED_PENDING is a documented, evidenced, NON-releasing triage
        # waiver. A capability-gap deferral is not the right instrument for it
        # and must not release it.
        d = _ladder._build_fully_signed_off(tmp_path)
        _ladder._write(d / "reports/phase3/lvs.rpt",
                       _ladder._LVS_POWER_PIN_ONLY)
        assert _tapeout(d).overall_verdict == "NOT_RELEASED"

        _write_waivers(d, [_entry(tier="T4.5_LVS_TAPEOUT")])
        rep = _tapeout(d)
        assert rep.overall_verdict == "NOT_RELEASED"
        assert rep.released is False

    def test_a_refused_entry_does_not_consume_the_tier(self, tmp_path):
        # A malformed first entry must not block a complete second one — the
        # tier is only spent when a waiver is actually honoured.
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry(ticket=""), _entry(ticket="SECOND")])
        rep = _tapeout(d)
        assert rep.released is True
        tier = {t.tier_id: t for t in rep.tiers}["T_AGING_STA"]
        assert tier.details["waiver"]["ticket"] == "SECOND"

    def test_the_same_waiver_applied_twice_defers_once(self, tmp_path):
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry(), _entry(ticket="SECOND")])
        rep = _tapeout(d)
        assert [t.tier_id for t in mod.waived_tiers(rep.tiers)] == [
            "T_AGING_STA"]
        assert any("already deferred" in x for x in rep.waiver_disclosures)
        # first entry wins, deterministically
        tier = {t.tier_id: t for t in rep.tiers}["T_AGING_STA"]
        assert tier.details["waiver"]["ticket"] == "CAPGAP-AGING-LIBERTY-1"


# ---------------------------------------------------------------------------
# Addressing: a flow-step waiver answers a different question.
# ---------------------------------------------------------------------------
class TestOnlyLadderAddressedEntriesParticipate:
    def test_an_ordinary_flow_step_waiver_is_neither_honoured_nor_flagged(
            self, tmp_path):
        # The shape every tracked project already carries. Honouring it would
        # spend a review of "did flow step 39 run" on a tapeout sign-off tier;
        # flagging it would be a category error. It is left alone.
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [{
            "id": 39, "verdict_tier": "ENV_UNAVAILABLE", "ticket": "T-1",
            "review_required": True, "evidence": ["reports/x.json"],
            "reason": _RATIONALE}], key="waived_steps")
        rep = _tapeout(d)
        assert rep.released is False
        assert mod.waived_tiers(rep.tiers) == []
        assert rep.waiver_disclosures == []

    def test_a_step_role_name_waiver_never_reaches_a_ladder_tier(self,
                                                                 tmp_path):
        # A `step: "drc"` waiver in the corpus is a reviewed judgement about a
        # DRC RESULT. It must not be spent on a sign-off tier.
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [{
            "step": "drc", "verdict_tier": "ENV_UNAVAILABLE", "ticket": "T-1",
            "review_required": True, "evidence": ["reports/x.json"],
            "rationale": _RATIONALE}])
        rep = _tapeout(d)
        assert mod.waived_tiers(rep.tiers) == []
        assert rep.waiver_disclosures == []

    def test_a_misspelt_tier_is_reported_not_silently_dropped(self, tmp_path):
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry(tier="T_AGING_ST")])
        rep = _tapeout(d)
        assert rep.released is False
        assert any("not a tier this ladder runs" in x
                   for x in rep.waiver_disclosures), rep.waiver_disclosures

    def test_a_tier_this_mode_does_not_run_says_so(self, tmp_path):
        # Not malformed — just aimed at a tier the diagnostic ladder never
        # reaches. The two mistakes have different fixes and must read
        # differently.
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry()])
        rep = mod.run_ladder(d, mode="triage")
        assert any("does not include" in x for x in rep.waiver_disclosures)
        assert rep.released is False

    def test_the_advisory_tier_cannot_be_deferred(self, tmp_path):
        # Its absence never withheld a release, so a waiver buys nothing and
        # would only demote a clean PASS to PASS_WITH_WAIVERS.
        d = _ladder._build_fully_signed_off(tmp_path)
        (d / "reports" / "drc" / "geographic_heatmap.json").unlink()
        _write_waivers(d, [_entry(tier="T1.5")])
        rep = _tapeout(d)
        assert rep.overall_verdict == "PASS"
        assert mod.waived_tiers(rep.tiers) == []
        assert any("ADVISORY" in x for x in rep.waiver_disclosures)

    def test_ladder_tier_ids_cover_every_tier_the_ladder_emits(self, tmp_path):
        # Derived by RUNNING both modes with the shuttle tiers on, so a new
        # tier cannot drift out of the constant the disclosure text uses to
        # tell "unknown tier" from "tier this mode does not run".
        emitted = set()
        for mode, caravel in (("triage", False), ("tapeout", False),
                              ("tapeout", True)):
            rep = mod.run_ladder(tmp_path, mode=mode, caravel=caravel)
            emitted.update(t.tier_id for t in rep.tiers)
        assert emitted == set(mod.LADDER_TIER_IDS)


# ---------------------------------------------------------------------------
# Paperwork over an empty ladder is still not a sign-off.
#
# Found by sweeping the corpus rather than by reading the issue: 85 of the 104
# projects have EVERY release-gating tier NOT_RUN. Waiving each one is
# individually legitimate — reviewed, ticketed, evidenced — and the sum of them
# would have released a design on which not one sign-off check ever ran. That is
# the claim #520 refused, re-entered through the front door with paperwork.
# ---------------------------------------------------------------------------
class TestAReleaseMustRestOnSomethingExecuted:
    def test_waiving_every_gate_of_an_empty_project_does_not_release(
            self, tmp_path):
        empty = tmp_path / "nothing_ran"
        empty.mkdir()
        rep = _tapeout(empty)
        assert rep.overall_verdict == mod.NOT_RELEASED_EVIDENCE_ABSENT
        gating = [t.tier_id for t in mod.evidence_absent_tiers(rep.tiers)]
        assert len(gating) > 5

        _write_waivers(empty, [_entry(tier=t, evidence=["waivers.json"])
                               for t in gating])
        after = _tapeout(empty)
        assert mod.evidence_absent_tiers(after.tiers) == []
        assert len(mod.waived_tiers(after.tiers)) == len(gating)
        assert after.overall_verdict == mod.NOT_RELEASED_ALL_WAIVED
        assert after.released is False
        assert mod.NOT_RELEASED_ALL_WAIVED not in mod.RELEASING_VERDICTS

    def test_one_executed_gate_is_enough_to_carry_the_others(self, tmp_path):
        # The guard must not block the case the issue is actually about: a
        # design that really was signed off, with one reviewable gap.
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry()])
        rep = _tapeout(d)
        assert mod.executed_signoff_tiers(rep.tiers)
        assert rep.overall_verdict == "PASS_WITH_WAIVERS"
        assert rep.released is True

    def test_an_advisory_pass_does_not_count_as_executed_sign_off(self):
        # T1.5 is the heatmap picture. Drawing it is not evidence, so it must
        # not be the single PASS that lets every real gate be deferred.
        tiers = [mod.TierResult("T1.5", "heatmap", "PASS",
                                release_gating=False),
                 mod.TierResult("T1", "DRC", "WAIVED")]
        assert mod.executed_signoff_tiers(tiers) == []
        assert mod.aggregate_verdict(tiers) == mod.NOT_RELEASED_ALL_WAIVED

    def test_an_NA_tier_does_not_count_as_executed_sign_off(self):
        # A RAM-less MBIST N/A is neutral, not proof anything was checked.
        tiers = [mod.TierResult("T_MBIST", "MBIST", "N/A"),
                 mod.TierResult("T1", "DRC", "WAIVED")]
        assert mod.aggregate_verdict(tiers) == mod.NOT_RELEASED_ALL_WAIVED

    def test_the_note_says_the_ladder_ran_no_signoff(self):
        rep = mod.LadderReport(
            project_dir="p",
            tiers=[mod.TierResult("T1", "DRC", "WAIVED")],
            overall_verdict=mod.NOT_RELEASED_ALL_WAIVED, mode="tapeout")
        assert "no sign-off" in rep.release_note()
        assert rep.released is False


# ---------------------------------------------------------------------------
# #524 — evidence is classified and disclosed, never demanded.
# ---------------------------------------------------------------------------
class TestEvidenceIsDisclosedNotDemanded:
    def test_a_self_referential_attestation_is_honoured_and_disclosed(
            self, tmp_path):
        # An ENV_UNAVAILABLE claim is uncorroborated BY CONSTRUCTION: no
        # independent artefact can corroborate a non-execution. Refusing it
        # would break "disclosure buys deferral" for the whole population.
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry(evidence=[
            "reports/orchestrator/phase3_one_shot.json#steps[name=aging]"])])
        rep = _tapeout(d)
        assert rep.released is True
        assert any("HONOURED but UNCORROBORATED" in x
                   for x in rep.waiver_disclosures)
        tier = {t.tier_id: t for t in rep.tiers}["T_AGING_STA"]
        assert tier.details["waiver"]["evidence_assessment"][
            "self_referential_only"] is True

    def test_a_corroborated_attestation_raises_no_advisory(self, tmp_path):
        # `reports/phase3/sta_signoff.rpt` exists in the fixture and is not the
        # run's own record — an independent item.
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry()])
        rep = _tapeout(d)
        assert rep.released is True
        assert rep.waiver_disclosures == []
        tier = {t.tier_id: t for t in rep.tiers}["T_AGING_STA"]
        assert tier.details["waiver"]["evidence_assessment"][
            "corroborated"] is True

    def test_free_text_evidence_is_honoured_but_never_counts_as_corroboration(
            self, tmp_path):
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry(evidence=["no foundry aging Liberty ships "
                                            "with this open PDK"])])
        rep = _tapeout(d)
        assert rep.released is True
        assert any("UNCORROBORATED" in x for x in rep.waiver_disclosures)


# ---------------------------------------------------------------------------
# Report what a waiver bought.
# ---------------------------------------------------------------------------
class TestTheReportNamesWhatAWaiverBought:
    def test_json_names_every_waived_tier_and_what_bought_it(self, tmp_path):
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry()])
        rows = _tapeout(d).as_dict()["waived_tiers"]
        assert [r["tier_id"] for r in rows] == ["T_AGING_STA"]
        assert rows[0]["ticket"] == "CAPGAP-AGING-LIBERTY-1"
        assert "ENV_UNAVAILABLE" in rows[0]["basis"]
        assert rows[0]["deferred_from"] == "NOT_RUN"

    def test_a_tier_internal_waiver_is_named_and_told_apart(self, tmp_path):
        # The XOR allow-list waiver is a decision made INSIDE a tier. It must
        # be named too, and must not read like a reviewed capability gap.
        d = _ladder._add_shuttle_documented_waiver(
            _ladder._build_fully_signed_off(tmp_path))
        rep = mod.run_ladder(d, mode="tapeout", caravel=True)
        rows = rep.as_dict()["waived_tiers"]
        assert [r["tier_id"] for r in rows] == ["T_XOR"]
        assert "tier-internal" in rows[0]["basis"]
        assert rows[0]["ticket"] is None

    def test_the_release_note_names_the_tiers_it_rests_on(self, tmp_path):
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry()])
        rep = _tapeout(d)
        assert rep.released is True
        assert "T_AGING_STA" in rep.release_note()
        assert "carried by a waiver" in rep.release_note()

    def test_markdown_names_the_waived_tiers_and_the_disclosures(self,
                                                                 tmp_path):
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry(), _entry(tier="T_NOPE")])
        md = mod.report_to_markdown(_tapeout(d))
        assert "carried by a WAIVER" in md
        assert "T_AGING_STA" in md
        assert "CAPGAP-AGING-LIBERTY-1" in md
        assert "Waiver disclosures" in md
        assert "T_NOPE" in md

    def test_a_ladder_with_no_waivers_says_nothing_about_waivers(self,
                                                                 tmp_path):
        md = mod.report_to_markdown(
            _tapeout(_ladder._build_fully_signed_off(tmp_path)))
        assert "carried by a WAIVER" not in md
        assert "Waiver disclosures" not in md


# ---------------------------------------------------------------------------
# The CLI's exit code must follow the flag it prints.
# ---------------------------------------------------------------------------
class TestStrictFollowsAWaivedRelease:
    def _cli(self, argv):
        import sys
        old = sys.argv
        sys.argv = ["signoff_ladder_run.py"] + argv
        try:
            return mod._cli()
        finally:
            sys.argv = old

    def test_strict_exits_zero_only_once_the_gap_is_reviewed(self, tmp_path,
                                                             capsys):
        d = _signed_off_but_for_aging(tmp_path)
        assert self._cli([str(d), "--mode", "tapeout", "--no-caravel",
                          "--strict"]) == 1
        capsys.readouterr()
        _write_waivers(d, [_entry()])
        assert self._cli([str(d), "--mode", "tapeout", "--no-caravel",
                          "--strict"]) == 0
        capsys.readouterr()

    def test_the_emitted_json_carries_the_waiver_record(self, tmp_path,
                                                        capsys):
        d = _signed_off_but_for_aging(tmp_path)
        _write_waivers(d, [_entry()])
        out = tmp_path / "ladder.json"
        rc = self._cli([str(d), "--mode", "tapeout", "--no-caravel",
                        "--out-json", str(out)])
        capsys.readouterr()
        assert rc == 0
        doc = json.loads(out.read_text())
        assert doc["released"] is True
        assert [w["tier_id"] for w in doc["waived_tiers"]] == ["T_AGING_STA"]
        assert doc["waiver_disclosures"] == []


# ---------------------------------------------------------------------------
# A malformed waiver document must never take the ladder down.
# ---------------------------------------------------------------------------
class TestMalformedDocumentsFailSafe:
    @pytest.mark.parametrize("text", [
        "{ not json",
        "[]",
        '{"waivers": "not-a-list"}',
        '{"waivers": [null, 3, "string"]}',
        '{"waived_steps": [{"tier": {"nested": true}}]}',
        '{"waivers": [{"tier": ["T_AGING_STA"]}]}',
        "null",
    ])
    def test_a_broken_document_leaves_the_verdict_where_it_was(self, tmp_path,
                                                               text):
        d = _signed_off_but_for_aging(tmp_path)
        (d / "waivers.json").write_text(text, encoding="utf-8")
        rep = _tapeout(d)
        assert rep.overall_verdict == mod.NOT_RELEASED_EVIDENCE_ABSENT
        assert rep.released is False

    def test_an_absent_waivers_file_is_not_an_error(self, tmp_path):
        d = _signed_off_but_for_aging(tmp_path)
        assert not (d / "waivers.json").exists()
        assert _tapeout(d).waiver_disclosures == []
