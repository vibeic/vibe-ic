#!/usr/bin/env python3
"""tracked_symlink_portability_check.py — a tracked symlink must resolve for
everyone, not just for the machine that created it.

THIS GATE BLOCKS (rc=1).

WHY THIS GATE EXISTS
--------------------
MEASURED (#371, 2026-07-26, `benchmark-data/ic`): 172 tracked symlinks, and
159 of them recorded an ABSOLUTE target under the author's own checkout
path. They resolved on that machine and dangled in every other clone — the
content looked present (`git ls-files` lists it, a blob exists) while the
blob held only a path string.

That is not a cosmetic problem. It made a gate's verdict
environment-dependent: `evidence_citation_resolves_check` READ tracked
paths, so locally those symlinks were followed and counted and in CI they
were not — the same commit enumerated 440 documents locally and 422 in CI,
and a baseline written in one place could never match the other. Two land
attempts were refuted by CI before the cause was found.

WHAT IT CHECKS
--------------
For every tracked symlink under the scan root:

  * ABSOLUTE target      → FAIL. An absolute path encodes one machine's
                           directory layout; it cannot be portable even when
                           it happens to point inside the repository.
  * ESCAPES the repo     → FAIL. A relative target that climbs out of the
                           repository ships a pointer to content the
                           repository does not have.

A relative target that stays inside the repository is fine, INCLUDING one
that is currently dangling: that is a missing-file problem for the tree to
fix, not a portability problem, and failing on it here would conflate two
different defects. The dangling count is REPORTED on every run so it cannot
hide behind this gate's silence.

WHERE THE CORPUS IS, NOW THAT IT IS NOT HERE (#1710's treatment, applied)
-------------------------------------------------------------------------
The scan root was hardcoded to the first ancestor directory literally named
`benchmark-data`. In v1.10.56 the published corpus moved to its own
repository, and in this repo that directory is gone, so the gate answered:

    [SKIP] tracked_symlink_portability_check: no scan root
           (benchmark-data not found).                              rc 2

That refusal was CORRECT for what it was asked — a check that could not look
has not passed, and `run` in `_gate_dispatch.sh` maps rc 2 to FAIL, so it
blocked every landing. What was wrong is WHERE IT WAS TOLD TO LOOK, and that
"the corpus is somewhere else" and "somebody pointed me at a corpus and was
wrong" came out as the same word.

`benchmark_evidence_structure_check` (vibe-ic#1710, landed v1.10.51) separated
three outcomes that had been one, and this gate now separates the same three:

    $VIBE_IC_BENCHMARK_DATA set + unreadable   -> UNDETERMINED (rc 2). Somebody
                                                  said where the corpus is and
                                                  was wrong. NEVER excused, with
                                                  or without the flag below.
    nothing set, nothing local, and the
      CALL SITE passed --corpus-may-be-absent  -> NO_CORPUS (rc 0). Nothing was
                                                  scanned and NOTHING IS CLAIMED
                                                  to have been scanned.
    nothing set, nothing local, nobody
      said so                                  -> UNDETERMINED (rc 2). Unchanged.

The override is ANNOUNCED. A gate that silently scans a different tree from the
one named on its command line is how a `--tree` typo once reported "13/28
conformant" over a tree an absolute path found 8 failures in.

The relaxation is opt-in AT THE CALL SITE and is not the default, because the
dangerous row is the middle one: an rc 0 for a scan that did not happen is the
false certificate this whole gate suite exists to remove. And it must not
weaken the gate where a corpus IS supplied — vibe-ic#1700 recorded 31 dangling
`steps/` pointers in that corpus, and pointing $VIBE_IC_BENCHMARK_DATA at a
clone has to keep finding them.

chip-AGNOSTIC: pure git/filesystem structure. No design, PDK or vendor
literal appears here.

USAGE
-----
    python3 tracked_symlink_portability_check.py [ROOT] [--json OUT]
                                                 [--corpus-may-be-absent]
    VIBE_IC_BENCHMARK_DATA=/path/to/benchmark-data-clone \
        python3 tracked_symlink_portability_check.py

EXIT CODES
----------
    0 = PASS, or NO_CORPUS (opted in, and it says nothing was scanned)
    1 = FAIL (non-portable symlink)
    2 = UNDETERMINED (no scan root, or a corpus pointer that is set and wrong)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _corpus_location as _cloc  # noqa: E402

_DEFAULT_ROOT_REL = "benchmark-data"

#: The name this gate prints itself under.
GATE = "tracked_symlink_portability_check"

#: Where a caller may point us at a clone of the published corpus.
#:
#: Spelled the same way `benchmark_evidence_structure_check.CORPUS_ENV` and
#: `programs/tests/_published_corpus.CORPUS_ENV` spell it, on purpose: one name
#: for one thing. Gates that disagree about where the corpus lives will
#: disagree about whether it was checked.
CORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"


def _repo_root(start: Path):
    r = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def tracked_symlinks(root: Path) -> List[str]:
    """Paths (relative to `root`) of tracked entries whose index mode is
    120000. Read from the INDEX, never from a filesystem walk, so the answer
    does not depend on what the walk can follow."""
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "-z"],
                           capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    out = r.stdout.decode("utf-8", "replace")
    found = []
    for ent in out.split("\0"):
        if not ent or "\t" not in ent:
            continue
        meta, path = ent.split("\t", 1)
        if meta.split(" ", 1)[0] == "120000":
            found.append(path)
    return found


def audit(root: Path, repo: Path) -> Dict:
    findings: List[Dict[str, str]] = []
    dangling: List[str] = []
    links = tracked_symlinks(root)
    for rel in links:
        p = root / rel
        try:
            target = os.readlink(p)
        except OSError:
            continue
        if os.path.isabs(target):
            findings.append({
                "path": rel, "target": target, "why": "absolute target",
                "detail": ("an absolute path encodes one machine's directory "
                           "layout and cannot resolve in another checkout, "
                           "even when it points inside this repository")})
            continue
        resolved = os.path.normpath(os.path.join(str(p.parent), target))
        try:
            Path(resolved).relative_to(repo)
        except ValueError:
            findings.append({
                "path": rel, "target": target, "why": "escapes the repository",
                "detail": ("the repository does not contain the target, so "
                           "this ships a pointer to content nobody else has")})
            continue
        if not Path(resolved).exists():
            dangling.append(rel)
    return {"program": "tracked_symlink_portability_check",
            "symlinks": len(links), "findings": findings,
            "dangling_inside_repo": len(dangling),
            "passed": not findings}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("root", nargs="?", default=None)
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="the caller asserts this repo need not carry the "
                         "published corpus. Turns 'no corpus discoverable "
                         "anywhere' from UNDETERMINED into NO_CORPUS (rc 0), "
                         "which STATES that nothing was scanned. It does NOT "
                         f"excuse a pointer that is set and broken: ${CORPUS_ENV} "
                         "aimed at something unreadable is UNDETERMINED with or "
                         "without this flag.")
    args = ap.parse_args(argv)

    here = Path(__file__).resolve()
    named = args.root or _DEFAULT_ROOT_REL

    # THE POINTER REPLACES A MISSING TREE; IT DOES NOT REPLACE A PRESENT ONE
    # (#1710, corrected 2026-08-20).
    #
    # The shipped call site passes no root at all and the fallback is a literal
    # directory name that no longer exists in this repository, so the pointer must
    # still answer for it: rewriting the call site instead would leave every OTHER
    # caller — agents, local runs, the benchmark-agent skill — aimed at a directory
    # that is gone.
    #
    # But it used to answer for an EXPLICIT `root` argument too, and an environment
    # default outranking an explicit command-line argument is backwards: a caller
    # who names a directory that CARRIES a tree has named a readable corpus, and
    # walking a different one instead is the very substitution the announcement
    # below exists to prevent. `_corpus_location.resolve` is where that rule lives
    # and its test is `named.is_dir()` — an absent literal still falls through to
    # the pointer, a real one does not.
    env_tree = _cloc.env_pointer()
    if env_tree and args.root:
        _named_root = Path(args.root)
        if _named_root.is_dir():
            # Declining the pointer is announced too: a reader who has it set
            # would otherwise have no way to know which tree produced the verdict.
            print(f"[{GATE}] note: scanning the corpus at the named root "
                  f"({_named_root}); {CORPUS_ENV}={env_tree} is set and NOT "
                  f"followed, because the named root carries a tree of its own.",
                  file=sys.stderr)
            env_tree = None
        elif not _cloc.pointer_may_replace(_named_root):
            print(f"[{GATE}] note: {CORPUS_ENV}={env_tree} is set and NOT "
                  f"followed: {_named_root} is not the repository-relative "
                  f"`{_cloc.CANONICAL_CORPUS_NAME}` location the pointer "
                  f"replaces, so this verdict is about the path you named.",
                  file=sys.stderr)
            env_tree = None
    if env_tree:
        print(f"note: {CORPUS_ENV} overrides {named} -> {env_tree}",
              file=sys.stderr)
        if not Path(env_tree).is_dir():
            # SET AND WRONG IS NOT ABSENT. Laundering it as NO_CORPUS would turn
            # a mistyped path, a failed clone or a no-op CI fetch step into a
            # green gate over nothing — the exact shape #1710 closed.
            print(f"UNDETERMINED: {CORPUS_ENV}={env_tree} is set and is not a "
                  f"readable directory, so this gate enumerated no tracked "
                  f"symlink and examined nothing. A pointer that is set and "
                  f"wrong is a broken configuration, not an absent corpus, and "
                  f"--corpus-may-be-absent does not excuse it.", file=sys.stderr)
            return 2
        # A DIRECTORY IS NOT A CHECKOUT, and this gate reads git's INDEX.
        #
        # `tracked_symlinks()` asks `git ls-files` and returns [] when git exits
        # non-zero. Over a corpus that is present but is NOT a git checkout that
        # empty list reaches `audit()` as "no symlinks", `passed` stays True, and
        # the program prints
        #
        #     [PASS] every tracked symlink is relative and stays inside the repository.
        #
        # Measured on two corpora built byte-identically except for `git init`, both
        # physically carrying one absolute-target symlink:
        #     git checkout -> [FAIL] 1 non-portable tracked symlink … (absolute target)  rc=1
        #     plain dir    -> 0 tracked symlink(s) … [PASS]                              rc=0
        #
        # The corpus lives in its own repository now, so a tarball fetch, an archive
        # export, a `git clone` that died, or a worktree without `.git` all produce
        # the second input. That is a FAILED FETCH CERTIFYING A TREE — strictly worse
        # than NO_CORPUS, which at least states that nothing was scanned.
        #
        # `tracked_symlink_target_present_check.py` already refuses this via
        # `_git_toplevel()`. Handed the same directory the two gates disagreed;
        # they no longer do.
        _probe = subprocess.run(
            ["git", "-C", env_tree, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=60)
        if _probe.returncode != 0 or not _probe.stdout.strip():
            print(f"UNDETERMINED: {CORPUS_ENV}={env_tree} exists but is not a git "
                  f"checkout, and this gate reads git's INDEX — a loose directory "
                  f"has none to ask. Enumerating zero tracked symlinks there is "
                  f"'I could not look', not 'there are none'.", file=sys.stderr)
            return 2
        root = Path(env_tree)
    elif args.root:
        root = Path(args.root)
    else:
        root = next((b / _DEFAULT_ROOT_REL for b in here.parents
                     if (b / _DEFAULT_ROOT_REL).is_dir()), None)

    if root is None or not root.is_dir():
        if args.corpus_may_be_absent:
            # rc 0, and it must never read as a scan that happened.
            print(f"NO_CORPUS: nothing at {named} and {CORPUS_ENV} is unset. "
                  f"The published corpus lives in its own repository and this "
                  f"repo is not required to carry it. NOTHING WAS SCANNED, "
                  f"0 tracked symlinks were examined and nothing is claimed — "
                  f"point {CORPUS_ENV} at a clone to make this gate check "
                  f"something.", file=sys.stderr)
            return 0
        print(f"UNDETERMINED: no scan root ({named} is not a directory), so "
              f"this gate enumerated nothing and examined nothing. A check "
              f"that could not look has not passed — set {CORPUS_ENV}, or pass "
              f"--corpus-may-be-absent if this repo need not carry a corpus.",
              file=sys.stderr)
        return 2
    repo = _repo_root(root) or root
    rep = audit(root, repo.resolve())
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rep, indent=2) + "\n")

    print(f"tracked_symlink_portability_check: {rep['symlinks']} tracked "
          f"symlink(s) under {root}")
    # Reported, never gated — a dangling relative link is a missing FILE, a
    # different defect from a non-portable POINTER. Printing it keeps this
    # gate's silence from reading as "and nothing else is wrong".
    print(f"  dangling (relative, inside repo): "
          f"{rep['dangling_inside_repo']} — not gated here, a missing file "
          f"is a different defect from a non-portable pointer")
    if rep["findings"]:
        print(f"[FAIL] {len(rep['findings'])} non-portable tracked symlink(s):")
        for f in rep["findings"][:20]:
            print(f"   {f['path']} -> {f['target']}  ({f['why']})")
        if len(rep["findings"]) > 20:
            print(f"   ... and {len(rep['findings']) - 20} more (this line is "
                  f"the disclosure, not a silent truncation)")
        return 1
    print("[PASS] every tracked symlink is relative and stays inside the "
          "repository.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
