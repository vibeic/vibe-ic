#!/usr/bin/env python3
"""A gate can be wired to stop a step while its own file says it cannot.

THE ASYMMETRY, MEASURED. `flow_gate_enforcement_audit` fails a gate that
DECLARES `blocking` and is wired AUDIT_ONLY — an overclaim. The reverse is
silent: a gate wired INLINE_BLOCKING whose file declares `advisory` passes the
audit with rc 0, and a reader of that file is told the gate cannot stop the step
when it can. That is the same defect as vibe-ic#886 (silence is not a decision)
with the sign flipped, and it survived every version of this audit.

It is not hypothetical. On origin/main a4caccefe exactly ONE gate is in that
state, and this test names it: `phase1_expert_parse_track`, wired
INLINE_BLOCKING, declaring `advisory`.

WHY IT IS DISCLOSED AND NOT FAILED, which is the whole judgement in this change.
That gate's declaration reads:

    ENFORCEMENT: advisory
    (Advisory describes the FINDINGS. The track's EXECUTION is mandatory ...)

so it is using `advisory` for finding SEVERITY, while this audit measures
whether a RUNNER can stop the step. Two meanings of one token, and the gate's
author stated theirs explicitly rather than by accident. Failing it would settle
that dispute by turning a BLOCKING hygiene gate red — which decides a flow
owner's question by reddening everyone's landing path. So the class is a CENSUS:
recorded, printed on the PASS path where the misreading happens, and never
affecting the exit code.

WHAT THE CENSUS BUYS, given it cannot fail. Two things a silent pass did not:
the state is VISIBLE to anyone running the gate, and a SECOND gate entering this
state is visible the moment it does. That is the same shape as the `#886`
register — the point is that nothing joins the class unnoticed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
_AUDIT = _PROGRAMS / "flow_gate_enforcement_audit.py"


def _mod():
    spec = importlib.util.spec_from_file_location("_fgea_dir", _AUDIT)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


# ───────────────────────────────────────── the class exists and is reported

def test_the_audit_reports_the_direction_its_contradiction_scan_cannot_see():
    """The report must carry the class as DATA, not only as console text: a
    consumer reading the JSON would otherwise conclude every declaration
    matched its wiring."""
    rep = _mod().audit(_FLOW, _PROGRAMS)
    assert "declared_weaker_than_wired" in rep, (
        "the audit no longer reports the class at all, so a gate wired "
        "blocking while declaring advisory is invisible again")
    for row in rep["declared_weaker_than_wired"]:
        assert row["declared"] == "advisory"
        assert row["wiring"] == "INLINE_BLOCKING"


def test_the_live_instance_is_named_rather_than_counted():
    """A count tells nobody which gate to go and read."""
    rep = _mod().audit(_FLOW, _PROGRAMS)
    named = {r["gate"] for r in rep["declared_weaker_than_wired"]}
    assert "phase1_expert_parse_track" in named, (
        "phase1_expert_parse_track was the one live member of this class when "
        "this was written. If it has been resolved, that is good news — check "
        "it, then update this assertion to whatever the census now finds "
        "rather than deleting it")


def test_the_disclosure_reaches_the_console_on_the_pass_path(tmp_path):
    """The PASS line is what gets read as "every declaration matches its
    wiring". The disclosure has to be there, not only in a report nobody opens
    — and it must not change the exit code."""
    cp = _pr.run(
        [sys.executable, str(_AUDIT), "--json", str(tmp_path / "r.json")],
        capture_output=True, text=True)
    assert cp.returncode == 0, (cp.returncode, cp.stdout[-2000:])
    assert "DISCLOSURE" in cp.stdout, cp.stdout[-1500:]
    assert "phase1_expert_parse_track" in cp.stdout, cp.stdout[-1500:]
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["declared_weaker_than_wired"], rep.get("declared_weaker_than_wired")


# ═════════════════════════════════════════════════════════════ THE CONTROLS
#
# The census cannot fail, so every assertion above is "it reported something".
# That family is satisfied by a census that reports everything, and by one that
# reports the same thing regardless of input. These drive `audit()` over
# synthetic trees and prove it discriminates.

_DECLARING_ADVISORY = '''"""a gate.

ENFORCEMENT: advisory — nothing spawns it.
"""
'''
_DECLARING_BLOCKING = '''"""a gate.

