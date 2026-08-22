#!/usr/bin/env python3
"""Which open issues carry no CLAIMED comment — with the un-readable ones NAMED.

WHY THIS EXISTS (vibe-ic#1464)
==============================
Every agent on the standing queue loop asks "what is unclaimed?" by hand:

    for n in $(gh issue list --repo R --state open --json number -q '.[].number'); do
      c=$(gh issue view $n --repo R --json comments \\
            -q '[.comments[].body]|map(select(startswith("CLAIMED:")))|length')
      [ "$c" = "0" ] && echo "#$n UNCLAIMED"
    done

Measured with a `gh` that fails the way an exhausted GraphQL budget does:

    budget exhausted          stdout 0 bytes, rc 0    d41d8cd98f00b204e9800998ecf8427e
    queue genuinely empty     stdout 0 bytes, rc 0    d41d8cd98f00b204e9800998ecf8427e

Byte-identical. `$c` is the empty string, `[ "" = "0" ]` is false, nothing
prints, and "I could not look" arrives at the caller as "there is nothing to
do" — which routes the agent to STOP. The inner half is worse: with the listing
healthy and the per-issue reads blocked, three issues that could NOT BE READ
print exactly like three issues that ARE claimed.

There are three ways this scan reports an absence it never measured, and all
three were measured on this repository:

    1. a failed call        an empty `$c` is not a count of zero claims
    2. `--limit` default 30 117 open issues, 30 returned, rc 0, and the output
                            is a well-formed newest-first list with nothing to
                            suggest 87 issues were never looked at
    3. comments capped 100  the one-call batched form (#1464's own remedy)
                            returns at most 100 comments per issue. #1241 has
                            387. A CLAIMED past the cap is invisible, so the
                            *negative* answer "unclaimed" is the one that
                            truncation can fabricate.

None of the three prints a denominator, so a scan that examined 30 of 117 is
indistinguishable from one that examined all of them.

WHAT IT REFUSES TO DO
=====================
* Report a count when the listing failed. rc 2, and NOTHING on stdout, so a
  caller's `N=$(...) || exit 1` fires instead of reading a fabricated zero.
* Report a count when the listing came back AT the cap. At the cap a full page
  and a truncated one are the same bytes, so the number would be a floor.
* Call an issue UNCLAIMED when its comments arrived at the per-issue cap and no
  claim was visible. A claim FOUND is positive evidence and survives truncation;
  a claim NOT FOUND under truncation is not evidence at all. Those issues are
  reported as UNMEASURED, by number, and they make the scan refuse.
* Accept a zero-issue listing without a second witness. On 2026-07-30 and again
  on 2026-08-13 a successful, well-formed, empty listing was wrong about this
  very repository (vibe-ic#554, #1319). A contradiction between the listing and
  the repository's own open count means the queue state is UNKNOWN, not empty.

It costs ONE call for the whole scan (two when the listing is empty, for the
witness), against `1 + N`: 118 calls for the 117 open issues measured here.
That is the difference between a fleet-wide budget that is exhausted in steady
state and one that is not — which is the same defect, one layer up, because an
exhausted budget is how (1) happens in the first place.

Exit: 0 scanned (a JSON summary carrying the DENOMINATOR on stdout),
      2 could not scan.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
# ONE `gh` invoker for every polling program in this directory. It was copied
# into this file and into its sibling, byte for byte — the shape of
# vibeic-eda#29, where two copies of `branch_is_ours` gave opposite answers
# about the same pins. The error encoding (127 not-installed / 126 could not
# run) is the part that must not drift, so it has one home.
from _gh_cli import gh as _gh  # noqa: E402
from typing import Any, Dict, List, Optional

RC_OK, RC_CANNOT_SCAN = 0, 2

#: Far above any plausible open-issue count for these repos, so reaching it
#: means something is wrong rather than that the repo is busy. Never left to
#: `gh`'s own default of 30, which is the truncation in mechanism (2).
DEFAULT_LIMIT = 1000

#: How many comments `gh issue list --json comments` returns per issue.
#: MEASURED, not assumed: #1241 came back with exactly 100 while the paginated
#: REST enumeration of the same issue returned 387. An issue at this many
#: comments has been truncated, so a missing claim there is unproven.
COMMENT_PAGE_CAP = 100

#: The claim protocol's prefix. A comment claims the issue when its body STARTS
#: with this, matched after leading whitespace only — a mention of the word
#: inside a paragraph is discussion, not a claim.
DEFAULT_MARKER = "CLAIMED:"

#: Below the landing harness's own bound, so a hung `gh` kills this call and
#: not the session around it.
_GH_TIMEOUT = 55

#: How many times the listing is attempted before the scan refuses.
#:
#: MEASURED 2026-08-14 on this repository, quota healthy throughout (core
#: 4942/5000, graphql 3873/5000), so this is not exhaustion and backing off for
#: a reset would be waiting on the wrong clock:
#:
#:     --json number             1 s
#:     --json number,title       2 s
#:     --json number,comments   23 s    <- the shape this scan needs
#:
#: `comments` costs ~20x and pushes the call past the gateway's patience;
#: `HTTP 504` came back on six separate attempts, three of them consecutive.
#: A retry cleared it every time it was tried again within seconds.
#:
#: THE RETRY DOES NOT SOFTEN THE REFUSAL, which is the whole subject of
#: vibe-ic#1464. After the last attempt the scan still exits 2 with nothing on
#: stdout, and the message says how many attempts were made — so "transient,
#: recovered" and "could not look" stay different answers, and the second one
#: never becomes a count.
_GH_ATTEMPTS = 3


def _claim_visible(comments: List[Dict[str, Any]], marker: str) -> bool:
    """Is a claim PRESENT in the comments we actually received?

    Only ever asked in the positive. A True here is evidence regardless of what
    else was truncated away; a False is evidence only when nothing was.
    """
    low = marker.lower()
    for c in comments:
        if not isinstance(c, dict):
            continue
        if (c.get("body") or "").lstrip().lower().startswith(low):
            return True
    return False


def _declared_open_count(repo: Optional[str]) -> Optional[int]:
    """The repository's own count of open issues, or None if unreadable.

    Asked ONLY when the listing came back empty, which is where a false zero
    does its damage and where one extra call is affordable. None is not zero:
    a witness that could not be reached has said nothing.
    """
    args = ["repo", "view", "--json", "issues"]
    if repo:
        args.insert(2, repo)
    rc, out, _err = _gh(args, timeout=_GH_TIMEOUT)
    if rc != 0:
        return None
    try:
        return int(json.loads(out or "{}")["issues"]["totalCount"])
    except (ValueError, TypeError, KeyError):
        return None


def scan(repo: Optional[str] = None, limit: int = DEFAULT_LIMIT,
         marker: str = DEFAULT_MARKER) -> dict:
    """Open issues split into claimed / unclaimed / unmeasured, in ONE call.

    Returns a dict carrying `scanned` (the denominator) on success and `error`
    when it could not be determined. Never returns an empty `unclaimed` list
    for a scan that did not happen.
    """
    args = ["issue", "list", "--state", "open", "--limit", str(limit),
            "--json", "number,title,comments"]
    if repo:
        args += ["--repo", repo]
    calls = 0
    for attempt in range(1, _GH_ATTEMPTS + 1):
        rc, out, err = _gh(args, timeout=_GH_TIMEOUT)
        calls += 1
        if rc == 0:
            break
        if attempt < _GH_ATTEMPTS:
            time.sleep(2 * attempt)
    if rc != 0:
        # The whole point. `gh` prints "GraphQL: API rate limit already
        # exceeded" here and returns nothing; the reason is quoted rather than
        # classified, because the caller needs to know WHICH wall it hit and a
        # second copy of that classification would drift from api_health's.
        return {"error": f"gh issue list failed (rc={rc}) after {calls} "
                         f"attempt(s): {(err or out).strip()[:200]}"}
    try:
        issues = json.loads(out or "[]")
    except ValueError as exc:
        return {"error": f"unparsable issue listing: {exc}"}
    if not isinstance(issues, list):
        return {"error": f"issue listing was {type(issues).__name__}, "
                         f"not a list"}
    if len(issues) >= limit:
        return {"error": f"issue listing came back at the --limit cap "
                         f"({limit}); the unclaimed set would be a floor, "
                         f"not a set"}

    unclaimed: List[int] = []
    unmeasured: List[str] = []
    claimed = 0
    for it in issues:
        num = it.get("number")
        comments = it.get("comments")
        if not isinstance(comments, list):
            # A 200 whose `comments` field is absent or null. The issue was
            # listed; its claims were not read. That is not "nobody claimed it".
            unmeasured.append(f"#{num}: comments field absent from the listing")
            continue
        if _claim_visible(comments, marker):
            claimed += 1
            continue
        if len(comments) >= COMMENT_PAGE_CAP:
            unmeasured.append(
                f"#{num}: no claim in the {len(comments)} comments returned, "
                f"but that is the per-issue cap — a claim past it would be "
                f"invisible, so 'unclaimed' here is unproven")
            continue
        unclaimed.append(num)

    witness: Dict[str, Any] = {"asked": False}
    if not issues:
        # A LISTING THAT CONFIDENTLY RETURNS ZERO IS THE ONE RESULT NOTHING
        # ABOVE CAN REFUSE: rc 0, well-formed, empty. It has been wrong about
        # this repository twice. Two sources agreeing is weak evidence; two
        # sources DISAGREEING proves one of them is wrong, and that is the
        # answer worth having.
        declared = _declared_open_count(repo)
        calls += 1
        witness = {"asked": True, "declared_open": declared}
        if isinstance(declared, int) and declared > 0:
            return {"error": f"the issue listing returned 0 open issues but the "
                             f"repository declares {declared} open — one of "
                             f"these is wrong, so the queue state is UNKNOWN, "
                             f"not empty"}

    return {"repo": repo, "scanned": len(issues), "claimed": claimed,
            "unclaimed": sorted(n for n in unclaimed if n is not None),
            "unclaimed_count": len(unclaimed),
            "unmeasured": unmeasured, "marker": marker,
            "zero_witness": witness, "calls": calls}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=None, help="OWNER/NAME (default: cwd's)")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--marker", default=DEFAULT_MARKER,
                    help=f"claim prefix (default: {DEFAULT_MARKER!r})")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    res = scan(a.repo, a.limit, a.marker)
    if a.json:
        # ATOMIC, and by hand (vibe-ic#1082). A direct `dest.write_text(...)`
        # creates the final name first and fills it after, so a crash mid-write
        # leaves a truncated report that the next reader cannot tell from a
        # complete one — which is this program's own subject, one layer over:
        # a half-written scan result is "I could not look" wearing the shape of
        # an answer.
        #
        # NOT through `_atomic_artefact`, which is what the gate's printed
        # remedy asks for, because that helper is not on main — and importing a
        # private helper that is not in the tree is itself a defect
        # (vibe-ic#1469). A new program cannot satisfy both gates through the
        # prescribed route until the helper lands, so it does the actual atomic
        # operation instead: write a sibling temp file, then `os.replace`, which
        # is atomic on the same filesystem. Switch to the helper when it exists.
        import os
        import tempfile
        from pathlib import Path
        dest = Path(a.json)
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"program": "open_issue_claim_scan", **res}, indent=2) + "\n"
        fd, tmp = tempfile.mkstemp(dir=str(dest.parent),
                                   prefix=dest.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, dest)
        except BaseException:
            # The temp file must not outlive a failed write, or the next run
            # inherits litter beside the report it is trying to publish.
            Path(tmp).unlink(missing_ok=True)
            raise

    if "error" in res:
        print(f"[NOT SCANNED] {res['error']}. This is NOT '0 unclaimed' — a "
              f"caller that reads an empty unclaimed set here would conclude "
              f"the queue is empty and stop (vibe-ic#1464).", file=sys.stderr)
        return RC_CANNOT_SCAN

    if res["unmeasured"]:
        # A floor is not a set. The scan ran, but some issues' claims were not
        # read, so "these are the unclaimed ones" is not something it can say.
        print(f"[NOT SCANNED] {len(res['unmeasured'])} of {res['scanned']} open "
              f"issue(s) could not have their claims read:\n  "
              + "\n  ".join(res["unmeasured"]), file=sys.stderr)
        return RC_CANNOT_SCAN

    print(json.dumps({"scanned": res["scanned"], "claimed": res["claimed"],
                      "unclaimed_count": res["unclaimed_count"],
                      "unclaimed": res["unclaimed"]}, indent=1))
    w = res["zero_witness"]
    if w.get("asked") and w.get("declared_open") is None:
        # Named rather than fatal: the listing itself succeeded, so refusing
        # here would halt a genuinely quiet queue every time one extra call
        # hiccups — and a check that blocks real work is a check that gets
        # switched off.
        print("[UNWITNESSED] the listing returned 0 open issues and the "
              "repository's own open count could not be read, so this zero "
              "rests on a single source.", file=sys.stderr)
    print(f"[OK] {res['unclaimed_count']} unclaimed of {res['scanned']} open "
          f"issue(s) examined ({res['claimed']} claimed) in {res['calls']} "
          f"call(s) — the denominator is the point: a scan that saw 30 of 117 "
          f"prints the same unclaimed set as one that saw all of them "
          f"(vibe-ic#1464)"
          + (f"; unclaimed: {res['unclaimed']}" if res["unclaimed"] else ""),
          file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
