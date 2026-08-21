#!/usr/bin/env python3
"""_corpus_location.py — "where is the published corpus, and may it be absent?",
answered once.

WHY THIS MODULE EXISTS
======================
v1.10.56 moved the three published trees (`benchmark-data/`, `benchmark_external/`,
`IP/`) into their own repositories. Every gate that had been aimed at a literal
`<repo>/benchmark-data...` then answered with some spelling of "it is not there",
and `run` in `_gate_dispatch.sh` maps both rc 1 and rc 2 to FAIL, so an absent
corpus blocked every landing.

Each refusal was CORRECT for what the gate was asked. What was wrong is WHERE it
was told to look — and, separately, that "the corpus lives somewhere else" and
"somebody pointed me at a corpus and was wrong" came out as the same word.

`benchmark_evidence_structure_check` (vibe-ic#1710, v1.10.51) separated the
outcomes for the first time; `tracked_symlink_portability_check`,
`tracked_symlink_target_present_check` and `benchmark_evidence_index` (v1.10.60)
each re-derived the same resolution by hand. This module is that resolution
written ONCE, for the same reason `_published_tree` exists: three programs asked
the same question on the same day and three programs got it wrong the same way.

THE FOUR OUTCOMES, AND COLLAPSING ANY TWO OF THEM IS THE DEFECT
===============================================================
    $VIBE_IC_BENCHMARK_DATA set + unreadable
        -> UNDETERMINED (rc 2). Somebody said where the corpus is and was
           wrong: a mistyped path, a failed clone, a CI fetch step that did
           nothing. NEVER excused, with or without the opt-in below.

    set + present but NOT a git checkout, for a gate that reads git's INDEX
        -> UNDETERMINED (rc 2). An empty `git ls-files` is "I could not look",
           not "there are none". MEASURED in v1.10.60 on two corpora built
           byte-identically except for `git init`, both physically carrying one
           absolute-target symlink: the checkout FAILED rc 1 and the plain
           directory PASSED rc 0. A tarball fetch, an archive export, a dead
           `git clone` or a worktree without `.git` all produce that input — a
           FAILED FETCH CERTIFYING A TREE, strictly worse than NO_CORPUS, which
           at least states that nothing was scanned.

    nothing anywhere + the CALL SITE opted in
        -> NO_CORPUS (rc 0). Nothing was scanned and NOTHING IS CLAIMED to have
           been scanned.

    nothing anywhere + nobody said so
        -> UNDETERMINED (rc 2). Unchanged.

THE OVERRIDE IS ANNOUNCED, AND SO IS DECLINING IT
=================================================
A gate that scans a tree other than the one named on its command line, in
silence, is how a mis-aimed `--tree` once reported "13/28 conformant" over a
tree an absolute path found 8 failures in. And a pointer a reader BELIEVES is in
force, that is not, is the same ambiguity pointing the other way — so
:func:`resolve` announces both.

THE POINTER REPLACES A MISSING CORPUS; IT DOES NOT REPLACE A PRESENT ONE. A
caller who names a root that DOES carry a corpus has named a readable corpus,
and walking a different one instead is precisely the failure the announcement
exists to prevent. (MEASURED in v1.10.60: letting the pointer win outright
turned 15 of 21 tests in `test_issue440_benchmark_evidence_index.py` red for
every developer who has the pointer set.)

THE OPT-IN IS A FLAG THE CALL SITE PASSES, NEVER A DEFAULT. The dangerous row is
the third one: an rc 0 for a scan that did not happen is the false certificate
this whole gate suite exists to remove, and the only thing keeping it from
becoming the general answer is that somebody has to type it.

AND SOME CALL SITES HAVE NO SUCH FLAG AT ALL, which is a THIRD state and not a
spelling of "did not pass it". A producer whose consumer reads only its exit
status and its item count cannot afford the NO_CORPUS row at any price: rc 0
with nothing on stdout is, at that consumer, byte-identical to a corpus that was
opened and holds none. MEASURED 2026-08-21 on `tools/ci/routed_def_corpus.py`
(vibe-ic#1764): with nothing at `benchmark-data/` and the pointer unset, and
again with a resolved checkout carrying no routed DEF, the dispatcher received
`rc 0, 0 items` both times and printed `corpus ... is EMPTY — nothing was
checked over it` about a corpus nothing had opened. Such a caller passes
``absent_opt_in=None`` to :func:`refuse`, which then refuses the absent row AND
stops naming a flag the caller does not accept — a remedy whose real answer is
`unrecognized arguments` is the false-premise defect one layer down.

chip-AGNOSTIC: pure path/git plumbing. No design, PDK, vendor or SKU literal.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

#: Where a caller may point us at a clone of the published-corpus repository.
#:
#: Spelled exactly as `benchmark_evidence_structure_check.CORPUS_ENV`,
#: `tracked_symlink_portability_check.CORPUS_ENV`, `benchmark_evidence_index`
#: and `programs/tests/_published_corpus.CORPUS_ENV` spell it — one name for one
#: thing. Gates that disagree about where the corpus lives will disagree about
#: whether it was checked.
CORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"
BOUND_SHA_ENV = "GATEKEEPER_BENCHMARK_DATA_SHA"

#: What the published corpus tree was CALLED while it lived in this repository.
#: The pointer names a clone whose ROOT is that tree, so a population recorded
#: as `benchmark-data/ic` before v1.10.56 is `ic` inside the clone. Baselines
#: record the population they were measured over and refuse to ratchet one
#: against another (vibe-ic#1223), so the two spellings must be reconciled
#: DELIBERATELY and in one place rather than by each gate guessing.
CANONICAL_CORPUS_NAME = "benchmark-data"

#: The flag a call site conventionally exposes to reach the NO_CORPUS row.
#: Quoted by :func:`refuse` so the remedy a reader is handed is the spelling
#: every gate that HAS one actually accepts. A caller with no such flag passes
#: ``absent_opt_in=None`` instead of a second spelling of this string.
ABSENT_OPT_IN = "--corpus-may-be-absent"

#: Origins returned by :func:`resolve`.
NAMED = "named"          #: the path the caller/CI named, in this repository
ENV = "env"              #: `$VIBE_IC_BENCHMARK_DATA` supplied it
REFUSED = "refused"      #: a bound landing omitted its mandatory checkout

# ``resolve`` historically returns a path even when resolution fails, and its
# callers uniformly ask ``is_dir()`` before delegating to :func:`refuse`.  A
# bound SHA without its pointer must therefore return a path which can never be
# supplied by the candidate.  A child below the platform null device cannot be
# a directory; unlike a repository-relative sentinel, the subject cannot create
# it and turn a configuration refusal into a scan of its own bytes.
_UNSCANNABLE_BOUND_PATH = Path(os.devnull) / \
    ".vibeic-bound-corpus-pointer-missing"


class CorpusIndexIndeterminate(RuntimeError):
    """The index probe itself failed; callers must not infer a population."""


def env_pointer() -> Optional[str]:
    """The raw pointer, or None. Read in one place so a test that clears it
    clears it for everybody."""
    return os.environ.get(CORPUS_ENV) or None


def resolve(named: Path, subdir: Optional[str] = None, gate: str = "",
            announce: bool = False) -> Tuple[Path, str]:
    """``(directory to scan, origin)`` where origin is :data:`NAMED` or :data:`ENV`.

    The path is returned WHETHER OR NOT IT EXISTS. Deciding what an absent one
    means is the caller's job and it is a different decision per origin: an
    absent env-named tree is a broken pointer, an absent repo-local one is a
    corpus that lives elsewhere. :func:`refuse` makes that decision uniformly.

    `subdir` is the component of the named path that lives at the ROOT of the
    clone. CI names `<repo>/benchmark-data/ic`, and the clone carries `ic/` at
    its top, so gates over the cell tree pass ``subdir="ic"``; a gate over the
    whole `benchmark-data` tree passes None.
    """
    env = env_pointer()
    tag = f"[{gate}] " if gate else ""
    if os.environ.get(BOUND_SHA_ENV):
        # Landing has already byte-attested one immutable external checkout.
        # Letting a candidate-local `benchmark-data/` win here would scan a
        # different tree while every summary still names the external SHA.
        # Outside that bound protocol the historical named-root precedence is
        # unchanged for developer/test callers.
        if env:
            target = Path(env) / subdir if subdir else Path(env)
            if announce:
                print(
                    f"{tag}note: {BOUND_SHA_ENV} binds the landing corpus; "
                    f"forcing {CORPUS_ENV}={env} -> {target} and refusing any "
                    f"candidate-local {named} shadow.", file=sys.stderr)
            return target, ENV
        if announce:
            print(
                f"{tag}UNDETERMINED: {BOUND_SHA_ENV} is set without "
                f"{CORPUS_ENV}; no bound checkout can be resolved.",
                file=sys.stderr)
        return _UNSCANNABLE_BOUND_PATH, REFUSED
    if named.is_dir():
        if env and announce:
            # Declining the pointer is announced too: a reader who has it set
            # would otherwise have no way to know which tree produced the
            # verdict.
            print(f"{tag}note: scanning the corpus at the named root ({named}); "
                  f"{CORPUS_ENV}={env} is set and NOT followed, because the "
                  f"named root carries a corpus of its own.", file=sys.stderr)
        return named, NAMED
    if env:
        target = Path(env) / subdir if subdir else Path(env)
        if announce:
            print(f"{tag}note: {CORPUS_ENV} overrides {named} -> {target}",
                  file=sys.stderr)
        return target, ENV
    return named, NAMED


def not_a_checkout_reason(root: Path, reads: str, *,
                          timeout: Optional[float] = 60,
                          strict: bool = False) -> Optional[str]:
    """A sentence naming why `root` cannot answer an INDEX question, or None.

    None means "this IS a git checkout". Anything else is the message a gate
    that reads `git ls-files` must refuse with, because over a present tree
    that git cannot read, an empty enumeration reaches the audit as "there are
    none" and the program certifies it.

    A semantic-progress caller passes ``strict=True, timeout=None``.  Its
    owning supervisor, not a duration guess inside this probe, then turns a
    hung or broken Git child into NORECORD.  Strict probe failures raise so
    they cannot be mistaken for a successfully classified loose directory.
    """
    if strict and timeout is not None:
        raise ValueError(
            "strict corpus index probes must be owned without an inner timeout")
    try:
        probe = subprocess.run(["git", "-C", str(root), "rev-parse",
                                "--show-toplevel"],
                               capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:   # noqa: BLE001
        if strict:
            raise CorpusIndexIndeterminate(
                f"git checkout probe failed for {root}: {exc}") from exc
        return (f"{root} exists but git could not be asked about it ({exc}), "
                f"and this gate reads git's INDEX to enumerate {reads}. "
                f"Enumerating zero of them is 'I could not look', not 'there "
                f"are none'.")
    if probe.returncode != 0 or not probe.stdout.strip():
        return (f"{root} exists but is not a git checkout, and this gate reads "
                f"git's INDEX to enumerate {reads} — a loose directory has none "
                f"to ask. Enumerating zero of them there is 'I could not look', "
                f"not 'there are none'. A tarball fetch, an archive export or a "
                f"dead clone all produce this tree.")
    return None


def refuse(gate: str, named: Path, resolved: Path, origin: str,
           may_be_absent: bool, scanned: str,
           absent_opt_in: Optional[str] = ABSENT_OPT_IN) -> int:
    """The rc for a corpus that could not be resolved, with the reason printed.

    `scanned` names what this gate would have examined ("published cell(s)",
    "published run tree(s)", "published gate record(s)") so the NO_CORPUS line
    states a zero over a named population rather than a bare silence.

    `absent_opt_in` is the flag THIS CALL SITE ACCEPTS to reach the NO_CORPUS
    row, quoted verbatim in the UNDETERMINED sentences so a reader is handed a
    remedy they can actually type. A caller that exposes no such flag — because
    for it an unopened corpus is never an acceptable input — passes None, and
    the sentences then say that rather than naming a flag whose real answer is
    `unrecognized arguments`. It does NOT decide the rc: `may_be_absent` alone
    does that, and a caller passing None simply never passes True either.

    Returns 2 for both UNDETERMINED rows and 0 for NO_CORPUS. It never returns
    1: "the corpus is not here" is not a finding against anything.
    """
    env = env_pointer()
    if origin == REFUSED:
        print(
            f"[{gate}] UNDETERMINED: {BOUND_SHA_ENV} is set but "
            f"{CORPUS_ENV} is unset, so no byte-attested checkout is bound to "
            "that SHA. Candidate-local corpus bytes are not an acceptable "
            "substitute; nothing was scanned.", file=sys.stderr)
        return 2
    if origin == ENV:
        # SET AND WRONG IS NOT ABSENT. Laundering it as NO_CORPUS would turn a
        # mistyped path, a failed clone or a no-op CI fetch step into a green
        # gate over nothing — the exact shape vibe-ic#1710 closed.
        print(f"[{gate}] UNDETERMINED: {CORPUS_ENV}={env} is set and "
              f"{resolved} is not a readable directory, so this gate scanned "
              f"nothing and examined 0 {scanned}. A pointer that is set and "
              f"wrong is a broken configuration, not an absent corpus, and "
              + (f"{absent_opt_in} does not excuse it."
                 if absent_opt_in else
                 "this caller accepts no absent opt-in that could excuse it."),
              file=sys.stderr)
        return 2
    if may_be_absent:
        # rc 0, and it must never read as a scan that happened.
        print(f"[{gate}] NO_CORPUS: nothing at {named} and {CORPUS_ENV} is "
              f"unset. The published corpus moved to its own repository in "
              f"v1.10.56 and this repo is not required to carry it. NOTHING "
              f"WAS SCANNED, 0 {scanned} were examined and nothing is claimed "
              f"about them — point {CORPUS_ENV} at a clone to make this gate "
              f"check something.", file=sys.stderr)
        return 0
    print(f"[{gate}] UNDETERMINED: no corpus at {named}, so this gate scanned "
          f"nothing and examined 0 {scanned}. A check that could not look has "
          f"not passed. Point {CORPUS_ENV} at a clone of the published-corpus "
          f"repository"
          + (f", or pass {absent_opt_in} if this repo need not "
             f"carry one." if absent_opt_in else
             ". This caller accepts no absent opt-in: a corpus nothing opened "
             "and a corpus that was read and holds none must not reach its "
             "consumer as the same answer."), file=sys.stderr)
    return 2


def population_key(corpus: Path, origin: str) -> str:
    """WHICH population a count was taken over, as a repository-relative path.

    THE INTEGER IS MEANINGLESS WITHOUT THE SET IT COUNTED (vibe-ic#1223), and
    after the corpus split the same set has two spellings: `benchmark-data/ic`
    while it lived here, `ic` inside the clone the pointer names. A baseline
    recorded under the first must still ratchet against a sweep of the second —
    they are the same cells — so the ENV origin is normalised back to the
    canonical name rather than each side being left to drift.

    That normalisation is deliberately NOT applied to a NAMED root: a caller who
    types a path in this repository gets the key for the tree they typed.
    """
    c = corpus.resolve()
    for anc in (c, *c.parents):
        if (anc / ".git").exists():
            try:
                rel = c.relative_to(anc).as_posix() or "."
            except ValueError:                      # noqa: PERF203
                break
            if origin != ENV:
                return rel
            return (CANONICAL_CORPUS_NAME if rel == "."
                    else f"{CANONICAL_CORPUS_NAME}/{rel}")
    return c.name
