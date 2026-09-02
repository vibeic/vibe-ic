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

THE THIRD WAY A SCRATCH ROOT MANUFACTURES FAILURES
===================================================
A root can be outside every repository AND outside the account home and still
falsify the run, because some tests in this suite do not merely WRITE under
`tmp_path` — they hand `tmp_path` to a gate that CLASSIFIES it:

    programs/project_outputs_in_tree_check.py
        _VOLATILE_PREFIXES = ("/tmp/", "/var/tmp/", "/dev/shm/", "/run/")

Those four prefixes are the whole of what that gate calls external storage. A
subject built anywhere else is not "external" to it, so the gate PASSes where
the test requires it to FAIL, and the failure names the fixture rather than the
root. MEASURED on ae5cc4dbfc3f (tree 954bc27704cb), one pytest invocation each,
ONLY `TMPDIR` different:

    TMPDIR under /var/tmp      6 failed -> 0    (25 passed)
    TMPDIR outside all four    6 failed         (19 passed)

    programs/tests/test_issue146_collect_external_outputs.py        4
    programs/tests/test_project_outputs_in_tree_check.py            2

THAT TABLE IS HISTORY, AND IT DECAYED WITHOUT SAYING SO. It was carried into
the operator-facing refusal below verbatim and read as present tense for six
days. RE-MEASURED on ded6aa231a68, same image, same clone, one bind mount,
ONLY `TMPDIR` different:

    programs/tests/test_issue146_collect_external_outputs.py        0  (was 4)
    programs/tests/test_project_outputs_in_tree_check.py            2
    programs/tests/test_issue1446_scratch_root_guard.py             6  (never
                                                                       listed;
                                                                       now 0)

fc32402c8 gave `test_issue146_collect_external_outputs.py` a `volatile_dir`
fixture that mkdtemps under one of the four prefixes, so its subject stopped
depending on where `tmp_path` lands: 4 failed at fc32402c8^, 0 at fc32402c8.
The refusal went on sending the reader to a file that is clean, and went on NOT
naming this guard's own test file, which is the largest contributor — its arms
ask this preflight about the work tree, the account home and git-absent, and
from a non-volatile root the preflight answers rc 1 to all three.

The cost table in `_VOLATILE_ADVISORY` is therefore RE-MEASURED rather than
read: `test_issue1446_scratch_root_guard.py::test_every_line_of_this_cost_table_fires`
runs each file the table names from a non-volatile root and requires the stated
count, so an entry that stops firing fails instead of misleading.

IT FIRED, AND THE ANSWER IS ZERO. RE-MEASURED on 4b3843f22c (v1.16.90), one
pytest process per file, only `--basetemp` different — `/tmp/...` against a
writable non-volatile directory outside every work tree:

    programs/tests/test_project_outputs_in_tree_check.py            0  (was 2)
    programs/tests/test_issue146_collect_external_outputs.py        0
    programs/tests/test_issue1446_scratch_root_guard.py             0
    ------------------------------------------------------------- ---
    total                                                          0

The remaining 2 went the way the 4 went, and in the same shape: the v1.16.85
landing gave `test_project_outputs_in_tree_check.py` a `volatile_project`
fixture that mkdtemps under one of the four prefixes and asserts it landed
there — "two tests that measured the harness's TMPDIR". Every test that
exercises the gate now pins its own volatile subject; none of them depends on
where `tmp_path` lands.

WIDENED, so that "zero" is a measurement and not the two files this table
happens to name: all 19 test files in the tree that reference the gate, the
collector, this guard, or the word "volatile" were run twice each — once from
`/tmp`, once from a non-volatile root — on 4b3843f22c. Every one of the 19
measured the SAME count under both roots. The only difference in the whole
sweep was this file's own `test_every_line_of_this_cost_table_fires`, red under
both roots because it builds its own non-volatile root, which is the red this
change is answering.

SO THE CONDITION WAS DEMOTED, and the demotion is this file's own arithmetic
run with today's numerator. It said: "refusing the other ~3198 to catch two
would be this guard causing the harm it exists to prevent". Two is now zero,
and refusing ~3200 measurable tests to catch zero falsified ones is that same
sentence with nothing left on the other side of it. `NOT VOLATILE` is now
DECLARED in both halves and refused in neither — see the BLOCKING block below,
and `_VOLATILE_ADVISORY` for what an operator is told instead.

WHAT DID NOT CHANGE: the mechanism, the declaration, or the table. The gate
still admits exactly four prefixes; the run still prints which side of them the
root is on — that INFO line is how a reader tells "this gate is broken" from
"this subject was built where the gate cannot look"; and the table is still
re-measured every run, so the day a line leaves 0 the guard says so instead of
staying silent about a cost it stopped charging for.

That is the same shape as the first condition and it cost the same half hour
while it lasted: an operator exported `TMPDIR=/work/tmp` into a container and
eight honest passes were published as main's redness. All eight are now fixed
at the fixture. pytest's own default lands in `/tmp` and is fine.

