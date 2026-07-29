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

Exit: 0 nothing new, 1 a new broken pointer or a recorded one that healed,
2 nothing was examined.
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
    if not rels:
        print(f"[NOT CHECKED] no tracked symlink under {a.subdir} — either the "
              f"path is wrong or the corpus is absent; not a pass",
              file=sys.stderr)
        return RC_NOTHING

    found = broken(root, rels)
    hard = sorted(f["link"] for f in found if f["kind"] == "BROKEN_EVERYWHERE")
    local = sorted(f["link"] for f in found
                   if f["kind"] == "UNTRACKED_TARGET_PRESENT_LOCALLY")

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

    print(f"tracked_symlink_target_present: {len(rels)} tracked symlink(s) "
          f"under {a.subdir}; {len(hard)} point at a file that exists nowhere, "
          f"{len(local)} at an untracked file this machine happens to have")
    for f in found:
        if f["kind"] == "BROKEN_EVERYWHERE":
            print(f"  BROKEN   {f['link']} -> {f['target']}")
    for f in found:
        if f["kind"] != "BROKEN_EVERYWHERE":
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
             "tracked_symlinks": len(rels), "broken_everywhere": hard,
             "untracked_target_present_locally": local,
             "new": new, "healed": healed}, indent=2) + "\n", encoding="utf-8")

    if new:
        print(f"[FAIL] {len(new)} NEW committed pointer(s) at a file that "
              f"exists nowhere. The corpus states a step produced an artefact "
              f"and points at nothing:\n  " + "\n  ".join(new), file=sys.stderr)
        return RC_FINDING
    if healed:
        print(f"[FAIL] {len(healed)} recorded entr(ies) now resolve. The "
              f"register MAY ONLY SHRINK — drop them from it in the same "
              f"commit that fixed them, or it becomes standing permission:\n  "
              + "\n  ".join(healed), file=sys.stderr)
        return RC_FINDING
    print(f"[PASS] no NEW broken pointer ({len(recorded)} recorded as debt, "
          f"repairable only by the benchmark-agent under NO-MIX). "
          f"{len(local)} pointer(s) resolve only on this machine — that is the "
          f"host-dependence #555 reported, and it is disclosed rather than "
          f"failed on because the file does exist.", file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
