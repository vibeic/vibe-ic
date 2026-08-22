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


@pytest.fixture(scope="module")
def straddling_clock(rows):
    """`(age, behind)` for the clock read at a tree the row's bound can straddle.

    WHY THE DIRECTION TESTS BELOW CANNOT READ THE CLOCK AT `HEAD` ANY MORE, AND
    WHY THE ANSWER IS NOT A BIGGER BOUND.

    Each of them takes a shipped row and SYNTHESISES a bound either side of the
    red's measured age -- `behind - 1` must expire, `behind + 1` must not. That
    construction has a ceiling built into it that nothing declared: a bound is
    only legal up to `MAX_BOUND_COMMITS`, and once the age read at HEAD passes
    that ceiling NEITHER side can be built. `behind - 1` is refused as
    `unbounded` before the expiry clause is ever reached, and `behind + 1`
    clamps to the ceiling and lands BELOW the age, so it expires too. MEASURED
    on this tree: `rows[0]` is 941 commits old at HEAD, ceiling 500, and all
    three tests reported the wrong clause. Nothing about the ROWS changed --
    every shipped row was already past its bound on the base, and no verdict
    moves. What went dark is the PROOF.

    `MAX_BOUND_COMMITS` is a ceiling on how large a bound may be DECLARED. It
    is not a deadline, and raising it to fit a test would be raising a limit to
    make a measurement come out -- so the endpoint moves instead, which costs
    the tests nothing they were actually asserting. `git_age` already takes the
    tree the clock counts TO: it is the production `--head-ref`, and a landing
    passes its BASE for exactly this reason. Here it is handed a tree partway
    along the row's own real history, so `behind` is a distance a row is
    ALLOWED to declare a bound for, at any age the row ever reaches. `since` is
    untouched, the row is the shipped one, and the history is this repository's.

    The endpoint is MEASURED, not assumed: merges make "the Nth commit after
    `since`" and "N commits ahead of `since`" different numbers, so candidates
    are probed with the same `age` the adjudicator uses and the first one
    inside the window is returned.
    """
    since = str(rows[0]["since"])
    listing = subprocess.run(
        ["git", "-C", str(REPO), "rev-list", "--reverse", "--ancestry-path",
         f"{since}..HEAD"], capture_output=True, text=True).stdout.split()
    assert listing, (
        f"no commit of this repository lies between {since[:12]} and HEAD, so "
        f"no endpoint can be chosen and neither direction of the expiry rule "
        f"can be constructed here")
    hi = G.MAX_BOUND_COMMITS - 1
    for nth in (hi // 2, hi // 4, hi // 8, 32, 8, 2, 1):
        if not 0 < nth <= len(listing):
            continue
        at = G.git_age(REPO, listing[nth - 1])
        behind = at(since)
        if behind is not None and 1 < behind <= hi:
            return at, behind
    raise AssertionError(
        f"no tree between {since[:12]} and HEAD sits a declarable distance "
        f"(2..{hi}) from it, so the expiry rule cannot be exercised in either "
        f"direction on this history")


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
        bound = row["max_commits"]
        if not isinstance(bound, int) or isinstance(bound, bool):
            bad.append(f"{row['gate']} declares {bound!r}, not an int")
        elif not 0 < bound <= G.MAX_BOUND_COMMITS:
            bad.append(f"{row['gate']} declares {bound}, outside "
                       f"1..{G.MAX_BOUND_COMMITS}")
    assert not bad, f"{len(bad)} bound(s) are not bounds: " + "; ".join(bad)


# --------------------------------------------------------------------------
# THE EXPIRY BITES. Both directions, over the SHIPPED rows and real history.
# --------------------------------------------------------------------------

def test_a_row_whose_since_has_fallen_past_its_bound_refuses(
        rows, straddling_clock):
    """Direction one. Take a shipped row, leave `since` where the measurement
    put it, and set the bound BELOW the red's real age. It must fail.

    The clock is read at a tree the bound can straddle rather than at HEAD --
    see `straddling_clock` for why, and for what stayed the same.
    """
    age, behind = straddling_clock
    row = dict(rows[0])
    assert 1 < behind <= G.MAX_BOUND_COMMITS, behind
    row["max_commits"] = behind - 1
    findings, _, _ = G.adjudicate(
        _record({row["gate"]: "FAIL"}), [row], age)
    kinds = [f.kind for f in findings]
    assert "expired" in kinds, kinds
    assert str(behind) in " ".join(f.detail for f in findings), (
        "the refusal must say how far behind it actually is, not merely that "
        "it is behind")


def test_the_same_row_inside_its_bound_does_not_refuse(
        rows, straddling_clock):
    """Direction two, and it is the one that makes direction one mean
    something: if every row refused, `expired` would be a constant.

    The bound is `behind + 1` and is NOT clamped any more. Clamping was how
    this direction went dark: once the age passed the ceiling, `min(...)` chose
    the ceiling, which is BELOW the age, so the row expired and the test read
    that as the rule being broken. A bound the ceiling cannot express is a
    stimulus that no longer exists, not a smaller stimulus.
    """
    age, behind = straddling_clock
    row = dict(rows[0])
    row["max_commits"] = behind + 1
    assert row["max_commits"] <= G.MAX_BOUND_COMMITS, (
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
        tight, _, _ = G.adjudicate(red, [dict(row, max_commits=1)], age)
        loose, _, _ = G.adjudicate(
            red, [dict(row, max_commits=G.MAX_BOUND_COMMITS)], age)
        if not any(f.kind == "expired" for f in tight):
            never_expires.append(row["gate"])

        behind = age(row["since"])
        if behind is not None and behind > G.MAX_BOUND_COMMITS:
            # PAST THE CEILING, WHICH IS A DIFFERENT CLAUSE AND MUST BE SAID SO.
            # A red older than MAX_BOUND_COMMITS cannot be covered by ANY legal
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
        f"{len(never_expires)} row(s) do not expire even at a bound of 1: "
        f"{never_expires}")
    assert not past_ceiling, (
        f"{len(past_ceiling)} row(s) are past the ceiling of "
        f"{G.MAX_BOUND_COMMITS} and so must expire even at the ceiling: "
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
            _record({row["gate"]: "FAIL"}), [dict(row, max_commits=1)], age)
        if not any(f.kind == "expired" for f in expired):
            not_expiring.append(row["gate"])
        renewed, _, _ = G.adjudicate(
            _record({row["gate"]: "FAIL"}),
            [dict(row, since=head, max_commits=1)], age)
        if any(f.kind == "expired" for f in renewed):
            walled.append(row["gate"])
    assert not not_expiring, (
        f"{len(not_expiring)} row(s) do not expire at a bound of 1: "
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


def test_no_environment_variable_can_move_the_clock(rows, straddling_clock):
    """`adjudicate` takes (record, ledger, age) and nothing else, and this is
    the behavioural proof rather than a reading of the signature: a row that
    has expired stays expired with the environment stuffed with every name a
    reader might guess at.

    It needs an EXPIRED row to poison the environment around, and it built one
    the same way direction one did, so it went dark for the same reason. Same
    repair: the clock is read at a tree the bound can straddle.
    """
    age, behind = straddling_clock
    row = dict(rows[0])
    row["max_commits"] = behind - 1
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


# --------------------------------------------------------------------------
# THE CANDIDATE MUST NOT MOVE THE CLOCK.
# --------------------------------------------------------------------------

def _repo(tmp_path):
    """A history: since -> base -> three candidate commits."""
    r = tmp_path / "r"
    r.mkdir()
    def git(*a):
        return subprocess.run(["git", "-C", str(r), *a], capture_output=True,
                              text=True, check=False)
    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    shas = []
    for i in range(5):
        (r / f"f{i}").write_text(str(i), encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", f"c{i}")
        shas.append(git("rev-parse", "HEAD").stdout.strip())
    return r, shas


def test_the_clock_counts_to_the_ref_it_is_given(tmp_path):
    r, shas = _repo(tmp_path)
    since, base = shas[0], shas[1]
    assert G.git_age(r, base)(since) == 1
    assert G.git_age(r, "HEAD")(since) == 4


def test_a_candidates_own_commits_do_not_expire_a_row_it_never_touched(tmp_path):
    """MEASURED as a real defect on a 15-commit branch: 7 rows read as expired
    against its own head and 5 against origin/main, and two of the difference
    were rows the branch never touched. A landing therefore counts to the BASE
    — the same rule that requires the LEDGER to be the base's, for the same
    reason: a branch must not be able to change what counts as overdue, in
    either direction."""
    r, shas = _repo(tmp_path)
    since, base = shas[0], shas[1]
    row = {"gate": "some gate", "since": since, "max_commits": 2}
    red = _record({"some gate": "FAIL"})

    against_base, _, _ = G.adjudicate(red, [row], G.git_age(r, base))
    assert [f.kind for f in against_base] == [], (
        "one commit behind a bound of two must not be overdue")

    against_head, _, _ = G.adjudicate(red, [row], G.git_age(r, "HEAD"))
    assert any(f.kind == "expired" for f in against_head), (
        "four commits behind a bound of two must be overdue — otherwise this "
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
    def git(*a):
        return subprocess.run(["git", "-C", str(r), *a], capture_output=True,
                              text=True, check=False)
    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (r / "seed").write_text("x", encoding="utf-8")
    git("add", "-A"); git("commit", "-q", "-m", "seed")
    since = git("rev-parse", "HEAD").stdout.strip()

    # Commits BETWEEN `since` and the base, so a row bounded at 1 is genuinely
    # past its bound at the base rather than exactly on it — `adjudicate` fails
    # on `behind > bound`, and a fixture sitting on the boundary would prove
    # nothing about which ledger was read.
    for i in range(3):
        (r / f"b{i}").write_text("x", encoding="utf-8")
        git("add", "-A"); git("commit", "-q", "-m", f"base{i}")

    led = r / G.LEDGER_REL
    def write(rows):
        led.write_text(json.dumps({"acknowledged": rows}), encoding="utf-8")
    write([dict(row, since=since) for row in base_rows])
    git("add", "-A"); git("commit", "-q", "-m", "base ledger")
    base = git("rev-parse", "HEAD").stdout.strip()

    for i in range(4):                      # the candidate's own commits
        (r / f"c{i}").write_text("x", encoding="utf-8")
        git("add", "-A"); git("commit", "-q", "-m", f"cand{i}")
    write([dict(row, since=git("rev-parse", "HEAD").stdout.strip())
           for row in head_rows])
    git("add", "-A"); git("commit", "-q", "-m", "candidate renews the row")
    return r, since, base


def test_the_ledger_comes_from_the_ref_not_the_working_tree(tmp_path):
    r, since, base = _repo_with_ledger(
        tmp_path, [{"gate": "g", "max_commits": 1}],
        [{"gate": "g", "max_commits": 1}])
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
        tmp_path, [{"gate": "g", "max_commits": 1}],
        [{"gate": "g", "max_commits": 1}])
    red = _record({"g": "FAIL"})

    silenced, _, _ = G.adjudicate(
        red, G.load_ledger(r / G.LEDGER_REL), G.git_age(r, base))
    assert not any(f.kind == "expired" for f in silenced), (
        "the candidate's own ledger must be the one that WOULD silence it, or "
        "this test is not exercising the attack")

    held, _, _ = G.adjudicate(
        red, G.load_ledger_from_ref(r, base), G.git_age(r, base))
    assert any(f.kind == "expired" for f in held), (
        "reading the rows at the base did not keep the row overdue")


def test_a_ref_that_predates_the_ledger_is_empty_not_an_error(tmp_path):
    r, since, base = _repo_with_ledger(
        tmp_path, [{"gate": "g", "max_commits": 1}], [])
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
        tmp_path, [{"gate": "g", "max_commits": 1}], [])
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
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "gate_red_since_check.py"),
         "--record", str(record), "--repo", str(repo), *extra],
        capture_output=True, text=True, timeout=120)


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
    assert "ages counted to" in line


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
    row = {"gate": "g", "since": shas[0], "max_commits": 1}
    findings, known, new = G.adjudicate(
        _record({"g": state}), [row], G.git_age(r, "HEAD"))
    assert [f.kind for f in findings] == [], [f.line() for f in findings]
    assert "g" not in known and "g" not in new


