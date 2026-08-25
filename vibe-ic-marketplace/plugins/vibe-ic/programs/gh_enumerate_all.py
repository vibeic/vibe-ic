#!/usr/bin/env python3
"""Enumerate a GitHub collection COMPLETELY, or refuse — never a partial page.

WHY THIS EXISTS
===============
Six times in one session (2026-07-30) a conclusion was published from a listing
that had been capped by the person asking for it, and each time the capped result
was indistinguishable from a complete one:

    head -8            "that fork has no such branch"     — it had, past line 8
    head -40           an upstream list short by 5        — that list went into a
                                                            GitHub appeal draft
    per_page=100 → 100 "the repo has exactly 100 branches"
    | tail -35         14 minutes blind to a gate's progress, and it ate the exit
                       code — a FAILED script reported success
    one Dockerfile     "dockerfile_arg is stale" — pins live in fifteen files
    labels=bug → 70    "unreported upstream" — the tracker holds 2303 issues

`org_open_work_poll` already refuses this for one org's PRs and issues, and its
docstring names the defect exactly: at the cap there is no way to tell a full
page from a truncated one, so the number is a floor and not a count. This is that
refusal, generalised, so the next question about somebody ELSE's repository
cannot be answered from page one.

WHAT IT REFUSES TO DO
=====================
* Return a page and let the caller believe it is the collection. Pagination runs
  to exhaustion; a `--max-pages` stop is an ERROR (rc 2), not a truncated result.
* Report a count from a REST listing that came back exactly at `per_page`. That
  is the shape the six failures share.
* Treat a failed page as the end of the collection. Half a listing is not a
  listing, and "the query died" must not read as "nothing more".
* Answer at all when the search index is used. GitHub's issue/PR search returns
  HTTP 200 with `total_count: 0` for a flagged account (vibe-ic#550), so this
  enumerates via GraphQL, whose result is not filtered that way.

Exit: 0 complete (JSON on stdout), 2 could not enumerate completely.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

RC_OK, RC_INCOMPLETE = 0, 2

#: Far above any plausible collection, so hitting it means something is wrong
#: rather than that the collection is large.
DEFAULT_MAX_PAGES = 200
PAGE = 100

#: `<owner>/<repo>` + the collection. Each maps to the GraphQL connection and the
#: fields worth carrying; the caller filters the result.
COLLECTIONS: Dict[str, Tuple[str, str]] = {
    # `body` is carried because a title-only search is a search of titles, not
    # of the tracker. Found the hard way: `--grep FlexPA` reported "2303
    # enumerated, 0 match", which reads as proof upstream never mentions the
    # frame this project's crash dies in — while saying nothing about the 2303
    # bodies. The issue that mattered most (#6065) has neither "crash" nor
    # "segfault" in its title either.
    "issues": ("issues", "number state title body createdAt url"),
    "pullRequests": ("pullRequests", "number state title body createdAt url"),
    "refs/tags": ("refs(refPrefix:\"refs/tags/\")", "name"),
    # `target{oid}` rides along because a branch listing is used to decide
    # whether two repositories hold the same work, and a name-only listing
    # cannot answer that. `org_duplicate_fork_check._branch_fingerprint` is the
    # caller: it compares `name@sha` across a fork and its upstream, and a fork
    # whose branches all match is the one it recommends DELETING. That listing
    # used to be `repos/<full>/branches?per_page=100`, which is failure three in
    # the table above — at 100 branches the prefix reads as the collection, two
    # forks agree on their first hundred, and the recommendation is to drop a
    # fork whose difference sits past the cap.
    "refs/heads": ("refs(refPrefix:\"refs/heads/\")", "name target{oid}"),
}


def _gh_graphql(query: str, timeout: int = 120) -> Tuple[Optional[dict], str]:
    try:
        r = subprocess.run(["gh", "api", "graphql", "-f", f"query={query}"],
                           capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return None, "gh is not installed"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if r.returncode != 0:
        return None, (r.stderr or r.stdout).strip()[:200]
    try:
        return json.loads(r.stdout), ""
    except ValueError as exc:
        return None, f"unparsable response: {exc}"


def enumerate_all(owner: str, repo: str, collection: str,
                  max_pages: int = DEFAULT_MAX_PAGES) -> dict:
    """Every node in the collection, or an error — never a prefix."""
    if collection not in COLLECTIONS:
        return {"error": f"unknown collection {collection!r}; "
                         f"known: {', '.join(sorted(COLLECTIONS))}"}
    conn, fields = COLLECTIONS[collection]
    nodes: List[dict] = []
    cursor = "null"
    for page in range(max_pages):
        # `first` inside the connection, `after` for the cursor. A connection
        # that already carries arguments (refs) gets them merged.
        head, _, tail = conn.partition("(")
        inner = (f"{head}(first:{PAGE},after:{cursor},{tail}"
                 if tail else f"{conn}(first:{PAGE},after:{cursor})")
        q = (f'{{repository(owner:"{owner}",name:"{repo}"){{'
             f'{inner}{{totalCount pageInfo{{hasNextPage endCursor}}'
             f'nodes{{{fields}}}}}}}}}')
        data, err = _gh_graphql(q)
        if err:
            # A failed page is NOT the end of the collection. Returning what was
            # collected so far would be the exact defect this program exists for.
            return {"error": f"page {page + 1} failed after {len(nodes)} node(s): "
                             f"{err}"}
        try:
            block = data["data"]["repository"]
            for key in block:
                if isinstance(block[key], dict) and "nodes" in block[key]:
                    block = block[key]
                    break
            nodes.extend(block.get("nodes") or [])
            total = block.get("totalCount")
            info = block.get("pageInfo") or {}
        except (KeyError, TypeError) as exc:
            return {"error": f"unexpected response shape: {exc}"}
        if not info.get("hasNextPage"):
            if isinstance(total, int) and len(nodes) != total:
                return {"error": f"pagination ended with {len(nodes)} node(s) but "
                                 f"the collection declares {total}; one of those "
                                 f"is wrong and the listing cannot be trusted"}
            return {"owner": owner, "repo": repo, "collection": collection,
                    "count": len(nodes), "declared_total": total, "nodes": nodes}
        cursor = f'"{info["endCursor"]}"'

    return {"error": f"stopped at the {max_pages}-page cap with {len(nodes)} "
                     f"node(s) and more to come; a prefix is not a collection"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", help="owner/name, e.g. The-OpenROAD-Project/OpenROAD")
    ap.add_argument("collection", choices=sorted(COLLECTIONS))
    ap.add_argument("--grep", default=None,
                    help="case-insensitive substring filter over title AND body "
                         "(name, for refs); applied AFTER complete enumeration, "
                         "never instead of it")
    ap.add_argument("--titles-only", action="store_true",
                    help="restrict --grep to titles. The verdict says so, because "
                         "a title search that reads as a tracker search is how a "
                         "zero becomes false reassurance.")
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    if "/" not in a.repo:
        print(f"[NOT ENUMERATED] {a.repo!r} is not owner/name", file=sys.stderr)
        return RC_INCOMPLETE
    owner, _, name = a.repo.partition("/")

    res = enumerate_all(owner, name, a.collection, a.max_pages)
    if a.json:
        from pathlib import Path
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(
            {"program": "gh_enumerate_all", **res}, indent=2) + "\n",
            encoding="utf-8")

    if "error" in res:
        print(f"[NOT ENUMERATED] {res['error']}. This is NOT an empty collection "
              f"and NOT a count — a caller that reads a number here would be "
              f"reading a floor.", file=sys.stderr)
        return RC_INCOMPLETE

    out = res["nodes"]
    if a.grep:
        needle = a.grep.lower()
        fields = ("title", "name") if a.titles_only else ("title", "name", "body")
        out = [n for n in out
               if any(needle in str(n.get(f) or "").lower() for f in fields)]
        where = "titles only" if a.titles_only else "title and body"
        print(f"[OK] {res['count']} {a.collection} enumerated in {a.repo}; "
              f"{len(out)} match {a.grep!r} in {where}. The denominator is the "
              f"whole collection, not a page.", file=sys.stderr)
    else:
        print(f"[OK] {res['count']} {a.collection} in {a.repo} "
              f"(declared {res['declared_total']}).", file=sys.stderr)
    print(json.dumps(out, indent=1))
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
