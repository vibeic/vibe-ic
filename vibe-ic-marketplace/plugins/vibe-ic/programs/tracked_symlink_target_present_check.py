#!/usr/bin/env python3
"""A committed pointer to a file that does not exist — anywhere.

WHY THIS EXISTS (vibe-ic#555)
=============================
`gate_host_independence_check` reported `published_record_staleness_check` as
HOST_DEPENDENT: the same commit adjudicated 225 records in a working checkout
and 224 in a fresh worktree. Traced to one record, which turned out to be a
SYMLINK whose target is not tracked:

    ic/sha256/clean_run_v1427_.../steps/32_.../eco_log.json
        -> ../../phase3/stage3/eco/eco_log.json     (not in git)

The pointer is committed. The target exists only where someone ran the flow. So
the corpus a gate reads is a function of what that machine happens to have done,
and every ratio computed over it is machine-specific.

THEN THE MEASUREMENT MOVED THE PROBLEM
======================================
I first framed this as a corpus-policy question with three answers — commit the
targets, drop the pointers, or exempt them by name. Counting properly settled it
instead:

    tracked symlinks under benchmark-data       172
    …whose target is not tracked by git          43
    …of those, unresolvable ON THIS BOX TOO      28

Twenty-eight are not "present here, absent there". They are broken everywhere,
including on the machine that published them. Seven are `.json` — files a gate
would read as a published record if they resolved. The corpus states that a step
produced an artefact and points at nothing.

That is a defect rather than a choice, and it needed no policy decision. What it
needed was for something to fail on it.

WHY A SECOND PROGRAM AND NOT A FLAG ON THE FIRST
=================================================
`tracked_symlink_portability_check` already counts these, and deliberately does
not gate them — its subject is whether a pointer is relative and stays inside
the repo, and its own comment says a dangling link "is a missing FILE, a
different defect". That reasoning is right, and the gap it names is real: the
count was reported on every run and nothing ever failed on it.

So this is the gate for the defect that one declines, with the same population
and the opposite question.

WHAT IT DOES NOT DO
===================
It does not repair anything. Correcting `benchmark-data` is the benchmark-agent's
commit under NO-MIX — results and plugin fixes never share one, or a hand-patch
could inflate a published number. This names the files and refuses.

A BASELINE, BECAUSE THE DEBT IS SOMEONE ELSE'S TO PAY
======================================================
Wiring an unconditional rc 1 into CI would leave main permanently red on a
defect this plugin is forbidden to fix, and a permanently-red gate is an ignored
gate — the failure mode half this repo's recent history is about. So the 28 are
recorded, the register MAY ONLY SHRINK, anything NEW fails, and an entry that
starts resolving fails too so the register cannot become standing permission.

ZERO POINTERS IS AN ANSWER; ZERO CORPUS IS NOT (vibe-ic#1700)
=============================================================
`git ls-files` returning no symlink used to end the run at rc 2, on the reading
that "no symlink at all" can only mean the subdir is wrong or the corpus is
missing. That reading was true while `benchmark-data/ic` carried 172 of them.
It stopped being true when the published cells moved to `vibeic/benchmark-data`
and the 31 dangling `steps/` pointers #1700 names left this repository with
them. Measured at that commit (c5d7f2d00): what remains under `benchmark-data/`
is 527 tracked files, 0 of them symlinks, and 0 `steps/` paths at all.

So the gate refused, and `run` in `_gate_dispatch.sh` maps rc 2 to FAIL — the
sweep that `tools/gatekeeper-land.sh` runs before every landing failed on a
gate whose population had legitimately gone to zero.

The distinction the program was missing is the one this repository states
everywhere else: a command that could not look is not a zero, but a command
that LOOKED and found nothing is. Both are now asked separately:

    tracked paths under <subdir> == 0  ->  rc 2, could not look (wrong path,
                                           corpus absent) — unchanged
    tracked paths  > 0, symlinks == 0  ->  rc 0, WITH the denominator printed

The FAIL arm is untouched: one committed pointer at a file that exists nowhere
and is not deliberately ignored still returns rc 1, baseline or not.

AND THEN THE CORPUS LEFT THE REPOSITORY ALTOGETHER (#1710's treatment)
======================================================================
v1.10.56 moved the published directories into their own repositories. `--subdir
benchmark-data` now names nothing at all here, so the surviving refusal fired:

    [NOT CHECKED] git tracks nothing at all under benchmark-data — either the
    path is wrong or the corpus is absent; not a pass                    rc 2

Correct again, for what it was asked, and again fatal: `run` maps rc 2 to FAIL.
`benchmark_evidence_structure_check` (#1710, v1.10.51) had the same shape and
the same repair, which is the one applied here — THE POINTER WINS OVER THE PATH,
the override is ANNOUNCED, and the three outcomes stay three:

    $VIBE_IC_BENCHMARK_DATA set + unreadable,
      or set at something git does not track  -> UNDETERMINED (rc 2), never
                                                 excused by any flag
    nothing set, nothing tracked locally, and
      the CALL SITE opted in                  -> NO_CORPUS (rc 0), stating that
                                                 NOTHING WAS SCANNED
    nothing set, nothing tracked, nobody
      opted in                                -> UNDETERMINED (rc 2), unchanged

A clone of the published corpus is its OWN git repository, and this gate reads
git's index rather than the filesystem — that is load-bearing here, since the
condition under test is whether a path materialises. So the pointer is resolved
to the clone's TOPLEVEL and the subdir to the corpus's path within it, and the
enumeration then runs exactly as it always did. A loose directory of files is
refused rather than scanned: it has no index to ask, and answering from a walk
would make the verdict depend on what the walk could follow.

WHAT THIS MUST NOT BUY. #1700 recorded 31 dangling `steps/` pointers in that
corpus. Pointing $VIBE_IC_BENCHMARK_DATA at a clone must still find them and
still return rc 1 — the flag exists for the case where there is nothing to look
at, and it must never reach the case where there is.

AND THE SAME DISTINCTION, ONE LEVEL UP, ON THE REGISTER (vibe-ic#1705)
=====================================================================
The refusal below already read "a missing register is not an empty one" — and
applied it only to a file that exists and will not parse. A path with NO file
at it skipped the branch and left `recorded` at `[]`, the value that means
MEASURED AND EMPTY. Since the verdict is `hard - recorded`, that turned every
inherited pointer into a NEW one. Absent, unreadable, truncated, or carrying no
list of strings at `known` are now all NOT CHECKED (rc 2, path named); only
`--write-baseline` at a path with nothing at it may bootstrap one, and it may
never overwrite an unreadable file as though its old value had been empty.

An explicitly empty `{"known": []}` register stays a measurement — of a corpus
with no broken pointer in it — and the FIRST broken pointer against it is still
NEW and still exits 1.

Exit: 0 nothing new (or NO_CORPUS, which says so), 1 a new broken pointer or a
recorded one that no longer appears, 2 nothing was examined — including a
register that states no readable measurement.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

RC_OK, RC_FINDING, RC_NOTHING = 0, 1, 2

DIR = Path(__file__).resolve().parent
DEFAULT_BASELINE = DIR / "tracked_symlink_target_baseline.json"

#: Where a caller may point us at a clone of the published corpus. Spelled the
#: same way `benchmark_evidence_structure_check`, `tracked_symlink_portability_
#: check` and `programs/tests/_published_corpus` spell it: one name for one
#: thing, so two gates cannot disagree about whether a corpus was checked.
CORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"


def _repo_root(start: Path) -> Path:
    r = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True, timeout=60)
    return Path(r.stdout.strip()) if r.returncode == 0 else start


def _git_toplevel(start: Path):
    """The repository containing ``start``, or None if it is not a checkout.

    Distinct from `_repo_root`, which falls back to `start` itself. A fallback
    is the wrong answer for a corpus pointer: "this is not a git checkout" has
    to be sayable, because everything below asks git's INDEX and a loose
    directory has none to ask.
    """
    r = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True, timeout=60)
    out = r.stdout.strip()
    return Path(out) if r.returncode == 0 and out else None


def tracked_symlinks(root: Path, subdir: str) -> Tuple[List[str], str]:
    """Every tracked symlink under ``subdir``, from git's index.

    Mode 120000 is git's own record that a path is a symlink, so this does not
    depend on the filesystem having materialised it — which is the very
    condition under test.
    """
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", subdir],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        return [], f"git ls-files failed: {r.stderr.strip()[:160]}"
    out = []
    for line in r.stdout.splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) == 4 and parts[0] == "120000":
            out.append(parts[3].strip())
    return out, ""


def tracked_path_count(root: Path, subdir: str) -> Tuple[int, str]:
    """How many paths git tracks under ``subdir`` — symlink or not.

    This is the denominator that tells "the corpus is not here" apart from "the
    corpus is here and holds no pointers". Asked of the INDEX for the same
    reason as above: it must not depend on what this checkout materialised.
    """
    r = subprocess.run(["git", "-C", str(root), "ls-files", "--", subdir],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        return 0, f"git ls-files failed: {r.stderr.strip()[:160]}"
    return len([ln for ln in r.stdout.splitlines() if ln.strip()]), ""


def broken(root: Path, rels: List[str]) -> List[dict]:
    """Symlinks whose target does not resolve, and whose target is untracked.

    BOTH conditions, and the second is what keeps this honest. A pointer at a
    tracked file that this checkout has not materialised is a partial checkout,
    not a corpus defect — reporting it would make the gate fail on a machine
    rather than on a commit, which is the thing #555 is about.
    """
    tracked = set()
    r = subprocess.run(["git", "-C", str(root), "ls-files"],
                       capture_output=True, text=True, timeout=180)
    if r.returncode == 0:
        tracked = set(r.stdout.splitlines())

    found = []
    for rel in rels:
        p = root / rel
        try:
            target = os.readlink(p)
        except OSError:
            # git says symlink, the path is not one here: a partial checkout.
            continue
        resolved = os.path.normpath(os.path.join(os.path.dirname(rel), target))
        if resolved in tracked:
            continue                     # target IS committed; nothing to see
        # A TARGET THE REPOSITORY DELIBERATELY DOES NOT TRACK IS NOT A DEFECT,
        # and treating it as one nearly cost something real. `.gitignore:138`
        # excludes `benchmark-data/ic/*/clean_run_*/` with its reason written
        # beside it: a raw run directory can carry a commercial-PDK identifier
        # IN ITS NAME, and tracking it is one `git add -A` away from re-leaking
        # what the 2026-07-19/20 history rewrite removed.
        #
        # Measured: 31 of the 44 pointers this check flags resolve into that
        # ignored tree. My first reading called all 28 "broken everywhere" and
        # my recommendation to the owner was to delete the pointers — which
        # would have deleted the index into a deliberately-untracked corpus.
        # Asking git whether the target is IGNORED separates a decision from a
        # defect, and only the second is debt.
        if _is_ignored(root, resolved):
            found.append({"link": rel, "target": target, "resolved": resolved,
                          "kind": "TARGET_DELIBERATELY_UNTRACKED"})
            continue
        if (root / resolved).exists():
            # Resolves here but is untracked — present only because this
            # machine ran the flow. Real, and it is the host-dependence half;
            # reported without failing, since the file does exist.
            found.append({"link": rel, "target": target, "resolved": resolved,
                          "kind": "UNTRACKED_TARGET_PRESENT_LOCALLY"})
            continue
        found.append({"link": rel, "target": target, "resolved": resolved,
                      "kind": "BROKEN_EVERYWHERE"})
    return found


def _is_ignored(root: Path, rel: str) -> bool:
    """Does `.gitignore` deliberately exclude this path?

    One `git check-ignore` per path is a subprocess per pointer, which is fine
    at this population (172) and is the only answer that respects negations,
    nested ignore files and precedence. Reimplementing the matching would be a
    second copy of git's rules, and those two would disagree.
    """
    return subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", "--", rel],
        capture_output=True, timeout=60).returncode == 0


def _load_register(path: Path) -> Optional[List[str]]:
    """The recorded pointers, or ``None`` when NO register could be read.

    ``None`` and ``[]`` are different values and must never be collapsed
    (vibe-ic#1705): ``[]`` asserts that this tree was measured and carries no
    known-broken pointer, which is what makes the FIRST one NEW; ``None``
    asserts nothing at all. Every way of failing to read one lands on ``None``
    — no file, a directory, unreadable or truncated bytes, a document that is
    not an object, a ``known`` that is absent or is not a list of strings.
    """
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    known = doc.get("known")
    if not isinstance(known, list) or any(not isinstance(k, str)
                                          for k in known):
        return None
    return known


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--subdir", default="benchmark-data")
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    ap.add_argument("--json", default=None)
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="the caller asserts this repo need not carry the "
                         "published corpus. Turns 'git tracks nothing under the "
                         "subdir and no pointer was given' from UNDETERMINED "
                         "into NO_CORPUS (rc 0), which STATES that nothing was "
                         f"scanned. It does NOT excuse a ${CORPUS_ENV} that is "
                         "set and does not resolve to a git checkout carrying a "
                         "corpus — that stays UNDETERMINED.")
    a = ap.parse_args(argv)

    # THE POINTER WINS OVER THE PATH, ANNOUNCED (#1710). A clone of the published
    # corpus is its own repository, so the pointer resolves to that repository's
    # TOPLEVEL and the subdir to the corpus's path inside it; the enumeration
    # below is then unchanged and still reads git's index, never a walk.
    env_tree = os.environ.get(CORPUS_ENV)
    subdir = a.subdir
    if env_tree:
        print(f"note: {CORPUS_ENV} overrides --subdir {a.subdir} -> {env_tree}",
              file=sys.stderr)
        corpus = Path(env_tree)
        if not corpus.is_dir():
            print(f"UNDETERMINED: {CORPUS_ENV}={env_tree} is set and is not a "
                  f"readable directory, so nothing was enumerated and nothing "
                  f"examined. A pointer that is set and wrong is a broken "
                  f"configuration, not an absent corpus, and "
                  f"--corpus-may-be-absent does not excuse it.", file=sys.stderr)
            return RC_NOTHING
        top = _git_toplevel(corpus)
        if top is None:
            print(f"UNDETERMINED: the corpus at {env_tree} is not a git "
                  f"checkout. This gate judges what git TRACKS, never what a "
                  f"directory happens to hold — that is the whole point of "
                  f"#555 — so it cannot be aimed at a loose directory of "
                  f"files. Point {CORPUS_ENV} at a clone.", file=sys.stderr)
            return RC_NOTHING
        try:
            rel = corpus.resolve().relative_to(top.resolve())
        except ValueError:      # pragma: no cover — git cannot report this
            print(f"UNDETERMINED: {env_tree} is not inside the repository git "
                  f"reports for it ({top}); refusing to guess a subdir.",
                  file=sys.stderr)
            return RC_NOTHING
        root = top
        subdir = rel.as_posix() or "."
        print(f"note: enumerating git-tracked paths in {root} under {subdir}",
              file=sys.stderr)
    else:
        root = _repo_root(Path(a.root or Path.cwd()))

    # THE REGISTER IS READ BEFORE THE POPULATION, so one that states no
    # measurement refuses whatever the corpus turns out to be. A NO_CORPUS run
    # leaves a readable register unevaluated and has to say so; that count is
    # how a reader sees it.
    bl_path = Path(a.baseline)
    # AND AN ABSENT REGISTER IS A MISSING ONE (vibe-ic#1705). The refusal this
    # replaces already said "a missing register is not an empty one" — and then
    # applied it only to a file that exists and will not parse. A path with no file at
    # it skipped the branch entirely and left `recorded` at `[]`, which is the
    # value that says MEASURED, AND NOTHING IS RECORDED. `new` is
    # `hard - recorded`, so against that value every inherited pointer is a
    # regression. Measured on a synthetic corpus carrying one recorded broken
    # pointer: rc 0 with the register, rc 1 and "1 NEW committed pointer(s)"
    # with the same tree and the register moved aside.
    #
    # This repo's corpus lives elsewhere since v1.10.56, so the run reaches
    # NO_CORPUS before the verdict and the fabrication was not observable here
    # — which is why #1705 could only record this site as inconclusive. It is
    # latent, not absent.
    recorded = _load_register(bl_path)
    if recorded is None:
        # `--write-baseline` is the operation that CREATES the register, so it
        # may bootstrap a path with nothing at it. It must not overwrite an
        # existing unreadable or truncated file as though the measurement it
        # replaces had been empty.
        bootstrapping = (a.write_baseline and not bl_path.exists()
                         and not bl_path.is_symlink())
        if not bootstrapping:
            print(f"[NOT CHECKED] no register states a readable measurement at "
                  f"{bl_path} — absent, unreadable or truncated is not an empty "
                  f"one, so no pointer found here can be called NEW. Record it "
                  f"with --write-baseline before asking this gate to attribute "
                  f"anything. See vibe-ic#1705.", file=sys.stderr)
            return RC_NOTHING
        recorded = []

    rels, err = tracked_symlinks(root, subdir)
    if err:
        print(f"[NOT CHECKED] {err} — nothing was examined, which is not a "
              f"clean result", file=sys.stderr)
        return RC_NOTHING
    # No symlink is either "nothing to check" or "nothing was checkable", and
    # the denominator is what separates them (#1700).
    population, perr = tracked_path_count(root, subdir)
    if perr:
        print(f"[NOT CHECKED] {perr} — nothing was examined, which is not a "
              f"clean result", file=sys.stderr)
        return RC_NOTHING
    if not rels and population == 0:
        # `not env_tree` is the load-bearing half. A pointer that was SET and
        # led to a tree git tracks nothing under is somebody's broken
        # configuration, and the opt-in must not reach it.
        if a.corpus_may_be_absent and not env_tree:
            print(f"NO_CORPUS: git tracks nothing under {subdir} in {root} and "
                  f"{CORPUS_ENV} is unset. The published corpus lives in its own "
                  f"repository and this repo is not required to carry it. "
                  f"NOTHING WAS SCANNED — 0 tracked paths, 0 tracked symlinks, "
                  f"0 pointers adjudicated, and the {len(recorded)}-entry "
                  f"register was NOT evaluated. Point {CORPUS_ENV} at a clone to "
                  f"make this gate check something.", file=sys.stderr)
            return RC_OK
        print(f"[NOT CHECKED] git tracks nothing at all under {subdir} — "
              f"either the path is wrong or the corpus is absent; not a pass",
              file=sys.stderr)
        return RC_NOTHING

    found = broken(root, rels)
    hard = sorted(f["link"] for f in found if f["kind"] == "BROKEN_EVERYWHERE")
    local = sorted(f["link"] for f in found
                   if f["kind"] == "UNTRACKED_TARGET_PRESENT_LOCALLY")
    ignored = sorted(f["link"] for f in found
                     if f["kind"] == "TARGET_DELIBERATELY_UNTRACKED")

    new = sorted(set(hard) - set(recorded))
    healed = sorted(set(recorded) - set(hard))

    # The denominator is printed with the numerator, always. "0 broken" over an
    # unstated population is the shape #1700 is about.
    print(f"tracked_symlink_target_present: {len(rels)} tracked symlink(s) "
          f"among {population} tracked path(s) under {subdir}; "
          f"{len(hard)} point at a file that exists nowhere, "
          f"{len(local)} at an untracked file this machine happens to have, "
          f"{len(ignored)} into a tree .gitignore deliberately excludes")
    for f in found:
        if f["kind"] == "BROKEN_EVERYWHERE":
            print(f"  BROKEN   {f['link']} -> {f['target']}")
    for f in found:
        if f["kind"] == "UNTRACKED_TARGET_PRESENT_LOCALLY":
            print(f"  LOCAL    {f['link']} -> {f['target']}  "
                  f"(resolves here only; this is the host-dependence in #555)")

    if a.write_baseline:
        bl_path.write_text(json.dumps(
            {"_comment": "Tracked symlinks under the corpus whose target exists "
                         "nowhere. MAY ONLY SHRINK: a new one FAILS, and one "
                         "that starts resolving also FAILS so the register "
                         "cannot become standing permission. Repairing these is "
                         "the benchmark-agent's commit under NO-MIX, never this "
                         "plugin's (vibe-ic#555).",
             "known": hard}, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {bl_path} ({len(hard)} entr(ies))", file=sys.stderr)
        return RC_OK

    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(
            {"program": "tracked_symlink_target_present_check",
             "tracked_symlinks": len(rels), "tracked_paths": population,
             "broken_everywhere": hard,
             "untracked_target_present_locally": local,
             "target_deliberately_untracked": ignored,
             "new": new, "healed": healed}, indent=2) + "\n", encoding="utf-8")

    if new:
        print(f"[FAIL] {len(new)} NEW committed pointer(s) at a file that "
              f"exists nowhere. The corpus states a step produced an artefact "
              f"and points at nothing:\n  " + "\n  ".join(new), file=sys.stderr)
        return RC_FINDING
    if healed:
        # "no longer broken" rather than "now resolve": since #1700 a recorded
        # entry can also leave the register by having its POINTER deleted, and
        # a message that names only the other cause sends the reader looking
        # for a target that was never restored.
        print(f"[FAIL] {len(healed)} recorded entr(ies) are no longer a broken "
              f"pointer — the target resolves, or the pointer itself was "
              f"removed. The register MAY ONLY SHRINK — drop them from it in "
              f"the same commit that fixed them, or it becomes standing "
              f"permission:\n  " + "\n  ".join(healed), file=sys.stderr)
        return RC_FINDING
    print(f"[PASS] no NEW broken pointer over {population} tracked path(s) "
          f"under {subdir} carrying {len(rels)} symlink(s) "
          f"({len(recorded)} recorded as debt, repairable only by the "
          f"benchmark-agent under NO-MIX). "
          f"{len(local)} pointer(s) resolve only on this machine — that is the "
          f"host-dependence #555 reported, and it is disclosed rather than "
          f"failed on because the file does exist.", file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
