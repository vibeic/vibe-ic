"""A test switch that never reaches the process it switches is not a test.

BLOCKING. A failure here stops the suite, and it should: what it detects is a
test that PASSES while measuring nothing, which is the one defect no later
reader can see.

WHAT THIS REFUSES, and every clause was a measured defect
========================================================
`test_landing_merge_verdict.py` drives the landing verifier end to end. Some of
its scenarios need the SUBJECT — the code inside a hermetic arm — to behave
badly on purpose, and the fixture arranges that by planting a stub
`tools/gatekeeper-land.sh` whose branches read environment variables the test
sets on the verifier process.

An arm is a container. `tools/ci/hermetic_candidate_runner.py` is launched with
an explicit `--env NAME=VALUE` list and the container gets nothing else, so a
variable that is not on that list is EMPTY inside the arm and every branch
keyed on it is skipped. MEASURED on a4caccefe: of the six switches that file's
stubs used, exactly ONE reached an arm. Five scenarios were therefore asserting
the outcome of something that had never been attempted — four of them RED for
what looked like a defect in the verifier, and one of them GREEN, which is
worse: `test_end_to_end_candidate_cannot_prewrite_base_wave_artifacts` asserted
that a planted line was absent from the output, and no line had ever been
planted. Two sessions were spent on that file before the common cause was
named.

THE RULE, and all three of its inputs are DERIVED, never hand-typed
===================================================================
For every environment variable N such that

    (a) a test passes N to the verifier subprocess (an `env=` or `env_extra=`
        dict literal, found by walking the test module's AST), AND
    (b) subject-side code DEREFERENCES N — `$N` or `${N` on a non-comment
        line of the stub landing gate, which is written into the fixture's
        `tools/gatekeeper-land.sh` and therefore runs INSIDE an arm,

N must appear in the hermetic launcher's `--env` list.

The intersection is what makes it precise, and both directions matter:

  * (a) without (b) is fine — `GATEKEEPER_CONCURRENCY_PROBE_DIR` is set by a
    test and read only by the parent shell's `cleanup_event`, host-side, which
    is exactly where it can work.
  * (b) without (a) is fine — `GATEKEEPER_STUB_ROUTED_TRANSITION` still appears
    in the stub, but no test sets it any more: `_routed_activation_repo`
    rewrites that branch to key on committed subject content, which does reach
    an arm.

Reading the allow-list out of the launcher rather than restating it here is the
load-bearing part. A hand-typed copy of a canonical set is the defect
`test_tier_pipeline_gate_parity` exists to catch, and it had already happened
once in this repository: `gates_atomic.py` carried a copy of the emit-blocking
rule set and drifted from it for 515 commits. A guard that repeats that mistake
guards nothing.

WHAT IT CANNOT SEE, AND HOW MUCH THAT COSTS TODAY
=================================================
Only the stub in THIS module. That scope was measured rather than assumed:
of the seven test modules in the repository that name `GATEKEEPER_VERIFY_ARM`
or the hermetic runner, exactly one other passes environment dicts to a
subprocess -- `tools/test_gatekeeper_land_differential_removed.py` -- and it
runs `tools/gatekeeper-land.sh` and `tools/git-hooks/pre-push` as HOST
subprocesses, with no container between the variable and the reader, so its
switches arrive and the class cannot occur there. (Before 2026-08-28 that module
was `test_gatekeeper_land_differential.py` and the subprocess it ran was the
two-arm driver; the driver was removed, the reasoning is unchanged.) The remaining five construct the runner's `--env` list
explicitly, which is the boundary itself rather than something crossing it
unexamined.

So the gap this check leaves is a FUTURE one: a fixture that plants
subject-side behaviour somewhere else. The honest place to say so is here
rather than in a commit message nobody re-reads.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from _hostpaths import require_repo

# THE IMPORT IS THE POINT, not the names. `ci_targeted_test_select.py` runs in
# import-edge mode, so a test that reaches its subject only by PATH is
# INVISIBLE to it: measured on a diff touching nothing but
# test_landing_merge_verdict.py, the selector chose 19 files and this one was
# not among them -- the guard would not have run at the moment it matters.
# Importing the module it inspects is the edge that fixes that, and it costs
# nothing at runtime: the subject's module level only defines constants.
import test_landing_merge_verdict as _subject  # noqa: F401,E402

_HERE = Path(__file__).resolve()
# Both subjects are CHECKED-IN REPOSITORY ARTEFACTS, resolved through the
# repo's own helper rather than by counting `.parents[...]` from this file.
# Two reasons, and neither is style: `require_repo` SKIPS on the installed
# plugin cache, where the monorepo is simply absent and hand-rolled path
# arithmetic would instead point at a directory that does not exist and read
# as a clean answer; and `real_artefact_test_backing_check` can see the helper,
# so this module reports as what it is -- a test driven by real in-repo files,
# not by fixtures authored beside it. They are resolved inside the fixture
# because `require_repo` skips, and a skip at import time is not a skip.
_VERIFY_PARTS = ("tools", "gatekeeper-verify-merge.sh")
_SUBJECT_PARTS = ("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                  "tests", "test_landing_merge_verdict.py")

# The stub landing gate is this module-level constant, written into the
# fixture's tools/gatekeeper-land.sh. Named, not guessed: if it is renamed the
# check says NOT CHECKED rather than passing over an empty string.
_STUB_CONSTANT = "_STUB_LAND"
_ENV_KEYWORDS = ("env", "env_extra")
_SWITCH = re.compile(r"\b(GATEKEEPER_[A-Z0-9_]+)")
# A BRANCH DEREFERENCES. `$NAME` or `${NAME` is a read; a name sitting in a
# comment is not, and this check's FIRST sweep flagged a false positive for
# exactly that reason -- the comment that records which dead switches were
# deleted names all four of them. A gate that fires on a legitimately clean
# tree is a bug in the gate.
_DEREF = re.compile(r"\$\{?(GATEKEEPER_[A-Z0-9_]+)")


def _launcher_env_allowlist(text):
    """Every NAME the launcher forwards into an arm, read from the launcher."""
    names = set()
    for body in re.findall(
            r"^launch_hermetic_\w+_arm\(\) \{(.*?)^\}", text,
            re.MULTILINE | re.DOTALL):
        names.update(re.findall(r'--env\s+"?([A-Za-z_][A-Za-z0-9_]*)=', body))
    return names


def _switches_a_test_hands_the_verifier(tree):
    """Names used as keys of an `env=`/`env_extra=` dict literal, by AST.

    A dict literal is what the fixture actually writes, and reading it from the
    syntax tree rather than by regex means a name inside a docstring or a
    comment — this file is full of both — cannot be mistaken for one that is
    passed.
    """
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg not in _ENV_KEYWORDS:
                continue
            for value in ast.walk(keyword.value):
                if isinstance(value, ast.Dict):
                    for key in value.keys:
                        if (isinstance(key, ast.Constant)
                                and isinstance(key.value, str)):
                            names.update(_SWITCH.findall(key.value))
    return names


def _switches_the_subject_branches_on(tree):
    """Names the stub landing gate dereferences, read from its own source."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if _STUB_CONSTANT not in targets:
            continue
        if not (isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            return None
        script = "\n".join(
            line for line in node.value.value.splitlines()
            if not line.lstrip().startswith("#"))
        return set(_DEREF.findall(script))
    return None


@pytest.fixture(scope="module")
def measured():
    verify = require_repo(*_VERIFY_PARTS)
    subject = require_repo(*_SUBJECT_PARTS)
    tree = ast.parse(subject.read_text(encoding="utf-8"))
    return {
        "verify": verify,
        "subject": subject,
        "tree": tree,
        "verify_text": verify.read_text(encoding="utf-8"),
        "forwarded": _launcher_env_allowlist(verify.read_text(encoding="utf-8")),
        "handed": _switches_a_test_hands_the_verifier(tree),
        "branched": _switches_the_subject_branches_on(tree),
    }


def test_the_three_inputs_were_actually_read(measured):
    """DEGRADE LOUDLY. An empty answer and a clean answer print the same.

    Each of the three sets is derived by locating a construct that could be
    renamed out from under this file. If any of them comes back empty the
    check below would pass over nothing at all, so the emptiness is the
    failure, stated before any verdict is computed.
    """
    assert measured["forwarded"], (
        f"no `--env NAME=` forwarding found in {measured['verify']} — the "
        f"allow-list this "
        f"check compares against was not read, so NOTHING WAS CHECKED")
    assert measured["handed"], (
        f"no env=/env_extra= dict literal found in {measured['subject'].name} — the "
        f"switches a test hands the verifier were not read, so NOTHING WAS "
        f"CHECKED")
    assert measured["branched"] is not None, (
        f"{_STUB_CONSTANT} is not a plain string constant in "
        f"{measured['subject'].name} — the subject-side branches were not read, so "
        f"NOTHING WAS CHECKED")
    assert measured["branched"], (
        f"{_STUB_CONSTANT} names no GATEKEEPER_* switch at all, which has "
        f"never been true of it — read it before trusting a clean answer")


def test_every_switch_a_test_sets_and_the_subject_reads_reaches_the_arm(
        measured):
    """THE RULE. Its violation is a test that measures nothing."""
    unreachable = sorted(
        (measured["handed"] & (measured["branched"] or set()))
        - measured["forwarded"])
    assert unreachable == [], (
        "these switches are set by a test AND branched on by the subject-side "
        "landing gate, but the hermetic launcher does not forward them, so "
        "inside an arm each is EMPTY and its branch never runs — every "
        "scenario keyed on one of them asserts the outcome of something that "
        f"was never attempted: {unreachable}. Either forward it in "
        f"{measured['verify'].name}, or express the stimulus through a channel "
        "that "
        "reaches an arm (committed subject content does; so does the parent's "
        "own run directory, from the host).")


def test_the_allowlist_is_read_from_the_launcher_and_not_restated_here(
        measured):
    """A hand-typed copy of a canonical set drifts from it. Measured in this
    repository: `gates_atomic.py` carried a copy of the emit-blocking rule set
    and was 515 commits out of date when it was found. So this file must not
    contain a literal allow-list of its own; the names it compares against have
    to come out of the launcher.
    """
    source = _HERE.read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]
    quoted = {name for name in _SWITCH.findall(body)}
    restated = sorted(quoted & measured["forwarded"])
    assert restated == [], (
        "this file names forwarded switches in its own code, which is the "
        f"beginning of a copy that will drift: {restated}")


