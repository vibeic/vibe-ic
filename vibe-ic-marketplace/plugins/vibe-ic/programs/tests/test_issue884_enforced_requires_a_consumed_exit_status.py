#!/usr/bin/env python3
"""ORGANIC #884 — ENFORCED must mean "the exit status can stop the step", not
"the filename appears inside a string", AND it must not move when the source is
reshaped without changing what it does.

ROUND 1. `flow_gate_enforcement_audit` decided ENFORCED from `_invoked()`,
which asks whether the gate's filename appears in a string literal somewhere in
a runner. A runner that spawns a gate and throws the exit status away is
TEXTUALLY IDENTICAL to one that stops the step on it, so the audit scored the
first as enforcement. Four gates were named ENFORCED while their verdict was
discarded:

    rtl_hygiene_lint   `rc, out, err = _run([...])`, `rc` never read again
    dfm_screen_check   `subprocess.run(...)` with the result not bound at all
    bsdl_emit          the same, inside `except Exception: pass`; the
                       `r.returncode` eleven lines later is a DIFFERENT
                       subprocess (the ATPG run)
    sdc_syntax_check   `r = subprocess.run(...)`, `r.returncode` never read

ROUND 2 — WHY THIS FILE GREW. An independent verifier refuted round 1 with one
move, and it is reproduced verbatim below (`test_884_R_*`, and
`test_884_the_verifiers_exact_refactor_*` on the real tree):

    Apply the textbook `extract method` refactor to the very call site the
    finding names — design_one_shot_runner.py:11128 — and `bsdl_emit` went
    back to ENFORCED. MEASURED on round 1's classifier: 16 -> 17 ENFORCED,
    `bsdl_emit` INLINE_STATUS_IGNORED -> INLINE_BLOCKING. The refactor changes
    nothing: same argv, same `except Exception` swallow, same discarded result
    at the one call site.

Round 1 had filed `return` alongside `raise` and `sys.exit` as a control-flow
"escape". A `return` decides nothing — it DELEGATES to a caller — so the fix
was still keyed on how the source looked. The tests here are therefore
METAMORPHIC: they hold one behaviour fixed, vary its spelling across a family
of behaviour-preserving refactors, and require the verdict not to move. A test
that only pinned the four original shapes would have PASSED on the refuted fix,
which is why it would not have been enough.

The suite also pins the OTHER direction (`test_884_*_control_*`): an edit that
genuinely wires the status must still reach ENFORCED. Robustness to refactors
is trivially achievable by never saying ENFORCED, and that would be a different
lie, not a fix.

ROUND 2b — WHAT ATTACKING ROUND 2 THE SAME WAY FOUND. Waiting to be refuted a
second time is not a method, so round 2 was put through a wider battery of its
own (20 drops, 6 wired controls) before anyone else could. Four more verdicts
moved on spelling alone, and each is now a shape in the families below:

    R16/R17  `if cp.returncode != 0: pass` — a branch that does nothing was
             read as a decision, so DEAD CODE manufactured ENFORCED
    R18/W07  the gate name handed straight to a dispatcher vs via a local —
             the name-flow was seeded only from assignments, so the two
             spellings of the same program disagreed
    R13/W08  `_emit` returning `_spawn(...)` — delegation chains went cold one
             frame short of the caller that decides
    R21/W16  `import subprocess as _sp` — a spawn was recognised only under
             the module's literal name (one runner in this tree is spelled
             this way)

MUTATION EVIDENCE for this file, measured with THIS file against each of the
three earlier programs in turn (85 tests collected in every run):
    against origin/main 9efa32894 (unfixed) 55 failed / 30 passed
    against ROUND 1 (the refuted fix)       17 failed / 68 passed
    against ROUND 2 (before round 2b)        9 failed / 76 passed
    against the program in this change       0 failed / 85 passed

The middle line is the one that matters: a suite that passed on round 1 would
have certified the very code a verifier broke in one move.

Every synthetic fixture is chip-AGNOSTIC: no design, PDK, vendor or cell name
appears anywhere.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import flow_gate_enforcement_audit as A  # noqa: E402

_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

#: The audit only reads files it recognises as runners.
_RUNNER = "design_one_shot_runner.py"


@pytest.fixture(scope="module")
def real_report():
    """One audit of the real tree, shared. Auditing it costs seconds — most of
    it parsing ~10 MB of runner source — and re-running it per test would put a
    minute on the suite for the same answer."""
    return A.audit(_FLOW, _PROGRAMS)


def _tree(tmp_path: Path, runner_src: str, gates: list) -> Path:
    """A programs dir holding one synthetic runner and a flow declaring
    `gates`. Returns the flow path; the programs dir is `tmp_path`.

    `mkdir` because several tests build TWO trees under one `tmp_path`
    (`tmp_path / "a"`, `tmp_path / "b"`) to hold a helper body fixed and vary
    only its caller — those subdirectories do not exist yet.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / _RUNNER).write_text(runner_src)
    flow = tmp_path / "flow.yaml"
    flow.write_text("".join(
        f'- program_exit_zero: "{g} . --json {g}.json"\n' for g in gates))
    return flow


def _rows(tmp_path: Path, runner_src: str, gates: list) -> dict:
    flow = _tree(tmp_path, runner_src, gates)
    rep = A.audit(flow, tmp_path)
    return {r["gate"]: r for r in rep["gates"]}


# ---------------------------------------------------------------------------
# THE DEFECT, IN ITS SIMPLEST FORM
# ---------------------------------------------------------------------------
_SPAWN_AND_DROP = '''
import subprocess
import sys


def step_that_drops_the_verdict():
    # Spawned for real, and the exit status is not even bound.
    subprocess.run([sys.executable, "dropped_check.py", "p"], check=False)


def step_that_blocks_on_the_verdict():
    cp = subprocess.run([sys.executable, "reading_check.py", "p"], check=False)
    if cp.returncode != 0:
        return "FAIL"
    return "PASS"
'''


def test_884_a_spawned_gate_whose_status_is_dropped_is_not_enforced(tmp_path):
    rows = _rows(tmp_path, _SPAWN_AND_DROP, ["dropped_check", "reading_check"])
    assert rows["dropped_check"]["enforcement"] == "AUDIT_ONLY", \
        rows["dropped_check"]
    assert rows["dropped_check"]["wiring"] == A.INLINE_STATUS_IGNORED, \
        rows["dropped_check"]


