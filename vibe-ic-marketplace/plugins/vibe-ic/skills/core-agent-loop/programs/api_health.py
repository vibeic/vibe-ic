"""api_health — tell a SECONDARY rate limit from exhausted quota, and from a real 403.

vibe-ic#1319. Measured 2026-08-13: every REST call returned 403 with the body
`API rate limit exceeded for user ID …` while `gh api rate_limit` reported the
quota nearly untouched. `rate_limit` is itself exempt from the limit, so the one
diagnostic an agent reaches for keeps answering, and answers HEALTHY.

The three states need different responses and are indistinguishable by status
code alone:

    SECONDARY_LIMIT   403, rate-limit wording, quota REMAINING     -> back off;
                      retrying immediately extends the block, and the reset
                      time from `rate_limit` is the WRONG clock to wait on.
    QUOTA_EXHAUSTED   403/429, quota at zero                       -> wait for
                      the reset timestamp, which in this case is the right one.
    FORBIDDEN         403 with no rate-limit wording               -> a
                      permissions problem; waiting never fixes it.

WHY THIS IS A CORRECTNESS PROBLEM, NOT AN ERGONOMIC ONE
    The queue protocol is "post a claim, then RE-READ to see whether you won".
    Under a secondary limit BOTH halves fail the same way: the post 403s so no
    claim is recorded, and the re-read 403s so the collision is invisible. To
    the agent, "my claim failed" and "nobody claimed this" are the same
    observation — and the re-read exists precisely to make them different.

    So the rule this module exists to enforce: **an API failure is never
    evidence about the world.** It is never "no issues", never "no claims",
    never "not claimed by anyone". :func:`is_evidence` says so in one call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

HEALTHY = "HEALTHY"
SECONDARY_LIMIT = "SECONDARY_LIMIT"
QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
FORBIDDEN = "FORBIDDEN"
OTHER = "OTHER"

#: The wording GitHub uses for BOTH limit kinds, which is why it cannot be the
#: discriminator on its own — the quota counters are.
_LIMIT_WORDING = ("rate limit exceeded", "secondary rate limit",
                  "abuse detection", "exceeded a secondary")


def _message(payload: Any) -> str:
    if isinstance(payload, dict):
        return str(payload.get("message") or "")
    return str(payload or "")


def core_remaining(rate_limit_payload: Any) -> Optional[int]:
    """`remaining` for the core resource, or None when it cannot be read.

    None is NOT zero. A rate_limit response we could not parse tells us nothing
    about the quota, and folding it to 0 would report QUOTA_EXHAUSTED — sending
    the caller to sleep until a reset that is not the reason it is blocked.
    """
    try:
        res = rate_limit_payload["resources"]["core"]
        return int(res["remaining"])
    except (TypeError, KeyError, ValueError):
        return None


def classify(status: int, payload: Any,
             rate_limit_payload: Any = None) -> str:
    """One of the five states, from a failed call plus (optionally) the quota."""
    if status == 200:
        return HEALTHY
    msg = _message(payload).lower()
    looks_like_a_limit = any(w in msg for w in _LIMIT_WORDING)
    if status in (403, 429) and looks_like_a_limit:
        remaining = core_remaining(rate_limit_payload)
        if remaining is None:
            # Cannot tell which limit. SECONDARY is the safe answer: its advice
            # (back off, do not trust the reset clock) is also correct under
            # exhaustion, whereas the reverse is not.
            return SECONDARY_LIMIT
        return SECONDARY_LIMIT if remaining > 0 else QUOTA_EXHAUSTED
    if status == 403:
        return FORBIDDEN
    return OTHER


def is_evidence(status: int) -> bool:
    """Whether a response may be read as a statement ABOUT THE REPOSITORY.

    A 403 is a statement about our client. Reading an empty/failed response as
    "no open issues" or "nobody has claimed this" is the defect in #1319.
    """
    return status == 200


def advice(state: str, rate_limit_payload: Any = None) -> str:
    if state == SECONDARY_LIMIT:
        rem = core_remaining(rate_limit_payload)
        rem_txt = "unknown" if rem is None else str(rem)
        return ("SECONDARY rate limit (account-wide, abuse detection). Quota is "
                f"NOT the problem — core remaining={rem_txt}. `gh api rate_limit` "
                "is exempt from this limit, so it will keep reporting healthy. "
                "Back off; do NOT retry in a tight loop, and do NOT wait on the "
                "rate_limit reset — it is the wrong clock.")
    if state == QUOTA_EXHAUSTED:
        return ("Primary quota exhausted (core remaining=0). Wait for the reset "
                "timestamp from `gh api rate_limit`, which IS the right clock here.")
    if state == FORBIDDEN:
        return ("403 with no rate-limit wording: a permissions/scope problem. "
                "Waiting will never clear it.")
    if state == HEALTHY:
        return "OK."
    return "Unclassified API failure; treat the response as NO EVIDENCE."
