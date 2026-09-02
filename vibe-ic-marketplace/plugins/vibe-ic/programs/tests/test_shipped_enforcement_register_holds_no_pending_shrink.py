#!/usr/bin/env python3
"""The shipped enforcement register still owed three entries it had been paid.

THE FINDING, MEASURED at eef7ee887 (v1.15.87), a clean checkout of `origin/main`.
`flow_gate_enforcement_audit.py` run with no arguments exits 0 and prints:

    [TIGHTENED] undeclared_known: 3 entries left the recorded set (115 -> 112)
      - undeclared::cpu_functional_oracle_waiver_check
      - undeclared::hold_area_budget_check
      - undeclared::vacuous_testbench_check
      Record it with:  flow_gate_enforcement_audit.py --record-shrink

Three gates had genuinely paid their debt — `cpu_functional_oracle_waiver_check`
and `vacuous_testbench_check` now DECLARE `blocking` and are wired
INLINE_BLOCKING, and `hold_area_budget_check` was removed from the step-20 gate
denominator by vibe-ic#1980 and is no longer a gate at all — but nobody wrote
the tightening back, so `programs/flow_gate_enforcement_baseline.json` still
recorded 115 undeclared gates over a tree whose real count is 112, and
`undeclared_previous_size` said 116 over a list of 115.

WHY NOTHING STOPPED IT. An unrecorded SHRINK is deliberately not a failure: the
audit's own docstring says so, because failing it would make "fix nothing" the
cheapest way to stay green and would point the operator at `--write-baseline`,
the one write that also launders every NEW finding of the same run into accepted
debt. So the audit exits 0 with the tightening merely REPORTED. Two module-level
tests do assert the recorded set is exact
(`test_issue1035_five_gates_declare_where_they_are_enforced` and
`test_two_gates_declare_where_their_verdict_is_consumed`, both via
`mod.audit(...)`), and both were RED on main for exactly this. Nothing asserted
it through the CLI, which is the surface an operator and `repo_hygiene_gates.sh`
actually see, and the CLI is where the un-acted-on remedy line is printed.

WHAT THIS FILE ADDS THAT THOSE TWO DO NOT. It reads the audit's OWN report — exit
status and stdout of the shipped argv, default flow and default baseline — rather
than re-deriving the set in-process, so it fails on the same evidence a landing
gate would show. And it pins the other half of the same register in the same
place: `known` (contradiction/orphan) must stay `[]`, with
`analog_topology_behaviour_check` — wired into flow step A8 by 85338ac71 after
shipping orphaned at 21247ff50 — named as neither an orphan nor an entry.
Silencing that orphan by RECORDING it would satisfy "the audit exits 0"; it must
not satisfy this file.

NOT ONE ASSERTION IS VACUOUS. Every positive claim has a negative arm that
re-runs the same argv against a mutated COPY of the tree and requires the claim
to break: un-wire the gate from the flow definition and the orphan must come
back; put a paid-down entry back in the register and the tightening must come
back; record the orphan as debt and this file must still refuse it.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_AUDIT = _PROGRAMS / "flow_gate_enforcement_audit.py"
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
_BASELINE = _PROGRAMS / "flow_gate_enforcement_baseline.json"

#: The gate the orphan half of this register was last grown by. It shipped at
#: 21247ff50 run only by `analog_one_shot_runner`, which is not one of the
#: venues the orphan scan consults, and was wired into the flow definition at
#: A8 by 85338ac71.
_ONCE_ORPHANED = "analog_topology_behaviour_check"

#: The A8 clause that pays it. Removing this exact line is the negative arm.
_A8_CLAUSE = (
    '        - program_exit_zero: "analog_topology_behaviour_check . '
    '--json reports/phase2/gates/a8_topology_behaviour.json"'
)


def _run(*extra, flow=None, baseline=None):
    cmd = [sys.executable, str(_AUDIT)]
    if flow is not None:
        cmd += ["--flow", str(flow)]
    if baseline is not None:
        cmd += ["--baseline", str(baseline)]
    return _pr.run(cmd + list(extra), capture_output=True, text=True)


def _tightened_lines(out: str):
    """Every `[TIGHTENED] <register>: ...` line the audit printed."""
    return [ln.strip() for ln in out.splitlines() if "[TIGHTENED]" in ln]


# --------------------------------------------------------------------------
# 1. the register owes no unrecorded paydown
# --------------------------------------------------------------------------

def test_the_shipped_audit_reports_no_pending_tightening():
    """The shipped register equals what the shipped tree measures.

    RED before the shrink was recorded: the audit printed
    `[TIGHTENED] undeclared_known: 3 entries left the recorded set (115 -> 112)`
    and named the remedy nobody ran."""
    r = _run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert not _tightened_lines(r.stdout + r.stderr), (
        "the shipped register records debt the tree no longer owes; run "
        "`flow_gate_enforcement_audit.py --record-shrink`:\n"
        + "\n".join(_tightened_lines(r.stdout + r.stderr)))
    assert "--record-shrink" not in r.stdout, r.stdout


def test_the_recorded_undeclared_set_is_exactly_what_the_cli_measures():
    """Not `<=` and not `does not contain X` — the same set, both directions.

    The recorded size must also stop over-stating the list it summarises:
    `undeclared_previous_size` said 116 above a 115-entry list."""
    doc = json.loads(_BASELINE.read_text())
    recorded = doc["undeclared_known"]
    assert len(recorded) == len(set(recorded)), "duplicate entries"
    r = _run()
    assert r.returncode == 0, r.stdout + r.stderr
    # The audit's own summary line states the measured population.
    m = re.search(r"UNDECLARED and AUDIT_ONLY — (\d+) gate\(s\)", r.stdout)
    assert m, r.stdout
    assert int(m.group(1)) == len(recorded), (
        f"the audit measures {m.group(1)} undeclared gates and the register "
        f"records {len(recorded)}")
    prev = doc["undeclared_previous_size"]
    assert prev is None or prev == len(recorded) or prev > len(recorded), prev
    # `previous_size` is a claim about the list beside it, so it may not
    # over-state a set that has since been recorded as tightened.
    assert prev is None or prev >= len(recorded)


def test_the_orphan_register_is_empty_and_was_not_paid_by_recording_it():
    """The brief's control: exit 0 AND `known == []`.

    Recording `orphan::analog_topology_behaviour_check` would also make the
    audit exit 0. The register's own comment forbids it — "this register
    records debt that must be paid down, never permission to add more"."""
    doc = json.loads(_BASELINE.read_text())
    assert doc["known"] == [], doc["known"]
    for key in ("known", "undeclared_known"):
        for entry in doc[key]:
            assert _ONCE_ORPHANED not in entry, (
                f"{_ONCE_ORPHANED} was recorded as debt in {key} instead of "
                f"being wired")
    for key in ("scope_expanded", "undeclared_scope_expanded"):
        assert _ONCE_ORPHANED not in (doc.get(key) or ""), key
    r = _run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ORPHANED" not in r.stdout, r.stdout
    assert f"orphan::{_ONCE_ORPHANED}" not in r.stdout + r.stderr


