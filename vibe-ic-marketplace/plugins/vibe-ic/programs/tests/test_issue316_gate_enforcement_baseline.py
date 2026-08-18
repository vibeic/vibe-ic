#!/usr/bin/env python3
"""#316/#306 — the enforcement audit must itself be able to stop something.

`flow_gate_enforcement_audit` measures which gates can actually block a run.
It found 4 gates declaring an intent they are not wired for — and it exited 1
about that while being wired into nothing, which is the exact defect it
names, one level up.

Fixing those 4 changes what a REAL run blocks on: a flow-owner decision, not
this audit's. So they are recorded as DEBT and the audit blocks anything NEW.
The class stops growing without the audit quietly setting enforcement policy.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "flow_gate_enforcement_audit.py"
_BASELINE = _PROGRAMS / "flow_gate_enforcement_baseline.json"


def _run(*extra, baseline=None, flow=None, programs=None):
    cmd = [sys.executable, str(_PROG)]
    if baseline is not None:
        cmd += ["--baseline", str(baseline)]
    if flow is not None:
        cmd += ["--flow", str(flow)]
    if programs is not None:
        cmd += ["--programs", str(programs)]
    return subprocess.run(cmd + list(extra), capture_output=True, text=True,
                          timeout=60)


def _tree_with_one_contradiction(tmp_path):
    """A minimal tree that DOES owe one entry: a gate declaring
    `ENFORCEMENT: blocking`, wired into the flow, invoked by no runner.

    #306 paydown — the guards below used to be driven by the REAL tree's debt,
    which made them silently vacuous the moment that debt reached zero: with an
    empty register there is no "new" entry to detect and no growth to refuse,
    so all three passed by doing nothing. An empty register is the GOAL state,
    so the guards must be proven against debt this test constructs itself.
    """
    (tmp_path / "faux_check.py").write_text(
        '"""x\n\nENFORCEMENT: blocking\n"""\n')
    flow = tmp_path / "flow.yaml"
    flow.write_text('      - program_exit_zero: "faux_check . --json x.json"\n')
    return flow, tmp_path


def test_316_shipped_tree_passes_against_its_recorded_debt():
    """Green as landed — an audit that ships red blocks nothing, which is the
    failure mode it exists to name."""
    r = _run()
    if r.returncode == 2:
        return
    assert r.returncode == 0, r.stdout + r.stderr
    assert "recorded as debt" in r.stdout


def test_316_the_recorded_debt_is_named_not_hidden():
    """A count alone would let the register become a shrug. Every entry names
    its gate and which contract it broke.

    #306 paydown — this used to also assert the register was NON-EMPTY, on the
    reasoning that an empty one makes the gate vacuous. That had it backwards:
    empty is the state the whole register exists to reach, and asserting
    against it made paying the last entry a test failure. Emptiness is not what
    keeps this honest — `test_316_a_new_contradiction_fails` and
    `test_316_register_may_not_grow` are, and both now prove themselves against
    debt they construct rather than debt the tree happens to owe.
    """
    known = json.loads(_BASELINE.read_text())["known"]
    for k in known:
        kind, _, gate = k.partition("::")
        assert kind in ("contradiction", "orphan"), k
        assert gate and (_PROGRAMS / f"{gate}.py").is_file(), k


def test_316_a_new_contradiction_fails(tmp_path):
    """THE guard: an entry absent from the register must fail.

    Driven by a gate this test creates, so it keeps proving the guard after the
    real register reaches zero — at which point pointing it at the real tree
    would assert nothing at all.
    """
    flow, programs = _tree_with_one_contradiction(tmp_path)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": []}))
    r = _run(baseline=bl, flow=flow, programs=programs)
    assert r.returncode == 1, r.stdout
    assert "declare an intent they are not wired for" in r.stdout
    assert "faux_check" in r.stdout, r.stdout


def test_316_paid_debt_must_leave_the_register(tmp_path):
    """A register entry that no longer contradicts is stale; left in place it
    becomes standing permission."""
    bl = tmp_path / "bl.json"
    known = json.loads(_BASELINE.read_text())["known"]
    bl.write_text(json.dumps({"known": known + ["orphan::a_gate_that_is_gone"]}))
    r = _run(baseline=bl)
    assert r.returncode == 1, r.stdout
    assert "the debt was paid" in r.stdout


def test_316_register_may_not_grow(tmp_path):
    """The one control that keeps this from becoming a waiver list.

    Also driven by constructed debt: against an already-empty real register
    there is nothing to grow FROM, so the refusal could never be exercised.
    """
    flow, programs = _tree_with_one_contradiction(tmp_path)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": []}))
    r = _run("--write-baseline", baseline=bl, flow=flow, programs=programs)
    assert r.returncode == 1, r.stdout
    assert "refusing to GROW" in r.stdout
    assert json.loads(bl.read_text())["known"] == [], "the refused write landed"


def test_316_an_empty_register_is_a_valid_terminal_state(tmp_path):
    """#306 paydown — paying the LAST entry must leave the audit green.

    A register that cannot reach zero is a register nobody can finish paying,
    and the three guards above would have made the final payment a test
    failure. Proven on a tree that owes nothing.
    """
    (tmp_path / "clean_check.py").write_text('"""x\n\nENFORCEMENT: advisory\n"""\n')
    flow = tmp_path / "flow.yaml"
    flow.write_text('      - program_exit_zero: "clean_check . --json x.json"\n')
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": []}))
    r = _run(baseline=bl, flow=flow, programs=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 recorded as debt" in r.stdout, r.stdout


# ══════════════════════════════════════════════════════════════════════
# #1705 — AN UNREADABLE BASELINE IS NOT AN EMPTY ONE
# ══════════════════════════════════════════════════════════════════════
# Every control below plants a defect in the BASELINE and asserts the audit
# REFUSES (rc 2, NOT_CHECKED) instead of reporting a register it never read.
# The shared shape is deliberate: a flow with no gates, so `now` is empty and
# the pre-#1705 code reached `[PASS] no NEW enforcement contradiction (0
# recorded as debt)` — a verdict line stating a measurement of a file it had
# just failed to open. Each control therefore has to distinguish rc 2 from a
# GREEN run, which is the direction that actually cost something; a control
# that only distinguished it from rc 1 would pass on the broken code.

def _no_gate_tree(tmp_path):
    """A flow declaring no `program_exit_zero` gate at all.

    `now` and `now_u` are both empty over it, so ANY exit code other than 2
    here is this program claiming it compared today's set against the recorded
    one. It is the arm where "I could not read it" and "there was nothing in
    it" produce identical output on the old code and must not on the new.
    """
    flow = tmp_path / "flow.yaml"
    flow.write_text("steps:\n  - id: 1\n    name: nothing\n")
    return flow, tmp_path


#: A baseline that records REAL debt. The point of every planted defect below
#: is that this content is what the audit fails to read — so a run that reports
#: "0 recorded as debt" over it is off by three entries, not by a rounding.
_REAL_DEBT = {
    "known": ["contradiction::faux_check.py", "orphan::other_check.py"],
    "undeclared_known": ["undeclared::third_check.py"],
}


def _planted(tmp_path, name, write):
    """Write a corrupt baseline and return it, with the intact one beside it."""
    bl = tmp_path / name
    write(bl)
    return bl


def test_1705_a_baseline_that_cannot_be_OPENED_is_refused(tmp_path):
    """PLANTED DEFECT: the file exists and the process may not read it.

    Before #1705 the `except OSError` arm set `doc = {}` and this run exited 0
    printing "0 recorded as debt" — a gate passing a tree against a register it
    never opened. It is the worst of the three because nothing about the file
    is wrong; only this run's ability to read it is.
    """
    if os.geteuid() == 0:
        pytest.skip("running as root: chmod 000 does not deny a read")
    flow, programs = _no_gate_tree(tmp_path)
    bl = _planted(tmp_path, "unopenable.json",
                  lambda p: (p.write_text(json.dumps(_REAL_DEBT)),
                             p.chmod(0o000)))
    try:
        r = _run(baseline=bl, flow=flow, programs=programs)
    finally:
        bl.chmod(0o600)
    assert r.returncode == 2, (
        f"the audit reached a VERDICT over a baseline it could not open "
        f"(rc {r.returncode}). stdout:\n{r.stdout}")
    assert "0 recorded as debt" not in r.stdout, (
        "it reported the register's SIZE — a measurement of a file it never "
        "read")
    assert "IO_ERROR" in r.stderr and str(bl) in r.stderr, r.stderr


def test_1705_a_baseline_that_is_not_JSON_is_refused(tmp_path):
    """PLANTED DEFECT: a truncated write — the commonest way a register rots."""
    flow, programs = _no_gate_tree(tmp_path)
    bl = _planted(tmp_path, "truncated.json",
                  lambda p: p.write_text(json.dumps(_REAL_DEBT)[:37]))
    r = _run(baseline=bl, flow=flow, programs=programs)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "0 recorded as debt" not in r.stdout, r.stdout
    assert "IO_ERROR" in r.stderr, r.stderr


def test_1705_a_baseline_that_is_not_an_object_is_refused(tmp_path):
    """PLANTED DEFECT: valid JSON, wrong shape — the `isinstance` arm.

    It reached the SAME `doc = {}`, so it is the same fabrication with a
    different cause and needs its own control: a fix that only caught the
    exception would leave this one reporting "no debt" over a list of it.
    """
    flow, programs = _no_gate_tree(tmp_path)
    bl = _planted(tmp_path, "array.json",
                  lambda p: p.write_text(json.dumps(_REAL_DEBT["known"])))
    r = _run(baseline=bl, flow=flow, programs=programs)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "0 recorded as debt" not in r.stdout, r.stdout
    assert "not an object" in r.stderr, r.stderr


def test_1705_a_register_whose_membership_cannot_be_read_is_refused(tmp_path):
    """PLANTED DEFECT: `known` is a STRING, not a list.

    This one is not caught by any of the three arms above — the file opens,
    parses, and IS an object. `_recorded` did
    `sorted(str(x) for x in doc.get(key))`, which over a string iterates
    CHARACTERS: a register corrupted to `"orphan::a"` read as nine entries of
    one letter each, so every real entry reported `paid` and nine invented ones
    reported NEW. Both halves of that are fabricated measurements.
    """
    flow, programs = _no_gate_tree(tmp_path)
    bl = _planted(tmp_path, "stringly.json",
                  lambda p: p.write_text(json.dumps(
                      {"known": "orphan::a_gate", "undeclared_known": []})))
    r = _run(baseline=bl, flow=flow, programs=programs)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "IO_ERROR" in r.stderr and "not a list" in r.stderr, r.stderr


def test_1705_the_remedy_may_not_overwrite_the_evidence(tmp_path):
    """PLANTED DEFECT + the path the old message SENT you down.

    With an unreadable baseline the old read path printed "`known` is
    UNRECORDED in <file>" and told the operator to run `--write-baseline`. On
    that same unreadable file `--write-baseline` took prev=None, so the
    shrink-only ratchet had nothing to compare against and the recorded debt
    was replaced by whatever today's tree showed. A ratchet a truncated write
    can reset is not a ratchet.

    So the write path must refuse too, and the file must come back BYTE-
    IDENTICAL — the assertion is on the bytes, not on the exit code, because a
    program that refuses after writing has still destroyed the evidence.
    """
    flow, programs = _no_gate_tree(tmp_path)
    corrupt = json.dumps(_REAL_DEBT)[:37]
    bl = _planted(tmp_path, "truncated.json", lambda p: p.write_text(corrupt))
    before = bl.read_bytes()
    r = _run("--write-baseline", baseline=bl, flow=flow, programs=programs)
    assert r.returncode == 2, r.stdout + r.stderr
    assert bl.read_bytes() == before, (
        "the refused write LANDED — the recorded debt this run could not read "
        "has been overwritten by a run that never read it")


def test_1705_an_ABSENT_baseline_is_still_UNRECORDED_not_refused(tmp_path):
    """THE NEGATIVE CONTROL, and the reason this is a fix and not a blanket.

    Absent and unreadable are different states and the fix exists to separate
    them, so it must not merge them the other way. A first run against a
    baseline that was never written still reports UNRECORDED and still reaches
    a verdict — rc 0 over a tree owing nothing, rc 1 over a tree owing
    something, both proven here so the arm cannot rot into vacuity.
    """
    flow, programs = _no_gate_tree(tmp_path)
    missing = tmp_path / "never_written.json"
    assert not missing.exists()
    r = _run(baseline=missing, flow=flow, programs=programs)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "recorded as debt" in r.stdout, r.stdout

    owing = tmp_path / "owing"
    owing.mkdir()
    flow2, programs2 = _tree_with_one_contradiction(owing)
    r2 = _run(baseline=tmp_path / "also_never_written.json",
              flow=flow2, programs=programs2)
    assert r2.returncode == 1, r2.stdout + r2.stderr
    assert "UNRECORDED" in r2.stdout, r2.stdout


def test_1705_an_INTACT_baseline_still_decides(tmp_path):
    """THE OTHER NEGATIVE CONTROL: a readable baseline is still read.

    A refusal that fires on everything would satisfy every assertion above
    while making the audit useless. This arm plants the SAME debt as the
    corrupt files, intact, and requires the audit to reach a verdict ABOUT it.
    """
    flow, programs = _no_gate_tree(tmp_path)
    bl = tmp_path / "intact.json"
    bl.write_text(json.dumps(_REAL_DEBT))
    r = _run(baseline=bl, flow=flow, programs=programs)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "the debt was paid" in r.stdout, r.stdout
    assert "contradiction::faux_check.py" in r.stdout, r.stdout
