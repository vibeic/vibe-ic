#!/usr/bin/env python3
"""The claim protocol is only worth anything if LOSING is detected.

Every test here drives the losing path or a path where the claim cannot be
established. A module that always returned WON would pass a suite that only
tested the happy case, and would reproduce vibe-ic#1015 exactly — fourteen
agents, every one correctly claiming, every one proceeding.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claim as C  # noqa: E402


_NEXT_ID = [1000]


def _c(body, t, cid=None):
    if cid is None:
        _NEXT_ID[0] += 1
        cid = _NEXT_ID[0]
    return {"body": body, "created_at": t, "id": cid}


def _fake(existing, lands=True, when="2026-08-13T05:00:10Z"):
    """A transport whose POST appends to the same list the re-read returns.

    `post` RETURNS the comment it created — the seam contract the id-based
    liveness check needs, and the thing the real `gh api -X POST` was already
    handing back and this module was discarding.

    `lands=False` drives the case the whole protocol exists for: the POST
    reports success and the comment is not in the thread.
    """
    store = list(existing)

    def post(repo, number, body):
        created = _c(body, when)
        if lands:
            store.append(created)
        return created

    def fetch(repo, number):
        return list(store)
    return post, fetch


def test_the_earliest_claim_wins_and_a_later_one_yields():
    post, fetch = _fake([_c("CLAIMED: rival on 8HD-8", "2026-08-13T05:00:00Z")])
    rc = C.claim("r/r", 1, "issue", "me on 8HD-9", post=post, fetch=fetch)
    assert rc == 1, "a claim 10s later must YIELD"


def test_being_first_wins():
    post, fetch = _fake([])
    assert C.claim("r/r", 1, "issue", "me on 8HD-9", post=post, fetch=fetch) == 0


def test_a_claim_that_cannot_be_POSTED_is_refused_not_won():
    def post(repo, number, body):
        raise RuntimeError("graphql 0/5000")

    def fetch(repo, number):
        return []
    rc = C.claim("r/r", 1, "issue", "me on 8HD-9", post=post, fetch=fetch)
    assert rc == 2, "an unposted claim must never read as a win"


def test_a_claim_the_reread_CANNOT_SEE_is_refused_not_won():
    """#1302's silent failure: `gh pr comment` returned, the comment was absent.
    Posting is not evidence the claim exists; only the re-read is."""
    def post(repo, number, body):
        return None                      # "succeeds", writes nothing

    def fetch(repo, number):
        return []
    rc = C.claim("r/r", 1, "issue", "me on 8HD-9", post=post, fetch=fetch)
    assert rc == 2


def test_a_reread_that_FAILS_is_refused_not_won():
    def post(repo, number, body):
        return None

    def fetch(repo, number):
        raise RuntimeError("rate limited")
    assert C.claim("r/r", 1, "issue", "x on h", post=post, fetch=fetch) == 2


def test_the_two_queues_use_DIFFERENT_markers():
    """A PR verification must not be able to satisfy an issue claim, or the two
    queues would silently share a namespace."""
    assert C.MARKERS["issue"] != C.MARKERS["pr"]
    post, fetch = _fake([_c("VERIFYING: rival on h", "2026-08-13T04:00:00Z")])
    # an older VERIFYING claim is invisible to an ISSUE claim, and vice versa
    assert C.claim("r/r", 1, "issue", "me on h", post=post, fetch=fetch) == 0


def test_ordering_is_by_TIMESTAMP_not_by_api_order():
    """The tie-break must be identical for every agent. Sorting by the order the
    API happened to return would give two agents two different winners."""
    rows = C.claims_in([_c("CLAIMED: b", "2026-08-13T05:00:05Z"),
                        _c("CLAIMED: a", "2026-08-13T05:00:01Z")], "CLAIMED:")
    assert [b for _t, b in rows] == ["CLAIMED: a", "CLAIMED: b"]


# ---------------------------------------------------------------------------
# THE FOUR ROWS — prior-claim x did-the-POST-land (#1303 review, 09:10Z)
# ---------------------------------------------------------------------------
# The liveness check used to be `b.strip() == body`, a pure function of the
# IDENTITY. Any claim the same agent had posted earlier satisfied it, so for an
# agent with history the check was non-empty BY CONSTRUCTION, whatever the POST
# did. Row 4 is the one that costs: post() reports success, the comment is not
# in the thread, and the agent is told WON off its own earlier comment.
#
# Reachable, not hypothetical: on #1241 two identities each hold TWO claim
# comments, and `--who` is stable across a restart, a resumed session and a
# retry loop by design — so a repeat claim is what all three look like.
#
# Note the asymmetry these pin: the missing `--paginate` fails CLOSED (a false
# REFUSED, one agent loses a minute); this one failed OPEN (a false WON, two
# agents take the same work).
_PRIOR = "2026-08-13T02:21:18Z"


def _rows_case(prior: bool, lands: bool):
    existing = [_c("CLAIMED: me on 8HD-d", _PRIOR)] if prior else []
    post, fetch = _fake(existing, lands=lands)
    return C.claim("r/r", 1, "issue", "me on 8HD-d", post=post, fetch=fetch)


def test_row1_no_prior_claim_and_the_post_LANDS_behind_a_rival_yields():
    post, fetch = _fake([_c("CLAIMED: rival on 8HD-8", "2026-08-13T05:00:00Z")])
    assert C.claim("r/r", 1, "issue", "me on 8HD-d", post=post, fetch=fetch) == 1


def test_row2_no_prior_claim_and_the_post_DOES_NOT_LAND_is_refused():
    """The guard's original purpose, and it already worked here."""
    assert _rows_case(prior=False, lands=False) == 2


