#!/usr/bin/env python3
"""claim.py — take a work item, then CHECK YOU WON IT. Both halves, mechanically.

WHY THIS EXISTS (vibe-ic#1015, #1044, #1302)
============================================
The fleet coordinates by posting a claim comment. Posting alone does not
coordinate anything, and the repo has now measured that twice:

    issues  2026-08-13   FOURTEEN agents claimed #1015; four claimed #1044.
                         Every one read the list in the same few seconds, every
                         one saw no claim, every one claimed correctly.
    PRs     2026-08-13   #1276 carried 4 verification runs, #1258 3, #1247 2 —
                         nine runs where three would do, at 10-30 min of
                         two-arm compute each. Roughly two machine-hours.

    "Reading before writing does not prevent a collision when everybody reads
     first — it only prevents the collision you can see."

The re-read AFTER writing is the load-bearing half: by then every competing
claim exists and carries a timestamp, so the earliest one can be identified.
This module makes that a function instead of a habit, because a protocol that
lives only in prose is followed only when remembered.

WHY REST AND NOT `gh pr comment` (#1302)
========================================
`gh pr comment` / `gh issue list` / `gh pr list` go through GraphQL, whose
5000/hr is shared by every agent on the account. Measured 2026-08-13 04:15:
`graphql 0/5000` while `core 4955/5000`. A verdict posted through the exhausted
budget SILENTLY FAILED TO APPEAR. So every call here uses the REST endpoint, and
`claim()` RE-READS to confirm its own comment is present rather than trusting
the exit code — a claim that was never posted would otherwise "win" every race
by being invisible.

EXIT CODES
    0  WON      — this agent holds the earliest claim; proceed
    1  YIELD    — an older claim exists; take the next item
    2  REFUSED  — the claim could not be established (post failed, or the
                  re-read cannot see it). NEVER treated as a win: an
                  unverifiable claim is the collision it exists to prevent.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Callable, Dict, List, Optional, Tuple

#: The two work queues, and the marker each uses. Kept in one place so a third
#: queue cannot be added with a marker nobody else recognises.
MARKERS: Dict[str, str] = {"issue": "CLAIMED:", "pr": "VERIFYING:"}


def _gh_post(repo: str, number: int, body: str) -> None:
    subprocess.run(
        ["gh", "api", "-X", "POST", f"repos/{repo}/issues/{number}/comments",
         "-f", f"body={body}"],
        check=True, capture_output=True, text=True, timeout=60)


def _gh_list(repo: str, number: int) -> List[Dict]:
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{number}/comments?per_page=100"],
        check=True, capture_output=True, text=True, timeout=60).stdout
    return json.loads(out or "[]")


def claims_in(comments: List[Dict], marker: str) -> List[Tuple[str, str]]:
    """`(created_at, body)` for every claim comment, EARLIEST FIRST.

    Sorted by the server's timestamp, never by the order the API returned them
    or by who noticed first — the tie-break has to be the same for every agent
    or it is not a tie-break.
    """
    rows = [(str(c.get("created_at") or ""), str(c.get("body") or ""))
            for c in comments
            if str(c.get("body") or "").startswith(marker)]
    return sorted(rows)


def claim(repo: str, number: int, kind: str, who: str,
          post: Optional[Callable[[str, int, str], None]] = None,
          fetch: Optional[Callable[[str, int], List[Dict]]] = None) -> int:
    """Post the claim, then re-read and decide. Returns an EXIT CODE."""
    marker = MARKERS[kind]
    body = f"{marker} {who}"
    post = post or _gh_post
    fetch = fetch or _gh_list
    try:
        post(repo, number, body)
    except Exception as exc:                       # noqa: BLE001
        print(f"REFUSED: the claim could not be POSTED ({exc}). Not proceeding "
              f"— an unposted claim wins every race by being invisible.")
        return 2
    try:
        rows = claims_in(fetch(repo, number), marker)
    except Exception as exc:                       # noqa: BLE001
        print(f"REFUSED: the claim was posted but could not be RE-READ ({exc}). "
              f"Not proceeding — the re-read is the half that decides.")
        return 2

    mine = [t for t, b in rows if b.strip() == body]
    if not mine:
        # Posted, exit 0, and absent from the thread. Exactly the silent
        # GraphQL failure #1302 measured. Refuse rather than assume.
        print(f"REFUSED: posted a claim but the re-read does not contain it "
              f"({len(rows)} claim(s) seen). Not proceeding.")
        return 2

    earliest_t, earliest_b = rows[0]
    if earliest_b.strip() == body and earliest_t == mine[0]:
        print(f"WON {kind} #{number} as {who} at {mine[0]} "
              f"({len(rows)} claim(s) total)")
        return 0
    print(f"YIELD {kind} #{number} — {earliest_b.strip()[len(marker):].strip()} "
          f"claimed at {earliest_t}, mine at {mine[0]}. Take the next item.")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("number", type=int)
    ap.add_argument("--kind", choices=sorted(MARKERS), default="issue")
    ap.add_argument("--who", required=True, help="<agent> on <host>")
    ap.add_argument("--repo", default="vibeic/vibe-ic")
    a = ap.parse_args(argv)
    return claim(a.repo, a.number, a.kind, a.who)


if __name__ == "__main__":
    raise SystemExit(main())
