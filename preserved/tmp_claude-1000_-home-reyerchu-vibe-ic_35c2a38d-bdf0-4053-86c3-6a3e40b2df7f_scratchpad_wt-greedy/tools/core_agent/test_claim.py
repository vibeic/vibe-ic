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


def _c(body, t):
    return {"body": body, "created_at": t}


def _fake(existing):
    """A transport whose POST appends to the same list the re-read returns."""
    store = list(existing)

    def post(repo, number, body):
        store.append(_c(body, "2026-08-13T05:00:10Z"))

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
