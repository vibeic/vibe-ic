#!/usr/bin/env python3
"""Re-derive the published census under the provenance THE BLOCK DECLARES.

WHAT WENT WRONG
===============
``programs/tests/flow_matrix/README.md`` carries a GENERATED census block, and the
block names its own provenance on the line ``gen_flow_matrix_census
.corpus_identity_line`` writes into it::

    Corpus at generation: NOT_OFFERED — no published cell was read.

MEASURED on 2026-09-05, one full clone of main at ``3e3d0a46e``, the digest-pinned
image, the SAME tree in both arms, one file per process::

    VIBE_IC_BENCHMARK_DATA withheld              6 passed
    VIBE_IC_BENCHMARK_DATA=<corpus @ 8c4b608a>   4 passed, 2 failed
        test_the_census_block_is_fresh
        test_the_published_total_equals_the_live_census

Nothing is wrong with the tree, with the block, or with the corpus. 44 cells carry a
``needs_corpus`` skip that a mounted corpus lifts, so ``undeclared`` re-derives at
449 where the committed block publishes 405 — and the re-derivation ALSO writes
``Corpus at generation: PRESENT @ 8c4b608a``, which is the generator saying, in the
artefact itself, that the two things being compared were not made the same way.

So the freshness verdict was a function of an environment pointer that appears in no
argv, in no commit and in no report. A stamp run on a corpus-mounted host calls main
stale; the identical commit on a corpus-absent host calls it fresh. Both ran the same
check, and neither says which environment it was standing in.

WHAT THIS REFUSES, AND WHY NEITHER OBVIOUS REPAIR IS TAKEN
==========================================================
*Run the check with the corpus withheld.* That settles the verdict by choosing an
environment, which is the defect with a preferred value rather than a repair — and
the check's whole purpose is to measure the shipped tree as it is, on whatever host
it is asked about.

*Regenerate the block per corpus.* That publishes a figure nobody can reproduce
without a 353 MB side tree, and makes the check RED on every corpus-absent checkout,
which is every user.

THE RULE
========
Compare like with like. Re-derive under the provenance the block DECLARES, whatever
this host happens to have mounted, and give THREE outcomes rather than two:

    measured, and it reproduces            PASS
    measured, and it does not              FAIL — the block is stale
    the declared provenance could not
    be arranged on this host               NOT_MEASURED, NAMING what it could not
                                           arrange

NOT_MEASURED IS NOT THE EASY ANSWER, and that is a property of this module rather
than an intention stated about it. :func:`reproduce` arranges the declared
provenance whenever it CAN, and only the cases it genuinely cannot arrange reach the
third outcome: a block declaring ``PRESENT @ <sha>`` on a host with no corpus, a
block declaring ``NOT_OFFERED`` in a checkout that carries a corpus in-tree (which
this repository has not since ``c5d7f2d00``), and a block whose own provenance line
says ``UNRESOLVED``. MEASURED on the host this module was written on, with the
corpus mounted at ``VIBE_IC_BENCHMARK_DATA``: the declared ``NOT_OFFERED`` IS
arrangeable — the pointer is withheld for the derivation — so the check reaches a
real PASS and never the skip.

THE CACHE IS PART OF THE ENVIRONMENT (and this guard is not decoration)
======================================================================
Both census axes are memoised: ``test_flow_matrix_coverage.collect_items`` and
``cell_outcomes_with_record`` each drive a nested pytest session ONCE per process and
``lru_cache`` the answer. Arranging ``os.environ`` after one of them has already run
changes nothing about the cells — but it DOES change
``corpus_identity_line()``, which is read live. The re-derived block would then carry
the declared provenance over cells derived under a different one: the exact
like-with-like failure this module exists to remove, wearing this module's own
output. So :func:`reproduce` refuses a warm cache as NOT_MEASURED instead of
producing a verdict it cannot stand behind.
"""
from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterator, NamedTuple, Optional

import _published_corpus as PC

#: The line :func:`gen_flow_matrix_census.corpus_identity_line` writes. Parsed here
#: rather than in each consumer so that the WRITER and every READER of the
#: provenance share one spelling; a second spelling is how a declared fact and the
#: check over it drift apart while both look maintained.
_DECLARED_RE = re.compile(
    r"^Corpus at generation:\s*(?P<state>[A-Z_]+)(?:\s*@\s*(?P<sha>\S+))?",
    re.MULTILINE)

