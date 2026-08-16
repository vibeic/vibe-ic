"""The local hygiene DAG must be faster without becoming a smaller gate."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
spec = importlib.util.spec_from_file_location(
    "_repo_hygiene_parallel", PROGRAMS / "repo_hygiene_parallel.py")
assert spec and spec.loader
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


def gate(label, state):
    return {"label": label, "state": state, "seconds": 1,
            "exempt_until": None, "exempt_reason": None,
            "exemption_expired": False}


def fixture():
    reference = {
        "gates": [gate("ordinary", "LISTED"),
                  gate(P.HOST_LABEL, "LISTED")],
        "corpora": [], "undisclosed_loops": [], "today": "2026-08-16",
    }
    a = {"listed_only": False, "shard": "0/2", "gates": [
        gate("ordinary", "PASS"), gate(P.HOST_LABEL, "OTHER_SHARD")],
         "corpora": [], "undisclosed_loops": [], "today": "2026-08-16",
         "wiring_errors": []}
    b = {"listed_only": False, "shard": "1/2", "gates": [
        gate("ordinary", "OTHER_SHARD"), gate(P.HOST_LABEL, "PASS")],
         "corpora": [], "undisclosed_loops": [], "today": "2026-08-16",
         "wiring_errors": []}
    attest = [{"label": "ordinary", "complete": True},
              {"label": P.HOST_LABEL, "complete": True}]
    return reference, a, b, attest


def test_complete_dag_preserves_full_dispatch_summary():
    reference, a, b, attest = fixture()
    problems = []
    doc = P.merge_records(reference, [(Path("a"), a), (Path("b"), b)],
                          attest, 12, problems)
    assert problems == []
    assert doc["declared"] == doc["decided"] == doc["passed"] == 2
    assert doc["other_shard"] == 0
    assert doc["parallel"]["complete"] is True
    assert P._summary_rc(doc) == 0


def test_missing_shard_gate_is_named_and_refused():
    reference, a, _, attest = fixture()
    problems = []
    doc = P.merge_records(reference, [(Path("a"), a)], attest, 12, problems)
    assert any(P.HOST_LABEL in problem for problem in problems)
    assert doc["parallel"]["complete"] is False
    assert P._summary_rc(doc) == 2


def test_duplicate_owner_is_named_and_refused():
    reference, a, b, attest = fixture()
    duplicate = dict(b)
    duplicate["gates"] = [gate("ordinary", "PASS"),
                          gate(P.HOST_LABEL, "PASS")]
    problems = []
    doc = P.merge_records(reference,
                          [(Path("a"), a), (Path("b"), duplicate)],
                          attest, 12, problems)
    assert any("ordinary" in problem and "got 2" in problem
               for problem in problems)
    assert P._summary_rc(doc) == 2


def test_missing_process_attestation_cannot_become_green():
    reference, a, b, attest = fixture()
    problems = []
    doc = P.merge_records(reference, [(Path("a"), a), (Path("b"), b)],
                          attest[:1], 12, problems)
    assert any(P.HOST_LABEL in problem and "attestation" in problem
               for problem in problems)
    assert P._summary_rc(doc) == 2
