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


def test_312_the_repo_today_really_is_never_ran(tmp_path):
    """Non-vacuous: this asserts the DEFECT is present in this tree. When the
    expert track is finally wired, this test fails and must be updated
    deliberately — that is the point."""
    assert E.expert_track_wired(_PROGRAMS) is False, (
        "a Phase-1 runner now invokes the expert hand-off — #312 is fixed; "
        "update this test to reflect the new reality")
    rep = E.assess(_proj(tmp_path), _PROGRAMS)
    assert rep["state"] == "NEVER_RAN" and rep["wired"] is False
    assert "NOT because it ran and found nothing" in rep["detail"]


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


def test_312_handoff_module_exists_but_is_orphaned():
    """ic_expert_backup_pack is not missing — it is UNWIRED. That distinction
    matters: the mechanism was designed and measured, then never connected."""
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
    assert callers == [], f"no longer orphaned (called by {callers}) — #312 progressed"


def test_312_wired_detection_ignores_a_bare_mention(tmp_path):
    """A runner COMMENT saying the handoff should be called is exactly the
    state #312 describes — it must read as NOT wired. #306's lesson, applied
    to my own detector before it could repeat the mistake."""
    fake = tmp_path / "programs"
    fake.mkdir()
    (fake / "phase1_doc_one_shot_runner.py").write_text(
        "# TODO: call ic_expert_backup_pack here\n")
    assert E.expert_track_wired(fake) is False
