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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

REPO = PROGRAMS.parents[3]
LEDGER = REPO / G.LEDGER_REL
HYGIENE = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"


@pytest.fixture(scope="module")
def rows():
    return G.load_ledger(LEDGER)


@pytest.fixture(scope="module")
def age():
    return G.git_age_days(REPO)


#: A bound BELOW every shipped row's real age, used as the "must expire" arm.
#: A day is too coarse now that the clock is a duration: the three PPA rows are
#: hours old, so `max_days=1` would not expire them and the arm would report
#: the rule broken when it is the stimulus that is wrong.
_TIGHT_DAYS = 0.001


def _ack(repo, gate, since, days, **kw):
    """A synthetic acknowledgement, DATED FROM THE REPOSITORY like a real one.

    `since_date` is read from the commit rather than typed, for the same reason
    the shipped rows carry the commit's own date: a row whose stated date and
    whose anchor disagree is a `misdated` finding, and a fixture that hand-typed
    one would be testing the typo rather than the rule.
    """
    return dict(gate=gate, since=since,
                since_date=G.git_commit_date(repo)(since),
                max_days=days, **kw)


#: The window a synthesised bound must be able to straddle: `behind - 1` has to
#: stay a positive bound and `behind + 1` has to stay under `MAX_BOUND_DAYS`, so
#: the age itself has to sit strictly inside both.
_STRADDLE_LO = 1.5
_STRADDLE_HI = G.MAX_BOUND_DAYS - 1.0

#: How far back to look for an anchor. This history runs ~78 commits/day (the
#: cadence the retired ledger rows measured), so the six-day ceiling is ~470
#: commits and this is an order of magnitude of headroom. Bounded rather than
#: unbounded because the walk is a fixture, not a verdict.
_ANCHOR_SCAN = 6000


@pytest.fixture(scope="module")
def straddling_clock():
    """`(since, age, behind)` — a real commit of this repository, and a clock
    at which a declarable bound sits on either side of its age.

    THE ANCHOR IS NO LONGER A SHIPPED ROW (2026-08-29). It was `rows[0]["since"]`,
    which made three direction tests and the ceiling test ERROR the moment the
    ledger was emptied — and the ledger being empty is the state this whole
    mechanism is trying to reach. A control that takes its stimulus from the
    debt it polices dies with the fix and stops being a control without stopping
    being green, which is the shape `test_the_1_6x_clause_was_REHOMED` records on
    the other side of the repository. Nothing these tests assert needed the
    shipped row: every one of them overwrites `max_days` outright and keeps only
    the `(gate, since, since_date)` triple, which `_ack` synthesises FROM THE
    REPOSITORY exactly as a real row carries it.

    WHY THE DIRECTION TESTS BELOW CANNOT READ THE CLOCK AT `HEAD`, AND WHY THE
    ANSWER IS NOT A BIGGER BOUND.

    Each of them takes a shipped row and SYNTHESISES a bound either side of the
    red's measured age -- `behind - 1` must expire, `behind + 1` must not. That
    construction has a ceiling built into it that nothing declared: a bound is
    only legal up to `MAX_BOUND_DAYS`, and once the age read at HEAD passes that
    ceiling NEITHER side can be built. `behind - 1` is refused as `unbounded`
    before the expiry clause is ever reached, and `behind + 1` lands above the
    ceiling too. MEASURED on this tree: `rows[0]` is 6.1 days old at HEAD
    against a 6-day ceiling, so both sides are out of reach at the endpoint the
    production run uses.

    `MAX_BOUND_DAYS` is a ceiling on how large a bound may be DECLARED. It is
    not a deadline, and raising it to fit a test would be raising a limit to
    make a measurement come out -- so the ENDPOINT moves instead, which costs
    the tests nothing they were actually asserting. `git_age_days` already takes
    the tree the clock counts TO: it is the production `--head-ref`, and a
    landing passes its BASE for exactly this reason. Here it is handed a tree
    partway along the row's own real history, so `behind` is a distance a row is
    ALLOWED to declare a bound for. `since` is untouched, the row is the shipped
    one, and the history is this repository's.

    THE ENDPOINT IS MEASURED, NOT ASSUMED. Under the duration clock the useful
    endpoint is one whose DATE sits a workable number of days after `since`,
    which is not the same as one a fixed number of commits along: commit dates
    are not monotonic across merges, and 500 commits of a busy day can span
    hours. So candidates are probed with the same `age` the adjudicator uses and
    the first one landing inside the window is returned.
    """
    # ONE `git log`, NOT ONE PROBE PER COMMIT. Calling the age function for each
    # commit is two `git` processes apiece — minutes of fixture for a value that
    # is a subtraction of two dates. The dates are read in one pass and the
    # arithmetic is done here.
    listing = subprocess.run(
        ["git", "-C", str(REPO), "log", "-n", str(_ANCHOR_SCAN),
         "--format=%H %cI", "HEAD"],
        capture_output=True, text=True).stdout.splitlines()
    assert listing, "this repository has no history to anchor a deadline in"
    end = G._parse_iso(G.git_commit_date(REPO)("HEAD"))
    assert end is not None, "this repo cannot date HEAD"
    # The LARGEST age inside the window gives the widest straddle, so a rounding
    # difference at either side cannot collapse it.
    best = None
    for line in listing:
        sha, _, iso = line.partition(" ")
        when = G._parse_iso(iso)
        if when is None:
            continue
        behind = (end - when).total_seconds() / G._SECONDS_PER_DAY
        if (_STRADDLE_LO <= behind <= _STRADDLE_HI
                and (best is None or behind > best[1])):
            best = (sha, behind)
    if best is None:
        raise AssertionError(
            f"no commit within the last {_ANCHOR_SCAN} sits "
            f"{_STRADDLE_LO}..{_STRADDLE_HI} days behind HEAD, so no bound can "
            f"be straddled and neither direction of the expiry rule can be "
            f"exercised on this history")
    since, behind = best
    at = G.git_age_days(REPO, "HEAD")
    # MEASURED THROUGH THE PRODUCTION FUNCTION, not trusted from the loop: if
    # `git_age_days` and this arithmetic ever disagree, the direction tests must
    # fail rather than silently assert against a number the adjudicator never
    # sees.
    assert at(since) == pytest.approx(behind), (at(since), behind)
    return since, at, behind


