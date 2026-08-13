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

THE CLAIM GROUPING ALONE IS BLIND TO MOST OF THE QUEUE, measured 2026-08-14 on
this program's own branch: of eight PRs in four competing groups found by hand,
**six claim no issue at all**, so there was nothing to group them by. That is
structural rather than stylistic — the queue's own fallback instructs agents to
take a red that "no open issue covers", so the PRs most likely to duplicate each
other are exactly the ones with no issue to group by. So there are three
regions, and this program now covers all three:

    same bytes, conflicting     -> git reports it at merge
    same claimed issue          -> group_by_claim / invisible_pairs
    same FILE, no conflict,     -> path_overlap_pairs   (added for that miss)
      no claim

and one region where a report is not advice but a FACT:

    both CREATE the same path   -> add_add_pairs

An add/add pair can never both land whatever their merits, because git cannot
take both sides of an add/add, and neither PR's `mergeable` flag can show it —
that flag compares each PR to main and never to its batch-mates. Measured on the
same day: 196 open PRs, 194 of them MERGEABLE, and still four add/add pairs
among them, every one reporting MERGEABLE on both sides. Two were resolved that
afternoon (#1066 closed for #1336, #1239 closed for #1258) on exactly this
evidence, so this is the one output here that carries a verdict.
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
# region 3 — same FILE, no conflict, no shared claim
# ---------------------------------------------------------------------------
def default_hot_floor(n_prs: int) -> int:
    """How many open PRs must touch a path before it stops being a signal?

    Scaled to the queue rather than pinned, because the queue trebled in a week
    and a constant tuned at 100 PRs means something else at 300. Measured on the
    196-PR population of 2026-08-14, a 5% floor lands at 10 and separates the
    generated/registry files from the real ones:

        27  programs/INDEX.md                    generated       discounted
        14  tools/ci/repo_hygiene_gates.sh       registry        discounted
    ----------------------------------------------- floor = 10 ---------------
         9  flow/phase1_phase2_phase3.yaml       real            KEPT
         9  tests/test_matrix_d3_outputs_produced.py  real       KEPT

    The floor must sit ABOVE the flow yaml: its 9 PRs include #1239/#1258, a
    genuinely competing pair that this program exists to surface, so a floor
    that swallowed it would defeat the extension it is part of.
    """
    return max(5, (n_prs * 5 + 99) // 100)


def hot_paths(prs: Sequence[dict], floor: int) -> FrozenSet[str]:
    """Paths touched by MORE than `floor` open PRs — too common to mean anything."""
    counts: Dict[str, int] = {}
    for pr in prs:
        for p in _significant_files(pr.get("files", ())):
            counts[p] = counts.get(p, 0) + 1
    return frozenset(p for p, c in counts.items() if c > floor)


def stacked(prs: Sequence[dict]) -> FrozenSet[Tuple[int, int]]:
    """Pairs where one PR is BUILT ON the other — related, never competing.

    A stack shares files with its own parent by construction, so a path rule
    reports every stack as loudly as a duplicate. Measured on this program's
    own review: of 18 candidate pairs, FOUR were stacks (#1247<-#1262,
    #1328<-#1465, #1359<-#1386, #1396<-#1420) and the reviewer's top-ranked
    "duplicate" was one of them.

    Detected from `baseRefName`, which a stacked PR points at its parent's
    `headRefName` — exact, and free with the fetch we already do. TRANSITIVE,
    because the queue really does chain three deep (#1257 <- #1328 <- #1465),
    and stopping at one hop would call the ends of that chain competitors.
    """
    by_head = {p["headRefName"]: p["number"] for p in prs
               if p.get("headRefName")}
    parent = {p["number"]: by_head.get(p.get("baseRefName"))
              for p in prs if p.get("baseRefName") in by_head}
    out = set()
    for n in list(parent):
        seen, cur = set(), parent.get(n)
        while cur is not None and cur not in seen:
            seen.add(cur)
            out.add((min(n, cur), max(n, cur)))
            cur = parent.get(cur)
    return frozenset(out)


def path_overlap_pairs(prs: Sequence[dict],
                       floor: int | None = None
                       ) -> List[Tuple[int, int, float, List[str]]]:
    """(a, b, jaccard, shared) for PRs sharing a file but NO claimed issue.

    Ranked by Jaccard so an identical file set outranks a one-file brush; the
    output is meant to be read top-down by a person and truncated wherever they
    lose interest.

    Pairs that DO share a claimed issue are excluded, not because they matter
    less but because `invisible_pairs` already reports them and a reviewer
    reading two lists wants them disjoint.

    Like every other group here this is NOT a duplicate verdict — two PRs
    editing one file can be repairing two unrelated things in it. It is the
    short list the conflict mechanism cannot produce.
    """
    if floor is None:
        floor = default_hot_floor(len(prs))
    hot = hot_paths(prs, floor)
    stacks = stacked(prs)
    ranked = sorted(prs, key=lambda m: m["number"])
    out: List[Tuple[int, int, float, List[str]]] = []
    for i, a in enumerate(ranked):
        fa = _significant_files(a.get("files", ())) - hot
        ca = claimed_issues(a.get("title", ""), a.get("body", ""))
        if not fa:
            continue
        for b in ranked[i + 1:]:
            if ca & claimed_issues(b.get("title", ""), b.get("body", "")):
                continue
            if (min(a["number"], b["number"]),
                    max(a["number"], b["number"])) in stacks:
                continue
            fb = _significant_files(b.get("files", ())) - hot
            shared = fa & fb
            if not shared:
                continue
            out.append((a["number"], b["number"],
                        len(shared) / len(fa | fb), sorted(shared)))
    return sorted(out, key=lambda t: (-t[2], t[0], t[1]))


def add_add_pairs(prs: Sequence[dict]) -> List[Tuple[int, int, List[str]]]:
    """(a, b, paths) for PRs that CREATE the same path. Not advice — a fact.

    Git cannot take both sides of an add/add, so at most one of the pair can
    land however good both are, and no `mergeable` flag can say so because that
    flag never compares a PR to its batch-mates.

    `added` is read from the adapter's `changeType == "ADDED"`. A PR whose
    `added` key is absent contributes nothing here rather than falling back to
    `files`: guessing that every changed path is a new path would report the
    whole queue as un-landable, and a false certainty is worse than a silence in
    the one output of this program that carries a verdict.
    """
    ranked = [m for m in sorted(prs, key=lambda m: m["number"]) if "added" in m]
    out: List[Tuple[int, int, List[str]]] = []
    for i, a in enumerate(ranked):
        pa = _significant_files(a.get("added", ()))
        if not pa:
            continue
        for b in ranked[i + 1:]:
            shared = pa & _significant_files(b.get("added", ()))
            if shared:
                out.append((a["number"], b["number"], sorted(shared)))
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
      nodes { number title body headRefName baseRefName headRefOid updatedAt
              files(first:100){ totalCount nodes{ path changeType } } } } } }
