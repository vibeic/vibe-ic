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


# --------------------------------------------------------------------------
# PARSING THE DISPATCHER'S STATE VOCABULARY. Shared shape, one defect fixed
# once.
#
# The first version of this matched only the LITERAL form
# `GATE_STATES+=("NAME")` and therefore found 5 of the 8 states -- it MISSED
# PASS, FAIL and WROTE_CORPUS, which are assigned to `_GX_STATE` and reach the
# array through `GATE_STATES+=("$_GX_STATE")`. The three it missed are exactly
# the states that mean "this gate ran", so a test named for covering every
# state covered none of the interesting ones.
#
# Widening the pattern alone would leave the same defect one indirection later,
# so `dispatcher_states` also REFUSES a `GATE_STATES+=(` occurrence it cannot
# explain: a third assignment form fails here instead of silently shrinking the
# set.
# --------------------------------------------------------------------------

_STATE_LITERAL = r'GATE_STATES\+=\("([A-Z_]+)"\)'
_STATE_VIA_GX = r'_GX_STATE\s*=\s*"([A-Z_]+)"'
_ANY_APPEND = r'GATE_STATES\+=\(([^)]*)\)'
_KNOWN_INDIRECTION = '"$_GX_STATE"'


def dispatcher_states(disp: str) -> set:
    """Every state `_gate_dispatch.sh` can record, both assignment forms."""
    import re
    literal = set(re.findall(_STATE_LITERAL, disp))
    via_gx = set(re.findall(_STATE_VIA_GX, disp))
    unexplained = [a.strip() for a in re.findall(_ANY_APPEND, disp)
                   if a.strip() != _KNOWN_INDIRECTION
                   and a.strip().strip('"') not in literal]
    assert not unexplained, (
        "GATE_STATES is appended in a form this parser does not understand, "
        f"so the state set below is incomplete: {unexplained}")
    states = literal | via_gx
    assert states, "no states parsed -- the dispatcher's shape changed"
    return states


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


# --------------------------------------------------------------------------
# THE DENOMINATOR MUST BE WHAT RAN.
# --------------------------------------------------------------------------

def _doc(states):
    return {"declared": len(states),
            "gates": [{"label": f"g{i}", "state": s, "seconds": 1}
                      for i, s in enumerate(states)]}


def test_a_sharded_record_does_not_claim_every_gate_ran():
    """MEASURED on a real shard record — 8 FAIL beside 79 OTHER_SHARD — the
    summary read `87/87 gate(s) ran`. `gate_discloses_denominator_check`
    demands of every gate that a PASS say how much it looked at; this is that
    requirement applied to the line this program prints about the whole set."""
    doc = _doc(["FAIL"] * 8 + ["OTHER_SHARD"] * 79)
    assert "8/87 gate(s) ran" in R._hygiene_verdict(doc, 1).summary


@pytest.mark.parametrize("state", ["LISTED", "OTHER_SHARD", "OUT_OF_SCOPE",
                                   "QUEUED"])
def test_every_non_process_state_is_out_of_the_denominator(state):
    doc = _doc(["PASS", state])
    assert "1/2 gate(s) ran" in R._hygiene_verdict(doc, 0).summary


def test_not_checked_still_counts_as_having_run():
    """The gate EXECUTED and refused. Dropping it from the denominator would
    hide a refusal inside a shrinking population, which is the opposite of what
    NOT_CHECKED exists to make visible."""
    doc = _doc(["PASS", "NOT_CHECKED"])
    assert "2/2 gate(s) ran" in R._hygiene_verdict(doc, 1).summary


def test_a_full_record_is_unchanged():
    doc = _doc(["PASS"] * 60 + ["FAIL"] * 8)
    assert "68/68 gate(s) ran" in R._hygiene_verdict(doc, 1).summary


def test_the_not_run_set_covers_every_state_the_dispatcher_records():
    """Parsed from `_gate_dispatch.sh`, so a new state fails HERE rather than
    quietly inflating a denominator in a landing summary."""
    repo = PROGRAMS.parents[3]
    disp = (repo / "tools" / "ci" / "_gate_dispatch.sh").read_text(encoding="utf-8")
    states = dispatcher_states(disp)
    assert states >= {"PASS", "FAIL", "WROTE_CORPUS"}, (
        "the three states that MEAN 'this gate ran' must be in the parsed set; "
        f"a parser that misses them proves nothing here: {sorted(states)}")
    # Collected, for the same reason: one assert per state reports one state.
    wrong = []
    for s in sorted(states):
        doc = _doc(["PASS", s])
        summary = R._hygiene_verdict(doc, 1).summary
        expected = "2/2" if s in ("PASS", "FAIL", "NOT_CHECKED",
                                  "WROTE_CORPUS") else "1/2"
        if f"{expected} gate(s) ran" not in summary:
            wrong.append(f"{s} (wanted {expected}, got {summary!r})")
    assert not wrong, (
        f"{len(wrong)} state(s) counted wrongly in the denominator: "
        + "; ".join(wrong))


def test_all_three_consumers_agree_on_what_counts_as_having_run():
    """One name for one thing, checked across every consumer.

    `hygiene_finding_delta` owns the set and computed `ran` from it correctly
    all along. `gatekeeper_review` and `gate_red_since_check` had each grown a
    hand-maintained complement of it, and both were wrong in the same
    direction — a state the dispatcher added was counted as having run, or as
    being red. This asserts the three now share one definition.
    """
    import hygiene_finding_delta as H
    import gate_red_since_check as G
    assert tuple(R._process_states()) == tuple(H.PROCESS_STATES)
    assert tuple(G._RAN) == tuple(H.PROCESS_STATES)


