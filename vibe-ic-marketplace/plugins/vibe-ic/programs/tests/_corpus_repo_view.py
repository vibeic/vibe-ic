#!/usr/bin/env python3
"""The published corpus, seen as a repository that tracks it under `benchmark-data/`.

WHY THIS EXISTS
===============
`provenance_correction_note_check` and `provenance_declared_output_check` judge
what GIT TRACKS, never what the working tree happens to hold. That is not a
detail — it is the #414/#416 lesson, and it is load-bearing: reading the working
tree once reported five HASH_MISMATCHes against a PUBLISHED deliverable that were
all untracked leftovers from a later local run. Both programs therefore enumerate
with

    git -C <repo> ls-files benchmark-data

so they can only be aimed at a repository that tracks the cells under that prefix.
A clone of `vibeic/benchmark-data` tracks the same cells under `ic/`.

Rather than weaken either program (neither is in this change) or let a corpus test
"measure" a tree that no longer holds cells, this builds a zero-copy VIEW: a
scratch repository whose index is the clone's own HEAD tree, read in under the
`benchmark-data/` prefix, with the clone's object database as an alternate. No
blob is copied and no digest is recomputed — the hashes these checks compare are
the clone's own objects, byte for byte.

WHAT IT IS NOT
==============
It cannot manufacture a pass. A view that came out empty or partial enumerates
too few ledgers, and every caller asserts a floor on the population it found
(>= 22 tracked ledgers, >= 156 declared outputs), so a broken view FAILS loudly
instead of passing vacuously. It also refuses to answer at all when no corpus is
readable — that case belongs to `_published_corpus.needs_corpus`, which says
"could not look" in the one wording the suite uses everywhere.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import _published_corpus as _pc


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: "
                           f"{r.stderr.strip()[:200]}")
    return r.stdout


def _toplevel(start: Path) -> Optional[Path]:
    try:
        out = _git(start, "rev-parse", "--show-toplevel").strip()
    except RuntimeError:
        return None
    return Path(out) if out else None


def corpus_repo(tmp_path: Path) -> Path:
    """A git repository whose tracked `benchmark-data/` IS the published corpus.

    Two shapes, because both are real:

      * a checkout that still carries the cells in-tree — returned as itself, so
        the audit runs exactly as it always did;
      * a clone named by `$VIBE_IC_BENCHMARK_DATA` — read into a scratch view
        under the prefix the checks enumerate.
    """
    root = _pc.corpus_root()
    if root is None:
        raise RuntimeError(
            "corpus_repo() was called with no published corpus readable. The "
            "caller must carry @needs_corpus; without it a check reports about "
            "a tree it never read. " + _pc.SKIP_REASON)
    top = _toplevel(root)
    if top is not None and (top / "benchmark-data").resolve() == root.resolve():
        return top
    return _prefixed_view(root, tmp_path)


def _prefixed_view(corpus: Path, dest: Path) -> Path:
    top = _toplevel(corpus)
    if top is None:
        raise RuntimeError(
            f"the corpus at {corpus} is not a git checkout. These checks judge "
            f"what git TRACKS rather than what the directory holds (#414/#416), "
            f"so they cannot be aimed at a loose directory of files — point "
            f"{_pc.CORPUS_ENV} at a clone.")

    rel = corpus.resolve().relative_to(top.resolve())
    spec = "HEAD^{tree}" if str(rel) == "." else f"HEAD:{rel.as_posix()}"
    tree = _git(corpus, "rev-parse", spec).strip()

    objects = Path(_git(corpus, "rev-parse", "--git-path", "objects").strip())
    if not objects.is_absolute():
        objects = corpus / objects

    view = Path(dest) / "corpus-view"
    view.mkdir(parents=True, exist_ok=True)
    _git(view, "init", "-q")
    alt = view / ".git" / "objects" / "info" / "alternates"
    alt.parent.mkdir(parents=True, exist_ok=True)
    alt.write_text(str(objects.resolve()) + "\n")
    _git(view, "read-tree", "--prefix=benchmark-data/", tree)

    # Only the ledgers are read off disk; every artefact these checks weigh is
    # read out of the object database, so nothing else needs materialising.
    leds = [ln for ln in _git(view, "ls-files", "benchmark-data").splitlines()
            if ln.endswith("provenance.jsonl")]
    if leds:
        r = subprocess.run(
            ["git", "-C", str(view), "checkout-index", "-f", "--stdin"],
            input="\n".join(leds) + "\n", text=True, capture_output=True)
        if r.returncode != 0:
            raise RuntimeError("could not materialise the corpus ledgers: "
                               f"{r.stderr.strip()[:200]}")
    return view
