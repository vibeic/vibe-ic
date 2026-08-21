#!/usr/bin/env python3
"""programs/_run_isolation.py — run a program against a COPY of a published run,
and prove the original did not move.

    An instrument that writes into its subject is not measuring it.

WHY THIS IS SHARED CODE AND NOT A THIRD CAREFUL DOCSTRING
=========================================================
Three separate pieces of work hit this in one day, each found by a different
agent doing a different task, and each fixed its own instance correctly:

  * **the corpus baseline** (``tools/d9_corpus_baseline.py``) — 10 of 77
    content-reading checkers WRITE INTO the run they judge.
    ``phase1_one_shot_runner`` rewrites ``phase1/generated_docs/*``, ``qsf_gen``
    emits FPGA project files, ``ip_catalog_pull`` drops vendor RTL into
    ``phase2/stage1/rtl/``. The first sweep left 2336 tracked files modified,
    and — worse for the numbers — made the verdicts depend on SCHEDULING ORDER:
    a checker reading after the rewrite reads different content from one that
    ran before. One checker read 91 red contaminated against 17 isolated.
  * **the mutation ledger** (``matrix_mutation_ledger.py``) — a ``cp -al``
    hardlink mirror let the gate programs' ordinary open-for-write TRUNCATE
    EIGHT PUBLISHED ARTEFACTS through shared inodes. The copy was correct; the
    SHARING was the defect.
  * **the flow-declaration work**
    (``tests/test_flow_declaration_does_not_silence_its_producer.py``) — its L3
    leg runs real gates through ``check_step``, which write into the project
    directory, so it had to build throwaway fixtures.

None of the three widened scope into the others, and that was right three
times. What it leaves behind is a CLASS with three hand-written treatments of
the same hazard, in three docstrings, that no fourth author will find.

THE GENERALISABLE FINDING, WHICH IS THE IMPORTANT ONE
=====================================================
The corpus baseline probed for writers and recorded the census as a finding
rather than relying on it, because the census does not converge:

    probing 1 run  found  3 writers
    probing 2 runs found  8 writers
    probing 3 runs found 10 writers

Writers fire on what is PRESENT — ``dfm_screen_check`` writes only where a
``phase3/`` exists, ``ip_catalog_pull`` only where it can resolve IP — so a
probe is a lower bound and cannot bound the set. **Isolation must therefore be
unconditional or it is not isolation.** Nothing here takes a "does this program
write?" argument, and that omission is the design.

WHAT THIS MODULE REFUSES
========================
1. **A hardlinked copy.** :func:`copy_run` copies for real and then proves it:
   the ``(st_dev, st_ino)`` sets of source and copy must be DISJOINT. A plain
   "did we copy every path" assertion would NOT have caught the ledger's bug —
   every path was there; the inodes were shared.
2. **A source that moved.** :func:`isolated_run` stat-manifests the source
   before and after and raises :class:`SubjectPerturbed` naming the paths.
3. **A silent zero.** Copying a run with no files refuses; the tripwire over a
   path git does not track refuses. A measurement whose denominator is zero
   must refuse rather than pass, and every result here carries the number of
   files it examined so a caller can state it.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
=========================================
It does not change what any gate WRITES. Every one of the three fixes above
left its gate's producing behaviour exactly as it was, and so does this: the
hazard is handled by giving the gate a throwaway subject, never by asking it to
write less.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Optional, Sequence, Tuple

try:  # in-tree import, whether or not `programs/` is on sys.path
    from _crash_safe_scratch import reserve
except ImportError:  # pragma: no cover - exercised by the packaged layout
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _crash_safe_scratch import reserve

#: The corpus every tripwire below defaults to. One name, so a caller cannot
#: quietly narrow the guard to a subdirectory that happens to be clean.
CORPUS = "benchmark-data"


class Perturbation(Exception):
    """Base: the instrument moved something it was only supposed to read."""


class SubjectPerturbed(Perturbation):
    """A published run changed while a program ran against a copy of it."""


class CorpusContaminated(Perturbation):
    """``git status --porcelain`` over the corpus is not empty."""


class EmptySubject(Perturbation):
    """A zero denominator: there was nothing to isolate, or nothing to check."""


class FileStat(NamedTuple):
    """Enough to catch a rewrite, a truncation and a shared inode."""

    size: int
    mtime_ns: int
    dev: int
    ino: int


class Drift(NamedTuple):
    """What moved between two snapshots, and how much was looked at."""

    added: Tuple[str, ...]
    removed: Tuple[str, ...]
    changed: Tuple[str, ...]
    #: The denominator. A Drift with ``examined == 0`` proves nothing.
    examined: int

    @property
    def clean(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def describe(self) -> str:
        """One line that states the reach as well as the result."""
        if self.clean:
            return f"unchanged across {self.examined} file(s)"
        return (f"{len(self.added)} added / {len(self.removed)} removed / "
                f"{len(self.changed)} changed, of {self.examined} file(s) "
                f"examined; e.g. "
                f"{sorted(self.added + self.removed + self.changed)[:5]}")


def snapshot(root: Path) -> Dict[str, FileStat]:
    """``{relative path: FileStat}`` for every regular file under *root*.

    One ``stat`` per file and no reads, so it is cheap enough to take on both
    sides of every isolated run rather than only when someone suspects a
    problem. Symlinks are recorded by their own ``lstat``: a run that had a
    symlink REPLACED by a regular file has been perturbed, and following the
    link would hide exactly that.
    """
    out: Dict[str, FileStat] = {}
    root = Path(root)
    for p in root.rglob("*"):
        try:
            st = p.lstat()
        except OSError:  # pragma: no cover - races on a shared tree
            continue
        if not (p.is_file() or p.is_symlink()):
            continue
        out[str(p.relative_to(root))] = FileStat(
            st.st_size, st.st_mtime_ns, st.st_dev, st.st_ino)
    return out


def drift(before: Dict[str, FileStat],
          after: Dict[str, FileStat]) -> Drift:
    """Compare two :func:`snapshot` results.

    ``examined`` is the size of the UNION, not of either side: a run that only
    gained files was still examined over both, and reporting the smaller number
    would understate the reach of the check.
    """
    a, b = set(before), set(after)
    return Drift(
        added=tuple(sorted(b - a)),
        removed=tuple(sorted(a - b)),
        changed=tuple(sorted(
            k for k in a & b
            if (before[k].size, before[k].mtime_ns)
            != (after[k].size, after[k].mtime_ns))),
        examined=len(a | b),
    )


def shared_inodes(left: Dict[str, FileStat],
                  right: Dict[str, FileStat]) -> Tuple[str, ...]:
    """Paths in *right* whose inode also backs a file in *left*.

    THE CHECK THAT THE LEDGER'S BUG NEEDED. ``cp -al`` produces a tree in which
    every path exists and every size matches, so a copy-completeness assertion
    passes; the first ordinary open-for-write in the copy then truncates the
    original. Comparing ``(dev, ino)`` is the only cheap statement of "these
    are different files".
    """
    seen = {(s.dev, s.ino) for s in left.values()}
    return tuple(sorted(k for k, s in right.items() if (s.dev, s.ino) in seen))


class IsolatedRun(NamedTuple):
    """A throwaway copy of a published run, and the source it must not touch."""

    source: Path
    #: Run programs against THIS. Deleted when the context exits.
    copy: Path
    #: How many files were copied. The denominator for any claim about it.
    examined: int


def copy_run(src: Path, dst: Path) -> int:
    """Copy a published run for real, and prove it shares nothing with *src*.

    Returns the number of files copied. Refuses a source that holds none:
    isolating an empty tree and reporting success is a zero denominator wearing
    the word "isolated".
    """
    src, dst = Path(src), Path(dst)
    if not src.is_dir():
        raise EmptySubject(f"{src} is not a directory; there is nothing to isolate")
    before = snapshot(src)
    if not before:
        raise EmptySubject(
            f"{src} holds no files, so a program run against a copy of it "
            f"would be measuring nothing; refusing rather than reporting an "
            f"isolated run over an empty subject")
    shutil.copytree(src, dst, symlinks=True)
    after = snapshot(dst)
    shared = shared_inodes(before, after)
    if shared:
        raise SubjectPerturbed(
            f"the copy of {src} at {dst} shares {len(shared)} inode(s) with "
            f"the original, e.g. {list(shared[:5])}. A write into the copy "
            f"would truncate the published file through the shared inode — "
            f"this is the `cp -al` defect, and it is refused here rather than "
            f"discovered afterwards in `git status`.")
    return len(after)


@contextmanager
def isolated_run(src: Path, *, prefix: str = "runiso_") -> Iterator[IsolatedRun]:
    """Yield a throwaway copy of *src*; raise if *src* itself moved.

    The scratch directory comes from :mod:`_crash_safe_scratch`, so a run this
    process never gets to clean up — ``SIGKILL``, a harness tearing down the
    process group — is reaped by the next one instead of accumulating.

    The after-snapshot is taken in a ``finally``, so a program that raises
    still gets its subject checked: a crash is exactly when a half-written file
    is most likely to have been left behind.
    """
    src = Path(src)
    before = snapshot(src)
    if not before:
        raise EmptySubject(
            f"{src} holds no files; refusing to report an isolated run over "
            f"an empty subject")
    reservation, _ = reserve(prefix)
    try:
        dst = Path(reservation.path) / "run"
        n = copy_run(src, dst)
        yield IsolatedRun(source=src, copy=dst, examined=n)
    finally:
        moved = drift(before, snapshot(src))
        reservation.release()
        if not moved.clean:
            raise SubjectPerturbed(
                f"the published run {src} changed while a program ran against "
                f"a COPY of it: {moved.describe()}. An instrument that writes "
                f"into its subject is not measuring it.")


class Outcome(NamedTuple):
    """What the program did, and what it did to the copy it was given."""

    returncode: int
    stdout: str
    stderr: str
    #: What the program changed INSIDE the throwaway copy. Not a failure —
    #: this is the writer census the corpus baseline publishes as a finding.
    wrote: Drift
    #: Files in the copy the program was given.
    examined: int


def run_against_copy(src: Path, argv: Sequence[str], *,
                     cwd_in_copy: bool = True,
                     timeout: Optional[int] = None,
                     env: Optional[Dict[str, str]] = None,
                     prefix: str = "runiso_") -> Outcome:
    """Run *argv* against a throwaway copy of the published run *src*.

    ``{run}`` anywhere in *argv* is replaced with the copy's path, which is how
    a caller points a program at the copy without knowing where it landed.

    A non-zero exit is NOT an error here — plenty of gates are meant to fail on
    plenty of runs, and deciding that is the caller's business. What this
    function guarantees is only the thing every caller needs and no caller
    should re-implement: whatever the program did, it did it to the copy.
    """
    with isolated_run(src, prefix=prefix) as iso:
        argv = [str(a).replace("{run}", str(iso.copy)) for a in argv]
        before = snapshot(iso.copy)
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout,
                cwd=str(iso.copy) if cwd_in_copy else None,
                env=({**os.environ, **env} if env else None))
            rc, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as e:
            rc, out, err = 124, (e.stdout or b"").decode(errors="replace"), \
                f"timeout after {timeout}s"
        return Outcome(rc, out, err, drift(before, snapshot(iso.copy)),
                       iso.examined)


# ══════════════════════════════════════════════════════════════════════
# THE TRIPWIRE
# ══════════════════════════════════════════════════════════════════════
class CorpusStatus(NamedTuple):
    """``git status --porcelain`` over the corpus, with its denominator."""

    repo: Path
    subpath: str
    #: The porcelain lines. Empty is the only passing value.
    dirty: Tuple[str, ...]
    #: Files git TRACKS under ``subpath``. If this is zero the tripwire was
    #: pointed somewhere it cannot see, and reporting "clean" would be a pass
    #: over nothing.
    tracked: int

    @property
    def clean(self) -> bool:
        return not self.dirty

    def describe(self) -> str:
        if self.clean:
            return (f"{self.subpath} is pristine across {self.tracked} tracked "
                    f"file(s)")
        return (f"{self.subpath} has {len(self.dirty)} modified path(s) of "
                f"{self.tracked} tracked, e.g. {list(self.dirty[:5])}")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True,
                          check=True).stdout


def repo_root(start: Optional[Path] = None) -> Path:
    """The git worktree containing *start* (default: this file)."""
    s = Path(start) if start else Path(__file__).resolve()
    d = s if s.is_dir() else s.parent
    return Path(_git(d, "rev-parse", "--show-toplevel").strip())


def corpus_status(repo: Optional[Path] = None,
                  subpath: str = CORPUS) -> CorpusStatus:
    """``git status --porcelain <subpath>``, plus how much git tracks there.

    ``--porcelain`` alone would report "clean" just as happily for a path that
    does not exist, for a typo, and for a corpus that really is untouched. The
    tracked count separates the three, and :func:`assert_corpus_pristine`
    refuses the first two instead of passing.
    """
    root = Path(repo) if repo else repo_root()
    dirty = tuple(
        ln for ln in _git(root, "status", "--porcelain", "--", subpath)
        .splitlines() if ln.strip())
    tracked = sum(
        1 for ln in _git(root, "ls-files", "--", subpath).splitlines()
        if ln.strip())
    return CorpusStatus(root, subpath, dirty, tracked)


def assert_corpus_pristine(repo: Optional[Path] = None,
                           subpath: str = CORPUS,
                           *, what: str = "this measurement") -> CorpusStatus:
    """THE TRIPWIRE. Call after any sweep that reads the published corpus.

    Three agents asserted this by hand in three different docstrings on one
    day. It belongs in the harness, where the fourth author gets it without
    having to have read the other three.

    Raises :class:`EmptySubject` when git tracks nothing under *subpath* — a
    tripwire that cannot see its subject must refuse, not report clean — and
    :class:`CorpusContaminated` when anything moved.
    """
    st = corpus_status(repo, subpath)
    if st.tracked == 0:
        raise EmptySubject(
            f"git tracks no files under {subpath!r} in {st.repo}, so "
            f"'--porcelain is empty' says nothing about {what}. A tripwire "
            f"over a zero denominator must refuse rather than pass.")
    if not st.clean:
        raise CorpusContaminated(
            f"{what} modified the corpus it was reading: {st.describe()}.\n"
            f"Isolation is unconditional or it is not isolation — probing for "
            f"writers finds 3, 8 or 10 of them depending on how many runs you "
            f"probe, so a program is never known not to write. Route it "
            f"through _run_isolation.run_against_copy / isolated_run.\n"
            f"Full status:\n  " + "\n  ".join(st.dirty))
    return st


def main(argv: Optional[List[str]] = None) -> int:
    """``python3 programs/_run_isolation.py [subpath]`` — run the tripwire."""
    args = list(sys.argv[1:] if argv is None else argv)
    sub = args[0] if args else CORPUS
    try:
        st = assert_corpus_pristine(subpath=sub)
    except Perturbation as e:
        print(f"[FAIL] _run_isolation: {e}")
        return 1
    print(f"[PASS] _run_isolation: {st.describe()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
