#!/usr/bin/env python3
"""ORGANIC #884 — ENFORCED must mean "the exit status can stop the step", not
"the filename appears inside a string".

`flow_gate_enforcement_audit` is the instrument the rest of the flow-gate work
trusts: it is what says which of the 120 declared gates can actually block. It
decided that from `_invoked()`, which asks whether the gate's filename appears
in a string literal somewhere in a runner. A runner that spawns a gate and
throws the exit status away is TEXTUALLY IDENTICAL to one that stops the step
on it, so the audit scored the first as enforcement.

Measured on the tree that carried this defect: 19 gates reported ENFORCED, of
which 4 could not block anything —

    rtl_hygiene_lint   `rc, out, err = _run([...])`, `rc` never read again
    dfm_screen_check   `subprocess.run(...)` with the result not bound at all
    bsdl_emit          the same, inside `except Exception: pass`; the
                       `r.returncode` eleven lines later is a DIFFERENT
                       subprocess (the ATPG run)
    sdc_syntax_check   `r = subprocess.run(...)`, `r.returncode` never read

An audit of checks that lie, lying the same way, is the worst instance of the
class — every other verdict in the campaign was read through it.

Every test below is chip-AGNOSTIC: the fixtures are synthetic runners, and no
design, PDK, vendor or cell name appears anywhere.
"""
from __future__ import annotations

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
    it scanning ~10 MB of concatenated runner source — and re-running it per
    test would put a minute on the suite for the same answer."""
    return A.audit(_FLOW, _PROGRAMS)


def _tree(tmp_path: Path, runner_src: str, gates: list) -> Path:
    """A programs dir holding one synthetic runner and a flow declaring
    `gates`. Returns the flow path; the programs dir is `tmp_path`."""
    (tmp_path / _RUNNER).write_text(runner_src)
    flow = tmp_path / "flow.yaml"
    flow.write_text("".join(
        f'      - program_exit_zero: "{g} . --json {g}.json"\n' for g in gates))
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
    """The finding itself. Both gates are named in the same shape of string
    literal; only one of them can stop its step."""
    rows = _rows(tmp_path, _SPAWN_AND_DROP,
                 ["dropped_check", "reading_check"])
    assert rows["dropped_check"]["enforcement"] == "AUDIT_ONLY", \
        rows["dropped_check"]
    assert rows["dropped_check"]["wiring"] == A.INLINE_STATUS_IGNORED, \
        rows["dropped_check"]


def test_884_reading_the_status_is_still_enforcement(tmp_path):
    """The two-sided control. A predicate that answered AUDIT_ONLY to
    everything would pass the test above and be useless — worse than the
    defect, because it would hide the gates that DO block."""
    rows = _rows(tmp_path, _SPAWN_AND_DROP,
                 ["dropped_check", "reading_check"])
    assert rows["reading_check"]["enforcement"] == "ENFORCED", \
        rows["reading_check"]


def test_884_the_dropped_gate_is_still_NAMED_by_the_runner(tmp_path):
    """Locates the repair precisely: the runner does name the gate — the old
    text predicate was not wrong about that. What it could not see is that
    nothing reads the status. If this ever fails, the fixture stopped
    exercising the defect and the tests above prove nothing."""
    src = (tmp_path / "src.py")
    src.write_text(_SPAWN_AND_DROP)
    assert A._invoked(_SPAWN_AND_DROP, "dropped_check") is True


# ---------------------------------------------------------------------------
# THE `_run` WRAPPER — a helper that RETURNS the status has delegated the
# decision to its caller. `rtl_hygiene_lint`'s caller drops it.
# ---------------------------------------------------------------------------
_TUPLE_WRAPPER = '''
import subprocess
import sys


def _run(cmd, timeout=600):
    """The runners' house helper: returns (rc, out, err)."""
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return cp.returncode, cp.stdout, cp.stderr


def step_scrapes_the_text_and_drops_the_rc():
    rc, out, err = _run([sys.executable, "dropped_check.py", "--fix"])
    for line in (out + err).splitlines():
        if "repaired" in line:
            return 1
    return 0


def step_reads_the_rc():
    rc, out, err = _run([sys.executable, "reading_check.py", "--fix"])
    if rc != 0:
        return "FAIL"
    return "PASS"
