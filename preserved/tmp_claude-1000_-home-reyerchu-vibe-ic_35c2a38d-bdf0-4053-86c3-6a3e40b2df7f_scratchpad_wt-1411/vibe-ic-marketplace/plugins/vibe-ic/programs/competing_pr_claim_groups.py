#!/usr/bin/env python3
"""Group open PRs by the ISSUE they claim, and name the groups that a merge
conflict can never surface (vibe-ic#1411).

WHY THIS EXISTS. The repo finds competing PRs the way git finds them: two
branches edit the same bytes and the merge conflicts. That answers "do these
touch the same file", which is a different question from "do these do the same
job" — and #1411 measured the gap: of the 22 issues carrying more than one open
PR, **16 have members that share no file at all**, so the mechanism in use
cannot report them. #1080 is the proven instance: two PRs shipped two different
schemas for one issue, each with its own passing tests, neither branch
containing the other's program.

WHAT THIS IS NOT. A group with no shared file is NOT thereby a duplicate.
#1241 has nineteen rows and four PRs is exactly right; #1097 names three
mechanisms and its PRs implement different ones. This tool refuses to call
those duplicates, because it cannot tell a complementary split from a
duplicate and neither can any file-based rule. What it CAN do is hand a
reviewer the short list that the conflict mechanism is structurally blind to,
so the judgement gets made by someone rather than skipped by everyone.

DESIGN — general core, thin adapter. Every rule below is a pure function over
plain dicts, so the whole thing is testable with no network and no GitHub. The
only fetching lives in `main`, which is a shell around `gh`. That split is
deliberate: a checker whose logic can only run against the live API is a
checker whose logic is never exercised in CI.

`INDEX.md` is discounted from "shares a file" because it is generated and ~27
open PRs touch it (#1363), so it makes unrelated PRs look related. Counting it
would report almost every pair as colliding and the signal would be gone.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Dict, FrozenSet, Iterable, List, Sequence, Tuple

# `Refs #N` is deliberately INCLUDED. #1407 uses `Refs` rather than `Closes`
# precisely because it fixes part of an issue, and a partial fix competing with
# another partial fix is exactly the case worth surfacing.
_BODY_CLAIM = re.compile(
    r"\b(?:closes|fixes|resolves|advances|refs|addresses)\s+#(\d+)",
    re.IGNORECASE)
# The trailing `(#N)` convention this repo uses in titles.
_TITLE_CLAIM = re.compile(r"\(#(\d+)\)")

# Generated files that carry no authorship signal; sharing one means nothing.
DISCOUNTED_PATHS: Tuple[str, ...] = ("programs/INDEX.md",)


def claimed_issues(title: str, body: str) -> FrozenSet[int]:
    """Which issue numbers does this PR say it addresses?

    Body keywords and the title's `(#N)` convention are both read, because the
    repo uses both and a PR that only puts the number in its title is not less
    of a claim.
    """
    out = {int(n) for n in _BODY_CLAIM.findall(body or "")}
    out |= {int(n) for n in _TITLE_CLAIM.findall(title or "")}
    return frozenset(out)


def _significant_files(paths: Iterable[str]) -> FrozenSet[str]:
    """Changed paths minus the generated ones (see DISCOUNTED_PATHS)."""
    return frozenset(
        p for p in paths
        if not any(p.endswith(d) for d in DISCOUNTED_PATHS))


def group_by_claim(prs: Sequence[dict]) -> Dict[int, List[dict]]:
    """issue number -> the open PRs claiming it, for issues claimed by >1.

    A PR claiming several issues appears in each of their groups; that is
    correct, since it competes in each.
    """
    groups: Dict[int, List[dict]] = {}
    for pr in prs:
        for issue in claimed_issues(pr.get("title", ""), pr.get("body", "")):
            groups.setdefault(issue, []).append(pr)
    return {i: m for i, m in groups.items() if len(m) > 1}


def shares_a_file(members: Sequence[dict]) -> bool:
    """Would git surface these two as competing? True iff SOME pair overlaps.

    Pairwise, not a global intersection: three PRs where A and B overlap and C
    is disjoint IS visible to the conflict mechanism, because A and B collide.
    A global intersection would be empty here and would wrongly report the
    group invisible.
    """
    sets = [_significant_files(m.get("files", ())) for m in members]
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            if sets[i] & sets[j]:
                return True
    return False


def invisible_groups(prs: Sequence[dict]) -> List[Tuple[int, List[dict]]]:
    """Claim-groups no merge conflict can report, lowest issue first."""
    return sorted(
        ((issue, members) for issue, members in group_by_claim(prs).items()
         if not shares_a_file(members)),
        key=lambda t: t[0])


def invisible_pairs(prs: Sequence[dict]) -> List[Tuple[int, int, int]]:
    """(issue, pr_a, pr_b) for every same-issue PAIR sharing no file.

    THE PAIR IS THE RIGHT UNIT, and #1080 is the proof — measured 2026-08-13.
    Its group is #1122/#1150/#1205. The confirmed duplicate is #1150 x #1205,
    which share nothing. But #1122 x #1205 share `programs/step_metrics.py` and
    its test, so the GROUP collides and a group-level report calls it visible —
    while the duplicate pair inside it stays invisible.

    Group granularity therefore hides the very case the group was cited for.
    Six of the groups #1411 counted as invisible are visible as groups and still
    contain invisible pairs; reporting groups alone loses them in both
    directions.
    """
    out: List[Tuple[int, int, int]] = []
    for issue, members in sorted(group_by_claim(prs).items()):
        ranked = sorted(members, key=lambda m: m["number"])
        for i, a in enumerate(ranked):
            fa = _significant_files(a.get("files", ()))
            for b in ranked[i + 1:]:
                if not (fa & _significant_files(b.get("files", ()))):
                    out.append((issue, a["number"], b["number"]))
    return out


# ---------------------------------------------------------------------------
# thin adapter — the only part that talks to GitHub
# ---------------------------------------------------------------------------
_Q = """
query($cur: String) {
  repository(owner:"vibeic", name:"vibe-ic") {
    pullRequests(states:OPEN, first:50, after:$cur) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { number title body files(first:100){nodes{path}} } } } }
