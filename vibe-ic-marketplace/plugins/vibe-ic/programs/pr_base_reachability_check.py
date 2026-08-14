#!/usr/bin/env python3
"""pr_base_reachability_check.py — a PR that declares a dead base, or that
merely CARRIES a closed-unmerged PR's commits, is not landable; `mergeable`
reports CLEAN for both (vibe-ic#1364).

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

TWO QUESTIONS, AND NEITHER ANSWERS THE OTHER
============================================
DECLARED — does `baseRefName` chain terminate at `main`?  (metadata only)
CARRIED  — does the branch CONTAIN a closed-unmerged PR's commits?  (`--repo-dir`)

The first revision of this file asked only the DECLARED question and told
authors to fix a finding with `gh pr edit <n> --base main`. That remedy silences
the DECLARED question **without removing the parent's commits**, so a branch
that took the advice becomes invisible to the very check that gave it.

#1290 is the worked example. #1364 recorded its base as
`fix/63x8-waiver-citations-reverified`; it now reads `main`, reports MERGEABLE,
and still contains #1259's `3d5ecf73`. #1259 was closed WITHOUT merging.

Re-measured 2026-08-13 over the full population — 218 open, 760 closed of which
485 unmerged, 87 of those with a branch still live and not in `main` (counts
taken by REST pagination, because `gh pr list --limit 400` returned exactly 400
and was silently truncating):

    DECLARED only ....... #1110
    CARRIED only ........ #1078  #1197  #1239  #1290      <- all declare `main`
    both ................ #1265  #1301  #1309

Eight PRs, and **each pass alone misses at least one of them**. That is why both
run, and why a run that could not perform the CARRIED pass says so rather than
printing a clean bill.

It still does not judge whether the PR is correct, whether it conflicts, or
whether the parent SHOULD have been closed. A stack on an OPEN parent is healthy
and is reported as such; the parent landing first is the normal order.

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


def _git(repo_dir: str, *args: str) -> Tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", repo_dir, *args], capture_output=True,
                           text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 128, ""
    return r.returncode, r.stdout.strip()


def _resolves(repo_dir: str, ref: str) -> bool:
    return _git(repo_dir, "rev-parse", "--verify", "-q", ref)[0] == 0


def carried_rejects(prs: List[dict], repo_dir: str,
                    remote: str = "origin") -> Tuple[List[dict], Optional[str]]:
    """`(hits, refusal)` — open PRs whose HEAD CONTAINS a closed-unmerged PR.

    This is a different question from the one `audit()` asks, and neither
    subsumes the other:

      * `audit()` reads `baseRefName` — what the PR SAYS it targets;
      * this reads the commit graph — what the branch actually CARRIES.

    Retargeting an orphan to `main` changes the first and changes nothing about
    the second. #1290 is the worked example: #1364 recorded its base as
    `fix/63x8-waiver-citations-reverified`; today it reads `main`, reports
    MERGEABLE, and still contains #1259's `3d5ecf73`. Landing it would land the
    content of a PR that was closed WITHOUT merging, under a different number
    and with none of that PR's review.

    A parent whose commits are already ancestors of `main` is skipped: its
    content landed, so carrying it is not a resurrection.

    WHAT ANCESTRY CAN AND CANNOT PROVE. `--is-ancestor` is exact about commits
    and silent about content. This repository squash-merges, so a rejected
    branch whose *content* was later re-landed under another number still fails
    the ancestry test and will be reported here. The finding is therefore
    "carries commits that never landed as such", which is precisely what a
    reviewer needs to look at — not "carries content nobody approved". Stated
    so the next reader does not have to re-derive it.
    """
    if _git(repo_dir, "rev-parse", "--git-dir")[0] != 0:
        return [], f"{repo_dir} is not a git repository"
    if not _resolves(repo_dir, f"{remote}/{TRUNK}"):
        return [], f"{remote}/{TRUNK} does not resolve"

    open_prs = [p for p in prs if p.get("state") == "OPEN"]
    dead = [p for p in prs if is_dead_parent(p)]

    # Batched, because the natural shape is O(open x dead) subprocesses — 218 x
    # 87 in this repo, measured at 52s wall with almost all of it spawn cost,
    # and both factors only grow. `for-each-ref` answers each question in one
    # call. A gate that takes a minute is a gate somebody turns off.
    def refs(*extra: str) -> Optional[Set[str]]:
        rc, out = _git(repo_dir, "for-each-ref", "--format=%(refname:strip=3)",
                       *extra, f"refs/remotes/{remote}/")
        return set(out.split("\n")) - {""} if rc == 0 else None

    known = refs()
    in_trunk = refs("--merged", f"{remote}/{TRUNK}")
    if known is None or in_trunk is None:
        return [], f"could not enumerate refs under {remote}/"

    live: Dict[str, dict] = {}
    for p in dead:
        ref = p.get("headRefName")
        if not ref or ref not in known:
            continue                       # branch deleted — carries nothing
        if ref in in_trunk:
            continue                       # already in main — not a resurrection
        live[ref] = p

    missing = [int(p["number"]) for p in open_prs
               if p.get("headRefName") not in known]
    if missing:
        return [], (f"{len(missing)} open PR head branch(es) do not resolve "
                    f"under {remote}/ ({sorted(missing)[:8]}...): run "
                    f"`git fetch {remote} '+refs/heads/*:refs/remotes/{remote}/*'` "
                    f"first. Containment over a partial set would answer 0 for "
                    f"the branches this run could not see")

    by_head: Dict[str, List[dict]] = {}
    for p in open_prs:
        by_head.setdefault(p["headRefName"], []).append(p)

    hits: List[dict] = []
    for ref, parent in sorted(live.items()):
        carriers = refs("--contains", f"{remote}/{ref}")
        if carriers is None:
            return [], f"could not list branches containing {remote}/{ref}"
        for head in sorted(carriers & set(by_head)):
            if head == ref:
                continue
            for p in by_head[head]:
                hits.append({"pr": p, "parent": parent})
    return hits, None


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
    ap.add_argument("--repo-dir", type=str, default=None,
                    help="git checkout to read the commit graph from; enables "
                         "the CARRIED pass, which baseRefName cannot see")
    ap.add_argument("--remote", type=str, default="origin")
    ap.add_argument("--require-carried", action="store_true",
                    help="REFUSE (rc 2) if the CARRIED pass could not run, "
                         "instead of reporting it as not established")
    ap.add_argument("--advisory", action="store_true",
                    help="lower a FAIL to rc 0. Every finding is still printed "
                         "and the verdict line still says FAIL. Does NOT lower "
                         "a REFUSAL: 'I could not look' must never share an "
                         "exit code with 'I looked and it was clean'")
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

    carried: List[dict] = []
    carried_refusal: Optional[str] = None
    if args.repo_dir:
        carried, carried_refusal = carried_rejects(prs, args.repo_dir,
                                                   args.remote)
        if carried_refusal:
            print(f"   CARRIED pass NOT ESTABLISHED — {carried_refusal}")
        else:
            print(f"   CARRIED pass: {len(carried)} open PR(s) contain commits "
                  f"of a CLOSED-unmerged PR whose branch never reached {TRUNK}")
            for h in sorted(carried, key=lambda x: int(x["pr"]["number"])):
                print(f"      #{h['pr']['number']} "
                      f"(base={h['pr'].get('baseRefName')}) carries "
                      f"#{h['parent']['number']} "
                      f"({h['parent']['headRefName']})")
    else:
        carried_refusal = ("no --repo-dir given, so nothing was established "
                           "about what the branches CARRY")
        print(f"   CARRIED pass NOT ESTABLISHED — {carried_refusal}")

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
                # Absent/empty `carried` and a non-null `carried_not_established`
                # are different facts. A consumer that reads only `carried`
                # would turn "not measured" into "none found".
                "carried": [{"pr": h["pr"]["number"],
                             "base": h["pr"].get("baseRefName"),
                             "parent": h["parent"]["number"]} for h in carried],
                "carried_not_established": carried_refusal,
            }, fh, indent=1)

    if unresolved:
        print(f"REFUSE — {len(unresolved)} open PR(s) have a base branch owned "
              f"by no PR in the input: "
              f"{sorted(int(p['number']) for p in unresolved)}. The population "
              f"is incomplete, so a clean verdict would be over a set this run "
              f"could not see.")
        return RC_REFUSE
    if args.require_carried and carried_refusal:
        print(f"REFUSE — the CARRIED pass could not run ({carried_refusal}) "
              f"and --require-carried was given. A declared base of {TRUNK} is "
              f"not evidence that a branch carries nothing rejected.")
        return RC_REFUSE
    if orphans or carried:
        if orphans:
            print(f"[FAIL] {len(orphans)} open PR(s) DECLARE a base whose PR "
                  f"was closed without merging.")
        if carried:
            print(f"[FAIL] {len(carried)} open PR(s) CARRY the commits of a "
                  f"closed-unmerged PR.")
        print(
            f"   REMEDY. Retargeting to {TRUNK} (`gh pr edit <n> --base "
            f"{TRUNK}`) fixes only the DECLARED base. It does not remove the "
            f"parent's commits, and once the base reads {TRUNK} the declared "
            f"pass above goes quiet — which is how these branches became "
            f"invisible in the first place. An earlier revision of THIS FILE "
            f"recommended exactly that and nothing else; the recommendation "
            f"was wrong and is corrected here.\n"
            f"   Decide, per PR, which of these two is true, and say which:\n"
            f"     * the parent's change is NOT wanted — rebase it out "
            f"(`git rebase --onto {TRUNK} <parent-tip> <head>`), so the PR "
            f"carries only its own work;\n"
            f"     * the parent's change IS wanted — say so in the PR body, "
            f"name the closed PR, and have it reviewed HERE, because closing "
            f"it removed the review it would otherwise have had.")
        if args.advisory:
            print("   (--advisory: exit code lowered to 0. The verdict above "
                  "is FAIL and every finding is printed. Nothing is baselined "
                  "or waived — the only thing that can make this print zero is "
                  "the branches being fixed.)")
            return RC_OK
        return RC_FAIL
    scope = ("base chain AND carried commits" if not carried_refusal
             else f"base chain only — {carried_refusal}")
    print(f"[PASS] every one of the {total_open} open PR(s) is clean on: "
          f"{scope}")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
