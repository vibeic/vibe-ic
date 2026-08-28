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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "flow_gate_enforcement_audit.py"
_BASELINE = _PROGRAMS / "flow_gate_enforcement_baseline.json"


def _run(*extra, baseline=None, flow=None, programs=None, extra_kw=()):
    extra = tuple(extra) + tuple(extra_kw)
    cmd = [sys.executable, str(_PROG)]
    if baseline is not None:
        cmd += ["--baseline", str(baseline)]
    if flow is not None:
        cmd += ["--flow", str(flow)]
    if programs is not None:
        cmd += ["--programs", str(programs)]
    return _pr.run(cmd + list(extra), capture_output=True, text=True)


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
    becomes standing permission.

    IT LEAVES BY BEING RECORDED, NOT BY REDDENING THE BOARD. This arm used to
    assert `rc == 1` on a paid debt, which made "fix nothing" the cheapest way
    to keep this audit green — and the remedy the audit named, `--write-baseline`,
    records whatever THAT run measured, so on a day when a debt is paid and a
    new finding arrives it files the new finding as accepted debt. A ratchet
    that costs its own operator something in the tightening direction is not a
    ratchet.

    So what is asserted now is strictly more than before: the paid entry is
    NAMED, the run does NOT fail over it, the audit does NOT point at the
    laundering flag, and `--record-shrink` actually removes it — and removes
    ONLY it. The old form could be satisfied by a program that failed every
    run; this one cannot.

    BOTH registers are recorded in the fixture, deliberately. With
    `undeclared_known` absent the run exits 1 for being UNRECORDED, so the old
    `rc == 1` was true whatever the shrink did — two causes folded into one
    assertion.
    """
    bl = tmp_path / "bl.json"
    rep = tmp_path / "rep.json"
    known = json.loads(_BASELINE.read_text())["known"]
    seed = {"known": known, "undeclared_known": []}
    bl.write_text(json.dumps(seed))
    _run("--json", str(rep), baseline=bl)
    measured = json.loads(rep.read_text())
    now_u = sorted(f"undeclared::{u['gate']}"
                   for u in (measured.get("undeclared_audit_only") or []))

    paid = "orphan::a_gate_that_is_gone"
    bl.write_text(json.dumps({"known": known + [paid],
                              "undeclared_known": now_u}))
    r = _run(baseline=bl)
    assert r.returncode == 0, r.stdout + r.stderr
    assert paid in r.stdout and "TIGHTENED" in r.stdout, r.stdout
    assert "--write-baseline" not in r.stdout, (
        "the audit still points a reader at the flag whose other effect is to "
        "record this run's NEW findings as accepted debt")

    r2 = _run("--record-shrink", baseline=bl)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    after = json.loads(bl.read_text())
    assert paid not in after["known"], "the paid debt did not leave the register"
    assert set(after["known"]) <= set(known + [paid]), (
        "the recording ADDED an entry — that is --write-baseline under another "
        "name")
    assert set(after["undeclared_known"]) <= set(now_u)


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