def test_884_reading_the_status_is_still_enforcement(tmp_path):
    """The control. Without it, "nothing is ENFORCED" would pass every other
    test in this file."""
    rows = _rows(tmp_path, _SPAWN_AND_DROP, ["dropped_check", "reading_check"])
    assert rows["reading_check"]["enforcement"] == "ENFORCED", \
        rows["reading_check"]
    assert rows["reading_check"]["wiring"] == A.INLINE_BLOCKING, \
        rows["reading_check"]


def test_884_the_dropped_gate_is_still_NAMED_by_the_runner(tmp_path):
    """The two questions must be demonstrably different. `_invoked` — the
    predicate that used to decide ENFORCED on its own — says yes for BOTH
    gates, so the fix is doing work rather than agreeing by accident."""
    _tree(tmp_path, _SPAWN_AND_DROP, ["dropped_check", "reading_check"])
    src = A.runner_source(tmp_path)
    assert A._invoked(src, "dropped_check")
    assert A._invoked(src, "reading_check")


# ===========================================================================
# ROUND 2 — THE REFUTATION VECTOR
#
# One behaviour: spawn the gate, discard its verdict. Fifteen spellings of it.
# The verdict must be the same for all fifteen, and it must never be ENFORCED.
#
# `R05` is the verifier's move verbatim — extract method, returning the
# `CompletedProcess`. On round 1's classifier R05, R06, R07 and R13 all came
# back ENFORCED; they are the reason this is a family and not a single case.
# ===========================================================================
_GATE = "refactored_check.py"

_R01_BARE = '''
import subprocess
import sys


def step(project):
    subprocess.run([sys.executable, "refactored_check.py", project],
                   capture_output=True, text=True, timeout=300)
'''

_R02_BOUND_UNUSED = '''
import subprocess
import sys


def step(project):
    _cp = subprocess.run([sys.executable, "refactored_check.py", project],
                         capture_output=True, text=True, timeout=300)
'''

_R03_BOUND_TO_UNDERSCORE = '''
import subprocess
import sys


def step(project):
    _ = subprocess.run([sys.executable, "refactored_check.py", project],
                       capture_output=True, text=True, timeout=300)
'''

_R04_ARGV_HOISTED = '''
import subprocess
import sys


def step(project):
    argv = [sys.executable, "refactored_check.py", project]
    subprocess.run(argv, capture_output=True, text=True, timeout=300)
'''

#: THE VERIFIER'S EXACT MOVE. Extract method; the helper returns the
#: CompletedProcess; the one call site drops it. Round 1 read the `return` as
#: a control-flow decision and answered INLINE_BLOCKING.
_R05_EXTRACTED_RETURNS_PROCESS = '''
import subprocess
import sys


def _emit(project):
    return subprocess.run([sys.executable, "refactored_check.py", project],
                          capture_output=True, text=True, timeout=300)


def step(project):
    _emit(project)
'''

_R06_EXTRACTED_RETURNS_STATUS = '''
import subprocess
import sys


def _emit(project):
    return subprocess.run([sys.executable, "refactored_check.py", project],
                          capture_output=True, text=True).returncode


def step(project):
    _emit(project)
'''

_R07_EXTRACTED_RETURNS_TUPLE = '''
import subprocess
import sys


def _emit(project):
    cp = subprocess.run([sys.executable, "refactored_check.py", project],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout, cp.stderr


def step(project):
    rc, out, err = _emit(project)
    _ = out + err
'''

_R08_EXTRACTED_RETURNS_NOTHING = '''
import subprocess
import sys


def _emit(project):
    subprocess.run([sys.executable, "refactored_check.py", project],
                   capture_output=True, text=True)
    return None


def step(project):
    _emit(project)
'''

_R09_SWALLOWING_TRY = '''
import subprocess
import sys


def step(project):
    try:
        subprocess.run([sys.executable, "refactored_check.py", project],
                       capture_output=True, text=True, timeout=300)
    except Exception:
        pass
'''

_R10_EXTRACTED_INSIDE_SWALLOWING_TRY = '''
import subprocess
import sys


def _emit(project):
    try:
        return subprocess.run([sys.executable, "refactored_check.py", project],
                              capture_output=True, text=True, timeout=300)
    except Exception:
        return None


def step(project):
    _emit(project)
'''

_R11_STATUS_ONLY_LOGGED = '''
import subprocess
import sys


def step(project, log):
    cp = subprocess.run([sys.executable, "refactored_check.py", project],
                        capture_output=True, text=True)
    log.append("plan emitted (rc=%d)" % cp.returncode)
'''

_R12_COMPARISON_DISCARDED = '''
import subprocess
import sys


def step(project):
    cp = subprocess.run([sys.executable, "refactored_check.py", project],
                        capture_output=True, text=True)
    ok = cp.returncode == 0
'''

_R13_TWO_FRAMES = '''
import subprocess
import sys


def _spawn(project):
    return subprocess.run([sys.executable, "refactored_check.py", project],
                          capture_output=True, text=True)


def _emit(project):
    return _spawn(project)


def step(project):
    _emit(project)
'''

_R14_ONE_ELEMENT_LOOP = '''
import subprocess
import sys


def step(project):
    for prog in ["refactored_check.py"]:
        subprocess.run([sys.executable, prog, project],
                       capture_output=True, text=True)
'''

_R15_SUBPROCESS_CALL_BARE = '''
import subprocess
import sys


def step(project):
    subprocess.call([sys.executable, "refactored_check.py", project])
'''

#: ROUND 2b. Found by attacking round 2 the way the verifier attacked round 1,
#: instead of waiting to be told. Adding a branch that does nothing is a
#: behaviour-preserving edit by the strictest reading — no process can observe
#: the difference — and it moved the gate into ENFORCED, because the status
#: reached an `if` TEST. MEASURED on round 2: ENFORCED / INLINE_BLOCKING.
#: A branch with no effect at all is not a decision; see `_is_inert_branch`.
_R16_DEAD_BRANCH_ON_STATUS = '''
import subprocess
import sys


def step(project):
    cp = subprocess.run([sys.executable, "refactored_check.py", project],
                        capture_output=True, text=True)
    if cp.returncode != 0:
        pass
'''

_R17_DEAD_BRANCH_WITH_ELSE = '''
import subprocess
import sys


def step(project):
    cp = subprocess.run([sys.executable, "refactored_check.py", project],
                        capture_output=True, text=True)
    if cp.returncode != 0:
        pass
    else:
        pass
'''

#: The gate name handed STRAIGHT to a helper that drops the status, rather than
#: through a local. Round 2 seeded its name-flow only from assignments, so the
#: two spellings took different paths through the analysis.
_R18_LITERAL_STRAIGHT_TO_DISPATCHER = '''
import subprocess
import sys


def _dispatch(project, prog):
    cp = subprocess.run([sys.executable, prog, project], capture_output=True)
    return cp.stdout


def step(project):
    _dispatch(project, "refactored_check.py")
'''

