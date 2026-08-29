#!/usr/bin/env python3
"""attestation_preflight_check.py — refuse a dirty tree BEFORE the hour, not
after it.

THIS GATE BLOCKS (rc=1). It is a PREFLIGHT: it costs milliseconds and is meant
to run immediately before any attestation, mutation-verification or
host-independence gate, all of which re-derive a tree in an isolated copy built
from HEAD.

THE DEFECT, MEASURED IN THREE GATES ON ONE DAY (2026-08-21)
===========================================================
A gate that snapshots a tree, re-derives it somewhere else, and compares the two
is defeated by anything present in the CHECKOUT and absent from the COMMIT.

    one gate returned UNDETERMINED on uncommitted tracked edits
    one flipped between red and green run to run with untracked files present
    one differential suite failed 13 of 39 with a refusal naming ONE stray
      bytecode artefact in the snapshot path set

After cleaning the tree and disabling bytecode writing, that same suite passed
33 with ZERO failures.

Every one of those refusals was CORRECT, and each named its real reason in its
own output. The defect was not the gates. It was the tree they were pointed at,
and the cost was paid at the END of an hour-long run instead of at the start.

WHY BYTECODE IS THE SHARPEST CASE, AND WHY `git status` CANNOT SEE IT
=====================================================================
``__pycache__`` is covered by ``.gitignore``, so ``git status --porcelain``
reports nothing about it. But ``_run_isolation.snapshot`` — which
``matrix_mutation_ledger`` takes on both sides of every replay — walks the
FILESYSTEM (``root.rglob("*")``) and records every regular file. A single
``.pyc`` written by the replay's own import is therefore invisible to the
cleanliness instrument and fully visible to the drift instrument. That asymmetry
is the 13-of-39 failure, and it is why this program walks the filesystem instead
of asking git.

BYTECODE WRITING IS CHECKED IN THE ENVIRONMENT, NOT IN THIS INTERPRETER
=======================================================================
``sys.dont_write_bytecode`` is what ``python3 -B`` sets, and ``-B`` DOES NOT
PROPAGATE to a child process. The gates this preflight protects all spawn
children — that is how they re-derive anything — so the property that matters is
``PYTHONDONTWRITEBYTECODE`` being present in the ENVIRONMENT, which children
inherit. A run under ``-B`` alone is reported as insufficient and named as such,
rather than being credited for a flag its children will not see.

WHAT IS AND IS NOT REFUSED, STATED BECAUSE AN UNSTATED BOUND READS AS A GUARANTEE
=================================================================================
REFUSED by default:
    bytecode writing enabled in the environment
    bytecode / cache residue under a declared root (``__pycache__``, ``*.pyc``,
      ``*.pyo``, ``.pytest_cache``)
    a TRACKED path under a declared root that differs from HEAD

NOT refused by default: untracked non-cache files. ``gate_host_independence_check``
uses exactly those as its STIMULUS — "the working checkout's leftovers ARE the
stimulus; the fresh worktree is the control" (#539) — so refusing them here by
default would break the one gate that needs them. ``--refuse-untracked`` is
available for a caller whose attestation genuinely requires the checkout to equal
the commit, and it is opt-in so it cannot silently disarm #539.

THE ROOTS ARE DECLARED, NEVER GUESSED
=====================================
At least one ROOT is required. The set of paths an attestation will re-derive is
a property of that attestation, and a preflight that invented "the repository"
would refuse over scratch clones and probe output that no measurement reads —
which is the shape that teaches an operator to route around a gate.

EXIT CODES
==========
    0  the declared roots are attestable: no residue, no tracked drift, and
       bytecode writing is off for every child the run will spawn
    1  REFUSED — the causes and the offending paths are printed; NOTHING
       expensive has run
    2  VACUOUS — the declared roots hold no file at all, so there was nothing
       to preflight (`_vacuous_exit`'s tier, announced)
    3  the command line was rejected (`_gate_usage_exit`)

USAGE
-----
    attestation_preflight_check.py ROOT [ROOT...] [--repo DIR]
                                   [--refuse-untracked] [--json OUT]

chip-AGNOSTIC: filesystem and git plumbing. No design, PDK, vendor or SKU.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import _atomic_artefact as _atomic
import _gate_usage_exit as _usage
import _vacuous_exit as _vac

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

TOOL = "attestation_preflight_check"

#: The environment variable a CHILD inherits. `python3 -B` sets
#: `sys.dont_write_bytecode` in THIS interpreter only and is not equivalent.
ENV_FLAG = "PYTHONDONTWRITEBYTECODE"

#: Directory names that are pure interpreter/runner residue.
RESIDUE_DIRS = ("__pycache__", ".pytest_cache", ".mypy_cache")
#: File suffixes of compiled bytecode.
RESIDUE_SUFFIXES = (".pyc", ".pyo")


def residue(root: Path) -> Tuple[List[str], int]:
    """``([paths], files_seen)`` — every bytecode/cache artefact under `root`.

    The walk prunes into residue directories rather than descending them: a
    ``__pycache__`` holding four hundred ``.pyc`` files is ONE thing to remove,
    and listing four hundred paths would bury the other findings.
    """
    hits: List[str] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        for name in list(dirnames):
            if name in RESIDUE_DIRS:
                hits.append(str(here / name))
                dirnames.remove(name)
        for name in filenames:
            seen += 1
            if name.endswith(RESIDUE_SUFFIXES):
                hits.append(str(here / name))
    return sorted(hits), seen


def tracked_drift(repo: Path, roots: List[Path]) -> Optional[List[str]]:
    """``["<XY> <path>"]`` for TRACKED modifications under `roots`, or None.

    None means git did not answer, which is not the same as clean and is
    reported as its own refusal rather than folded into a pass.
    """
    r = _pr.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--",
         *[str(p) for p in roots]],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return [line for line in r.stdout.splitlines()
            if line.strip() and not line.startswith("??")]


def untracked(repo: Path, roots: List[Path]) -> List[str]:
    r = _pr.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--",
         *[str(p) for p in roots]],
        capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return [line[3:] for line in r.stdout.splitlines()
            if line.startswith("??")]


def remedy_for(*, residues: List[str], drift: Optional[List[str]],
               untracked_paths: List[str], env_value: Optional[str],
               ) -> List[str]:
    """The remedy for the causes that FIRED, and for no other cause.

    THE DEFECT THIS REPLACES. The refusal used to end with one fixed sentence
    naming all three remedies at once — "Clean the residue, commit or stash the
    tracked edits, and export PYTHONDONTWRITEBYTECODE=1" — whatever had actually
    gone wrong. An operator who had ALREADY done all three, on a `git clean
    -xdfq` tree with `dirty=0` and the variable exported, was sent to do them
    again. Two of the three were about a tree that was already clean, and the
    third was about a variable that was already set, so the sentence carried no
    information about this checkout at all and cost an hour.

    THE RESIDUE-WITH-THE-FLAG-SET CASE IS ITS OWN DIAGNOSIS, not a repetition of
    the generic one. Bytecode under a declared root while `PYTHONDONTWRITEBYTECODE`
    IS set cannot be the operator's omission: a child ignored the environment.
    The known way for that to happen in this repo is `python3 -I`, which implies
    `-E` and therefore discards every `PYTHON*` variable. MEASURED in the pinned
    image with the variable exported::

        python3        -> sys.dont_write_bytecode True
        python3 -I     -> sys.dont_write_bytecode False
        python3 -I -B  -> sys.dont_write_bytecode True

    So that case names `-B` on the isolated child, which is where the fix is,
    instead of naming the export the operator has already done.
    """
    out: List[str] = []
    if residues:
        if env_value:
            out.append(
                f"residue exists even though {ENV_FLAG} IS set, so a CHILD "
                f"ignored the environment rather than the operator omitting it: "
                f"`python3 -I` implies `-E` and discards every PYTHON* variable, "
                f"so pass the `-B` FLAG to any isolated child that imports this "
                f"tree. Removing the listed paths without that fixes one run only")
        else:
            out.append("remove the residue paths listed above")
    if drift is None:
        out.append("make `git status` answerable for --repo; an unmeasurable "
                   "checkout is not a clean one")
    elif drift:
        out.append("commit or stash the tracked edits listed above")
    if untracked_paths:
        out.append("remove or commit the untracked paths listed above "
                   "(--refuse-untracked was requested)")
    if not env_value:
        out.append(f"export {ENV_FLAG}=1 so the children this run spawns "
                   f"inherit it")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = _usage.GateArgumentParser(
        prog=TOOL,
        description="refuse an attestation whose checkout would defeat it, "
                    "before it spends the time")
    ap.add_argument("roots", nargs="*", type=Path, metavar="ROOT",
                    help="the paths the attestation will snapshot or re-derive")
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--refuse-untracked", action="store_true",
                    help="also refuse untracked non-cache files; OFF by default "
                         "because gate_host_independence_check uses them as its "
                         "stimulus (#539)")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    if not args.roots:
        return _usage.usage_error(
            TOOL, "no ROOT given; the set of paths an attestation re-derives is "
                  "a property of that attestation and is never guessed here")
    top = _pr.run(["git", "-C", str(args.repo), "rev-parse",
                   "--show-toplevel"],
                  capture_output=True, text=True)
    if top.returncode != 0 or not top.stdout.strip():
        return _usage.usage_error(
            TOOL, f"--repo {args.repo} is not a git repository, so the tracked "
                  f"half of the preflight could not be put at all")
    toplevel = Path(top.stdout.strip()).resolve()
    for p in args.roots:
        if not p.exists():
            return _usage.usage_error(TOOL, f"ROOT {p} does not exist")
        # A root git cannot speak for makes the tracked-drift half unanswerable,
        # and an unanswerable half must not arrive dressed as a finding about
        # the tree. It is a defect in the CALL, so it is rc 3.
        try:
            p.resolve().relative_to(toplevel)
        except ValueError:
            return _usage.usage_error(
                TOOL, f"ROOT {p} is outside --repo {toplevel}; a root this "
                      f"repository does not contain cannot be preflighted "
                      f"against its HEAD")

    problems: List[str] = []
    detail: List[str] = []

    env_value = os.environ.get(ENV_FLAG)
    if not env_value:
        note = (" (this interpreter was started with -B, which sets "
                "sys.dont_write_bytecode for ITSELF and is not inherited by "
                "the children the attestation spawns)"
                if sys.dont_write_bytecode else "")
        problems.append(
            f"{ENV_FLAG} is not set in the environment, so every child this "
            f"run spawns will write .pyc files INTO the snapshot path set and "
            f"the run will measure its own residue{note}")

    residues: List[str] = []
    files_seen = 0
    for root in args.roots:
        hits, seen = residue(root)
        residues.extend(hits)
        files_seen += seen
    if residues:
        problems.append(
            f"{len(residues)} bytecode/cache artefact(s) already sit under the "
            f"declared roots; `git status` cannot see them (.gitignore) and the "
            f"drift instrument can, which is the 13-of-39 shape")
        detail.extend(f"    residue: {p}" for p in residues[:8])

    drift = tracked_drift(args.repo, args.roots)
    if drift is None:
        problems.append(
            f"`git status` did not answer for {args.repo}, so tracked drift "
            f"could not be established; an unmeasurable checkout is not a "
            f"clean one")
    elif drift:
        problems.append(
            f"{len(drift)} TRACKED path(s) under the declared roots differ from "
            f"HEAD; the isolated copy is built from HEAD, so each one reads as "
            f"a difference that is about the edit and not about the subject")
        detail.extend(f"    tracked:  {line}" for line in drift[:8])

    extra_untracked: List[str] = []
    if args.refuse_untracked:
        extra_untracked = [p for p in untracked(args.repo, args.roots)]
        if extra_untracked:
            problems.append(
                f"{len(extra_untracked)} untracked path(s) under the declared "
                f"roots are present in the checkout and absent from HEAD")
            detail.extend(f"    untracked:{p}" for p in extra_untracked[:8])

    report = {
        "tool": TOOL,
        "roots": [str(p) for p in args.roots],
        "files_seen": files_seen,
        "env_flag_set": bool(env_value),
        "residue": residues,
        "tracked_drift": drift or [],
        "untracked": extra_untracked,
        "problems": problems,
    }
    if args.json:
        _atomic.write_json(args.json, report)

    head = (f"{files_seen} file(s) under {len(args.roots)} declared root(s)")

    if files_seen == 0 and not problems:
        _vac.announce_vacuous(TOOL, "roots-hold-no-file")
        print(f"[VACUOUS] {TOOL}: the declared roots hold no file, so there was "
              f"nothing to preflight; this is NOT a pass")
        return _vac.RC_VACUOUS

    if problems:
        for p in problems:
            print(f"  [PREFLIGHT] {p}")
        for d in detail:
            print(d)
        for line in remedy_for(residues=residues, drift=drift,
                               untracked_paths=extra_untracked,
                               env_value=env_value):
            print(f"  [REMEDY] {line}")
        print(f"[FAIL] {TOOL}: this checkout would make the attestation measure "
              f"itself [{head}]. Nothing expensive has run. The REMEDY line(s) "
              f"above name what actually fired; nothing else needs doing.")
        return _vac.RC_FAIL

    print(f"[PASS] {TOOL}: attestable — no residue, no tracked drift, "
          f"{ENV_FLAG} set for every child [{head}]")
    return _vac.RC_PASS


if __name__ == "__main__":
    # A stall is not a verdict about the commit: reach the stamp as rc 2
    # (this gate's 'could not measure'), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