#: The two axes that spawn a nested pytest and therefore READ the environment. Named
#: rather than "every lru_cache in the module": a cache over something the pointer
#: cannot reach is not contamination, and refusing on it would make NOT_MEASURED the
#: easy answer this module refuses to make it.
_ENV_READING_CACHES = ("collect_items", "cell_outcomes_with_record")

#: The module those caches live in. Consulted through ``sys.modules`` and never
#: imported by this one: an unimported coverage module has, by construction, run no
#: nested session, and importing it here to ask would cost ~400 s to learn nothing.
_COVERAGE_MODULE = "test_flow_matrix_coverage"


#: THE PROVENANCE THIS PROCESS'S WARM CACHES WERE DERIVED UNDER, or None.
#:
#: The coldness guard below refuses a census that was already computed, and on its
#: own that would refuse the SECOND honest consumer as well:
#: ``test_flow_matrix_census_freshness.py`` runs three comparisons against the
#: block in one session and the first of them
#: warms the axes. What makes a warm cache admissible is not that it is warm, it is
#: WHICH ENVIRONMENT it was warmed in — recorded here by the arrangement that
#: warmed it, so a second consumer asking for the SAME provenance is served and one
#: asking for a different provenance is refused.
_DERIVED_UNDER: Optional["Declared"] = None


class CannotReproduce(RuntimeError):
    """NOT_MEASURED. The declared provenance could not be arranged HERE.

    Carries the sentence a reader acts on: what was declared, what this host has,
    and what could not be arranged between them. Never raised for a difference in
    the census itself — that is a FAIL and belongs to the caller.
    """


class NoDeclaredProvenance(CannotReproduce):
    """The block declares NO provenance at all — a DIFFERENT state, and it matters.

    Every block :func:`gen_flow_matrix_census.render` produces carries a
    ``Corpus at generation:`` line unconditionally. So a block WITHOUT one cannot
    equal any rendering under ANY environment, and a caller whose comparison is
    whole-block equality already has an environment-INDEPENDENT answer: stale.

    Its own class rather than a message, because the two callers here answer it
    differently and both are right:

      * ``--check`` compares the WHOLE block. It proceeds, unarranged, and says
        so — refusing would withhold a verdict that no pointer can move, and the
        one test in the suite that drives a `placeholder` block through
        ``--check`` is asking for exactly that verdict (vibe-ic#2004).
      * ``test_the_published_total_equals_the_live_census`` compares parsed
        FIGURES, and figures CAN coincide with the wrong environment's. It stays
        NOT_MEASURED, because for that comparison the answer really could go
        either way depending on the mount.
    """


class Declared(NamedTuple):
    """What the committed block says it was generated against."""
    state: str                 #: ``NOT_OFFERED`` / ``PRESENT`` / ``MEASURED_EMPTY`` / ``UNRESOLVED``
    corpus_sha: Optional[str]  #: the short commit the block names, when it names one

    def describe(self) -> str:
        return self.state + (f" @ {self.corpus_sha}" if self.corpus_sha else "")


#: The state tokens :func:`corpus_identity_line` can print, derived from the seam's
#: own constants so a fourth state added there cannot arrive here as an unparsed
#: word that silently reads as "not the one I handle".
_KNOWN_STATES = frozenset(
    s.upper().replace("-", "_")
    for s in (PC.PRESENT, PC.MEASURED_EMPTY, PC.NOT_OFFERED)) | {"UNRESOLVED"}


def declared_provenance(block: str) -> Declared:
    """The provenance line of a GENERATED census block, parsed.

    Raises :class:`NoDeclaredProvenance` when the block carries no such line at
    all. That is deliberately not a silent default of ``NOT_OFFERED``: a block
    written before the provenance line existed would then be compared against a
    corpus-withheld re-derivation on the strength of an assumption nobody
    recorded, which is the same defect one layer up. It is a SUBCLASS so a caller
    whose comparison cannot come out either way can act on it — see there.
    """
    m = _DECLARED_RE.search(block)
    if not m:
        raise NoDeclaredProvenance(
            "the committed census block declares no `Corpus at generation:` line, "
            "so there is no provenance to reproduce and no like-with-like "
            "comparison to make. Regenerate the block with a generator that emits "
            "one (`corpus_identity_line`), or read the difference below as "
            "UNKNOWN — it is not evidence of staleness.")
    state = m.group("state")
    if state not in _KNOWN_STATES:
        raise CannotReproduce(
            f"the committed census block declares `Corpus at generation: {state}`, "
            f"which is not one of the states this checkout's corpus seam can "
            f"produce ({', '.join(sorted(_KNOWN_STATES))}). It was generated by a "
            f"different vocabulary and cannot be reproduced against this one.")
    return Declared(state, m.group("sha"))