_R19_EXTRACTED_ONTO_A_METHOD = '''
import subprocess
import sys


class Runner:
    def _emit(self, project):
        return subprocess.run([sys.executable, "refactored_check.py", project],
                              capture_output=True, text=True)

    def step(self, project):
        self._emit(project)
'''

_R20_SUPPRESS_INSTEAD_OF_TRY = '''
import contextlib
import subprocess
import sys


def step(project):
    with contextlib.suppress(Exception):
        subprocess.run([sys.executable, "refactored_check.py", project],
                       capture_output=True, text=True, timeout=300)
'''

#: `import subprocess as _sp` — a real spelling in this tree
#: (phase3_one_shot_runner.py:38406). Renaming the MODULE must not change the
#: verdict either.
_R21_ALIASED_SUBPROCESS_MODULE = '''
import subprocess as _sp
import sys


def step(project):
    _sp.run([sys.executable, "refactored_check.py", project],
            capture_output=True, text=True)
'''

_R22_FROM_IMPORT_RUN = '''
import sys
from subprocess import run


def step(project):
    run([sys.executable, "refactored_check.py", project], capture_output=True)
'''


#: ROUND-3 REFUTATION VECTOR. Every fixture above is a SINGLE-launch-site
#: module, so none of them can express the shape that actually broke round 2:
#: the gate's argv is hoisted into a local whose NAME a DIFFERENT program's
#: spawn also uses. On the real runner that name is `cmd`, already in use
#: eleven lines earlier for the ATPG run. The audit credited that other spawn
#: to this gate and answered ENFORCED — so the verdict turned on how a local
#: was spelled, which is the defect this whole file exists to refuse.
_R23_NAME_REUSED_BY_AN_EARLIER_BLOCKING_SPAWN = '''
import subprocess
import sys


def step(project):
    cmd = [sys.executable, "other_program.py", project]
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if cp.returncode != 0:
        return "FAIL"

    cmd = [sys.executable, "refactored_check.py", project]
    subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return "PASS"
'''

#: The same coincidence in the other order: the gate is named first, and the
#: name is later rebound to another program whose status IS tested.
_R24_NAME_REBOUND_TO_A_LATER_BLOCKING_SPAWN = '''
import subprocess
import sys


def step(project):
    cmd = [sys.executable, "refactored_check.py", project]
    subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    cmd = [sys.executable, "other_program.py", project]
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if cp.returncode != 0:
        return "FAIL"
    return "PASS"
'''

#: The worst shape: the gate is NEVER SPAWNED AT ALL, only named — and the
#: local holding its name is rebound to a program that IS judged. This is the
#: original #884 defect verbatim ("the filename appeared in a string"),
#: reproduced by the classifier that was supposed to have closed it.
_R25_NAMED_BUT_NEVER_SPAWNED = '''
import subprocess
import sys


def step(project):
    cmd = [sys.executable, "refactored_check.py", project]
    cmd = [sys.executable, "other_program.py", project]
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if cp.returncode != 0:
        return "FAIL"
    return "PASS"
'''


#: vibe-ic#898 — DEAD CODE AT MODULE SCOPE. Cheaper than R23-R25: no refactor,
#: no second spawn, just one line that is never read and never executed. The
#: module binding was treated as live inside a function that binds the same
#: name, because the window closed with a MODULE-scope next-store which cannot
#: see a function-local. Python scoping says the opposite: a name assigned
#: anywhere in a function body is local for the WHOLE body.
_R26_DEAD_MODULE_LEVEL_LINE = '''
cmd = "refactored_check.py"

import subprocess
import sys


def step(project):
    cmd = [sys.executable, "other_program.py", project]
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if cp.returncode != 0:
        return "FAIL"
    return "PASS"
'''

_BEHAVIOUR_PRESERVING = {
    "R01_bare_statement": _R01_BARE,
    "R02_bound_unused": _R02_BOUND_UNUSED,
    "R03_bound_to_underscore": _R03_BOUND_TO_UNDERSCORE,
    "R04_argv_hoisted": _R04_ARGV_HOISTED,
    "R05_extract_method_returns_process": _R05_EXTRACTED_RETURNS_PROCESS,
    "R06_extract_method_returns_status": _R06_EXTRACTED_RETURNS_STATUS,
    "R07_extract_method_returns_tuple": _R07_EXTRACTED_RETURNS_TUPLE,
    "R08_extract_method_returns_none": _R08_EXTRACTED_RETURNS_NOTHING,
    "R09_swallowing_try": _R09_SWALLOWING_TRY,
    "R10_extracted_inside_swallowing_try": _R10_EXTRACTED_INSIDE_SWALLOWING_TRY,
    "R11_status_only_logged": _R11_STATUS_ONLY_LOGGED,
    "R12_comparison_discarded": _R12_COMPARISON_DISCARDED,
    "R13_two_frames": _R13_TWO_FRAMES,
    "R14_one_element_loop": _R14_ONE_ELEMENT_LOOP,
    "R15_subprocess_call_bare": _R15_SUBPROCESS_CALL_BARE,
    "R16_dead_branch_on_status": _R16_DEAD_BRANCH_ON_STATUS,
    "R17_dead_branch_with_else": _R17_DEAD_BRANCH_WITH_ELSE,
    "R18_literal_straight_to_dispatcher": _R18_LITERAL_STRAIGHT_TO_DISPATCHER,
    "R19_extracted_onto_a_method": _R19_EXTRACTED_ONTO_A_METHOD,
    "R20_suppress_instead_of_try": _R20_SUPPRESS_INSTEAD_OF_TRY,
    "R21_aliased_subprocess_module": _R21_ALIASED_SUBPROCESS_MODULE,
    "R22_from_import_run": _R22_FROM_IMPORT_RUN,
    "R23_name_reused_by_earlier_blocking_spawn":
        _R23_NAME_REUSED_BY_AN_EARLIER_BLOCKING_SPAWN,
    "R24_name_rebound_to_later_blocking_spawn":
        _R24_NAME_REBOUND_TO_A_LATER_BLOCKING_SPAWN,
    "R25_named_but_never_spawned": _R25_NAMED_BUT_NEVER_SPAWNED,
    "R26_dead_module_level_line": _R26_DEAD_MODULE_LEVEL_LINE,
}