def _probe_dir_variables(tree, unforwarded):
    """Local variables whose value is handed to the verifier as a NON-forwarded
    environment variable — i.e. a directory the parent names and the arm cannot.

    `{"GATEKEEPER_CONCURRENCY_PROBE_DIR": str(probe)}` yields `{"probe"}`.
    """
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value in unforwarded):
                continue
            for inner in ast.walk(value):
                if isinstance(inner, ast.Name):
                    names.add(inner.id)
    return names


def _awaited_basenames(tree, variables):
    """Filenames the test builds UNDER one of those directories.

    `probe / "cleanup.done"` -> "cleanup.done";
    `probe / f"{arm}.pid"`   -> ".pid"  (the constant part is what identifies
    the writer; the arm name is not knowable statically and does not need to
    be).
    """
    found = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
            continue
        if not (isinstance(node.left, ast.Name) and node.left.id in variables):
            continue
        right = node.right
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            found.add(right.value)
        elif isinstance(right, ast.JoinedStr):
            literal = "".join(v.value for v in right.values
                              if isinstance(v, ast.Constant)
                              and isinstance(v.value, str))
            if literal:
                found.add(literal)
    return found


def test_a_file_the_test_waits_for_must_have_a_host_side_writer(measured):
    """THE SECOND SHAPE, and a real instance got past the first one.

    The rule above catches a stub BRANCH keyed on a switch that reaches no arm.
    It does not catch a test that simply WAITS for a file only an arm could
    have written — no branch, no dereference, just a poll that can never end.

    MEASURED 2026-08-22 on `land/two-assembled` b1b654943ece: a later revision
    of `_assert_interruption_cleans_every_parallel_arm` waits for
    `probe / f"{hung_arm}.pid"`, where `probe` is the value handed to
    `GATEKEEPER_CONCURRENCY_PROBE_DIR` — which is NOT on the launcher's `--env`
    allow-list, so inside the arm that variable is empty and no `<ARM>.pid` is
    ever written. Both interruption ids fail there, on the batch tip alone, at
    load 4. The comment immediately above that wait still records why it cannot
    work: it is the note left by the revision that had removed it.

    THE DISCRIMINATOR IS WHO WRITES THE FILE, and it is decidable: the parent
    shell writes `cleanup.<event>` into that same directory from
    `cleanup_event`, host-side, so waiting on `cleanup.done` is legitimate and
    must NOT be flagged. A basename the verifier script never produces has no
    host-side writer at all, which leaves only the arm — and the arm cannot
    reach the directory.
    """
    unforwarded = (measured["handed"] or set()) - measured["forwarded"]
    variables = _probe_dir_variables(measured["tree"], unforwarded)
    awaited = _awaited_basenames(measured["tree"], variables)
    script = measured["verify_text"]

    def host_writes(name):
        # The script COMPOSES the name it writes -- `cleanup.$event` -- so the
        # awaited `cleanup.done` never appears there literally. Its constant
        # prefix through the first dot does, and that is what identifies the
        # writer. FIRST SWEEP OF THIS RULE flagged all three cleanup events on
        # a clean tree for exactly that reason; a gate that fires on a
        # legitimately clean tree is a bug in the gate.
        if name in script:
            return True
        head, dot, _ = name.partition(".")
        return bool(dot and head and (head + dot) in script)

    orphans = sorted(name for name in awaited if not host_writes(name))
    assert orphans == [], (
        "these filenames are awaited under a directory the parent names "
        "through an environment variable the hermetic launcher does NOT "
        "forward, and the verifier script never writes them, so the only "
        f"possible writer is an arm that cannot see the directory: {orphans}. "
        "Wait on something the PARENT writes (cleanup_event does), or observe "
        "the arm host-side.")
