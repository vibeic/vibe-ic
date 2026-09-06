#!/usr/bin/env python3
"""Two behaviours of the #2040 correction operation that nothing else pins.

This module is the residue of an ADVERSARIAL review of the landed operation
(main ``bdd0c24dd``, v1.17.51) against the refusal list issue #2040 states for
itself. Nine probes were driven through the real ``--resume
--review-correction`` entry: the happy path, a pre-occupied new challenge path,
a structurally invalid prior current challenge, an absent ``solve_report.json``,
a byte-drifted inherited challenge, a prior review whose semantic verdict is
PASS, a chained second correction, and the auditability of the advanced task.
Every refusal in the issue's list fired, correctly, with its own message. No
functional residual was demonstrated, so this module changes no source.

What it adds is coverage for the two behaviours the probes exercised that the
landed suite does not:

  OCCUPIED NEW PATH -- ``test_source_drift_or_published_candidate_blocks``
      covers a published response, but not a new review or new challenge path
      that already exists. That branch matters most precisely when it is
      hardest to reach honestly: the new key is derived from the request hash,
      so anyone holding the request can compute the path and plant a passing
      test at it before the round opens. Deleting the guard reddens the test
      here and nothing else in the module.

  CHAINED CORRECTION -- a corrected round can itself be corrected, and the
      obligations must ACCUMULATE. Both prior tests stay inherited and both
      sets of bytes stay on disk, so the second correction cannot be used to
      shed the first round's proof. This one is characterisation: it pins
      behaviour the landing already has, and its value is that a later change
      to the dedup or to ``verification_challenges`` cannot drop an obligation
      silently.
"""
from __future__ import annotations

import json
from pathlib import Path

import test_ai_review_correction as correction
import test_benchmark_program_first_ai_review as fixtures

bd = fixtures.bd


def test_a_preoccupied_new_challenge_path_refuses_the_round(tmp_path, capsys):
    """The new key is public to whoever holds the request; planting a test at
    it must stop the round, not seed it."""
    run, task, request_path, _ = correction._case(tmp_path)
    key = "review-correction-" + bd._sha256_text(request_path.read_text())
    planted = (run / "ai_verification_challenges" / "p1" / key
               / "challenge_tb.sv")
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text("// planted before the round was opened\n")
    before = (run / bd._REVIEW_WORKLIST).read_bytes()

    assert correction._resume(run, request_path) == 2
    assert "REVIEW_CORRECTION_REFUSED" in capsys.readouterr().err
    assert (run / bd._REVIEW_WORKLIST).read_bytes() == before
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0].get(
        "review_correction") is None
    assert planted.read_text() == "// planted before the round was opened\n"


def test_a_preoccupied_new_review_path_refuses_the_round(tmp_path, capsys):
    run, task, request_path, _ = correction._case(tmp_path)
    key = "review-correction-" + bd._sha256_text(request_path.read_text())
    planted = run / "ai_reviews" / "p1" / f"{key}.json"
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text("{}")
    before = (run / bd._REVIEW_WORKLIST).read_bytes()

    assert correction._resume(run, request_path) == 2
    assert "REVIEW_CORRECTION_REFUSED" in capsys.readouterr().err
    assert (run / bd._REVIEW_WORKLIST).read_bytes() == before


@fixtures._NEEDS_SIMULATOR
def test_a_corrected_round_can_itself_be_corrected_and_obligations_accumulate(
        tmp_path):
    """Correcting round one must not shed round zero's proof."""
    run, task, request_path, request = correction._case(tmp_path)
    assert correction._resume(run, request_path) == 2
    first = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]

    # Round one reviews the same candidate and gets it wrong a DIFFERENT way.
    review = fixtures._valid_review(first)
    record = fixtures._write_direct_assignment_challenge(first)
    source = Path(first["challenge_path"]).read_text().replace(
        "module vibeic_ai_challenge_tb;",
        "// round one, a different wrong test\nmodule vibeic_ai_challenge_tb;",
        1).replace("if (y !== 1'b0)", "if (y !== 1'b1)")
    Path(first["challenge_path"]).write_text(source)
    review["verification_test"] = dict(record,
                                       sha256=bd._sha256_text(source))
    review["semantic_review"].update({
        "verdict": "FAIL",
        "findings": ["round one also expects inversion"],
        "prompt_evidence": review["verification_test"]["prompt_evidence"]})
    fixtures._write_review(first, review)

    second = dict(request)
    second.update({
        "task_sha256": bd._review_task_digest(first),
        "review_sha256": correction._digest(first["review_path"]),
        "challenge_sha256": correction._digest(first["challenge_path"]),
        "rationale": request["rationale"] + " Round one repeated the error."})
    second_path = run / "correction_request_2.json"
    second_path.write_text(json.dumps(second))
    assert correction._resume(run, second_path) == 2

    latest = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert latest["review_path"] != first["review_path"]
    assert latest["challenge_path"] != first["challenge_path"]
    assert latest["rtl_sha256"] == task["rtl_sha256"]
    inherited = [c["sha256"] for c in latest["verification_challenges"]]
    assert inherited == [request["challenge_sha256"],
                         second["challenge_sha256"]], inherited
    assert correction._digest(task["challenge_path"]) == \
        request["challenge_sha256"]
    assert correction._digest(first["challenge_path"]) == \
        second["challenge_sha256"]