@pytest.mark.parametrize("shape", sorted(_BEHAVIOUR_PRESERVING))
def test_884_R_a_behaviour_preserving_refactor_cannot_create_enforcement(
        shape, tmp_path):
    """THE REFUTATION VECTOR, generalised.

    Each of these spawns the gate and discards its verdict. They differ only in
    spelling. A classifier keyed on what the code MEANS gives one answer for
    all of them; one keyed on how it LOOKS does not — which is exactly how
    round 1 was broken.
    """
    rows = _rows(tmp_path, _BEHAVIOUR_PRESERVING[shape], ["refactored_check"])
    row = rows["refactored_check"]
    assert row["enforcement"] == "AUDIT_ONLY", (shape, row)
    assert row["wiring"] != A.INLINE_BLOCKING, (shape, row)
    # It must still be SEEN — a gate that fell out of the audit entirely would
    # satisfy the assertions above while reporting nothing at all.
    assert row["wiring"] != A.NOT_INVOKED, (shape, row)


@pytest.mark.parametrize("shape", sorted(_BEHAVIOUR_PRESERVING))
def test_884_R_the_runner_still_NAMES_the_gate_in_every_shape(shape, tmp_path):
    """Guards the assertion above against passing for the wrong reason: in
    every shape the filename really is in the runner, so the old substring
    predicate would say ENFORCED for all fifteen."""
    _tree(tmp_path, _BEHAVIOUR_PRESERVING[shape], ["refactored_check"])
    assert A._invoked(A.runner_source(tmp_path), "refactored_check"), shape


# --- the other direction ---------------------------------------------------
_WIRED_VARIANTS = {
    "W01_if_on_returncode": '''
import subprocess
import sys


def step(project):
    cp = subprocess.run([sys.executable, "refactored_check.py", project],
                        capture_output=True, text=True)
    if cp.returncode != 0:
        return "FAIL"
    return "PASS"
''',
    "W02_extract_method_caller_tests_it": '''
import subprocess
import sys


def _emit(project):
    return subprocess.run([sys.executable, "refactored_check.py", project],
                          capture_output=True, text=True)


def step(project):
    cp = _emit(project)
    if cp.returncode != 0:
        return "FAIL"
    return "PASS"
''',
    "W03_extract_method_caller_tests_the_status": '''
import subprocess
import sys


def _emit(project):
    return subprocess.run([sys.executable, "refactored_check.py", project],
                          capture_output=True, text=True).returncode


def step(project):
    if _emit(project) != 0:
        return "FAIL"
    return "PASS"
''',
    "W04_check_true_not_swallowed": '''
import subprocess
import sys


def step(project):
    subprocess.run([sys.executable, "refactored_check.py", project],
                   check=True)
''',
    "W05_status_becomes_the_process_exit_code": '''
import subprocess
import sys


def step(project):
    cp = subprocess.run([sys.executable, "refactored_check.py", project])
    sys.exit(cp.returncode)
''',
    "W06_subprocess_call_in_a_test": '''
import subprocess
import sys


def step(project):
    if subprocess.call([sys.executable, "refactored_check.py", project]):
        return "FAIL"
    return "PASS"
''',
    #: ROUND 2b, the mirror of R18: the SAME dispatcher, the same literal
    #: handed straight to it, and this time the status IS tested. Round 2
    #: answered INLINE_UNPROVEN for both, i.e. the verdict did not depend on
    #: what the dispatcher did with the status — only on whether the author
    #: bound the name to a local first. Wrong in the safe direction, but wrong
    #: for exactly the reason #884 is about, so it is pinned here.
    "W07_literal_straight_to_a_dispatcher_that_tests_it": '''
import subprocess
import sys


def _dispatch(project, prog):
    cp = subprocess.run([sys.executable, prog, project], capture_output=True)
    if cp.returncode != 0:
        return "FAIL"
    return "PASS"


def step(project):
    return _dispatch(project, "refactored_check.py")
''',
    #: ROUND 2b: delegation CHAINS. `_emit` returns what `_spawn` returns, and
    #: `step` tests it. Round 2 saw no `subprocess` inside `_emit`, so `_emit`
    #: was not a wrapper and the trail went cold one frame short of the caller
    #: that actually blocks. Compare R13, which is the same two frames with the
    #: status DROPPED — the two must not give the same answer.
    "W08_two_frames_of_delegation_then_tested": '''
import subprocess
import sys


def _spawn(project):
    return subprocess.run([sys.executable, "refactored_check.py", project],
                          capture_output=True, text=True)


def _emit(project):
    return _spawn(project)


def step(project):
    cp = _emit(project)
    if cp.returncode != 0:
        return "FAIL"
    return "PASS"
''',
    #: ROUND 2b: the module renamed, and the status genuinely tested. Round 2
    #: recognised a spawn only through the literal token `subprocess`, so this
    #: launch site did not exist as far as the analysis was concerned. One
    #: runner in this tree really is spelled this way.
    "W16_aliased_module_and_status_tested": '''
import subprocess as _sp
import sys


def step(project):
    cp = _sp.run([sys.executable, "refactored_check.py", project],
                 capture_output=True, text=True)
    if cp.returncode != 0:
        return "FAIL"
    return "PASS"
''',
    #: The same gate spawned TWICE — once with the verdict dropped, once with
    #: it tested. Enforcement is an EXISTENCE claim, so the strongest wiring
    #: wins and the answer must not depend on which site the walk reaches
    #: first.
    "W09_dropped_at_one_site_and_wired_at_another": '''
import subprocess
import sys


def step_a(project):
    subprocess.run([sys.executable, "refactored_check.py", project])


def step_b(project):
    cp = subprocess.run([sys.executable, "refactored_check.py", project])
    if cp.returncode != 0:
        return "FAIL"
    return "PASS"
''',
}


@pytest.mark.parametrize("shape", sorted(_WIRED_VARIANTS))
def test_884_R_control_a_genuinely_consumed_status_still_reaches_enforced(
        shape, tmp_path):
    """NON-DEGENERACY. Every assertion in this file about "cannot create
    enforcement" is satisfied by a classifier that never says ENFORCED, and
    that would be a new lie rather than a fix. These six are the same call site
    with the verdict actually wired, and each must come back ENFORCED.
    """
    rows = _rows(tmp_path, _WIRED_VARIANTS[shape], ["refactored_check"])
    row = rows["refactored_check"]
    assert row["enforcement"] == "ENFORCED", (shape, row)
    assert row["wiring"] == A.INLINE_BLOCKING, (shape, row)


