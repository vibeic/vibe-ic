#!/usr/bin/env python3
"""scratch_root_guard.py — the suite's scratch root is part of its verdict, so
every run states it, and refuses a root that manufactures failures.

WHY THIS EXISTS (vibe-ic#1446)
==============================
#1446 set out to count main's red tests outside the 63x9 matrix. Five counts
were published on it — ~93, 46, 39, 145, 218 — and its own author retracted or
corrected four of them. One correction names this file's subject exactly:

    "218 reds as I measured them / 35 of which are the TMPDIR artefact, not
     main's ... That is the second time today my own instrument shaped its own
     answer."

and, from the re-measurement:

    scratch INSIDE a repo   218 reds
    scratch OUTSIDE         145 reds
    only in the inside run   74      <- environment, not main

RE-MEASURED ON 75776dbbb (v1.10.40), same tree, same commit, same host, one
pytest invocation each, ONLY `--basetemp` different:

    --basetemp <outside any repository>   86 passed in 140.48s
    --basetemp <inside a git work tree>   46 failed, 40 passed in 49.78s

over exactly three files —

    programs/tests/test_published_record_staleness_check.py
    programs/tests/test_issue905_ic_level_layout_contract.py
    programs/tests/test_issue967_empty_ic_unit_examined_nothing.py

— which is the same 46 the reporter's own correction names, two months and
one hundred and sixty merged PRs later. The artefact did not go away; nothing
had ever been aimed at it.

THE MECHANISM, AND WHY IT IS NOT A DEFECT IN THE PROGRAMS
=========================================================
`git -C D ls-files` cannot FAIL while any ancestor of D is a work tree: it
succeeds and answers about that ENCLOSING repository, scoped to D, which is
zero paths for a directory nobody committed. Gates that enumerate a corpus
this way therefore meet an empty population and correctly say so —
`VACUOUS_PASS: 0 JSON file(s) enumerated (git-tracked)`, `examined nothing —
0 published entries`.

That behaviour is deliberate and load-bearing. `published means committed` is
the contract (`published_record_staleness_check._tracked_paths`: "adjudicating
scratch output would report a defect nobody published"), and #967 pins it as a
property with its own test: an IC whose only entry is a developer's local
scratch "published NOTHING, so it is a skip, not a pass". Widening the
enumeration to walk the disk whenever the tracked set came back empty makes
those 46 green and BREAKS that property — which is why this guard does not
touch a single gate. No program's behaviour is changed by this file.

So the programs are right and the tests they fail are right. What was wrong is
the RUN: a fixture that builds an untracked corpus in `tmp_path` is only
discoverable when `tmp_path` is not inside a repository, and nothing in the
harness pinned or recorded that. pytest's own default lands in `/tmp` and is
fine; an operator who exports `TMPDIR` into a checkout silently converts 46
honest passes into 46 failures that then get published as main's redness. Grep
`tools/` on 75776dbbb: no `--basetemp`, no `TMPDIR`, nowhere.

WHAT THIS GUARD DOES
====================
Two things, and deliberately not a third:

  DECLARES  every run prints the scratch root it used and whether that root is
            inside a git work tree. A count is only re-derivable if the run
            that produced it says what it ran under; #1446's five
            irreconcilable numbers are what a suite whose verdict depends on
            an unrecorded environment variable looks like from outside.
  REFUSES   a session whose scratch root IS inside a work tree stops with ONE
            named error instead of producing dozens of failures whose cause is
            nowhere in their output. A run that cannot be trusted must not
            LOOK like a measurement of the tree.
  NEVER     relocates the scratch root behind the operator's back. Silently
            moving it would make the guard the thing shaping the answer, which
            is the failure this whole issue is about.

THE SECOND WAY THE ROOT FALSIFIES THE RUN: A CONTROL CHARACTER IN IT
===================================================================
The root can be outside every checkout and STILL manufacture failures, because
pytest does not use the temp root directly. With no `--basetemp` it builds

    temproot / f"pytest-of-{user}"            _pytest/tmpdir.py:161 (pytest 9.0.3)

from `getpass.getuser()`, and falls back to `pytest-of-unknown` only when that
`mkdir` raises `OSError`. A newline is a LEGAL filename character on Linux, so
the mkdir succeeds and the newline lands inside every `tmp_path` of the session.

MEASURED in the pinned EDA container image, which is the sanctioned runner:

    $ python3 -c 'import getpass; print(repr(getpass.getuser()))'
    '1000\ndesigner'                     # USER is a two-line value there
    $ getent passwd 1000
    (no entry)

and the consequence, same tree, same commit, one pytest invocation each, ONLY
`--basetemp` different:

    default basetemp (newline in the path)   4 failed, 75 passed
    --basetemp /tmp/<clean>                  79 passed

Three of those four are
`test_matrix_d2_falsifiable::test_d2_a_real_crash_is_disclosed_by_the_consumer_not_guessed`,
and the mechanism is not incidental. `flow_compliance_check._check_program_exit_zero`
hands back a LINE-DELIMITED evidence string, and every consumer of it — the
crash sentinel, the vacuity hints, this repo's `_classify` — reads it by line.
A project path carrying a newline injects a line break INTO that channel, so
the sentinel and the evidence it prefixes come apart. The failures then name
their own subject and say nothing about the root, which is #1446's shape
exactly, in a run whose root passed the work-tree question.

So the guard asks a second question of the same subject: not only WHERE the
scratch root is, but whether the identity pytest is about to interpolate into
it can survive being a path component in a line-oriented channel. Only control
characters qualify — `/` makes pytest's own mkdir fail and it backs off to
`pytest-of-unknown` on its own, so that case is already handled upstream and is
deliberately not duplicated here.

The question is asked ONLY when pytest will interpolate: an explicit
`--basetemp` is used verbatim and no identity enters it.

BLOCKING (declared, per flow-change-acceptance §5)
==================================================
BLOCKING. A scratch root inside a work tree stops the session in
`pytest_configure` with `pytest.UsageError` — rc 4, nothing collected, no
passed/failed tally. Advisory would be the wrong choice for the criterion's
own reason: the thing this guard exists to stop is a run that LOOKS like a
measurement of the tree, and a warning printed beside 46 red tests is a
warning nobody reads. That is not hypothetical — it is what happened, and a
count was published off the back of it.

BLOCKING, on the same criterion's own reason, for a scratch identity that
would put a control character into the path: it produces reds that name
anything except their cause, which is the one outcome this file exists to stop.
It refuses in the same `pytest_configure`, with its own named error, and it has
its own escape hatch below.

The DECLARATION half is advisory by nature: it prints on every run, passing or
failing, and never changes an outcome.

THE ESCAPE HATCH IS DISCLOSED, NOT SILENT
=========================================
`--allow-scratch-root-in-control-character-identity` (or
`VIBE_IC_ALLOW_SCRATCH_IDENTITY=1`) is the second refusal's hatch, and the fix
it names first is the one-word one: pass `--basetemp`, which stops pytest
interpolating the identity at all.

`--allow-scratch-root-in-repo` (or `VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO=1`) runs
anyway — for a container whose only writable tmp is inside the checkout. The
declaration still prints, and it prints that the allowance was used, so a
number lifted out of that run still carries the reason not to trust it.

chip-AGNOSTIC: pure harness/environment structure; no IC, PDK or vendor literal.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import pytest

#: Well under the 180 s session bound `tools/gatekeeper-land.sh` runs at, and
#: under the 60 s inner ceiling `ci_harness_timeout_ceiling_check` enforces. An
#: inner bound at or above the harness's does not fail a test — it outlives the
#: harness and takes the whole session down, losing every other result in the
#: run unnamed, which is the other half of why #1446 could not be counted.
_GIT_TIMEOUT = 20

_ENV_ALLOW = "VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO"
_FLAG = "--allow-scratch-root-in-repo"

_ENV_ALLOW_IDENTITY = "VIBE_IC_ALLOW_SCRATCH_IDENTITY"
_FLAG_IDENTITY = "--allow-scratch-root-in-control-character-identity"


def scratch_root(config) -> Path:
    """The directory pytest will put `tmp_path` under, as pytest picks it.

    `--basetemp` when given, otherwise the platform temp root — which is what
    `TMPDIR` moves. Read from pytest's own resolved option rather than
    recomputed by the caller, so the guard and the fixture cannot disagree
    about which directory is at issue.
    """
    given = getattr(config.option, "basetemp", None)
    return Path(given).resolve() if given else Path(tempfile.gettempdir()).resolve()


def interpolated_identity(config) -> Optional[str]:
    """The identity pytest will put into the scratch path, or None.

    None when `--basetemp` is given — pytest uses that path VERBATIM and no
    identity enters it — and None when `getpass` cannot answer, which pytest
    itself treats as "no user" and backs off from.

    Read the way pytest reads it (`_pytest/tmpdir.py:get_user`), not from
    `$USER` directly, so the guard and the fixture cannot disagree about which
    string is at issue.
    """
    if config is None or getattr(config.option, "basetemp", None):
        # `config is None` is the caller that already classified and is only
        # asking for wording (see `declaration`); it has no session to refuse.
        return None
    try:
        import getpass
        return getpass.getuser()
    except (ImportError, OSError, KeyError):
        return None


def control_characters(identity: Optional[str]) -> Tuple[str, ...]:
    """The control characters in `identity`, as repr'd names, in order.

    Only control characters. `/` is excluded ON PURPOSE and not by oversight:
    it makes pytest's own `rootdir.mkdir` raise, and pytest then backs off to
    `pytest-of-unknown` without this guard's help (`_pytest/tmpdir.py:165`).
    Duplicating that here would refuse a session pytest was already going to
    make safe.
    """
    if not identity:
        return ()
    return tuple(repr(c) for c in identity if ord(c) < 32 or ord(c) == 127)


def _nearest_existing(p: Path) -> Path:
    """`--basetemp` need not exist yet; git must be asked about a real path."""
    cur = p
    while not cur.is_dir() and cur != cur.parent:
        cur = cur.parent
    return cur


def enclosing_work_tree(d: Path) -> Optional[str]:
    """Toplevel of the git work tree containing `d`, or None.

    None also covers "git is not installed" and "git errored". This guard
    exists to stop a run being MISREAD, and a run it could not classify is not
    one it should refuse — refusing on "I could not look" would make an absent
    `git` unable to run the suite at all. That absence is stated in the
    declaration rather than reported as a clean "outside", because "I could not
    look" and "I looked and there is nothing" are the two this repo keeps apart.
    """
    try:
        r = subprocess.run(["git", "-C", str(_nearest_existing(d)),
                            "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=_GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    top = r.stdout.strip()
    return top or None


def classify(config) -> Tuple[Path, Optional[str], bool]:
    """(scratch root, enclosing work tree or None, allowance in force)."""
    root = scratch_root(config)
    allowed = bool(getattr(config.option, "allow_scratch_root_in_repo", False)) \
        or os.environ.get(_ENV_ALLOW, "") not in ("", "0")
    return root, enclosing_work_tree(root), allowed


_REFUSAL = """\
the pytest scratch root is INSIDE a git work tree, and this suite cannot be
measured from there.

    scratch root : {root}
    work tree    : {top}

