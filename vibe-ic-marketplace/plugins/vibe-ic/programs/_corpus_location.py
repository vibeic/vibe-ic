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

chip-AGNOSTIC: pure path/git plumbing. No design, PDK, vendor or SKU literal.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

#: Where a caller may point us at a clone of the published-corpus repository.
#:
#: Spelled exactly as `benchmark_evidence_structure_check.CORPUS_ENV`,
#: `tracked_symlink_portability_check.CORPUS_ENV`, `benchmark_evidence_index`
#: and `programs/tests/_published_corpus.CORPUS_ENV` spell it — one name for one
#: thing. Gates that disagree about where the corpus lives will disagree about
#: whether it was checked.
CORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"
BOUND_SHA_ENV = "GATEKEEPER_BENCHMARK_DATA_SHA"

#: Where a TRUSTED PARENT declares which tree this gate is judging.
#:
#: `tools/ci/gate_mutation_fixtures.py` sets it to the fixture subject and
#: `tools/gatekeeper-land.sh` sets it to the candidate; `repo_hygiene_gates.sh`
#: has read it since it was introduced. No PROGRAM read it, which is the whole
#: of vibe-ic#2066 for this seam: a gate that resolves its population from its
#: OWN location answers about the instrument and not about the subject it was
#: handed. Spelled once here so the two seams cannot disagree.
SUBJECT_ENV = "VIBEIC_SUBJECT_ROOT"

#: What the published corpus tree was CALLED while it lived in this repository.
#: The pointer names a clone whose ROOT is that tree, so a population recorded
#: as `benchmark-data/ic` before v1.10.56 is `ic` inside the clone. Baselines
#: record the population they were measured over and refuse to ratchet one
#: against another (vibe-ic#1223), so the two spellings must be reconciled
#: DELIBERATELY and in one place rather than by each gate guessing.
CANONICAL_CORPUS_NAME = "benchmark-data"

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


#: The structural marker that says "this directory is the repository root".
#: `.git` is deliberately NOT the marker: a tarball export, a `git worktree`
#: without its gitdir, and a vendored copy all lack it while still being the
#: tree the gate is about. `vibe-ic-marketplace/` is tracked content, so it is
#: present in every shape of the checkout.
_REPO_MARKER = "vibe-ic-marketplace"


def repo_root(start: Path) -> Optional[Path]:
    """The repository root at or above `start`, or None.

    The same walk `checker_execution_wiring_audit` already does; hoisted here
    so the corpus seam and the root seam cannot disagree about where the
    repository ends.
    """
    start = Path(start).resolve()
    for anc in (start, *start.parents):
        if (anc / _REPO_MARKER).is_dir():
            return anc
    return None


def subject_root() -> Optional[Path]:
    """The tree a trusted parent DECLARED this gate is judging, or None.

    Only an ABSOLUTE path to an existing directory is honoured — the same two
    conditions `tools/ci/repo_hygiene_gates.sh` puts on it, which refuses a
    relative one by name rather than resolving it against a cwd nobody chose.
    An unset, empty, relative or missing value is None, which means "nobody
    declared one" and leaves every caller exactly where it was.
    """
    raw = os.environ.get(SUBJECT_ENV) or ""
    if not raw:
        return None
    cand = Path(raw)
    if not cand.is_absolute():
        return None
    try:
        cand = cand.resolve(strict=True)
    except OSError:
        return None
    return cand if cand.is_dir() else None