def _record(states):
    """A dispatch record in the shape `_gate_dispatch.sh --summary-json` writes."""
    gates = [{"label": lab, "state": st, "seconds": 1}
             for lab, st in states.items()]
    return {"declared": len(gates), "gates": gates}


# --------------------------------------------------------------------------
# THE ROWS ARE EVALUABLE. Each of these is a way a row goes quiet on its own.
# --------------------------------------------------------------------------

def test_every_row_carries_the_required_keys_and_the_three_human_ones(rows):
    # `assert rows, "the ledger is empty -- the clock is stopped again"` STOOD
    # HERE AND WAS RETIRED 2026-08-29, because it made the ledger's correct
    # state unreachable.
    #
    # It was true when written: vibe-ic#1025 shipped this ledger empty and
    # nothing forced a row into it, so empty really did mean the clock was
    # stopped. What closed that gap is `landing_merge_verdict.decide` calling
    # `gate_red_since_check.inherited_red_reasons`, which REFUSES a landing over
    # an inherited blocking red no row names -- and that property is pinned,
    # over an EMPTY ledger, by
    # `test_inherited_red_deadline.test_an_inherited_blocking_red_with_no_owner_refuses`.
    # So the file being empty no longer means nobody is acknowledging; it means
    # nothing is owed, and the next red that appears is refused rather than
    # carried.
    #
    # Left in place, the assertion demanded that this repository always owe
    # something. MEASURED at 073a703de: both rows it carried had to go -- one
    # was FIXED and one was a red this repository cannot close and whose own
    # `adjudicated` ruling forbids renewal -- so satisfying this line would have
    # meant keeping an acknowledgement that was already false in both
    # directions. The loop below is the check; over no rows it correctly finds
    # nothing, and `test_gate_red_since_check` drives the same rules over
    # fixtures where the population is never empty.
    # COLLECTED. An assert inside the row loop stops at the first offender, so
    # the failure names one row and the next is reachable only by fixing that
    # one and re-running. See the note on the bound test below.
    missing = []
    for row in rows:
        for key in G._REQUIRED_KEYS:
            if key not in row:
                missing.append(f"{row.get('gate')} is missing {key}")
        # Not required by the adjudicator, and required HERE. A bound with no
        # stated reason is indistinguishable at review time from a bound chosen
        # to reach past today, which is the one thing this mechanism cannot
        # detect for itself.
        for key in ("owner", "why", "bound_because"):
            if not row.get(key):
                missing.append(f"{row.get('gate')} has no {key}")
    assert not missing, (
        f"{len(missing)} field(s) missing across the ledger: " + "; ".join(missing))


def test_every_row_names_a_gate_this_repo_actually_declares(rows):
    """A label that matches nothing is failed as `stale` -- but only once the
    gate has run. A row typed against a label that never existed would sit in
    the file looking like coverage, so it is checked against the declaring
    script directly."""
    script = HYGIENE.read_text(encoding="utf-8")
    undeclared = [row["gate"] for row in rows
                  if f'"{row["gate"]}"' not in script]
    assert not undeclared, (
        f"{len(undeclared)} row(s) named by no `run` line in "
        f"{HYGIENE.relative_to(REPO)}: " + ", ".join(undeclared))


def test_every_since_resolves_to_a_commit_this_repo_contains(rows, age):
    unresolvable = [f"{row['gate']} cites {row['since']}" for row in rows
                    if age(row["since"]) is None]
    assert not unresolvable, (
        f"{len(unresolvable)} row(s) cite a commit this repo does not have -- "
        "an unresolvable `since` is a clock that never advances: "
        + "; ".join(unresolvable))


def test_every_bound_is_a_bound(rows):
    bad = []
    for row in rows:
        bound = row["max_days"]
        if not isinstance(bound, (int, float)) or isinstance(bound, bool):
            bad.append(f"{row['gate']} declares {bound!r}, not a number")
        elif not 0 < bound <= G.MAX_BOUND_DAYS:
            bad.append(f"{row['gate']} declares {bound}, outside "
                       f"0..{G.MAX_BOUND_DAYS} days")
    assert not bad, f"{len(bad)} bound(s) are not bounds: " + "; ".join(bad)


def test_every_since_date_is_the_date_of_the_commit_it_names(rows):
    """The row's anchor and the row's stated date must agree.

    A row that says it was acknowledged on one date while the commit it cites
    is dated another is misreporting its own age to every human who reads it —
    and re-dating a row to keep it alive is the one act this file forbids
    outright. It buys nothing in any case (the clock reads the repository, not
    this field), which is exactly why the disagreement would otherwise go
    unnoticed until somebody tried to audit a deadline by eye.
    """
    dated = G.git_commit_date(REPO)
    wrong = []
    for row in rows:
        actual = dated(str(row["since"]))
        if actual is None:
            wrong.append(f"{row['gate']}: this repo cannot date "
                         f"{str(row['since'])[:12]}")
        elif not G._same_instant(str(row["since_date"]), actual):
            wrong.append(f"{row['gate']}: row says {row['since_date']}, "
                         f"commit {str(row['since'])[:12]} says {actual}")
    assert not wrong, (
        f"{len(wrong)} row(s) disagree with their own anchor: "
        + "; ".join(wrong))


# --------------------------------------------------------------------------
# THE EXPIRY BITES. Both directions, over the SHIPPED rows and real history.
# --------------------------------------------------------------------------

def test_a_row_whose_since_has_fallen_past_its_bound_refuses(
        straddling_clock):
    """Direction one. Take a shipped row, leave `since` where the measurement
    put it, and set the bound BELOW the red's real age. It must fail.

    The clock is read at a tree the bound can straddle rather than at HEAD --
    see `straddling_clock` for why, and for what stayed the same.
    """
    since, age, behind = straddling_clock
    assert _STRADDLE_LO <= behind <= _STRADDLE_HI, behind
    row = _ack(REPO, "a gate this row acknowledges", since, behind - 1)
    findings, _, _ = G.adjudicate(
        _record({row["gate"]: "FAIL"}), [row], age)
    kinds = [f.kind for f in findings]
    assert "expired" in kinds, kinds
    assert G._days(behind) in " ".join(f.detail for f in findings), (
        "the refusal must say how far behind it actually is, not merely that "
        "it is behind")


