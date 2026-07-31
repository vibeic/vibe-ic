"""#559 — gates registered in the per-project umbrella that do not take a project.

`_NOT_A_PROJECT_GATE` records four of them: three examine this plugin's own
source, one drives a bench oscilloscope.  Two are marked READY and wired into
`tools/ci/repo_hygiene_gates.sh`; the other two are recorded with the
measurement that says why they are not.

The assertions below re-derive the parts that can go stale.  In particular a
READY disposition is checked against the shell script, not against itself: a
register that says "wired" while nothing runs the gate is the same silence one
level up, wearing a record as a disguise.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_HYGIENE = (_PROGRAMS.parents[3] / "tools" / "ci" / "repo_hygiene_gates.sh")


def _load_flow():
    spec = importlib.util.spec_from_file_location(
        "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["flow_compliance_check"] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load_flow()
REGISTER = F._NOT_A_PROJECT_GATE
READY = sorted(g for g, e in REGISTER.items()
               if e["disposition"].startswith("READY"))
NOT_READY = sorted(set(REGISTER) - set(READY))


def test_register_is_not_empty():
    assert REGISTER, "_NOT_A_PROJECT_GATE is empty"


def test_hygiene_script_exists():
    """Anchors the path the wiring assertions depend on.

    Without this, a moved script would make every 'is it wired' test below fail
    for the wrong reason, or — if they were written with a soft skip — pass
    while checking nothing.
    """
    assert _HYGIENE.is_file(), f"{_HYGIENE} not found"


@pytest.mark.parametrize("gate", sorted(REGISTER))
def test_gate_is_still_registered_in_the_project_umbrella(gate):
    """Recorded, not de-registered — the record describes a live registration."""
    assert gate in F._STRUCTURAL_RTL_GATES, (
        f"{gate} is recorded here but no longer registered; the entry now "
        f"explains a state that does not exist")


@pytest.mark.parametrize("gate", sorted(REGISTER))
def test_gate_does_not_accept_a_project_positional(gate):
    """The premise of the whole register, re-derived by execution.

    If one of these ever learns to take a project it belongs back in the
    ordinary triage, not here.
    """
    proc = subprocess.run(
        [sys.executable, str(_PROGRAMS / f"{gate}.py"), "/tmp"],
        capture_output=True, text=True, timeout=45)
    assert proc.returncode == 2 and "usage:" in (proc.stderr or ""), (
        f"{gate} accepted a project positional (rc={proc.returncode}); it is "
        f"no longer 'not a project gate'")


@pytest.mark.parametrize("gate", READY)
def test_ready_gates_are_actually_wired(gate):
    """A READY disposition must correspond to a line that runs the gate."""
    text = _HYGIENE.read_text(encoding="utf-8")
    needle = f"programs/{gate}.py"
    assert needle in text, (
        f"{gate} is recorded READY but {_HYGIENE.name} never invokes it; the "
        f"record claims a wiring that does not exist")


@pytest.mark.parametrize("gate", READY)
def test_ready_gates_pass_from_the_plugin_directory(gate):
    """Wired gates must be green, or every landing breaks on the next push."""
    proc = subprocess.run(
        [sys.executable, str(_PROGRAMS / f"{gate}.py")],
        cwd=str(_PROGRAMS.parent), capture_output=True, text=True, timeout=45)
    assert proc.returncode == 0, (
        f"{gate} is wired into the landing ladder and exits "
        f"{proc.returncode}:\n{(proc.stdout + proc.stderr)[:600]}")


@pytest.mark.parametrize("gate", NOT_READY)
def test_not_ready_gates_are_not_wired(gate):
    """The negative half.

    Without it, every gate could be wired and the READY tests would still pass,
    so the distinction the register draws would be unenforced.
    """
    text = _HYGIENE.read_text(encoding="utf-8")
    invocations = [ln for ln in text.splitlines()
                   if f"programs/{gate}.py" in ln and ln.lstrip().startswith("run ")]
    assert not invocations, (
        f"{gate} is recorded NOT READY but {_HYGIENE.name} runs it: "
        f"{invocations}")


@pytest.mark.parametrize("gate", sorted(REGISTER))
def test_entry_states_scope_measurement_and_disposition(gate):
    entry = REGISTER[gate]
    assert entry.get("scope") in ("plugin-self-check", "hardware-instrument"), (
        f"{gate}: unknown scope {entry.get('scope')!r}")
    for field in ("measured", "disposition"):
        assert entry.get(field, "").strip(), f"{gate}: {field} is empty"
    assert len(entry["measured"]) > 60, (
        f"{gate}: `measured` is too short to carry a measurement")


def test_register_gates_are_counted_as_licensed():
    spec = importlib.util.spec_from_file_location(
        "p0_gate_invocability_drift_check",
        _PROGRAMS / "p0_gate_invocability_drift_check.py")
    drift = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drift)
    missing = sorted(set(REGISTER) - drift._licensed_gates())
    assert not missing, (
        f"recorded here but still counted undecided: {missing}")