def default_named(start: Path, rel: str) -> Path:
    """The in-repo path `rel`, or the LITERAL `rel` when the repo has no such tree.

    WHY THIS EXISTS, AND WHY IT IS BOUNDED (vibe-ic#1710)
    =====================================================
    Three gates spelled this as an UNBOUNDED ancestor walk::

        named = next((b / _DEFAULT_CORPUS_REL for b in here.parents
                      if (b / _DEFAULT_CORPUS_REL).is_dir()),
                     Path(_DEFAULT_CORPUS_REL))

    `Path.parents` does not stop at the repository. It continues into the
    checkout's parent directory, into $HOME, and up to `/`. So the corpus a
    repository gate scanned was decided by whatever happened to sit ABOVE the
    checkout on that machine.

    MEASURED on main a4caccefe, the SAME commit, the SAME host, two clones:

        clone at $HOME/<work>/vibe-ic   (an ancestor, $HOME, carries a
                                         benchmark-data/ checkout)
            test_issue1710_...py -> 15 failed, 27 passed
            and the gate announced: "scanning the corpus at the named root
            ($HOME/benchmark-data/ic); VIBE_IC_BENCHMARK_DATA=<the corpus the
            TEST built> is set and NOT followed"
        clone at /var/tmp/j1710/vibe-ic         (no such ancestor)
            same file -> 42 passed

    Nothing about the repository differed. That is the whole of the reported
    host discrepancy: a gate's verdict moved with the operator's home directory,
    and `resolve()`'s named-root precedence then DECLINED the pointer in favour
    of a tree nobody named.

    The repair is not to give the pointer precedence — that asymmetry is
    deliberate and measured (see the module docstring; letting the pointer win
    outright turned 15 of 21 tests red for every developer who had it set). The
    repair is that the NAMED root must be a fact about the REPOSITORY. Bounded
    here at the repository root, so:

      * a repo that carries `rel` resolves to its own copy, on every host;
      * a repo that does not returns the LITERAL relative `rel`, which is not a
        directory, so `resolve()` follows the pointer and `refuse()` names the
        path that was looked for. Nothing silently becomes a pass.
    """
    subject = subject_root()
    if subject is not None:
        # A DECLARED SUBJECT IS NOT A HINT, IT IS THE QUESTION. When a parent
        # has named the tree under judgement, the answer is about THAT tree and
        # there is no fallback to the tree this file happens to live in: a
        # fallback is how a gate ends up scanning the instrument and reporting
        # it as the candidate. If the subject carries no `rel`, the literal
        # relative path is returned exactly as it is below, so `resolve()`
        # follows the pointer and `refuse()` names what was looked for.
        # MEASURED 2026-09-07 on 8HD-9: with a published corpus present at the
        # repository root, `gate_fixture_discrimination_check` went from 0 to 1
        # non-discriminating pair — `l_doc_field_producer` read the 48 in-tree
        # L-docs in BOTH arms and never opened either subject.
        candidate = subject / rel
        return candidate if candidate.is_dir() else Path(rel)
    root = repo_root(start)
    if root is not None:
        candidate = root / rel
        if candidate.is_dir():
            return candidate
    return Path(rel)


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
        probe = _pr.run(["git", "-C", str(root), "rev-parse",
                                "--show-toplevel"],
                               capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError, _pr.Stalled) as exc:  # noqa: BLE001,E501
        # `_pr.Stalled` is a RuntimeError and `SubprocessError` does not catch
        # it; a git that stopped moving is this branch's subject, not an
        # exception for the caller to discover it has no handler for.
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


#: The opt-in flag MOST callers offer, and the default so every existing caller
#: keeps the message it had.
OPT_IN_FLAG = "--corpus-may-be-absent"