THE SECOND WAY A SCRATCH ROOT MANUFACTURES FAILURES
===================================================
"Manufactures failures" is this file's own word for what it refuses, and until
now it checked exactly ONE way of doing it. There is a second, and it costs the
same half hour:

    tools/ci/hermetic_candidate_runner.py::_resolve_mount
        if _inside(resolved, home):
            raise Refusal(f"{kind} would expose the host HOME to the candidate")

    where `home` is `_home_path()` — `pwd.getpwuid(os.getuid()).pw_dir`,
    resolved strictly — NOT `$HOME`.

Every hermetic mount goes through that: subject, runtime, corpus, selection,
progress plan. And the subject a landing mounts is derived from the platform
temp root, exactly as `tmp_path` is — `gatekeeper-verify-merge.sh:276`:

    RUN="$(mktemp -d -t gkverify.XXXXXX)"     # -> $TMPDIR, else /tmp

So a scratch root under the account home is NOT inside a work tree, passes this
guard's one condition, and then makes every hermetic arm NORECORD. It happened:
an operator created exactly that root by accident, spent measurements on it, and
had to work back from the refusal text to find out why the arms were empty.

`gatekeeper-verify-merge.sh:462` already records the cost of that from the other
end — three unrelated causes collapsing into one symptom line, the first of them
being this one, "(TMPDIR under $HOME)".

MEASURED HERE, by calling the runner's own `_resolve_mount` (no container, no
docker needed — it refuses before it ever starts one):

    host account home (pwd.getpwuid)      /home/<account>
    _resolve_mount(/tmp)                  OK
    _resolve_mount(<home>/scratch_demo)   Refusal: subject would expose the
                                          host HOME to the candidate

WHAT THIS GUARD DOES
====================
Three things, and deliberately not a fourth:

  DECLARES  every run prints the scratch root it used, whether that root is
            inside a git work tree, whether it is under the host account
            home — naming that home — AND whether it is under a volatile root,
            naming the prefixes. A count is only re-derivable if the run
            that produced it says what it ran under; #1446's five
            irreconcilable numbers are what a suite whose verdict depends on
            an unrecorded environment variable looks like from outside. The
            home half is declared for the same reason and by the same rule: a
            guard that refuses without saying WHICH condition it refused on
            sends the next reader back to the half hour this cost.
  REFUSES   a session whose scratch root IS inside a work tree stops with ONE
            named error instead of producing dozens of failures whose cause is
            nowhere in their output; and the PREFLIGHT CLI additionally refuses
            a root under the account home, which is the condition the hermetic
            lane is about to refuse anyway, silently, arm by arm.
  SAYS SO   when it could not tell. "I could not look" and "I looked and there
            is nothing" are two answers this repo keeps apart, and this file
            used to fold them: `git could not be asked` and `git said no` both
            returned a clean pass. They are now separate states with separate
            exit codes.
  NEVER     relocates the scratch root behind the operator's back. Silently
            moving it would make the guard the thing shaping the answer, which
            is the failure this whole issue is about.

BLOCKING (declared, per flow-change-acceptance §5)
==================================================
BLOCKING, and asymmetrically so, because the two conditions do different harm:

  IN A WORK TREE     BLOCKING IN BOTH HALVES. The pytest hook stops the session
                     in `pytest_configure` with `pytest.UsageError` — rc 4,
                     nothing collected, no passed/failed tally — and the CLI
                     preflight refuses. Advisory would be the wrong choice for
                     the criterion's own reason: the thing this guard exists to
                     stop is a run that LOOKS like a measurement of the tree,
                     and a warning printed beside 46 red tests is a warning
                     nobody reads. That is not hypothetical — it is what
                     happened, and a count was published off the back of it.

                     AND THE 46 IS RE-MEASURED, NOT REMEMBERED. It is the one
                     number left in this file that a refusal rests on, and the
                     condition below is what a remembered number decays into.
                     RE-MEASURED on 4b3843f22c (v1.16.90), one pytest process
                     per file, only `--basetemp` different — outside every
                     repository against inside a throwaway work tree:

                         test_published_record_staleness_check.py  35   (0)
                         test_issue905_ic_level_layout_contract.py  6   (0)
                         test_issue967_empty_ic_unit_examined_nothing.py
                                                                    5   (0)
                         ---------------------------------------- ---
                         total                                     46   (0)

                     — the same 46, over the same three files, that #1446's own
                     correction named. The table lives in `_REFUSAL` and
                     `test_every_line_of_the_work_tree_cost_table_fires` runs
                     it, so this row cannot become the row below it without
                     saying so.

  NOT VOLATILE       NOT BLOCKING IN EITHER HALF. DECLARED IN BOTH. This
                     row used to read "BLOCKING IN THE CLI PREFLIGHT ONLY",
                     and it was demoted by its own arithmetic rather than by a
                     judgement: "refusing the other ~3198 to catch two would be
                     this guard causing the harm it exists to prevent."

                     The two are now ZERO. Re-measured on 4b3843f22c over all
                     19 test files in the tree that touch the gate, the
                     collector, this guard or the word "volatile" — twice each,
                     only `--basetemp` different — every one measured the same
                     count from a non-volatile root as from `/tmp`. The debt
                     was paid at the fixtures, file by file (fc32402c8, the
                     v1.16.85 landing, cca4ba4e72), and nothing is left on the
                     other side of that sentence.

                     A REFUSAL WHOSE COST IS ZERO IS A BAN. It stops runs the
                     suite can measure perfectly, in exchange for nothing, and
                     "a guard that manufactures the harm it exists to prevent"
                     is this file's own name for that. So the preflight prints
                     `[ADVISORY]`, names the mechanism, states the re-measured
                     table, and returns the rc it would have returned anyway.

                     WHAT KEEPS IT HONEST is that the table is still RUN. If a
                     line ever leaves 0 — a new test that hands `tmp_path` to
                     the gate — `test_every_line_of_this_cost_table_fires`
                     fails and names the file, and this row can be argued back
                     up on a measurement instead of a memory. Restoring a
                     refusal is a one-line change; the number is the part that
                     has to be earned.

  UNDER THE HOME     BLOCKING IN THE CLI PREFLIGHT ONLY; DECLARED, NEVER
                     BLOCKING, IN THE PYTEST HOOK. A pytest session whose
                     `tmp_path` is under the account home is not falsified by
                     that fact — `git ls-files` answers the same, the fixtures
                     are discoverable, the tally is real. Nothing about it needs
                     refusing, and refusing it would take down runs that are
                     perfectly measurable. What breaks is the HERMETIC lane, and
                     the hermetic lane is what asks the preflight
                     (`gatekeeper-land.sh:872`). So the block is placed where
                     the harm is, and only there.