# ---------------------------------------------------------------------------
# WHY ROUND 1 FELL: `return` IS DELEGATION, NOT A DECISION
# ---------------------------------------------------------------------------
def test_884_a_return_is_delegation_and_is_resolved_at_the_call_site(tmp_path):
    """The mechanism, isolated.

    ONE helper body, TWO callers. The helper is identical in both trees; only
    what the caller does with the returned value differs. If `return` were a
    decision — round 1's rule — both would read as blocking and the caller
    would be irrelevant. The verdict must instead follow the CALLER.
    """
    helper = '''
import subprocess
import sys


def _emit(project):
    return subprocess.run([sys.executable, "delegated_check.py", project],
                          capture_output=True, text=True)
'''
    dropped = helper + '''

def step(project):
    _emit(project)
'''
    consumed = helper + '''

def step(project):
    cp = _emit(project)
    if cp.returncode != 0:
        return "FAIL"
    return "PASS"
'''
    a = _rows(tmp_path / "a", dropped, ["delegated_check"])["delegated_check"]
    b = _rows(tmp_path / "b", consumed, ["delegated_check"])["delegated_check"]
    assert a["enforcement"] == "AUDIT_ONLY", a
    assert b["enforcement"] == "ENFORCED", b
    assert b["wiring"] == A.INLINE_BLOCKING, b


def test_884_a_negative_across_a_frame_boundary_is_UNPROVEN_not_IGNORED(
        tmp_path):
    """The soundness asymmetry, pinned so it is not "tidied" away later.

    Inside one frame the whole live range of the status is visible, so "nothing
    reads it" is provable — INLINE_STATUS_IGNORED. Across a `return` it is not:
    no static pass can enumerate every caller of a Python function. So the
    strongest NEGATIVE available there is INLINE_UNPROVEN. BLOCKS stays
    provable across the boundary because it is an EXISTENCE claim — one caller
    that tests the status is enough.
    """
    in_frame = _rows(tmp_path / "a", _R01_BARE,
                     ["refactored_check"])["refactored_check"]
    across = _rows(tmp_path / "b", _R05_EXTRACTED_RETURNS_PROCESS,
                   ["refactored_check"])["refactored_check"]
    assert in_frame["wiring"] == A.INLINE_STATUS_IGNORED, in_frame
    assert across["wiring"] == A.INLINE_UNPROVEN, across
    # ...and the column anyone ACTS on is the same for both.
    assert in_frame["enforcement"] == across["enforcement"] == "AUDIT_ONLY"


def test_884_a_branch_that_does_nothing_is_not_a_decision(tmp_path):
    """ROUND 2b, the mechanism isolated.

    TWO trees. Identical up to the BODY of one `if`. Round 2 answered ENFORCED
    for both, because it stopped at "the status reached a test" — so a dead
    branch, which no process can observe, manufactured enforcement. The line is
    drawn at "has any effect at all", NOT at "stops the step": the second
    question needs each runner's notion of stopping and is deliberately not
    answered here.
    """
    dead = _rows(tmp_path / "a", _R16_DEAD_BRANCH_ON_STATUS,
                 ["refactored_check"])["refactored_check"]
    live = _rows(tmp_path / "b", _WIRED_VARIANTS["W01_if_on_returncode"],
                 ["refactored_check"])["refactored_check"]
    assert dead["enforcement"] == "AUDIT_ONLY", dead
    assert dead["wiring"] != A.INLINE_BLOCKING, dead
    assert live["enforcement"] == "ENFORCED", live


def test_884_a_while_that_does_nothing_is_still_a_decision(tmp_path):
    """The inert-branch rule must stay narrow. `while rc: pass` spins forever
    on a non-zero exit — very much an effect — so it is NOT inert, and neither
    is an `assert`, which raises. Widening the rule to any loop or assertion
    would start hiding real enforcement."""
    src = '''
import subprocess
import sys


def step(project):
    cp = subprocess.run([sys.executable, "spinning_check.py", project])
    while cp.returncode:
        pass
'''
    rows = _rows(tmp_path, src, ["spinning_check"])
    assert rows["spinning_check"]["enforcement"] == "ENFORCED", \
        rows["spinning_check"]


def test_884_delegation_chains_and_the_caller_still_decides(tmp_path):
    """ROUND 2b. `_emit` returns what `_spawn` returns. The helper bodies are
    byte-identical in both trees; only the outermost caller differs. Round 2
    gave the SAME answer to both, so the caller — the only thing that decides —
    was not being read at all."""
    dropped = _rows(tmp_path / "a", _R13_TWO_FRAMES,
                    ["refactored_check"])["refactored_check"]
    consumed = _rows(
        tmp_path / "b",
        _WIRED_VARIANTS["W08_two_frames_of_delegation_then_tested"],
        ["refactored_check"])["refactored_check"]
    assert dropped["enforcement"] == "AUDIT_ONLY", dropped
    assert consumed["enforcement"] == "ENFORCED", consumed
    assert consumed["wiring"] == A.INLINE_BLOCKING, consumed


def test_884_binding_the_gate_name_to_a_local_first_changes_nothing(tmp_path):
    """ROUND 2b. `_dispatch(project, "g.py")` and `prog = "g.py"` /
    `_dispatch(project, prog)` are the same program. Round 2 seeded its
    name-flow only from assignments, so only the second reached the dispatcher
    and the two spellings disagreed."""
    direct = _rows(
        tmp_path / "a",
        _WIRED_VARIANTS["W07_literal_straight_to_a_dispatcher_that_tests_it"],
        ["refactored_check"])["refactored_check"]
    via_local = _rows(tmp_path / "b", '''
import subprocess
import sys


def _dispatch(project, prog):
    cp = subprocess.run([sys.executable, prog, project], capture_output=True)
    if cp.returncode != 0:
        return "FAIL"
    return "PASS"


def step(project):
    prog = "refactored_check.py"
    return _dispatch(project, prog)
''', ["refactored_check"])["refactored_check"]
    assert direct["enforcement"] == via_local["enforcement"] == "ENFORCED", \
        (direct, via_local)


# ---------------------------------------------------------------------------
# THE SECOND PATTERN-SHAPED HOLE: DISPATCH BY CO-LOCATION
# ---------------------------------------------------------------------------
_DISPATCH_COLOCATED = '''
import subprocess
import sys


def _dispatch(project, plan_program, gate_program):
    # Two programs. Only ONE of them has its verdict read. `plan_program` is
    # never even put into an argv.
    cp = subprocess.run([sys.executable, gate_program, project],
                        capture_output=True, text=True)
    if cp.returncode != 0:
        return "FAIL"
    return "PASS"


def step(project):
    return _dispatch(project, "colocated_check.py", "blocking_check.py")
'''