"""


def fetch_open_prs() -> List[dict]:
    """Every open PR, paginated to exhaustion with the denominator ASSERTED.

    Refuses rather than returning a partial list: a short read here would
    silently shrink every group and report fewer competing PRs than exist,
    which is the failure mode this tool is meant to remove.
    """
    nodes: List[dict] = []
    cur, total = None, None
    while True:
        cmd = ["gh", "api", "graphql", "-f", f"query={_Q}"]
        if cur:
            cmd += ["-F", f"cur={cur}"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f"REFUSING: gh failed: {proc.stderr[:200]}")
        page = json.loads(proc.stdout)["data"]["repository"]["pullRequests"]
        total = page["totalCount"]
        for n in page["nodes"]:
            nodes.append({
                "number": n["number"], "title": n["title"],
                "body": n.get("body") or "",
                "files": [f["path"] for f in n["files"]["nodes"]]})
        if not page["pageInfo"]["hasNextPage"]:
            break
        cur = page["pageInfo"]["endCursor"]
    if len(nodes) != total:
        raise SystemExit(f"REFUSING: fetched {len(nodes)} of totalCount {total}")
    return nodes


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prs-json", help="read PRs from a file instead of the "
                                       "API: [{number,title,body,files}]")
    args = ap.parse_args(argv)

    if args.prs_json:
        prs = json.loads(open(args.prs_json).read())
    else:
        prs = fetch_open_prs()

    groups = group_by_claim(prs)
    invisible = invisible_groups(prs)
    pairs = invisible_pairs(prs)
    total_pairs = sum(len(m) * (len(m) - 1) // 2 for m in groups.values())
    print(f"open PRs                                  {len(prs)}")
    print(f"issues with >1 open PR                    {len(groups)}")
    print(f"  whole group cannot collide              {len(invisible)}")
    print(f"same-issue PR PAIRS                       {total_pairs}")
    print(f"  pairs a merge conflict cannot report    {len(pairs)}")
    if pairs:
        print("\ncompeting PAIRS invisible to conflict detection:")
        last = None
        for issue, a, b in pairs:
            head = f"#{issue}" if issue != last else ""
            print(f"  {head:<8}#{a} x #{b}")
            last = issue
        print("\nNOTE: 'cannot collide' is NOT 'duplicate' — a split across "
              "several mechanisms lands here too. This is the list nothing "
              "else can produce, not a verdict. The PAIR is the unit: #1080's "
              "group collides (via #1122 x #1205) while its duplicate pair "
              "#1150 x #1205 does not, so group granularity would hide it.")
    # Advisory by construction: this reports, it does not fail a landing.
    return 0


if __name__ == "__main__":
    sys.exit(main())
