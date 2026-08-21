#!/usr/bin/env python3
"""gatekeeper_stale_branch_check.py — the STALE-BRANCH / phantom-revert guard.

WHY THIS EXISTS
---------------
A PR branch cut from an OLDER base than the CURRENT `origin/main` tip carries a
trap. A naive `origin/main..HEAD` diff of such a branch shows a PHANTOM REVERT
of every commit that landed on main SINCE the fork point — so a blind
`git checkout HEAD -- <files>` land (or any "just take the PR's file versions"
merge) SILENTLY REVERTS those already-landed fixes. Two real PRs (#246, #247)
were each cut from a pre-previous-fix base; only a manual merge-base check
caught it, and both were landed correctly by CHERRY-PICKING the PR's OWN delta
(`git diff <merge-base>..HEAD`), which applies only what the PR changed and
preserves the intervening work.

This guard fossilizes that check so no future gatekeeper has to remember it. It
runs at review time (base=origin/main, head=PR-branch) and makes the risk
un-missable:

  FRESH  — merge-base(base, head) == base tip. The branch is current; an
           ordinary squash-merge cannot phantom-revert anything. rc 0.

  STALE  — merge-base != base tip. Commits landed on base since the fork. It
           then measures the ACTUAL phantom-revert surface:
             * intervening files = files changed on base since the fork
               (`git diff --name-only <merge-base>..<base-tip>`),
             * PR files          = files the PR changes
               (`git diff --name-only <merge-base>..<head>`),
             * OVERLAP           = PR files ∩ intervening files.
           OVERLAP is exactly the set a blind checkout would revert.
             - OVERLAP non-empty  -> rc 1 (BLOCK): a blind checkout WOULD
               revert landed work on these files; the land MUST be a cherry-pick
               of the PR's delta, then a grep of the intervening fixes' symbols
               to prove no false revert.
             - OVERLAP empty      -> rc 0 (ADVISORY): stale but no shared file,
               so a blind checkout could not phantom-revert; a cherry-pick of
               the true delta is still the recommended, drift-free land.

This never judges whether the PR's CHANGE is good (that is Step-2.7 + the other
gates). It only guards the LANDING METHOD against a silent revert.

THE FRESH VERDICT WAS UNEARNED (2026-08-05)
-------------------------------------------
`FRESH` above was decided by ANCESTRY ALONE — `merge-base(base, head) == base
tip` — and then asserted a property about CONTENT: "an ordinary squash-merge
cannot phantom-revert anything". Ancestry does not imply that, and a commit
proved it an hour before it would have landed:

    git diff --stat origin/main...1766746f6  ->  81 files, 1974 +, 9258 -
    git diff --stat 1a6721e15   1766746f6    ->   2 files, 1599 +,   24 -

The second line is the whole story. The commit names `origin/main` (v1.9.78) as
its PARENT but carries v1.9.77's TREE plus its author's two files. Landing it
would have reverted all 13 intervening commits: 15 files deleted (13 of them
tests), `plugin.json` walked back 1.9.78 -> 1.9.77, the test-module count 2334
-> 2322. It reverted `070aea3e8` while the very docstring it added called that
fix "#790's other half" — it shipped the caller and deleted the dependency in
one change.

Measured on that commit, EVERY landing-shape gate was green:

    gatekeeper_stale_branch_check   FRESH (merge-base == base tip)
    landing_collateral_revert_check CLEAN, "0 pair(s) examined"
    landing_is_one_commit_check     one commit ahead of base

Not an accident — the two revert guards each disclaim this case IN WRITING and
hand it to the other. `landing_collateral_revert_check`'s docstring says its
window is "this push" and that "a revert of work that landed in an EARLIER push
… is the PRE-land guard's (gatekeeper_stale_branch_check), which fires on
exactly the stale-base shape that produces it". This gate then answered FRESH,
because the head really does descend from the base tip. The graph was fresh and
the tree was stale, and nothing was looking at the tree.

The only machine gate that reddened is `version_bump_monotonic_check`, and only
by coincidence: the stale window happened to contain a version bump, so the
symptom `1.9.77 < 1.9.78` surfaced. That is a PROXY, not the property — 89 of
the last 200 commits of `main` carry no version at all (measured by
`landing_is_one_commit_check`), so a stale window made only of data-only, doc
or unversioned landings reverts just as much work and moves no version. A gate
must not rest on a coincidence of which files the reverted commits touched.

WHAT THE FRESH BRANCH NOW CHECKS — AND WHY IT IS THIS PREDICATE
--------------------------------------------------------------
When `base` IS an ancestor of `head`, the land publishes `head`'s TREE verbatim,
so the tree must be one that was built ON the base it claims:

    for every path P that `head` MODIFIES relative to `base`:
        blob(head:P) must NOT equal blob(C:P) for any strict ancestor C of
        `base` — i.e. `head` must not hold, at any path, a state `base`'s own
        history has already SUPERSEDED.

That is decidable by blob identity: no size, no ratio, no threshold, nothing to
tune and nothing to sit just under. A tree authored on `base` cannot satisfy it
by accident, because its content for those paths has never existed on `base`.

REJECTED ALTERNATIVES, on evidence:

  * "too many files / too many deletions". A legitimate refactor touches many
    files, and any threshold is a number to stay under. The measured fixture
    below makes the point concrete: a genuine removal of two dead programs and
    their thirteen tests deletes the SAME 15 paths as the defect (16 files,
    4206 deletions) — the footprint is identical and the provenance is not.
    Size cannot separate them; blob provenance does, exactly.

  * "plugin.json version strictly below base's". Already checked (see above) —
    and it is a proxy that is blind whenever the reverted commits happen not to
    ship.

  * "content on base absent from the head's tree, unless the diff is an
    intentional deletion". Undecidable as stated: a deletion IS the diff saying
    so, and "intentional" is not a machine property. Restricting the rule to
    MODIFIED paths is what makes it decidable — and it is also what keeps the
    legitimate-deletion fixture green.

  * "tracked-file count in a directory decreasing". Fires on every real removal
    and says nothing about provenance.

The rule reads: A CHANGE MUST NOT DELETE OR REVERT CONTENT IT NEVER CLAIMED TO
TOUCH — enforced as: the commit's tree must be built on the tree of the parent
it claims.

WHAT IT CANNOT SEE (stated so a clean result is not read as more than it is)
---------------------------------------------------------------------------
* A rewind to a state older than `--window` commits of `base` — a REAL bound,
  not a formality: on this repo window 300 returns rc 0 with zero findings on a
  tree that window 400 fails with 64 rewound paths. 300 landings is roughly four
  days here. Every FRESH-branch verdict therefore states whether the window was
  EXHAUSTED or covered the base's full first-parent history, so a PASS that read
  300 of 1644 commits cannot be mistaken for one that read all of them.
* A stale tree whose window contains ONLY additions, so no path it holds is a
  superseded state and the whole diff is deletions. Deletions alone are not
  evidence — that is the same fact that keeps a real removal green, and no
  discriminator was found that survives the legitimate-deletion fixture.
* A stale tree the single-commit-inverse exemption still covers. MEASURED on an
  artificial 2-commit re-parent at 300 points of `main`: 11 of 300 pass, down
  from 65 before the exemption was bounded. The stronger condition that would
  take it to 1 blocks four of the five real landings the exemption exists for,
  and was rejected on that measurement — see `_single_commit_inverse`.
* A modified path with no blob at one end (a submodule, a path git must quote).
  Counted as NOT EXAMINED and named in the verdict — never folded into the pass.
* A DECLARED revert of more than one commit fires, by design. Restoring files to
  a state `base` has moved past is precisely this rule's subject, and "publish
  and un-publish in one push" is what the sibling guard refuses too. There is no
  keyword escape, because a keyword escape is a bypass anyone can type.

MEASURED BEFORE LANDING BLOCKING
--------------------------------
    the incident commit 1766746f6                      FAIL — 64 of 65 modified
                                                       paths rewound, all 13
                                                       intervening commits named
    six clean sibling branches, all FRESH               PASS, 0 findings each
    a legitimate 16-file / 4206-line deletion fixture   PASS, 0 findings
    every single-parent landing of the last 800 on main PASS — 0 blocked,
                                                       5 disclosed as
                                                       single-commit inverses
    an artificial 2-commit re-parent at 300 points      11 of 300 still pass
                                                       (65 before the exemption
                                                       was bounded)
    the same at 3 commits of staleness                  1 of 300

MODES / CLI
-----------
    gatekeeper_stale_branch_check.py --repo <dir> --base <ref> --head <ref>
                                     [--window N] [--json <out>]

EXIT CODES
----------
  0  FRESH (and the tree rewinds nothing), or STALE with no file overlap
  1  STALE with file overlap — phantom-revert risk; land via cherry-pick
     TREE_REWIND — head claims base as its parent but does not contain it
  2  ERROR — bad usage / unresolvable ref / git failure (fail LOUD)

chip-AGNOSTIC / DETERMINISTIC: reasons over commit graph, changed-path sets and
blob identity only; no IC / vendor / SKU literal.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

GATE_NAME = "gatekeeper_stale_branch_check"

#: 0 = walk `base`'s COMPLETE first-parent history. `--window N` bounds it.
#:
#: IT WAS 300, AND THAT WAS A BLIND SPOT WITH A WRONG NAME. The comment here
#: claimed the window was a cost bound and "no result changes sign as it
#: moves". Measured, it moves the sign: window 300 -> rc 0 with zero findings on
#: a tree window 400 fails with 64 rewound paths.
#:
#: Worse, the property it bounds is not the one the name suggests. It is NOT
#: "the tree is stale by more than `window` landings" — it is "the state the
#: head holds was last written more than `window` landings before the base". A
#: tree TWO commits stale is invisible when the files those two commits touched
#: had not been touched for 300 landings before that, which is not exotic:
#: swept over 300 points of `main`, an artificial 2-commit re-parent produced
#: ZERO findings at eight of them for exactly this reason.
#:
#: So the bound is gone by default, because it was never buying anything:
#: measured on this repo, walking all 1644 first-parent commits costs 0.60 s
#: against 0.39 s for 300. `--window` remains for a repository where that trade
#: is different, and any verdict taken under one says so.
DEFAULT_WINDOW = 0


def _git(repo: Path, *args: str) -> Tuple[int, str, str]:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _rev(repo: Path, ref: str) -> str:
    rc, out, err = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if rc != 0:
        raise RuntimeError(f"cannot resolve ref {ref!r}: {err.strip()[:200]}")
    return out.strip()


def _merge_base(repo: Path, a: str, b: str) -> str:
    rc, out, err = _git(repo, "merge-base", a, b)
    if rc != 0:
        raise RuntimeError(
            f"no merge-base for {a!r} and {b!r}: {err.strip()[:200]}")
    return out.strip()


def _changed_files(repo: Path, rng: str) -> List[str]:
    rc, out, err = _git(repo, "diff", "--name-only", rng)
    if rc != 0:
        raise RuntimeError(f"git diff --name-only {rng} failed: "
                           f"{err.strip()[:200]}")
    return [ln for ln in out.splitlines() if ln.strip()]


def _name_status(repo: Path, base: str, head: str
                 ) -> Tuple[List[str], List[str], List[str]]:
    """(modified, added, deleted) between two trees.

    `-z` rather than a text parse: a NUL-delimited record cannot be corrupted by
    a path git would otherwise quote, and a path this program cannot name is a
    path it cannot check.
    """
    rc, out, err = _git(repo, "diff", "--name-status", "-z", "--no-renames",
                        base, head)
    if rc != 0:
        raise RuntimeError(f"git diff --name-status {base} {head} failed: "
                           f"{err.strip()[:200]}")
    fields = [f for f in out.split("\0") if f != ""]
    mod: List[str] = []
    add: List[str] = []
    dele: List[str] = []
    for i in range(0, len(fields) - 1, 2):
        status, path = fields[i], fields[i + 1]
        if status.startswith("M"):
            mod.append(path)
        elif status.startswith("A"):
            add.append(path)
        elif status.startswith("D"):
            dele.append(path)
    return mod, add, dele


def _window_touch_map(repo: Path, base: str, window: int
                      ) -> Tuple[Dict[str, List[str]], Dict[str, int], int]:
    """What `base`'s own recent history changed, and when.

    Returns (path -> commits that changed it NEWEST FIRST, commit -> age index
    with 0 = base tip, number of commits walked). ONE `git log` for the whole
    window rather than one per path: the per-path form is O(paths) history
    walks and was 20x slower on the incident's 65-path change-set.

    `core.quotePath=false` so a non-ASCII path arrives verbatim and can be
    matched against the diff's own `-z` output. A path git still quotes (one
    containing a newline or a quote) is counted as UNEXAMINED by the caller
    rather than silently treated as clean.
    """
    limit = [f"-{window}"] if window > 0 else []
    rc, out, err = _git(repo, "-c", "core.quotePath=false", "log",
                        *limit, "--first-parent", "--no-renames",
                        "--format=%x00%H", "--name-only", base)
    if rc != 0:
        raise RuntimeError(f"git log over {base} failed: {err.strip()[:200]}")
    touched: Dict[str, List[str]] = {}
    order: Dict[str, int] = {}
    cur: Optional[str] = None
    for line in out.splitlines():
        if line.startswith("\0"):
            cur = line[1:].strip()
            order.setdefault(cur, len(order))
        elif line.strip() and cur is not None:
            touched.setdefault(line, []).append(cur)
    return touched, order, len(order)


def _batch_blobs(repo: Path, specs: List[str]) -> Dict[str, Optional[str]]:
    """`<rev>:<path>` -> blob object name (None when it is not a blob there).

    One `git cat-file --batch-check` for every lookup in the run. `--batch-check`
    emits exactly one line per input line, so the pairing is positional and
    exact even for a path containing spaces.
    """
    if not specs:
        return {}
    proc = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch-check"],
                          input="\n".join(specs) + "\n",
                          capture_output=True, text=True)
    lines = proc.stdout.splitlines()
    out: Dict[str, Optional[str]] = {}
    for spec, line in zip(specs, lines):
        parts = line.split()
        out[spec] = parts[0] if len(parts) >= 3 and parts[1] == "blob" else None
    return out


@dataclass
class Rewind:
    path: str
    ancestor: str          # the commit of `base` whose state of `path` this is


def _single_commit_inverse(repo: Path, head: str, rewinds: List[Rewind],
                           missing: List[str],
                           deleted: Optional[List[str]] = None
                           ) -> Optional[str]:
    """The commit this rewind is the EXACT INVERSE of, or None.

    THE DISCRIMINATION, AND WHY IT IS NOT A MAGNITUDE (measured over 800)
    ---------------------------------------------------------------------
    Run over every single-parent landing of the last 800 on `main`, the raw
    rule above fires three times, and all three are the same shape:

        afce80526  body: "Reverts `fe3e32822`"           — a DECLARED revert
        c895327d4  removes a probe marker v1.9.7 landed by accident, and its
                   two `.probe-orig` backups — a REPAIR that restores the two
                   files to the state before that one commit
        3c5530564  deletes a gate whose whole entry INDEX.md had gained one
                   commit earlier, so INDEX.md returns to its exact prior state

    None is the incident's shape, and blocking any of them is how a gate gets
    switched off. What separates them is not how much they rewind — it is that
    each is the exact inverse of ONE commit that EXISTS, verifiable against it:
    `blob(head:P) == blob(M~1:P)` for every rewound path, with M the only
    commit whose work is absent. `landing_collateral_revert_check` draws the
    same line for the same reason and states it well: a revert "RESTORES a state
    the file demonstrably had", while a stale-branch land "leaves the file in a
    state it has NEVER had" — the branch's additions present, the intervening
    work missing, a composite that existed nowhere.

    So this is a structural test against a named commit, not a threshold. It
    cannot be satisfied by a tree that is missing twelve commits, and there is
    no keyword in it for anyone to type.

    `missing` IS NOT A COUNT OF THE STALE WINDOW — and this exemption used to
    behave as if it were. `missing` is the union, over REWOUND PATHS ONLY, of
    the commits that touched those paths. A commit in the stale window that only
    ADDS files touches no rewound path, so it never enters that union; and a
    stale tree deletes exactly those additions, so the whole commit disappears
    from the arithmetic. Reproduced: a tree missing TEN commits and deleting
    nine landed files came back rc 0 with "the tree is the EXACT INVERSE of one
    commit that exists" — an assertion that was simply false about that tree.
    Measured on real `main`, at SIX points in the last 300 commits a 2-commit
    stale re-parent passed at rc 0, three of them through here, one while
    rewinding six paths. The blindness was structurally unbounded, not the
    one-landing window the note below describes.

    THE BOUND, and it is the deletions rather than a bigger counter: a real
    inverse of M can only delete what M ADDED, so every deleted path must EXIST
    AT M. A deleted path that is absent at M was added by some commit the
    rewound-path union never saw, which is the pure-add commit the exemption
    cannot otherwise detect. `caller_deleted` carries the head's deletions in
    for exactly that test.

    ANCHORED AT `M`, NOT AT `M~1`. The first candidate condition used `M~1` and
    would have blocked `c895327d4` — a genuine repair whose deleted
    `.probe-orig` backups were added BY the commit it inverts, so they are
    absent at `M~1` and present at `M`. `M` is the state a true inverse restores
    the tree FROM; `M~1` is the state it restores it TO, and asking whether the
    deletions exist there asks the wrong question.

    KNOWN RESIDUAL, MEASURED rather than asserted. Driving an artificial
    2-commit re-parent at 300 points of `main`'s own history — the incident's
    mechanism at every staleness depth — and counting how many pass at rc 0:

        exemption as first written                   65 / 300
        + deletions anchored at `M` (this function)  43 / 300
        + deletions counted as missing content       11 / 300
        real landings falsely blocked, last 800       0

    The 11 are trees whose pure-add commit is OLDER than the oldest commit the
    rewinds prove missing, so nothing here proves it missing either. That is the
    price of the inequality being sound in the direction it is sound.

    THE RESIDUAL IS CONCENTRATED AT TWO. The same sweep at THREE commits of
    staleness passes 1 of 300, because a third landing is very likely to touch a
    path some rewind already proves missing. Two is where a re-parented tree and
    a revert of the tip are hardest to tell apart, and it is also where the least
    work is at stake — which is the shape a residual should have if it has to
    exist at all.

    ONE FURTHER CANDIDATE WAS MEASURED AND REJECTED, and the numbers are the
    reason rather than taste. "Every path in `diff(base, head)` must be a path
    `M` itself touched" — the change is confined to the commit it inverts —
    would catch 10 of those 11. It would also BLOCK FOUR OF THE FIVE real
    landings this exemption exists for, including a declared revert and a
    milestone. A gate that is right about 10 synthetic trees and wrong about 4
    real landings is a gate that gets switched off, which is how the hole it
    would close came to matter in the first place.

    And when `base` has advanced by exactly ONE commit AND the head deletes
    nothing that commit did not add, a re-parented stale tree and a deliberate
    revert of that commit are the same tree — no predicate can separate them,
    because there is nothing left to read. The sibling checks
    (`version_bump_monotonic_check` on a shipping commit, Step-2.7 on any) still
    see it, and every exempted verdict is DISCLOSED, never silent.
    """
    if len(missing) != 1 or not rewinds:
        return None
    m = missing[0]
    specs = ([f"{m}~1:{r.path}" for r in rewinds]
             + [f"{head}:{r.path}" for r in rewinds])
    blobs = _batch_blobs(repo, specs)
    for r in rewinds:
        before = blobs.get(f"{m}~1:{r.path}")
        if before is None or before != blobs.get(f"{head}:{r.path}"):
            return None
    if unaccounted_deletions(repo, m, deleted or []):
        return None
    return m


def unaccounted_deletions(repo: Path, inverse_of: str,
                          deleted: List[str]) -> List[str]:
    """Deleted paths that DO NOT EXIST at `inverse_of` — so it did not add them.

    Split out and named so the bound above is one readable predicate rather than
    an inline clause, and so a test can drive it directly. An empty `deleted`
    yields an empty list: a change that deletes nothing cannot be caught here,
    which is the residual the caller documents.
    """
    if not deleted:
        return []
    probe = _batch_blobs(repo, [f"{inverse_of}:{p}" for p in deleted])
    return [p for p in deleted if probe.get(f"{inverse_of}:{p}") is None]


@dataclass
class RewindReport:
    rewinds: List[Rewind] = field(default_factory=list)
    #: commits of `base` that changed a rewound path AFTER the state the head
    #: holds — the work this tree does not contain.
    missing_commits: List[str] = field(default_factory=list)
    #: paths the head DELETES that did not yet exist at the content base, i.e.
    #: `base` added them during the span this tree is missing. Reported, never
    #: the trigger: a deletion on its own is what a real removal looks like.
    collateral_deletions: List[str] = field(default_factory=list)
    #: how many paths the head deletes, whatever the verdict — so a PASS names
    #: what it erased instead of leaving the reader to assume it erased nothing.
    deletions: int = 0
    modified_examined: int = 0
    unexaminable_paths: int = 0
    window_commits: int = 0
    #: True when the walk stopped at `--window` rather than at the root, so a
    #: rewind to an older state is OUT OF REACH. False means the window covered
    #: the base's whole first-parent history and nothing older exists to miss.
    #: A PASS that examined 300 of 1644 commits must not read like one that
    #: examined all of them.
    window_exhausted: bool = False
    #: set when the whole rewind is the exact inverse of this ONE commit — a
    #: revert, not a re-parented tree. See `_single_commit_inverse`.
    inverse_of: Optional[str] = None


def tree_rewind(repo: Path, base: str, head: str,
                window: int = DEFAULT_WINDOW) -> RewindReport:
    """Paths where `head` holds a state `base`'s own history has superseded.

    PRECONDITION: `base` is an ancestor of `head` (the FRESH case). Only there
    does the land publish `head`'s tree verbatim, so only there is a rewind a
    silent revert rather than a diff artefact of an un-rebased branch — which is
    the STALE case, and the business of the overlap check above.
    """
    mod, _add, dele = _name_status(repo, base, head)
    touched, order, walked = _window_touch_map(repo, base, window)
    rep = RewindReport(modified_examined=len(mod), window_commits=walked,
                       window_exhausted=window > 0 and walked >= window)

    specs = [f"{head}:{p}" for p in mod] + [f"{base}:{p}" for p in mod]
    for p in mod:
        specs += [f"{c}:{p}" for c in touched.get(p, [])]
    blobs = _batch_blobs(repo, specs)

    missing: Set[str] = set()
    for p in mod:
        here = blobs.get(f"{head}:{p}")
        there = blobs.get(f"{base}:{p}")
        if here is None or there is None:
            # `git diff` called it MODIFIED and `cat-file` cannot produce a blob
            # for it at one of the two ends — a quoted path, a symlink or a
            # submodule. Not examined, and counted as such: "I could not look"
            # must never read as "I looked and it was clean".
            rep.unexaminable_paths += 1
            continue
        if here == there:
            continue
        history = touched.get(p, [])
        for c in history:
            if blobs.get(f"{c}:{p}") != here:
                continue
            rep.rewinds.append(Rewind(p, c))
            age = order.get(c)
            if age is not None:
                missing.update(c2 for c2 in history
                               if order.get(c2, age) < age)
            break

    if not rep.rewinds:
        return rep

    # A DELETED PATH IS MISSING CONTENT TOO, and leaving it out of this count is
    # what let a re-parented tree call itself a revert.
    #
    # `missing` above is the union, over REWOUND (modified) paths only, of the
    # commits that changed them. A commit in the stale window that ONLY ADDS
    # files touches no rewound path, so it never entered the count — and the
    # stale tree deletes exactly those additions, so the whole commit vanished
    # from the arithmetic. Swept over 300 points of `main`, an artificial
    # 2-commit re-parent passed as a "single-commit inverse" at 22 of them
    # through precisely this gap.
    #
    # The symmetric rule closes it: for a path the head does not have, the commit
    # that ADDED it is content this tree predates, exactly as a superseded blob
    # is. `h[-1]` is the oldest commit in the walk that touched the path, and it
    # is confirmed to be the creator by the path being ABSENT at its parent — so
    # a path that merely predates the walk is not miscounted.
    #
    # ONLY WHEN THE CREATING COMMIT IS PROVABLY NEWER THAN THIS TREE'S CONTENT
    # BASE. A change may perfectly well delete a file that has been there for
    # months; what a stale tree cannot do is delete a file that did not exist yet
    # at the state it was built on — it never had it to delete.
    #
    # THE DIRECTION OF THE INEQUALITY IS THE WHOLE POINT, and getting it wrong
    # cost two real landings in a measured sweep. The rewinds bound the content
    # base A from BOTH sides, and only one side is usable here:
    #
    #   * A is at least as NEW as the newest matched ancestor — an upper bound on
    #     how old A is, and useless for this test. Comparing creators against it
    #     blocked `afce80526` and `3c5530564`, whose deleted files were created
    #     BEFORE the commit they invert and therefore existed at their content
    #     base perfectly legitimately.
    #   * A is OLDER than every commit already known missing — because those
    #     commits changed a rewound path after the state this tree holds. So any
    #     commit at least as new as the OLDEST known-missing one is also newer
    #     than A, and a file it created is content this tree provably predates.
    #
    # The second is sound, and it is the one used. It is deliberately
    # CONSERVATIVE: a pure-add commit older than the oldest known-missing commit
    # is not counted, because nothing here proves it is missing.
    #
    # This cannot fail a legitimate removal: deletions only ever ADD to the
    # count, the count is only reached when a rewound MODIFIED path already
    # exists, and a pure removal has none and returns above.
    if dele and missing:
        oldest_missing = max(order.get(c, -1) for c in missing)
        oldest_touch = {p: touched[p][-1] for p in dele if touched.get(p)}
        probe = _batch_blobs(repo, [f"{c}~1:{p}"
                                    for p, c in oldest_touch.items()])
        for p, creator in oldest_touch.items():
            if probe.get(f"{creator}~1:{p}") is not None:
                continue                      # not a creation we can see
            if order.get(creator, -1) <= oldest_missing:
                missing.update(c for c in touched[p]
                               if order.get(c, -1) <= oldest_missing)

    by_age = sorted(missing, key=lambda c: order.get(c, 0))
    rep.missing_commits = by_age
    # `dele` is passed IN, and that is the whole repair: the exemption is bounded
    # by the deletions it cannot account for, because a pure-add commit in the
    # stale window touches no rewound path and so is invisible to `by_age`.
    rep.inverse_of = _single_commit_inverse(repo, head, rep.rewinds, by_age,
                                            dele)
    rep.deletions = len(dele)
    # BEFORE any early return. The deletion evidence used to be computed AFTER
    # the exemption had already returned, so the one shape that most needed
    # naming — a stale tree erasing landed files — reported its damage as one
    # path and one commit.
    #
    # It is only CALLED collateral when there is no inverse. Under an inverse the
    # bound above has already established that every deleted path exists at `M`,
    # i.e. `M` added them and undoing `M` un-adds them; labelling those
    # "collateral" would be the false statement in the other direction. The count
    # is still reported, so a passing verdict names what it erased.
    if by_age and dele and rep.inverse_of is None:
        # The content base is the commit just under the oldest missing one. A
        # path the head deletes that does not exist THERE was added by `base`
        # during the span this tree is missing, so its deletion is collateral
        # rather than authored. Same evidence, stated at the deletions.
        oldest = by_age[-1]
        probe = _batch_blobs(repo, [f"{oldest}~1:{p}" for p in dele])
        rep.collateral_deletions = [p for p in dele
                                    if probe.get(f"{oldest}~1:{p}") is None]
    return rep


@dataclass
class StaleResult:
    verdict: str                       # "FRESH" | "STALE_ADVISORY" |
                                       # "STALE_OVERLAP" | "TREE_REWIND"
    rc: int
    base_tip: str
    merge_base: str
    intervening_commits: int
    overlap_files: List[str] = field(default_factory=list)
    summary: str = ""
    #: FRESH-branch evidence. Empty on every STALE verdict, which is a different
    #: question answered by `overlap_files` above.
    rewound_files: List[str] = field(default_factory=list)
    missing_commits: List[str] = field(default_factory=list)
    collateral_deletions: List[str] = field(default_factory=list)
    deletions: int = 0
    modified_examined: int = 0
    unexaminable_paths: int = 0
    window_exhausted: bool = False
    inverse_of: Optional[str] = None


def _scope_note(rep: "RewindReport") -> str:
    """What this verdict did and did not look at. Appended to EVERY FRESH-branch
    summary, because a bound nobody is told about is a blind spot."""
    if rep.window_exhausted:
        note = (f" Searched the last {rep.window_commits} commit(s) of the base "
                f"and the WINDOW WAS EXHAUSTED — a path whose state was last "
                f"written before that is out of reach of this result.")
    else:
        note = (f" Searched all {rep.window_commits} commit(s) of the base's "
                f"first-parent history — its complete history, nothing bounded "
                f"away.")
    if rep.unexaminable_paths:
        note += (f" {rep.unexaminable_paths} modified path(s) NOT EXAMINED "
                 f"(no blob at one end — a submodule, or a path this program "
                 f"cannot name); that is not a pass over them.")
    return note


def analyze(repo: Path, base: str, head: str,
            window: int = DEFAULT_WINDOW) -> StaleResult:
    """Compute the stale-branch verdict for landing `head` onto `base`."""
    base_tip = _rev(repo, base)
    mb = _merge_base(repo, base, head)
    if mb == base_tip:
        rep = tree_rewind(repo, base, head, window)
        if rep.rewinds and rep.inverse_of is not None:
            # A revert, not a re-parented tree — and said out loud rather than
            # dropped, so a reader still sees which commit is being undone.
            return StaleResult(
                "SINGLE_COMMIT_INVERSE", 0, base_tip, mb, 0,
                summary=(
                    f"FRESH: merge-base == {base} tip ({base_tip[:9]}). "
                    f"{len(rep.rewinds)} path(s) hold an earlier state"
                    + (f" and {rep.deletions} path(s) are DELETED, every one of "
                       f"them added by that same commit," if rep.deletions
                       else ",")
                    + f" but the tree is the EXACT INVERSE of one commit that "
                      f"exists ({rep.inverse_of[:9]}) — a revert, which restores "
                      f"a state those files demonstrably had, not a tree "
                      f"re-parented onto a base it was never built on."
                    + _scope_note(rep)),
                rewound_files=[r.path for r in rep.rewinds],
                missing_commits=rep.missing_commits,
                deletions=rep.deletions,
                modified_examined=rep.modified_examined,
                unexaminable_paths=rep.unexaminable_paths,
                window_exhausted=rep.window_exhausted,
                inverse_of=rep.inverse_of)
        if rep.rewinds:
            named = [r.path for r in rep.rewinds]
            first = rep.rewinds[0]
            return StaleResult(
                "TREE_REWIND", 1, base_tip, mb, 0,
                summary=(
                    f"TREE REWIND: {head} names {base} tip ({base_tip[:9]}) as "
                    f"its parent, but its TREE does not contain that history. "
                    f"{len(named)} of the {rep.modified_examined} path(s) it "
                    f"modifies hold a blob {base} has already superseded — "
                    f"{first.path} is {base}'s state as of {first.ancestor[:9]} "
                    f"— and {len(rep.missing_commits)} commit(s) on {base} "
                    f"changed those paths after it"
                    + (f"; {len(rep.collateral_deletions)} of the deleted "
                       f"path(s) did not exist yet at that state, so their "
                       f"removal is collateral, not authored"
                       if rep.collateral_deletions else "")
                    + f". Landing this publishes and un-publishes that work in "
                      f"one step. RE-AUTHOR on top of {base} — apply the "
                      f"branch's own delta (`git diff <fork>..{head}`) or "
                      f"rebase; do NOT re-parent a tree."
                    + _scope_note(rep)),
                rewound_files=named,
                missing_commits=rep.missing_commits,
                collateral_deletions=rep.collateral_deletions,
                deletions=rep.deletions,
                modified_examined=rep.modified_examined,
                unexaminable_paths=rep.unexaminable_paths,
                window_exhausted=rep.window_exhausted)
        return StaleResult(
            "FRESH", 0, base_tip, mb, 0,
            summary=(f"FRESH: merge-base == {base} tip ({base_tip[:9]}), and "
                     f"the tree rewinds none of the {rep.modified_examined} "
                     f"path(s) it modifies." + _scope_note(rep)),
            deletions=rep.deletions,
            modified_examined=rep.modified_examined,
            unexaminable_paths=rep.unexaminable_paths,
            window_exhausted=rep.window_exhausted)
    # Stale: measure the phantom-revert surface.
    rc, out, _ = _git(repo, "rev-list", "--count", f"{mb}..{base_tip}")
    n_inter = int(out.strip() or "0") if rc == 0 else -1
    inter_files = set(_changed_files(repo, f"{mb}..{base_tip}"))
    pr_files = set(_changed_files(repo, f"{mb}..{head}"))
    overlap = sorted(inter_files & pr_files)
    if overlap:
        return StaleResult(
            "STALE_OVERLAP", 1, base_tip, mb, n_inter, overlap,
            summary=(
                f"STALE + OVERLAP: branch forked at {mb[:9]}, {n_inter} "
                f"commit(s) landed on {base} since, and the PR ALSO touches "
                f"{len(overlap)} of the files they changed "
                f"({', '.join(overlap[:6])}"
                f"{' …' if len(overlap) > 6 else ''}). A blind "
                "`git checkout HEAD -- <files>` land WOULD phantom-revert that "
                "landed work. LAND VIA CHERRY-PICK of the PR's own delta "
                f"(`git diff {mb[:9]}..{head}`), then grep the intervening "
                "fixes' symbols to prove no false revert."))
    return StaleResult(
        "STALE_ADVISORY", 0, base_tip, mb, n_inter, [],
        summary=(
            f"STALE (advisory): branch forked at {mb[:9]}, {n_inter} commit(s) "
            f"landed on {base} since, but the PR shares NO file with them — a "
            "blind checkout could not phantom-revert. Cherry-pick of the true "
            "delta is still the recommended, drift-free land."))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Landing-method guard. FAILs when a PR branch forked from "
                    "an older base AND touches a file that landed on base "
                    "since (a blind checkout would revert it), and when a "
                    "branch that NAMES the base tip as its parent carries a "
                    "tree that does not contain it.")
    ap.add_argument("--repo", default=None, help="repo root (default: cwd)")
    ap.add_argument("--base", required=True,
                    help="base ref (normally origin/main)")
    ap.add_argument("--head", required=True, help="head ref (the PR branch)")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                    help="bound the search to the last N commits of BASE's own "
                         "history (default %(default)s = its COMPLETE "
                         "first-parent history; measured 0.60s vs 0.39s for "
                         "300, so the bound bought nothing). A REAL boundary "
                         "when set: it hides a path whose state was last "
                         "written before it, not merely a tree staler than it. "
                         "Any bounded verdict says so.")
    ap.add_argument("--json", help="write a JSON report to this path")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else Path.cwd()
    if args.window < 0:
        print("error: --window must be 0 (complete history) or a positive "
              "commit count", file=sys.stderr)
        return 2
    try:
        res = analyze(repo, args.base, args.head, args.window)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(
            {"gate": GATE_NAME, **asdict(res)}, indent=2) + "\n")

    stream = sys.stderr if res.rc != 0 else sys.stdout
    # THE VERDICT FIRST, then the evidence. `gatekeeper_review.stale_branch_gate`
    # summarises this program by its FIRST line, and every caller that pipes it
    # shows a head rather than a tail; a detail line printed above the verdict
    # becomes the summary a reader acts on.
    print(f"{'FAIL' if res.rc == 1 else 'PASS'}: {res.summary}", file=stream)
    for path in res.rewound_files[:8]:
        print(f"  [REWOUND] {path}", file=stream)
    if len(res.rewound_files) > 8:
        print(f"  … and {len(res.rewound_files) - 8} more path(s)", file=stream)
    for sha in res.missing_commits[:6]:
        rc, subj, _ = _git(repo, "log", "-1", "--format=%s", sha)
        print(f"  [MISSING FROM THIS TREE] {sha[:9]} "
              f"{subj.strip()[:80] if rc == 0 else ''}", file=stream)
    if len(res.missing_commits) > 6:
        print(f"  … and {len(res.missing_commits) - 6} more commit(s)",
              file=stream)
    return res.rc


if __name__ == "__main__":
    raise SystemExit(main())