THE MEASUREMENT THAT DECIDED "BLOCK" RATHER THAN "DECLARE ONLY"
===============================================================
Blocking on the home condition is only safe if the canonical landing lane's own
scratch root is not under the account home — otherwise this guard breaks
landing on every branch, which is a far larger failure than the one it fixes.
That was measured before it was decided, in both places the preflight runs:

    ON THE HOST that launches the arms
        TMPDIR                        unset
        tempfile.gettempdir()         /tmp
        mktemp -d -t gkverify.XXXXXX  /tmp/gkverify.XXXXXX
        account home                  /home/<account>
        -> /tmp is not under the home. PASS. Landing unaffected.

    INSIDE THE PINNED CANDIDATE IMAGE, where `gatekeeper-land.sh` — and so this
    preflight — also runs, as uid 65534:
        TMPDIR                        /tmp   (fixed by the runner)
        pwd.getpwuid(65534).pw_dir    /nonexistent
        resolve(strict=True)          FileNotFoundError
        -> the account home CANNOT BE RESOLVED there.

That second measurement is why "cannot resolve the account home" is NOT a
refusal. Read literally it is an unchecked condition, and an unchecked
condition is rc 2 — but rc 2 from this preflight fails the landing
(`gatekeeper-land.sh` treats every non-zero rc alike), so the literal reading
breaks every landing in the canonical lane. It is also the wrong reading: a
host where `_home_path()` raises is a host where the hermetic runner refuses
EVERY mount before it looks at any scratch root, so the scratch root is not the
finding there; and inside the candidate there is no host home to expose. The
state is therefore DECLARED as NOT CHECKED and passes, and a caller that needs
the answer rather than the declaration asks for it with
`--require-home-check`, which turns the same state into rc 2. The landing does
not pass that flag.

Two things this guard does NOT use, for the same reason in both cases — the
guard must ask the question the way the thing it predicts asks it, or it will
confidently answer about a different subject:

  $HOME       the runner reads `pwd`, not the environment. Inside the candidate
              the runner itself sets `HOME=/tmp` while TMPDIR is also `/tmp`, so
              a `$HOME`-based check would call the landing's own scratch root a
              finding and block every landing. Measured, not supposed.
  an override there is no `--allow-scratch-root-under-home`. The work-tree
              refusal has an escape hatch because a run under it can still be
              made and merely carries a caveat. This one cannot: waiving it here
              would not make `_resolve_mount` accept the mount, so the flag
              would buy a green preflight and an identical NORECORD ten minutes
              later. A hatch that does not open is worse than none.

The DECLARATION half is advisory by nature: it prints on every run, passing or
failing, and never changes an outcome.

EXIT CODES (the CLI preflight)
==============================
    0  PASS           the root is outside every condition that COSTS
                      something, or a condition did not apply here and said so.
                      A non-volatile root is rc 0 and an `[ADVISORY]` line — it
                      is declared, never charged for; see the BLOCKING block.
    1  a FINDING about the root — inside a work tree, or under the account
                      home. Those are the two conditions with a measured cost,
                      and both tables are re-measured rather than read.
    2  UNDETERMINED / NOT CHECKED, naming what could not be determined
    3  bad invocation

This RENUMBERS the work-tree refusal, which shipped as rc 2, and the renumber
is the point rather than a side effect. rc 2 in this repo is the disclosed-skip
convention — `_vacuous_exit`: "rc 2 -> VACUOUS_PASS ... the gate examined
NOTHING" — and this file was the odd one out, spending it on a finding. Holding
both meanings on one code is a documented pathology here, not a theoretical
one. Measured blast radius before the change: the only two consumers are
`gatekeeper-land.sh:872`, which is `if ! out="$(...)"` and treats every non-zero
rc identically, and `conftest.py`, which loads the pytest hook and never sees a
CLI rc. Nothing production-side can tell 1 from 2; the reader can.

