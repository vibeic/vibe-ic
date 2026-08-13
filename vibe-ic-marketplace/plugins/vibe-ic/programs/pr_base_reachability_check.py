#!/usr/bin/env python3
"""pr_base_reachability_check.py — a PR whose base cannot reach `main` is not
landable, and `mergeable` cannot say so (vibe-ic#1364).

THE FALSE GREEN
===============
GitHub computes `mergeable` against the PR's OWN base, not against `main`. When
that base is the head branch of a PR that was CLOSED without merging, the PR
reports exactly what a healthy PR reports::

    #1290  state=open  base=fix/63x8-waiver-citations-reverified
           mergeable=MERGEABLE  mergeStateStatus=CLEAN

`CLEAN` there means "clean against a branch belonging to a closed PR". Merging it
would land the change INTO THAT DEAD BRANCH. Every batcher that reads the flag
sees a landable PR.

This is the worst shape a defect can take in this repository: not a missing
signal, but a **green one that everybody already reads**. The same class as a
gate that exits 0 having examined nothing — see `gate_skip_routing_check` — one
level up, in the queue rather than in the tree.

MEASURED 2026-08-13 over all 916 PRs (167 open): 17 open PRs have a base that is
not `main`; 13 are legitimately stacked on an open or merged parent; **4 are
rooted on a CLOSED-unmerged one**, and every one of the four reports
`MERGEABLE/CLEAN`. Two of the four are the root of a further stack, so **7 open
PRs cannot reach `main`** while none of them says so.

WHAT THIS CHECKS, AND WHAT IT DOES NOT
======================================
It answers one question — can this PR's base chain terminate at `main` — and
nothing else. It does not judge whether the PR is correct, whether it conflicts,
or whether the parent SHOULD have been closed. A stack on an OPEN parent is
healthy and is reported as such; the parent landing first is the normal order.

REFUSAL IS A VERDICT
====================
rc 2 when the population cannot be established: no PR data, or a base branch
whose owning PR is not in the input. "I read no PRs" and "I read PRs and found
no orphans" are different sentences and only the second is a pass. A check that
answers 0 over an unknown population is the disease this file exists to catch.

EXIT CODES
    0  every open PR's base chain terminates at `main`
    1  at least one does not (each named, with the closed parent and the stack
       above it)
    2  refused — the population could not be established
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Dict, Iterable, List, Optional, Set, Tuple

#: The branch every landable chain must terminate at.
TRUNK = "main"

RC_OK, RC_FAIL, RC_REFUSE = 0, 1, 2

#: The fields this check needs. Named once so a caller supplying its own JSON
#: knows exactly what to provide, and so the `gh` invocation cannot drift from
#: the projection below.
REQUIRED_FIELDS = ("number", "state", "headRefName", "baseRefName", "mergedAt")


def load_from_gh(repo: str, limit: int = 1000) -> Optional[List[dict]]:
    """Every PR in every state, or None when the CLI could not answer.

    ALL states, not just open: resolving a base branch to its owning PR is the
    entire mechanism, and the owner of an orphan's base is by definition closed.
    A scan over open PRs alone would resolve nothing and report a confident zero.
    """
    argv = ["gh", "pr", "list", "--repo", repo, "--state", "all",
            "--limit", str(limit), "--json", ",".join(
                REQUIRED_FIELDS + ("mergeable", "mergeStateStatus", "title"))]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=55)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        return None
    return doc if isinstance(doc, list) else None


def owners(prs: Iterable[dict]) -> Dict[str, dict]:
    """`head branch -> the PR that owns it`.

    When two PRs share a head branch an OPEN one wins, then the highest number.
    Sharing a head is itself irregular, but resolving it silently to the closed
    copy would manufacture an orphan that is not one.
    """
    out: Dict[str, dict] = {}
    for pr in sorted(prs, key=lambda p: (p.get("state") != "OPEN",
                                         -int(p.get("number") or 0))):
        ref = pr.get("headRefName")
        if ref:
            out.setdefault(ref, pr)
    return out


def is_dead_parent(pr: dict) -> bool:
    """CLOSED and never merged. A merged parent is fine — its commits are in."""
    return pr.get("state") == "CLOSED" and not pr.get("mergedAt")


def audit(prs: List[dict]) -> Tuple[List[dict], List[dict], List[int], Set[int]]:
    """`(orphans, unresolved, healthy_numbers, blocked)`.

    `orphans`  open PRs whose base is owned by a closed-unmerged PR
    `unresolved` open PRs whose base is neither `main` nor any PR's head — the
                 population is incomplete for them, so they are a REFUSAL and
                 never silently a pass
    `blocked`  orphans plus, transitively, every PR stacked above one
    """
    by_head = owners(prs)
    open_prs = [p for p in prs if p.get("state") == "OPEN"]
    orphans: List[dict] = []
    unresolved: List[dict] = []
    healthy: List[int] = []

    for pr in open_prs:
        base = pr.get("baseRefName")
        if base == TRUNK:
            healthy.append(int(pr["number"])); continue
        parent = by_head.get(base)
        if parent is None:
            unresolved.append(pr); continue
        if is_dead_parent(parent):
            orphans.append({"pr": pr, "parent": parent})
        else:
            healthy.append(int(pr["number"]))

    blocked: Set[int] = {int(o["pr"]["number"]) for o in orphans}
    changed = True
    while changed:                       # a stack inherits its root's fate
        changed = False
        for pr in open_prs:
            parent = by_head.get(pr.get("baseRefName"))
            n = int(pr["number"])
            if parent and int(parent.get("number") or 0) in blocked and n not in blocked:
                blocked.add(n); changed = True
    return orphans, unresolved, healthy, blocked


def _report(orphans, unresolved, healthy, blocked, total_open) -> None:
    print(f"pr_base_reachability: {total_open} open PR(s); "
          f"{len(healthy)} reach {TRUNK}; {len(orphans)} rooted on a "
          f"CLOSED-unmerged parent; {len(unresolved)} unresolved base(s)")
    for o in sorted(orphans, key=lambda x: int(x["pr"]["number"])):
        pr, par = o["pr"], o["parent"]
        print(f"   #{pr['number']} base={pr['baseRefName']} -> PR "
              f"#{par['number']} CLOSED unmerged"
              f"   (this PR reports mergeable={pr.get('mergeable')}"
              f"/{pr.get('mergeStateStatus')})")
    if blocked:
        print(f"   {len(blocked)} open PR(s) cannot reach {TRUNK}: "
              f"{sorted(blocked)}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default="vibeic/vibe-ic")
    ap.add_argument("--from-json", type=str, default=None,
                    help="read the PR list from a file instead of the gh CLI")
    ap.add_argument("--json", dest="json_out", type=str, default=None)
    args = ap.parse_args(argv)

    if args.from_json:
        try:
            prs = json.loads(open(args.from_json, encoding="utf-8").read())
        except (OSError, ValueError):
            prs = None
    else:
        prs = load_from_gh(args.repo)

    if not isinstance(prs, list) or not prs:
        print("REFUSE — no PR data could be read, so nothing was established "
              "about base reachability. An API failure is not evidence that "
              "every base is healthy.")
        return RC_REFUSE

    orphans, unresolved, healthy, blocked = audit(prs)
    total_open = sum(1 for p in prs if p.get("state") == "OPEN")
    _report(orphans, unresolved, healthy, blocked, total_open)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({
                "open": total_open,
                "reach_trunk": len(healthy),
                "orphans": [{"pr": o["pr"]["number"],
                             "base": o["pr"]["baseRefName"],
                             "parent": o["parent"]["number"]} for o in orphans],
                "unresolved": [p["number"] for p in unresolved],
                "blocked": sorted(blocked),
            }, fh, indent=1)

    if unresolved:
        print(f"REFUSE — {len(unresolved)} open PR(s) have a base branch owned "
              f"by no PR in the input: "
              f"{sorted(int(p['number']) for p in unresolved)}. The population "
              f"is incomplete, so a clean verdict would be over a set this run "
              f"could not see.")
        return RC_REFUSE
    if orphans:
        print(f"[FAIL] {len(orphans)} open PR(s) are based on a branch whose "
              f"PR was closed without merging. Retarget each to {TRUNK} "
              f"(`gh pr edit <n> --base {TRUNK}`) — the branch already carries "
              f"its parent's commits, so retargeting makes that explicit rather "
              f"than losing it.")
        return RC_FAIL
    print(f"[PASS] every one of the {total_open} open PR(s) has a base chain "
          f"that terminates at {TRUNK}")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