def test_the_same_row_inside_its_bound_does_not_refuse(
        straddling_clock):
    """Direction two, and it is the one that makes direction one mean
    something: if every row refused, `expired` would be a constant.

    The bound is `behind + 1` and is NOT clamped any more. Clamping was how
    this direction went dark: once the age passed the ceiling, `min(...)` chose
    the ceiling, which is BELOW the age, so the row expired and the test read
    that as the rule being broken. A bound the ceiling cannot express is a
    stimulus that no longer exists, not a smaller stimulus.
    """
    since, age, behind = straddling_clock
    row = _ack(REPO, "a gate this row acknowledges", since, behind + 1)
    assert row["max_days"] <= G.MAX_BOUND_DAYS, (
        "the endpoint left no room for a bound ABOVE the age; direction two "
        "cannot be constructed and must not be silently weakened to fit")
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


# ---------------------------------------------------------------------------
# THIS MODULE WAS VALIDATED AS AN INSTRUMENT, 2026-08-22.
#
# A suite that passes proves nothing about a mechanism unless it FAILS when the
# mechanism is broken. Both sites of the deciding clause in
# `gate_red_since_check` --
#
#     if behind > bound:        (x2)   ->   if False:
#
# were mutated, and the mutation was confirmed to change observable behaviour
# BEFORE the suite's verdict was read (a substitution that merely reports
# "applied" proves only that a string was found):
#
#     pristine   a row 999 behind a bound of 1  ->  findings ['expired']
#     mutant     the same row                   ->  findings []
#
# Against that mutant this module goes 1 failed -> 7 failed: SIX guards flip
# from pass to fail --
#
#     test_a_row_whose_since_has_fallen_past_its_bound_refuses
#     test_the_bound_is_what_refuses_and_not_some_other_clause
#     test_renewing_by_moving_since_forward_is_what_silences_it
#     test_no_environment_variable_can_move_the_clock
#     test_a_candidates_own_commits_do_not_expire_a_row_it_never_touched
#     test_a_candidate_cannot_renew_its_own_overdue_row
#     test_the_mechanism_still_expires_a_gate_that_DID_run
#
# -- so they sit BEHIND the deadline rather than restating it. The seventh is
# the ceiling failure this module reports on the shipped rows either way.
# ---------------------------------------------------------------------------


def test_the_bound_is_what_refuses_and_not_some_other_clause(rows, age):
    """The mutation arm on the SHIPPED rows.

    Every row is driven red at an age one commit PAST the bound it typed for
    itself, and then again at an age exactly AT it. The first must report
    `expired` and the second must report nothing at all -- so what decides is
    the comparison between the red's age and this row's own number, and nothing
    else about the row.

    WHY THE AGE IS VARIED AND NOT THE BOUND. Until v1.11.70 this held the real
    age fixed and raised the bound to `MAX_BOUND_COMMITS`, expecting `expired`
    to stop. That is the same question only while every shipped row is YOUNGER
    than the ceiling. The ceiling is 500 commits, and MEASURED on 2026-08-22 this
    repo took 539 commits in the 5.69 days from c5d7f2d00e1d (2026-08-16 19:07)
    to a4caccefe -- 94.7 a day, which makes that ceiling a 5.3-DAY deadline. So
    two rows citing c5d7f2d00e1d -- 'L-doc field producer' (bound 210, itself
    2.2 days) and 'evidence citation resolves' (bound 140, 1.5 days) -- stood
    539 commits back, 39 PAST the ceiling. For a row in that state no
    legal bound clears the deadline, so the old loose arm asked `adjudicate`
    for a verdict it is designed never to give, and then read the refusal as
    evidence that "something other than the deadline is failing it". That is
    precisely backwards: it was the deadline, and only the deadline. The bound
    had not become decorative; it had been overtaken. Varying the AGE asks the
    intended question at any repo age and never has to name a number past the
    ceiling, so it cannot expire on its own the way the old form did.

    The at-bound arm asserts NO findings rather than merely no `expired` one.
    `adjudicate` returns early for `stale`, `unresolvable` and `incomplete`, so
    a row failing for one of those produces no `expired` finding either and
    "not any expired" would have passed on it -- green because the row was
    broken in a different way, which is the one thing this arm must not do.
    """
    # COLLECTED, then asserted once. `assert` inside this loop stopped at the
    # first offending row, so the failure could only ever say "a row" and never
    # "how many". Measured on the shipped tree: it reported ONE decorative bound
    # while TWO were present, and the second was only reachable by deleting the
    # first from the file and re-running. A check that under-reports by a factor
    # of two is the same defect this test exists to catch, in the test itself.
    never_expires = []
    decorative = []
    past_ceiling = []
    for row in rows:
        red = _record({row["gate"]: "FAIL"})
        tight, _, _ = G.adjudicate(
            red, [dict(row, max_days=_TIGHT_DAYS)], age)
        loose, _, _ = G.adjudicate(
            red, [dict(row, max_days=G.MAX_BOUND_DAYS)], age)
        if not any(f.kind == "expired" for f in tight):
            never_expires.append(row["gate"])

        behind = age(row["since"])
        if behind is not None and behind > G.MAX_BOUND_DAYS:
            # PAST THE CEILING, WHICH IS A DIFFERENT CLAUSE AND MUST BE SAID SO.
            # A red older than MAX_BOUND_DAYS cannot be covered by ANY legal
            # bound, so "it still expires at the ceiling" is true and is not
            # evidence that some unnamed clause is deciding it. Measured
            # 2026-08-22: `L-doc field producer` and `evidence citation
            # resolves` reached 501 against a ceiling of 500. Asserting the
            # generic message there would have reported a defect that is not
            # one -- and saying nothing would have hidden a row that can never
            # again be legitimately acknowledged, only renewed or fixed.
            if not any(f.kind == "expired" for f in loose):
                past_ceiling.append((row["gate"], behind))
            continue

        if any(f.kind == "expired" for f in loose):
            decorative.append(row["gate"])
    assert not never_expires, (
        f"{len(never_expires)} row(s) do not expire even at a bound of "
        f"{_TIGHT_DAYS} day(s): "
        f"{never_expires}")
    assert not past_ceiling, (
        f"{len(past_ceiling)} row(s) are past the ceiling of "
        f"{G.MAX_BOUND_DAYS} day(s) and so must expire even at the ceiling: "
        f"{past_ceiling}")
    assert not decorative, (
        f"{len(decorative)} row(s) still expire at the ceiling -- their stated "
        f"bound is not what is deciding them: {decorative}")