def test_884_a_gate_that_merely_shares_a_helper_is_not_enforced(tmp_path):
    """Round 1 asked, for one hop of dispatch, only whether the helper
    contained ANY blocking launch site. So a gate name handed to a helper that
    happens to block on something ELSE was scored ENFORCED on a coincidence of
    co-location — the same "name near a decision" reasoning the finding is
    about, one level down. The gate name must reach the argv of the launch site
    that is judged.
    """
    rows = _rows(tmp_path, _DISPATCH_COLOCATED,
                 ["colocated_check", "blocking_check"])
    assert rows["colocated_check"]["enforcement"] == "AUDIT_ONLY", \
        rows["colocated_check"]
    assert rows["colocated_check"]["wiring"] != A.INLINE_BLOCKING, \
        rows["colocated_check"]
    # the gate that IS in the argv keeps its enforcement — the hop still works
    assert rows["blocking_check"]["enforcement"] == "ENFORCED", \
        rows["blocking_check"]


_NAME_COINCIDENCE = '''
import subprocess
import sys


def _emit(project, findings):
    subprocess.run([sys.executable, "namecoin_check.py", project],
                   capture_output=True, text=True)
    # `rc` here is a COUNT, not an exit status. Nothing in this tuple is one.
    rc = len(findings)
    return rc, "", ""


def step(project, findings):
    rc, out, err = _emit(project, findings)
    if rc:
        return "FAIL"
    return "PASS"
'''


def test_884_a_variable_merely_SPELLED_like_a_status_is_not_one(tmp_path):
    """Round 1 accepted a bare name spelled `rc`/`code`/`status`/... as proof
    that it WAS an exit status, which is a name coincidence deciding a verdict
    — the same species as the defect being fixed. Here the helper spawns the
    gate, drops its real status, and returns an unrelated count called `rc`
    that the caller then tests. Believing the name would report this gate as
    blocking on a verdict it never saw.
    """
    row = _rows(tmp_path, _NAME_COINCIDENCE, ["namecoin_check"])[
        "namecoin_check"]
    assert row["enforcement"] == "AUDIT_ONLY", row
    assert row["wiring"] != A.INLINE_BLOCKING, row


# ---------------------------------------------------------------------------
# A HELPER THAT RETURNS THE STATUS HAS DELEGATED THE DECISION
# ---------------------------------------------------------------------------
_TUPLE_WRAPPER = '''
import subprocess
import sys


def _run(cmd, timeout=600):
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return cp.returncode, cp.stdout, cp.stderr


def step_that_ignores_rc(project):
    rc, out, err = _run([sys.executable, "ignored_check.py", project])
    return out.count("repaired")


def step_that_uses_rc(project):
    rc, out, err = _run([sys.executable, "used_check.py", project])
    if rc != 0:
        return "FAIL"
    return "PASS"
'''


def test_884_a_wrapper_returning_the_status_does_not_consume_it(tmp_path):
    """`_run` is the runners' house helper. It RETURNS `(rc, out, err)`, so the
    decision belongs to whoever called it. Judging enforcement inside `_run`
    would call every one of its ~hundreds of call sites enforcement, including
    `rtl_hygiene_lint`'s, which binds `rc` and then scrapes `out` instead."""
    rows = _rows(tmp_path, _TUPLE_WRAPPER, ["ignored_check", "used_check"])
    assert rows["ignored_check"]["enforcement"] == "AUDIT_ONLY", \
        rows["ignored_check"]
    assert rows["ignored_check"]["wiring"] == A.INLINE_STATUS_IGNORED, \
        rows["ignored_check"]
    assert rows["used_check"]["enforcement"] == "ENFORCED", rows["used_check"]


# ---------------------------------------------------------------------------
# PROXIMITY IS NOT CONSUMPTION
# ---------------------------------------------------------------------------
_PROXIMITY = '''
import subprocess
import sys


def step(project):
    r = subprocess.run([sys.executable, "engine_tool.py", project],
                       capture_output=True, text=True)
    subprocess.run([sys.executable, "nearby_check.py", project],
                   capture_output=True, text=True)
    # This `r.returncode` is the ENGINE's, not the gate's. Eleven lines apart
    # in the real runner; three here.
    if r.returncode != 0:
        return "FAIL"
    return "PASS"
'''


def test_884_a_nearby_returncode_from_another_process_is_not_consumption(
        tmp_path):
    """The `bsdl_emit` shape exactly: a `.returncode` belonging to a different
    subprocess in the same function. Reading proximity as evidence is the same
    error the finding names, one level down — so the fix must not commit it
    while diagnosing it."""
    rows = _rows(tmp_path, _PROXIMITY, ["nearby_check"])
    assert rows["nearby_check"]["enforcement"] == "AUDIT_ONLY", \
        rows["nearby_check"]
    assert rows["nearby_check"]["wiring"] == A.INLINE_STATUS_IGNORED, \
        rows["nearby_check"]


def test_884_a_swallowed_raise_is_not_enforcement(tmp_path):
    """`check=True` raises on a non-zero exit — but not past a handler that
    drops it. The exception stops nothing, so neither does the gate."""
    src = '''
import subprocess
import sys


def step(project):
    try:
        subprocess.run([sys.executable, "swallowed_check.py", project],
                       check=True)
    except Exception:
        pass


def step_unguarded(project):
    subprocess.run([sys.executable, "raising_check.py", project], check=True)
'''
    rows = _rows(tmp_path, src, ["swallowed_check", "raising_check"])
    assert rows["swallowed_check"]["enforcement"] == "AUDIT_ONLY", \
        rows["swallowed_check"]
    assert rows["raising_check"]["enforcement"] == "ENFORCED", \
        rows["raising_check"]


def test_884_a_handler_that_cannot_catch_the_raise_is_not_a_swallow(tmp_path):
    """`except subprocess.TimeoutExpired:` does not catch `CalledProcessError`,
    so a non-zero exit still stops the step. Counting every enclosing `try` as
    a swallow would accuse a runner of dropping a verdict it enforces."""
    src = '''
import subprocess
import sys


def step(project):
    try:
        subprocess.run([sys.executable, "timeout_only_check.py", project],
                       check=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    return "PASS"
'''
    rows = _rows(tmp_path, src, ["timeout_only_check"])
    assert rows["timeout_only_check"]["enforcement"] == "ENFORCED", \
        rows["timeout_only_check"]


# ---------------------------------------------------------------------------
# OVER-TIGHTENING CONTROL — the genuinely wired gates must survive.
# ---------------------------------------------------------------------------
_TABLE_DISPATCH = '''
import subprocess
import sys

PROGRAMS_DIR = "."

_TABLE = (
    ("first", "table_check.py", "reports/a.json", ()),
)


def _dispatch(project, name, program, out_rel, extra_argv=()):
    cp = subprocess.run([sys.executable, program, project, *extra_argv],
                        capture_output=True, text=True, check=False)
    if cp.returncode == 0:
        return "PASS"
    if cp.returncode == 1:
        return "FAIL"
    return "BLOCKED"


def step_declared_gates(project):
    return [_dispatch(project, *g) for g in _TABLE]
'''