@pytest.mark.parametrize("state", [G._LISTED, G._OTHER_SHARD, "OUT_OF_SCOPE", "QUEUED"])
def test_a_gate_that_did_not_run_is_not_counted_red(tmp_path, state):
    _, _, new = G.adjudicate(
        _record({"other": state}), [], G.git_age(tmp_path, "HEAD"))
    assert new == [], new


def test_the_mechanism_still_expires_a_gate_that_DID_run(tmp_path):
    """The direction that keeps the exemption honest: widening what cannot be
    adjudicated must not turn the deadline into something that never fires."""
    r, shas = _repo(tmp_path)
    row = {"gate": "g", "since": shas[0], "max_commits": 1}
    findings, _, _ = G.adjudicate(
        _record({"g": "FAIL"}), [row], G.git_age(r, "HEAD"))
    assert any(f.kind == "expired" for f in findings), [f.line() for f in findings]


def test_the_cli_names_the_rows_it_could_not_adjudicate(tmp_path):
    """Skipping them silently would let a row nobody judged read as a row that
    passed — which is the same silence this program exists to remove."""
    r, shas = _repo(tmp_path)
    led = tmp_path / "led.json"
    led.write_text(json.dumps({"acknowledged": [
        {"gate": "g", "since": shas[0], "max_commits": 1}]}), encoding="utf-8")
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
    repository is shallow — a `.git/shallow` written 2026-08-22 — and every
    `since` in the shipped ledger resolves in it anyway, because `--depth`
    truncates what a clone FETCHED, not what it later acquired. Refusing
    pre-emptively would have blocked every landing here over a condition that
    changes no verdict."""
    assert G.repository_is_shallow(REPO) is not None, (
        "this checkout is no longer shallow — the case below is still correct "
        "but this test no longer proves the distinction on it")
    age = G.git_age(REPO, "HEAD")
    rows = G.load_ledger(LEDGER)
    assert rows and all(age(r["since"]) is not None for r in rows), (
        "a shipped row stopped resolving in a shallow-but-complete checkout")


def test_a_truncated_clone_names_the_truncation_and_a_remedy(tmp_path):
    r, shas = _repo(tmp_path)
    shallow = _shallow_clone_of(r, tmp_path / "sh", depth=1)
    if G.repository_is_shallow(shallow) is None:
        pytest.skip("git did not produce a shallow clone here")
    led = tmp_path / "led.json"
    led.write_text(json.dumps({"acknowledged": [
        {"gate": "g", "since": shas[0], "max_commits": 1}]}), encoding="utf-8")
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
        {"gate": "g", "since": "0" * 40, "max_commits": 1}]}), encoding="utf-8")
    out = _cli(r, _rec_file(tmp_path, {"g": "FAIL"}), "--ledger", str(led)).stdout
    assert "unresolvable" in out.lower()
    assert "SHALLOW" not in out, out
