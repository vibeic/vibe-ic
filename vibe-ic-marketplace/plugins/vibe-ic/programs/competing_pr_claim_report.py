#!/usr/bin/env python3
"""competing_pr_claim_report.py — which issues have more than one change
claiming them, INCLUDING the ones that share no file.

THIS IS A REPORT (rc 0), NOT A GATE. `--fail-on-competing` promotes it to
BLOCKING (rc 1) for a caller that wants competing claims to stop something.
The default is deliberate and measured — see "WHY IT DOES NOT DECIDE".

THE DEFECT (vibe-ic#1411), measured
===================================
The mechanism this repo actually uses to notice that two changes are doing one
job is a MERGE CONFLICT: the harness refuses the batch and somebody has to
look. That mechanism answers "do these edit the same bytes", and the question
that matters is "do these do the same job". The two come apart, and they come
apart most of the time.

Measured over 192 open PRs at `24ff9530`, grouped by the issue each PR claims
(`Closes/Fixes/Advances #N`, or `(#N)` in the title), with `INDEX.md`
discounted because ~27 PRs touch it and it carries no information (#1363):

    open PRs                                  192
    issues with >1 open PR                     22
      cannot collide (no shared file)          16     <- invisible
      share a file (git surfaces them)          6     <- adjudicated

Sixteen of twenty-two groups could not collide, so nothing reported them. Each
member merges cleanly, each is individually correct, and every member reports
`mergeable`.

**#1080 is the confirmed instance.** PRs #1150 and #1205 both implemented it,
both passed their own tests, and neither branch contained the other's program:
`run_metrics.py` (verdicts BETTER / SAME / WORSE) beside `step_metrics.py`
(verdicts improved / REGRESSED), agreeing on the metric NAMES and disagreeing
on the record shape. #1080 asks for ONE schema so runs are comparable; landing
both closes it in name and defeats it in substance. That pair was found by
accident while verifying #1150 for unrelated reasons. Nothing would have
surfaced it.

WHY IT DOES NOT DECIDE (and why that is not timidity)
=====================================================
"Cannot collide" is NOT "duplicate", and a detector that treated it as one
would be wrong about most of what it flags. Of the 16 above, at least three
are legitimate splits, verified by hand: #1241 has nineteen rows so four PRs
is expected, #1097 names three separate mechanisms and its two PRs implement
different ones, #1115's pair repairs different channels.

A report that fires on all of them as a BLOCKING gate is a gate that is red
every day, and a gate that is red every day is a gate people learn to bypass —
which is how this repo arrived at a landing path with no gate in it at all
(#1019). So the default answers the one question a machine can answer
correctly ("these N changes claim one issue, and this is whether git can see
them"), prints it where the landing log already is, and leaves the
split-vs-duplicate call to the reader.

`--fail-on-competing` exists for the caller that has a narrower population —
one assembled batch rather than every open PR — where two members claiming one
issue really is a stop.

DEGRADING LOUDLY: AN EMPTY RESULT IS NOT A ZERO
===============================================
Three answers are kept apart, because conflating them is the same shape as the
defect:

  * a group whose members demonstrably share no file        -> NO_SHARED_FILE
  * a group with a shared file                              -> SHARED
  * a group whose file lists were not supplied / not fetched -> UNDETERMINED

UNDETERMINED is never counted as NO_SHARED_FILE. A PR record without a `files`
key has not told us the members do not collide; it has told us nobody looked.
An input with ZERO claimants exits 2 (NOT CHECKED), never 0 — a report that
examined nothing must not read like a clean one. Every run prints its
denominator.

INPUT MODES
===========
The predicate is pure and takes records; the modes are thin adapters, so the
report is testable with no network and no repo.

    --prs-json FILE|-   a JSON list as produced by
                        `gh pr list --json number,title,body,files`.
                        `files` may be a list of strings or of
                        `{"path": ...}` records; absent -> UNDETERMINED.
    --from-github       run that `gh pr list` here (bounded, see TIMEOUT).
    --rev-range A..B    the claimants are COMMITS in a git range — what a
                        LANDING is. Needs no network, which is why the landing
                        path wires this one.

A NOTE ON `(#N)` IN A LANDED SUBJECT. A squash-merge appends the PR's own
number, so `... (#1047) (#1049)` claims both the issue and the PR. Both are
recorded as claims: suppressing the trailing one by position would silently
drop the issue reference of every commit that carries only one, and a PR
number claimed twice means one PR landed twice, which is itself worth seeing.

TIMEOUT
=======
Every subprocess is bounded at <= 60 s, which is the ceiling
`ci_harness_timeout_ceiling_check` enforces: the landing harness runs pytest
at `--timeout=180 --timeout-method=thread`, so a longer inner bound lets one
hang kill the whole session instead of one test.

chip-AGNOSTIC: keys only on issue / PR / commit metadata. No design, PDK or
vendor literal anywhere in this file.

EXIT CODES
==========
    0 = report printed (competing claims may exist — this is a REPORT)
    1 = competing claims exist AND --fail-on-competing was passed
    2 = NOT CHECKED — nothing to examine, or the source could not be read
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

RC_REPORT, RC_COMPETING, RC_NOT_CHECKED = 0, 1, 2

#: Hard ceiling for any subprocess this program starts. See TIMEOUT above.
SUBPROCESS_TIMEOUT_S = 60

#: GitHub's closing keywords, plus this repo's non-closing `Advances #N`.
#: A claim is a claim whether or not it closes the issue: two PRs that each
#: "advance" one issue are exactly the population #1411 is about.
_CLAIM_BODY_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|advance[sd]?)\s*:?\s*#(\d+)",
    re.IGNORECASE,
)
#: The title convention: a trailing / embedded `(#N)`.
_CLAIM_TITLE_RE = re.compile(r"\(#(\d+)\)")

#: Basenames that carry no information about whether two changes overlap.
#: ~27 open PRs touch `INDEX.md` (it is generated from every program's
#: docstring, so any new program touches it), and counting it as a shared file
#: would classify almost every group as SHARED — which is the failure mode of
#: reading collision as meaning. #1363. Overridable via --discount.
DEFAULT_DISCOUNT = ("INDEX.md",)

SHARED, NO_SHARED_FILE, UNDETERMINED = "SHARED", "NO_SHARED_FILE", "UNDETERMINED"


# --------------------------------------------------------------------------
# the record
# --------------------------------------------------------------------------
class Claimant:
    """One change that may claim issues: a PR, or a commit in a landing.

    `files` is ``None`` when the file list was not supplied. That is NOT the
    same as an empty set, and the two are never merged — see DEGRADING LOUDLY.
    """

    __slots__ = ("ident", "title", "body", "files")

    def __init__(self, ident: str, title: str = "", body: str = "",
                 files: Optional[Set[str]] = None) -> None:
        self.ident = ident
        self.title = title or ""
        self.body = body or ""
        self.files = files

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Claimant(%s)" % self.ident


def claims(claimant: Claimant) -> Set[int]:
    """Issue numbers this claimant claims, from its body AND its title."""
    found = {int(n) for n in _CLAIM_BODY_RE.findall(claimant.body)}
    found |= {int(n) for n in _CLAIM_TITLE_RE.findall(claimant.title)}
    return found


# --------------------------------------------------------------------------
# the predicate
# --------------------------------------------------------------------------
def _effective_files(c: Claimant,
                     discount: Sequence[str]) -> Optional[Set[str]]:
    if c.files is None:
        return None
    drop = {d.lower() for d in discount}
    return {f for f in c.files if os.path.basename(f).lower() not in drop}


def classify(members: Sequence[Claimant],
             discount: Sequence[str] = DEFAULT_DISCOUNT) -> str:
    """SHARED / NO_SHARED_FILE / UNDETERMINED for one group.

    UNDETERMINED wins over NO_SHARED_FILE whenever ANY member's file list is
    missing: with a member unread, "they share nothing" is not something the
    data supports. It does NOT win over SHARED — a demonstrated overlap
    between two known members is a fact that another member's absence cannot
    take away.
    """
    sets = [_effective_files(m, discount) for m in members]
    known = [s for s in sets if s is not None]
    for i in range(len(known)):
        for j in range(i + 1, len(known)):
            if known[i] & known[j]:
                return SHARED
    if len(known) != len(sets) or len(known) < 2:
        return UNDETERMINED
    return NO_SHARED_FILE


def group_by_claim(claimants: Sequence[Claimant],
                   discount: Sequence[str] = DEFAULT_DISCOUNT,
                   ) -> List[Tuple[int, List[Claimant], str]]:
    """Every issue claimed by MORE THAN ONE claimant, with its verdict.

    Sorted by issue number so two runs over one population print the same
    bytes. The verdict is reported, never used as a filter: a group that
    shares a file is listed too, because "git would surface it" is a property
    of the tooling, not of the claim.
    """
    by_issue: Dict[int, List[Claimant]] = {}
    for c in claimants:
        for issue in claims(c):
            by_issue.setdefault(issue, []).append(c)
    out: List[Tuple[int, List[Claimant], str]] = []
    for issue in sorted(by_issue):
        members = by_issue[issue]
        if len(members) > 1:
            out.append((issue, members, classify(members, discount)))
    return out


# --------------------------------------------------------------------------
# input adapters
# --------------------------------------------------------------------------
def _files_of(record: Dict[str, Any]) -> Optional[Set[str]]:
    """`files` as gh emits it, or None when the key is absent.

    An explicitly EMPTY list stays an empty set: gh looked and found no file.
    Only an absent key is UNDETERMINED.
    """
    if "files" not in record or record["files"] is None:
        return None
    out: Set[str] = set()
    for f in record["files"]:
        if isinstance(f, str):
            out.add(f)
        elif isinstance(f, dict):
            p = f.get("path") or f.get("filename")
            if p:
                out.add(str(p))
    return out


def claimants_from_prs(records: Sequence[Dict[str, Any]]) -> List[Claimant]:
    out: List[Claimant] = []
    for r in records:
        num = r.get("number")
        out.append(Claimant(
            ident="PR #%s" % (num if num is not None else "?"),
            title=r.get("title") or "",
            body=r.get("body") or "",
            files=_files_of(r),
        ))
    return out


def load_prs_json(source: str) -> List[Dict[str, Any]]:
    """Parse a `gh pr list --json ...` payload. Raises ValueError on garbage."""
    text = sys.stdin.read() if source == "-" else Path(source).read_text()
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("expected a JSON list of PR records, got %s"
                         % type(data).__name__)
    return [d for d in data if isinstance(d, dict)]


def fetch_prs_github(repo: str, base: str) -> List[Dict[str, Any]]:
    """`gh pr list` for OPEN PRs. Raises RuntimeError so the caller can map it
    to NOT CHECKED — a failed fetch has not told us the count is zero."""
    cmd = ["gh", "pr", "list", "--repo", repo, "--base", base,
           "--state", "open", "--limit", "300",
           "--json", "number,title,body,files"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=SUBPROCESS_TIMEOUT_S)
    except FileNotFoundError:
        raise RuntimeError("the gh CLI is not installed")
    except subprocess.TimeoutExpired:
        raise RuntimeError("gh pr list exceeded %ds" % SUBPROCESS_TIMEOUT_S)
    if proc.returncode != 0:
        raise RuntimeError("gh pr list rc=%d: %s"
                           % (proc.returncode, (proc.stderr or "").strip()[:300]))
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("gh pr list emitted unparsable JSON: %s" % exc)
    return [d for d in data if isinstance(d, dict)]


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True,
                          timeout=SUBPROCESS_TIMEOUT_S)
    if proc.returncode != 0:
        raise RuntimeError("git %s rc=%d: %s"
                           % (" ".join(args), proc.returncode,
                              (proc.stderr or "").strip()[:300]))
    return proc.stdout


def claimants_from_range(repo: Path, rev_range: str) -> List[Claimant]:
    """The commits in `rev_range`, each with the files it touched.

    One `git log --name-only` for the whole range rather than one `git show`
    per commit: a landing may be a dozen commits and this runs on the landing
    path, where a slow check is a bypassed check.
    """
    sep = "\x1e"        # record separator: cannot occur in a commit message
    fsep = "\x1f"       # field separator
    raw = _git(repo, "log", "--no-merges", "--name-only",
               "--format=%s%%H%s%%s%s%%b%s" % (sep, fsep, fsep, fsep),
               rev_range)
    out: List[Claimant] = []
    for chunk in raw.split(sep):
        if not chunk.strip():
            continue
        parts = chunk.split(fsep)
        if len(parts) < 4:
            continue
        sha, subject, body, filepart = parts[0], parts[1], parts[2], parts[3]
        files = {ln.strip() for ln in filepart.splitlines() if ln.strip()}
        out.append(Claimant(ident="commit %s" % sha.strip()[:9],
                            title=subject.strip(), body=body,
                            files=files))
    return out


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
def render(groups: Sequence[Tuple[int, List[Claimant], str]],
           examined: int, source: str) -> List[str]:
    """The report, denominator first. Never silent about what it looked at.

    EVERY line starts with ``REPORT``, and that is load-bearing rather than
    decorative: the `report` helper in `tools/gatekeeper-land.sh` — the caller
    this is wired into — pipes a program's output through
    ``grep -aE 'REPORT|VIOLATION|\\[FAIL\\]|\\[SKIP\\]'`` before printing it.
    A group line that did not carry the token would be dropped from the
    landing log, leaving a summary count with nothing named under it, which is
    a silent report wearing a loud one's clothes.
    """
    lines: List[str] = []
    counts = {SHARED: 0, NO_SHARED_FILE: 0, UNDETERMINED: 0}
    for _, _, verdict in groups:
        counts[verdict] += 1
    lines.append(
        "REPORT competing-PR claims: examined %d claimant(s) from %s; "
        "%d issue(s) claimed more than once "
        "(%d no shared file, %d share a file, %d undetermined)"
        % (examined, source, len(groups), counts[NO_SHARED_FILE],
           counts[SHARED], counts[UNDETERMINED]))
    for issue, members, verdict in groups:
        lines.append("REPORT   #%-6d %-14s %s"
                     % (issue, verdict,
                        ", ".join(m.ident for m in members)))
    if groups:
        lines.append("REPORT   NOTE more than one claim is not a duplicate: a "
                     "split across several mechanisms is legitimate. What this "
                     "report asserts is only that nobody has looked yet.")
    return lines


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Report every issue claimed by more than one change, "
                    "whether or not the changes share a file (vibe-ic#1411).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--prs-json", metavar="FILE",
                     help="JSON list from `gh pr list --json "
                          "number,title,body,files`; '-' reads stdin")
    src.add_argument("--from-github", action="store_true",
                     help="run that gh pr list now (needs network + auth)")
    src.add_argument("--rev-range", metavar="A..B",
                     help="the claimants are the commits in this git range")
    ap.add_argument("--repo", default="vibeic/vibe-ic",
                    help="owner/name for --from-github (default: %(default)s)")
    ap.add_argument("--base", default="main",
                    help="base branch for --from-github (default: %(default)s)")
    ap.add_argument("--repo-root", default=".",
                    help="git checkout for --rev-range (default: %(default)s)")
    ap.add_argument("--discount", action="append", metavar="BASENAME",
                    help="a basename that does not count as a shared file "
                         "(repeatable; default: INDEX.md)")
    ap.add_argument("--fail-on-competing", action="store_true",
                    help="exit 1 when any issue has more than one claimant "
                         "(promotes this REPORT to a BLOCKING gate)")
    ap.add_argument("--json", metavar="OUT",
                    help="also write the machine-readable report here")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    discount = tuple(args.discount) if args.discount else DEFAULT_DISCOUNT

    try:
        if args.prs_json:
            src = "stdin" if args.prs_json == "-" else args.prs_json
            claimants = claimants_from_prs(load_prs_json(args.prs_json))
        elif args.from_github:
            src = "open PRs of %s against %s" % (args.repo, args.base)
            claimants = claimants_from_prs(fetch_prs_github(args.repo, args.base))
        else:
            src = "commits in %s" % args.rev_range
            claimants = claimants_from_range(Path(args.repo_root), args.rev_range)
    except (OSError, ValueError, RuntimeError,
            json.JSONDecodeError, subprocess.SubprocessError) as exc:
        # The `REPORT` token is what keeps this line in the landing log —
        # see `render`. A refusal that gets filtered out is a silent one.
        print("REPORT NOT CHECKED competing-PR claims: could not read %s: %s"
              % (args.prs_json or args.rev_range or "GitHub", exc))
        return RC_NOT_CHECKED

    if not claimants:
        # A zero denominator refuses. "No claimant" is the shape of a broken
        # query, and rendering it as a clean report is the defect this file
        # exists to stop, one level down.
        print("REPORT NOT CHECKED competing-PR claims: 0 claimant(s) from %s — "
              "nothing was examined, which is not the same as nothing found"
              % src)
        return RC_NOT_CHECKED

    groups = group_by_claim(claimants, discount)
    for line in render(groups, len(claimants), src):
        print(line)

    if args.json:
        payload = {
            "program": "competing_pr_claim_report",
            "source": src,
            "examined": len(claimants),
            "discounted_basenames": list(discount),
            "groups": [{"issue": i,
                        "claimants": [m.ident for m in ms],
                        "verdict": v} for i, ms, v in groups],
            "blocking": bool(args.fail_on_competing),
        }
        Path(args.json).write_text(json.dumps(payload, indent=2) + "\n")

    if groups and args.fail_on_competing:
        return RC_COMPETING
    return RC_REPORT


if __name__ == "__main__":
    sys.exit(main())
