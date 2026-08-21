#!/usr/bin/env python3
"""Count OPEN issues whose title carries a marker, WITHOUT the search index.

WHY THIS EXISTS (vibe-ic#554, and #550 underneath it)
=====================================================
The Phase-1 coverage loop's STOP condition has three clauses, and clause (2) is
"zero open `ORGANIC-phase1-*` issues". Both the skill and the checker's own
docstring specify it as:

    gh issue list --search "ORGANIC-phase1 in:title" --state open

`--search` routes through GitHub's search INDEX, and that index currently
returns 0 for this repository regardless of content. Positive control, measured:

    gh issue list --search "Actions in:title" --state open   ->  0   WRONG
    gh issue list --state open, filtered on title locally    ->  1   correct

`#550` is open and has "Actions" in its title. So the search path returns 0 for
something that demonstrably exists, and N=0 satisfies clause (2): the loop
concludes there is nothing left to do and stops.

THE FAILURE IS THE SHAPE, NOT THE OUTAGE
========================================
A stale index is temporary. What is not temporary is that **a broken query and a
finished job produce the same number**, and the number is what the STOP decision
reads. That is the same class as #550 itself — an empty listing standing in for
a clean result — one layer up, and it is why this is a program rather than a
corrected line in a skill.

So this counts by LISTING and filtering locally, and it distinguishes:

    a real zero      the listing was read and no title matched     -> exit 0
    an unreadable    the listing could not be obtained             -> exit 2

The second must never be reported as `N=0`. A caller that cannot tell them apart
has the bug this file is about.

PAGINATION IS PART OF THE CORRECTNESS
=====================================
`gh issue list` defaults to 30. A repository with more than 30 open issues would
silently drop the ones past the limit and under-count — the same
truncation-reads-as-absence shape a third time. `--limit` is set high and the
count is refused if the listing comes back exactly at the cap, because at the
cap there is no way to know whether more were waiting.

Exit: 0 counted (the count is on stdout), 2 could not count.
"""
from __future__ import annotations

import argparse
import json
import sys
# ONE `gh` invoker for every polling program in this directory. It was copied
# into this file and into its sibling, byte for byte — the shape of
# vibeic-eda#29, where two copies of `branch_is_ours` gave opposite answers
# about the same pins. The error encoding (127 not-installed / 126 could not
# run) is the part that must not drift, so it has one home.
from _gh_cli import gh as _gh  # noqa: E402
from typing import List, Optional, Tuple

RC_OK, RC_CANNOT_COUNT = 0, 2

#: Deliberately far above any plausible open-issue count for these repos, so
#: hitting it means something is wrong rather than that the repo is busy.
DEFAULT_LIMIT = 1000


def count(marker: str, repo: Optional[str] = None,
          limit: int = DEFAULT_LIMIT) -> dict:
    """Open issues whose TITLE contains `marker`, matched locally.

    Returns a dict with `count` on success and `error` when it could not be
    determined. Never guesses, and never returns 0 for "I could not look".
    """
    args = ["issue", "list", "--state", "open", "--limit", str(limit),
            "--json", "number,title"]
    if repo:
        args += ["--repo", repo]
    rc, out, err = _gh(args)
    if rc != 0:
        return {"error": f"gh issue list failed (rc={rc}): "
                         f"{(err or out).strip()[:200]}"}
    try:
        issues = json.loads(out or "[]")
    except ValueError as exc:
        return {"error": f"unparsable issue listing: {exc}"}
    if not isinstance(issues, list):
        return {"error": f"issue listing was {type(issues).__name__}, not a list"}
    if len(issues) >= limit:
        # At the cap there is no way to tell a full page from a truncated one,
        # and under-counting here reads as "nothing left to do".
        return {"error": f"listing came back at the --limit cap ({limit}); the "
                         f"count would be a floor, not a count"}
    matched = [i for i in issues
               if marker.lower() in (i.get("title") or "").lower()]
    return {"count": len(matched), "scanned": len(issues),
            "numbers": sorted(i.get("number") for i in matched)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("marker", help="substring to match in the issue TITLE")
    ap.add_argument("--repo", default=None, help="OWNER/NAME (default: cwd's)")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    res = count(a.marker, a.repo, a.limit)
    if a.json:
        from pathlib import Path
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(
            {"program": "open_organic_issue_count", "marker": a.marker,
             **res}, indent=2) + "\n", encoding="utf-8")

    if "error" in res:
        print(f"[NOT COUNTED] {res['error']}. This is NOT zero — a caller that "
              f"passes 0 here would satisfy the STOP clause on a failed "
              f"measurement (vibe-ic#554).", file=sys.stderr)
        return RC_CANNOT_COUNT

    print(res["count"])
    print(f"[OK] {res['count']} open issue(s) with {a.marker!r} in the title, "
          f"out of {res['scanned']} scanned — listed and filtered locally, "
          f"never through the search index (vibe-ic#554)"
          + (f"; numbers: {res['numbers']}" if res["numbers"] else ""),
          file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
