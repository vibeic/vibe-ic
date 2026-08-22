#!/usr/bin/env python3
"""An inherited BLOCKING red must be OWNED, and the ownership must EXPIRE.

WHAT THIS FILE MAKES UNREPEATABLE
=================================
`landing_merge_verdict` subtracts a failure present on BOTH arms — "gate fails
on the base too, so it is not this branch's", and for the hygiene tier
"…carried (which do NOT block)". That subtraction is correct: an absolute "any
FAIL refuses" would refuse every landing, which the comment above the gate
differential measures. What it had was no floor.

MEASURED, and this file exists because of it: `flow-gate enforcement audit` is
dispatched with a plain blocking `run` at `tools/ci/repo_hygiene_gates.sh`, was
red on the base at `e4880703b` on 2026-08-12, and was still red at `752a8baa`
nine days, 704 commits and 96 version-bearing landings later. Three other lanes
reached the same wall from three other directions: an always-run BLOCKING gate
green at `9cc09b863~1` and red from v1.11.5 through v1.11.18 with correct wiring
blocking nothing; `ci_targeted_test_select --base 7fcbc7397~1` selecting 325
tests including 16 `test_matrix_*` whose red was never acted on; and the ninth
matrix dimension, built around whether a step's verdict is CONSUMED.

The deadline itself was already built — `max_days` in
`tools/ci/gate_red_since.json`, read by `gate_red_since_check` — and nothing
ever opened it, because a row is voluntary and pure cost so no row is ever
written. These tests pin the forcing function, in BOTH directions, and mutate
the ledger in the four ways a future author would reach for to make a red quiet.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process node.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_red_since_check as G           # noqa: E402
import landing_merge_verdict as V          # noqa: E402


# ----------------------------------------------------------------- the fixture

#: Ages, in DAYS behind the endpoint, for the synthetic `since` shas below.
#: Injected rather than built from a real history, exactly as `adjudicate`
#: intends: every branch stays reachable without a git repository per case,
#: INCLUDING the unresolvable one, which by definition cannot be staged with a
#: real commit.
_AGE = {"since-recent": 0.5, "since-old": 5.0}

#: A stand-in date. Nothing here reads it as a clock — `_age` is the clock —
#: but a row without it is `incomplete`, a different finding from the ones
#: under test.
DATE = "2026-01-01T00:00:00+00:00"


def _age(sha: str):
    return _AGE.get(sha)


def _row(gate="repo hygiene: a blocking gate", since="since-recent",
         max_days=3, owner="#1025"):
    row = {"gate": gate, "since": since, "since_date": DATE, "owner": owner,
           "why": "a synthetic row, for this test only"}
    if max_days is not None:
        row["max_days"] = max_days
    return row


def _carried(*findings):
    """`hygiene_finding_delta`'s carried shape: (kind, label, corpus)."""
    return [tuple(f) for f in findings]


def _reasons(carried, ledger):
    return G.inherited_red_reasons(carried, ledger, _age)


# ------------------------------------------------- DIRECTION 1: it must REFUSE

def test_an_inherited_blocking_red_with_no_owner_refuses():
    """The state main was actually in: red on both arms, named by nobody."""
    out = _reasons(_carried(("FAIL", "repo hygiene: a blocking gate", "")), [])
    assert len(out) == 1, out
    assert "AN INHERITED RED WITH NO OWNER" in out[0]
    assert "repo hygiene: a blocking gate" in out[0]
    assert G.LEDGER_REL in out[0], "the refusal must name the file to edit"


def test_an_inherited_blocking_red_past_its_deadline_refuses():
    """THE DEADLINE, BITING. `since-old` is 5 days back, the bound is 3."""
    out = _reasons(_carried(("FAIL", "repo hygiene: a blocking gate", "")),
                   [_row(since="since-old", max_days=3)])
    assert len(out) == 1, out
    assert "THE DEADLINE ON AN INHERITED RED HAS PASSED" in out[0]
    assert "5 day(s) ago" in out[0]
    assert "was 3" in out[0]
    assert "#1025" in out[0], "the refusal must name the owner it has"


# -------------------------------------------------- DIRECTION 2: it must NOT

def test_an_inherited_red_owned_by_a_live_deadline_does_not_refuse():
    """The whole point of the ledger: a row with a live bound buys TIME, and
    that is the only thing it buys — the suite still exits 1 for the gate."""
    assert _reasons(_carried(("FAIL", "repo hygiene: a blocking gate", "")),
                    [_row(since="since-recent", max_days=5)]) == []


@pytest.mark.parametrize("kind", ["WROTE_CORPUS", "EXEMPTION_EXPIRED"])
def test_a_finding_that_is_not_a_blocking_red_does_not_stop_a_landing(kind):
    """THE MIRROR. A gate not declared always-run-and-BLOCKING must not be
    stopped by this rule.

    `WROTE_CORPUS` is a producer whose rc was never classified, and
    `EXEMPTION_EXPIRED` is the dispatcher's own dated-tolerance failure, which
    `_gate_dispatch.sh` already fails the sweep for. Neither is this rule's
    subject, and a rule that refused them would be refusing twice for one thing
    and once for something it never measured.
    """
    assert _reasons(_carried((kind, "some other gate", "")), []) == []


def test_a_red_that_is_NOT_inherited_is_not_this_rule_s_business():
    """A red present only on the candidate never reaches `carried`, so this rule
    never sees it — the label-level and finding-level rules already refuse it.
    Pinned so a future author does not 'helpfully' widen the input."""
    assert _reasons(_carried(), [_row()]) == []