`git -C <dir> ls-files` does not FAIL inside a checkout — it succeeds and
answers about that checkout, scoped to <dir>, which is ZERO paths for a
directory nobody committed. Fixtures that build an untracked corpus under
`tmp_path` are then enumerated as empty, and the gates correctly report
"published nothing". 46 tests measure red this way on a tree whose real
count for them is 0 (vibe-ic#1446), and each one names its own subject
rather than this root, so the cause is nowhere in the failure output.

FIX: put the scratch root outside any repository. pytest's own default
already is — the usual cause is an exported TMPDIR.

    env -u TMPDIR pytest ...
    pytest --basetemp=/tmp/<something-outside-any-repo> ...

If this environment genuinely has no writable tmp outside a checkout, run
with {flag} (or {env}=1). The run then
declares the allowance, so a count taken from it still carries the reason
not to trust it."""


_IDENTITY_REFUSAL = """\
the identity pytest is about to interpolate into the scratch path carries a
CONTROL CHARACTER, and a run from there measures the path and not the tree.

    identity            : {identity!r}
    control character(s): {chars}
    scratch path pytest will build: {root}/pytest-of-<that identity>

pytest builds `temproot / f"pytest-of-{{user}}"` from `getpass.getuser()` and
backs off to `pytest-of-unknown` only when that mkdir RAISES. A newline is a
legal filename character here, so it does not raise: the character lands inside
every `tmp_path` of this session.

That matters because this repo's gate evidence is line-delimited.
`flow_compliance_check._check_program_exit_zero` returns one string that every
consumer reads BY LINE — the crash sentinel, the vacuity hints, the matrix's
own classifier. A project path carrying a newline injects a line break into
that channel, and the sentinel comes apart from the evidence it prefixes.
MEASURED: 3 dimension-2 cells fail this way and not one of them names the root.

FIX, and it is one word: give the run a scratch root, so pytest interpolates
nothing.

    pytest --basetemp=/tmp/<something-outside-any-repo> ...

Or give the environment a `USER` that is one line, or a passwd entry for this
uid. To run anyway, {flag} (or {env}=1); the declaration then says so, and a
count taken from that run carries the reason not to trust it."""


def pytest_addoption(parser):
    parser.addoption(
        _FLAG, action="store_true", default=False,
        help="Run even though the pytest scratch root is inside a git work "
             "tree. Disclosed in the run header; see vibe-ic#1446.")
    parser.addoption(
        _FLAG_IDENTITY, action="store_true", default=False,
        help="Run even though the identity pytest will interpolate into the "
             "scratch path carries a control character. Disclosed in the run "
             "header.")


def _identity_allowed(config) -> bool:
    """The second refusal's escape hatch, read the same way as the first's."""
    opt = getattr(config, "option", None) if config is not None else None
    return bool(getattr(
        opt, "allow_scratch_root_in_control_character_identity", False)) \
        or os.environ.get(_ENV_ALLOW_IDENTITY, "") not in ("", "0")


def declaration(config, verdict=None) -> str:
    """The one line every run states about the root it measured from.

    `verdict` lets a caller that already classified pass the answer in, so one
    session asks git once. Recomputing would also let the declaration and the
    refusal disagree if the tree moved between them — a small window, but this
    guard exists because a run said something other than what it did.
    """
    root, top, allowed = verdict if verdict is not None else classify(config)
    chars = control_characters(interpolated_identity(config))
    if chars:
        state = "ALLOWED BY FLAG — results from this run are not trustworthy" \
            if _identity_allowed(config) else "REFUSED"
        return (f"scratch_root_guard: {root} — the identity pytest will "
                f"interpolate carries control character(s) "
                f"{', '.join(chars)} [{state}]")
    if top is None:
        return (f"scratch_root_guard: {root} — outside any git work tree "
                f"(or git could not be asked)")
    state = "ALLOWED BY FLAG — results from this run are not trustworthy" \
        if allowed else "REFUSED"
    return f"scratch_root_guard: {root} — INSIDE work tree {top} [{state}]"


def pytest_report_header(config):
    """The verbose header. Not sufficient on its own — see `pytest_configure`."""
    return declaration(config)


def pytest_configure(config):
    """Declare FIRST, then refuse if the root is one that falsifies the run.

    The declaration is PRINTED here rather than left to `pytest_report_header`
    because `-q` SUPPRESSES that header — and `-q` is the shape
    `tools/gatekeeper-land.sh` runs on every landing. Measured on this branch
    before this line existed:

        pytest -q  ... | grep -c scratch_root_guard   ->  0
        pytest     ... | grep -c scratch_root_guard   ->  2

    A guard whose subject is runs that do not state their own conditions,
    shipped so that it stated nothing in the only invocation shape that
    matters, would have been this issue's defect wearing this issue's fix.

    AT CONFIGURE AND NOT AT SESSION FINISH, deliberately: `gatekeeper-land.sh`
    prints `tail -6` of a failing pytest run as the failure context, so a line
    emitted at the END costs a line of the failure the reader needs. A run's
    conditions belong before its results anyway.
    """
    verdict = classify(config)
    print("[INFO] " + declaration(config, verdict))
    root, top, allowed = verdict
    if top is not None and not allowed:
        raise pytest.UsageError(
            "scratch_root_guard: " + _REFUSAL.format(
                root=root, top=top, flag=_FLAG, env=_ENV_ALLOW))
    identity = interpolated_identity(config)
    chars = control_characters(identity)
    if chars and not _identity_allowed(config):
        raise pytest.UsageError(
            "scratch_root_guard: " + _IDENTITY_REFUSAL.format(
                identity=identity, chars=", ".join(chars), root=root,
                flag=_FLAG_IDENTITY, env=_ENV_ALLOW_IDENTITY))


# ── the same question, PREFLIGHT, before an hour of tests answers it ────────

def _main(argv=None) -> int:
    """CLI: is the scratch root a pytest run here would use a falsifying one?

    WHY THIS EXISTS BESIDE THE HOOK. The in-process hook can only refuse once
    pytest is already starting, which in a landing is after the selection has
    been built. Asked as a preflight, the landing learns in milliseconds that
    its environment would falsify the run it is about to spend an hour on —
    and `suite_write_guard`, the pytest plugin this one is modelled on, is
    wired into `gatekeeper-land.sh` as a CLI for exactly that reason.

    It also gives the check a machine runner. A checker that only its own unit
    test executes is one `checker_execution_wiring_audit` names as an orphan:
    "its own unit test proves the logic works on a fixture the author wrote. It
    proves nothing about production artefacts, because it never sees one."

    rc 0  scratch root is outside any work tree, or git could not be asked
    rc 2  scratch root is INSIDE a work tree — the disclosed-refusal
          convention this repo uses for "I will not certify this"
    """
    import argparse
    ap = argparse.ArgumentParser(
        description="Refuse a pytest scratch root that falsifies the run "
                    "(vibe-ic#1446).")
    ap.add_argument("--scratch-root", default=None,
                    help="Directory to test. Default: the platform temp root, "
                         "which is what pytest uses when --basetemp is unset.")
    ap.add_argument("--allow", action="store_true",
                    help="Report but do not refuse. Still prints the verdict.")
    a = ap.parse_args(argv)

    root = Path(a.scratch_root).resolve() if a.scratch_root \
        else Path(tempfile.gettempdir()).resolve()
    top = enclosing_work_tree(root)
    allowed = a.allow or os.environ.get(_ENV_ALLOW, "") not in ("", "0")

    if top is None:
        print(f"[PASS] scratch_root_guard: {root} — outside any git work tree "
              f"(or git could not be asked); a pytest run here is measurable.")
        return 0
    print("[FAIL] scratch_root_guard: " + _REFUSAL.format(
        root=root, top=top, flag=_FLAG, env=_ENV_ALLOW))
    if allowed:
        print("[ALLOWED] refusal waived; results from a run here are not "
              "trustworthy and a count taken from one carries this caveat.")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
