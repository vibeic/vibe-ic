#!/usr/bin/env python3
"""_published_tree.py — "is this artefact PUBLISHED?", answered once.

WHY THIS MODULE EXISTS
======================
Three independent programs asked the same question on the same day and three
independent programs got it wrong the same way: they asked THIS MACHINE'S DISK
whether an artefact is there, when the question was whether the PUBLISHED TREE
carries it. Published means git-TRACKED. A working checkout also holds whatever
the last local run left behind; a fresh clone, and a `git worktree`, hold only
what is tracked.

The consequence is not a cosmetic difference — it is a gate that gives DIFFERENT
VERDICTS ON DIFFERENT HOSTS for byte-identical code:

  provenance_output_hash_completeness_check (v1.6.88)
      37 declared outputs were present-but-untracked, turning three cells'
      honest "not shipped" disclosures into "the disclosure is false".
      PASS in a worktree, FAIL in a working checkout.

  cross_layer_reference_check (v1.6.90)
      corpus of 46 L1 documents on disk vs 23 tracked. Its regression BASELINE
      records counts, so a baseline recorded in a worktree read 3 and the same
      corpus read 4 in a checkout — CI failing for no change to the code.

  l4_systemrdl_export (this landing)
      299 L4 documents on disk vs 201 tracked. Its docstring already recorded
      "0 of 201" from an earlier bug, which is how we know 201 was a worktree
      count. audit-corpus PASSes in a worktree and FAILs in a checkout.

Whoever runs the flow locally fails; whoever does not, passes. That inverts the
signal: the more you exercise the tool, the more its gates lie to you.

THE DISCRIMINATOR
=================
Not every tree is a published one. A raw run directory handed over on its own,
or a run that happens to sit inside a repository uncommitted, has published
NOTHING — there tracked-ness is not a question that applies and presence on
disk is the honest answer. Callers say which they are:

    published_paths(root)                       -> tracked set, or None
    published_paths(root, require="x.jsonl")    -> None unless x.jsonl is tracked

`None` means "not a published tree — use the disk". It never means "published
and empty", and callers must keep those apart: collapsing them turns "I could
not look" into "I looked and there is nothing", which is the false-certificate
shape this repo keeps finding.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import FrozenSet, Iterable, List, Optional


def published_paths(root: Path,
                    require: Optional[str] = None,
                    timeout: int = 180) -> Optional[FrozenSet[str]]:
    """Paths git tracks under `root`, RELATIVE to it.

    Returns None when `root` is not a published tree: not in a git work tree,
    git unavailable, nothing tracked under it, or — when `require` is given —
    that path is not itself tracked. `require` is how a caller says "this is a
    published DELIVERABLE", keyed on the artefact that makes it one (its
    ledger, its manifest), rather than on the accident of some file under it
    happening to be committed.
    """
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    paths = frozenset(p for p in r.stdout.split("\0") if p)
    if not paths:
        return None
    if require is not None and require not in paths:
        return None
    return paths


def is_published(root: Path, rel: str,
                 published: Optional[FrozenSet[str]] = None,
                 require: Optional[str] = None) -> bool:
    """Does this deliverable SHIP `rel`?

    Falls back to the disk when `root` is not a published tree. Pass a
    `published` set computed once if you are asking about many paths — the git
    call is not free and the answer cannot change mid-audit.
    """
    if published is None:
        published = published_paths(root, require=require)
    if published is None:
        return (root / rel).is_file()
    return rel in published


def filter_to_published(root: Path, paths: Iterable[Path],
                        require: Optional[str] = None) -> List[Path]:
    """Keep only the paths the published tree carries.

    Order-preserving. When `root` is not a published tree every path is kept,
    because nothing has been published and the caller's own walk is already
    the right answer.
    """
    paths = list(paths)
    published = published_paths(root, require=require)
    if published is None:
        return paths
    root = root.resolve()
    keep: List[Path] = []
    for p in paths:
        try:
            rel = p.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in published:
            keep.append(p)
    return keep
