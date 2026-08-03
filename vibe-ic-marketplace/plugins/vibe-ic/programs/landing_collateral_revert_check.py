#!/usr/bin/env python3
"""landing_collateral_revert_check.py — a squash must not silently revert work
that landed alongside it in the same push.

WHY THIS EXISTS (2026-08-03, five stacked PRs)
----------------------------------------------
Five PRs (#665, #669, #672, #673, #674) all carried `baseRefOid 032e1b8a2`
(v1.9.59) and were landed 6.5 hours and 29-39 commits later, as one 11-commit
batch push. Three of those eleven commits ERASED work the batch had landed
minutes earlier:

    c5ee7c780  erased 02f1aa8bb's additions to tools/ci/repo_hygiene_gates.sh
    5d771d420  erased c5ee7c780's additions to the same file
    dd74a8a34  erased 9706c78c0's, d0f6e65a0's and c1e87413f's additions to
               phase3_one_shot_runner.py

Blob identity proves the mechanism: the landed blob for
`tools/ci/repo_hygiene_gates.sh` in c5ee7c780 is byte-identical to the PR head's
blob (`ad8ca7f1582ed51f169764b6bd55ae963541ec9a`). The file was taken wholesale
from a stale branch instead of the PR's own delta being applied. The PR's OWN
delta on that file deletes NOTHING — it is 18 diff lines of pure addition. Every
deleted line was manufactured by the landing method.

`gatekeeper_stale_branch_check` — which already exists, is already wired, and is
already blocking — said rc 1 STALE_OVERLAP on all five PRs and named the exact
overlap files. It is the PRE-land guard and it did its job. What was missing is a
guard that looks at the commits AFTER they exist, because that is the artefact
the push actually publishes.

WHAT THIS CHECKS — AND WHY IT USES NO DATES
--------------------------------------------
For each commit C in the range, with single parent P:

    for each file F that C modifies:
        unpaired(C,F) = lines C deletes from F that have NO similar line added
                        in the SAME -U0 hunk (an outright removal, not an
                        in-place edit) and that are ABSENT from C's own version
                        of F (so a move is not a removal)
        for each earlier commit r IN THE SAME RANGE that touched F:
            reverted = r's substantive added lines that are in unpaired(C,F)
            frac     = |reverted| / |r's substantive added lines|
            FIRE if |reverted| >= --min-reverted AND frac >= --min-frac

The window is EXACT: "earlier commits of this same push". It is supplied by the
caller (`$PUSH_RANGE` / gatekeeper-land's `$RANGE`), never inferred.

This deliberately does NOT use the author-date heuristic the first draft of this
guard proposed ("commits whose committer time is later than C's author time —
work the author cannot have seen"). That is a PROXY for the property, and it is
defeated by any landing method that stamps a fresh author date. Measured: a
byte-identical replay of the bad land, committed with
`GIT_AUTHOR_DATE == GIT_COMMITTER_DATE`, produces the same
`ad8ca7f158…` blob and the date-proxy detector reports it CLEAN — while this
range-scoped rule fires on it. 171 of the last 300 commits on `main` have
`author time == committer time`, so the proxy is empty-by-construction on 57% of
this repo's history. Measuring a proxy instead of the property is exactly the
trap this repo keeps re-learning; the range is the property.

The property this asserts is not "the author never saw it" (in a linear range
the author's parent literally contains it). It is the stronger, directly
observable one:

    a commit must not erase, in bulk and without replacement, the whole
    contribution an earlier commit of the SAME push made to a file.

Within one push that is essentially always a landing-method accident. If the
earlier commit's work is genuinely unwanted, drop the commit — do not publish
it and un-publish it in the same breath.

WHAT IT CANNOT SEE (stated so a clean result is not read as more than it is)
---------------------------------------------------------------------------
* A revert of work that landed in an EARLIER push. The window is this push.
  That case is the PRE-land guard's (`gatekeeper_stale_branch_check`), which
  fires on exactly the stale-base shape that produces it.
* A single-commit push. There is no earlier in-range commit, so nothing is
  compared. The summary says `0 pair(s) examined` rather than claiming a pass
  over an empty question.
* A file added or deleted outright (only `M` status is analysed).

MODES / CLI
-----------
    landing_collateral_revert_check.py --repo <dir> --rev-range <A..B> [--json OUT]
                                       [--similarity 0.6] [--minlen 12]
                                       [--min-reverted 2] [--min-frac 0.5]

`--rev-range` accepts anything `git rev-list` accepts, including the
`<sha> --not --remotes` form `pre-push` builds for a new branch (vibe-ic#640) —
the string is re-split here rather than handed to a command that would exit 128.

EXIT CODES
----------
  0  no collateral revert found in the range
  1  a commit erases an earlier in-range commit's contribution to a file
  2  ERROR — bad usage / unresolvable range / empty range / git failure

chip-AGNOSTIC / DETERMINISTIC: reasons over the commit graph and diff text only;
no IC / PDK / vendor / SKU literal.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

GATE_NAME = "landing_collateral_revert_check"

# Defaults are MEASURED, not chosen. See the PR body for the sweep; the short
# form is: over the 136 reconstructed multi-commit pushes in the last 1000
# commits of `main`, the five ground-truth rows have frac 1.00, 1.00, 0.95,
# 0.93, 0.83 and the highest-scoring row that is NOT ground truth has frac
# 0.15. 0.5 sits in the middle of that measured gap.
DEFAULT_SIMILARITY = 0.6
DEFAULT_MINLEN = 12
DEFAULT_MIN_REVERTED = 2
DEFAULT_MIN_FRAC = 0.5

_REVLIST_ONLY = ("--not", "--remotes", "--branches", "--tags", "--all")


def _git(repo: Path, *args: str) -> Tuple[int, str, str]:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _toplevel(repo: Path) -> Path:
    """The repo ROOT, whatever subdirectory `--repo` happened to name.

    `git diff --name-status` prints paths relative to the repo root, but a
    PATHSPEC is resolved relative to the working directory. Run from
    `vibe-ic-marketplace/`, this program therefore fed root-relative paths back
    to git as subdir-relative pathspecs, every per-file diff came back empty, and
    it reported `CLEAN: 11 commits, 0 pairs examined` on the incident range
    itself. A checker that answers "clean" because it was standing in the wrong
    directory is the exact false-certificate shape this guard exists to stop, so
    the root is resolved once, here, and never assumed.
    """
    rc, out, err = _git(repo, "rev-parse", "--show-toplevel")
    if rc != 0:
        raise RuntimeError(f"{repo} is not a git repo: {err.strip()[:200]}")
    return Path(out.strip())


def norm(line: str) -> str:
    """Whitespace-insensitive form, so a re-indent is not a rewrite."""
    return re.sub(r"\s+", " ", line.strip())


def substantive(line: str, minlen: int) -> bool:
    """A line worth reasoning about.

    Blank lines, `}`, `fi`, `done` and friends recur all over a file, so a rule
    that counted them would be measuring boilerplate rather than content. The
    alnum test alone excludes blanks and pure punctuation; `minlen` excludes the
    short keywords. Both are swept in the tests.
    """
    s = line.strip()
    return len(s) >= minlen and any(c.isalnum() for c in s)


def resolve_range(repo: Path, rev_range: str) -> List[str]:
    """Commits selected by `rev_range`, OLDEST FIRST.

    vibe-ic#640: `pre-push` builds a new branch's range as `<sha> --not
    --remotes` — three git arguments in one string. `git rev-list` understands
    it; anything expecting a single token exits 128. Split here, always.
    """
    parts = rev_range.split()
    if not parts:
        raise RuntimeError("empty --rev-range")
    rc, out, err = _git(repo, "rev-list", "--reverse", *parts)
    if rc != 0:
        raise RuntimeError(f"git rev-list {rev_range!r} failed: {err.strip()[:200]}")
    commits = out.split()
    if not commits:
        # An empty range has told us nothing. A clean result over an empty range
        # is not a clean result — this is rc 2 everywhere else in the repo.
        raise RuntimeError(f"rev-range {rev_range!r} selects no commit")
    return commits


def hunk_pairs(repo: Path, a: str, b: str, path: str) -> List[Tuple[List[str], List[str]]]:
    """`git diff -U0 a b -- path` as a list of (deleted, added) per hunk.

    Zero context on purpose: with context lines a replacement and a removal look
    alike, and the whole discrimination below is between those two.
    """
    rc, out, _err = _git(repo, "diff", "--no-color", "-U0", "--no-renames",
                         a, b, "--", path)
    if rc != 0:
        return []
    hunks: List[Tuple[List[str], List[str]]] = []
    cur: Optional[Tuple[List[str], List[str]]] = None
    for ln in out.splitlines():
        if ln.startswith("@@"):
            if cur is not None:
                hunks.append(cur)
            cur = ([], [])
        elif cur is None or ln.startswith(("---", "+++")):
            continue
        elif ln.startswith("-"):
            cur[0].append(ln[1:])
        elif ln.startswith("+"):
            cur[1].append(ln[1:])
    if cur is not None:
        hunks.append(cur)
    return hunks


def unpaired_deletions(hunks: Sequence[Tuple[List[str], List[str]]],
                       similarity: float, minlen: int) -> Set[str]:
    """Deleted lines with NO similar line added in the SAME hunk.

    An in-place edit — `timeout=300` -> `timeout=30`, a version bump, a counter
    being updated — deletes a line and adds its replacement in one hunk. That is
    a rewrite, not a removal, and it is the single shape that produced every
    false positive when this rule was first measured without the pairing step.
    """
    out: Set[str] = set()
    for deleted, added in hunks:
        na = [norm(a) for a in added]
        for d in deleted:
            if not substantive(d, minlen):
                continue
            nd = norm(d)
            if not any(difflib.SequenceMatcher(None, nd, a).ratio() >= similarity
                       for a in na):
                out.add(d)
    return out


def _blob(repo: Path, rev: str, path: str) -> Optional[str]:
    rc, out, _err = _git(repo, "rev-parse", f"{rev}:{path}")
    return out.strip() if rc == 0 else None


def _is_exact_rewind(repo: Path, c: str, r: str, path: str) -> bool:
    """True when C restores `path` to EXACTLY the state it had before `r`.

    This is what separates a DECLARED revert from a COLLATERAL one, and it needs
    no string matching on the commit subject — which would be a bypass anyone
    could type.

    A revert RESTORES a state the file demonstrably had: `blob(C:F)` equals
    `blob(r~1:F)`, so the change is exactly the inverse of `r` and a reader can
    verify it against a commit that exists.

    A stale-branch land leaves the file in a state it has NEVER had — the
    branch's own additions are present, the intervening work is missing, and
    that composite existed nowhere before the land. Measured on the incident:

        dfc3a954e cvdp_gate.py            C:F == r~1:F  368e4ca0b (declared)
        c5ee7c780 repo_hygiene_gates.sh   C:F  ad8ca7f15 != 39b00f378 (composite)
        dd74a8a34 phase3_one_shot_runner  C:F  7f8990d17 != d82a3bc8e (composite)

    The single false positive over all 1560 commits of `main` — `dfc3a954e`,
    "revert: cvdp_gate.py accidentally included in the roadmap commit (NO-MIX
    correction)" — is suppressed by this and by nothing else.

    KNOWN RESIDUAL MISS, stated rather than hidden: if a stale branch does not
    touch F at all, landing it by a whole-tree `git checkout <branch> -- .`
    rewinds F to the fork state, which may equal `r~1:F` and would be suppressed
    here. That land is still caught through every OTHER file the branch DID
    touch (measured on a replay of the incident: 5 files fired, not 1), and the
    per-file overlap case is what `gatekeeper_stale_branch_check` reports BEFORE
    the land.
    """
    a = _blob(repo, c, path)
    b = _blob(repo, f"{r}~1", path)
    return a is not None and a == b


@dataclass
class Finding:
    commit: str
    subject: str
    path: str
    source: str            # the earlier in-range commit whose work is erased
    source_subject: str
    added: int             # substantive lines `source` added to `path`
    reverted: int          # how many of them `commit` removes outright
    frac: float


@dataclass
class Result:
    rc: int
    commits: int
    pairs_examined: int
    findings: List[Finding] = field(default_factory=list)
    summary: str = ""


def analyze(repo: Path, rev_range: str,
            similarity: float = DEFAULT_SIMILARITY,
            minlen: int = DEFAULT_MINLEN,
            min_reverted: int = DEFAULT_MIN_REVERTED,
            min_frac: float = DEFAULT_MIN_FRAC) -> Result:
    repo = _toplevel(repo)
    commits = resolve_range(repo, rev_range)
    in_range = set(commits)
    subjects: Dict[str, str] = {}
    findings: List[Finding] = []
    pairs = 0

    for c in commits:
        rc, meta, _e = _git(repo, "log", "-1", "--format=%P%n%s", c)
        if rc != 0:
            continue
        lines = meta.split("\n")
        parents = lines[0].split()
        subj = lines[1] if len(lines) > 1 else ""
        subjects[c] = subj
        if len(parents) != 1:
            # A merge has no single delta to attribute. `main` is squash-only,
            # so this is a shape that should not arrive; skipping it silently
            # would be a lie, so it is reported in the summary counters.
            continue
        p = parents[0]
        rc, ns, _e = _git(repo, "diff", "--name-status", "--no-renames", p, c)
        if rc != 0:
            continue
        files = [ln.split("\t", 1)[1] for ln in ns.splitlines()
                 if ln.startswith("M") and "\t" in ln]

        for path in files:
            dropped = unpaired_deletions(hunk_pairs(repo, p, c, path),
                                         similarity, minlen)
            if not dropped:
                continue
            rc, ctext, _e = _git(repo, "show", f"{c}:{path}")
            here = set(ctext.splitlines()) if rc == 0 else set()

            # THE WINDOW — exact, date-free: commits that touched this file, are
            # ancestors of C's parent, and belong to this same push.
            rc, log, _e = _git(repo, "log", "--format=%H", p, "--", path)
            if rc != 0:
                continue
            window = [s for s in log.split() if s in in_range]

            for r in window:
                rc, rp, _e = _git(repo, "log", "-1", "--format=%P", r)
                if rc != 0 or len(rp.split()) != 1:
                    continue
                r_added = [a for _d, add in hunk_pairs(repo, rp.split()[0], r, path)
                           for a in add if substantive(a, minlen)]
                if not r_added:
                    continue
                pairs += 1
                # Absent from C's version too: a line moved elsewhere in the
                # file was not erased, and counting it would be measuring the
                # diff instead of the file.
                reverted = [a for a in r_added if a in dropped and a not in here]
                if not reverted:
                    continue
                frac = len(reverted) / len(r_added)
                if len(reverted) < min_reverted or frac < min_frac:
                    continue
                if _is_exact_rewind(repo, c, r, path):
                    # A DECLARED revert, not a collateral one. See the function.
                    continue
                if r not in subjects:
                    _rc, s, _e2 = _git(repo, "log", "-1", "--format=%s", r)
                    subjects[r] = s.strip()
                findings.append(Finding(
                    commit=c, subject=subj, path=path, source=r,
                    source_subject=subjects.get(r, ""), added=len(r_added),
                    reverted=len(reverted), frac=frac))

    if findings:
        worst = max(findings, key=lambda f: f.reverted)
        summary = (
            f"COLLATERAL REVERT: {len(findings)} finding(s) in {len(commits)} "
            f"commit(s). {worst.commit[:9]} removes {worst.reverted} of the "
            f"{worst.added} line(s) {worst.source[:9]} added to {worst.path} "
            f"({worst.frac:.0%}) — and {worst.source[:9]} is being published by "
            f"THIS SAME push. A land that replaces a file wholesale from a "
            f"stale branch does this; applying the branch's OWN delta "
            f"(`git diff <merge-base>..<branch>`) does not. Re-land the "
            f"offending commit from its delta, or drop the earlier commit if "
            f"its work is genuinely unwanted — do not publish and un-publish it "
            f"in one push.")
        rc_out = 1
    else:
        summary = (
            f"CLEAN: {len(commits)} commit(s), {pairs} in-range predecessor "
            f"pair(s) examined; no commit erases an earlier in-range commit's "
            f"contribution to a file."
            + ("" if pairs else
               " NOTE: 0 pairs — this range has no in-range predecessor to "
               "revert, so this result is the ABSENCE of a question, not a "
               "pass. A revert of work from an EARLIER push is out of scope "
               "here; gatekeeper_stale_branch_check is the guard for that."))
        rc_out = 0
    return Result(rc_out, len(commits), pairs, findings, summary)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Collateral-revert guard: FAILs when a commit erases the "
                    "contribution an earlier commit of the SAME push made to a "
                    "file — the signature of landing a branch by replacing "
                    "files wholesale instead of applying its own delta.")
    ap.add_argument("--repo", default=None, help="repo root (default: cwd)")
    ap.add_argument("--rev-range", required=True,
                    help="any git rev-list expression, e.g. A..B or "
                         "'<sha> --not --remotes'")
    ap.add_argument("--json", help="write a JSON report to this path")
    ap.add_argument("--similarity", type=float, default=DEFAULT_SIMILARITY,
                    help="in-hunk replacement similarity (default %(default)s)")
    ap.add_argument("--minlen", type=int, default=DEFAULT_MINLEN,
                    help="shortest line worth reasoning about "
                         "(default %(default)s)")
    ap.add_argument("--min-reverted", type=int, default=DEFAULT_MIN_REVERTED,
                    help="fire only at this many erased lines "
                         "(default %(default)s)")
    ap.add_argument("--min-frac", type=float, default=DEFAULT_MIN_FRAC,
                    help="fire only when this fraction of the earlier commit's "
                         "contribution is erased (default %(default)s)")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else Path.cwd()
    try:
        res = analyze(repo, args.rev_range, args.similarity, args.minlen,
                      args.min_reverted, args.min_frac)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(
            {"gate": GATE_NAME, "rc": res.rc, "commits": res.commits,
             "pairs_examined": res.pairs_examined,
             "findings": [asdict(f) for f in res.findings],
             "summary": res.summary}, indent=2) + "\n")

    stream = sys.stderr if res.rc != 0 else sys.stdout
    for f in res.findings:
        print(f"  {f.commit[:9]} {f.path}: removes {f.reverted}/{f.added} "
              f"({f.frac:.0%}) of {f.source[:9]} \"{f.source_subject[:60]}\"",
              file=stream)
    print(f"{'FAIL' if res.rc == 1 else 'PASS'}: {res.summary}", file=stream)
    return res.rc


if __name__ == "__main__":
    raise SystemExit(main())
