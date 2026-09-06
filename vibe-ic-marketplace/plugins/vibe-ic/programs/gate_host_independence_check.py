#!/usr/bin/env python3
"""gate_host_independence_check.py — the same commit must give the same verdict.

THE CLASS (vibe-ic#447), and why a SECOND probe was needed
===========================================================
`gate_discloses_denominator_check` catches a gate that PASSes over an empty
tree without saying so. It does NOT catch the other half of the same class: a
gate that examines the WRONG POPULATION and reports confidently about it.

    provenance_output_hash_completeness_check  PASS in a worktree, FAIL in a
                                               working checkout (v1.6.88)
    cross_layer_reference_check                46 cells vs 23, making a
                                               COUNT baseline host-dependent
    l4_systemrdl_export                        299 documents on disk vs 201
                                               tracked (v1.6.91)
    benchmark_evidence_publish                 reproduced by the author IN the
                                               fix for #448, one day after
                                               landing the shared helper that
                                               exists to prevent it (v1.7.13)

Every one walked THIS MACHINE'S DISK where the question was what the PUBLISHED
tree carries. A working checkout keeps untracked run leftovers; a fresh clone
and a `git worktree` do not. So the verdict depended on who ran it — and always
in the same direction: whoever exercises the tool most gets the most false
alarms.

THE PROBE
=========
Run each corpus-scanning gate at the same commit in two environments — once in
the working checkout and once in a throwaway `git worktree` (tracked files
only) — and require the structured process verdict to be IDENTICAL.  Inside
`repo_hygiene_gates.sh`, the checkout arm is the argv-bound machine record the
outer sweep has already produced, so only the fresh arm is launched here.  A
standalone invocation still launches both arms.  A difference is proof the
gate is reading something that is not in the commit.

Proven BOTH ways before landing, which is what separates this from a guess:

  negative control  the two gates fixed at v1.6.90/91 agree exactly
  positive control  restoring `cross_layer_reference_check`'s pre-fix
                    disk-walking `corpus_cells` makes the checkout report an
                    extra finding while the worktree says PASS — caught

WHY NOT A STATIC CHECK
======================
"Programs that rglob a project directory without using `_published_tree`" is 37
of them, and nearly all are RIGHT: a gate reading a RUN directory should read
the disk, because nothing is published yet. There is no static discriminator
for "this walk targets a published tree", so a static rule would fire on
legitimate code — the failure mode that got the orphan-capability detector
(#439) deleted rather than landed. Running it is the discriminator.

THE REFUSAL WAS KEYED ON THE WRONG SIGNAL (vibe-ic#539)
=======================================================
The probe detects a gate reading LOCAL state by giving ONE side that state and
the other side none of it. The working checkout's untracked and ignored
leftovers ARE the stimulus; the fresh worktree is the control. Take the
leftovers away from both sides and the two trees are byte-identical, every gate
agrees by construction, and the PASS measured nothing.

Until #539 this program refused on ANY output from `git status --porcelain`,
which folds together two opposite things:

    MODIFIED TRACKED FILES  the worktree is at HEAD and does not carry the
                            edit, so a difference between the trees says
                            nothing about host-dependence. Genuinely
                            uncheckable — still rc 2.
    UNTRACKED PATHS         here and not in the worktree, which is precisely
                            the condition being probed. The stimulus, not an
                            obstacle.

MEASURED, one toy gate that counts files on disk (the reduced form of
`cross_layer_reference_check`'s 46-cells-against-23), three trees at ONE commit:

    checkout carrying an UNTRACKED leftover   DIRTY_CHECKOUT   defect MISSED
    a fresh worktree of that same commit      PASS             defect MISSED
    checkout carrying an IGNORED leftover     FAIL             defect CAUGHT

Row 2 is the pre-push "run it in a clean worktree instead" habit, and it prints
`[PASS] all N corpus-scanning gate(s) give the same verdict` over a gate that
demonstrably reads local state — two pristine trees cannot exhibit the class.
Row 3 caught it only because an IGNORED file is invisible to `git status`, so
the refusal never fired on it. The refusal was rejecting the stimulus and
admitting it only in the one shape it could not see.

So the repair is not to make the probe tolerate a dirty tree by looking at
LESS. It is to run it where the stimulus lives — the working tree these
leftovers accumulate in, which is the one tree the probe used to refuse — and
to REPORT how much stimulus a run actually had, so that a comparison between
two identical trees can never again be read as coverage. A run with no stimulus
is NOT_CHECKED (rc 2), never a pass.

THE SCRATCH WORKTREE OUTLIVES THE PROBE (measured 2026-08-04)
=============================================================
The comparison needs a second tree, so this program creates one — a `mkdtemp`
plus a `git worktree add`, removed in a `finally`.  A `finally` does not run on
`SIGKILL`, and in one parallel-agent session NINETEEN `/tmp/hostindep-*/wt`
trees were left standing, each still REGISTERED as a worktree of the repository
every agent shares.  `git worktree prune` cannot clear a registration whose
directory still exists, so they do not age out; they accumulate.

The repair is not a better `finally` — there is no code the killed process gets
to run.  It is to make the NEXT run able to prove the previous one is dead and
clean up for it: each scratch directory carries an `flock`'d sidecar, which the
kernel releases on death however the process died, and `_crash_safe_scratch`
reaps every sibling whose lock it can take.  A peer that is still running holds
its lock, is skipped, and is NAMED in the output.

AND THE TWO ARMS SHARED AN ENVIRONMENT, SO ONE WHOLE HALF OF THE CLASS WAS
INVISIBLE (2026-09-05)
======================================================================
The probe above gives one arm a working checkout and the other a fresh worktree.
Both inherit THIS PROCESS'S ENVIRONMENT. So a gate whose verdict is decided by an
environment pointer rather than by the commit agrees with itself perfectly across
the two trees, and this program prints `[PASS] ... give the same verdict` over it.

MEASURED on 2026-09-05 at main `3e3d0a46e`, one tree, two values of one variable::

    VIBE_IC_BENCHMARK_DATA withheld              63x8 census `--check`  rc 0 PASS
    VIBE_IC_BENCHMARK_DATA=<corpus @ 8c4b608a>   63x8 census `--check`  rc 1 stale

Same commit, same tree, same argv, opposite verdicts — and nothing in the argv,
the commit or the report says which environment produced the one you are reading.
That is the same defect this program was written for ("the same commit must give
the same verdict") reached through a different door, and the two-tree comparison
cannot see it by construction: the pointer is on both sides.

THE POINTER ARM
===============
Each probed gate is driven ONE more time, in the fresh worktree, with
`VIBE_IC_BENCHMARK_DATA` toggled to the opposite of whatever this run inherited,
and a gate whose OUTCOME TIER flips between PASS and FAIL is reported
`ENV_POINTER_DEPENDENT_VERDICT`.

THE TIER, AND NOT THE BYTES, and that is the whole of the false-positive story. A
corpus-reading gate legitimately says different things with and without a corpus —
different counts, a different disclosure, a NOT_CHECKED it names — and requiring
its OUTPUT to be identical would report every honest one of them. What no gate may
do is say PASS in one environment and FAIL in the other, because those are the two
answers a caller acts on. rc 2 on either side is the disclosed third state
(`_vacuous_exit`: "I could not look") and is never half of a flip.

NOT_CHECKED WHEN THE POINTER IS NOT BOUND. With no corpus named there is no
"present" environment to construct, and inventing one is not available: the arm
reports how many gates it could drive both ways, and a run that could drive none
says so in the verdict line rather than printing the same green sentence.

COST, disclosed rather than buried: one extra drive per probed gate, and a second
pair only for the gates that flip. On the ~90-gate script that is the same order
as the fresh arm this program already pays for.

chip-AGNOSTIC: it compares process output, nothing else.

FLOW CLASSIFICATION: **BLOCKING**.  A reproducible host-dependent or
non-deterministic gate returns rc 1 and the enclosing hygiene/landing flow must
stop.  An unavailable comparison returns rc 2 as a named NOT_CHECKED state;
only the dated ``run_tolerating_uncheckable`` declaration in the enclosing
dispatcher may bound that refusal.  Neither state is a PASS.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys

import _watchdog
import tempfile
import time
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

import _crash_safe_scratch as _scratch

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# THE SCRIPT IS PARSED IN ONE PLACE. This file used to carry a verbatim copy of
# the other reader's regex, with a comment saying so — and the copy is what let
# one defect hide in two files at once: neither could see a gate whose label
# embeds `$(basename "$(dirname "$_cell")")`, because the label group stopped
# at the inner quote, and neither folded `\` continuations. Fixing that in one
# copy would have left the other still blind and the two readers disagreeing
# about what the script says, which the #539 tests exist to forbid.
#
# THE COPY WAS RE-ADDED ONCE, IN A MERGE, AND THAT IS THE POINT. The crash-safe
# scratch work landed a second `_RUN_RE` here — the very regex this file had
# just stopped carrying — widened by one hand for `run_tolerating_uncheckable`
# while the other hand was rewriting the shared reader. Driven against the
# merged `tools/ci/repo_hygiene_gates.sh`, the regex saw 60 declarations and
# `parse_declarations` saw 63: the three `$_cell` loop gates were invisible to
# it, and `severity=ERROR is consumed` came back truncated at its `\`. The one
# element the regex produced that the shared reader does not is that truncation
# — same label, broken command — so nothing is lost by deleting it, and a
# second copy is exactly how the last defect stayed invisible in both files.
from gate_discloses_denominator_check import (            # noqa: E402
    HOST_INDEPENDENCE_EXCLUDE_RE, parse_declarations)
from gate_process_attestation import (                    # noqa: E402
    argv_sha256, load_jsonl, normalise_line, process_attestation)
from hygiene_shard_plan import load_profile, plan          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

#: Scratch prefix.  UNCHANGED from the leaking version on purpose — the reaper
#: keys on it, so the directories a pre-fix build already left behind are the
#: first thing a fixed run cleans up.
_SCRATCH_PREFIX = "hostindep-"

#: The claim file for one working checkout. Deliberately NOT under
#: `_SCRATCH_PREFIX`: `sweep_abandoned_scratch` reaps that prefix, and a reaper
#: that deletes the lock two live drivers are holding hands them both the
#: checkout at once. Deliberately NOT inside the subject tree either — this
#: program's whole subject is a gate that writes into the tree it measures.
_CLAIM_PREFIX = "vibeic-ckout-claim-"

#: How long a drive waits for the claim before giving up on ATTRIBUTION. It
#: never gives up on the DRIVE: the verdict is this gate's job and the
#: attribution is a side observation, so a busy checkout must cost the second,
#: never the first.
_CLAIM_WAIT_S = 600

#: A gate may DECLARE itself out of this comparison, on the line above its own
#: `run` line, in the script where it is wired:
#:
#:     # host-independence: EXCLUDE — <why>
#:     run "..." "$ROOT" python3 ...
#:
#: WHY A STANDALONE LINE AND NOT A TRAILING COMMENT. `_RUN_RE` here is
#: duplicated verbatim in `gate_discloses_denominator_check`, which drives the
#: same script against a scratch empty tree. A marker appended to the gate line
#: would land inside THAT parser's command capture and be handed to the gate as
#: argv, so the two readers of one script would disagree about what the script
#: says. Anchored at `^\s*run`, neither parser can see a line above.
#:
#: WHY ANY EXCLUSION AT ALL. `sync_image_version --check --require-remote`
#: resolves a tag on a remote registry. This probe runs every gate TWICE and
#: requires the two verdicts to match, so a gate whose answer depends on a
#: network round-trip can differ between the invocations for a reason that is
#: not in the commit — which is how v1.7.92 went red on a gate whose code is
#: perfectly host-independent, and green on the identical commit when re-run.
#: Excluding it deliberately is the alternative to excluding it by luck.
#:
#: FAIL-SAFE BY SHAPE: the directive must be the line IMMEDIATELY above. If it
#: is moved or a line is inserted, the gate is PROBED again — the failure mode
#: is a returning flake, which is visible, not a silent exclusion. Every
#: exclusion is NAMED in the verdict line for the same reason.
_EXCLUDE_RE = HOST_INDEPENDENCE_EXCLUDE_RE


class Gate(NamedTuple):
    """One gate as the CI script declares it."""
    label: str
    cwd_token: str          # `$ROOT` or `$PLUGIN`
    cmd: str
    excluded: Optional[str]  # None = probed; a string = declared reason
    #: Set when the declaration carries something only bash can resolve — a
    #: loop variable, a command substitution. Such a gate is DECLARED here and
    #: cannot be DRIVEN here, and the two are different facts.
    runtime_expansion: Optional[str] = None


class Dirt(NamedTuple):
    """What the working checkout carries that a fresh worktree would not.

    `tracked` invalidates the comparison; `untracked` + `ignored` ARE the
    comparison's stimulus. Splitting them is the whole of #539.
    """
    tracked: List[str]
    untracked: List[str]
    ignored: List[str]
    ignored_reported: bool   # False when git would not report ignored paths

    @property
    def stimulus(self) -> int:
        return len(self.untracked) + len(self.ignored)

    def describe(self) -> str:
        ig = (f"{len(self.ignored)} ignored" if self.ignored_reported
              else "an unreported number of ignored")
        return (f"{len(self.untracked)} untracked + {ig} path(s) present in "
                f"the checkout and not in a fresh worktree")


class Audit(NamedTuple):
    """The probe's result, with its own denominator attached.

    `declared` vs `probed` is load-bearing and used to be absent: the verdict
    line said "all N gate(s)" using the DECLARED count while the loop had
    skipped this program itself, so the sentence was already over-claiming by
    one before any exclusion existed.
    """
    verdict: str
    findings: List[Dict]
    dirt: Optional[Dirt]
    declared: int
    probed: int
    not_probed: List[Tuple[str, str]]   # (label, why)
    #: What the scratch reaper did on the way in. Reported rather than silent:
    #: a sweep that removes another agent's live worktree and says nothing is
    #: the same class of damage as the leak it is fixing, so both the removals
    #: and the SKIPS are named.
    scratch: Optional[Dict] = None
    #: `(label, why)` for every gate driven in the working checkout while this
    #: process could NOT hold an exclusive claim on it. Its checkout-write
    #: attribution was not performed. Carried separately from `findings`
    #: because it is not a defect in the gate and must not colour the verdict:
    #: naming an innocent gate is the harm this list exists to replace.
    unattributed: Optional[List[Tuple[str, str]]] = None
    #: The POINTER ARM's own denominator: `{"bound": <str|"">, "probed": int,
    #: "not_probed": [(label, why)]}`, or None when the result was decided before
    #: any gate ran. Reported rather than implied, because a run that could drive
    #: NO gate both ways has not checked the pointer class at all and must not
    #: print the same sentence as one that checked every gate.
    #:
    #: APPENDED LAST, and that is not cosmetic: every `Audit(...)` in this file is
    #: built POSITIONALLY, so a field inserted above `unattributed` would silently
    #: re-bind the last argument of each of them.
    pointer: Optional[Dict] = None


def corpus_gates(script: Path) -> List[Gate]:
    """Every gate the CI script runs, with any EXCLUDE directive attached.

    The cwd token is LOAD-BEARING and was dropped in a first version: the
    `$PLUGIN`-scoped gates invoke a RELATIVE `programs/x.py`, so running
    them from the repo root made both trees fail to open the file and
    produced 9 identical-error "findings". A probe that reports a defect
    because it could not run the subject is worse than no probe."""
    try:
        lines = script.read_text(errors="replace").splitlines()
    except OSError:
        return []
    # NO FILTER. A first version kept only gates whose argv names
    # `benchmark-data` and parsed exactly ONE of them — most read the corpus
    # from an internal default, so the argv says nothing. Guessing which gates
    # "could" have the defect is how the defect keeps escaping; running all of
    # them costs a couple of minutes and needs no guess.
    #
    # An EXCLUDED gate is still parsed and still counted in `declared`. It
    # leaves the numerator, never the denominator.
    out: List[Gate] = []
    for decl in parse_declarations(script):
        # THE DIRECTIVE BINDS TO THE LINE IMMEDIATELY ABOVE THE `run` LINE.
        # `lineno` is the first PHYSICAL line of the declaration, so a gate
        # written across a `\` continuation still looks one line up from where
        # a reader of the script sees it start. The adjacency rule is the whole
        # fail-safe claim: if the directive drifts, the gate is probed again.
        out.append(Gate(decl.label, decl.cwd_token, decl.cmd,
                        decl.host_independence_exclusion,
                        decl.runtime_expansion))
    return out


def inert_exclusions(script: Path) -> List[Tuple[int, str]]:
    """EXCLUDE directives WRITTEN in the script that exclude NOTHING.

    The adjacency rule above is fail-safe for the gate — drift means the gate
    is probed again — but it is NOT fail-safe for the READER, and that half was
    unenforced. Measured on origin/main 1f3d8d067: THREE directives are written
    (lines 162, 175, 221) and only TWO take effect. The third sits one blank
    line above `run_tolerating_uncheckable "STA engines agree"`, so the parser
    reads the blank line, finds no directive, and probes the gate anyway. A
    reader of the script sees an exclusion that does not exist.

    A declaration that silently does nothing is this repo's recurring shape
    with the polarity reversed: not a check that lies about what it found, but
    a directive that lies about what it governs. It is cheap to detect —
    written count vs effective count — so it is detected.
    """
    try:
        lines = script.read_text(errors="replace").splitlines()
    except OSError:
        return []
    out: List[Tuple[int, str]] = []
    run_head = re.compile(r'^\s*run(?:_\w+)?\s')
    for i, ln in enumerate(lines):
        if not _EXCLUDE_RE.match(ln):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if not run_head.match(nxt):
            out.append((i + 1, ln.strip()[:160]))
    return out


def _expand(cmd: str, root: Path) -> List[str]:
    """The argv THE SHELL BUILDS from this declaration, quoting included.

    SPLITTING ON WHITESPACE IS NOT WHAT THE SHELL DOES, and the difference is
    not cosmetic: this argv is hashed and compared against the record the
    dispatcher wrote from the REAL process, so a declaration carrying a quoted
    argument with a space in it reconstructed here as two words is reported as
    `CHECKOUT_ATTESTATION_WRONG_COMMAND` — the probe accusing the declaration
    of a mismatch it invented itself — and, on the fresh arm, is RUN wrong.

    MEASURED 2026-08-26 on 58514abe8, isolated and reproduced 3/3:

        run "benchmark doctrine sections kept" "$PLUGIN" python3 \
            "$PG/skill_doc_section_present_check.py" \
            --doc skills/open-benchmark-methodology/SKILL.md \
            --marker "RULE 0" --marker "GENERAL-CORE / THIN-ADAPTER"

    became `--marker RULE 0 --marker GENERAL-CORE / THIN-ADAPTER` — seven words
    where the shell passes four arguments. `shlex.split` is the shell's own
    rule, so the quotes are now honoured instead of deleted.
    """
    c = (cmd.replace("$PG", str(root / "vibe-ic-marketplace" / "plugins" /
                                "vibe-ic" / "programs"))
            .replace("$PLUGIN", str(root / "vibe-ic-marketplace" / "plugins" /
                                    "vibe-ic"))
            .replace("$ROOT", str(root)))
    return shlex.split(c)


def _compare_roots(repo_root: Path, wt: Path,
                   wd: Optional[Path] = None) -> Tuple[Path, ...]:
    """Every path that must become `<TREE>` before two arms are compared.

    THE ROOT SET IS HALF OF THE COMPARISON, AND THE TWO SIDES USED DIFFERENT
    ONES. Arm A can be a PRECOMPUTED record written by `_gate_dispatch.sh`,
    which normalises against three roots:

        --root "${ROOT:-$wd}" --root "$wd" [--root "$VIBE_IC_BENCHMARK_DATA"]

    while this probe passed only `(repo_root, wt)`. So a gate that NAMES the
    corpus in its verdict — and the corpus-scanning gates are the ones this
    probe exists to drive — produced `<TREE>/ic` on Arm A and `/corpus/ic` on
    Arm B, from the same bytes. Different text, different `semantic_sha256`,
    reported as a disagreement.

    MEASURED 2026-08-25 on v1.11.77 with the corpus bound at /corpus. Inside
    the hygiene run (Arm A precomputed) the probe reported

        [FAIL] 6 of 92 probed corpus gate(s) ... 6 NON_DETERMINISTIC_VERDICT

    and all SIX were gates whose verdict line contains the corpus path —
    including `published-evidence index honest`, whose four recorded drives
    were all `rc=0 PASS`. Driving BOTH arms from this probe, so that one
    normaliser saw both, returned

        [PASS] all 92 probed corpus-scanning gate(s) ... give the same verdict

    with zero findings. The gates were reproducible the whole time; the two
    rulers were not the same ruler.

    Round 2 is why it surfaced as NON_DETERMINISTIC rather than HOST_DEPENDENT:
    the confirmation drive runs BOTH arms here, so both get this root set, they
    agree, and the shapes differ between rounds. That reading is accurate about
    the evidence and wrong about the cause, which is what a shared vocabulary
    fixes and a suppression would hide.
    """
    roots = [repo_root, wt]
    # AND THE THIRD ROOT THE PRODUCER USED. `_gate_dispatch.sh` normalises
    # against `--root "${ROOT:-$wd}" --root "$wd"`, and `$wd` is `$PLUGIN` for
    # every gate declared to run inside the plugin. `_replace_roots` takes the
    # LONGEST match, so the dispatcher turns an absolute plugin path into
    # `<TREE>/programs/x.py` while a root set of only (repo_root, wt) turns the
    # same bytes into `<TREE>/vibe-ic-marketplace/plugins/vibe-ic/programs/x.py`
    # — a difference in the RULER, reported as a difference in the SUBJECT.
    #
    # MEASURED 2026-08-26 on 58514abe8: `lessons corpus consistency`, the first
    # probed gate to combine cwd `$PLUGIN` with an absolute `$PG/` argv, was
    # reported CHECKOUT_ATTESTATION_WRONG_COMMAND on 3 of 3 isolated runs while
    # both sides held the identical argv.
    if wd is not None:
        roots.append(wd)
    corpus = os.environ.get("VIBE_IC_BENCHMARK_DATA", "").strip()
    if corpus:
        roots.append(Path(corpus))
    return tuple(roots)


def _norm(line: str, repo_root: Path, wt: Path) -> str:
    """One line through the SAME vocabulary the comparison uses."""
    return normalise_line(line, _compare_roots(repo_root, wt))


def _verdict_line(out: str) -> str:
    """The last non-empty line — the verdict a caller reads.

    Pytest's terminal summary appends elapsed wall time.  That value is not a
    verdict and necessarily differs between two otherwise identical runs; the
    outcome/count prefix and process return code remain compared exactly.
    """
    lines = [ln.rstrip() for ln in (out or "").splitlines() if ln.strip()]
    if not lines:
        return "(no output)"
    return re.sub(
        r"\bin\s+\d+(?:\.\d+)?s(?:\s+\(\d+:\d{2}:\d{2}\))?\s*$",
        "in <TIME>s", lines[-1])


def _completed_attestation(label: str, proc: subprocess.CompletedProcess,
                           argv: List[str], repo_root: Path, wt: Path,
                           wd: Optional[Path] = None) -> Dict:
    """The structured verdict a host comparison consumes.

    `wd` is THIS ARM'S working directory, so each arm normalises its own
    `$PLUGIN` prefix exactly as the dispatcher normalised Arm A's — one
    vocabulary on both sides, which is the whole precondition of comparing
    them.
    """
    return process_attestation(
        label, (proc.stdout or "") + (proc.stderr or ""), proc.returncode,
        argv, roots=_compare_roots(repo_root, wt, wd))


def _run_gate(argv: List[str], cwd: Path,
              timeout: int) -> subprocess.CompletedProcess:
    """Run one arm through the same combined stream as the outer dispatcher.

    Separately captured stdout followed by stderr is not the order a human or
    ``2>&1 | tee`` observes.  Python buffering makes that distinction verdict
    bearing: stderr can arrive first while the final stdout PASS flushes at
    exit.  Both arms therefore preserve one combined stream.

    BOUNDED BY NO-PROGRESS, NOT BY A CLOCK.  This module's own subject is that
    the same commit must give the same verdict whoever runs it, and a
    wall-clock bound is precisely a thing that makes the verdict depend on WHO
    RUNS IT.  `TimeoutExpired` is a `SubprocessError`, so a gate that was
    merely SLOW on a loaded host landed in the callers' `GATE_UNRUNNABLE`
    handler and FAILed the probe: the machine's load reported as a property of
    the commit.  The comment at the confirmation drive already named this
    exactly -- "the same tool reported 6/6 clean on one run and 5/6 on the
    next -- a verdict that depends on the machine's load is the very thing this
    probe exists to refuse, occurring in the probe itself".

    `timeout` is now the IDLE tolerance.  A gate whose process tree keeps
    moving runs to completion however long it legitimately takes; one that has
    stopped moving entirely still raises `TimeoutExpired`, so every caller's
    `GATE_UNRUNNABLE` path is untouched -- and that verdict is now honest,
    because "this gate made no progress at all" is a statement about the GATE,
    which is what `GATE_UNRUNNABLE` claims, and not about the host.
    """
    res = _watchdog.run_host_supervised(
        argv, cwd=str(cwd), merge_stderr=True,
        stall_grace_s=float(timeout))
    if res.outcome in ("stalled", "ceiling"):
        # Raised, not returned: a stalled arm has NO verdict, and letting it
        # reach the comparison would invent a difference out of an absence.
        raise subprocess.TimeoutExpired(
            argv, timeout,
            output=(res.out + "\nNO FORWARD PROGRESS: nothing in the process "
                    "tree (output, CPU or I/O) advanced — killed as hung. This "
                    "is NOT a statement that the gate was too slow."))
    return subprocess.CompletedProcess(argv, res.rc, res.out, "")


#: The pointer whose value must not decide a verdict. ONE name, spelled here and
#: consumed by both `_compare_roots` (which already knew the corpus can be bound)
#: and the arm below (which is what makes the binding verdict-visible).
POINTER_ENV = "VIBE_IC_BENCHMARK_DATA"

#: The three answers a caller ACTS on, keyed off the house exit codes. rc 2 is
#: `_vacuous_exit`'s NOT_CHECKED and is deliberately NOT a verdict: a gate that
#: says "I could not look" without a corpus and "PASS" with one has disclosed the
#: difference, which is the honest shape and must never be reported as a defect.
def _tier(rc: int) -> str:
    return {0: "PASS", 1: "FAIL", 2: "NOT_CHECKED"}.get(rc, f"rc={rc}")


def _flips(rc_a: int, rc_b: int) -> bool:
    """Is this a PASS/FAIL flip — the one difference no environment may cause?"""
    return {_tier(rc_a), _tier(rc_b)} == {"PASS", "FAIL"}


def _run_gate_pointer_toggled(argv: List[str], cwd: Path,
                              timeout: int) -> subprocess.CompletedProcess:
    """Drive one arm with `POINTER_ENV` toggled to the opposite of this run's.

    Restored in a `finally` because the loop that calls this keeps driving other
    gates afterwards: a probe that leaks a changed environment into the gates it
    measures next would BE the defect it is looking for.

    The toggle is always pointer-bound -> pointer-withheld and never the reverse.
    Constructing a "present" environment out of nothing would mean inventing a
    corpus, and a comparison against a corpus nobody published is not evidence
    about anything; the unbound case is reported as NOT_CHECKED instead.
    """
    prev = os.environ.pop(POINTER_ENV, None)
    try:
        return _run_gate(argv, cwd, timeout)
    finally:
        # No `assert` here, deliberately. An assertion raised while an exception
        # is unwinding REPLACES that exception, so a self-check in a `finally`
        # can only ever hide the failure a caller needed to see — and `-O`
        # deletes it anyway. The property is pinned by
        # `test_the_pointer_arm_restores_the_environment_it_toggled` instead.
        if prev is not None:
            os.environ[POINTER_ENV] = prev


def pointer_arm_finding(label: str, argv: List[str], cwd: Path,
                        rec_bound: Dict, repo_root: Path, wt: Path,
                        timeout: int) -> Optional[Dict]:
    """One gate, both values of the pointer. A finding, or None.

    CONFIRMED BEFORE IT IS FILED, exactly as the two-tree disagreement above is:
    a flip that does not reproduce is not a property of the commit, and this arm
    drives the same nested pytest sessions the rest of this probe drives, under
    the same load. Paid only on the flipping minority.
    """
    withheld = _run_gate_pointer_toggled(argv, cwd, timeout)
    rec_withheld = _completed_attestation(label, withheld, argv, repo_root, wt,
                                          cwd)
    if not _flips(rec_bound["returncode"], rec_withheld["returncode"]):
        return None
    bound2 = _run_gate(argv, cwd, timeout)
    withheld2 = _run_gate_pointer_toggled(argv, cwd, timeout)
    if not _flips(bound2.returncode, withheld2.returncode):
        # NOT folded into a pass, and NOT filed as pointer dependence either.
        # A gate that will not reproduce its own flip is the same
        # NON_DETERMINISTIC_VERDICT state the two-tree half already names.
        return {
            "gate": label, "kind": "NON_DETERMINISTIC_VERDICT",
            "detail": ("its verdict flipped between PASS and FAIL when "
                       f"{POINTER_ENV} was withheld, and did not flip the same "
                       "way when re-driven, so the difference is not a property "
                       "of the commit. NOT pointer dependence, and NOT a pass"),
            "checkout": f"{POINTER_ENV} bound: "
                        f"{_attestation_summary(rec_bound)}",
            "worktree": f"{POINTER_ENV} withheld: "
                        f"{_attestation_summary(rec_withheld)}",
        }
    return {
        "gate": label, "kind": "ENV_POINTER_DEPENDENT_VERDICT",
        "detail": (
            f"the same commit, the same tree and the same argv give "
            f"{_tier(rec_bound['returncode'])} with {POINTER_ENV} bound and "
            f"{_tier(rec_withheld['returncode'])} with it withheld, on BOTH "
            f"rounds. A caller reading this gate's verdict cannot tell which "
            f"environment produced it, because the pointer is in no argv, in no "
            f"commit and in no report. Either make the gate's comparison "
            f"independent of the pointer, or make it state the provenance it "
            f"measured under and refuse when it cannot reproduce that "
            f"provenance — never let the answer depend on the mount"),
        "checkout": f"{POINTER_ENV} bound: {_attestation_summary(rec_bound)}",
        "worktree": f"{POINTER_ENV} withheld: "
                    f"{_attestation_summary(rec_withheld)}",
    }


def _attestation_summary(rec: Dict, limit: int = 200) -> str:
    findings = rec.get("finding_identities") or []
    named = " | ".join(findings[:3]) if findings else rec["verdict_line"]
    return f"rc={rec['returncode']} {named[:limit]}"


def _load_checkout_attestations(path: Path) -> Dict[str, Dict]:
    records: Dict[str, Dict] = {}
    for rec in load_jsonl(path):
        label = str(rec["label"])
        if label in records:
            raise ValueError(f"duplicate process attestation for {label!r}")
        records[label] = rec
    if not records:
        raise ValueError("the process attestation record is empty")
    return records


def checkout_dirt(repo_root: Path, timeout: int = 600) -> Optional[Dirt]:
    """Split what the checkout carries into the three categories that matter.

    Returns None when git would not answer at all — "I could not look" is its
    own state here too, and must not collapse into "the tree was clean".
    """
    def _status(extra: List[str]) -> Optional[List[str]]:
        try:
            st = _pr.run(
                ["git", "-C", str(repo_root), "status", "--porcelain", *extra],
                capture_output=True, text=True)
        except (OSError, subprocess.SubprocessError):
            return None
        if st.returncode != 0:
            return None
        return [ln for ln in st.stdout.splitlines() if ln.strip()]

    # `traditional` collapses an ignored DIRECTORY into one entry instead of
    # walking into it, which keeps this cheap on a tree carrying large ignored
    # build output. The count is a disclosure, not an inventory.
    lines = _status(["--ignored=traditional"])
    ignored_reported = lines is not None
    if lines is None:                       # older/odd git: fall back
        lines = _status([])
        if lines is None:
            return None
    tracked, untracked, ignored = [], [], []
    for ln in lines:
        (untracked if ln.startswith("??")
         else ignored if ln.startswith("!!")
         else tracked).append(ln)
    return Dirt(tracked, untracked, ignored, ignored_reported)


def _unregister_worktree(scratch: Path) -> None:
    """Drop the git registration an abandoned scratch tree still holds.

    Addressed THROUGH the worktree itself (`git -C <wt> worktree remove <wt>`)
    rather than through the repo this run happens to be probing: a leftover may
    belong to any checkout on the host, and pointing the wrong repository at it
    would fail while looking like it worked.  The directory is what knows who
    owns it.
    """
    wt = scratch / "wt"
    if not wt.exists():
        return
    r = _pr.run_best_effort(["git", "-C", str(wt), "worktree", "remove", "--force",
                             str(wt)], capture_output=True, text=True)
    if r.returncode == 0:
        return
    # A worktree git considers LOCKED refuses a single `--force`. Measured: a
    # run killed mid-`worktree add` left the lock behind, so the very state
    # this reaper exists for is the one that can be locked. `unlock` then
    # retry; if that still fails the directory is removed anyway and the
    # registration is dropped by the `prune` the caller runs — never left
    # standing because one git subcommand was fussy.
    _pr.run_best_effort(["git", "-C", str(wt), "worktree", "unlock", str(wt)],
                        capture_output=True, text=True)
    _pr.run_best_effort(["git", "-C", str(wt), "worktree", "remove", "--force",
                         str(wt)], capture_output=True, text=True)


def _release_scratch(res, repo_root: Path) -> None:
    """The CLEAN path: unregister, unlock, delete.

    Correctness does not depend on reaching it — that is what the reaper is for
    — but a run that exits normally should not leave work for the next one.
    """
    _unregister_worktree(res.path)
    res.release()
    # Only ever removes registrations whose DIRECTORY is gone, so a worktree a
    # concurrent agent is sitting in cannot be pruned by this.
    _pr.run_best_effort(["git", "-C", str(repo_root), "worktree", "prune"],
                        capture_output=True, text=True)


def _setup(verdict: str, kind: str, detail: str, dirt: Optional[Dirt],
           declared: int, scratch: Optional[Dict] = None) -> Audit:
    """A result decided before any gate ran. 0 probed, and it says so."""
    return Audit(verdict,
                 [{"gate": "(setup)", "kind": kind, "detail": detail}],
                 dirt, declared, 0, [], scratch)


def _not_probed_reason(gate: Gate) -> Optional[str]:
    """Why a declaration cannot be driven, shared by serial and parallel mode."""
    if Path(__file__).name in gate.cmd:
        return "this probe itself — it would recurse"
    if gate.excluded is not None:
        return f"EXCLUDED by declaration: {gate.excluded}"
    if gate.runtime_expansion is not None:
        return (
            f"declared inside a shell loop — {gate.runtime_expansion}. Driving "
            "it twice would need the loop's binding, and a fixed substitute "
            "would make both trees identical, so the agreement would prove "
            "nothing")
    return None


def peer_probes_running() -> List[int]:
    """Other live processes running THIS program, by pid.

    Needed only for the transition. A build that predates the lock sidecar
    leaves a scratch directory this reaper cannot attribute, so it falls back
    to age plus a `/proc` scan — and several agents demonstrably run against
    one host, where a probe that has been alive longer than the age threshold
    would be a candidate for deletion at the instant no child of it happens to
    be sitting in the directory. While ANY peer is alive the unlockable
    directories are simply kept; the guess is not made better, it is not made.
    """
    me = Path(__file__).name
    pids: List[int] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return [-1]                     # cannot look -> assume a peer exists
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            cmd = (entry / "cmdline").read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        if me in cmd:
            pids.append(int(entry.name))
    return pids


def sweep_abandoned_scratch(repo_root: Path,
                            tmp_root: Optional[Path] = None,
                            peers: Optional[List[int]] = None) -> Dict:
    """Clean up after every PREVIOUS run of this program that was killed.

    Runs before anything else, and on every exit path including the ones that
    refuse to probe: a checkout too dirty to compare is exactly the state a
    maintainer's tree is in while the leftovers pile up, so a reaper that only
    ran on the happy path would almost never run at all.

    `tmp_root` and `peers` are test seams, and they exist for a reason this
    module is about: a test that drove this against the real `/tmp` would
    create and delete directories other agents' probes are reading, and one
    that depended on no peer being alive would either race them or skip
    whenever the host is busy — which on this host is most of the time.
    """
    if peers is None:
        peers = peer_probes_running()
    rep = _scratch.reap(_SCRATCH_PREFIX, remover=_unregister_worktree,
                        root=tmp_root, reap_unlocked=not peers)
    if rep.reaped:
        # `prune` after the removals, not instead of them: it drops the
        # registrations whose directories this sweep has just deleted, and by
        # construction cannot touch one whose directory still exists.
        _pr.run_best_effort(["git", "-C", str(repo_root), "worktree", "prune"],
                            capture_output=True, text=True)
    return {"reaped": rep.reaped, "live_peers": rep.live,
            "peer_probe_pids": peers,
            "vanished_under_the_sweep": rep.vanished,
            "kept": [{"path": p, "why": w} for p, w in rep.kept]}


def declared_concurrent_lanes() -> int:
    """How many stages the ENCLOSING runner is driving against this checkout.

    `tools/gatekeeper-land.sh` runs `LANE_WIDTH` full-tier lanes — targeted
    tests, the corpus suite, this hygiene tier, the plugin audit —
    CONCURRENTLY IN ONE CHECKOUT, and exports that width here.

    A DECLARATION, not an observation, and for the reason
    `tools/ci/_gate_dispatch.sh:518` already had to write down one level below
    this file: "no tree-only observation can separate a writer from a gate that
    merely overlapped it". The only process that knows how many writers share
    the tree is the one that started them, so it is the one that says.

    ABSENT MEANS ONE, and that direction is chosen rather than defaulted into:
    a standalone run does own its checkout, and it is the shape
    `test_issue1029_the_killer_must_clean_up.py` drives. Reading an absent
    variable as "probably concurrent" would retire that detector everywhere and
    print nothing while doing it — quiet, not fixed.
    """
    raw = os.environ.get("VIBEIC_CHECKOUT_CONCURRENT_LANES", "").strip()
    if not raw:
        return 1
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


class _CheckoutClaim:
    """An EXCLUSIVE claim on writing to one working checkout — or an honest no.

    `_repair_checkout` below attributes a write to a gate and then UNDOES it.
    Both halves are sound only inside a window where this process is the only
    one writing to the tree, and nothing used to establish that window. This
    does, and when it cannot, it says so instead of guessing an author.

    Three states, and the caller must handle all three:

      * ``want=False``  — this loop is about to run NOTHING in the working
        checkout (Arm A came from the outer sweep's record). No write in the
        tree can be ours, so there is no bracket to open and no true positive
        to lose by not opening one.
      * ``held=True``   — an exclusive `flock` is held for the window. Every
        driver in this program takes the same file, so no two of them, and no
        two concurrent invocations on one host, can be inside each other's
        bracket.
      * ``held=False``  — a concurrent window was DECLARED, or another driver
        holds the claim, or the claim file cannot be opened. The drive still
        happens; the ATTRIBUTION does not, and `why` says which of the three it
        was.

    ``held`` IS A RECORD, NOT A LIVE HANDLE, and it stays true after the block
    exits. The caller decides whether to report the gate as unattributed AFTER
    the window closes — there is nowhere else it can — so a `__exit__` that
    reset this to False made every attributed gate report itself as skipped,
    with `why` reading "held". That is the mirror of the false accusation this
    class exists to stop: a clean measurement filed as "I could not look".
    MEASURED at `parallel_audit(jobs=3)` with no attestations, 6 gates, 6 of 6
    wrongly listed. `_fh is None` is what says the lock is released.

    Non-fatal by construction: every failure path here costs an observation,
    never a verdict.
    """

    def __init__(self, repo_root: Path, want: bool,
                 wait_s: float = _CLAIM_WAIT_S,
                 lock_root: Optional[Path] = None) -> None:
        self.repo_root = Path(repo_root)
        self.want = bool(want)
        self.wait_s = wait_s
        self.lock_root = (Path(lock_root) if lock_root is not None
                          else Path(tempfile.gettempdir()))
        self.held = False
        self.why = "not requested"
        self._fh = None

    def _path(self) -> Path:
        key = hashlib.sha256(
            str(self.repo_root.resolve()).encode("utf-8")).hexdigest()[:16]
        return self.lock_root / f"{_CLAIM_PREFIX}{key}.lock"

    def __enter__(self) -> "_CheckoutClaim":
        if not self.want:
            self.why = ("this drive ran no child in the working checkout, so "
                        "no write that appeared in it can be this gate's")
            return self
        lanes = declared_concurrent_lanes()
        if lanes > 1:
            self.why = (
                f"the enclosing runner declared {lanes} lanes sharing this "
                f"checkout (VIBEIC_CHECKOUT_CONCURRENT_LANES), so a write "
                f"seen here may be any of them")
            return self
        try:
            self.lock_root.mkdir(parents=True, exist_ok=True)
            fh = open(self._path(), "a+")          # noqa: SIM115 - held open
        except OSError as exc:
            self.why = f"the claim file could not be opened: {exc}"
            return self
        deadline = time.monotonic() + self.wait_s
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                if time.monotonic() >= deadline:
                    fh.close()
                    self.why = (f"another driver held the claim on this "
                                f"checkout for {self.wait_s:g}s")
                    return self
                time.sleep(0.25)
                continue
            self._fh = fh
            self.held = True
            self.why = "held"
            return self

    def __exit__(self, *exc) -> bool:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            finally:
                self._fh.close()
                self._fh = None
        return False


def _checkout_dirty_paths(repo_root: Path) -> Dict[str, str]:
    """``{path: status}`` for everything git currently reports, or ``{}``.

    No ``--ignored``: `__pycache__` and `.pytest_cache` churn on every drive and
    are not what a killed mutator leaves. Including them would make this fire on
    every gate in every run, and a guard that always fires is one people route
    around.

    An unreadable tree returns ``{}``, which makes `_repair_checkout` a no-op --
    it can then only fail to repair, never repair the wrong thing.
    """
    try:
        r = _pr.run(["git", "-C", str(repo_root), "status",
                            "--porcelain"],
                           capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return {}
    if r.returncode != 0:
        return {}
    out: Dict[str, str] = {}
    for line in (r.stdout or "").splitlines():
        if len(line) > 3:
            out[line[3:].strip()] = line[:2]
    return out


def _path_digest(path: Path) -> Optional[str]:
    """Content digest of one path, or ``None`` when it cannot be read.

    A module-level function rather than an inline `read_bytes` because
    `_repair_checkout` reads the same path TWICE and the whole question is
    whether anything happened in between — a test needs a seam it can make the
    two reads disagree at, and there is no way to race a real second writer
    into that window on purpose.
    """
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _repair_checkout(repo_root: Path, before: Dict[str, str],
                     label: str) -> Tuple[List[str], List[str]]:
    """Undo what THIS drive wrote. Returns ``(repaired, refused)``.

    THE PREMISE, WHICH THE CALLER OWNS. Every sentence below says "the child
    this loop just ran". `git status` is a fact about the TREE and cannot name
    an author, so the difference between two snapshots is this drive's ONLY
    while this process was the only one writing to the tree between them.
    `_CheckoutClaim` is what establishes that, and this function must not be
    called without it — see the two call sites in `audit`.

    AND THE REPAIR IS DESTRUCTIVE, which is why the premise is not optional.
    ``git checkout -- <path>`` on a file this process did not write DISCARDS
    whatever the real writer was in the middle of doing. Under
    `gatekeeper-land.sh`'s `LANE_WIDTH=4` that is another lane's in-flight
    work, reverted underneath it while it runs. A false accusation is
    recoverable by reading; that is not.

    THE BOUNDARY, because an over-eager repair here would destroy a
    maintainer's work in order to tidy up after a gate:

      * a TRACKED path that was pristine before and is modified after -- the
        difference was made by the child this loop just ran, so
        ``git checkout -- <path>`` undoes that and provably nothing else.
        REPAIRED.
      * a path that was ALREADY dirty before the drive -- somebody's in-flight
        work, possibly with the gate's write layered on top. Nothing here can
        separate the two, so it is NAMED and left exactly as it is. REFUSED.
      * an UNTRACKED path that appeared -- a gate writing its own report beside
        the code is doing the thing the corpus guard's message recommends.
        Named, never deleted: this function's licence is to undo a modification
        it can prove it caused, not to remove files.
    """
    after = _checkout_dirty_paths(repo_root)
    # THE CONTENT AS THE DRIVE LEFT IT, read once here and once again in the
    # instant before the destructive step below.
    #
    # `docs/capture/2026-08-22-jcapsha/evidence/concurrent_repair/MEASURED.md`
    # prescribes this after watching this function delete a live editor's work
    # twice: "capture it again immediately before each `checkout --` and refuse
    # the repair if the path's content changed a second time, because a file
    # being written twice inside one drive is not a file only the child
    # touched." It NARROWS the window rather than closing it — a writer that
    # lands between the two reads is still missed, which is why the CALLER's
    # exclusive claim is the primary defence and this is the second one.
    settled = {p: _path_digest(repo_root / p) for p in after}
    repaired: List[str] = []
    refused: List[str] = []
    for path, status in sorted(after.items()):
        if path in before:
            continue
        if status.strip() == "??":
            refused.append(f"{path} (untracked -- named, not deleted)")
            continue
        if _path_digest(repo_root / path) != settled.get(path):
            refused.append(f"{path} (written AGAIN after the drive ended, so "
                           f"this process is not its only writer)")
            continue
        r = _pr.run_best_effort(
            ["git", "-C", str(repo_root), "checkout", "--", path],
            capture_output=True, text=True)
        if r.returncode == 0 and path not in _checkout_dirty_paths(repo_root):
            repaired.append(path)
        else:
            refused.append(f"{path} (restore failed)")
    for path in sorted(before):
        if path in after and after[path] != before[path]:
            refused.append(f"{path} (already dirty before this drive)")
    return repaired, refused


def audit(repo_root: Path, timeout: int = 600,
          tmp_root: Optional[Path] = None,
          checkout_attestations: Optional[Path] = None,
          only_labels: Optional[Set[str]] = None,
          include_script_findings: bool = True,
          pointer_arm: bool = False) -> Audit:
    """`tmp_root` overrides where the scratch lives (default: the system temp).

    A caller that needs to OBSERVE what this run left behind cannot do it in
    the shared temp: on a busy host a peer's directory appears there mid-run
    and is indistinguishable from a leak of our own. Pointing this at a private
    root is what makes "left nothing behind" a statement about THIS run.
    """
    scratch = sweep_abandoned_scratch(repo_root, tmp_root=tmp_root)
    script = repo_root / "tools" / "ci" / "repo_hygiene_gates.sh"
    gates = corpus_gates(script)
    if only_labels is not None:
        available = {g.label for g in gates}
        unknown = sorted(only_labels - available)
        if unknown:
            return _setup(
                "SELECTION_UNAVAILABLE", "SELECTION_UNAVAILABLE",
                "parallel worker was assigned label(s) the gate script does "
                "not declare: " + ", ".join(unknown[:6]), None,
                len(only_labels), scratch)
        gates = [g for g in gates if g.label in only_labels]
    declared = len(gates)
    if not gates:
        # This program's own denominator: reporting clean over an empty gate
        # list is the defect it exists to catch, one level up.
        return Audit("NOTHING_SCANNED", [], None, 0, 0, [], scratch)

    checkout_records: Optional[Dict[str, Dict]] = None
    if checkout_attestations is not None:
        try:
            checkout_records = _load_checkout_attestations(
                Path(checkout_attestations))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _setup(
                "ATTESTATION_UNAVAILABLE", "ATTESTATION_UNAVAILABLE",
                "the outer hygiene run supplied no complete machine record "
                f"for its checkout arm: {exc}", None, declared, scratch)

    dirt = checkout_dirt(repo_root, timeout)
    if dirt is None:
        return _setup("STATUS_UNAVAILABLE", "STATUS_UNAVAILABLE",
                      "`git status` did not answer, so the checkout could not "
                      "be characterised and no comparison was attempted",
                      None, declared, scratch)

    # MODIFIED TRACKED FILES make the comparison meaningless: the worktree is
    # at HEAD, so every uncommitted edit shows up as a "difference" that has
    # nothing to do with the defect being probed. Measured while building this
    # — an in-progress version of THIS program made the chip-agnostic guard
    # report 1241 files against the worktree's 1240 and flagged itself as an
    # unwired checker. Reporting those as host-dependence would be a probe that
    # fires on its own author.
    #
    # Refused rather than filtered: "the comparison could not be made" is its
    # own state and must not be dressed up as a clean one.
    #
    # UNTRACKED paths used to be refused by this same branch and are not
    # refused now — see the module docstring. They are the stimulus.
    if dirt.tracked:
        return _setup(
            "DIRTY_CHECKOUT", "DIRTY_CHECKOUT",
            f"{len(dirt.tracked)} TRACKED path(s) modified/staged; the "
            f"worktree is at HEAD so each would read as a difference that is "
            f"about the edit, not about the gate. Commit or stash them and the "
            f"probe runs — untracked leftovers no longer block it "
            f"({len(dirt.untracked)} present). First few: "
            + ", ".join(x[3:][:40] for x in dirt.tracked[:4]),
            dirt, declared, scratch)

    findings: List[Dict] = []
    not_probed: List[Tuple[str, str]] = []
    #: THE POINTER ARM's denominator. `bound` is what this run inherited; the arm
    #: can only toggle bound -> withheld, so an unbound run drives no pointer arm
    #: at all and the verdict line has to say so instead of reading as coverage.
    #: OFF BY DEFAULT AT THIS ENTRY POINT, and that is not an escape hatch: `main`
    #: passes True, so the PROGRAM always runs it and no CLI flag turns it off. What
    #: the default protects is `audit()`'s DRIVE COUNT, which two tests pin and which
    #: this arm would otherwise make a function of the ambient pointer:
    #:
    #:   test_the_reproduce_step_costs_nothing_when_the_arms_AGREE
    #:       "an agreeing gate was driven 3 times, not 2"
    #:   test_the_outer_checkout_attestation_replaces_the_duplicate_arm_A
    #:       "the host probe reran checkout Arm A instead of consuming the exact
    #:        outer process attestation"
    #:
    #: MEASURED on 2026-09-06: both are green with the pointer withheld and RED with
    #: it bound, at ONE commit, and NEITHER test mentions the pointer. Driving a third
    #: time whenever a pointer happens to be bound would turn two
    #: environment-INDEPENDENT tests into environment-DEPENDENT ones -- this program's
    #: own subject, introduced by the thing that detects it. The arm is therefore
    #: something a caller ASKS for, never something the environment switches on.
    pointer_bound = (os.environ.get(POINTER_ENV, "").strip()
                     if pointer_arm else "")
    pointer_probed = 0
    pointer_not_probed: List[Tuple[str, str]] = []
    #: Gates driven in the working checkout WITHOUT an exclusive claim on it.
    #: Their checkout-write attribution was not performed and is reported by
    #: name — "I could not look" is a state of its own, never a clean zero.
    unattributed: List[Tuple[str, str]] = []
    if include_script_findings:
        for lineno, text in inert_exclusions(script):
            findings.append({
                "gate": f"(script line {lineno})", "kind": "INERT_EXCLUSION",
                "detail": ("an EXCLUDE directive is written here but is not the "
                           "line IMMEDIATELY above a `run` line, so it excludes "
                           "NOTHING — the script says one thing and the parser "
                           "reads another. Move it flush against its `run` line, "
                           "or delete it."),
                "checkout": text, "worktree": "-"})
    # A LOCKED scratch directory, not a bare `mkdtemp`. The lock is what a later
    # run reads to decide this one is dead; the `finally` below is the tidy
    # path, and the reaper is the one that holds under `SIGKILL`.
    res, _ = _scratch.reserve(_SCRATCH_PREFIX,
                              remover=_unregister_worktree,
                              root=tmp_root)
    wt = res.path / "wt"
    try:
        r = _pr.run(
            ["git", "-C", str(repo_root), "worktree", "add", "-q",
             "--detach", str(wt), "HEAD"],
            capture_output=True, text=True)
        if r.returncode != 0:
            # NEVER a silent pass — "I could not look" is its own state.
            return _setup("WORKTREE_UNAVAILABLE", "WORKTREE_UNAVAILABLE",
                          (r.stderr or r.stdout or "").strip()[:300],
                          dirt, declared, scratch)

        plugin_rel = Path("vibe-ic-marketplace") / "plugins" / "vibe-ic"
        for label, wd_tok, cmd, excluded, templated in gates:
            # NEVER probe ITSELF. The gate list is unfiltered by design, so it
            # contains this program — and running it inside the worktree runs
            # it again, which creates another worktree, and so on.
            #
            # This shipped and CI caught it. Locally it was MASKED: the working
            # tree is permanently dirty, so the inner invocation returned
            # DIRTY_CHECKOUT immediately and the recursion never happened. CI
            # checks out clean, recursed, and hit the per-gate timeout — which
            # was ALSO unhandled, so the probe died with a traceback instead of
            # reporting. "It passed on my machine" was true and worthless.
            #
            # The skip is RECORDED, not silent. It used to be a bare `continue`
            # while the verdict line went on to say "all <declared> gate(s)" —
            # a denominator this program's whole subject is not over-claiming.
            reason = _not_probed_reason(Gate(
                label, wd_tok, cmd, excluded, templated))
            if reason is not None:
                not_probed.append((label, reason))
                continue
            # A GATE DECLARED INSIDE A LOOP CANNOT BE DRIVEN HERE, and saying
            # so is the only honest option available. This probe's evidence is
            # that ONE tree carries something the other does not; binding the
            # loop variable to some fixed path would hand BOTH invocations the
            # same input, they would agree by construction, and the agreement
            # would be counted as coverage — the NO_STIMULUS defect #539 exists
            # to refuse, reintroduced one gate at a time.
            #
            # It stays in `declared`. Before v1.9.78 the parser could not see
            # these lines at all, so the three loop gates were absent from the
            # denominator AND from this list: the verdict named neither, and a
            # reader had no way to tell they existed.
            ca = repo_root if wd_tok == "$ROOT" else repo_root / plugin_rel
            cb = wt if wd_tok == "$ROOT" else wt / plugin_rel
            # THE KILLER CLEANS UP (vibe-ic#1029, same family).
            #
            # ARM A runs in THE WORKING CHECKOUT, and `subprocess.run(timeout=)`
            # on expiry calls `Popen.kill()` -- SIGKILL. A killed process runs
            # no `finally` and no signal handler, so a gate that was inside its
            # own mutation window when the bound landed leaves the mutation in
            # the tree, and this loop then filed `GATE_UNRUNNABLE` and carried
            # on. Everything declared after it measured the mutation.
            #
            # MEASURED 2026-08-12, reproducing a real landing run on .120
            # (candidate stack h1c, `/home/<your-user>/_pg_h1c`) byte for byte:
            #
            #   parent caught TimeoutExpired after 75s
            #   porcelain AFTER: 1
            #    M programs/phase3_one_shot_runner.py
            #   -    return _detect_pdk(project, override="sky130A")
            #   +    return _detect_pdk(project, override="nangate45")
            #
            # `an argued direction is pinned` needs 543 s here against the
            # 600 s bound, and `phase3_one_shot_runner.py:8414` is the LAST
            # site it processes in sort order -- so it is the site holding a
            # mutation when the bound lands, which is exactly the file .120 was
            # left carrying.
            #
            # WHY THE FIX IS HERE AND NOT IN THE KILLED GATE. Its `finally`
            # already works: an exception raised mid-pin restores the file
            # byte-identically (measured). SIGTERM is handled too, once #1090
            # lands. SIGKILL cannot be caught by anybody -- so the only process
            # still alive to undo the write is THIS ONE, the one that sent it.
            drive_exc: Optional[BaseException] = None
            # A DECLARATION THE SHELL'S OWN SPLITTER CANNOT READ is not a
            # pass and not a traceback: it gets the state a gate that cannot
            # be driven already has, so the label stays named in the report.
            try:
                argv_a = _expand(cmd, repo_root)
                argv_b = _expand(cmd, wt)
            except ValueError as exc:
                findings.append({
                    "gate": label, "kind": "GATE_UNRUNNABLE",
                    "detail": f"its declaration does not split into shell "
                              f"words, so the argv it really runs is unknown: "
                              f"{type(exc).__name__}: {str(exc)[:160]}",
                    "checkout": "-", "worktree": "-"})
                continue
            rec_a: Optional[Dict] = None
            rec_b: Optional[Dict] = None
            if checkout_records is not None:
                rec_a = checkout_records.get(label)
                if rec_a is None:
                    findings.append({
                        "gate": label,
                        "kind": "CHECKOUT_ATTESTATION_MISSING",
                        "detail": ("the outer hygiene run supplied no complete "
                                   "process record for this declared gate; the "
                                   "fresh arm was not run because there is "
                                   "nothing trustworthy to compare it with"),
                        "checkout": "NORECORD", "worktree": "NOT RUN"})
                    continue
                expected_argv = argv_sha256(
                    argv_a, roots=_compare_roots(repo_root, wt, ca))
                if rec_a.get("argv_sha256") != expected_argv:
                    findings.append({
                        "gate": label,
                        "kind": "CHECKOUT_ATTESTATION_WRONG_COMMAND",
                        "detail": ("the outer record belongs to different "
                                   "argv than the gate declaration now being "
                                   "compared; label equality is not evidence"),
                        "checkout": str(rec_a.get("argv_sha256", "NORECORD")),
                        "worktree": expected_argv})
                    continue
            # THE BRACKET IS EVIDENCE ONLY WHILE ITS PREMISE HOLDS, and the
            # premise is `_repair_checkout`'s own first line: "undo what THIS
            # drive wrote". Two things must be true for a write seen between
            # the two snapshots to be THIS gate's, and neither was checked.
            #
            #   1. THIS LOOP RAN A CHILD IN THE WORKING CHECKOUT AT ALL. Under
            #      the wiring this gate actually ships with — `--jobs 8` with
            #      `GATE_DISPATCH_ATTESTATION_FILE` set, `repo_hygiene_gates.sh
            #      :2608` — Arm A is the record the outer sweep ALREADY
            #      produced and is not re-run, so the only child driven here
            #      runs in `wt`. The bracket then watched the working checkout
            #      across ~40 min while nothing of ours wrote to it: every path
            #      it could see was somebody else's, and every finding it could
            #      file was false. Closing it loses no true positive, because
            #      on that path there is none to lose.
            #
            #   2. NOBODY ELSE IS DRIVING THE SAME CHECKOUT. `gatekeeper-land
            #      .sh:112` runs `LANE_WIDTH=4` full-tier lanes — targeted
            #      tests, the corpus suite, this hygiene tier, the plugin audit
            #      — CONCURRENTLY IN ONE CHECKOUT. A write by the targeted lane
            #      lands inside this bracket and is charged to whichever gate
            #      this probe happened to be driving. That is how
            #      `3 GATE_CORRUPTED_CHECKOUT` appeared on one host and not
            #      another and was briefly attributed to a landing batch that
            #      had nothing to do with it — the detector named whoever was
            #      standing there.
            #
            # `tools/ci/_gate_dispatch.sh:518-537` settled exactly this one
            # level down and in the same words: "no tree-only observation can
            # separate a writer from a gate that merely overlapped it. The
            # choice is therefore between naming the wrong gate and running the
            # watched gates one at a time." `gatekeeper-land.sh:1556` reaches
            # the same place from the other side — a write inside the
            # concurrent window re-runs that window SERIALLY "so the write is
            # attributed to a stage rather than to an overlap".
            #
            # So: hold an EXCLUSIVE claim for the window, and when it cannot be
            # had, DRIVE ANYWAY AND DO NOT ATTRIBUTE. The gates still get their
            # two-tree verdict — that is this program's subject and it is
            # untouched — and the run names the gates whose checkout-write
            # attribution was skipped instead of filing an author it cannot
            # support.
            with _CheckoutClaim(repo_root, want=rec_a is None) as claim:
                before_dirty = (_checkout_dirty_paths(repo_root)
                                if claim.held else None)
                try:
                    if rec_a is None:
                        a = _run_gate(argv_a, ca, timeout)
                        rec_a = _completed_attestation(
                            label, a, argv_a, repo_root, wt, ca)
                    b = _run_gate(argv_b, cb, timeout)
                    rec_b = _completed_attestation(
                        label, b, argv_b, repo_root, wt, cb)
                except (OSError, subprocess.SubprocessError) as exc:
                    drive_exc = exc
                # ALWAYS, not only on the exception path. A gate that writes
                # into the checkout while EXITING CLEANLY corrupts the
                # comparison just as thoroughly, and would otherwise be
                # invisible here.
                repaired, refused = (
                    _repair_checkout(repo_root, before_dirty, label)
                    if before_dirty is not None else ([], []))
            if claim.want and not claim.held:
                unattributed.append((label, claim.why))
            if repaired or refused:
                findings.append({
                    "gate": label, "kind": "GATE_CORRUPTED_CHECKOUT",
                    "detail": (
                        "this gate left the WORKING CHECKOUT modified while "
                        "being driven"
                        + (f" (killed: {type(drive_exc).__name__})"
                           if drive_exc is not None
                           else " (it exited normally)")
                        + ". Every gate declared after it would have measured "
                          "that. "
                        + (f"Restored: {', '.join(repaired)}. "
                           if repaired else "")
                        + (f"REFUSED to touch (dirty before this run): "
                           f"{', '.join(refused)}. " if refused else "")),
                    "checkout": "modified", "worktree": "-"})
            if drive_exc is not None:
                # A gate that cannot be driven is NOT host-dependence, and it
                # is NOT a clean result either. It gets its own state rather
                # than a traceback that kills the whole probe.
                findings.append({
                    "gate": label, "kind": "GATE_UNRUNNABLE",
                    "detail": f"could not be driven twice: "
                              f"{type(drive_exc).__name__}: "
                              f"{str(drive_exc)[:160]}",
                    "checkout": "-", "worktree": "-"})
                continue
            # NORMALISE THE TREE PATH OUT before comparing. A gate that echoes
            # its own root — `marketplace_version_sync_check` prints the
            # manifest paths it read — differs between the two trees for a
            # reason that has nothing to do with what it EXAMINED.
            #
            # Caught by this probe's first genuine run: CI reported it
            # HOST_DEPENDENT while both sides said "PASS: 2 manifest(s), 2
            # plugin entr(ies) — all versions in sync". A comparison that
            # reports a difference which is not one is the same defect class
            # this probe exists to find, in the probe itself.
            #
            # A REAL difference — a count, a verdict word, a finding — still
            # differs after this, so the check is not weakened.
            assert rec_a is not None and rec_b is not None
            # THE POINTER ARM. Same tree, same argv, the OTHER value of the one
            # variable both arms above inherited — see the module docstring. It is
            # driven in the fresh worktree because that is the arm this program
            # always launches itself: Arm A may be a precomputed record, and an
            # environment toggle proves nothing against a record produced under an
            # environment this process did not control.
            if pointer_bound:
                try:
                    pf = pointer_arm_finding(label, argv_b, cb, rec_b,
                                             repo_root, wt, timeout)
                except (OSError, subprocess.SubprocessError) as exc:
                    # NAMED, never counted clean, and never filed as a finding: a
                    # gate that could not be driven a third time is not evidence
                    # that its verdict depends on the pointer.
                    pointer_not_probed.append(
                        (label, f"could not be driven with {POINTER_ENV} "
                                f"withheld: {type(exc).__name__}: "
                                f"{str(exc)[:160]}"))
                else:
                    pointer_probed += 1
                    if pf is not None:
                        findings.append(pf)
            va, vb = rec_a["verdict_line"], rec_b["verdict_line"]
            if rec_a["semantic_sha256"] != rec_b["semantic_sha256"]:
                # A DIFFERENCE MUST REPRODUCE TO BE EVIDENCE (vibe-ic#1029).
                #
                # Measured on `3febf537`, this probe reported:
                #
                #   [HOST_DEPENDENT_VERDICT] 63x8 census freshness
                #     checkout: rc=1 AssertionError: the outcome run for
                #               test_matrix_d7_outputs_list_complete.py did not
                #               finish within 60s
                #     worktree: rc=0 [PASS] 63x8 census fresh: 504 cells ...
                #
                # The arms did not disagree about the SUBJECT. One ran out of
                # wall clock: `_OUTCOME_TIMEOUT_S = 60` bounds an inner pytest,
                # and this probe drives 66 gates twice, so the checkout arm is
                # the one under load. The same tool reported 6/6 clean on one
                # run and 5/6 on the next — a verdict that depends on the
                # machine's load is the very thing this probe exists to refuse,
                # occurring in the probe itself. That is the same shape as the
                # `_norm` fix above: a reported difference which is not one.
                #
                # `TimeoutExpired` raised HERE is already GATE_UNRUNNABLE. The
                # gap is a gate that enforces its OWN deadline and therefore
                # RETURNS rc=1 with a message — indistinguishable, to a single
                # comparison, from a real verdict.
                #
                # The discriminator is NOT the text of the message; deciding a
                # tier by grepping prose is the defect `_vacuous_exit` was
                # written to end. It is REPRODUCIBILITY. A gate reading local
                # state disagrees on every round, because the leftovers are
                # still there. A gate that ran out of clock does not.
                #
                # Paid ONLY on the disagreeing minority: the agreeing majority
                # is still driven exactly twice, which matters at ~44 min.
                # SAME PREMISE, SAME CLAIM. The confirmation drive DOES run
                # Arm A in the working checkout even when the first round read
                # Arm A out of the outer record, so unlike the main path there
                # is a real bracket to open here — but only while this process
                # is the only one writing to the tree.
                retry_exc: Optional[BaseException] = None
                with _CheckoutClaim(repo_root, want=True) as retry_claim:
                    retry_before = (_checkout_dirty_paths(repo_root)
                                    if retry_claim.held else None)
                    try:
                        a2 = _run_gate(argv_a, ca, timeout)
                        b2 = _run_gate(argv_b, cb, timeout)
                    except (OSError, subprocess.SubprocessError) as exc:
                        retry_exc = exc
                    retry_repaired, retry_refused = (
                        _repair_checkout(repo_root, retry_before, label)
                        if retry_before is not None else ([], []))
                if not retry_claim.held:
                    unattributed.append((label, retry_claim.why))
                if retry_repaired or retry_refused:
                    findings.append({
                        "gate": label, "kind": "GATE_CORRUPTED_CHECKOUT",
                        "detail": ("the confirmation drive modified the "
                                   "working checkout. Restored: "
                                   + (", ".join(retry_repaired) or "none")
                                   + ". Refused: "
                                   + (", ".join(retry_refused) or "none")),
                        "checkout": "modified", "worktree": "-"})
                if retry_exc is not None:
                    findings.append({
                        "gate": label, "kind": "GATE_UNRUNNABLE",
                        "detail": f"disagreed once, then could not be re-driven "
                                  f"to confirm it: {type(retry_exc).__name__}: "
                                  f"{str(retry_exc)[:160]}",
                        "checkout": _attestation_summary(rec_a),
                        "worktree": _attestation_summary(rec_b)})
                    continue
                rec_a2 = _completed_attestation(
                    label, a2, argv_a, repo_root, wt, ca)
                rec_b2 = _completed_attestation(
                    label, b2, argv_b, repo_root, wt, cb)
                va2, vb2 = rec_a2["verdict_line"], rec_b2["verdict_line"]
                round2_differs = (
                    rec_a2["semantic_sha256"] != rec_b2["semantic_sha256"])
                same_shape = (
                    round2_differs
                    and (rec_a["semantic_sha256"], rec_b["semantic_sha256"])
                    == (rec_a2["semantic_sha256"],
                        rec_b2["semantic_sha256"]))
                if same_shape:
                    findings.append({
                        "gate": label, "kind": "HOST_DEPENDENT_VERDICT",
                        "detail": ("the same commit gives different answers in "
                                   "a working checkout and a fresh worktree, "
                                   "and does so on BOTH rounds, so the gate is "
                                   "reading something that is not in the commit "
                                   "— almost always untracked run leftovers"),
                        "checkout": _attestation_summary(rec_a),
                        "worktree": _attestation_summary(rec_b),
                    })
                else:
                    # NOT folded into a pass. A gate that cannot reproduce its
                    # own verdict is not usable evidence — it is a DIFFERENT
                    # defect from host dependence, and naming it as host
                    # dependence sends the reader to the wrong repair.
                    findings.append({
                        "gate": label, "kind": "NON_DETERMINISTIC_VERDICT",
                        "detail": ("the two arms disagreed once and did not "
                                   "disagree the same way when reran, so the "
                                   "difference is not a property of the commit "
                                   "— typically an inner wall-clock bound met "
                                   "under this probe's own load. NOT host "
                                   "dependence, and NOT a pass: a gate whose "
                                   "verdict is not reproducible cannot be used "
                                   "as evidence by anything downstream"),
                        "checkout": _attestation_summary(rec_a)
                                    + "  || second run "
                                    + _attestation_summary(rec_a2, 120),
                        "worktree": _attestation_summary(rec_b)
                                    + "  || second run "
                                    + _attestation_summary(rec_b2, 120),
                    })
    finally:
        _release_scratch(res, repo_root)

    probed = declared - len(not_probed)
    pointer = {"bound": pointer_bound, "probed": pointer_probed,
               "not_probed": [list(x) for x in pointer_not_probed]}
    if findings:
        return Audit("FAIL", findings, dirt, declared, probed, not_probed,
                     scratch, unattributed, pointer)
    # NO STIMULUS IS NOT A PASS (#539). Every gate agreeing across two trees
    # that carry the same bytes is arithmetic, not evidence: the leftovers this
    # probe detects a gate READING were absent from both sides, so the run had
    # nothing it could have detected. Reported at the rc-2 vacuous tier — the
    # `_vacuous_exit` convention — so a consumer sees NOT CHECKED rather than a
    # pass, and so the one configuration this probe is blind in announces
    # itself instead of printing the same green sentence as a real run.
    #
    # rc 2 and not rc 1: nothing is WRONG with the tree or the gates, and a
    # permanently red gate is a gate that gets skipped. `--ignored` unreported
    # keeps the PASS: we cannot then prove the stimulus was zero, and inventing
    # a NOT_CHECKED out of an unknown is the mirror of inventing a pass.
    if dirt is not None and dirt.ignored_reported and dirt.stimulus == 0:
        return Audit("NO_STIMULUS", [], dirt, declared, probed, not_probed,
                     scratch, unattributed, pointer)
    return Audit("PASS", findings, dirt, declared, probed, not_probed,
                 scratch, unattributed, pointer)


def _audit_doc(res: Audit, selected: Optional[List[str]] = None) -> Dict:
    """Stable machine record used by both a caller and parallel workers."""
    return {
        "verdict": res.verdict,
        "gates_declared": res.declared,
        "gates_probed": res.probed,
        "selected_labels": sorted(selected or []),
        "not_probed": [{"gate": g, "why": w} for g, w in res.not_probed],
        "not_attributed": [{"gate": g, "why": w}
                           for g, w in (res.unattributed or [])],
        "pointer_arm": res.pointer,
        "scratch_sweep": res.scratch,
        "stimulus": (None if res.dirt is None else {
            "untracked": len(res.dirt.untracked),
            "ignored": len(res.dirt.ignored),
            "ignored_reported": res.dirt.ignored_reported}),
        "findings": res.findings,
    }


def precomputed_audit(repo_root: Path, checkout_attestations: Path,
                      fresh_attestations: Path, timeout: int = 600) -> Audit:
    """Compare concurrently-produced Arm A/B process records.

    The records were emitted by the same dispatcher command in two trees; no
    verdict is reconstructed from prose.  Any missing, duplicate, wrong-command
    or semantic mismatch is a finding/refusal.  This is the pipelined common
    path: Arm B no longer waits for the last Arm-A gate before it starts.
    """
    scratch = sweep_abandoned_scratch(repo_root)
    script = repo_root / "tools" / "ci" / "repo_hygiene_gates.sh"
    gates = corpus_gates(script)
    declared = len(gates)
    if not gates:
        return Audit("NOTHING_SCANNED", [], None, 0, 0, [], scratch)
    dirt = checkout_dirt(repo_root, timeout)
    if dirt is None:
        return _setup("STATUS_UNAVAILABLE", "STATUS_UNAVAILABLE",
                      "`git status` did not answer", None, declared, scratch)
    if dirt.tracked:
        return _setup("DIRTY_CHECKOUT", "DIRTY_CHECKOUT",
                      f"{len(dirt.tracked)} tracked path(s) are modified",
                      dirt, declared, scratch)
    try:
        arm_a = _load_checkout_attestations(checkout_attestations)
        arm_b = _load_checkout_attestations(fresh_attestations)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _setup(
            "ATTESTATION_UNAVAILABLE", "ATTESTATION_UNAVAILABLE",
            f"a pipelined arm has no complete machine record: {exc}", dirt,
            declared, scratch)

    findings: List[Dict] = []
    not_probed: List[Tuple[str, str]] = []
    for lineno, text in inert_exclusions(script):
        findings.append({
            "gate": f"(script line {lineno})", "kind": "INERT_EXCLUSION",
            "detail": "an EXCLUDE directive is written but excludes nothing",
            "checkout": text, "worktree": "-"})
    probed = 0
    for gate in gates:
        reason = _not_probed_reason(gate)
        if reason is not None:
            not_probed.append((gate.label, reason))
            continue
        probed += 1
        a = arm_a.get(gate.label)
        b = arm_b.get(gate.label)
        if a is None or b is None:
            findings.append({
                "gate": gate.label, "kind": "PIPELINE_RECORD_MISSING",
                "detail": "the gate did not produce one complete record in "
                          "both concurrently-run trees",
                "checkout": "NORECORD" if a is None else _attestation_summary(a),
                "worktree": "NORECORD" if b is None else _attestation_summary(b)})
            continue
        if a.get("argv_sha256") != b.get("argv_sha256"):
            findings.append({
                "gate": gate.label, "kind": "PIPELINE_WRONG_COMMAND",
                "detail": "the two records belong to different normalized argv",
                "checkout": str(a.get("argv_sha256", "NORECORD")),
                "worktree": str(b.get("argv_sha256", "NORECORD"))})
            continue
        if a.get("semantic_sha256") != b.get("semantic_sha256"):
            findings.append({
                "gate": gate.label, "kind": "HOST_OR_NONDETERMINISTIC_VERDICT",
                "detail": "the same command on the same commit produced "
                          "different structured outcomes in the checkout and "
                          "fresh worktree. A one-off mismatch is not usable "
                          "evidence and is never folded into PASS",
                "checkout": _attestation_summary(a),
                "worktree": _attestation_summary(b)})
    # BOTH ARMS WERE PRODUCED ELSEWHERE, so THIS process drove nothing and could
    # toggle nothing. Named rather than left as an absence: a missing pointer-arm
    # record and a pointer arm that drove zero gates have to reach the reader as
    # the same NOT_CHECKED sentence, never as silence.
    pointer = {"bound": os.environ.get(POINTER_ENV, "").strip(), "probed": 0,
               "not_probed": [["(all)",
                               "both arms were supplied as precomputed records, "
                               "so this process drove no gate and could not "
                               "toggle the pointer for any of them"]]}
    if findings:
        return Audit("FAIL", findings, dirt, declared, probed, not_probed,
                     scratch, None, pointer)
    if dirt.ignored_reported and dirt.stimulus == 0:
        return Audit("NO_STIMULUS", [], dirt, declared, probed, not_probed,
                     scratch, None, pointer)
    return Audit("PASS", [], dirt, declared, probed, not_probed, scratch,
                 None, pointer)


def parallel_audit(repo_root: Path, jobs: int,
                   checkout_attestations: Optional[Path],
                   timeout: int = 600) -> Audit:
    """Drive disjoint Arm-B label sets in isolated worker worktrees.

    Each child uses the unchanged serial ``audit`` implementation and owns one
    worktree.  The parent derives the denominator before launching anything and
    accepts a result only when every planned label is named by exactly one
    complete child record.  A dead child is therefore lost evidence, never a
    smaller green run.
    """
    script = repo_root / "tools" / "ci" / "repo_hygiene_gates.sh"
    gates = corpus_gates(script)
    declared = len(gates)
    if not gates:
        return Audit("NOTHING_SCANNED", [], None, 0, 0, [], None)
    if jobs < 1:
        return _setup("PARALLEL_INCOMPLETE", "PARALLEL_INCOMPLETE",
                      f"--jobs must be >= 1, got {jobs}", None, declared)

    dirt = checkout_dirt(repo_root, timeout)
    if dirt is None:
        return _setup("STATUS_UNAVAILABLE", "STATUS_UNAVAILABLE",
                      "`git status` did not answer before parallel launch",
                      None, declared)
    if dirt.tracked:
        return _setup(
            "DIRTY_CHECKOUT", "DIRTY_CHECKOUT",
            f"{len(dirt.tracked)} TRACKED path(s) modified/staged; parallel "
            "workers would compare them with HEAD rather than with this tree",
            dirt, declared)
    if checkout_attestations is not None:
        try:
            _load_checkout_attestations(Path(checkout_attestations))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _setup(
                "ATTESTATION_UNAVAILABLE", "ATTESTATION_UNAVAILABLE",
                f"the checkout-arm record is incomplete: {exc}", dirt,
                declared)

    not_probed = [(g.label, reason) for g in gates
                  if (reason := _not_probed_reason(g)) is not None]
    driveable = [g.label for g in gates if _not_probed_reason(g) is None]
    if not driveable:
        return _setup("PARALLEL_INCOMPLETE", "PARALLEL_INCOMPLETE",
                      "no declared gate is driveable", dirt, declared)

    jobs = min(jobs, len(driveable))
    profile_path = _HERE / "hygiene_gate_profile.json"
    try:
        profile = load_profile(profile_path)
        buckets, _ = plan(driveable, profile, jobs)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _setup(
            "PARALLEL_INCOMPLETE", "PARALLEL_INCOMPLETE",
            f"the measured shard profile could not be loaded: {exc}", dirt,
            declared)

    findings: List[Dict] = []
    for lineno, text in inert_exclusions(script):
        findings.append({
            "gate": f"(script line {lineno})", "kind": "INERT_EXCLUSION",
            "detail": ("an EXCLUDE directive is written here but excludes "
                       "nothing; parallel execution does not waive the "
                       "declaration defect"),
            "checkout": text, "worktree": "-"})

    scratch_rows: List[Dict] = []
    unattributed: List[Tuple[str, str]] = []
    #: Summed across workers, never assumed. A worker that reported no pointer-arm
    #: record has not driven one, and a parent that defaulted the missing field to
    #: "all of them" would publish a denominator nobody measured.
    pointer_bound = os.environ.get(POINTER_ENV, "").strip()
    pointer_probed = 0
    pointer_not_probed: List[Tuple[str, str]] = []
    problems: List[str] = []
    seen: List[str] = []
    probed = 0
    verdicts: List[str] = []
    with tempfile.TemporaryDirectory(prefix="hostindep-plan-") as td:
        tmp = Path(td)
        procs = []
        for i, labels in enumerate(buckets):
            labels_path = tmp / f"labels-{i}.txt"
            labels_path.write_text("\n".join(labels) + "\n", encoding="utf-8")
            json_path = tmp / f"worker-{i}.json"
            argv = [sys.executable, str(Path(__file__).resolve()),
                    str(repo_root), "--json", str(json_path),
                    "--labels-file", str(labels_path)]
            if checkout_attestations is not None:
                argv += ["--checkout-attestations",
                         str(Path(checkout_attestations).resolve())]
            procs.append((i, labels, json_path, subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True)))

        def collect(row):
            """Wait for one worker. NO STOPWATCH — see below.

            This used to wait `max(timeout * len(labels), timeout)` and KILL
            the worker on expiry, which turned every busy host into
            PARALLEL_INCOMPLETE: a killed worker writes no record, so its
            labels are then reported as "driven by no worker" and the whole
            gate returns a NON-VERDICT. The configuration it was asked about
            was never checked, and the reason had nothing to do with the tree.

            MEASURED 2026-09-07 on 8HD-9 at 18cb660e3b01, `--jobs 8`, load 62:
            the arm with no corpus pointer bound — the arm that is supposed to
            PASS — returned rc 2 `PARALLEL_INCOMPLETE`, "worker 0 exceeded its
            600s process budget", "labels driven by no worker: an argued
            direction is pinned", after 1915 s. A deadline that fires on load
            is a measurement of the machine, and this gate exists to measure
            the TREE.

            This is the move `matrix_mutation_ledger.replay` already made for
            the same reason, in this same repository: "``timeout`` NO LONGER
            BOUNDS A CELL … one that is merely slow on a busy host runs to
            completion instead of being killed and recorded as unreadable."

            Nothing is lost by waiting. A worker that dies still returns, and
            the branch below already names it — "exited {rc} without a machine
            record" — so a genuine failure is reported BY NAME rather than
            inferred from a clock. What is gained is that a slow run reports a
            verdict about the tree, late, instead of no verdict at all.
            """
            i, labels, json_path, proc = row
            out, err = proc.communicate()
            return i, labels, json_path, proc.returncode, out, err, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            rows = list(pool.map(collect, procs))

        for i, labels, json_path, rc, out, err, exc in sorted(rows):
            assert exc is None                 # no stopwatch — see `collect`
            if not json_path.is_file():
                tail = ((err or out).strip().splitlines() or ["no output"])[-1]
                problems.append(
                    f"worker {i} exited {rc} without a machine record: {tail[:180]}")
                continue
            try:
                doc = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as parse_exc:
                problems.append(f"worker {i} wrote an unreadable record: {parse_exc}")
                continue
            selected = [str(x) for x in doc.get("selected_labels") or []]
            if sorted(selected) != sorted(labels):
                problems.append(
                    f"worker {i} reported a different selection than assigned")
                continue
            if int(doc.get("gates_declared") or 0) != len(labels):
                problems.append(
                    f"worker {i} declared {doc.get('gates_declared')} gate(s), "
                    f"but was assigned {len(labels)}")
                continue
            seen.extend(selected)
            probed += int(doc.get("gates_probed") or 0)
            verdicts.append(str(doc.get("verdict") or ""))
            findings.extend(doc.get("findings") or [])
            if doc.get("scratch_sweep"):
                scratch_rows.append(doc["scratch_sweep"])
            for row in doc.get("not_attributed") or []:
                unattributed.append((str(row.get("gate", "")),
                                     str(row.get("why", ""))))
            arm = doc.get("pointer_arm")
            if arm is None:
                pointer_not_probed.append(
                    (f"(worker {i})",
                     "returned no pointer-arm record, so the gates it drove were "
                     "not checked for a verdict that depends on "
                     f"{POINTER_ENV}"))
            else:
                pointer_probed += int(arm.get("probed") or 0)
                for row in arm.get("not_probed") or []:
                    pointer_not_probed.append((str(row[0]), str(row[1])))
            if rc not in (0, 1, 2):
                problems.append(f"worker {i} exited unexpected rc {rc}")
            expected_rc = {"PASS": 0, "FAIL": 1,
                           "NO_STIMULUS": 2}.get(str(doc.get("verdict")))
            if expected_rc is not None and rc != expected_rc:
                problems.append(
                    f"worker {i} record says {doc.get('verdict')} but process "
                    f"exited {rc}, expected {expected_rc}")

    pointer = {"bound": pointer_bound, "probed": pointer_probed,
               "not_probed": [list(x) for x in pointer_not_probed]}
    duplicates = sorted({label for label in seen if seen.count(label) > 1})
    missing = sorted(set(driveable) - set(seen))
    extra = sorted(set(seen) - set(driveable))
    if duplicates:
        problems.append("labels driven more than once: " + ", ".join(duplicates[:6]))
    if missing:
        problems.append("labels driven by no worker: " + ", ".join(missing[:6]))
    if extra:
        problems.append("unplanned labels were driven: " + ", ".join(extra[:6]))
    if problems:
        return Audit(
            "PARALLEL_INCOMPLETE",
            [{"gate": "(parallel workers)", "kind": "PARALLEL_INCOMPLETE",
              "detail": p, "checkout": "-", "worktree": "-"}
             for p in problems],
            dirt, declared, probed, not_probed,
            {"workers": scratch_rows}, unattributed, pointer)
    if any(v not in ("PASS", "NO_STIMULUS", "FAIL") for v in verdicts):
        return Audit(
            "PARALLEL_INCOMPLETE",
            [{"gate": "(parallel workers)", "kind": "PARALLEL_INCOMPLETE",
              "detail": "worker setup/refusal verdict(s): " + ", ".join(verdicts),
              "checkout": "-", "worktree": "-"}],
            dirt, declared, probed, not_probed,
            {"workers": scratch_rows}, unattributed, pointer)
    if findings or "FAIL" in verdicts:
        return Audit("FAIL", findings, dirt, declared, probed, not_probed,
                     {"workers": scratch_rows}, unattributed, pointer)
    if verdicts and all(v == "NO_STIMULUS" for v in verdicts):
        return Audit("NO_STIMULUS", [], dirt, declared, probed, not_probed,
                     {"workers": scratch_rows}, unattributed, pointer)
    if any(v == "NO_STIMULUS" for v in verdicts):
        return Audit(
            "PARALLEL_INCOMPLETE",
            [{"gate": "(parallel workers)", "kind": "PARALLEL_INCOMPLETE",
              "detail": "workers disagreed about whether stimulus existed",
              "checkout": "-", "worktree": "-"}],
            dirt, declared, probed, not_probed,
            {"workers": scratch_rows}, unattributed, pointer)
    return Audit("PASS", [], dirt, declared, probed, not_probed,
                 {"workers": scratch_rows}, unattributed, pointer)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repo_root", nargs="?", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument(
        "--checkout-attestations", type=Path, default=None,
        help=("JSONL process records written by the enclosing hygiene run; "
              "when supplied, those records are Arm A and only the fresh "
              "worktree Arm B is launched"))
    ap.add_argument(
        "--jobs", type=int, default=1,
        help="parallel isolated Arm-B workers (default: serial compatibility)")
    ap.add_argument("--labels-file", type=Path, default=None,
                    help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    # The enclosing dispatcher owns this path and exports it to every gate.
    # Reading that channel here keeps the shell declaration free of a
    # run-specific variable.  The declaration parser treats unresolved shell
    # variables as loop bindings; spelling this path in the argv therefore
    # made the one repo-wide host gate look like a fifth per-cell gate and
    # corrupted the loop denominator.  An explicit CLI argument remains the
    # higher-priority interface for standalone callers and worker processes.
    if a.checkout_attestations is None:
        inherited = os.environ.get("GATE_DISPATCH_ATTESTATION_FILE", "")
        if inherited:
            a.checkout_attestations = Path(inherited)

    root = Path(a.repo_root).resolve() if a.repo_root else _PLUGIN.parents[2]
    selected: Optional[Set[str]] = None
    if a.labels_file is not None:
        try:
            selected = {line.strip() for line in
                        a.labels_file.read_text(encoding="utf-8").splitlines()
                        if line.strip()}
        except OSError as exc:
            res = _setup("SELECTION_UNAVAILABLE", "SELECTION_UNAVAILABLE",
                         f"could not read worker label manifest: {exc}", None, 0)
        else:
            res = audit(root, checkout_attestations=a.checkout_attestations,
                        only_labels=selected, include_script_findings=False,
                        pointer_arm=True)
    elif os.environ.get("VIBEIC_HOST_FRESH_ATTESTATIONS"):
        if a.checkout_attestations is None:
            res = _setup(
                "ATTESTATION_UNAVAILABLE", "ATTESTATION_UNAVAILABLE",
                "pipelined fresh-arm evidence was supplied without Arm A",
                None, len(corpus_gates(
                    root / "tools" / "ci" / "repo_hygiene_gates.sh")))
        else:
            res = precomputed_audit(
                root, a.checkout_attestations,
                Path(os.environ["VIBEIC_HOST_FRESH_ATTESTATIONS"]))
    elif a.jobs > 1:
        res = parallel_audit(root, a.jobs, a.checkout_attestations)
    else:
        res = audit(root, checkout_attestations=a.checkout_attestations,
                    pointer_arm=True)

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            _audit_doc(res, sorted(selected or [])), indent=2) + "\n")

    # Whatever the outcome, SAY WHAT WAS NOT PROBED. A gate that left the
    # numerator without being named is how a set silently shrinks.
    for label, why in res.not_probed:
        print(f"  [NOT PROBED] {label} — {why}", file=sys.stderr)

    # And say which gates were driven in a checkout this process did not own.
    # Their two-tree verdict below is unaffected; what was NOT measured is
    # whether the drive left the checkout modified. Named rather than counted
    # as clean, because a zero nobody looked for is the mirror of the false
    # accusation this replaced.
    for label, why in (res.unattributed or []):
        print(f"  [NOT ATTRIBUTED] {label} — a write into the working checkout "
              f"during this drive could not be shown to be this gate's: {why}. "
              f"No gate was named and nothing was restored; the two-tree "
              f"verdict for it is unaffected.", file=sys.stderr)

    # And say what the entry sweep did to other people's directories. A cleanup
    # that runs silently is one nobody can audit when it removes the wrong
    # thing, and this one deletes git worktrees.
    if res.scratch:
        for p in res.scratch.get("reaped", []):
            print(f"  [REAPED] {p} — its owner was gone (the flock it held was "
                  f"released), so an interrupted run's scratch worktree was "
                  f"removed and unregistered", file=sys.stderr)
        for p in res.scratch.get("live_peers", []):
            print(f"  [LEFT ALONE] {p} — a live peer holds its lock",
                  file=sys.stderr)
        for k in res.scratch.get("kept", []):
            print(f"  [LEFT ALONE] {k['path']} — {k['why']}", file=sys.stderr)

    if res.verdict == "NOTHING_SCANNED":
        print("NOTHING_SCANNED: no corpus-scanning gate parsed from "
              f"{root}/tools/ci/repo_hygiene_gates.sh", file=sys.stderr)
        return 2
    if res.verdict in ("DIRTY_CHECKOUT", "STATUS_UNAVAILABLE",
                       "WORKTREE_UNAVAILABLE", "ATTESTATION_UNAVAILABLE",
                       "SELECTION_UNAVAILABLE", "PARALLEL_INCOMPLETE"):
        head = {
            "DIRTY_CHECKOUT":
                "DIRTY_CHECKOUT: host-independence was NOT checked — tracked "
                "files are modified, so the worktree at HEAD does not carry "
                "them and every one would read as a difference about the edit "
                "rather than about the gate. This is not a pass.",
            "STATUS_UNAVAILABLE":
                "STATUS_UNAVAILABLE: the checkout could not be characterised, "
                "so host-independence was NOT checked. This is not a pass.",
            "WORKTREE_UNAVAILABLE":
                "WORKTREE_UNAVAILABLE: could not create a scratch git "
                "worktree, so host-independence was NOT checked. This is not "
                "a pass.",
            "ATTESTATION_UNAVAILABLE":
                "ATTESTATION_UNAVAILABLE: the outer hygiene run supplied no "
                "complete checkout process record, so host-independence was "
                "NOT checked. This is not a pass.",
            "SELECTION_UNAVAILABLE":
                "SELECTION_UNAVAILABLE: a parallel worker could not establish "
                "its exact gate set. This is not a pass.",
            "PARALLEL_INCOMPLETE":
                "PARALLEL_INCOMPLETE: one or more isolated workers did not "
                "return a complete, exactly-once record. This is not a pass.",
        }[res.verdict]
        print(head, file=sys.stderr)
        for f in res.findings:
            print(f"      {f['detail']}", file=sys.stderr)
        return 2

    for f in res.findings:
        print(f"  [{f['kind']}] {f['gate']}", file=sys.stderr)
        print(f"      {f['detail']}", file=sys.stderr)
        print(f"      checkout: {f['checkout']}", file=sys.stderr)
        print(f"      worktree: {f['worktree']}", file=sys.stderr)

    # THE POINTER ARM'S OWN DENOMINATOR, printed on every outcome. A verdict line
    # that says "the same verdict in a working checkout and a fresh worktree" is
    # true and is only half the question this program now asks; a run that could
    # drive NO gate under the other value of the pointer has not asked the other
    # half at all, and must say so rather than let the sentence above cover it.
    arm = res.pointer
    if arm is None:
        pointer_line = (f"{POINTER_ENV} arm NOT CHECKED: this run produced no "
                        f"pointer-arm record")
    elif not arm.get("bound"):
        pointer_line = (
            f"{POINTER_ENV} arm NOT CHECKED: no corpus pointer was bound, so "
            f"there is no second environment to compare against and inventing "
            f"one would be a comparison against a corpus nobody published")
    else:
        pointer_line = (f"{POINTER_ENV} arm: {arm.get('probed', 0)} gate(s) "
                        f"driven with the pointer bound AND withheld")
    for label, why in (arm or {}).get("not_probed", []):
        print(f"  [POINTER ARM NOT PROBED] {label} — {why}", file=sys.stderr)

    stim = res.dirt.describe() if res.dirt is not None else "unknown stimulus"
    if res.findings:
        # Split by KIND rather than totalling them. Reporting a gate that met
        # an inner deadline as "HOST-DEPENDENT" sends the reader to look for
        # untracked leftovers that are not there — the wrong repair, which is
        # the cost this split exists to stop.
        by_kind: dict = {}
        for f in res.findings:
            by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
        parts = ", ".join(f"{n} {k}" for k, n in sorted(by_kind.items()))
        print(f"[FAIL] {len(res.findings)} of {res.probed} probed corpus "
              f"gate(s) ({res.declared} declared) did not give one reproducible "
              f"verdict across two trees: {parts}. {pointer_line}.",
              file=sys.stderr)
        return 1
    if res.verdict == "NO_STIMULUS":
        # The sentence a two-pristine-tree run has always deserved and never
        # printed.
        print(f"NO_STIMULUS: host-independence was NOT checked — the checkout "
              f"carried no untracked and no ignored path, so it and the fresh "
              f"worktree held the same bytes and all {res.probed} probed "
              f"gate(s) agreed by construction. A comparison with nothing on "
              f"one side that is not on the other cannot detect a gate reading "
              f"local state. This is not a pass. Run it in the working tree "
              f"the leftovers accumulate in.", file=sys.stderr)
        return 2
    print(f"[PASS] all {res.probed} probed corpus-scanning gate(s) "
          f"({res.declared} declared) give the same verdict in a working "
          f"checkout and a fresh worktree; {stim}. {pointer_line}.",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    raise SystemExit(_pr.exit_undetermined_on_stall(main))