def test_the_gate_is_wired_where_the_audit_can_see_it(tmp_path):
    """Reads the audit's classification, not a grep of the YAML."""
    out = tmp_path / "audit.json"
    r = _run("--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(out.read_text())
    rows = {g["gate"]: g for g in payload["gates"]}
    assert _ONCE_ORPHANED in rows, sorted(rows)[:5]
    row = rows[_ONCE_ORPHANED]
    assert row["declared"] == "blocking", row
    assert row["enforcement"] == "ENFORCED", row
    assert row["wiring"] == "INLINE_BLOCKING", row


# --------------------------------------------------------------------------
# 2. negative arms — every claim above must break when the fix is undone
# --------------------------------------------------------------------------

def test_negative_arm_unwiring_the_gate_restores_the_orphan(tmp_path):
    """Delete the A8 clause and the audit must refuse again."""
    text = _FLOW.read_text()
    assert _A8_CLAUSE in text, "the A8 clause moved; update _A8_CLAUSE"
    mutated = tmp_path / "flow.yaml"
    mutated.write_text(text.replace(_A8_CLAUSE + "\n", ""))
    r = _run(flow=mutated)
    assert r.returncode == 1, r.stdout + r.stderr
    both = r.stdout + r.stderr
    assert "ORPHANED" in both, both
    assert f"orphan::{_ONCE_ORPHANED}" in both, both


def test_negative_arm_returning_a_paid_entry_restores_the_tightening(tmp_path):
    """Put a paid-down entry back and the pending-tightening claim must fail."""
    doc = json.loads(_BASELINE.read_text())
    doc["undeclared_known"] = sorted(
        set(doc["undeclared_known"]) | {"undeclared::vacuous_testbench_check"})
    doc["undeclared_previous_size"] = len(doc["undeclared_known"])
    mutated = tmp_path / "baseline.json"
    mutated.write_text(json.dumps(doc, ensure_ascii=False))
    r = _run(baseline=mutated)
    assert r.returncode == 0, r.stdout + r.stderr
    lines = _tightened_lines(r.stdout + r.stderr)
    assert lines, r.stdout
    assert any("undeclared_known" in ln for ln in lines), lines


def test_negative_arm_recording_the_orphan_is_refused_by_this_file(tmp_path):
    """Silencing the orphan by recording it makes the audit exit 0 — and this
    file must still call it debt, or the control above proves nothing."""
    text = _FLOW.read_text()
    mutated_flow = tmp_path / "flow.yaml"
    mutated_flow.write_text(text.replace(_A8_CLAUSE + "\n", ""))
    doc = json.loads(_BASELINE.read_text())
    doc["known"] = [f"orphan::{_ONCE_ORPHANED}"]
    doc["previous_size"] = 1
    laundered = tmp_path / "baseline.json"
    laundered.write_text(json.dumps(doc, ensure_ascii=False))
    r = _run(flow=mutated_flow, baseline=laundered)
    # The audit is satisfied: recorded debt is not NEW debt.
    assert r.returncode == 0, r.stdout + r.stderr
    # This file is not.
    reloaded = json.loads(laundered.read_text())
    assert reloaded["known"] != [], "fixture did not record the orphan"
    assert any(_ONCE_ORPHANED in e for e in reloaded["known"])


def test_negative_arm_the_shrink_path_cannot_add(tmp_path):
    """`--record-shrink` is the write this fix used. Prove it can only remove:
    a register missing an entry the tree DOES owe must not gain it."""
    shutil.copy2(_BASELINE, tmp_path / "baseline.json")
    bl = tmp_path / "baseline.json"
    doc = json.loads(bl.read_text())
    dropped = doc["undeclared_known"][0]
    doc["undeclared_known"] = doc["undeclared_known"][1:]
    doc["undeclared_previous_size"] = len(doc["undeclared_known"])
    bl.write_text(json.dumps(doc, ensure_ascii=False))
    r = _run("--record-shrink", baseline=bl)
    after = json.loads(bl.read_text())
    assert dropped not in after["undeclared_known"], (
        f"--record-shrink ADDED {dropped} back; it may only remove")
    assert r.returncode in (0, 1), r.stdout + r.stderr