def test_renewing_by_moving_since_forward_is_what_silences_it(rows, age):
    """The legitimate act, proven to work -- so the refusals above are a
    judgement and not a stuck output."""
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    # Same correction as above, for the same reason: one assert per loop reports
    # one row and hides the rest.
    not_expiring = []
    walled = []
    for row in rows:
        expired, _, _ = G.adjudicate(
            _record({row["gate"]: "FAIL"}),
            [dict(row, max_days=_TIGHT_DAYS)], age)
        if not any(f.kind == "expired" for f in expired):
            not_expiring.append(row["gate"])
        renewed, _, _ = G.adjudicate(
            _record({row["gate"]: "FAIL"}),
            [_ack(REPO, row["gate"], head, _TIGHT_DAYS)], age)
        if any(f.kind == "expired" for f in renewed):
            walled.append(row["gate"])
    assert not not_expiring, (
        f"{len(not_expiring)} row(s) do not expire at a bound of "
        f"{_TIGHT_DAYS} day(s): "
        f"{not_expiring}")
    assert not walled, (
        f"{len(walled)} row(s) cannot be renewed by moving `since` to HEAD, so "
        f"they have no legitimate way out and the mechanism is a wall: {walled}")


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


def test_no_environment_variable_can_move_the_clock(straddling_clock):
    """`adjudicate` takes (record, ledger, age) and nothing else, and this is
    the behavioural proof rather than a reading of the signature: a row that
    has expired stays expired with the environment stuffed with every name a
    reader might guess at.

    It needs an EXPIRED row to poison the environment around, and it built one
    the same way direction one did, so it went dark for the same reason. Same
    repair: the clock is read at a tree the bound can straddle.
    """
    since, age, behind = straddling_clock
    row = _ack(REPO, "a gate this row acknowledges", since, behind - 1)
    red = _record({row["gate"]: "FAIL"})
    before = [f.line() for f in G.adjudicate(red, [row], age)[0]]
    assert any("expired" in line for line in before)
    poison = {"GATE_RED_SINCE_MAX_DAYS": "99999",
              "GATE_RED_SINCE_SKIP": "1", "MAX_BOUND_DAYS": "99999",
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


def test_the_ceiling_cannot_be_raised_from_the_file_it_adjudicates(
        straddling_clock, age):
    """A row asking for more than the ceiling is refused, so the mechanism
    cannot be switched off by editing the ledger."""
    since, _at, _behind = straddling_clock
    row = _ack(REPO, "a gate this row acknowledges", since,
               G.MAX_BOUND_DAYS + 1)
    findings, _, _ = G.adjudicate(
        _record({row["gate"]: "FAIL"}), [row], age)
    assert findings, "a bound above the ceiling was accepted"


# --------------------------------------------------------------------------
# THE CANDIDATE MUST NOT MOVE THE CLOCK.
# --------------------------------------------------------------------------

#: Fixture commits are ONE DAY APART, and that is load-bearing now.
#: The clock is a duration, so five commits written in the same second are five
#: commits zero days apart: every age would be 0.0, no bound could be straddled,
#: and each direction test would pass for the wrong reason. Dates are stamped
#: explicitly rather than left to the wall clock so the fixture means the same
#: thing on a fast host and a slow one.
_FIXTURE_DAY = "2026-01-{:02d}T00:00:00+00:00"


def _repo(tmp_path):
    """A history: since -> base -> three candidate commits, one day apart."""
    r = tmp_path / "r"
    r.mkdir()
    def git(*a, day=None):
        env = None
        if day is not None:
            env = dict(os.environ,
                       GIT_AUTHOR_DATE=_FIXTURE_DAY.format(day),
                       GIT_COMMITTER_DATE=_FIXTURE_DAY.format(day))
        return subprocess.run(["git", "-C", str(r), *a], capture_output=True,
                              text=True, check=False, env=env)
    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    shas = []
    for i in range(5):
        (r / f"f{i}").write_text(str(i), encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", f"c{i}", day=i + 1)
        shas.append(git("rev-parse", "HEAD").stdout.strip())
    return r, shas


def test_the_clock_counts_to_the_ref_it_is_given(tmp_path):
    r, shas = _repo(tmp_path)
    since, base = shas[0], shas[1]
    assert G.git_age_days(r, base)(since) == 1.0
    assert G.git_age_days(r, "HEAD")(since) == 4.0


def test_a_candidates_own_commits_do_not_expire_a_row_it_never_touched(tmp_path):
    """MEASURED as a real defect on a 15-commit branch: 7 rows read as expired
    against its own head and 5 against origin/main, and two of the difference
    were rows the branch never touched. A landing therefore counts to the BASE
    — the same rule that requires the LEDGER to be the base's, for the same
    reason: a branch must not be able to change what counts as overdue, in
    either direction."""
    r, shas = _repo(tmp_path)
    since, base = shas[0], shas[1]
    row = _ack(r, "some gate", since, 2)
    red = _record({"some gate": "FAIL"})

    against_base, _, _ = G.adjudicate(red, [row], G.git_age_days(r, base))
    assert [f.kind for f in against_base] == [], (
        "one day behind a bound of two must not be overdue")

    against_head, _, _ = G.adjudicate(red, [row], G.git_age_days(r, "HEAD"))
    assert any(f.kind == "expired" for f in against_head), (
        "four days behind a bound of two must be overdue — otherwise this "
        "test proves nothing about which ref was used")


def test_the_landing_review_passes_a_base_ref_through(tmp_path, monkeypatch):
    """The wiring, not just the helper: `gatekeeper_review` must hand the base
    to the checker, or the fix exists and is never reached."""
    import gatekeeper_review as R
    seen = {}

    def fake(prog, argv):
        seen["argv"] = argv
        return 0, "[PASS] ok", ""

    monkeypatch.setattr(R, "_run_program", fake)
    rec = tmp_path / "rec.json"
    rec.write_text("{}", encoding="utf-8")
    R.gate_red_since_gate(tmp_path, rec, base="origin/main")
    assert "--head-ref" in seen["argv"], seen["argv"]
    assert seen["argv"][seen["argv"].index("--head-ref") + 1] == "origin/main"


def test_without_a_base_the_checker_is_not_told_a_ref(tmp_path, monkeypatch):
    """The mirror: callers that have no base (a developer running it by hand)
    keep the old behaviour byte-for-byte rather than being handed an empty
    --head-ref, which git would read as a ref named ''."""
    import gatekeeper_review as R
    seen = {}
    monkeypatch.setattr(R, "_run_program",
                        lambda prog, argv: (seen.setdefault("argv", argv), 0,
                                            "[PASS] ok", "")[1:])
    rec = tmp_path / "rec.json"
    rec.write_text("{}", encoding="utf-8")
    R.gate_red_since_gate(tmp_path, rec)
    assert "--head-ref" not in seen["argv"], seen["argv"]


# --------------------------------------------------------------------------
# NOR MAY THE CANDIDATE RENEW ITS OWN OVERDUE ROW.
# --------------------------------------------------------------------------

def _repo_with_ledger(tmp_path, base_rows, head_rows):
    """A history whose ledger differs between the base commit and HEAD."""
    r = tmp_path / "lr"
    (r / "tools" / "ci").mkdir(parents=True)
    day = [0]
    def git(*a, dated=False):
        env = None
        if dated:
            day[0] += 1
            env = dict(os.environ,
                       GIT_AUTHOR_DATE=_FIXTURE_DAY.format(day[0]),
                       GIT_COMMITTER_DATE=_FIXTURE_DAY.format(day[0]))
        return subprocess.run(["git", "-C", str(r), *a], capture_output=True,
                              text=True, check=False, env=env)
    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (r / "seed").write_text("x", encoding="utf-8")
    git("add", "-A"); git("commit", "-q", "-m", "seed", dated=True)
    since = git("rev-parse", "HEAD").stdout.strip()

    # Commits BETWEEN `since` and the base — a DAY apart now that the clock is
    # a duration — so a row bounded at 1 day is genuinely past its bound at the
    # base rather than exactly on it. `adjudicate` fails on `behind > bound`,
    # and a fixture sitting on the boundary would prove nothing about which
    # ledger was read. Same commits, dates instead of counts.
    for i in range(3):
        (r / f"b{i}").write_text("x", encoding="utf-8")
        git("add", "-A"); git("commit", "-q", "-m", f"base{i}", dated=True)

    led = r / G.LEDGER_REL
    def write(rows):
        led.write_text(json.dumps({"acknowledged": rows}), encoding="utf-8")
    write([_ack(r, row["gate"], since, row["max_days"]) for row in base_rows])
    git("add", "-A"); git("commit", "-q", "-m", "base ledger", dated=True)
    base = git("rev-parse", "HEAD").stdout.strip()

    for i in range(4):                      # the candidate's own commits
        (r / f"c{i}").write_text("x", encoding="utf-8")
        git("add", "-A"); git("commit", "-q", "-m", f"cand{i}", dated=True)
    head = git("rev-parse", "HEAD").stdout.strip()
    write([_ack(r, row["gate"], head, row["max_days"]) for row in head_rows])
    git("add", "-A"); git("commit", "-q", "-m", "candidate renews the row",
                          dated=True)
    return r, since, base


def test_the_ledger_comes_from_the_ref_not_the_working_tree(tmp_path):
    r, since, base = _repo_with_ledger(
        tmp_path, [{"gate": "g", "max_days": 1}],
        [{"gate": "g", "max_days": 1}])
    at_base = G.load_ledger_from_ref(r, base)
    assert [row["since"] for row in at_base] == [since], at_base
    on_disk = G.load_ledger(r / G.LEDGER_REL)
    assert on_disk[0]["since"] != since, (
        "the fixture did not actually move `since`, so this proves nothing")


def test_a_candidate_cannot_renew_its_own_overdue_row(tmp_path):
    """THE ATTACK. The row is overdue against the base. The candidate moves
    `since` forward to HEAD in its own tree, which WOULD silence it — and does
    not, because the landing reads the rows at the base."""
    r, since, base = _repo_with_ledger(
        tmp_path, [{"gate": "g", "max_days": 1}],
        [{"gate": "g", "max_days": 1}])
    red = _record({"g": "FAIL"})

    silenced, _, _ = G.adjudicate(
        red, G.load_ledger(r / G.LEDGER_REL), G.git_age_days(r, base))
    assert not any(f.kind == "expired" for f in silenced), (
        "the candidate's own ledger must be the one that WOULD silence it, or "
        "this test is not exercising the attack")

    held, _, _ = G.adjudicate(
        red, G.load_ledger_from_ref(r, base), G.git_age_days(r, base))
    assert any(f.kind == "expired" for f in held), (
        "reading the rows at the base did not keep the row overdue")


def test_a_ref_that_predates_the_ledger_is_empty_not_an_error(tmp_path):
    r, since, base = _repo_with_ledger(
        tmp_path, [{"gate": "g", "max_days": 1}], [])
    assert G.load_ledger_from_ref(r, since) == []


def test_a_ref_that_does_not_exist_is_an_error(tmp_path):
    """A caller that names a ref and is wrong about it must not be handed an
    empty ledger, which would read as `nothing is acknowledged`.

    AND IT MUST NOT BE HANDED A FINDING EITHER, which is the half this test did
    not say and which cost a clean tree its merge: `--ledger-ref` reads through
    `git show`, so any tree that is not a git repository failed the read, and
    the read failure was graded rc 1 -- a refusal about the ENVIRONMENT printed
    in the words of a finding about the CANDIDATE. Both directions are pinned
    below: the exception is `LedgerUnreadable` and NAMES the path and the ref,
    and the CLI grades it rc 2 NOT CHECKED with the vacuity disclosed on both
    channels. A bare `pytest.raises(ValueError)` accepted either grading.
    """
    r, since, base = _repo_with_ledger(
        tmp_path, [{"gate": "g", "max_days": 1}], [])
    with pytest.raises(G.LedgerUnreadable) as caught:
        G.load_ledger_from_ref(r, "no-such-ref-9f3a")
    named = str(caught.value)
    assert G.LEDGER_REL in named and "no-such-ref-9f3a" in named, named

    out = _cli(r, _rec_file(tmp_path, {"g": "FAIL"}),
               "--ledger-ref", "no-such-ref-9f3a")
    assert out.returncode == 2, (out.returncode, out.stdout, out.stderr)
    assert "[VACUOUS]" in out.stdout, out.stdout
    assert "[FAIL]" not in out.stdout, out.stdout
    assert G.LEDGER_REL in out.stdout and "no-such-ref-9f3a" in out.stdout, \
        out.stdout
    assert "VACUOUS_PASS:" in out.stderr, out.stderr


def test_the_review_passes_both_halves_from_the_base(tmp_path, monkeypatch):
    import gatekeeper_review as R
    seen = {}
    monkeypatch.setattr(R, "_run_program",
                        lambda prog, argv: (seen.setdefault("argv", argv), 0,
                                            "[PASS] ok", "")[1:])
    rec = tmp_path / "rec.json"
    rec.write_text("{}", encoding="utf-8")
    R.gate_red_since_gate(tmp_path, rec, base="origin/main")
    argv = seen["argv"]
    for flag in ("--head-ref", "--ledger-ref"):
        assert flag in argv, argv
        assert argv[argv.index(flag) + 1] == "origin/main"


# --------------------------------------------------------------------------
# THE ENDPOINT IS PART OF THE NUMBER.
# --------------------------------------------------------------------------

def _cli(repo, record, *extra):
    return _pr.run(
        [sys.executable, str(PROGRAMS / "gate_red_since_check.py"),
         "--record", str(record), "--repo", str(repo), *extra],
        capture_output=True, text=True)


def _rec_file(tmp_path, states):
    q = tmp_path / "rec.json"
    q.write_text(json.dumps(_record(states)), encoding="utf-8")
    return q


def test_the_verdict_says_which_tree_the_ages_were_counted_to(tmp_path):
    """"N commit(s) ago" is meaningless without its endpoint. The same ledger
    and record gave 7 expired counted to a branch head and 5 counted to
    origin/main, and nothing in the output distinguished the two runs."""
    r, shas = _repo(tmp_path)
    out = _cli(r, _rec_file(tmp_path, {"g": "FAIL"}), "--head-ref", shas[1]).stdout
    line = next((l for l in out.splitlines() if "clock:" in l), "")
    assert line, out
    assert shas[1][:7] in line or shas[1] in line, line
    assert "ages are DAYS, counted to" in line


def test_the_verdict_says_where_the_rows_came_from(tmp_path):
    r, shas = _repo(tmp_path)
    rec = _rec_file(tmp_path, {"g": "FAIL"})
    from_tree = _cli(r, rec).stdout
    assert "rows read from the working tree at" in from_tree, from_tree
    from_ref = _cli(r, rec, "--ledger-ref", shas[1]).stdout
    assert f"rows read from {shas[1]}" in from_ref, from_ref


def test_a_ref_that_cannot_be_resolved_is_disclosed_not_echoed(tmp_path):
    """A disclosure that silently degrades to repeating its input tells a
    reader nothing they did not type."""
    r, _ = _repo(tmp_path)
    out = _cli(r, _rec_file(tmp_path, {"g": "FAIL"}),
               "--head-ref", "no-such-ref-9f3a").stdout
    line = next((l for l in out.splitlines() if "clock:" in l), "")
    assert "UNRESOLVABLE" in line, line


def test_the_two_endpoints_produce_visibly_different_output(tmp_path):
    """The property that makes the disclosure worth having: two runs that
    differ ONLY in what they counted to must not look identical."""
    r, shas = _repo(tmp_path)
    rec = _rec_file(tmp_path, {"g": "FAIL"})
    a = _cli(r, rec, "--head-ref", shas[1]).stdout
    b = _cli(r, rec, "--head-ref", "HEAD").stdout
    line_a = next(l for l in a.splitlines() if "clock:" in l)
    line_b = next(l for l in b.splitlines() if "clock:" in l)
    assert line_a != line_b, line_a


# --------------------------------------------------------------------------
# A GATE THAT DID NOT RUN IN THIS RECORD CANNOT BE ADJUDICATED.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("state", [G._LISTED, G._OTHER_SHARD, "OUT_OF_SCOPE", "QUEUED"])
def test_a_gate_that_did_not_run_is_never_reported_expired(tmp_path, state):
    """MEASURED: a real shard record carries 79 OTHER_SHARD beside 8 FAIL, and
    every one of the 79 was counted red — so a row could be failed as EXPIRED
    for a gate that was never executed. "I could not look" must not reach a
    verdict as "I looked and it was bad"."""
    r, shas = _repo(tmp_path)
    row = _ack(r, "g", shas[0], 1)
    findings, known, new = G.adjudicate(
        _record({"g": state}), [row], G.git_age_days(r, "HEAD"))
    assert [f.kind for f in findings] == [], [f.line() for f in findings]
    assert "g" not in known and "g" not in new


@pytest.mark.parametrize("state", [G._LISTED, G._OTHER_SHARD, "OUT_OF_SCOPE", "QUEUED"])
def test_a_gate_that_did_not_run_is_not_counted_red(tmp_path, state):
    _, _, new = G.adjudicate(
        _record({"other": state}), [], G.git_age_days(tmp_path, "HEAD"))
    assert new == [], new


def test_the_mechanism_still_expires_a_gate_that_DID_run(tmp_path):
    """The direction that keeps the exemption honest: widening what cannot be
    adjudicated must not turn the deadline into something that never fires."""
    r, shas = _repo(tmp_path)
    row = _ack(r, "g", shas[0], 1)
    findings, _, _ = G.adjudicate(
        _record({"g": "FAIL"}), [row], G.git_age_days(r, "HEAD"))
    assert any(f.kind == "expired" for f in findings), [f.line() for f in findings]


def test_the_cli_names_the_rows_it_could_not_adjudicate(tmp_path):
    """Skipping them silently would let a row nobody judged read as a row that
    passed — which is the same silence this program exists to remove."""
    r, shas = _repo(tmp_path)
    led = tmp_path / "led.json"
    led.write_text(json.dumps({"acknowledged": [
        _ack(r, "g", shas[0], 1)]}), encoding="utf-8")
    rec = tmp_path / "rec.json"
    rec.write_text(json.dumps(_record({"g": G._OTHER_SHARD, "x": "PASS"})),
                   encoding="utf-8")
    out = _cli(r, rec, "--ledger", str(led)).stdout
    assert "NOT ADJUDICABLE" in out, out
    assert "g" in out


def test_the_ran_set_agrees_with_the_shared_one():
    """One name for one thing, checked. If `hygiene_finding_delta` learns a new
    process state and this file does not, a gate that ran would stop being
    adjudicated — silently, and in the permissive direction."""
    import hygiene_finding_delta as H
    assert tuple(G._RAN) == tuple(H.PROCESS_STATES), (G._RAN, H.PROCESS_STATES)


def test_every_state_the_dispatcher_can_record_is_classified():
    """THE GUARD THAT MAKES THIS A RULE AND NOT A LIST. Parsed from
    `_gate_dispatch.sh` itself, so a state added there fails HERE rather than
    quietly becoming overdue-by-default in a landing."""
    import re
    disp = (REPO / "tools" / "ci" / "_gate_dispatch.sh").read_text(encoding="utf-8")
    states = set(re.findall(r'GATE_STATES\+=\("([A-Z_]+)"', disp))
    assert states, "no states parsed — the dispatcher's shape changed"
    for s in states:
        ran = s in G._RAN
        assert ran != G._did_not_run(s), (
            f"{s!r} is classified inconsistently: in _RAN={ran}, "
            f"_did_not_run={G._did_not_run(s)}")
    # and the ones that are NOT process states must be the not-run kind
    assert {s for s in states if not G._did_not_run(s)} <= set(G._RAN)


def test_an_unrecognised_state_is_not_adjudicable_rather_than_overdue():
    """The fail-safe direction: 'I do not recognise this state' must mean 'I
    cannot judge it', never 'it is red'."""
    assert G._did_not_run("SOME_STATE_INVENTED_LATER")


# --------------------------------------------------------------------------
# A TRUNCATED HISTORY IS A CAUSE THE ROWS CANNOT BE BLAMED FOR.
# --------------------------------------------------------------------------

def _shallow_clone_of(src, dest, depth=1):
    subprocess.run(["git", "clone", "--quiet", "--depth", str(depth),
                    "--no-local", f"file://{src}", str(dest)],
                   capture_output=True, text=True, check=False)
    return dest


def test_a_shallow_repository_that_still_resolves_is_treated_as_normal(tmp_path):
    """MY FIRST ATTEMPT REFUSED ON SHALLOWNESS ITSELF AND WAS WRONG. This
    fixture is shallow while the named `since` commit still resolves.  The
    fixture owns that premise; requiring the ambient checkout to be shallow
    made this test impossible to run in a full clone, while a depth-1 clone
    made the shipped old commits unavailable to every other test in the file.
    Refusing pre-emptively on shallowness would block a valid clock over a
    condition that changes no verdict."""
    repo, shas = _repo(tmp_path)
    git_dir = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-dir"],
        capture_output=True, text=True, check=True).stdout.strip()
    git_dir_path = Path(git_dir)
    if not git_dir_path.is_absolute():
        git_dir_path = repo / git_dir_path
    # Mark the second commit as the retained shallow boundary.  Both it and
    # HEAD exist locally, so the clock has every object it needs even though
    # history before the boundary is intentionally unavailable.
    (git_dir_path / "shallow").write_text(shas[1] + "\n", encoding="utf-8")
    assert G.repository_is_shallow(repo) is not None
    age = G.git_age_days(repo, "HEAD")
    assert age(shas[1]) == 3.0, (
        "the retained shallow-boundary commit stopped resolving")


def test_a_truncated_clone_names_the_truncation_and_a_remedy(tmp_path):
    r, shas = _repo(tmp_path)
    shallow = _shallow_clone_of(r, tmp_path / "sh", depth=1)
    if G.repository_is_shallow(shallow) is None:
        pytest.skip("git did not produce a shallow clone here")
    led = tmp_path / "led.json"
    led.write_text(json.dumps({"acknowledged": [
        _ack(r, "g", shas[0], 1)]}), encoding="utf-8")
    rec = _rec_file(tmp_path, {"g": "FAIL"})
    out = _cli(shallow, rec, "--ledger", str(led)).stdout
    assert "SHALLOW clone" in out, out
    assert "fetch --unshallow" in out, out


def test_a_full_repository_with_a_bad_sha_does_not_blame_shallowness(tmp_path):
    """The direction that keeps the explanation honest: a row citing a commit
    that never existed is the ROW's defect, and saying `the clone is truncated`
    there would point the reader at the wrong thing."""
    r, _ = _repo(tmp_path)
    assert G.repository_is_shallow(r) is None
    led = tmp_path / "led.json"
    led.write_text(json.dumps({"acknowledged": [
        {"gate": "g", "since": "0" * 40,
         "since_date": "2026-01-01T00:00:00+00:00",
         "max_days": 1}]}), encoding="utf-8")
    out = _cli(r, _rec_file(tmp_path, {"g": "FAIL"}), "--ledger", str(led)).stdout
    assert "unresolvable" in out.lower()
    assert "SHALLOW" not in out, out


# --------------------------------------------------------------------------
# A MERGE IS NOT AN AGE. The defect this clock was changed for, staged.
# --------------------------------------------------------------------------

def _assembly(tmp_path, branches=97):
    """`since` -> a base -> an assembly of `branches` merged side branches.

    Every commit is dated ONE DAY after `since` — including all 97 merges — so
    the assembly adds no elapsed time at all and adds a great deal of topology.
    That separates the two clocks cleanly: the commit count moves by hundreds,
    the calendar does not move at all, and any verdict that changes between the
    two trees changed because of the merge and nothing else.
    """
    r = tmp_path / "asm"
    r.mkdir()
    day1 = _FIXTURE_DAY.format(1)
    day2 = _FIXTURE_DAY.format(2)

    def git(*a, when=day2):
        return subprocess.run(
            ["git", "-C", str(r), *a], capture_output=True, text=True,
            check=False,
            env=dict(os.environ, GIT_AUTHOR_DATE=when,
                     GIT_COMMITTER_DATE=when))

    git("init", "-q", "-b", "trunk")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (r / "seed").write_text("x", encoding="utf-8")
    git("add", "-A"); git("commit", "-q", "-m", "since", when=day1)
    since = git("rev-parse", "HEAD").stdout.strip()
    (r / "base").write_text("x", encoding="utf-8")
    git("add", "-A"); git("commit", "-q", "-m", "base")
    before = git("rev-parse", "HEAD").stdout.strip()

    for b in range(branches):
        git("checkout", "-q", "-b", f"side{b}", since)
        (r / f"s{b}").write_text("x", encoding="utf-8")
        git("add", "-A"); git("commit", "-q", "-m", f"side{b}")
        git("checkout", "-q", "trunk")
        git("merge", "-q", "--no-ff", "-m", f"merge side{b}", f"side{b}")
    return r, since, before, git("rev-parse", "HEAD").stdout.strip()


def test_a_ninety_seven_branch_merge_does_not_move_either_verdict(tmp_path):
    """The measurement that changed the clock, reproduced as a fixture.

    MEASURED 2026-08-22 on `land/two-assembled`: the five shipped rows read
    1590-2109 commits against bounds of 140-210 and ALL FIVE would have been
    called expired — by an assembly none of their authors had anything to do
    with. Here the same shape is built deliberately: 97 side branches merged in,
    every one of them dated the same day as the tree before the assembly.

    Both directions are checked, because a clock that never expires anything
    would also pass a one-directional version of this test. The live row must
    stay live and the overdue row must stay overdue.
    """
    r, since, before, after = _assembly(tmp_path)

    n_before = int(subprocess.run(
        ["git", "-C", str(r), "rev-list", "--count", f"{since}..{before}"],
        capture_output=True, text=True).stdout)
    n_after = int(subprocess.run(
        ["git", "-C", str(r), "rev-list", "--count", f"{since}..{after}"],
        capture_output=True, text=True).stdout)
    assert n_after > n_before + 100, (
        f"the fixture did not actually inflate the topology ({n_before} -> "
        f"{n_after}), so it cannot demonstrate anything about a merge")

    live = _ack(r, "g", since, 3)          # 1 day old, bound 3 days
    overdue = _ack(r, "g", since, 0.5)     # 1 day old, bound half a day
    red = _record({"g": "FAIL"})

    for label, row, expect in (("live", live, False), ("overdue", overdue, True)):
        was = [f.kind for f in G.adjudicate(
            red, [row], G.git_age_days(r, before))[0]]
        now = [f.kind for f in G.adjudicate(
            red, [row], G.git_age_days(r, after))[0]]
        assert ("expired" in was) is expect, (label, was)
        assert now == was, (
            f"the {label} row's verdict moved across a {n_after - n_before}-"
            f"commit merge that added no elapsed time: {was} -> {now}")

    # AND THE CLOCK THAT WAS REPLACED WOULD HAVE FLIPPED IT. Without this the
    # test above could pass on a fixture too small to reproduce the defect, and
    # would then be asserting that nothing happens rather than that this clock
    # is immune to something that really does happen.
    assert n_after > 3 >= n_before, (
        f"a commit-count bound of 3 would not have straddled this assembly "
        f"({n_before} -> {n_after}), so the old clock's failure is not "
        f"reproduced and the immunity above is untested")


def test_a_row_whose_commit_cannot_be_dated_is_not_checked_rather_than_expired(
        tmp_path):
    """rc 2, NOT rc 0 and NOT rc 1.

    "I could not read this row's date" must not reach a reader as "the deadline
    is fine", and must not reach one as "the deadline has passed" either. The
    row is NAMED, and the exit code says no verdict was reached.
    """
    r, shas = _repo(tmp_path)
    ledger = tmp_path / "led.json"
    ledger.write_text(json.dumps({"acknowledged": [
        {"gate": "g", "since": "0" * 40,
         "since_date": "2026-01-01T00:00:00+00:00", "max_days": 1}]}),
        encoding="utf-8")
    rec = tmp_path / "rec.json"
    rec.write_text(json.dumps(_record({"g": "FAIL"})), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(PROGRAMS / "gate_red_since_check.py"),
         "--record", str(rec), "--repo", str(r), "--ledger", str(ledger)],
        capture_output=True, text=True)
    assert out.returncode == 2, (out.returncode, out.stdout, out.stderr)
    assert "NOT CHECKED" in out.stdout, out.stdout
    assert "g" in out.stdout
    assert "expired" not in out.stdout.lower(), (
        "a row that could not be aged was reported as overdue")


