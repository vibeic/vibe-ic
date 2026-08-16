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

Exit: 0 nothing new, 1 a new broken pointer or a recorded one that no longer
appears, 2 nothing was examined.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

RC_OK, RC_FINDING, RC_NOTHING = 0, 1, 2

DIR = Path(__file__).resolve().parent
DEFAULT_BASELINE = DIR / "tracked_symlink_target_baseline.json"


def _repo_root(start: Path) -> Path:
    r = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True, timeout=60)
    return Path(r.stdout.strip()) if r.returncode == 0 else start


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--subdir", default="benchmark-data")
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    ap.add_argument("--json", default=None)
    ap.add_argument("--write-baseline", action="store_true")
    a = ap.parse_args(argv)

    root = _repo_root(Path(a.root or Path.cwd()))
    rels, err = tracked_symlinks(root, a.subdir)
    if err:
        print(f"[NOT CHECKED] {err} — nothing was examined, which is not a "
              f"clean result", file=sys.stderr)
        return RC_NOTHING
    # No symlink is either "nothing to check" or "nothing was checkable", and
    # the denominator is what separates them (#1700).
    population, perr = tracked_path_count(root, a.subdir)
    if perr:
        print(f"[NOT CHECKED] {perr} — nothing was examined, which is not a "
              f"clean result", file=sys.stderr)
        return RC_NOTHING
    if not rels and population == 0:
        print(f"[NOT CHECKED] git tracks nothing at all under {a.subdir} — "
              f"either the path is wrong or the corpus is absent; not a pass",
              file=sys.stderr)
        return RC_NOTHING

    found = broken(root, rels)
    hard = sorted(f["link"] for f in found if f["kind"] == "BROKEN_EVERYWHERE")
    local = sorted(f["link"] for f in found
                   if f["kind"] == "UNTRACKED_TARGET_PRESENT_LOCALLY")
    ignored = sorted(f["link"] for f in found
                     if f["kind"] == "TARGET_DELIBERATELY_UNTRACKED")

    bl_path = Path(a.baseline)
    recorded = []
    if bl_path.is_file():
        try:
            recorded = json.loads(bl_path.read_text()).get("known") or []
        except (OSError, ValueError):
            print(f"[NOT CHECKED] {bl_path} is unreadable — a missing register "
                  f"is not an empty one", file=sys.stderr)
            return RC_NOTHING

    new = sorted(set(hard) - set(recorded))
    healed = sorted(set(recorded) - set(hard))

    # The denominator is printed with the numerator, always. "0 broken" over an
    # unstated population is the shape #1700 is about.
    print(f"tracked_symlink_target_present: {len(rels)} tracked symlink(s) "
          f"among {population} tracked path(s) under {a.subdir}; "
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
          f"under {a.subdir} carrying {len(rels)} symlink(s) "
          f"({len(recorded)} recorded as debt, repairable only by the "
          f"benchmark-agent under NO-MIX). "
          f"{len(local)} pointer(s) resolve only on this machine — that is the "
          f"host-dependence #555 reported, and it is disclosed rather than "
          f"failed on because the file does exist.", file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
