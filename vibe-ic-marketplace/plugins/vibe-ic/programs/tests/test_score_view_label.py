"""The scored VIEW must be on the record, and must never be assumed.

A pass@1 (first-candidate) number and a terminal loop2converge number are
different metrics. `pass_at_1.json` used to carry NEITHER label, so a converged
score and a single-shot score sat in the same field shape and were compared as
if they were one measurement -- which is how a plugin that scored the same at
the same view was read as having regressed by two problems.

The run already knows which it is: every accepted review is filed under
``{candidate_origin}-r{round}-{rtl_sha256}``.
"""
import json
import sys
from pathlib import Path

import pytest

_BENCH = Path(__file__).resolve().parents[2] / "benchmark"
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))

import score_iverilog_tb as S  # noqa: E402


def _run(tmp_path, outcomes):
    (tmp_path / "program_first_ai_review_acceptance.json").write_text(
        json.dumps({"review_outcomes": outcomes}))
    return tmp_path


def _o(pid, key, status="ACCEPTED"):
    return {"id": pid, "status": status,
            "review_path": f"/x/ai_reviews/{pid}/{key}.json"}


def test_all_first_candidates_is_single_shot(tmp_path):
    r = _run(tmp_path, [_o("ProbA", "program-r0-" + "a" * 64),
                        _o("ProbB", "ai_backup-r0-" + "b" * 64)])
    v = S.scored_view(r)
    assert v["view"] == "single-shot-first-candidate"
    assert v["recovered_ids"] == []


def test_a_repaired_candidate_makes_it_converged(tmp_path):
    """GREEN for the real defect: ONE recovered problem is enough to make the
    whole number a converged one, and it must be named."""
    r = _run(tmp_path, [_o("ProbA", "program-r0-" + "a" * 64),
                        _o("ProbB", "ai_repair-r1-" + "b" * 64)])
    v = S.scored_view(r)
    assert v["view"] == "converged-composed"
    assert v["recovered_ids"] == ["ProbB"]


def test_a_later_round_is_converged_even_from_a_program_origin(tmp_path):
    r = _run(tmp_path, [_o("ProbA", "program-r1-" + "a" * 64)])
    assert S.scored_view(r)["view"] == "converged-composed"


def test_unaccepted_outcomes_do_not_count(tmp_path):
    r = _run(tmp_path, [_o("ProbA", "program-r0-" + "a" * 64),
                        _o("ProbB", "ai_repair-r1-" + "b" * 64, status="REJECTED")])
    v = S.scored_view(r)
    assert v["view"] == "single-shot-first-candidate"
    assert v["recovered_ids"] == []


def test_missing_record_is_not_measured_never_single_shot(tmp_path):
    """Degrade LOUDLY. Claiming the stricter view when it was not measured is
    the exact error the field exists to prevent."""
    v = S.scored_view(tmp_path / "absent")
    assert v["view"] == "NOT_MEASURED"
    assert "no acceptance record" in v["view_basis"]


def test_unreadable_record_is_not_measured(tmp_path):
    (tmp_path / "program_first_ai_review_acceptance.json").write_text("{ not json")
    assert S.scored_view(tmp_path)["view"] == "NOT_MEASURED"


def test_unparseable_review_key_is_not_measured(tmp_path):
    """An accepted review whose key carries no origin-round cannot be classified,
    and a guess would be a fabricated label."""
    r = _run(tmp_path, [_o("ProbA", "no-round-here")])
    v = S.scored_view(r)
    assert v["view"] == "NOT_MEASURED"
    assert "ProbA" in v["view_basis"]


def test_empty_acceptance_record_is_not_measured(tmp_path):
    assert S.scored_view(_run(tmp_path, []))["view"] == "NOT_MEASURED"
