#!/usr/bin/env python3
"""issue_state_notify.py — diff GitHub issue state across cron fires.

Compares the current open/closed state + labels of every recently
touched issue in reyerchu/AI_IC_design against a local snapshot
at ~/.config/vibe-ic-issue-state.json. Emits a JSON event list on
stdout (one line per change), then rewrites the snapshot.

Event kinds:
  * state_change       — open <-> closed
  * label_added        — new label appeared
  * label_removed      — label gone
  * new_issue          — first time we've seen this number

Cron fire reads stdout; non-empty event list → emit PushNotification.

Why a separate snapshot file rather than diff-from-comments:
  * comments don't transition state (closing an issue can be
    button-only, no comment) — must read `state` directly
  * snapshot is durable across cron fires + manual triggers
  * o(open + recent-closed) per fire, bounded

WHY THE ENUMERATION IS GraphQL AND NOT REST (vibe-ic#1645)
==========================================================
This program used to enumerate with the REST listing endpoint:

    GET /repos/{REPO}/issues?state=open&per_page=50

That endpoint returns an EMPTY ARRAY, with HTTP 200, for a repository
that demonstrably has open issues. Measured against `vibeic/vibe-ic`:

    gh api 'repos/vibeic/vibe-ic/issues?state=open&per_page=50' -> 0
    gh api 'repos/vibeic/vibe-ic/issues?state=all&per_page=100' -> 0
    gh api 'search/issues?q=repo:vibeic/vibe-ic+is:issue+is:open'
                                              -> total_count 0
    gh api repos/vibeic/vibe-ic --jq .open_issues_count           -> 0
    gh issue list --state open --limit 200 (GraphQL)              -> 33

and a single-issue REST GET of one of those 33 returns `state: open`,
so the zero is false rather than a repository with nothing open. The
REST listing for PULL requests on the same repository returns 6, so it
is the ISSUE listing specifically, not auth and not the repository.

An empty listing and an empty backlog are byte-identical here, and this
program reported the second when it was handed the first: pointed at
that repository it printed `{"events": [], "fetched": 0}` with rc 0 —
a well-formed, successful, silent cron fire. Every new issue, reopen
and label change would go unreported for as long as the condition
lasts, and nothing in the output would say so.

GraphQL keeps working through the same condition (that is what
`gh issue list` uses, and it is the authority the repo's other polling
programs already use — see `open_organic_issue_count.py` for vibe-ic#554
and `org_open_work_poll.py` for the org-level sibling). So the
enumeration is GraphQL, and a query that CANNOT be answered exits 2
with an `error` on stdout instead of an empty event list, because
"I could not look" must not arrive at the cron as "nothing changed".
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO = "reyerchu/AI_IC_design"
STATE_PATH = Path.home() / ".config" / "vibe-ic-issue-state.json"
TOKEN_PATH = Path.home() / ".config" / "github" / "token"

API_ROOT = "https://api.github.com"
GRAPHQL_URL = f"{API_ROOT}/graphql"

#: Same page sizes the REST listings used, so the tracked window does not
#: change with the transport. GraphQL caps `first` at 100.
OPEN_PAGE = 50
CLOSED_PAGE = 20

#: Both halves in ONE request. `repository.issues` never contains pull
#: requests, so the PR filter below is belt-and-braces rather than load
#: bearing. Ordered by UPDATED_AT so that, on a repository with more open
#: issues than one page, the window holds the ones that actually moved —
#: which is what a change notifier needs.
_ISSUES_QUERY = """
query($owner:String!, $name:String!, $open:Int!, $closed:Int!) {
  repository(owner:$owner, name:$name) {
    openIssues: issues(first:$open, states:OPEN,
                       orderBy:{field:UPDATED_AT, direction:DESC}) {
      nodes { number state title updatedAt labels(first:100){nodes{name}} }
    }
    closedIssues: issues(first:$closed, states:CLOSED,
                         orderBy:{field:UPDATED_AT, direction:DESC}) {
      nodes { number state title updatedAt labels(first:100){nodes{name}} }
    }
  }
}
"""


class GitHubQueryError(RuntimeError):
    """The enumeration could not be answered. NEVER an empty result."""


def _http_json(url: str, token: str, payload: dict | None = None) -> Any:
    """The one network seam in this file, so every call is fakeable."""
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _graphql(query: str, variables: dict, token: str) -> dict:
    """Run a GraphQL query, or raise.

    GitHub answers a failed GraphQL query with HTTP 200 and an `errors`
    array, so the transport succeeding says nothing about the query
    succeeding. A response carrying `errors`, or one whose `repository`
    is null, is an ANSWER THAT WAS NOT GIVEN — it is raised, never
    flattened into an empty node list.
    """
    body = _http_json(GRAPHQL_URL, token,
                      {"query": query, "variables": variables})
    if not isinstance(body, dict):
        raise GitHubQueryError(
            f"GraphQL response was {type(body).__name__}, not an object")
    if body.get("errors"):
        msgs = "; ".join(
            str(e.get("message", e)) for e in body["errors"][:3])
        raise GitHubQueryError(f"GraphQL errors: {msgs}")
    data = body.get("data") or {}
    if data.get("repository") is None:
        raise GitHubQueryError(
            "GraphQL returned no `repository` object — the repo could not "
            "be read, which is not the same as a repo with no issues")
    return data["repository"]


def _normalise(node: dict) -> dict:
    """GraphQL node -> the REST-shaped record the differ already speaks.

    `state` is LOWERCASED on purpose: snapshots written by the REST era
    hold `open`/`closed`, and GraphQL says `OPEN`/`CLOSED`. Carrying the
    GraphQL casing through would make the first fire after this change
    report a state_change on every tracked issue.
    """
    labels = ((node.get("labels") or {}).get("nodes")) or []
    return {
        "number": node["number"],
        "state": str(node.get("state", "")).lower(),
        "title": node.get("title") or "",
        "updated_at": node.get("updatedAt"),
        "labels": [{"name": l.get("name")} for l in labels if l],
    }


def _fetch_recent(token: str) -> list[dict]:
    owner, _, name = REPO.partition("/")
    repo = _graphql(_ISSUES_QUERY,
                    {"owner": owner, "name": name,
                     "open": OPEN_PAGE, "closed": CLOSED_PAGE},
                    token)
    open_nodes = ((repo.get("openIssues") or {}).get("nodes")) or []
    closed_nodes = ((repo.get("closedIssues") or {}).get("nodes")) or []
    # No PR filter: `repository.issues` never contains pull requests. The
    # REST listing did, which is why the old code had one.
    seen = set()
    out: list[dict] = []
    for node in (*open_nodes, *closed_nodes):
        d = _normalise(node)
        if d["number"] in seen:
            continue
        seen.add(d["number"])
        out.append(d)
    return out


def _load_snapshot() -> dict[str, dict]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _save_snapshot(snap: dict[str, dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(snap, indent=2, sort_keys=True))


def _diff(prev: dict, cur: dict, num: int) -> list[dict]:
    events: list[dict] = []
    if not prev:
        events.append({
            "kind": "new_issue",
            "number": num,
            "state": cur["state"],
            "title": cur["title"],
        })
        return events
    if prev.get("state") != cur["state"]:
        events.append({
            "kind": "state_change",
            "number": num,
            "from": prev.get("state"),
            "to": cur["state"],
            "title": cur["title"],
        })
    prev_labels = set(prev.get("labels", []))
    cur_labels = set(cur["labels"])
    for added in sorted(cur_labels - prev_labels):
        events.append({
            "kind": "label_added",
            "number": num,
            "label": added,
            "title": cur["title"],
        })
    for removed in sorted(prev_labels - cur_labels):
        events.append({
            "kind": "label_removed",
            "number": num,
            "label": removed,
            "title": cur["title"],
        })
    return events


def comment_is_core_agent(body: str) -> bool:
    """Classify a GitHub issue comment as core-agent push vs field-agent
    verification report.

    A core-agent push comment starts with ``## v<X.Y.Z> -`` (em-dash or
    hyphen after the version, no ``verification`` keyword in the first
    line). A field-agent verification report starts with
    ``## v<X.Y.Z> verification ...`` -- same version prefix but with the
    keyword ``verification`` somewhere on the first line.

    Returns ``True`` only if the comment looks like a core-agent push.
    Comments that don't match the ``## v<X.Y.Z>`` shape return ``False``.
    """
    if not body:
        return False
    first_line = body.lstrip().split('\n', 1)[0]
    if not re.match(r'^##\s*v\d+\.\d+\.\d+\b', first_line, re.IGNORECASE):
        return False
    if re.search(r'\bverification\b', first_line, re.IGNORECASE):
        return False
    return True


_FIELD_FAIL_MARKERS_RE = re.compile(
    r'\b(?:reopen(?:ing)?|residual|regress(?:ion|ed)?|leak(?:ing|s)?|'
    r'still\s+(?:fires|leaks|emits|fails|broken)|'
    r'NOT\s+fixed|partial(?:ly)?\s+(?:fix|fail)|'
    r'fail(?:ed|ure)?\b(?!\s+to\s+reject))\b',
    re.IGNORECASE,
)


def classify_comment(body: str) -> str:
    """Three-way classifier.

    Returns one of:
      * ``core``        — core-agent push comment (no fix needed)
      * ``field_pass``  — field-agent verification confirming PASS
                          (no fix needed, just waiting for the field
                          agent to actually close the issue)
      * ``field_fail``  — field-agent verification reporting a residual
                          / regression / leak (core agent must fix)

    Cron triage logic: ``field_fail`` is the only ACTIONABLE class.
    A ``field_pass`` PASS-report is a no-op for the core agent — it
    merely awaits the field agent's close button.
    """
    if comment_is_core_agent(body):
        return 'core'
    if not body:
        return 'field_fail'
    # field-agent comment. Distinguish PASS vs FAIL by scanning for
    # FAIL-marker words anywhere in the body.
    if _FIELD_FAIL_MARKERS_RE.search(body):
        return 'field_fail'
    # No FAIL marker present → treat as PASS (closing-confirmation,
    # verified, fixed across all N projects, etc.). Conservative
    # default: any field comment lacking explicit FAIL signals is a
    # PASS, which prevents the false-positive cron loop on
    # closing-confirmation reports.
    return 'field_pass'


def _classify_stdin() -> int:
    """CLI: emit a single label for a comment body on stdin.

    With ``--three-way`` flag emits one of {core, field_pass, field_fail}.
    Without flag (default) emits the older ``core`` / ``field`` labels
    for backwards-compat with v1.6.77-era cron prompts. Cron prompts
    that need the PASS-vs-FAIL distinction must opt in.
    """
    body = sys.stdin.read()
    if '--three-way' in sys.argv[1:]:
        print(classify_comment(body))
    else:
        print('core' if comment_is_core_agent(body) else 'field')
    return 0


def _read_token() -> str | None:
    """The token file, else the environment. None when neither is set.

    The env fallback is what makes the failure in vibe-ic#1645
    reproducible by anyone: `GH_TOKEN=$(gh auth token) ... --repo
    vibeic/vibe-ic --state-path /tmp/throwaway.json`.
    """
    if TOKEN_PATH.exists():
        tok = TOKEN_PATH.read_text().strip()
        if tok:
            return tok
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        tok = (os.environ.get(var) or "").strip()
        if tok:
            return tok
    return None


def _parse_overrides(args: list[str]) -> None:
    """`--repo OWNER/NAME` and `--state-path PATH`, both optional.

    Unknown arguments are ignored, as they were before, so legacy cron
    invocations keep working.
    """
    global REPO, STATE_PATH
    repo = state_path = None
    i = 0
    while i < len(args):
        flag, val = args[i], None
        if flag in ("--repo", "--state-path") and i + 1 < len(args):
            val = args[i + 1]
            i += 1
        elif flag.startswith("--repo=") or flag.startswith("--state-path="):
            flag, val = flag.split("=", 1)
        if val is not None:
            if flag == "--repo":
                repo = val
            else:
                state_path = val
        i += 1
    if state_path:
        STATE_PATH = Path(state_path)
    elif repo and repo != REPO:
        # A snapshot is keyed by issue NUMBER, so pointing this program at a
        # second repository while sharing one snapshot would read repo B's
        # #12 as a state change on repo A's #12. Separate file, derived.
        slug = repo.replace("/", "-")
        STATE_PATH = STATE_PATH.with_name(f"vibe-ic-issue-state-{slug}.json")
    if repo:
        REPO = repo


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if '--classify-comment-stdin' in args:
        return _classify_stdin()
    _parse_overrides(args)
    token = _read_token()
    if not token:
        print(json.dumps({"error": "no_github_token"}))
        return 2

    try:
        issues = _fetch_recent(token)
    except (GitHubQueryError, OSError, ValueError, KeyError) as exc:
        # A fire that could not enumerate prints an ERROR, not an empty
        # event list. The cron reads stdout and notifies on a non-empty
        # `events`; emitting `{"events": []}` here would make "GitHub
        # would not answer" indistinguishable from "nothing changed" —
        # which is the defect in vibe-ic#1645, one layer up.
        print(json.dumps({"error": "issue_enumeration_failed",
                          "detail": f"{type(exc).__name__}: {exc}"[:300],
                          "repo": REPO}))
        return 2

    snapshot = _load_snapshot()
    new_snapshot: dict[str, dict] = {}
    all_events: list[dict] = []

    for d in issues:
        num = d["number"]
        cur = {
            "state": d["state"],
            "labels": [l["name"] for l in d.get("labels", [])],
            "updated_at": d["updated_at"],
            "title": d["title"][:120],
        }
        new_snapshot[str(num)] = cur
        prev = snapshot.get(str(num), {})
        all_events.extend(_diff(prev, cur, num))

    # Preserve snapshot entries we didn't see this fire (older
    # closed issues) — don't drop them, or a future re-open
    # would falsely fire as "new_issue".
    for k, v in snapshot.items():
        new_snapshot.setdefault(k, v)

    _save_snapshot(new_snapshot)

    out = {
        "events": all_events,
        "tracked": len(new_snapshot),
        "fetched": len(issues),
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
