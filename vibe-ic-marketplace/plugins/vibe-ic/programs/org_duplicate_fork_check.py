#!/usr/bin/env python3
"""Duplicate forks of one upstream — the shape that got this account flagged.

WHY THIS EXISTS
===============
On 2026-07-28, between 22:19 and 22:25, `povik/sv-elab` was forked into this org
twenty-five times: `sv-elab` and `sv-elab-1` … `sv-elab-24`. Every branch of
every duplicate was byte-identical to upstream. Not one carried a commit.

Two days later GitHub flagged the account as spammy. Issues and pull requests
vanished from the search index, which is what the web UI renders `/issues` and
`/pulls` from, so a repository with 205 issues and 353 PRs displayed as empty to
every visitor, and Actions began returning 422.

Nobody meant to create 25 forks. `gh repo fork` is not idempotent: when the
target name is taken it creates the NEXT NUMBERED NAME and exits 0. A retry
loop that would have stopped on an error instead manufactured a fork per
attempt, and the numbering is the loop's fingerprint — `-1 … -24` is not a
naming choice anyone makes.

The forks themselves are legitimate and load-bearing: an IC flow calls a dozen
mature upstream tools, and when one has a bug between us and a chip we fork it,
fix it against the failing case, and keep going. This program is not against
forking. It is against forking the SAME upstream twice, which is never intended
and which an abuse heuristic cannot distinguish from fork farming — reasonably,
because from the outside it looks exactly like it.

WHAT IT REFUSES TO DO
=====================
* Recommend deleting a fork that carries work. A duplicate is only reported as
  removable once every branch it has is proven byte-identical to the upstream
  it came from. A fork with one commit of its own is reported as a duplicate to
  RECONCILE, never as one to drop.
* Report a clean org when the listing was truncated or a comparison failed. A
  fork whose branches could not be read is UNKNOWN, and unknown is not clean —
  the whole point is that the dangerous state looks like the safe one.
* Treat the numbered suffix as proof on its own. `sv-elab-1` is only evidence of
  a retry when `sv-elab` also exists AND both point at the same upstream; a
  project legitimately named `foo-2` must not be swept up.
* Call an org clean without saying how much of it was read (vibe-ic#619). See
  below — this one was learned the hard way, by this file becoming the shape it
  audits.

AN EMPTY LISTING IS NOT A CLEAN ORG (vibe-ic#619)
==================================================
`gh repo list <owner>` exits 0 and prints `[]` for an owner that DOES NOT
EXIST. It is not an error to `gh`; there is simply nothing to list. Measured:

    $ gh repo list vibeic-typo-xyz --limit 3 --json name,isFork
    []
    rc=0

So a typo'd org, an org the token cannot see, and an org that genuinely has no
repositories all arrived here as `rows == []`, produced no fork groups, and
were reported identically:

    [OK] no upstream in vibeic-typo-xyz is forked more than once.
    rc=0

That is a verdict of success over a population that was never established —
precisely what `gate_zero_denominator_refuses_check` exists to catch, and it
caught this one: both registry-wide meta-checks flagged this file with
`PASS_WITHOUT_DENOMINATOR` and `PASS_ON_A_PROJECT_THAT_IS_NOT_THERE`.

The cost is not cosmetic. This program exists because 25 duplicate forks got
the account flagged. A monitoring run pointed at a misspelled org would have
reported `[OK]` every time while the duplicates sat there — permanent
blindness, rendered as permanent cleanliness.

Two rules follow, and they are different rules:

* ZERO REPOSITORIES LISTED -> rc 2 NOT_CHECKED. Nothing was read, so nothing
  can be vouched for. The three causes a reader must distinguish (typo, token
  scope, genuinely empty) are named in the message, because "clean" sends them
  nowhere and "I read nothing" sends them to the right three places.
* ZERO FORKS AMONG N REPOSITORIES -> rc 0 clean, WITH the count. That is an
  honest zero: N repositories really were read and none was a fork. The
  denominator makes it reviewable instead of merely reassuring.

Every rc-0 line now carries the denominator (repositories listed / forks /
distinct upstreams grouped), so `[OK]` can never again be printed by a run that
examined nothing.

Exit: 0 clean, 1 duplicates found, 2 could not check.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from typing import Dict, List, Optional

from _gate_denominator import DENOMINATOR_KEY, Denominator, line_of  # noqa: E402
from _gh_cli import gh as _gh  # noqa: E402

RC_CLEAN, RC_DUPLICATES, RC_CANNOT_CHECK = 0, 1, 2

DEFAULT_REPO_LIMIT = 500

#: `gh repo fork` appends `-N` when the name is taken. Only meaningful when the
#: unsuffixed sibling is present and shares the upstream — see the module notes.
_NUMBERED_SUFFIX = re.compile(r"^(?P<stem>.+?)-(?P<n>\d+)$")

#: A GitHub login: alphanumerics and single hyphens, never leading or trailing.
#: Checked BEFORE the network call so `vibeic/vibe-ic` (a repo where an owner
#: belongs) and `.` (a driver that assumed argument one is a path) fail with the
#: reason rather than as an anonymous empty listing. This is the fast path only
#: — a WELL-FORMED name that does not exist still reaches the listing, and the
#: zero-repository rule is what catches that one.
_ORG_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def _branch_fingerprint(full: str) -> Optional[str]:
    """Every branch and its head sha, ordered — or None if it could not be read.

    None is a THIRD state and never collapses into "matches" or "differs". A
    fork we could not read is the one we must not recommend deleting.
    """
    rc, out, _ = _gh(["api", f"repos/{full}/branches?per_page=100",
                      "--jq", '[.[]|"\\(.name)@\\(.commit.sha)"]|sort|join(" ")'],
                     timeout=60)
    if rc != 0:
        return None
    fp = (out or "").strip()
    return fp or None


def find_duplicates(org: str, limit: int = DEFAULT_REPO_LIMIT) -> dict:
    # #619 — the fast, specific half of "an empty listing is not a clean org".
    # An owner is not a path and not a repo; saying so costs no network call.
    if not _ORG_NAME.match(org):
        return {"error": f"{org!r} is not a GitHub owner name (letters, digits "
                         f"and single hyphens). A path or an OWNER/REPO was "
                         f"passed where an ORG belongs, so no org was read"}

    rc, out, err = _gh(["repo", "list", org, "--limit", str(limit), "--json",
                        "name,isFork,parent"], timeout=180)
    if rc != 0:
        return {"error": f"gh repo list failed (rc={rc}): "
                         f"{(err or out).strip()[:200]}"}
    try:
        rows = json.loads(out or "[]")
    except ValueError as exc:
        return {"error": f"unparsable repo listing: {exc}"}
    if len(rows) >= limit:
        return {"error": f"repo listing came back at the cap ({limit}); a "
                         f"duplicate could be sitting in the part not returned"}

    # #619 — THE LOAD-BEARING RULE. `gh repo list` exits 0 with `[]` for an
    # owner that does not exist, so a zero-length listing is the one state that
    # is NOT a measurement. Refusing it here, rather than letting it fall
    # through to "no groups, therefore clean", is what stops this program from
    # reporting an org it never opened as an org with nothing wrong in it.
    if not rows:
        return {"error": f"gh listed 0 repositories for {org!r}, so nothing "
                         f"was examined and this is NOT a clean org. `gh repo "
                         f"list` exits 0 with an empty list for an owner that "
                         f"does not exist, so check, in this order: the name "
                         f"is spelled right; the token can see this owner "
                         f"(`gh auth status`, org SSO and `read:org` scope); "
                         f"the owner really does have no repositories"}

    by_upstream: Dict[str, List[str]] = defaultdict(list)
    for r in rows:
        if not r.get("isFork"):
            continue
        p = r.get("parent") or {}
        owner = (p.get("owner") or {}).get("login")
        if not owner or not p.get("name"):
            # A fork whose parent we cannot see cannot be grouped, and silently
            # dropping it would let the duplicate it belongs to go unreported.
            by_upstream["<unknown-parent>"].append(r["name"])
            continue
        by_upstream[f"{owner}/{p['name']}"].append(r["name"])

    groups = []
    for upstream, names in sorted(by_upstream.items()):
        if len(names) < 2 or upstream == "<unknown-parent>":
            continue
        up_fp = _branch_fingerprint(upstream)
        members = []
        for n in sorted(names):
            fp = _branch_fingerprint(f"{org}/{n}")
            if fp is None or up_fp is None:
                state = "unreadable"
            elif fp == up_fp:
                state = "empty"          # no work of its own — safe to drop
            else:
                state = "carries-work"   # must be reconciled, never dropped
            m = _NUMBERED_SUFFIX.match(n)
            members.append({
                "name": n, "state": state,
                # The retry fingerprint, and only when the unsuffixed sibling is
                # right there sharing the upstream.
                "retry_artifact": bool(m and m.group("stem") in names),
            })
        groups.append({"upstream": upstream, "count": len(names),
                       "members": members})

    unknown = by_upstream.get("<unknown-parent>", [])

    # #619 — what this run actually read, in the gate's own units. The rule
    # ("no upstream is forked more than once") is applied to FORKS GROUPED BY
    # UPSTREAM, so that is `examined`; the repositories listed are the
    # candidates seen before `isFork` filtered them, so that is `considered`.
    # An org of N repositories with no forks in it is an honest zero and stays
    # rc 0 — but it now has to say so.
    forks_grouped = sum(len(v) for k, v in by_upstream.items()
                        if k != "<unknown-parent>")
    den = Denominator(
        unit="fork grouped by the upstream it came from",
        examined=forks_grouped,
        considered=len(rows),
        not_applicable_reason=(
            "" if forks_grouped else
            f"{len(rows)} repositories listed under {org}, none of them a fork "
            f"with a readable parent, so no upstream could be forked twice"),
        details={"repositories_listed": len(rows),
                 "forks_grouped": forks_grouped,
                 "distinct_upstreams": len([k for k in by_upstream
                                            if k != "<unknown-parent>"]),
                 "forks_with_unreadable_parent": len(unknown)},
    )
    return {"org": org, "groups": groups,
            "forks_with_unreadable_parent": sorted(unknown),
            DENOMINATOR_KEY: den.as_dict()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("org")
    ap.add_argument("--repo-limit", type=int, default=DEFAULT_REPO_LIMIT)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    res = find_duplicates(a.org, a.repo_limit)
    if a.json:
        from pathlib import Path
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(
            {"program": "org_duplicate_fork_check", **res}, indent=2) + "\n",
            encoding="utf-8")

    if "error" in res:
        print(f"[NOT CHECKED] {res['error']}. This is NOT 'no duplicates'.",
              file=sys.stderr)
        return RC_CANNOT_CHECK

    if res["forks_with_unreadable_parent"]:
        print(f"[NOT CHECKED] {len(res['forks_with_unreadable_parent'])} fork(s) "
              f"have no readable parent and could not be grouped: "
              f"{', '.join(res['forks_with_unreadable_parent'][:8])}",
              file=sys.stderr)
        return RC_CANNOT_CHECK

    # #619 — the denominator rides on EVERY rc-0 line, not only the interesting
    # one. `[OK] no upstream in X is forked more than once` states the finding;
    # what a reader needs in order to believe it is the population it was found
    # over, and that sentence is the same length either way.
    denom = line_of(res)

    if not res["groups"]:
        print(f"[OK] no upstream in {a.org} is forked more than once — {denom}.",
              file=sys.stderr)
        return RC_CLEAN

    for g in res["groups"]:
        empties = [m["name"] for m in g["members"] if m["state"] == "empty"]
        work = [m["name"] for m in g["members"] if m["state"] == "carries-work"]
        unread = [m["name"] for m in g["members"] if m["state"] == "unreadable"]
        retries = [m["name"] for m in g["members"] if m["retry_artifact"]]
        print(f"[DUPLICATE] {g['upstream']} is forked {g['count']} times.",
              file=sys.stderr)
        if retries:
            print(f"  {len(retries)} carry the numbered suffix a retried "
                  f"`gh repo fork` leaves behind: {', '.join(retries[:6])}"
                  f"{' …' if len(retries) > 6 else ''}", file=sys.stderr)
        if work:
            print(f"  {len(work)} carry work of their own and must be "
                  f"RECONCILED, not deleted: {', '.join(work)}",
                  file=sys.stderr)
        if unread:
            print(f"  {len(unread)} could not be read, so their contents are "
                  f"UNKNOWN: {', '.join(unread[:6])}", file=sys.stderr)
        if empties:
            keep = work[0] if work else empties[0]
            print(f"  {len(empties)} are byte-identical to upstream. Keeping "
                  f"{keep}, the rest are removable.", file=sys.stderr)
    # The count a reader needs to size the finding: N duplicated upstreams out
    # of how many forks, out of how many repositories.
    print(f"[{len(res['groups'])} duplicated upstream(s)] over {denom}.",
          file=sys.stderr)
    print(json.dumps(res["groups"], indent=1))
    return RC_DUPLICATES


if __name__ == "__main__":
    sys.exit(main())
