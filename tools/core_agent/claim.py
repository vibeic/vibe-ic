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
import sys
from typing import Callable, Dict, List, Optional, Tuple

from pathlib import Path
# `_progress_run` lives in the plugin's `programs/`, which is not a sibling of
# this file. Walk UP until the directory that actually holds it is found, so
# this works from `tools/`, from `tools/<sub>/`, and from inside the flattened
# plugin cache where the marketplace path does not exist.
for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402

#: The two work queues, and the marker each uses. Kept in one place so a third
#: queue cannot be added with a marker nobody else recognises.
MARKERS: Dict[str, str] = {"issue": "CLAIMED:", "pr": "VERIFYING:"}


def _gh_post(repo: str, number: int, body: str) -> Optional[Dict]:
    """POST the claim and RETURN THE COMMENT IT CREATED.

    The response was previously discarded, and that is what made the re-read
    unable to tell "the comment I just posted" from "a comment I posted an hour
    ago" — see the `mine` note in :func:`claim`. The id is the only thing that
    distinguishes them, and the POST is the only place it is available.
    """
    out = _pr.run(
        ["gh", "api", "-X", "POST", f"repos/{repo}/issues/{number}/comments",
         "-f", f"body={body}"],
        check=True, capture_output=True, text=True).stdout
    doc = json.loads(out or "null")
    return doc if isinstance(doc, dict) else None


def _gh_list(repo: str, number: int) -> List[Dict]:
    """EVERY claim comment, not the first page of them.

    `--paginate` is load-bearing and its absence failed CLOSED in the worst
    possible place. MEASURED 2026-08-14 against the issue this program was
    written for, `#1241`, with `gh 2.97.0`:

        per_page=100 alone   ->  100 comments
        --paginate           ->  494 comments

    So four fifths of that thread were invisible, and an agent whose own claim
    sat outside the first page was told REFUSED — or, worse, read a stale
    `earliest` and yielded to somebody who was not first.

    `--paginate` alone is correct HERE and `--slurp` is not needed: gh merges
    JSON array pages into a single valid array (measured on 2.97.0 — 494 items,
    `json.loads` clean). `--slurp` instead returns an array OF PAGES, which
    would need flattening and would silently give this function a list of lists.
    """
    out = _pr.run(
        ["gh", "api", "--paginate",
         f"repos/{repo}/issues/{number}/comments?per_page=100"],
        check=True, capture_output=True, text=True).stdout
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
        created = post(repo, number, body)
    except Exception as exc:                       # noqa: BLE001
        print(f"REFUSED: the claim could not be POSTED ({exc}). Not proceeding "
              f"— an unposted claim wins every race by being invisible.")
        return 2

    # WHICH comment, not whose. The liveness check below used to be
    # `b.strip() == body`, which is a pure function of the IDENTITY and says
    # nothing about the POST that just ran. For an agent with any history on the
    # thread it was satisfied by its own older claim, so the one case it existed
    # for — post() returns success and the comment is not there — returned WON.
    # It failed OPEN, which is the expensive direction: two agents take the same
    # work. MEASURED on #1241, where two identities (mine among them) each hold
    # two claim comments, so the stale row was reachable today and not in theory.
    created_id = created.get("id") if isinstance(created, dict) else None
    if created_id is None:
        print("REFUSED: the POST did not identify the comment it created, so "
              "the re-read cannot tell it from an earlier claim by the same "
              "agent. Not proceeding — this is the check, not a formality.")
        return 2

    try:
        raw = fetch(repo, number)
    except Exception as exc:                       # noqa: BLE001
        print(f"REFUSED: the claim was posted but could not be RE-READ ({exc}). "
              f"Not proceeding — the re-read is the half that decides.")
        return 2
    rows = claims_in(raw, marker)

    landed = [c for c in raw
              if c.get("id") == created_id
              and str(c.get("body") or "").startswith(marker)]
    if not landed:
        # Posted, exit 0, and absent from the thread. Exactly the silent
        # GraphQL failure #1302 measured. Refuse rather than assume.
        print(f"REFUSED: posted a claim but the re-read does not contain THAT "
              f"comment ({len(rows)} claim(s) seen). Not proceeding.")
        return 2
    mine_t = str(landed[0].get("created_at") or "")

    # Ordering stays keyed on IDENTITY, deliberately. An agent that legitimately
    # re-claims a thread it already holds the earliest claim on must still WIN —
    # keying this on the new comment's timestamp would turn every restart and
    # every retry into a YIELD to itself.
    earliest_t, earliest_b = rows[0]
    if earliest_b.strip() == body:
        print(f"WON {kind} #{number} as {who} at {mine_t} "
              f"({len(rows)} claim(s) total)")
        return 0
    print(f"YIELD {kind} #{number} — {earliest_b.strip()[len(marker):].strip()} "
          f"claimed at {earliest_t}, mine at {mine_t}. Take the next item.")
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
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    raise SystemExit(_pr.exit_undetermined_on_stall(main))