def test_a_row_still_on_the_commit_bound_is_named_not_silently_unbounded(
        tmp_path):
    """The migration state: a row written under the clock this program replaced.

    It is NOT `incomplete` — the row was correct when it was written, and
    blaming it for a migration it could not have anticipated would send whoever
    reads the failure looking for a defect in the row. It is NOT adjudicated
    either: converting its commit bound into days here would be this program
    inventing a deadline nobody agreed to. rc 2, and the row is named.
    """
    r, shas = _repo(tmp_path)
    ledger = tmp_path / "led.json"
    ledger.write_text(json.dumps({"acknowledged": [
        {"gate": "g", "since": shas[0], "max_commits": 210}]}), encoding="utf-8")
    rec = tmp_path / "rec.json"
    rec.write_text(json.dumps(_record({"g": "FAIL"})), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(PROGRAMS / "gate_red_since_check.py"),
         "--record", str(rec), "--repo", str(r), "--ledger", str(ledger)],
        capture_output=True, text=True)
    assert out.returncode == 2, (out.returncode, out.stdout, out.stderr)
    assert "max_days" in out.stdout, out.stdout
    assert "incomplete" not in out.stdout, (
        "a row written under the previous clock was blamed as malformed")


def test_a_real_finding_beside_an_unreadable_row_still_exits_one(tmp_path):
    """rc 2 means "I reached no verdict", and that stops being true the moment
    another row genuinely failed. The unreadable row is still named."""
    r, shas = _repo(tmp_path)
    ledger = tmp_path / "led.json"
    ledger.write_text(json.dumps({"acknowledged": [
        {"gate": "unreadable", "since": "0" * 40,
         "since_date": "2026-01-01T00:00:00+00:00", "max_days": 1},
        _ack(r, "overdue", shas[0], _TIGHT_DAYS)]}), encoding="utf-8")
    rec = tmp_path / "rec.json"
    rec.write_text(json.dumps(
        _record({"unreadable": "FAIL", "overdue": "FAIL"})), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(PROGRAMS / "gate_red_since_check.py"),
         "--record", str(rec), "--repo", str(r), "--ledger", str(ledger)],
        capture_output=True, text=True)
    assert out.returncode == 1, (out.returncode, out.stdout, out.stderr)
    assert "expired" in out.stdout
    assert "NOT adjudicable" in out.stdout, (
        "the row that could not be aged was folded away by the real finding")
