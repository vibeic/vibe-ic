#!/usr/bin/env python3
"""ORGANIC #312 STRUCTURAL — the Phase-1 dual track has only one track.

Verified, not assumed:
  * `ai_deep_review_patches.json` has THREE readers and ZERO writers.
  * `phase1_doc_one_shot_runner` has no expert-track call site.
  * `ic_expert_backup_pack` — the module that assembles exactly this hand-off,
    carrying a measured A/B result (38->31 folded, 51 as independent authors) —
    is referenced by nothing but INDEX.md and its own test.

So `ai_captured_tokens_count: 0` cannot mean anything else. A real report read
`tokens_missing_everywhere: 52, ai_captured_tokens_count: 0`, which LOOKS like
the AI track performed badly and MEANS the AI track never ran.

That framing is the bug, and it is this campaign's recurring one in a new
place: an EMPTY result and a CLEAN result are indistinguishable at the verdict
(#300 empty CTS vs clean CTS; #306 gates that FAIL but cannot block).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase1_expert_track_evidence_check as E  # noqa: E402


def _proj(tmp_path, sidecar=None, raw=None):
    (tmp_path / "phase1").mkdir(parents=True, exist_ok=True)
    if raw is not None:
        (tmp_path / "phase1" / "ai_deep_review_patches.json").write_text(raw)
    elif sidecar is not None:
        (tmp_path / "phase1" / "ai_deep_review_patches.json").write_text(
            json.dumps(sidecar))
    return tmp_path


def test_312_never_ran_and_ran_empty_are_distinguishable(tmp_path):
    """THE FIX. Both have patch_count 0; only the STATE separates 'not
    measured' from 'measured, nothing there'. Reporting them identically is
    what made a dead track look like a well-behaved one."""
    never = E.assess(_proj(tmp_path / "n"), _PROGRAMS)
    empty = E.assess(_proj(tmp_path / "e", sidecar={"patches": {}}), _PROGRAMS)
    assert never["patch_count"] == empty["patch_count"] == 0
    assert never["state"] == "NEVER_RAN"
    assert empty["state"] == "RAN_EMPTY"
    assert never["state"] != empty["state"]


def test_312_ran_reports_the_patches(tmp_path):
    rep = E.assess(_proj(tmp_path, sidecar={"patches": {
        "L21_POWER_INTENT": [{"field": "power_rails"}],
        "L1_DATASHEET": [{"field": "x"}, {"field": "y"}]}}), _PROGRAMS)
    assert rep["state"] == "RAN"
    assert rep["patch_count"] == 3
    assert rep["layers"] == ["L1_DATASHEET", "L21_POWER_INTENT"]


def test_312_malformed_is_not_counted_as_ran(tmp_path):
    """Unreadable evidence is not evidence — it must not read as a track that
    ran, which would hide the missing track behind a parse error."""
    for raw in ("{not json", json.dumps({"no_patches_key": 1}),
                json.dumps({"patches": "not a mapping"})):
        rep = E.assess(_proj(tmp_path / str(abs(hash(raw))), raw=raw), _PROGRAMS)
        assert rep["state"] == "MALFORMED", raw[:20]
        assert rep["patch_count"] == 0


def test_312_wired_detection_separates_two_different_zeros(tmp_path):
    """`wired` is what tells 'the track does not exist' apart from 'the track
    exists, this design has no patches'. Without it NEVER_RAN would also fire
    on a design whose sidecar was merely absent."""
    fake = tmp_path / "programs"
    fake.mkdir()
    (fake / "phase1_doc_one_shot_runner.py").write_text("# no handoff here\n")
    assert E.expert_track_wired(fake) is False
    (fake / "phase1_one_shot_runner.py").write_text(
        "import ic_expert_backup_pack as _p\n")
    assert E.expert_track_wired(fake) is True


def test_312_the_track_is_now_wired(tmp_path):
    """UPDATED DELIBERATELY. This test previously asserted the defect was still
    present — `expert_track_wired(_PROGRAMS) is False` — and carried the note
    "when the expert track is finally wired, this test fails and must be
    updated". It has been: `phase1_one_shot_runner` now invokes
    `phase1_expert_parse_track`, which imports the hand-off module, in both
    input modes.

    The assertion is inverted rather than deleted, so it stays non-vacuous in
    the other direction: if the wiring is ever removed, this fails."""
    assert E.expert_track_wired(_PROGRAMS) is True, (
        "the Phase-1 expert track is no longer wired — #312 has regressed")

    # A project the track has not run on is still NEVER_RAN. `wired` is what
    # keeps the two zeros apart, and it now reads True.
    rep = E.assess(_proj(tmp_path), _PROGRAMS)
    assert rep["state"] == "NEVER_RAN" and rep["wired"] is True
    assert "did not reach it" in rep["detail"]


def test_312_the_track_report_is_execution_evidence(tmp_path):
    """The track deliberately does NOT write the sidecar — the gates that read
    the sidecar merge it into the haystack they then measure, so a track
    writing there would supply its own score. Its own report is therefore the
    honest evidence of execution, and reading only the sidecar would report
    NEVER_RAN for a track that demonstrably ran."""
    proj = _proj(tmp_path)
    rpt = proj / "reports" / "phase1" / "expert_parse_track.json"
    rpt.parent.mkdir(parents=True, exist_ok=True)

    # A report proves the PROGRAM ran, but #1973 separates that from the IC
    # Expert having answered. Handoff creation / skipped review is incomplete.
    rpt.write_text(json.dumps({
        "verdict": "INCOMPLETE", "findings": [],
        "ai_subtrack": {"status": "HANDOFF_EMITTED"},
        "ai_convergence": {"consumed": 0}}))
    incomplete = E.assess(proj, _PROGRAMS)
    assert incomplete["state"] == "INCOMPLETE"
    assert incomplete["ai_subtrack"] == "HANDOFF_EMITTED"

    # A consumed, non-empty review can genuinely agree with every generated
    # layer. That is the real-zero RAN_EMPTY state.
    rpt.write_text(json.dumps({
        "verdict": "PASS", "findings": [],
        "ai_subtrack": {"status": "CONSUMED"},
        "ai_convergence": {"consumed": 1}}))
    ran_empty = E.assess(proj, _PROGRAMS)
    assert ran_empty["state"] == "RAN_EMPTY"
    assert ran_empty["ai_subtrack"] == "CONSUMED"

    rpt.write_text(json.dumps({
        "verdict": "FINDINGS",
        "findings": [{"rule": "X", "layer": "L21_POWER_INTENT"}],
        "ai_subtrack": {"status": "CONSUMED"},
        "ai_convergence": {"consumed": 1}}))
    ran = E.assess(proj, _PROGRAMS)
    assert ran["state"] == "RAN" and ran["patch_count"] == 1
    assert ran["layers"] == ["L21_POWER_INTENT"]

    # Same rule as for the sidecar: unreadable evidence is not evidence.
    rpt.write_text("{not json")
    assert E.assess(proj, _PROGRAMS)["state"] == "MALFORMED"


def test_312_wiring_needs_both_ends_real(tmp_path):
    """One hop of indirection counts, but only when BOTH ends are real. A
    runner naming a track program that never reaches the hand-off is not wired
    — the same lesson as the bare-mention case, one level down."""
    fake = tmp_path / "programs"
    fake.mkdir()
    (fake / "phase1_one_shot_runner.py").write_text(
        '_EXPERT_TRACK = "phase1_expert_parse_track.py"\n')
    # No track program at all -> the hop leads nowhere.
    assert E.expert_track_wired(fake) is False
    # A track program that does not reach the hand-off -> still not wired.
    (fake / "phase1_expert_parse_track.py").write_text("# nothing here\n")
    assert E.expert_track_wired(fake) is False
    # Both ends real -> wired.
    (fake / "phase1_expert_parse_track.py").write_text(
        "import ic_expert_backup_pack as _p\n")
    assert E.expert_track_wired(fake) is True


def test_312_sidecar_path_matches_what_the_readers_read():
    """The writer-side contract must be the reader-side contract. Two paths
    would be a fresh drift — and a drifting sidecar location is how a track can
    'run' while every reader sees nothing."""
    reader = (_PROGRAMS / "phase1_doc_input_completeness_check.py").read_text()
    assert "phase1/ai_deep_review_patches.json" in reader
    assert E._SIDECAR_RELS[0] == "phase1/ai_deep_review_patches.json"


def test_312_enforcement_is_opt_in():
    """Default rc 0 (disclosure); --require-expert-track makes it fatal.
    Enabling it today would fail every Phase-1 run in the fleet — an owner
    decision, per #306, not a side effect."""
    src = (_PROGRAMS / "phase1_expert_track_evidence_check.py").read_text()
    assert "--require-expert-track" in src
    assert "ENFORCEMENT: advisory" in src