def test_a_correction_round_is_reconstructible_from_its_archive_alone(tmp_path):
    """Auditability is the product: a round nobody can reconstruct is a way to
    launder a review, and issue #2040 asks for the author, the reason, the
    parent review hash and the transition to be recorded.

    The landed suite checks that two archived files are byte-equal to their
    sources. This checks the CLOSURE: that the five archive files plus the
    advanced worklist row answer, on their own, which challenge was superseded,
    by whom, why, and that the candidate was byte-identical across the round --
    with every hash recomputed here rather than read back from the record that
    asserts it.
    """
    run, old, request_path, request = correction._case(tmp_path)
    assert correction._resume(run, request_path) == 2
    advanced = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    archive = Path(advanced["review_correction"]["archive_path"])

    request_raw = (archive / "request.json").read_text()
    prior_task = json.loads((archive / "prior_task.json").read_text())
    prior_review_raw = (archive / "prior_review.json").read_text()
    prior_review = json.loads(prior_review_raw)
    prior_test = (archive / "prior_challenge_tb.sv").read_text()
    transition = json.loads((archive / "transition.json").read_text())
    archived = json.loads(request_raw)

    # WHO, and WHY, without consulting anything the operation still controls.
    assert archived["author"]["kind"] == "AI"
    assert archived["author"]["model"].strip()
    assert archived["blind"]["oracle_accessed"] is False
    assert len(archived["rationale"].strip()) >= 80
    assert archived["prompt_evidence"]
    assert archive.name == bd._sha256_text(request_raw)

    # WHICH challenge was superseded -- archived bytes, live bytes and the
    # hash the request names all agree, so none of the three can drift alone.
    assert bd._sha256_text(prior_review_raw) == archived["review_sha256"]
    assert correction._digest(prior_task["review_path"]) == \
        archived["review_sha256"]
    assert bd._sha256_text(prior_test) == archived["challenge_sha256"]
    assert correction._digest(prior_task["challenge_path"]) == \
        archived["challenge_sha256"]
    assert prior_review["verification_test"]["sha256"] == \
        archived["challenge_sha256"]

    # The candidate did not move across the round.
    snapshot = prior_task["candidate_snapshot"]
    completion = Path(snapshot["completion_path"]).read_text()
    assert bd._sha256_text(completion) == prior_task["rtl_sha256"]
    assert archived["rtl_sha256"] == prior_task["rtl_sha256"]
    assert advanced["rtl_sha256"] == prior_task["rtl_sha256"]
    assert advanced["candidate_snapshot"] == snapshot
    assert bd._sha256_text(Path(prior_task["prompt_path"]).read_text()) == \
        prior_task["prompt_sha256"]
    assert advanced["prompt_sha256"] == prior_task["prompt_sha256"]

    # The TRANSITION: both endpoints are named, and every source the
    # preparation hashed still hashes to what the record says it did.
    assert transition["request_sha256"] == bd._sha256_text(request_raw)
    assert transition["prior_task"] == prior_task
    assert transition["new_task"] == advanced
    assert transition["material_sha256"]
    assert all(correction._digest(path) == digest
               for path, digest in transition["material_sha256"].items())
    assert prior_task["review_path"] in transition["material_sha256"]
    assert prior_task["challenge_path"] in transition["material_sha256"]
    assert advanced["verification_challenges"][-1]["sha256"] == \
        archived["challenge_sha256"]
    assert advanced["review_correction"]["repair_authorized"] is False