rc 3 does not collide with `PASS_WITH_WAIVERS` (#651), which — per
`_vacuous_exit`, "rc 3 IS NOT OURS" — is honoured only together with a matching
`PASS_WITH_WAIVERS` stdout sentinel. This file never emits that sentinel.

THE ESCAPE HATCH IS DISCLOSED, NOT SILENT
=========================================
`--allow-scratch-root-in-repo` (or `VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO=1`) runs
anyway — for a container whose only writable tmp is inside the checkout. The
declaration still prints, and it prints that the allowance was used, so a
number lifted out of that run still carries the reason not to trust it.

chip-AGNOSTIC: pure harness/environment structure; no IC, PDK or vendor literal.
"""
from __future__ import annotations

import importlib.util
import os
import pwd
import subprocess
import sys
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

#: The three answers each condition can give. `UNKNOWN` is a first-class state
#: rather than a shade of `OUTSIDE`: this file's original defect on the work-tree
#: side was folding "git could not be asked" into the clean answer, and repeating
#: it on the home side would be the same bug wearing this change's fix.
INSIDE, OUTSIDE, UNKNOWN = "inside", "outside", "unknown"

#: rc contract of the preflight CLI. See EXIT CODES in the module docstring.
RC_PASS, RC_FINDING, RC_UNDETERMINED, RC_BAD_INVOCATION = 0, 1, 2, 3

#: Substring git prints when it looked and there is no repository. Matched so
#: that the OTHER 128s — "detected dubious ownership", a broken `.git` file — are
#: not silently credited as a clean "outside". They are `UNKNOWN`.
_GIT_SAYS_NO_REPO = "not a git repository"


def scratch_root(config) -> Path:
    """The directory pytest will put `tmp_path` under, as pytest picks it.

    `--basetemp` when given, otherwise the platform temp root — which is what
    `TMPDIR` moves. Read from pytest's own resolved option rather than
    recomputed by the caller, so the guard and the fixture cannot disagree
    about which directory is at issue.
    """
    given = getattr(config.option, "basetemp", None)
    return Path(given).resolve() if given else Path(tempfile.gettempdir()).resolve()


def _nearest_existing(p: Path) -> Path:
    """`--basetemp` need not exist yet; git must be asked about a real path."""
    cur = p
    while not cur.is_dir() and cur != cur.parent:
        cur = cur.parent
    return cur


def resolve_scratch_root(raw: Path) -> Tuple[Optional[Path], Optional[str]]:
    """(resolved root, None) — or (None, why it could not be resolved).

    `Path.resolve()` is not total: a symlink loop or a component the caller
    cannot traverse raises, and a guard that dies with a traceback there has
    answered nothing while looking like a crash in whatever invoked it. "I could
    not tell where the root is" is a state this guard reports BY NAME, with the
    path it failed on, and never as a pass.
    """
    try:
        return raw.resolve(), None
    except (OSError, RuntimeError) as exc:
        return None, f"{raw}: {exc}"


def work_tree_state(d: Path) -> Tuple[str, Optional[str], Optional[str]]:
    """(INSIDE | OUTSIDE | UNKNOWN, toplevel or None, reason when UNKNOWN).

    `enclosing_work_tree` folded UNKNOWN into "no toplevel" and the CLI then
    reported it as a clean pass. The three are kept apart here because they are
    three different facts, and because "I could not look" credited as "I looked
    and there is nothing" is precisely the green-from-an-empty-denominator this
    repo refuses everywhere else.

    UNKNOWN is deliberately NOT a refusal in the pytest hook: refusing on "I
    could not look" would make an absent `git` unable to run the suite at all.
    """
    try:
        r = subprocess.run(["git", "-C", str(_nearest_existing(d)),
                            "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=_GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return UNKNOWN, None, f"git could not be asked: {exc}"
    if r.returncode == 0:
        top = r.stdout.strip()
        if top:
            return INSIDE, top, None
        return UNKNOWN, None, "git reported success with no toplevel"
    err = (r.stderr or "").strip()
    if _GIT_SAYS_NO_REPO in err:
        return OUTSIDE, None, None
    return UNKNOWN, None, f"git exited {r.returncode}: {err[:200] or '(no stderr)'}"


def enclosing_work_tree(d: Path) -> Optional[str]:
    """Toplevel of the git work tree containing `d`, or None.

    Kept as the two-state view for callers that only need "is it inside", and
    kept returning None for UNKNOWN so no existing reader silently changes
    meaning. Anything that must tell UNKNOWN from OUTSIDE calls
    `work_tree_state` instead.
    """
    return work_tree_state(d)[1]


def host_account_home() -> Tuple[Optional[Path], Optional[str]]:
    """(the host account home, None) — or (None, why it could not be resolved).

    Asked EXACTLY as `tools/ci/hermetic_candidate_runner.py::_home_path` asks
    it, and for the same reason `scratch_root` reads pytest's own resolved
    option rather than recomputing it: the guard and the thing it predicts must
    not be able to disagree about the subject.

    In particular this is `pwd`, NOT `$HOME`. Inside the pinned candidate image
    the runner itself sets `HOME=/tmp` with `TMPDIR=/tmp`, so a `$HOME`-based
    check would call the landing's own scratch root a finding and block every
    landing.
    """
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True), None
    except (KeyError, OSError) as exc:
        return None, f"cannot resolve the host account home: {exc}"


def home_state(root: Path) -> Tuple[str, Optional[Path], Optional[str]]:
    """(INSIDE | OUTSIDE | UNKNOWN, the home or None, reason when UNKNOWN).

    Containment is `Path.relative_to`, which is what `_resolve_mount` uses via
    `_inside`. No normalisation of its own: an account home of `/` would make
    every root INSIDE — and that is not a bug to special-case, because on such a
    host the runner refuses every mount too. Diverging here to be kinder would
    make this guard predict a refusal that does not happen and miss one that
    does.
    """
    home, why = host_account_home()
    if home is None:
        return UNKNOWN, None, why
    try:
        root.relative_to(home)
    except ValueError:
        return OUTSIDE, home, None
    return INSIDE, home, None


#: The gate whose classification this condition predicts.  Read from the gate
#: rather than copied, for the reason the module docstring gives about `$HOME`:
#: a guard that asks its question differently from the thing it predicts will
#: confidently answer about a different subject.  A second copy of four string
#: literals is exactly the drift this repo keeps measuring.
_VOLATILE_AUTHORITY = "project_outputs_in_tree_check.py"


def volatile_prefixes() -> Tuple[Optional[Tuple[str, ...]], Optional[str]]:
    """(the gate's own volatile prefixes, None) — or (None, why not).

    Loaded BY PATH from the sibling program, so the answer does not depend on
    `sys.path`, on the working directory, or on this file having been imported
    as a package member.  A failure here is UNKNOWN and says so; it is never a
    silently empty tuple, which would make every root look non-volatile and
    refuse every session.
    """
    try:
        spec = importlib.util.spec_from_file_location(
            "_scratch_root_guard_volatile_authority",
            Path(__file__).resolve().with_name(_VOLATILE_AUTHORITY))
        if spec is None or spec.loader is None:
            return None, f"{_VOLATILE_AUTHORITY} could not be loaded"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        prefixes = tuple(getattr(module, "_VOLATILE_PREFIXES"))
    except Exception as exc:                       # noqa: BLE001 — reported, not raised
        return None, (f"cannot read the volatile-prefix authority "
                      f"{_VOLATILE_AUTHORITY}: {exc}")
    if not prefixes or not all(isinstance(x, str) and x.startswith("/")
                               for x in prefixes):
        return None, (f"{_VOLATILE_AUTHORITY} declares no usable volatile "
                      f"prefix: {prefixes!r}")
    return prefixes, None


def volatile_state(root: Path
                   ) -> Tuple[str, Optional[Tuple[str, ...]], Optional[str]]:
    """(INSIDE | OUTSIDE | UNKNOWN, the prefixes or None, reason when UNKNOWN).

    THE POLARITY IS INVERTED HERE AND THAT IS DELIBERATE.  `INSIDE` means the
    root IS under one of the gate's volatile prefixes, which is the GOOD answer;
    `OUTSIDE` is the finding.  The three state names are reused rather than a
    fourth vocabulary invented, because a reader who has just read the other two
    conditions should not have to learn new words to read this one — and the
    declaration and the refusal below both say which way round it is, in words.

    Containment is a PREFIX test on the resolved path, matching the gate, which
    does `str(path).startswith(prefix)` on strings ending in `/`.  The root
    itself (`/tmp`, with no trailing slash) counts as inside: a scratch root AT
    a volatile prefix is the pytest default.
    """
    prefixes, why = volatile_prefixes()
    if prefixes is None:
        return UNKNOWN, None, why
    text = str(root)
    for prefix in prefixes:
        if text == prefix.rstrip("/") or text.startswith(prefix):
            return INSIDE, prefixes, None
    return OUTSIDE, prefixes, None


def classify(config) -> Tuple[Path, Optional[str], bool, str]:
    """(scratch root, enclosing work tree or None, allowance in force, state).

    The fourth element is the tri-state `work_tree_state` verdict. It is
    appended rather than substituted so a caller holding the historical
    three-tuple keeps its meaning.
    """
    root = scratch_root(config)
    allowed = bool(getattr(config.option, "allow_scratch_root_in_repo", False)) \
        or os.environ.get(_ENV_ALLOW, "") not in ("", "0")
    state, top, _ = work_tree_state(root)
    return root, top, allowed, state


_REFUSAL = """\
the pytest scratch root is INSIDE a git work tree, and this suite cannot be
measured from there.

    scratch root : {root}
    work tree    : {top}

`git -C <dir> ls-files` does not FAIL inside a checkout — it succeeds and
answers about that checkout, scoped to <dir>, which is ZERO paths for a
directory nobody committed. Fixtures that build an untracked corpus under
`tmp_path` are then enumerated as empty, and the gates correctly report
"published nothing". Each such test names its own subject rather than this
root, so the cause is nowhere in the failure output. What it costs, RE-MEASURED
on 4b3843f22c — one pytest process per file, only `--basetemp` different, a
root inside a throwaway work tree against a root outside every repository:

    programs/tests/test_published_record_staleness_check.py         35
    programs/tests/test_issue905_ic_level_layout_contract.py         6
    programs/tests/test_issue967_empty_ic_unit_examined_nothing.py   5

46 in a tree whose real count for them is 0 (vibe-ic#1446) — the same 46, over
the same three files, that #1446's own correction named. THAT TABLE IS RUN, not
read: `test_issue1446_scratch_root_guard.py::test_every_line_of_the_work_tree_
cost_table_fires` measures each line every session, because the OTHER condition
this guard used to refuse on was a remembered number that had quietly become 0.

FIX: put the scratch root outside any repository. pytest's own default
already is — the usual cause is an exported TMPDIR.

    env -u TMPDIR pytest ...
    pytest --basetemp=/tmp/<something-outside-any-repo> ...

If this environment genuinely has no writable tmp outside a checkout, run
with {flag} (or {env}=1). The run then
declares the allowance, so a count taken from it still carries the reason
not to trust it."""


_HOME_REFUSAL = """\
the scratch root is UNDER the host account home, and the hermetic lane will
refuse every mount taken from it.

    scratch root      : {root}
    host account home : {home}

`hermetic_candidate_runner._resolve_mount` raises

    Refusal: subject would expose the host HOME to the candidate

for the subject, the runtime, the corpus, the selection and the progress plan
alike — and `gatekeeper-verify-merge.sh` mounts a subject it made with
`mktemp -d`, which is this same root. The arm then records NOTHING, and the
validator can only report the symptom it shares with every other cause of an
absent receipt: "cannot resolve runner receipt: No such file or directory".
An operator lost half an hour to exactly this, working backwards from an empty
arm (vibe-ic#1446, second condition).

FIX: put the scratch root outside the account home. The platform default
already is — the usual cause is an exported TMPDIR.

    env -u TMPDIR ...
    TMPDIR=/tmp/<something-outside-the-account-home> ...

There is NO waiver for this one. Waiving it would not make `_resolve_mount`
accept the mount; it would buy a green preflight and the identical NORECORD
ten minutes later."""


_VOLATILE_ADVISORY = """\
the scratch root is NOT under a volatile root. This is DECLARED, and it is not
a finding: the cost of running here is re-measured below and it is zero.

    scratch root     : {root}
    volatile roots   : {prefixes}

`programs/project_outputs_in_tree_check.py` calls a path external storage iff
it starts with one of those four prefixes and nothing else. A test that builds
its subject at `tmp_path` and requires the gate to FIND it would get a PASS
where it requires a FAIL, and would report its own fixture as the defect. THAT
MECHANISM HAS NOT CHANGED. What changed is that no test in this suite is
exposed to it any more, because each one builds its own subject under one of
the four prefixes and asserts it landed there.

RE-MEASURED on 4b3843f22c (v1.16.90), one pytest process per file, only
`--basetemp` different — `/tmp/...` against a non-volatile root outside every
work tree:

    programs/tests/test_project_outputs_in_tree_check.py             0
    programs/tests/test_issue146_collect_external_outputs.py         0
    ------------------------------------------------------------- ---
    total                                                           0

    (this guard's own file is the third member of that population and also
     costs 0; the arm that runs this table skips it, because running it here
     would run that arm.)

THIS TABLE IS RUN, NOT READ. `test_issue1446_scratch_root_guard.py::
test_every_line_of_this_cost_table_fires` measures each line from a
non-volatile root every session. It is the reason you are reading an advisory
rather than a refusal: the line above said 2 for six days after the v1.16.85
landing made it 0, and before that the same table said 4 for a file fc32402c8
had already made clean. A refusal resting on a number nobody re-runs becomes a
ban nobody can argue with.

WHAT TO DO ABOUT IT: nothing is required. If you would rather this condition
were clean too, pytest's own default already is — the usual cause is an
exported TMPDIR.

    env -u TMPDIR pytest ...
    TMPDIR=/var/tmp/<something> pytest ...
    pytest --basetemp=/tmp/<something> ...

AND IF A LINE ABOVE EVER LEAVES 0, the fix is in that file's FIXTURE — build
the subject under a volatile prefix and assert it, the way `volatile_dir` and
`volatile_project` do — not in the gate, whose four-prefix scope is what it is
FOR, and not by widening what this guard calls volatile."""


def pytest_addoption(parser):
    parser.addoption(
        _FLAG, action="store_true", default=False,
        help="Run even though the pytest scratch root is inside a git work "
             "tree. Disclosed in the run header; see vibe-ic#1446.")


def declaration(config, verdict=None) -> str:
    """The one line every run states about the root it measured from.

    `verdict` lets a caller that already classified pass the answer in, so one
    session asks git once. Recomputing would also let the declaration and the
    refusal disagree if the tree moved between them — a small window, but this
    guard exists because a run said something other than what it did.
    """
    v = verdict if verdict is not None else classify(config)
    root, top, allowed = v[0], v[1], v[2]
    # A caller holding the historical three-tuple cannot say WHICH of the two
    # answers `top is None` meant, so it keeps the wording that claims neither.
    tri = v[3] if len(v) > 3 else None
    if top is None:
        if tri == UNKNOWN:
            return (f"scratch_root_guard: {root} — NOT CHECKED against any git "
                    f"work tree (git could not be asked)")
        if tri == OUTSIDE:
            return f"scratch_root_guard: {root} — outside any git work tree"
        return (f"scratch_root_guard: {root} — outside any git work tree "
                f"(or git could not be asked)")
    state = "ALLOWED BY FLAG — results from this run are not trustworthy" \
        if allowed else "REFUSED"
    # "git work tree" is this condition's name everywhere else it is
    # spoken — the three branches above, and the refusal text itself
    # ("the pytest scratch root is INSIDE a git work tree"). This branch
    # alone said "work tree", and it is the branch that fires on the
    # REFUSAL path, where the declaration is the only thing telling the
    # reader WHICH condition stopped the run.
    return f"scratch_root_guard: {root} — INSIDE git work tree {top} [{state}]"


def home_declaration(root: Path, verdict=None) -> str:
    """The second line every run states: is this root under the account home.

    Declared on EVERY run, whatever the answer, and the home is NAMED in all
    three states. A guard that reports only the condition it refused on leaves
    the next reader to work out from a NORECORD which of two things went wrong
    — which is the half hour this whole change exists to stop anyone spending
    again.
    """
    state, home, why = verdict if verdict is not None else home_state(root)
    if state == INSIDE:
        return (f"scratch_root_guard: {root} — UNDER the host account home "
                f"{home} [hermetic mounts from here are REFUSED]")
    if state == OUTSIDE:
        return (f"scratch_root_guard: {root} — outside the host account home "
                f"{home}")
    return (f"scratch_root_guard: {root} — host account home NOT CHECKED "
            f"({why}); there is no host home to expose from here")


def volatile_declaration(root: Path, verdict=None) -> str:
    """The third line every run states: is this root one the gates can see.

    Printed in all three states and naming the prefixes in each, for the reason
    the home line is: a run that refused on one of three conditions and named
    none of them sends the next reader back to the half hour this file exists
    to stop anyone spending again.
    """
    state, prefixes, why = verdict if verdict is not None else volatile_state(root)
    shown = ", ".join(prefixes) if prefixes else "(unknown)"
    if state == INSIDE:
        return (f"scratch_root_guard: {root} — under a volatile root "
                f"({shown})")
    if state == OUTSIDE:
        return (f"scratch_root_guard: {root} — NOT under a volatile root "
                f"({shown}) [the external-storage gate cannot see a subject "
                f"built here]")
    return (f"scratch_root_guard: {root} — volatile root NOT CHECKED ({why})")


def pytest_report_header(config):
    """The verbose header. Not sufficient on its own — see `pytest_configure`."""
    verdict = classify(config)
    return [declaration(config, verdict), home_declaration(verdict[0]),
            volatile_declaration(verdict[0])]


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
    root, top, allowed = verdict[0], verdict[1], verdict[2]
    # DECLARED, NOT BLOCKING, here — see BLOCKING in the module docstring. A
    # pytest session under the account home is measurable; it is the hermetic
    # lane that breaks, and the hermetic lane asks the preflight CLI below.
    print("[INFO] " + home_declaration(root))
    # DECLARED, NOT BLOCKING, here — and for the same reason the home condition
    # is: EVERY root under a real account home is outside all four volatile
    # prefixes, so refusing in the hook would refuse every under-home session,
    # which this file already pins as a supported and measurable shape
    # (`test_the_hook_does_not_refuse_a_measurable_run_under_the_account_home`).
    # Two of ~3200 tests are falsified by such a root; the other ~3198 are
    # measured correctly, and taking them all down to catch two is the harm
    # this guard is supposed to prevent, not cause.
    #
    # The BLOCK is in the preflight CLI instead, which is where the harm lands:
    # `gatekeeper-land.sh:872` asks it before the arms, and a LANDING is what
    # publishes a count. The declaration below is what stops those two from
    # being causeless — it names the root and what cannot see it, on the third
    # line of every session, before any result.
    vol_state, vol_prefixes, _vol_why = volatile_state(root)
    print("[INFO] " + volatile_declaration(
        root, verdict=(vol_state, vol_prefixes, _vol_why)))
    if top is not None and not allowed:
        raise pytest.UsageError(
            "scratch_root_guard: " + _REFUSAL.format(
                root=root, top=top, flag=_FLAG, env=_ENV_ALLOW))


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

    It asks ALL THREE conditions, because each of them makes a lane produce
    something other than a measurement, and a preflight that answers two of
    three is a preflight the next reader still has to debug behind. It CHARGES
    for two of them: the volatile condition is declared and costs nothing, and
    the module docstring's BLOCKING block carries the measurement that demoted
    it.

    rc 0  PASS — outside every condition that costs something. A non-volatile
          root prints `[ADVISORY]` and lands here.
    rc 1  a FINDING about the root — INSIDE a work tree, or UNDER the host
          account home
    rc 2  UNDETERMINED / NOT CHECKED, naming what could not be determined
    rc 3  bad invocation

    See EXIT CODES in the module docstring for why the work-tree finding moved
    off rc 2, and for the measured blast radius of moving it.

    FINDING BEATS UNDETERMINED, the same way `_vacuous_exit` puts FAIL above
    VACUOUS: a root can be under the account home while git is missing, and
    reporting the unchecked half would bury the half that was checked and found.
    """
    import argparse

    class _Parser(argparse.ArgumentParser):
        """argparse exits 2 on a usage error, and 2 is UNDETERMINED here.

        Left alone, `--typo` would report itself as "I could not determine
        something" — a wrong answer to a question that was never asked. rc 3 is
        the bad-invocation code in this contract, so the parser is made to use
        it. `--help` still exits 0 through `exit()` with an explicit code.
        """

        def error(self, message):
            self.print_usage(sys.stderr)
            sys.stderr.write(f"{self.prog}: error: {message}\n")
            raise SystemExit(RC_BAD_INVOCATION)

    ap = _Parser(
        description="Refuse a pytest scratch root that falsifies the run "
                    "(vibe-ic#1446).")
    ap.add_argument("--scratch-root", default=None,
                    help="Directory to test. Default: the platform temp root, "
                         "which is what pytest uses when --basetemp is unset, "
                         "and what `mktemp -d` gives the hermetic lane.")
    ap.add_argument("--allow", action="store_true",
                    help="Waive the WORK-TREE refusal only. Still prints the "
                         "verdict. There is deliberately no waiver for the "
                         "account-home finding — see the module docstring.")
    ap.add_argument("--require-home-check", action="store_true",
                    help="Treat 'the host account home could not be resolved' "
                         "as rc 2 instead of a declared NOT CHECKED. The "
                         "landing does not pass this: inside the pinned image "
                         "the account home never resolves, so it would fail "
                         "every landing.")
    a = ap.parse_args(argv)

    raw = Path(a.scratch_root) if a.scratch_root else Path(tempfile.gettempdir())
    root, why = resolve_scratch_root(raw)
    if root is None:
        print(f"[NOT CHECKED] scratch_root_guard: cannot resolve the scratch "
              f"root — {why}. Neither condition was checked; this is not a "
              f"pass.")
        return RC_UNDETERMINED

    tree, top, tree_why = work_tree_state(root)
    home, home_dir, home_why = home_state(root)
    vol, vol_prefixes, vol_why = volatile_state(root)
    allowed = a.allow or os.environ.get(_ENV_ALLOW, "") not in ("", "0")

    # Both lines print in every outcome. The reader must be able to tell which
    # condition fired without re-running anything.
    print("[INFO] " + declaration(None, verdict=(root, top, allowed, tree)))
    print("[INFO] " + home_declaration(root, verdict=(home, home_dir, home_why)))
    print("[INFO] " + volatile_declaration(
        root, verdict=(vol, vol_prefixes, vol_why)))

    finding = False
    if tree == INSIDE:
        print("[FAIL] scratch_root_guard: " + _REFUSAL.format(
            root=root, top=top, flag=_FLAG, env=_ENV_ALLOW))
        if allowed:
            print("[ALLOWED] refusal waived; results from a run here are not "
                  "trustworthy and a count taken from one carries this caveat.")
        else:
            finding = True
    if home == INSIDE:
        print("[FAIL] scratch_root_guard: " + _HOME_REFUSAL.format(
            root=root, home=home_dir))
        finding = True
    if vol == OUTSIDE:
        # DECLARED, NEVER CHARGED FOR. `finding` is deliberately not touched
        # here: the cost this condition used to refuse on was re-measured at
        # 4b3843f22c and is 0, and a refusal whose cost is zero stops runs the
        # suite can measure perfectly in exchange for nothing. The advisory
        # still names the mechanism and states the re-measured table, so the
        # reader who meets a failure in one of those files can tell "the gate
        # is broken" from "this subject was built where the gate cannot look".
        # See the BLOCKING block in the module docstring.
        print("[ADVISORY] scratch_root_guard: " + _VOLATILE_ADVISORY.format(
            root=root, prefixes=", ".join(vol_prefixes or ())))
    if finding:
        return RC_FINDING

    # `vol_why` is still here even though the volatile condition charges
    # nothing, and that is not an oversight. The ONLY way it goes UNKNOWN is
    # that `project_outputs_in_tree_check.py` could not be loaded from beside
    # this file — a broken plugin tree, not a fact about the root — and a
    # preflight that swallowed that would be answering about a subject it never
    # reached. It is reported as NOT CHECKED, by name, exactly as before.
    unchecked = [w for w in (tree_why if tree == UNKNOWN else None,
                             home_why if (home == UNKNOWN and
                                          a.require_home_check) else None,
                             vol_why if vol == UNKNOWN else None) if w]
    if unchecked:
        for w in unchecked:
            print(f"[NOT CHECKED] scratch_root_guard: {w}")
        print("[NOT CHECKED] a condition this root must satisfy was not "
              "determined; this is not a pass.")
        return RC_UNDETERMINED

    print(f"[PASS] scratch_root_guard: {root} — a pytest run here is "
          f"measurable and a hermetic mount from here is accepted.")
    return RC_PASS


if __name__ == "__main__":
    raise SystemExit(_main())