def test_884_a_table_dispatched_gate_is_still_enforced(tmp_path):
    """One hop of indirection through a `*args` expansion, blocking at the far
    end, must still read as enforcement — this is how the step-23/25 sign-off
    gates are genuinely wired, and under-reporting them would swap one false
    register for another."""
    rows = _rows(tmp_path, _TABLE_DISPATCH, ["table_check"])
    assert rows["table_check"]["enforcement"] == "ENFORCED", rows["table_check"]


def test_884_a_fallback_binding_in_an_except_handler_is_not_a_rebind(tmp_path):
    """`cp = subprocess.run(...)` / `except: cp = None` / `if cp is not None
    and cp.returncode != 0:` is enforcement. Treating the handler's assignment
    as ending the first binding's life would hide a gate that really does
    block — measured: it hid `synth_netlist_check` while round 1 was being
    written."""
    src = '''
import subprocess
import sys


def step(project):
    try:
        snc = subprocess.run([sys.executable, "fallback_check.py", project],
                             capture_output=True, text=True)
    except Exception:
        snc = None
    if snc is not None and snc.returncode != 0:
        return "FAIL"
    return "PASS"
'''
    rows = _rows(tmp_path, src, ["fallback_check"])
    assert rows["fallback_check"]["enforcement"] == "ENFORCED", \
        rows["fallback_check"]


def test_884_reading_only_stdout_is_not_reading_the_status(tmp_path):
    """`sdc_syntax_check`'s shape: the result IS bound, and everything read
    from it is text. A gate whose stdout is scraped and whose exit code is not
    read cannot fail the step on its own verdict."""
    src = '''
import subprocess
import sys


def step(project):
    r = subprocess.run([sys.executable, "stdout_only_check.py", project],
                       capture_output=True, text=True)
    if "ERROR" in r.stdout:
        return "WARN"
    return "PASS"
'''
    rows = _rows(tmp_path, src, ["stdout_only_check"])
    assert rows["stdout_only_check"]["enforcement"] == "AUDIT_ONLY", \
        rows["stdout_only_check"]
    assert rows["stdout_only_check"]["wiring"] == A.INLINE_STATUS_IGNORED, \
        rows["stdout_only_check"]


def test_884_a_bare_check_returncode_call_is_enforcement(tmp_path):
    """`cp.check_returncode()` raises on a non-zero exit. Nothing needs to READ
    the status for it to stop the step, so demanding an `if` would
    under-report."""
    src = '''
import subprocess
import sys


def step(project):
    cp = subprocess.run([sys.executable, "raise_on_rc_check.py", project],
                        capture_output=True, text=True)
    cp.check_returncode()
'''
    rows = _rows(tmp_path, src, ["raise_on_rc_check"])
    assert rows["raise_on_rc_check"]["enforcement"] == "ENFORCED", \
        rows["raise_on_rc_check"]


def test_884_a_status_that_is_only_RECORDED_is_not_enforcement(tmp_path):
    """The third state, and the reason there is one.

    Here the exit status IS read — folded into a verdict string and appended to
    a report — but nothing shown to this analysis turns it into a decision.
    That is neither enforcement nor a discarded status, so calling it either
    would be a claim the evidence does not support.

    This is `mixed_signal_top_lvs_run`'s real shape."""
    src = '''
import subprocess
import sys


def step(project, plan):
    cp = subprocess.run([sys.executable, "recorded_check.py", project],
                        capture_output=True, text=True)
    verdict = {0: "PASS", 2: "SKIP"}.get(cp.returncode, "FAIL")
    plan.append(("recorded", verdict, cp.returncode))
'''
    rows = _rows(tmp_path, src, ["recorded_check"])
    assert rows["recorded_check"]["enforcement"] == "AUDIT_ONLY", \
        rows["recorded_check"]
    assert rows["recorded_check"]["wiring"] == A.INLINE_UNPROVEN, \
        rows["recorded_check"]


# ---------------------------------------------------------------------------
# THE REAL TREE
# ---------------------------------------------------------------------------
#: The four gates this audit called ENFORCED while the runner discarded their
#: verdict. Repairing a CALL SITE is separate work that changes what a real run
#: blocks on — a flow-owner decision, not an audit change — so #884 fixes only
#: the auditor. When a repair lands, drop that gate from this tuple in the SAME
#: change: the entry is a record of debt, never permission to keep it.
_STATUS_IGNORED_TODAY = (
    "bsdl_emit",
    "dfm_screen_check",
    "rtl_hygiene_lint",
    "sdc_syntax_check",
)


@pytest.mark.parametrize("gate", _STATUS_IGNORED_TODAY)
def test_884_the_measured_false_enforced_are_no_longer_enforced(gate,
                                                                real_report):
    """Each of these is named by a runner in a real subprocess argv, and none
    of their exit statuses reaches a decision."""
    row = next((r for r in real_report["gates"] if r["gate"] == gate), None)
    assert row is not None, f"{gate} left the flow definition"
    assert row["enforcement"] == "AUDIT_ONLY", row
    assert row["wiring"] == A.INLINE_STATUS_IGNORED, row


#: `design_one_shot_runner.py:11128` as it stands, and the extract-method
#: refactor of it the verifier used. Byte-for-byte the same subprocess, the
#: same swallow, the same discarded result.
_BSDL_SITE = '''                try:
                    subprocess.run(
                        [sys.executable, str(PROGRAMS_DIR / "bsdl_emit.py"),
                         str(project), "--auto", "--json",
                         str(reports_dir / "phase2/dft/bsdl_plan.json")],
                        capture_output=True, text=True, timeout=300)
                except Exception:
                    pass
'''
_BSDL_EXTRACTED_CALL = '''                _emit_bsdl_plan(project, reports_dir)
'''
_BSDL_EXTRACTED_HELPER = '''

def _emit_bsdl_plan(project, reports_dir):
    """Emit the BSDL plan beside the coverage report. Best-effort: the plan is
    documentation, never a gate, so a failure here must not fail the step."""
    try:
        return subprocess.run(
            [sys.executable, str(PROGRAMS_DIR / "bsdl_emit.py"),
             str(project), "--auto", "--json",
             str(reports_dir / "phase2/dft/bsdl_plan.json")],
            capture_output=True, text=True, timeout=300)
    except Exception:
        return None

'''
#: ...and the same site actually WIRED, for the non-degeneracy control.
_BSDL_WIRED = '''                _bsdl_cp = subprocess.run(
                    [sys.executable, str(PROGRAMS_DIR / "bsdl_emit.py"),
                     str(project), "--auto", "--json",
                     str(reports_dir / "phase2/dft/bsdl_plan.json")],
                    capture_output=True, text=True, timeout=300)
                if _bsdl_cp.returncode != 0:
                    raise RuntimeError("bsdl plan emission failed")
'''
_HELPER_ANCHOR = "\ndef _dft_atpg_measured("