def corpus_commit(root: Path) -> str:
    """The corpus's own HEAD, short. ``unknown-commit`` rather than a guess.

    The single spelling shared by the writer of the provenance line and the reader
    that has to match it. When they were two spellings the reader could disagree
    with the writer about the same tree and report it as drift.
    """
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=str(root), capture_output=True, text=True,
                             timeout=20)
    except (OSError, subprocess.SubprocessError):
        return "unknown-commit"
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else "unknown-commit"


def _warm_caches() -> list:
    """Which env-reading census caches have ALREADY answered in this process.

    THREE CASES, AND COLLAPSING ANY TWO OF THEM IS A DEFECT IN THIS GUARD.

    * The module names NONE of the axes. It is not the coverage module — the
      generator's own CLI test installs a four-function stub under that name to
      drive `--check` over a synthetic census in under a second. A stub has run no
      nested session, so it is COLD, and refusing it would have made this guard
      turn a passing red/green proof into rc 2. MEASURED: it did, on the first
      run of `test_the_generator_cli_can_go_red_and_green` after this module
      landed.
    * The module names SOME of them and not the others. That is a RENAME in the
      coverage module, and answering "cold" to it would leave this guard blind
      exactly when the thing it guards moved. NOT_MEASURED, naming the axis that
      vanished.
    * It names them all. Then `cache_info` is the answer, and a name that carries
      no `cache_info` stopped being a cache: unaskable, and "could not read it" is
      never "read it and it was empty".
    """
    mod = sys.modules.get(_COVERAGE_MODULE)
    if mod is None:
        return []
    present = [n for n in _ENV_READING_CACHES if getattr(mod, n, None) is not None]
    if not present:
        return []
    warm = []
    for name in _ENV_READING_CACHES:
        fn = getattr(mod, name, None)
        if fn is None:
            warm.append(f"{name} (named by this module and now absent from "
                        f"{_COVERAGE_MODULE}: cannot be asked)")
            continue
        info = getattr(fn, "cache_info", None)
        if info is None:
            warm.append(f"{name} (no cache_info: cannot be asked)")
        elif info().currsize:
            warm.append(name)
    return warm


def _current_state() -> tuple:
    """``(state, root)`` from the live seam, with a broken pointer surfaced.

    ``CorpusPointerBroken`` is a statement about THIS HOST's configuration and not
    about the committed block, so it becomes NOT_MEASURED here rather than an
    exception a caller would report as a census defect.
    """
    try:
        return PC.corpus_state()
    except PC.CorpusPointerBroken as exc:
        raise CannotReproduce(
            f"this host's corpus pointer does not resolve, so no provenance can be "
            f"arranged from it: {exc}") from exc


def _already_derived_under(declared: "Declared") -> bool:
    """Were this process's warm axes derived under `declared` ANYWAY?

    TWO WAYS THEY CAN HAVE BEEN, and missing the second one costs real coverage.

    The first is that :func:`reproduce` arranged it and recorded that — the case
    of three comparisons against one block in one session.

    The second is that THIS HOST'S OWN ENVIRONMENT already resolves to the
    declared provenance, so nothing needed arranging and whoever warmed the axes
    warmed them correctly. That is the ordinary corpus-absent checkout, where the
    block declares NOT_OFFERED and the host offers nothing: without this branch a
    combined run — `test_flow_matrix_coverage.py` and this file in ONE pytest
    process, which is exactly what the targeted CI selection asks for — would
    report NOT_MEASURED over a derivation that is exactly right, and the check
    would quietly stop running for every user.

    A HOST THAT DOES NOT MATCH STILL REFUSES, and that refusal is the honest one:
    the cells in those caches were made somewhere else and this module cannot
    unmake them. Clearing the caches was considered and rejected — the tests that
    populated them are still running, and handing them a census re-derived under a
    different environment would corrupt their subject to repair ours.
    """
    if _DERIVED_UNDER == declared:
        return True
    try:
        state, root = _current_state()
    except CannotReproduce:
        return False
    here = state.upper().replace("-", "_")
    if here != declared.state:
        return False
    if declared.state != PC.PRESENT.upper().replace("-", "_"):
        return True
    return (root is not None and (declared.corpus_sha is None
                                  or corpus_commit(root) == declared.corpus_sha))


