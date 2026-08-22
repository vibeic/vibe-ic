"""The eight rows, and the proof that their deadlines can still bite.

vibe-ic#1025 shipped the clock and `acknowledged: []` kept it stopped. The
rows that start it are a promise with a date on it, and a promise that cannot
come due is the same infinity in a different file -- so what is tested here is
not that the rows are well-formed prose but that the EXPIRY still refuses, that
the BOUND is what refuses (and not some other clause that would fire whatever
number the row carried), and that the only way to move the date is an edit to a
tracked file that carries an author.

WHY THIS FILE IS SEPARATE FROM `test_gate_red_since_check.py`. That file drives
the adjudicator over fixtures and answers "does the logic work". This one drives
it over the SHIPPED ledger and answers "do the rows this repo actually carries
still have teeth". A fixture cannot answer the second question: a row can be
perfectly well-formed and still name a gate label that no longer exists, or a
commit this repo does not have, and both of those are how a real ledger goes
quiet without anybody editing it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import gate_red_since_check as G  # noqa: E402

REPO = PROGRAMS.parents[3]
LEDGER = REPO / G.LEDGER_REL
HYGIENE = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"


@pytest.fixture(scope="module")
def rows():
    return G.load_ledger(LEDGER)


@pytest.fixture(scope="module")
def age():
    return G.git_age(REPO)


def _record(states):
    """A dispatch record in the shape `_gate_dispatch.sh --summary-json` writes."""
    gates = [{"label": lab, "state": st, "seconds": 1}
             for lab, st in states.items()]
    return {"declared": len(gates), "gates": gates}


# --------------------------------------------------------------------------
# THE ROWS ARE EVALUABLE. Each of these is a way a row goes quiet on its own.
# --------------------------------------------------------------------------

def test_every_row_carries_the_three_required_keys_and_the_three_human_ones(rows):
    assert rows, "the ledger is empty -- the clock is stopped again"
    for row in rows:
        for key in G._REQUIRED_KEYS:
            assert key in row, f"{row.get('gate')!r} is missing {key!r}"
        # Not required by the adjudicator, and required HERE. A bound with no
        # stated reason is indistinguishable at review time from a bound chosen
        # to reach past today, which is the one thing this mechanism cannot
        # detect for itself.
        for key in ("owner", "why", "bound_because"):
            assert row.get(key), f"{row['gate']!r} has no {key}"


def test_every_row_names_a_gate_this_repo_actually_declares(rows):
    """A label that matches nothing is failed as `stale` -- but only once the
    gate has run. A row typed against a label that never existed would sit in
    the file looking like coverage, so it is checked against the declaring
    script directly."""
    script = HYGIENE.read_text(encoding="utf-8")
    for row in rows:
        assert f'"{row["gate"]}"' in script, (
            f"{row['gate']!r} is named by no `run` line in "
            f"{HYGIENE.relative_to(REPO)}")


def test_every_since_resolves_to_a_commit_this_repo_contains(rows, age):
    for row in rows:
        assert age(row["since"]) is not None, (
            f"{row['gate']!r} cites {row['since']!r}, which this repo does not "
            f"have -- an unresolvable `since` is a clock that never advances")


def test_every_bound_is_a_bound(rows):
    for row in rows:
        bound = row["max_commits"]
        assert isinstance(bound, int) and not isinstance(bound, bool)
        assert 0 < bound <= G.MAX_BOUND_COMMITS, (
            f"{row['gate']!r} declares {bound}, outside "
            f"1..{G.MAX_BOUND_COMMITS}")


# --------------------------------------------------------------------------
# THE EXPIRY BITES. Both directions, over the SHIPPED rows and real history.
# --------------------------------------------------------------------------

def test_a_row_whose_since_has_fallen_past_its_bound_refuses(rows, age):
    """Direction one. Take a shipped row, leave `since` where the measurement
    put it, and set the bound BELOW the red's real age. It must fail."""
    row = dict(rows[0])
    behind = age(row["since"])
    assert behind and behind > 1
    row["max_commits"] = behind - 1
    findings, _, _ = G.adjudicate(
        _record({row["gate"]: "FAIL"}), [row], age)
    kinds = [f.kind for f in findings]
    assert "expired" in kinds, kinds
    assert str(behind) in " ".join(f.detail for f in findings), (
        "the refusal must say how far behind it actually is, not merely that "
        "it is behind")


def test_the_same_row_inside_its_bound_does_not_refuse(rows, age):
    """Direction two, and it is the one that makes direction one mean
    something: if every row refused, `expired` would be a constant."""
    row = dict(rows[0])
    behind = age(row["since"])
    row["max_commits"] = min(behind + 1, G.MAX_BOUND_COMMITS)
    findings, known, _ = G.adjudicate(
        _record({row["gate"]: "FAIL"}), [row], age)
    assert [f.kind for f in findings] == [], [f.line() for f in findings]
    assert row["gate"] in known


