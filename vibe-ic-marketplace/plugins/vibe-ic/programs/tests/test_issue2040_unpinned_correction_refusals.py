#!/usr/bin/env python3
"""Six refusals the #2040 correction operation makes that no test required.

MEASURED on main ``bdd0c24dd`` (v1.17.51). Every ``raise ValueError(
"REVIEW_CORRECTION_REFUSED: ...")`` in ``_correction_path``,
``_correction_object`` and ``_apply_review_correction`` was removed in turn --
34 sites -- and both ``test_ai_review_correction.py`` and this lane's other
module were run against each. THIRTEEN sites reddened something. TWENTY-ONE
could be deleted with every test still green.

An unpinned refusal is not a bug: the operation refuses correctly today. It is
a refusal that will stop refusing SILENTLY, on the first change that touches it,
with a green suite. That matters more here than in most places, because these
particular refusals are the ones holding up the claims issue #2040 makes for the
operation -- that inherited proofs stay immutable, that an accepted candidate is
never reopened, and that the round is reconstructible from records that cannot
have drifted.

This module pins six of the twenty-one, chosen as those three claims:

  4340  an inherited challenge whose bytes drifted
  4398  a candidate the acceptance report already accepted
  4382  a transition archive that no longer describes this round
  4384  a worklist row that moved under an applied round
  4421  a source file that changed during preparation
  4423  the worklist itself changing during preparation

The other fifteen are recorded in the lane, not fixed here: refusing everything
at once would be a bigger change than the one the issue asked for, and each
still needs an input that reaches it honestly.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import test_ai_review_correction as correction
import test_benchmark_program_first_ai_review as fixtures

bd = fixtures.bd


def _refused(capsys) -> str:
    captured = capsys.readouterr().err
    assert "REVIEW_CORRECTION_REFUSED" in captured, captured
    return captured


def _apply(run, request_path) -> dict:
    assert correction._resume(run, request_path) == 2
    return bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]


# --- claim 1: an inherited proof stays immutable ---------------------------
def test_a_drifted_inherited_challenge_refuses_the_round(tmp_path, capsys):
    """The operation carries prior tests forward as obligations. If one of them
    no longer hashes to what the task says, the round must not open on top of
    it -- otherwise the correction is the moment the drift becomes invisible."""
    run, task, request_path, request = correction._case(tmp_path)
    inherited = fixtures._write_defective_inversion_challenge(task)
    task["verification_challenges"] = [inherited]
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [task])
    request["task_sha256"] = bd._review_task_digest(task)
    request_path.write_text(json.dumps(request))
    Path(inherited["path"]).write_text(
        Path(inherited["path"]).read_text() + "\n// drifted\n")
    before = (run / bd._REVIEW_WORKLIST).read_bytes()

    assert correction._resume(run, request_path) == 2
    assert "inherited challenge drift" in _refused(capsys)
    assert (run / bd._REVIEW_WORKLIST).read_bytes() == before


# --- claim 2: an accepted candidate is never reopened ----------------------
def test_a_candidate_the_acceptance_report_accepted_refuses_the_round(
        tmp_path, capsys):
    """`solve_report.json` is not the only place acceptance is recorded. A
    candidate already in the acceptance report's accepted_ids has been
    published as accepted, and a correction round would reopen it."""
    run, task, request_path, _ = correction._case(tmp_path)
    (run / bd._ACCEPTANCE_REPORT).write_text(json.dumps({
        "schema": bd._ACCEPTANCE_SCHEMA, "status": "COMPLETE",
        "accepted_ids": [task["id"]]}))
    before = (run / bd._REVIEW_WORKLIST).read_bytes()

    assert correction._resume(run, request_path) == 2
    assert "candidate already accepted" in _refused(capsys)
    assert (run / bd._REVIEW_WORKLIST).read_bytes() == before


# --- claim 3: the records cannot have drifted ------------------------------
def test_a_transition_archive_that_describes_another_round_is_refused(
        tmp_path, capsys):
    """Replay reads the round back out of its own archive. An archive that no
    longer matches what this request would produce must stop the replay, not
    steer it."""
    run, task, request_path, _ = correction._case(tmp_path)
    advanced = _apply(run, request_path)
    transition = Path(advanced["review_correction"]["archive_path"]) \
        / "transition.json"
    record = json.loads(transition.read_text())
    record["material_sha256"] = {}
    transition.write_text(json.dumps(record, ensure_ascii=False,
                                     sort_keys=True) + "\n")

    assert correction._resume(run, request_path) == 2
    assert "transition evidence drift" in _refused(capsys)
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0] == advanced


def test_a_worklist_row_that_moved_under_an_applied_round_is_refused(
        tmp_path, capsys):
    """A replay may find the round already applied, or not yet applied. A row
    that is NEITHER is a state this operation did not create, and it must not
    write over it."""
    run, task, request_path, _ = correction._case(tmp_path)
    advanced = _apply(run, request_path)
    moved = dict(advanced, project=advanced["project"] + "/..")
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [moved])

    assert correction._resume(run, request_path) == 2
    assert "current task drift" in _refused(capsys)
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0] == moved


def test_a_source_file_changing_during_preparation_is_refused(
        tmp_path, capsys, monkeypatch):
    """Everything is hashed before the archives are written and re-hashed
    before the one authoritative commit. A writer that slips in between must
    lose the round, not win it."""
    run, task, request_path, _ = correction._case(tmp_path)
    real = bd._atomic_write_text
    prompt = Path(task["prompt_path"])

    def racing(path, text, *a, **k):
        if Path(path).name == "request.json":
            prompt.write_text(prompt.read_text() + "\n<!-- concurrent -->\n")
        return real(path, text, *a, **k)

    monkeypatch.setattr(bd, "_atomic_write_text", racing)
    before = (run / bd._REVIEW_WORKLIST).read_bytes()

    assert correction._resume(run, request_path) == 2
    assert "source changed during preparation" in _refused(capsys)
    assert (run / bd._REVIEW_WORKLIST).read_bytes() == before


def test_the_worklist_changing_during_preparation_is_refused(
        tmp_path, capsys, monkeypatch):
    """The worklist is the authoritative state this operation replaces. If it
    moved while the archives were being prepared, the replacement would be
    computed from a task that is no longer live."""
    run, task, request_path, _ = correction._case(tmp_path)
    real = bd._atomic_write_text
    worklist = run / bd._REVIEW_WORKLIST
    other = dict(task, id="p2")

    def racing(path, text, *a, **k):
        if Path(path).name == "request.json":
            bd._write_jsonl(worklist, [task, other])
        return real(path, text, *a, **k)

    monkeypatch.setattr(bd, "_atomic_write_text", racing)

    assert correction._resume(run, request_path) == 2
    assert "worklist changed during preparation" in _refused(capsys)
    rows = bd._read_jsonl(worklist)
    assert [r["id"] for r in rows] == ["p1", "p2"]
    assert all(r.get("review_correction") is None for r in rows)