@contextlib.contextmanager
def reproduce(block: str) -> Iterator[Declared]:
    """Arrange ``os.environ`` so a re-derivation matches the block's OWN provenance.

    The environment is restored on the way out, including on the error path: this
    runs inside a pytest session and a program that mutates the process environment
    for its callers is the invisible pointer one layer down.

    Everything the comparison consumes must be derived INSIDE the block — the cells,
    the totals AND ``render()``, because ``corpus_identity_line()`` reads the live
    environment and would otherwise print this host's provenance onto cells derived
    under the declared one.
    """
    global _DERIVED_UNDER
    declared = declared_provenance(block)
    warm = _warm_caches()
    if warm and not _already_derived_under(declared):
        was = (_DERIVED_UNDER.describe() if _DERIVED_UNDER
               else "this host's own environment")
        raise CannotReproduce(
            f"the live census was already derived in this process under {was}, "
            f"before the declared provenance "
            f"({declared.describe()}) could be arranged — "
            f"{', '.join(warm)} already hold that answer. Re-deriving now would "
            f"compare those cells against a block made under "
            f"{declared.describe()}, and would print the declared provenance over "
            f"them. Drive this check in a process that has not yet run the census.")

    prev = os.environ.get(PC.CORPUS_ENV)
    try:
        if declared.state == "UNRESOLVED":
            raise CannotReproduce(
                "the committed block declares `Corpus at generation: UNRESOLVED` — "
                "the corpus seam could not be consulted when it was written, so it "
                "records no provenance to reproduce. Regenerate it on a host where "
                "the seam answers.")

        if declared.state == PC.NOT_OFFERED.upper().replace("-", "_"):
            # WITHHOLD THE POINTER, then CHECK that withholding was enough. The
            # repo-local `benchmark-data/` branch of `corpus_state` answers before
            # any pointer does, and a checkout carrying the corpus in-tree cannot
            # be talked into NOT_OFFERED by unsetting an environment variable.
            os.environ.pop(PC.CORPUS_ENV, None)
            state, _ = _current_state()
            if state != PC.NOT_OFFERED:
                raise CannotReproduce(
                    f"the committed block declares NOT_OFFERED, and this checkout "
                    f"resolves a corpus with the pointer withheld ({state}) — it "
                    f"carries one in-tree. The declared provenance cannot be "
                    f"arranged here by withholding {PC.CORPUS_ENV}.")
        elif declared.state == PC.MEASURED_EMPTY.upper().replace("-", "_"):
            state, _ = _current_state()
            if state != PC.MEASURED_EMPTY:
                raise CannotReproduce(
                    f"the committed block declares MEASURED_EMPTY — a corpus that "
                    f"was READ and publishes no cell. This host resolves {state}. "
                    f"Point {PC.CORPUS_ENV} at a corpus that publishes none, or "
                    f"read the difference as UNKNOWN.")
        else:                                    # PRESENT
            state, root = _current_state()
            if state != PC.PRESENT or root is None:
                raise CannotReproduce(
                    f"the committed block declares {declared.describe()} — it was "
                    f"generated against a MOUNTED corpus. This host resolves "
                    f"{state}, so the cells it would re-derive are not the cells "
                    f"the block is made of. Point {PC.CORPUS_ENV} at a clone of "
                    f"vibeic/benchmark-data at {declared.corpus_sha or 'that commit'}.")
            here = corpus_commit(root)
            if declared.corpus_sha and here != declared.corpus_sha:
                # NAMED, not tolerated. Two corpora both called "the corpus" is
                # exactly the drift `corpus_identity_line` was added to make
                # visible; accepting any mounted corpus would delete it again.
                raise CannotReproduce(
                    f"the committed block declares the corpus at "
                    f"{declared.corpus_sha} and this host has {here} mounted at "
                    f"{root}. A different corpus is a different derivation; "
                    f"comparing them and calling the difference staleness is the "
                    f"defect this check exists to refuse.")
        # RECORDED BEFORE THE BODY RUNS, because the body is what warms the
        # caches and it is already inside the arranged environment. A body that
        # derives nothing leaves them cold and this marker is never consulted.
        _DERIVED_UNDER = declared
        yield declared
    finally:
        if prev is None:
            os.environ.pop(PC.CORPUS_ENV, None)
        else:
            os.environ[PC.CORPUS_ENV] = prev
