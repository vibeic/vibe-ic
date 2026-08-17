#!/usr/bin/env python3
"""Give each tree-exclusive test file its OWN checkout, so nothing can dirty it.

WHY, MEASURED
=============
The first attempt at isolating these 21 files ran them SERIALLY, after the parallel
wave, in the shared tree. It changed nothing: the verdict hash was byte-identical to
the unisolated run (e08f83d7a507c013), and the `=== [tree-exclusive]` line proves
the split really executed.

That result named the real cause. These files fail not because they run BESIDE each
other but because the PARALLEL WAVE ITSELF leaves residue in the tree, and a test
whose assertion is "the shipped tree is clean" then reads that residue. Ordering
them later cannot help — the damage is already done before they start.

So they do not need an ORDER, they need a TREE. Each gets a fresh `git worktree` at
the same commit, which nothing else is running in.

AND THEN THEY CAN RUN AT ONCE. Serialising them was the price of sharing one tree;
with a tree each there is nothing left to share, so they go concurrently like
everything else. The isolation is what buys the parallelism back, not what spends it.

WHAT THIS COSTS AND WHAT IT DOES NOT
====================================
A worktree is ~200-500 ms and some disk. That is real, and it is nothing against a
test file that takes tens of seconds. What it does NOT cost is coverage: each file
runs the same tests, with the same argv, over the same commit. The only thing that
changes is who else is allowed to write next to it.

FAILURE IS A REFUSAL, NEVER A PASS. If a worktree cannot be created, that file is
reported as having no record rather than being skipped or assumed green — the
driver already treats a missing record as a refusal, and this must not become the
one path that quietly opts out of it.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

#: The plugin's position inside the repo, so a worktree of the repo can be turned
#: into the cwd the driver's children expect. Derived rather than hard-coded twice:
#: this file lives at <repo>/vibe-ic-marketplace/plugins/vibe-ic/programs/.
_PLUGIN_REL = Path(__file__).resolve().parents[1].relative_to(
    Path(__file__).resolve().parents[4])


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def make(commit: str, tag: str) -> Tuple[Optional[Path], Optional[str]]:
    """(worktree_path, None) or (None, reason). A reason is a REFUSAL, not a skip."""
    root = repo_root()
    base = Path(tempfile.mkdtemp(prefix=f"gk_excl_{tag}_"))
    # mkdtemp created it; `git worktree add` insists on a path that does not exist.
    shutil.rmtree(base, ignore_errors=True)
    cp = subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "-q", "--detach",
         str(base), commit],
        capture_output=True, text=True, timeout=180)
    if cp.returncode != 0:
        return None, (f"could not create an isolated worktree at {base}: "
                      f"{(cp.stderr or cp.stdout).strip()[:200]}")
    return base, None


def cwd_for(worktree: Path) -> str:
    """The directory the driver's children must run in inside that worktree."""
    return str(worktree / _PLUGIN_REL)


def remove(worktree: Path) -> None:
    """Best effort, and unconditional: a leaked worktree makes the NEXT round's
    clean-tree gate blame that round for a tree this one left behind."""
    root = repo_root()
    subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force",
                    str(worktree)],
                   capture_output=True, text=True, timeout=120)
    if worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)


def head_commit() -> Optional[str]:
    cp = subprocess.run(["git", "-C", str(repo_root()), "rev-parse", "HEAD"],
                        capture_output=True, text=True, timeout=60)
    return cp.stdout.strip() if cp.returncode == 0 and cp.stdout.strip() else None


def prune() -> None:
    subprocess.run(["git", "-C", str(repo_root()), "worktree", "prune", "-q"],
                   capture_output=True, text=True, timeout=120)


def plan(indices: List[int], selection) -> List[Tuple[int, str, str]]:
    """[(index, path, tag)] — the tag names the worktree after its file, so a leaked
    one can be traced to the test that leaked it rather than to a random suffix."""
    out = []
    for i in indices:
        p = selection[i - 1]
        stem = p.rsplit("/", 1)[-1]
        if stem.endswith(".py"):
            stem = stem[:-3]
        out.append((i, p, stem[:40]))
    return out