def test_a_gate_not_named_by_any_row_does_not_stop_a_landing(rows, age):
    """The mirror the brief asks for. A red nobody acknowledged is reported as
    NEW and is NOT failed here -- the suite has already failed it, and failing
    it twice would say nothing extra."""
    findings, _, new = G.adjudicate(
        _record({"a gate no row mentions": "FAIL"}), list(rows), age)
    assert "a gate no row mentions" in new
    assert not [f for f in findings
                if f.gate == "a gate no row mentions"], [f.line()
                                                         for f in findings]


def test_the_bound_is_what_refuses_and_not_some_other_clause(rows, age):
    """The mutation arm on the SHIPPED rows.

    Every row is driven red, then the SAME row is driven red again with its
    bound raised to the ceiling. If a row refuses in both arms, something other
    than the deadline is failing it and the row's number is decorative.
    """
    for row in rows:
        red = _record({row["gate"]: "FAIL"})
        tight, _, _ = G.adjudicate(red, [dict(row, max_commits=1)], age)
        loose, _, _ = G.adjudicate(
            red, [dict(row, max_commits=G.MAX_BOUND_COMMITS)], age)
        assert any(f.kind == "expired" for f in tight), (
            f"{row['gate']!r} does not expire even at a bound of 1")
        assert not any(f.kind == "expired" for f in loose), (
            f"{row['gate']!r} still expires at the ceiling -- its stated bound "
            f"is not what is deciding this")


def test_renewing_by_moving_since_forward_is_what_silences_it(rows, age):
    """The legitimate act, proven to work -- so the refusals above are a
    judgement and not a stuck output."""
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    for row in rows:
        expired, _, _ = G.adjudicate(
            _record({row["gate"]: "FAIL"}), [dict(row, max_commits=1)], age)
        assert any(f.kind == "expired" for f in expired)
        renewed, _, _ = G.adjudicate(
            _record({row["gate"]: "FAIL"}),
            [dict(row, since=head, max_commits=1)], age)
        assert not any(f.kind == "expired" for f in renewed), (
            f"{row['gate']!r} cannot be renewed by moving `since` to HEAD, so "
            f"the row has no legitimate way out and the mechanism is a wall")


# --------------------------------------------------------------------------
# THE ONLY WAY TO MOVE THE DATE IS A TRACKED EDIT THAT CARRIES AN AUTHOR.
# --------------------------------------------------------------------------

def test_the_ledger_is_tracked_so_every_renewal_has_an_author():
    tracked = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "--error-unmatch", G.LEDGER_REL],
        capture_output=True, text=True)
    assert tracked.returncode == 0, (
        f"{G.LEDGER_REL} is not tracked -- an untracked clock can be moved by "
        f"anyone with no record of who moved it")
    log = subprocess.run(
        ["git", "-C", str(REPO), "log", "--format=%an|%H", "--", G.LEDGER_REL],
        capture_output=True, text=True).stdout.strip().splitlines()
    assert log, "the ledger has no history"
    for line in log:
        author = line.split("|", 1)[0].strip()
        assert author, f"a commit touching the ledger carries no author: {line}"


def test_no_environment_variable_can_move_the_clock(rows, age):
    """`adjudicate` takes (record, ledger, age) and nothing else, and this is
    the behavioural proof rather than a reading of the signature: a row that
    has expired stays expired with the environment stuffed with every name a
    reader might guess at."""
    row = dict(rows[0])
    behind = age(row["since"])
    row["max_commits"] = max(1, behind - 1)
    red = _record({row["gate"]: "FAIL"})
    before = [f.line() for f in G.adjudicate(red, [row], age)[0]]
    assert any("expired" in line for line in before)
    poison = {"GATE_RED_SINCE_MAX_COMMITS": "99999",
              "GATE_RED_SINCE_SKIP": "1", "MAX_BOUND_COMMITS": "99999",
              "GATE_RED_SINCE_AMNESTY": "all", "CI": "true"}
    saved = {k: os.environ.get(k) for k in poison}
    os.environ.update(poison)
    try:
        after = [f.line() for f in G.adjudicate(red, [row], age)[0]]
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert after == before


def test_the_ceiling_cannot_be_raised_from_the_file_it_adjudicates(rows, age):
    """A row asking for more than the ceiling is refused, so the mechanism
    cannot be switched off by editing the ledger."""
    row = dict(rows[0], max_commits=G.MAX_BOUND_COMMITS + 1)
    findings, _, _ = G.adjudicate(
        _record({row["gate"]: "FAIL"}), [row], age)
    assert findings, "a bound above the ceiling was accepted"