# --------------------------------------------------------- THE MUTATION ARM
#
# Four ways a future author could make an inherited red quiet again. Each is the
# same fixture with ONE field moved, and each must still refuse.

def test_mutation_raising_the_bound_past_the_ceiling_cannot_buy_immortality():
    out = _reasons(_carried(("FAIL", "repo hygiene: a blocking gate", "")),
                   [_row(since="since-old", max_days=G.MAX_BOUND_DAYS + 1)])
    assert len(out) == 1, out
    assert "WITHOUT A REACHABLE DEADLINE" in out[0]
    assert G._days(G.MAX_BOUND_DAYS) in out[0]


def test_mutation_dropping_the_bound_is_not_an_acknowledgement():
    out = _reasons(_carried(("FAIL", "repo hygiene: a blocking gate", "")),
                   [_row(max_days=None)])
    assert len(out) == 1, out
    assert "WITHOUT A BOUND" in out[0]


def test_mutation_citing_a_commit_this_repo_does_not_have_is_not_fine():
    """'I could not check the deadline' must never read as 'the deadline is
    fine' — the rule this repository states about every other check."""
    out = _reasons(_carried(("FAIL", "repo hygiene: a blocking gate", "")),
                   [_row(since="a-commit-nobody-has")])
    assert len(out) == 1, out
    assert "CANNOT BE EVALUATED" in out[0]


def test_mutation_repointing_the_row_at_another_gate_unowns_this_one():
    """A row that drifts off its gate stops covering it, rather than covering
    whatever it now names by accident."""
    out = _reasons(_carried(("FAIL", "repo hygiene: a blocking gate", "")),
                   [_row(gate="a different gate entirely")])
    assert len(out) == 1, out
    assert "AN INHERITED RED WITH NO OWNER" in out[0]


def test_mutation_renewing_by_moving_since_forward_is_the_legitimate_act():
    """The one mutation that SHOULD silence it, so the arm above is a
    discriminator and not a rule that refuses everything."""
    expired = _row(since="since-old", max_days=3)
    assert _reasons(_carried(("FAIL", "repo hygiene: a blocking gate", "")),
                    [expired]) != []
    renewed = dict(expired, since="since-recent")
    assert _reasons(_carried(("FAIL", "repo hygiene: a blocking gate", "")),
                    [renewed]) == []


# ------------------------------------------- AND THE LANDING ACTUALLY REFUSES
#
# The rule above is a pure function; these two prove the VERDICT consumes it,
# which is the property the whole finding is about.

def _verdict(*, carried, ledger, age):
    """A LAND-OK baseline, borrowed verbatim from `test_landing_merge_verdict`'s
    own `_decide`, perturbed by exactly one fact: the carried list and the
    ledger. Borrowed rather than restated so this file cannot drift into
    asserting over a verdict shape the real one stopped producing."""
    import test_landing_merge_verdict as B
    return B._decide(
        base_land=V.parse_land_log(B._GOOD_LOG),
        hygiene={"status": V.HYG_CLEAN, "carried": carried, "introduced": [],
                 "cleared": [], "candidate_findings": len(carried),
                 "base_findings": len(carried), "declared": 1},
        red_since_ledger=ledger, commit_age=age)


def test_the_landing_refuses_an_inherited_red_past_its_deadline():
    v = _verdict(carried=_carried(("FAIL", "repo hygiene: a blocking gate", "")),
                 ledger=[_row(since="since-old", max_days=3)], age=_age)
    assert any("THE DEADLINE ON AN INHERITED RED HAS PASSED" in r
               for r in v.reasons), v.reasons


def test_the_landing_does_not_refuse_one_inside_its_deadline():
    v = _verdict(carried=_carried(("FAIL", "repo hygiene: a blocking gate", "")),
                 ledger=[_row(since="since-recent", max_days=5)], age=_age)
    assert not any("INHERITED RED" in r for r in v.reasons), v.reasons


def test_a_verdict_given_no_ledger_says_so_rather_than_reading_clean():
    """Rule nine, applied to this rule itself: not evaluated must not look like
    evaluated-and-clean."""
    v = _verdict(carried=_carried(("FAIL", "repo hygiene: a blocking gate", "")),
                 ledger=None, age=None)
    assert "INHERITED_RED_DEADLINE_NOT_EVALUATED" in v.disclosures
    assert not any("INHERITED RED" in r for r in v.reasons), v.reasons


def test_a_row_still_bounded_in_commits_refuses_and_names_the_migration():
    """The migration state, on the LANDING path.

    A row written under the clock this program replaced is a real
    acknowledgement whose bound cannot be evaluated as a duration. Converting
    it here would be this program inventing a deadline nobody agreed to, and
    staying silent would be "I could not check the deadline" reaching a reader
    as "the deadline is fine" — the rule this whole file exists to hold. So it
    refuses, and it NAMES what to do rather than leaving a reader to guess.
    """
    row = _row(max_days=None)
    row["max_commits"] = 210
    out = _reasons(_carried(("FAIL", "repo hygiene: a blocking gate", "")), [row])
    assert len(out) == 1, out
    assert "PREDATES THE DURATION CLOCK" in out[0], out[0]
    assert "max_days" in out[0]
    assert "WITHOUT A BOUND" not in out[0], (
        "a row that was correct when written was blamed as malformed")
