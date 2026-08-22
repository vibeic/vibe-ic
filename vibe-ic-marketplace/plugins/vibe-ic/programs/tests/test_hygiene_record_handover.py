"""A hygiene record handed over by the caller is CHECKED, never trusted.

`repo_hygiene_gate` refuses to grow a CLI seam because a command-line way to
point it at a cheap fixture would be a skip button on the gate whose whole
purpose is that it cannot be forgotten. `hygiene_gate_from_record` exists
beside that reasoning rather than against it: it changes the RUNNER of the same
subject, not the subject. What makes that safe is that every way of failing to
establish the record is rc 2 UNDETERMINED and blocking — so this file drives
each of those ways and asserts the refusal, and then asserts the one path that
is allowed to decide actually decides.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import gatekeeper_review as R  # noqa: E402

DECLARED = ["alpha gate", "beta gate", "gamma gate"]


@pytest.fixture()
def tree(tmp_path, monkeypatch):
    """A repo whose declared gate set is DECLARED, asked the way the gate asks."""
    monkeypatch.setattr(R, "_declared_labels",
                        lambda repo, script=None: list(DECLARED))
    return tmp_path


def _record(path: Path, labels, states=None):
    states = states or {}
    path.write_text(json.dumps({
        "declared": len(labels),
        "gates": [{"label": l, "state": states.get(l, "PASS"), "seconds": 1}
                  for l in labels]}), encoding="utf-8")
    return path


# --- every way of not establishing the record is rc 2, and blocking ---------

def test_a_record_that_is_not_there_is_undetermined(tree):
    g = R.hygiene_gate_from_record(tree, tree / "absent.json", 0)
    assert g.rc == 2 and not g.green
    assert "UNDETERMINED" in g.summary


def test_a_record_that_does_not_parse_is_undetermined(tree):
    p = tree / "r.json"
    p.write_text("{not json", encoding="utf-8")
    g = R.hygiene_gate_from_record(tree, p, 0)
    assert g.rc == 2 and not g.green


def test_a_record_with_no_exit_status_is_undetermined(tree):
    """The record says WHICH gates were red. Only the rc says the set finished,
    and a killed run leaves a record that looks complete."""
    g = R.hygiene_gate_from_record(tree, _record(tree / "r.json", DECLARED),
                                   None)
    assert g.rc == 2 and not g.green
    assert "exit status" in g.summary


def test_a_record_that_names_fewer_gates_than_the_tree_declares_is_undetermined(tree):
    """The anti-forgery check. A record trimmed to only its green gates is the
    cheapest possible forgery and it is the one this refuses by construction."""
    g = R.hygiene_gate_from_record(tree, _record(tree / "r.json", DECLARED[:1]),
                                   0)
    assert g.rc == 2 and not g.green
    assert "not in the record" in g.summary


def test_a_record_naming_a_gate_this_tree_does_not_declare_is_undetermined(tree):
    g = R.hygiene_gate_from_record(
        tree, _record(tree / "r.json", DECLARED + ["invented gate"]), 0)
    assert g.rc == 2 and not g.green
    assert "not\ndeclared" in g.summary or "not declared" in g.summary


def test_a_tree_that_cannot_be_asked_what_it_declares_is_undetermined(
        tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_declared_labels", lambda repo, script=None: None)
    g = R.hygiene_gate_from_record(
        tmp_path, _record(tmp_path / "r.json", DECLARED), 0)
    assert g.rc == 2 and not g.green


# --- and the path that IS allowed to decide, decides ------------------------

def test_a_matching_clean_record_passes_and_says_where_it_came_from(tree):
    g = R.hygiene_gate_from_record(tree, _record(tree / "r.json", DECLARED), 0)
    assert g.rc == 0 and g.green, g.summary
    # A verdict that came from somebody else's run must SAY so. A reader who
    # cannot tell an adjudicated record from a fresh run cannot audit either.
    assert "adjudicated from the caller's record" in g.summary
    assert "exited 0" in g.summary


def test_a_matching_record_carrying_a_failure_fails(tree):
    g = R.hygiene_gate_from_record(
        tree, _record(tree / "r.json", DECLARED, {"beta gate": "FAIL"}), 1)
    assert g.rc != 0 and not g.green
    assert "beta gate" in g.summary


def test_the_rc_is_not_ignored_in_favour_of_the_record(tree):
    """A record whose gates are all green, from a run that exited non-zero, is
    not a pass. The two are separate inputs precisely so this case exists."""
    g = R.hygiene_gate_from_record(tree, _record(tree / "r.json", DECLARED), 1)
    assert not g.green, g.summary


def test_review_uses_the_handover_instead_of_running_the_set(tree, monkeypatch):
    """The seam is actually taken: with a record supplied, the runner is not
    invoked at all."""
    called = []
    monkeypatch.setattr(R, "repo_hygiene_gate",
                        lambda *a, **k: called.append(1) or
                        R.GateResult("repo_hygiene_gates", 0, "ran"))
    rec = _record(tree / "r.json", DECLARED)
    g = R.hygiene_gate_from_record(tree, rec, 0)
    assert g.green and called == []