def test_312_handoff_module_is_no_longer_orphaned():
    """UPDATED DELIBERATELY. This previously asserted `callers == []` with the
    note "no longer orphaned — #312 progressed". It has: the Phase-1 expert
    PARSE track imports the hand-off module, which is what un-orphans it.

    Kept as an assertion rather than deleted, so removing the only caller fails
    here instead of silently returning the module to the shelf it sat on."""
    import re
    assert (_PROGRAMS / "ic_expert_backup_pack.py").is_file()
    # An IMPORT or a CALL — never a bare mention. This detector itself names
    # the module (it is the thing being looked for), and #306 already taught
    # that counting a mention as a call hides the whole defect.
    pat = re.compile(
        r"^[ \t]*(?:from[ \t]+ic_expert_backup_pack[ \t]+import"
        r"|import[ \t]+ic_expert_backup_pack\b)"
        r"|\bic_expert_backup_pack\s*\.\s*\w+\s*\(", re.M)
    callers = [f.name for f in _PROGRAMS.glob("*.py")
               if f.name != "ic_expert_backup_pack.py"
               and pat.search(f.read_text(errors="replace"))]
    assert "phase1_expert_parse_track.py" in callers, (
        f"the hand-off module is orphaned again (callers: {callers}) — the "
        f"Phase-1 expert track no longer uses the doctrine's own assembler")


def test_312_wired_detection_ignores_a_bare_mention(tmp_path):
    """A runner COMMENT saying the handoff should be called is exactly the
    state #312 describes — it must read as NOT wired. #306's lesson, applied
    to my own detector before it could repeat the mistake."""
    fake = tmp_path / "programs"
    fake.mkdir()
    (fake / "phase1_doc_one_shot_runner.py").write_text(
        "# TODO: call ic_expert_backup_pack here\n")
    assert E.expert_track_wired(fake) is False