ENFORCEMENT: blocking
"""
'''
_SILENT = '''"""a gate that says nothing."""
'''
_FLOW_DOC = textwrap.dedent("""\
    steps:
      - id: 1
        name: "synthetic"
        gate:
          all_of:
    {rows}
    """)

#: A runner that SPAWNS a gate and lets its exit status reach a control-flow
#: decision — the shape `audit()` classifies INLINE_BLOCKING.
_RUNNER = '''import subprocess, sys
from pathlib import Path
PROGRAMS_DIR = Path(__file__).resolve().parent


def step_thing(project):
    cp = subprocess.run([sys.executable,
                         str(PROGRAMS_DIR / "{gate}.py"), str(project)],
                        capture_output=True, text=True)
    if cp.returncode == 1:
        return "FAIL"
    return "PASS"
'''


def _tree(root: Path, gates: dict, wired: str = None):
    progs = root / "programs"
    progs.mkdir(parents=True, exist_ok=True)
    for name, body in gates.items():
        (progs / f"{name}.py").write_text(body)
    if wired:
        (progs / "design_one_shot_runner.py").write_text(
            _RUNNER.format(gate=wired))
    flow = root / "flow.yaml"
    flow.write_text(_FLOW_DOC.format(rows="\n".join(
        f'        - program_exit_zero: "{n} . --json out.json"' for n in gates)))
    return flow, progs


def test_the_control_it_fires_on_a_synthetic_gate_in_that_state(tmp_path):
    """THE GUARD. A gate declaring advisory that a runner spawns blocking must
    be reported — this is the whole class, built from nothing."""
    m = _mod()
    flow, progs = _tree(tmp_path / "t", {"wired_check": _DECLARING_ADVISORY},
                        wired="wired_check")
    rep = m.audit(flow, progs)
    assert [r["gate"] for r in rep["declared_weaker_than_wired"]] == [
        "wired_check"], rep


def test_the_control_it_does_not_fire_on_a_gate_nothing_spawns(tmp_path):
    """An advisory gate that is genuinely audit-only is the COMPLIANT state —
    the one #1035 spent a change reaching. Reporting it would punish exactly
    the gates that complied and make the disclosure noise."""
    m = _mod()
    flow, progs = _tree(tmp_path / "t", {"quiet_check": _DECLARING_ADVISORY})
    rep = m.audit(flow, progs)
    assert rep["declared_weaker_than_wired"] == [], rep


def test_the_control_it_does_not_fire_on_a_correctly_declared_blocking_gate(
        tmp_path):
    """Wired blocking AND declaring blocking is correct and must be silent."""
    m = _mod()
    flow, progs = _tree(tmp_path / "t", {"honest_check": _DECLARING_BLOCKING},
                        wired="honest_check")
    rep = m.audit(flow, progs)
    assert rep["declared_weaker_than_wired"] == [], rep


def test_the_control_it_does_not_fire_on_a_gate_that_declares_nothing(
        tmp_path):
    """Wired blocking and declaring NOTHING is a different class — it is
    silence, not a contradiction, and this census must not quietly absorb it or
    the two debts become one and neither is paid down properly."""
    m = _mod()
    flow, progs = _tree(tmp_path / "t", {"mute_check": _SILENT},
                        wired="mute_check")
    rep = m.audit(flow, progs)
    assert rep["declared_weaker_than_wired"] == [], rep


def test_the_control_the_census_never_changes_the_exit_code(tmp_path):
    """THE BOUND THIS CHANGE PROMISED. A tree whose ONLY finding is a member of
    this class must still exit 0, or the census has quietly become a gate and
    settled a dispute it was written not to settle."""
    m = _mod()
    flow, progs = _tree(tmp_path / "t", {"wired_check": _DECLARING_ADVISORY},
                        wired="wired_check")
    baseline = tmp_path / "b.json"
    baseline.write_text(json.dumps({"known": [], "undeclared_known": []}))
    rc = m.main(["--flow", str(flow), "--programs", str(progs),
                 "--baseline", str(baseline)])
    assert rc == 0, "the census must not affect the exit code"


def test_the_control_a_real_contradiction_still_fails(tmp_path):
    """And the direction that DOES fail must be untouched: declaring blocking
    while nothing spawns it is still an overclaim and still exits 1. Adding the
    census must not have softened the scan it sits beside."""
    m = _mod()
    flow, progs = _tree(tmp_path / "t", {"overclaiming_check": _DECLARING_BLOCKING})
    rep = m.audit(flow, progs)
    assert [c["gate"] for c in rep["contradictions"]] == ["overclaiming_check"]
    baseline = tmp_path / "b.json"
    baseline.write_text(json.dumps({"known": [], "undeclared_known": []}))
    assert m.main(["--flow", str(flow), "--programs", str(progs),
                   "--baseline", str(baseline)]) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-v"]))