'''


def test_884_a_wrapper_returning_the_status_does_not_consume_it(tmp_path):
    """`_run` ends in `return cp.returncode, ...`. Counting that as
    consumption would rebuild the false positive one level down: the wrapper
    hands the decision to its caller, and this caller binds `rc` and never
    reads it — the exact `rtl_hygiene_lint` shape."""
    rows = _rows(tmp_path, _TUPLE_WRAPPER,
                 ["dropped_check", "reading_check"])
    assert rows["dropped_check"]["enforcement"] == "AUDIT_ONLY", \
        rows["dropped_check"]
    assert rows["dropped_check"]["wiring"] == A.INLINE_STATUS_IGNORED, \
        rows["dropped_check"]
    assert rows["reading_check"]["enforcement"] == "ENFORCED", \
        rows["reading_check"]


# ---------------------------------------------------------------------------
# THE PROXIMITY TRAP — `bsdl_emit`'s shape exactly. A `.returncode` a few lines
# below belongs to a DIFFERENT subprocess.
# ---------------------------------------------------------------------------
_PROXIMITY = '''
import subprocess
import sys


def step_with_two_subprocesses(project):
    r = subprocess.run([sys.executable, "other_tool.py", project],
                       capture_output=True, text=True)
    try:
        subprocess.run([sys.executable, "trapped_check.py", project],
                       capture_output=True, text=True)
    except Exception:
        pass
    # This status belongs to other_tool.py, NOT to trapped_check.py.
    if r.returncode == 0:
        return "PASS"
    return "FAIL"
'''


def test_884_a_nearby_returncode_from_another_process_is_not_consumption(
        tmp_path):
    """The mechanism that produced the `bsdl_emit` false positive. An analysis
    that searched the enclosing function for `returncode` would find one and
    call the gate enforced — reading proximity as evidence, which is the same
    error as reading a filename as enforcement."""
    rows = _rows(tmp_path, _PROXIMITY, ["trapped_check"])
    assert rows["trapped_check"]["enforcement"] == "AUDIT_ONLY", \
        rows["trapped_check"]
    assert rows["trapped_check"]["wiring"] == A.INLINE_STATUS_IGNORED, \
        rows["trapped_check"]


def test_884_a_swallowed_raise_is_not_enforcement(tmp_path):
    """`check=True` inside `try: ... except: pass` raises into a handler that
    drops it. The gate cannot stop anything."""
    src = '''
import subprocess
import sys


def step():
    try:
        subprocess.run([sys.executable, "swallowed_check.py"], check=True)
    except Exception:
        pass


def step_unswallowed():
    subprocess.run([sys.executable, "raising_check.py"], check=True)
'''
    rows = _rows(tmp_path, src, ["swallowed_check", "raising_check"])
    assert rows["swallowed_check"]["enforcement"] == "AUDIT_ONLY", \
        rows["swallowed_check"]
    assert rows["raising_check"]["enforcement"] == "ENFORCED", \
        rows["raising_check"]


# ---------------------------------------------------------------------------
# OVER-TIGHTENING CONTROL — the genuinely wired gates must survive.
#
# The step-23/25 sign-off gates are named in a module-level TABLE and spawned
# by a shared helper. A predicate that only looked for the filename lexically
# inside a `subprocess.run(...)` argv would call them all unenforced, which
# would be a NEW lie in the opposite direction.
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
    """One hop of indirection, blocking at the far end, must still read as
    enforcement — otherwise the strengthened audit would under-report and the
    repair would have swapped one false register for another."""
    rows = _rows(tmp_path, _TABLE_DISPATCH, ["table_check"])
    assert rows["table_check"]["enforcement"] == "ENFORCED", rows["table_check"]


def test_884_a_fallback_binding_in_an_except_handler_is_not_a_rebind(tmp_path):
    """`cp = subprocess.run(...)` / `except: cp = None` / `if cp is not None
    and cp.returncode != 0:` is enforcement. Treating the handler's assignment
    as ending the first binding's life would hide a gate that really does
    block — measured: it hid `synth_netlist_check` while this fix was being
    written."""
    src = '''