def _tree_with_mutated_runner(tmp_path: Path, mutate) -> Path:
    """A programs dir holding ONE runner — the real `design_one_shot_runner.py`
    with `mutate` applied — audited against the REAL flow definition.

    `bsdl_emit` is named only by this runner, so a single-runner tree gives the
    same verdict for it as the whole set, in a fraction of the time.
    """
    src = (_PROGRAMS / _RUNNER).read_text()
    assert _BSDL_SITE in src, (
        "design_one_shot_runner.py:11128 no longer has the shape #884 was "
        "measured on; re-measure before editing this test")
    out = tmp_path / "programs"
    out.mkdir(parents=True, exist_ok=True)
    (out / _RUNNER).write_text(mutate(src))
    return out


def _bsdl_row(programs: Path) -> dict:
    rep = A.audit(_FLOW, programs)
    row = next(r for r in rep["gates"] if r["gate"] == "bsdl_emit")
    return row


def test_884_the_verifiers_exact_refactor_does_not_move_the_verdict(tmp_path):
    """THE REFUTATION, ON THE REAL FILE.

    Round 1 was refuted by extracting `design_one_shot_runner.py:11128` into a
    helper. MEASURED against round 1's classifier: `bsdl_emit` went
    AUDIT_ONLY / INLINE_STATUS_IGNORED -> ENFORCED / INLINE_BLOCKING, and the
    tree-wide ENFORCED count 16 -> 17, with no change whatsoever to what the
    program does.

    So the property under test is not "bsdl_emit is AUDIT_ONLY" — round 1
    satisfied that — but "the answer does not depend on the spelling".
    """
    def refactor(src):
        return (src.replace(_BSDL_SITE, _BSDL_EXTRACTED_CALL, 1)
                   .replace(_HELPER_ANCHOR,
                            _BSDL_EXTRACTED_HELPER + _HELPER_ANCHOR[1:], 1))

    before = _bsdl_row(_tree_with_mutated_runner(tmp_path / "a", lambda s: s))
    after = _bsdl_row(_tree_with_mutated_runner(tmp_path / "b", refactor))
    assert before["enforcement"] == "AUDIT_ONLY", before
    assert after["enforcement"] == "AUDIT_ONLY", after
    assert after["wiring"] != A.INLINE_BLOCKING, after


def test_884_control_wiring_the_bsdl_site_for_real_DOES_move_it(tmp_path):
    """The control for the test above, on the same real file.

    Here the edit is NOT behaviour-preserving: the status is bound, tested, and
    a non-zero exit raises. The verdict MUST move. Without this, the test above
    would also pass on an auditor that had simply stopped answering ENFORCED.
    """
    def wire(src):
        return src.replace(_BSDL_SITE, _BSDL_WIRED, 1)

    row = _bsdl_row(_tree_with_mutated_runner(tmp_path, wire))
    assert row["enforcement"] == "ENFORCED", row
    assert row["wiring"] == A.INLINE_BLOCKING, row


def test_884_being_named_by_a_runner_is_not_enough_on_the_real_tree(
        real_report):
    """The two questions must be demonstrably different where it counts. If
    every named gate also blocked, `_invoked` alone would have been a correct
    predicate and this whole repair would be inert."""
    src = A.runner_source(_PROGRAMS)
    named = {r["gate"] for r in real_report["gates"]
             if A._invoked(src, r["gate"])}
    blocking = {r["gate"] for r in real_report["gates"]
                if r["wiring"] == A.INLINE_BLOCKING}
    assert blocking < named, (
        "no gate is named-but-not-blocking; the strengthened predicate has "
        "stopped distinguishing anything")


def test_884_enforced_always_means_a_consumed_exit_status(real_report):
    """The invariant, stated once: ENFORCED is exactly INLINE_BLOCKING. No
    other wiring may reach the ENFORCED column, on any tree."""
    for r in real_report["gates"]:
        assert (r["enforcement"] == "ENFORCED") is (
            r["wiring"] == A.INLINE_BLOCKING), r
    assert real_report["enforced"] + real_report["audit_only"] == \
        real_report["total_gates"]
    assert sum(real_report["wiring"].values()) == real_report["total_gates"]


def test_884_the_real_tree_still_has_gates_that_genuinely_block(real_report):
    """Non-degeneracy on the real tree. A classifier that answered UNPROVEN to
    everything would satisfy every negative assertion in this file."""
    assert real_report["enforced"] > 0, real_report["wiring"]


#: The FIFTH gate that leaves the ENFORCED column, and the only one that leaves
#: it as UNPROVEN rather than STATUS_IGNORED. Kept separate from
#: `_STATUS_IGNORED_TODAY` because the two are different claims and different
#: repairs: "the status provably has no reader" versus "this analysis cannot
#: follow the status to a decision". Collapsing them would let a future change
#: quietly upgrade a guess into a proof.
def test_884_the_fifth_false_enforced_is_reported_as_UNDECIDED(real_report):
    row = next((r for r in real_report["gates"]
                if r["gate"] == "mixed_signal_top_lvs_run"), None)
    assert row is not None, "mixed_signal_top_lvs_run left the flow definition"
    assert row["enforcement"] == "AUDIT_ONLY", row
    assert row["wiring"] == A.INLINE_UNPROVEN, row


def test_884_the_real_tree_census_adds_up(real_report):
    """The five that leave ENFORCED are accounted for, not merely absent.

    MEASURED on this tree: ENFORCED 21 -> 16, and every gate that left is
    named by a runner in a real argv — so none of them fell out of the audit,
    which would satisfy "no longer ENFORCED" while reporting nothing at all.
    """
    left = set(_STATUS_IGNORED_TODAY) | {"mixed_signal_top_lvs_run"}
    src = A.runner_source(_PROGRAMS)
    for gate in sorted(left):
        row = next((r for r in real_report["gates"] if r["gate"] == gate), None)
        assert row is not None, gate
        assert row["wiring"] != A.NOT_INVOKED, row
        assert A._invoked(src, gate), (
            f"{gate} is no longer named by any runner; the 21 -> 16 delta "
            f"this change measured no longer describes this tree")