def test_the_owner_answers_so_no_fallback_is_reported():
    """Direction one. On a healthy tree the source is None -- otherwise the
    control below could pass simply because the loader is always failing."""
    states, source = R._process_states_with_source()
    import hygiene_finding_delta as H
    assert source is None, source
    assert tuple(states) == tuple(H.PROCESS_STATES)


def test_a_denominator_from_the_fallback_copy_says_so(monkeypatch):
    """Direction two, and the reason the fallback is not simply deleted.

    `_PROCESS_STATES_FALLBACK` is a COPY of the set this module loads by path
    precisely so it does not re-derive it. Keeping the copy means a packaging
    fault cannot brick every landing; using it SILENTLY would mean a `ran`
    count derived from a stale set reads identically to one derived from its
    owner. If a state were ever removed upstream, the copy would keep counting
    it and `ran` would OVER-report gates as having run.
    """
    monkeypatch.setattr(
        R, "_process_states_with_source",
        lambda: (R._PROCESS_STATES_FALLBACK, "ImportError: simulated"))
    summary = R._hygiene_verdict(_doc(["PASS"] * 3), 0).summary
    assert "FALLBACK copy" in summary, summary
    assert "hygiene_finding_delta" in summary, summary
    assert "ImportError: simulated" in summary, summary


# --------------------------------------------------------------------------
# THE ARM THAT SHOULD BE UNCHANGED — CHECKED, NOT ASSERTED.
# --------------------------------------------------------------------------

def _drive_review(tmp_path, monkeypatch, **extra):
    """Drive the REAL `review()` and record which hygiene path it took."""
    import test_gatekeeper_review as B
    repo, plugin = B._build_clean_plugin(tmp_path, version="1.0.96")
    took = []
    monkeypatch.setattr(R, "repo_hygiene_gate",
                        lambda *a, **k: took.append("ran the set") or
                        R.GateResult("repo_hygiene_gates", 0, "ran"))
    monkeypatch.setattr(R, "hygiene_gate_from_record",
                        lambda *a, **k: took.append("read a record") or
                        R.GateResult("repo_hygiene_gates", 0, "adjudicated"))
    monkeypatch.setattr(R, "gate_red_since_gate",
                        lambda *a, **k: R.GateResult("gate_red_since", 0, "ok"))
    R.review("BASE", "HEAD", repo=repo, plugin_root=plugin,
             override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
             override_cur="1.0.96", override_prev="1.0.95", **extra)
    return took


def test_without_a_record_the_review_still_RUNS_the_hygiene_set(tmp_path,
                                                                monkeypatch):
    """THE ARM I HAD NOT CHECKED. `--hygiene-record-in` is absent by default and
    the claim has been that behaviour is then unchanged — but nothing asserted
    that `repo_hygiene_gate` is still reached. Had the branch inverted, the
    hygiene set would never run inside this program and MERGE_OK would mean
    nothing, silently. That is the largest possible weakening this change could
    have caused and it was the one arm with no test."""
    assert _drive_review(tmp_path, monkeypatch) == ["ran the set"]


def test_with_a_record_the_review_adjudicates_it_instead(tmp_path, monkeypatch):
    rec = tmp_path / "rec.json"
    rec.write_text("{}", encoding="utf-8")
    assert _drive_review(tmp_path, monkeypatch,
                         hygiene_record_in=rec,
                         hygiene_record_rc=0) == ["read a record"]


def test_exactly_one_of_the_two_paths_is_ever_taken(tmp_path, monkeypatch):
    """Both would double-count the gate; neither would drop it entirely."""
    for i, with_record in enumerate((False, True)):
        # a fresh root per iteration: `_build_clean_plugin` writes a tree and
        # refuses to write it twice, which is the builder being careful rather
        # than anything about the branch under test
        root = tmp_path / f"run{i}"
        root.mkdir()
        extra = {}
        if with_record:
            rec = root / "r.json"
            rec.write_text("{}", encoding="utf-8")
            extra = {"hygiene_record_in": rec, "hygiene_record_rc": 0}
        assert len(_drive_review(root, monkeypatch, **extra)) == 1


def test_the_state_parser_finds_both_assignment_forms():
    """The parser's own control. It once matched only the literal form and so
    found 5 of 8, missing PASS, FAIL and WROTE_CORPUS -- the three that mean
    "this gate ran"."""
    repo = PROGRAMS.parents[3]
    disp = (repo / "tools" / "ci" / "_gate_dispatch.sh").read_text(encoding="utf-8")
    states = dispatcher_states(disp)
    assert states == {"PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS",
                      "LISTED", "OTHER_SHARD", "OUT_OF_SCOPE", "QUEUED"}, (
        sorted(states))


def test_a_third_assignment_form_fails_here_rather_than_shrinking_the_set():
    """Widening a pattern only moves the defect to the next spelling. An
    append this parser cannot explain must REFUSE, because the alternative is
    a silently smaller state set and every test built on it passing for the
    wrong reason."""
    repo = PROGRAMS.parents[3]
    disp = (repo / "tools" / "ci" / "_gate_dispatch.sh").read_text(encoding="utf-8")
    invented = disp + '\n  GATE_STATES+=("${SOME_NEW_HOLDER}")\n'
    with pytest.raises(AssertionError, match="does not understand"):
        dispatcher_states(invented)
