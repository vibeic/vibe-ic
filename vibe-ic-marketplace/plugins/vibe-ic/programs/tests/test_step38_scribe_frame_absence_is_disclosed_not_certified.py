#!/usr/bin/env python3
"""Step 38's foundry-supplied scribe frame: EXPLAIN the absence, never certify it.

MEASURED on the real spm x ihp-sg13g2 converge run
(reyerchu@192.168.1.120:~/campaign_pr427/spm/converge_ihp-sg13g2), audited with
`flow_compliance_check.py <proj> --flow phase1_phase2_phase3 --skip-analog
--skip-hardware`:

    [38] Foundry Handoff ... = PASS
      evidence: ... scribe_line_layout.PENDING_FOUNDRY.txt ...

A note whose entire content is "scribe_line_layout.gds is FOUNDRY-SUPPLIED and
is NOT generated here" was being counted as the artefact. The flow declared

    scribe_line_layout.gds OR scribe_line_layout.PENDING_FOUNDRY.txt

and `foundry_handoff_pack_gen` writes that note UNCONDITIONALLY whenever the
.gds is absent — and writes the step's four other outputs too. So the only way
to reach "neither present" is for the step's own generator never to have run, in
which case the step already MISSes on those four. The entry could not fail: the
evidence excusing the absence was produced by the artefact being audited.

The requirement is the real .gds again. The absence is now disclosed the way the
flow already supports it: the generator emits
`scribe_line_layout_pending_foundry.json`, the #675-STRICT capability-gap marker
(self-skip verdict + non-empty `capability_flag` + `skips_required_output` naming
this exact output), so the step resolves to SKIPPED-CONDITION — review-flagged,
`self_skip_disclosed=True`, excluded from executed-PASS — never a clean PASS.

These tests drive the REAL generator and the REAL step-38 declaration from the
flow yaml, so a fixture cannot drift away from what ships.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parent.parent
FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
import flow_compliance_check as fcc            # noqa: E402
import foundry_handoff_pack_gen as packgen     # noqa: E402

_SCRIBE = "phase3/stage4/foundry_handoff/scribe_line_layout.gds"
_HANDOFF = "phase3/stage4/foundry_handoff"


def _step38() -> dict:
    doc = yaml.safe_load(FLOW.read_text())
    return next(s for s in doc["steps"] if s.get("id") == 38)


def _packed(tmp_path: Path) -> Path:
    """A project exactly as `foundry_handoff_pack_gen` leaves it."""
    proj = tmp_path / "proj"
    proj.mkdir()
    assert packgen.main([str(proj)]) == 0
    return proj


def _check(proj: Path):
    return fcc.check_step(proj, _step38(), {}, None)


# ── the defect ───────────────────────────────────────────────────────────────

def test_pack_gen_output_does_not_certify_step_38(tmp_path):
    """THE defect, end to end over the shipped generator + shipped declaration.
    Before: PASS. The absent frame must never read as a completed step."""
    r = _check(_packed(tmp_path))
    assert r.status != "PASS", (r.status, r.evidence)
    assert r.status == "SKIPPED-CONDITION", (r.status, r.reasons)
    assert r.self_skip_disclosed is True, r.reasons


def test_the_pending_note_is_never_counted_as_the_frame(tmp_path):
    """The prose note must not appear as EVIDENCE for the step. It is a
    statement that the artefact is missing; evidence is the artefact."""
    r = _check(_packed(tmp_path))
    assert not any("PENDING_FOUNDRY.txt" in e for e in r.evidence), r.evidence


def test_prose_note_alone_cannot_excuse_the_absence(tmp_path):
    """Without the machine-readable marker the prose note excuses nothing —
    the step is MISSING, not skipped and certainly not passed. This is what
    stops the fix from degenerating back into "any file next to it will do"."""
    proj = _packed(tmp_path)
    (proj / _HANDOFF / "scribe_line_layout_pending_foundry.json").unlink()
    r = _check(proj)
    assert r.status == "MISSING", (r.status, r.reasons)
    assert any("scribe_line_layout.gds" in x for x in r.reasons), r.reasons


# ── the marker's shape is the #675-strict ownership contract ─────────────────

def test_marker_declares_the_gap_and_owns_exactly_this_output(tmp_path):
    proj = _packed(tmp_path)
    blob = json.loads(
        (proj / _HANDOFF / "scribe_line_layout_pending_foundry.json")
        .read_text())
    assert blob["verdict"] in fcc._SELF_SKIP_VERDICTS
    assert blob["capability_flag"].strip()
    assert blob["skips_required_output"] == _SCRIBE
    # #484 — per-design identity, so two designs never emit a byte-identical
    # member for cross_design_identity_check to flag as a canned report.
    assert blob["design"] == proj.name


def test_marker_cannot_excuse_a_different_absent_output(tmp_path):
    """ANTI-MASK. The marker owns the scribe frame and nothing else: delete a
    real deliverable and the step must go back to MISSING, not ride the
    disclosure."""
    proj = _packed(tmp_path)
    (proj / _HANDOFF / "mask_spec.json").unlink()
    r = _check(proj)
    assert r.status == "MISSING", (r.status, r.reasons)


def test_a_real_scribe_gds_passes_the_step(tmp_path):
    """DIRECTION 1: when the foundry frame actually lands, the step passes on
    the artefact — the disclosure path is not sticky."""
    proj = _packed(tmp_path)
    (proj / _SCRIBE).write_bytes(b"\x00\x06\x00\x02\x00\x07REALGDS")
    r = _check(proj)
    assert r.status == "PASS", (r.status, r.reasons)
    assert r.self_skip_disclosed is False


def test_generator_leaves_a_real_scribe_gds_untouched(tmp_path):
    """DIRECTION 1 on the producer: a foundry-supplied frame is never replaced,
    and no pending marker is emitted beside it."""
    proj = tmp_path / "proj"
    (proj / _HANDOFF).mkdir(parents=True)
    (proj / _SCRIBE).write_bytes(b"\x00\x06\x00\x02\x00\x07REALGDS")
    assert packgen.main([str(proj)]) == 0
    assert (proj / _SCRIBE).read_bytes().endswith(b"REALGDS")
    assert not (proj / _HANDOFF
                / "scribe_line_layout_pending_foundry.json").exists()


# ── the declaration itself ───────────────────────────────────────────────────

def test_step38_requires_the_frame_not_a_note_about_the_frame():
    """The `OR <the note>` form is unfalsifiable: the note's producer is the
    step itself. If a future change reintroduces it, this fails."""
    entries = _step38()["required_outputs"]
    assert _SCRIBE in entries, entries
    assert not any("PENDING_FOUNDRY" in e for e in entries), entries


# ── a declaring marker is honoured only for what it declares ────────────────

def _gate_step(missing_file: str) -> dict:
    """A step whose GATE is a `files_exist` on one absent file — the path that
    consults the dir-level sibling-skip match."""
    return {"id": 900, "name": "synthetic files_exist step",
            "required_outputs": [f"{_HANDOFF}/present.json"],
            "gate": {"files_exist": [missing_file]}}


def test_declaring_marker_does_not_excuse_a_different_file_at_the_gate(
        tmp_path):
    """The `files_exist` gate path matches ANY skip-verdict sibling in the
    absent file's directory. Once runners drop narrowly-scoped markers into
    SHARED artefact directories — as step 38's now does — that dir-level match
    starts excusing unrelated absent files. Observable form: a gate demanding
    mask_spec.json must still FAIL while the only marker present says it skips
    the scribe frame."""
    d = tmp_path / _HANDOFF
    d.mkdir(parents=True)
    (d / "present.json").write_text("{}")
    (d / "scribe_line_layout_pending_foundry.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION",
        "capability_flag": "cap:foundry_supplied_scribe_frame",
        "skips_required_output": _SCRIBE}))
    r = fcc.check_step(tmp_path, _gate_step(f"{_HANDOFF}/mask_spec.json"),
                       {}, None)
    assert r.status == "FAIL", (r.status, r.reasons)
    # …and it DOES still excuse the output it actually owns.
    r2 = fcc.check_step(tmp_path, _gate_step(_SCRIBE), {}, None)
    assert r2.status != "FAIL", (r2.status, r2.reasons)


def test_gate_skip_unchanged_for_markers_that_declare_nothing(tmp_path):
    """DIRECTION 1: markers WITHOUT `skips_required_output` keep the original
    dir-level behaviour — the tightening only ever refuses a promotion, and the
    canonical #675 case (formal_not_run.json beside an absent results.json)
    must be untouched."""
    d = tmp_path / "phase2/stage1/formal"
    d.mkdir(parents=True)
    (d / "formal_not_run.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION", "reason": "no solver on host"}))
    step = {"id": 901, "name": "synthetic formal step",
            "required_outputs": ["phase2/stage1/formal/formal_not_run.json"],
            "gate": {"files_exist": ["phase2/stage1/formal/results.json"]}}
    r = fcc.check_step(tmp_path, step, {}, None)
    assert r.status != "FAIL", (r.status, r.reasons)


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