"""
# A PR with more than 100 changed files needs its own pagination; the list
# query cannot page a nested connection per node.
_QF = """
query($n: Int!, $cur: String) {
  repository(owner:"vibeic", name:"vibe-ic") {
    pullRequest(number:$n) {
      files(first:100, after:$cur) {
        totalCount pageInfo { hasNextPage endCursor }
        nodes { path changeType } } } } }
"""


def _gh_graphql(query: str, **variables) -> dict:
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is not None:
            cmd += ["-F", f"{key}={value}"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"REFUSING: gh failed: {proc.stderr[:200]}")
    return json.loads(proc.stdout)["data"]["repository"]


def _all_files(number: int, first_page: dict) -> List[dict]:
    """Every changed file of one PR, or refuse.

    The list query returns at most 100 files per PR with no way to page a
    nested connection, so a PR over that limit arrives TRUNCATED and silently
    loses overlaps — the exact failure this program asserts against for the PR
    denominator, one level down. Re-fetch those to exhaustion and assert too.
    """
    nodes = list(first_page["nodes"])
    if first_page["totalCount"] <= len(nodes):
        return nodes
    nodes, cur = [], None
    while True:
        page = _gh_graphql(_QF, n=number, cur=cur)["pullRequest"]["files"]
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cur = page["pageInfo"]["endCursor"]
    if len(nodes) != first_page["totalCount"]:
        raise SystemExit(f"REFUSING: #{number} files {len(nodes)} of "
                         f"totalCount {first_page['totalCount']}")
    return nodes


def fetch_open_prs() -> List[dict]:
    """Every open PR, paginated to exhaustion with the denominator ASSERTED.

    Refuses rather than returning a partial list: a short read here would
    silently shrink every group and report fewer competing PRs than exist,
    which is the failure mode this tool is meant to remove.
    """
    nodes: List[dict] = []
    cur, total = None, None
    while True:
        page = _gh_graphql(_Q, cur=cur)["pullRequests"]
        total = page["totalCount"]
        for n in page["nodes"]:
            files = _all_files(n["number"], n["files"])
            nodes.append({
                "number": n["number"], "title": n["title"],
                "body": n.get("body") or "",
                "headRefName": n.get("headRefName"),
                "headRefOid": n.get("headRefOid"),
                "updatedAt": n.get("updatedAt"),
                "baseRefName": n.get("baseRefName"),
                "files": [f["path"] for f in files],
                "added": [f["path"] for f in files
                          if f.get("changeType") == "ADDED"]})
        if not page["pageInfo"]["hasNextPage"]:
            break
        cur = page["pageInfo"]["endCursor"]
    if len(nodes) != total:
        raise SystemExit(f"REFUSING: fetched {len(nodes)} of totalCount {total}")
    return nodes


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prs-json", help="read PRs from a file instead of the "
                                       "API: [{number,title,body,files,added}]")
    ap.add_argument("--hot-floor", type=int, default=None,
                    help="ignore paths touched by more than N open PRs "
                         "(default: 5%% of the queue, min 5)")
    ap.add_argument("--top", type=int, default=20,
                    help="how many path-overlap pairs to print (default 20)")
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

    floor = args.hot_floor if args.hot_floor is not None \
        else default_hot_floor(len(prs))
    hot = hot_paths(prs, floor)
    overlap = path_overlap_pairs(prs, floor)
    print(f"\nhot paths ignored (touched by >{floor} PRs)  {len(hot)}")
    for p in sorted(hot):
        print(f"      {p}")
    print(f"PRs sharing a FILE but claiming no common issue   {len(overlap)}")
    if overlap:
        print(f"\nranked by overlap, top {min(args.top, len(overlap))} of "
              f"{len(overlap)} — the region BOTH other lists miss:")
        for a, b, jac, shared in overlap[:args.top]:
            print(f"  #{a} x #{b}   overlap {jac:5.0%}  "
                  f"{len(shared)} file(s): "
                  f"{', '.join(s.rsplit('/', 1)[-1] for s in shared[:3])}"
                  f"{' …' if len(shared) > 3 else ''}")

    addadd = add_add_pairs(prs)
    scored = sum(1 for p in prs if "added" in p)
    tips = {p["number"]: (p.get("headRefOid") or "?")[:9] for p in prs}
    print(f"\npairs that CREATE the same path                   {len(addadd)}"
          f"   [{scored}/{len(prs)} PRs carry changeType]")
    if addadd:
        print("  AT MOST ONE OF EACH PAIR CAN LAND — git cannot take both "
              "sides of an add/add, and `mergeable` cannot see it:")
        for a, b, paths in addadd:
            print(f"  #{a} x #{b}   {len(paths)}: "
                  f"{', '.join(p.rsplit('/', 1)[-1] for p in paths[:3])}"
                  f"{' …' if len(paths) > 3 else ''}")
            # THE TIP EACH VERDICT WAS COMPUTED FROM, so the reader can re-verify
            # it instead of re-deriving it. Measured 2026-08-14: a branch in this
            # queue moved between one analysis fetching it and that analysis
            # finishing, and the stale ref said the PR no longer added the file at
            # all — the opposite of the truth. A pair reported here without its
            # tips cannot be checked later, because by then the tips have moved.
            print(f"          tips: #{a}@{tips.get(a, '?')}  #{b}@{tips.get(b, '?')}"
                  f"   (verify: git ls-remote origin <branch>)")
    elif scored:
        print("  none — every open PR creates paths no other open PR creates.")

    # Advisory by construction: this reports, it does not fail a landing.
    return 0


if __name__ == "__main__":
    sys.exit(main())