def test_row3_a_prior_claim_and_the_post_LANDS_still_WINS():
    """A restart must not yield to itself. This is why the ORDERING half stays
    keyed on identity even though the LIVENESS half no longer is."""
    assert _rows_case(prior=True, lands=True) == 0


def test_row4_a_prior_claim_and_the_post_DOES_NOT_LAND_is_REFUSED_not_WON():
    """The false WON. Before the fix this returned 0 and the agent proceeded,
    deciding off a comment from `2026-08-13T02:21:18Z`."""
    assert _rows_case(prior=True, lands=False) == 2, (
        "an agent with prior history was told it WON on a claim that never "
        "landed — the guard was satisfied by its own earlier comment")


def test_a_POST_that_names_no_comment_refuses_rather_than_guessing():
    """Fail closed when the seam cannot identify what it created. Falling back
    to identity matching here would restore the exact defect above, quietly."""
    def post(repo, number, body):
        return None                      # "succeeded", identified nothing

    def fetch(repo, number):
        return [_c("CLAIMED: me on 8HD-d", _PRIOR)]
    assert C.claim("r/r", 1, "issue", "me on 8HD-d", post=post, fetch=fetch) == 2


def test_the_comment_LIST_is_paginated():
    """`per_page=100` alone truncated #1241 — the issue this program was written
    for — to 100 of 494 comments, so four fifths of the thread was invisible and
    a claim outside page one read as absent.

    MEASURED 2026-08-14, gh 2.97.0, against the live thread:
        per_page=100 alone -> 100     --paginate -> 494
    """
    import inspect
    # The BODY, not the docstring: that docstring explains why `--slurp` is not
    # used, so a naive source scan reads its own prose and asserts nothing.
    src = inspect.getsource(C._gh_list).replace(C._gh_list.__doc__ or "", "")
    assert "--paginate" in src, (
        "the comment list is not paginated, so a claim past the first page is "
        "invisible and this program refuses a claim that is really there")
    assert "--slurp" not in src, (
        "--slurp returns an array OF PAGES, which would hand this function a "
        "list of lists; gh merges array pages under --paginate alone")