def refuse(gate: str, named: Path, resolved: Path, origin: str,
           may_be_absent: bool, scanned: str,
           opt_in_flag: Optional[str] = OPT_IN_FLAG) -> int:
    """The rc for a corpus that could not be resolved, with the reason printed.

    `scanned` names what this gate would have examined ("published cell(s)",
    "published run tree(s)", "published gate record(s)") so the NO_CORPUS line
    states a zero over a named population rather than a bare silence.

    `opt_in_flag` is the flag THIS caller offers for "this repo need not carry a
    corpus", or None when it offers none. It exists because this seam used to
    name `--corpus-may-be-absent` unconditionally, and vibe-ic#1241 added two
    callers (`ppa_contract_check --corpus`, `ppa_feasibility_check --corpus`)
    that deliberately do NOT have it — the rc 0 NO_CORPUS outcome it buys is a
    gate printing a pass over a population it never opened, which is the one
    thing those gates are wired through this channel to avoid. The message told
    the reader to pass a flag that would exit 2 as a usage error. An instruction
    a reader cannot follow is worse than no instruction: it sends them to debug
    their own invocation instead of the corpus.

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
              f"wrong is a broken configuration, not an absent corpus"
              + (f", and {opt_in_flag} does not excuse it." if opt_in_flag
                 else " and nothing excuses it."), file=sys.stderr)
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
          + (f", or pass {opt_in_flag} if this repo need not carry one."
             if opt_in_flag else
             ". This gate offers no way to call an absent corpus a pass."),
          file=sys.stderr)
    return 2


def corpus_repo_name(root: Path) -> Optional[str]:
    """The repository `root` is a checkout OF, from its own `origin` URL.

    A clone directory can be called anything. `git clone <corpus> /tmp/x` and
    `git clone <corpus> ~/benchmark-data` are the same repository, and the
    only thing on disk that says so is the remote the checkout carries.

    None means "this checkout does not say" — no origin, no git, a git that
    would not answer. Every caller must fall back rather than guess: a
    repository identity that is sometimes absent may narrow a population key,
    never widen one.

    A LABEL, NOT AN ATTESTATION. Anyone who can write a checkout can write its
    remote, so this says which set a count was taken over and never that the
    bytes are trustworthy. What guards a register against a tampered corpus is
    the register's own seal and its may-only-shrink ratchet, and neither of
    those is weakened by naming the population correctly — a mislabelled one
    is strictly worse, because it ratchets two different sets against each
    other in silence.
    """
    try:
        probe = _pr.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                        capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError, _pr.Stalled):  # noqa: BLE001
        return None
    if probe.returncode != 0:
        return None
    url = (probe.stdout or "").strip()
    if not url:
        return None
    # scp-style (`git@host:owner/repo.git`) and URL forms both end in the
    # repository name; take the last path segment either way.
    name = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if name.endswith(".git"):
        name = name[:-len(".git")]
    return name or None


def population_key(corpus: Path, origin: str) -> str:
    """WHICH population a count was taken over.

    THE INTEGER IS MEANINGLESS WITHOUT THE SET IT COUNTED (vibe-ic#1223), and
    after the corpus split the same set has two spellings: `benchmark-data/ic`
    while it lived here, `ic` inside the clone the pointer names. A baseline
    recorded under the first must still ratchet against a sweep of the second —
    they are the same cells — so the two are reconciled here rather than each
    side being left to drift.

    A PATH SPELLING IS NOT THE IDENTITY OF A CORPUS (vibe-ic#1704 follow-on)
    -----------------------------------------------------------------------
    The reconciliation used to be applied ONLY when the corpus arrived through
    `$VIBE_IC_BENCHMARK_DATA`, which made the key a function of HOW the caller
    reached the tree and of what the clone directory happens to be called.
    MEASURED on a host carrying a clone of the published corpus at
    `~/benchmark-data`, against `step_internal_fail_bubble_up_baseline.json`
    (`corpus_population: benchmark-data/ic`, `per_run:
    {<one run>: 1}`):

        --corpus ~/benchmark-data/ic                   -> key `ic`
            rc 2 NOT CHECKED, "measured over 'benchmark-data/ic' and this
            sweep covered 'ic'" — WHILE MEASURING 4 run trees, 4 with
            reports and exactly the 1 recorded finding. The sweep was
            standing on the entry the register names and was refused, so
            that entry could not be EXAMINED by the invocation CI uses.

        VIBE_IC_BENCHMARK_DATA=~/benchmark-data        -> key `benchmark-data/ic`
            rc 0, the same cells, the entry examined.

    Two verdicts over one population, decided by the spelling. So the key is
    now taken from the corpus repository's OWN identity — `origin`'s
    repository name — whenever the checkout says it is a clone of the
    published-corpus repository. That holds across clone directory names and
    across `--corpus` versus the pointer, because it is the same repository
    and it says so itself.

    IT IDENTIFIES THE REPOSITORY, NOT ITS STATE. Two clones at different
    commits are still one population; whether this checkout carries the runs
    the register names is the sweep's own question, and each gate already
    reports a run tree it could not open rather than counting it as repaired.

    When the checkout does NOT say (no origin, no git, an unanswering git)
    the previous rule stands unchanged, so nothing that used to key one way
    keys another for want of a remote.
    """
    c = corpus.resolve()
    for anc in (c, *c.parents):
        if (anc / ".git").exists():
            try:
                rel = c.relative_to(anc).as_posix() or "."
            except ValueError:                      # noqa: PERF203
                break
            canonical = (CANONICAL_CORPUS_NAME if rel == "."
                         else f"{CANONICAL_CORPUS_NAME}/{rel}")
            if corpus_repo_name(anc) == CANONICAL_CORPUS_NAME:
                return canonical
            if origin != ENV:
                return rel
            return canonical
    return c.name
