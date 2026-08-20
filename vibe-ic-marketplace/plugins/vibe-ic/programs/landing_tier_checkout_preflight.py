#!/usr/bin/env python3
"""landing_tier_checkout_preflight.py — the full tier runs in a SELF-CONTAINED
checkout, or it does not start.

WHY THIS EXISTS
===============
The full tier is an hour of gate wall-clock. Every minute of it depends on the
checkout it runs in still being a repository when it finishes.

A LINKED WORKTREE IS NOT THAT. Its `.git` is a control FILE naming
`<shared repo>/.git/worktrees/<name>`, and that registration is owned by a
repository this run does not control. `git worktree prune` — run by any other
process against the shared repo, on a host where several agents share one clone —
removes it. From that instant every `git` call inside the tree fails, and gates
that were measuring the COMMIT start reporting the accident instead.

MEASURED: a tier run whose worktree registration was pruned mid-run lost four
gates to pure collateral. Nothing in those four verdicts was about the tree under
test, and the run's third measurement was lost to something outside the
measurement.

The landing arms already knew this and already avoid it:
`tools/ci/hermetic_git_subject.py:4-9` — "Ordinary linked worktrees contain a
`.git` control file whose target is a host-only path" — so they materialize a
STANDALONE repository (`git init`, object-closure copy, no remotes, no
alternates, `gc.auto=0`) and run the tier in that. What was missing is the
refusal for every OTHER way a tier gets started: by hand, by a poller, by an
agent that happened to `cd` into a worktree.

WHAT IS REFUSED, AND WHY EACH ONE
=================================
    a LINKED WORKTREE        its registration is external and prunable, so the
                             repository can be removed from under a running
                             measurement.
    OBJECT ALTERNATES        `.git/objects/info/alternates` (a `git clone
                             --shared/--reference` tree). The objects live in
                             another repository; a `git gc` there can delete
                             them mid-run. Same class, same outcome, and
                             `hermetic_git_subject.py:252-254` already refuses
                             it for the landing arms.

A plain clone — including a local hardlink clone, whose objects are hardlinks to
IMMUTABLE files and therefore survive anything the source does — is accepted.
That is the cheap remedy this refusal names.

THERE IS NO ENVIRONMENT ESCAPE HATCH. A flag that lets a tier start in a
worktree is a flag that gets exported once and then forgotten, and "impossible
by accident" is the property being bought. A caller that genuinely needs a
throwaway tree should build a clone, which costs seconds on a local filesystem.

WHO CALLS THIS, AND WHY THAT ARRIVES IN TWO PIECES
==================================================
`gatekeeper_status_poller.prepare_gate_checkout()` calls it on the checkout it
just built, so the automated tier proves its own tree instead of assuming the
clone did the right thing. That is the path the measured four-gate loss happened
on, and it is guarded here.

The BY-HAND path — `tools/gatekeeper-land.sh` refusing before the full tier's
first arm — is a change to a PROTECTED runtime path, and
`protected_landing_transition.py` requires such a change to arrive as PREPARE
(manifest only) then ACTIVATE (bytes only); "per-file mixtures refuse". So that
call lands separately, and until it does this program's by-hand coverage is the
remedy text somebody has to run, not a refusal that fires on its own.

EXIT CODES
==========
    0   the checkout is self-contained; the tier may start
    2   REFUSED — the cause and the remedy are printed; nothing was measured

rc 1 is deliberately never returned: this is not a finding against the tree.

chip-AGNOSTIC: pure git/path plumbing. No design, PDK, vendor or SKU literal.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence


NAME = "landing_tier_checkout_preflight"


def _git(root: Path, args: Sequence[str]) -> Optional[str]:
    """One line of git output, or None when git could not answer."""
    try:
        proc = subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _remedy(root: Path) -> str:
    return (f"Remedy: run the tier in a CLONE, not in this tree — "
            f"`git clone {root} <somewhere>` (a local clone hardlinks its "
            f"objects, so it costs seconds and cannot be pruned or "
            f"garbage-collected from outside), then run the tier there.")


def refusal(root: Path) -> Optional[str]:
    """The sentence naming why `root` may not host a tier run, or None."""
    git_dir = _git(root, ["rev-parse", "--absolute-git-dir"])
    common = _git(root, ["rev-parse", "--path-format=absolute",
                         "--git-common-dir"])
    if common is None:
        # `--path-format` needs git >= 2.31. Fall back to the relative answer
        # resolved against the checkout, which is what git documents it to be.
        rel = _git(root, ["rev-parse", "--git-common-dir"])
        common = str((root / rel).resolve()) if rel else None
    if git_dir is None or common is None:
        return (f"REFUSED — {root} is not a git checkout this tool can "
                f"interrogate, so it cannot be shown to be self-contained. A "
                f"tier that cannot establish what it is running in has not "
                f"established anything. NOTHING WAS MEASURED.")

    if Path(git_dir).resolve() != Path(common).resolve():
        return (f"REFUSED — {root} is a LINKED WORKTREE: its git directory is "
                f"{git_dir}, registered inside the shared repository at "
                f"{common}. That registration is owned by a repository this run "
                f"does not control, and `git worktree prune` in it removes the "
                f"tree from under a running tier — after which every gate "
                f"reports the accident instead of the commit. MEASURED: four "
                f"gates lost to pure collateral in one such run. NOTHING WAS "
                f"MEASURED. " + _remedy(root))

    alternates = Path(common) / "objects" / "info" / "alternates"
    if alternates.exists():
        return (f"REFUSED — {root} borrows its objects from another repository "
                f"({alternates} exists), so a `git gc` there can delete them "
                f"mid-tier. The landing arms already refuse this shape "
                f"(hermetic_git_subject.py). NOTHING WAS MEASURED. "
                f"Remedy: re-clone WITHOUT --shared/--reference "
                f"(`git clone {root} <somewhere>`), or run "
                f"`git repack -a -d` in this clone to absorb the borrowed "
                f"objects, then run the tier there.")
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path.cwd(),
                    help="the checkout the tier would run in (default: cwd)")
    args = ap.parse_args(argv)
    root = args.root
    if not root.is_dir():
        print(f"[{NAME}] REFUSED — {root} is not a directory.", file=sys.stderr)
        return 2
    why = refusal(root)
    if why is not None:
        print(f"[{NAME}] {why}", file=sys.stderr)
        return 2
    print(f"[{NAME}] PASS: {root} is a self-contained checkout — its git "
          f"directory is its own and it borrows no objects, so nothing outside "
          f"this tier can remove the repository while it runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