import subprocess
import sys


def step(project):
    try:
        snc = subprocess.run([sys.executable, "fallback_check.py", project],
                             capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        snc = None
    if snc is not None and snc.returncode != 0:
        return "FAIL"
    return "PASS"
'''
    rows = _rows(tmp_path, src, ["fallback_check"])
    assert rows["fallback_check"]["enforcement"] == "ENFORCED", \
        rows["fallback_check"]


def test_884_reading_only_stdout_is_not_reading_the_status(tmp_path):
    """Scraping `cp.stdout` for a keyword and branching on THAT is a decision
    about text, not about the gate's verdict. A gate that FAILs silently — the
    normal case, since these gates report by exit code — sails straight
    through."""
    src = '''
import subprocess
import sys


def step():
    cp = subprocess.run([sys.executable, "text_only_check.py"],
                        capture_output=True, text=True)
    if "ERROR" in cp.stdout:
        return "FAIL"
    return "PASS"
'''
    rows = _rows(tmp_path, src, ["text_only_check"])
    assert rows["text_only_check"]["enforcement"] == "AUDIT_ONLY", \
        rows["text_only_check"]


def test_884_a_bare_check_returncode_call_is_enforcement(tmp_path):
    """`cp.check_returncode()` raises on a non-zero exit all by itself.
    Demanding an explicit `if` here would under-report a gate that really does
    stop the step — the opposite error, and just as wrong."""
    src = '''
import subprocess
import sys


def step():
    cp = subprocess.run([sys.executable, "raising_gate_check.py"])
    cp.check_returncode()
'''
    rows = _rows(tmp_path, src, ["raising_gate_check"])
    assert rows["raising_gate_check"]["enforcement"] == "ENFORCED", \
        rows["raising_gate_check"]


# ---------------------------------------------------------------------------
# THE REAL TREE
# ---------------------------------------------------------------------------
#: The four gates this audit called ENFORCED while the runner discarded their
#: verdict. Repairing a CALL SITE is separate work that changes what a real run
#: blocks on — a flow-owner decision, not an audit change — so #884 fixed only
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
    rep = real_report
    row = next((r for r in rep["gates"] if r["gate"] == gate), None)
    assert row is not None, f"{gate} left the flow definition"
    assert row["enforcement"] == "AUDIT_ONLY", row
    assert row["wiring"] == A.INLINE_STATUS_IGNORED, row


def test_884_being_named_by_a_runner_is_not_enough_on_the_real_tree(
        real_report):
    """The two questions must be demonstrably different where it counts. If
    every named gate also blocked, `_invoked` alone would have been a correct
    predicate and this whole repair would be inert."""
    src = A.runner_source(_PROGRAMS)
    rep = real_report
    named = {r["gate"] for r in rep["gates"] if A._invoked(src, r["gate"])}
    blocking = {r["gate"] for r in rep["gates"]
                if r["wiring"] == A.INLINE_BLOCKING}
    assert blocking < named, (
        "no gate is named-but-not-blocking; the strengthened predicate has "
        "stopped distinguishing anything")


def test_884_enforced_always_means_a_consumed_exit_status(real_report):
    """The invariant, stated once: ENFORCED is exactly INLINE_BLOCKING. No
    other wiring may reach the ENFORCED column, on any tree."""
    rep = real_report
    for r in rep["gates"]:
        assert (r["enforcement"] == "ENFORCED") is (
            r["wiring"] == A.INLINE_BLOCKING), r
    assert rep["enforced"] + rep["audit_only"] == rep["total_gates"]


def test_884_a_status_that_is_only_RECORDED_is_not_enforcement(tmp_path):
    """The third state, and the reason there is one.

    Here the exit status IS read — folded into a verdict string and appended to
    a report — but nothing shown to this analysis turns it into a decision.
    That is neither enforcement nor a discarded status, so calling it either
    would be a claim the evidence does not support. It is UNPROVEN, and
    UNPROVEN is not ENFORCED: unknown is not yes, which is the whole asymmetry
    of this repair.

    This is `mixed_signal_top_lvs_run`'s real shape, the one gate the
    strengthened audit moved out of ENFORCED without accusing the runner of
    dropping anything."""
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
