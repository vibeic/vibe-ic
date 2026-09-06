#!/usr/bin/env python3
"""The other fifteen refusals of the #2040 correction operation.

Companion to ``test_issue2040_unpinned_correction_refusals.py``. The census
recorded there found 21 of the operation's 34 ``REVIEW_CORRECTION_REFUSED``
sites deletable with a green suite; that module pinned the six carrying the
issue's headline claims. This module reaches the remaining fifteen.

Each test asserts the refusal by its own message, which is what keeps it
honest: this operation checks in a fixed order, so a test that merely asserted
"something was refused" would pass on whichever earlier guard happened to fire
and would keep passing after its own guard was deleted. Asserting the message
means the input really did travel as far as the refusal under test.

Every mutation of the task is accompanied by a recomputed ``task_sha256``, and
every mutation of the prior review by a recomputed ``review_sha256`` -- without
that, the staleness guard at the top of the operation answers first and nothing
below it is measured. That is the same trap in test form.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import test_ai_review_correction as correction
import test_benchmark_program_first_ai_review as fixtures

bd = fixtures.bd


def _retask(run: Path, task: dict, request: dict, request_path: Path,
            **changes) -> dict:
    """Change the live task and re-bind the request to it."""
    task = dict(task, **changes)
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [task])
    request["task_sha256"] = bd._review_task_digest(task)
    request_path.write_text(json.dumps(request))
    return task


def _rereview(task: dict, request: dict, request_path: Path,
              **changes) -> dict:
    """Change the prior review and re-bind the request to its new bytes."""
    review = json.loads(Path(task["review_path"]).read_text())
    review.update(changes)
    raw = json.dumps(review)
    Path(task["review_path"]).write_text(raw)
    request["review_sha256"] = bd._sha256_text(raw)
    request_path.write_text(json.dumps(request))
    return review


def _refuses(run: Path, request_path: Path, capsys, message: str) -> None:
    before = (run / bd._REVIEW_WORKLIST).read_bytes()
    assert correction._resume(run, request_path) == 2
    captured = capsys.readouterr().err
    assert "REVIEW_CORRECTION_REFUSED" in captured, captured
    assert message in captured, captured
    assert (run / bd._REVIEW_WORKLIST).read_bytes() == before


# --- the path and object helpers -------------------------------------------
def test_an_empty_evidence_path_is_refused_as_malformed(tmp_path, capsys):
    run, task, request_path, request = correction._case(tmp_path)
    _retask(run, task, request, request_path, prompt_path="")
    _refuses(run, request_path, capsys, "malformed path")


def test_evidence_outside_the_run_root_is_refused(tmp_path, capsys):
    """Correction evidence is read as trusted. A path outside the run is
    outside what this run can vouch for, even when the file exists."""
    run, task, request_path, request = correction._case(tmp_path)
    outside = tmp_path / "outside_the_run.md"
    outside.write_text(Path(task["prompt_path"]).read_text())
    _retask(run, task, request, request_path, prompt_path=str(outside))
    _refuses(run, request_path, capsys, "path outside run")


def test_absent_evidence_is_refused_by_name(tmp_path, capsys):
    run, task, request_path, request = correction._case(tmp_path)
    _retask(run, task, request, request_path,
            prompt_path=str(run / "no_such_prompt.md"))
    _refuses(run, request_path, capsys, "missing file")


def test_a_request_that_is_not_a_json_object_is_refused(tmp_path, capsys):
    run, task, request_path, _ = correction._case(tmp_path)
    request_path.write_text(json.dumps(["not", "an", "object"]))
    _refuses(run, request_path, capsys, "not a JSON object")


# --- identifying the one task being corrected ------------------------------
@pytest.mark.parametrize("kind", ["absent", "duplicate"])
def test_an_unidentifiable_task_is_refused(tmp_path, capsys, kind):
    """A correction names exactly one task. Zero matches would correct
    nothing; two would make which one it corrected a matter of ordering."""
    run, task, request_path, request = correction._case(tmp_path)
    if kind == "absent":
        request["id"] = "not-in-this-run"
        request_path.write_text(json.dumps(request))
    else:
        bd._write_jsonl(run / bd._REVIEW_WORKLIST, [task, dict(task)])
    _refuses(run, request_path, capsys, "missing or duplicate task id")


def test_a_transition_archive_without_a_prior_task_is_refused(tmp_path, capsys):
    """Replay reads the round's own starting point back out of the archive.
    An archive that cannot supply one must stop the replay before it picks a
    starting point of its own."""
    run, task, request_path, _ = correction._case(tmp_path)
    assert correction._resume(run, request_path) == 2
    advanced = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    transition = Path(advanced["review_correction"]["archive_path"]) \
        / "transition.json"
    record = json.loads(transition.read_text())
    record["prior_task"] = "not a task"
    transition.write_text(json.dumps(record))
    _refuses(run, request_path, capsys, "invalid transition archive")


def test_a_task_carrying_the_wrong_schema_is_refused(tmp_path, capsys):
    run, task, request_path, request = correction._case(tmp_path)
    _retask(run, task, request, request_path,
            schema="vibeic.benchmark.ai_review_task.v2")
    _refuses(run, request_path, capsys, "wrong task schema")


# --- the material the correction must be able to read ----------------------
def test_a_task_without_a_candidate_snapshot_is_refused(tmp_path, capsys):
    run, task, request_path, request = correction._case(tmp_path)
    _retask(run, task, request, request_path, candidate_snapshot=None)
    _refuses(run, request_path, capsys, "candidate snapshot missing")


def test_a_task_whose_project_directory_is_gone_is_refused(tmp_path, capsys):
    """The working RTL is re-hashed from the project to prove the candidate
    did not move. With no project there is nothing to compare against, and
    silence there would be the drift check passing vacuously."""
    run, task, request_path, request = correction._case(tmp_path)
    _retask(run, task, request, request_path,
            project=str(run / "projects" / "vanished"))
    _refuses(run, request_path, capsys, "missing project directory")


@pytest.mark.parametrize("field", ["rtl_paths", "working_rtl_paths"])
def test_a_task_with_no_rtl_path_list_is_refused(tmp_path, capsys, field):
    run, task, request_path, request = correction._case(tmp_path)
    _retask(run, task, request, request_path, **{field: []})
    _refuses(run, request_path, capsys, f"missing {field}")


# --- the prior review, which the round preserves ---------------------------
@pytest.mark.parametrize("field", ["id", "prompt_sha256", "rtl_sha256"])
def test_a_prior_review_bound_to_something_else_is_refused(
        tmp_path, capsys, field):
    """The review being corrected must be a review OF this task. A hash that
    matches its own bytes proves only that the file did not change."""
    run, task, request_path, request = correction._case(tmp_path)
    _rereview(task, request, request_path, **{field: "0" * 64})
    _refuses(run, request_path, capsys, f"prior review {field} drift")


@pytest.mark.parametrize("changes", [
    {"schema": "vibeic.benchmark.ai_review.v1"},
    {"reviewer": "not an object"},
    {"reviewer": {"kind": "Program", "model": "m"}},
    {"blind": {"oracle_accessed": True}},
])
def test_a_prior_review_that_was_never_a_blind_ai_review_is_refused(
        tmp_path, capsys, changes):
    """A correction round preserves the prior review as evidence. Evidence
    that was never an attributed blind AI review is not worth preserving, and
    carrying it forward would launder it."""
    run, task, request_path, request = correction._case(tmp_path)
    _rereview(task, request, request_path, **changes)
    _refuses(run, request_path, capsys, "malformed prior AI review")


def test_a_prior_review_with_no_verification_test_is_refused(tmp_path, capsys):
    run, task, request_path, request = correction._case(tmp_path)
    review = json.loads(Path(task["review_path"]).read_text())
    review.pop("verification_test")
    raw = json.dumps(review)
    Path(task["review_path"]).write_text(raw)
    request["review_sha256"] = bd._sha256_text(raw)
    request_path.write_text(json.dumps(request))
    _refuses(run, request_path, capsys, "prior challenge missing")


def test_a_prior_challenge_that_does_not_validate_is_refused(tmp_path, capsys):
    """The test being superseded is carried forward as an obligation, so it
    has to be a well-formed one. Its own validation reasons are quoted rather
    than replaced by a summary."""
    run, task, request_path, request = correction._case(tmp_path)
    review = json.loads(Path(task["review_path"]).read_text())
    review["verification_test"]["rationale"] = "too short to explain anything"
    raw = json.dumps(review)
    Path(task["review_path"]).write_text(raw)
    request["review_sha256"] = bd._sha256_text(raw)
    request_path.write_text(json.dumps(request))
    _refuses(run, request_path, capsys,
             "verification_test.rationale must explain the test")


def test_a_malformed_inherited_challenge_list_is_refused(tmp_path, capsys):
    run, task, request_path, request = correction._case(tmp_path)
    _retask(run, task, request, request_path,
            verification_challenges=["not a challenge record"])
    _refuses(run, request_path, capsys, "malformed inherited challenges")
