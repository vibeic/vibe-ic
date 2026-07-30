"""#559 — the four gates no generic umbrella can drive.

`_SEMANTIC_ARGV_UNDRIVABLE` records a DECISION, and a decision that nothing
re-derives decays into an assertion nobody can check.  These tests re-derive it:
each named gate is executed and its own argparse output is read, so the register
cannot outlive the condition it describes.

The failure this guards against is specific.  If one of these four ever gains a
default for its design-specific argument, it stops rejecting the umbrella argv —
and it would then be silently LICENSED by a table that still says it cannot be
driven, which is the register outliving its truth.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load_flow():
    spec = importlib.util.spec_from_file_location(
        "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["flow_compliance_check"] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load_flow()
REGISTER = F._SEMANTIC_ARGV_UNDRIVABLE


def test_register_is_not_empty():
    """An empty register would pass every other test in this file."""
    assert REGISTER, "_SEMANTIC_ARGV_UNDRIVABLE is empty"


@pytest.mark.parametrize("gate", sorted(REGISTER))
def test_gate_is_registered_as_structural(gate):
    """Recorded, not de-registered.

    Dropping these from `_STRUCTURAL_RTL_GATES` would shrink the denominator and
    remove the evidence that the check exists — the same disappearance the
    register exists to prevent, by a tidier route.
    """
    assert gate in F._STRUCTURAL_RTL_GATES, (
        f"{gate} is recorded as undrivable but no longer registered; "
        f"the record now describes a gate the umbrella never counts")


@pytest.mark.parametrize("gate", sorted(REGISTER))
def test_gate_still_rejects_the_umbrella_argv(gate):
    """Re-derived by execution, because the claim is about runtime behaviour.

    argparse rejection is `rc == 2` AND `usage:` on stderr. `rc == 2` alone is
    not the discriminator: plenty of programs exit 2 for their own reasons, and
    reading the bare code would license gates that failed for something else.
    """
    path = _PROGRAMS / f"{gate}.py"
    assert path.exists(), f"{path} does not exist"
    proc = subprocess.run(
        [sys.executable, str(path), "--rtl-dir", "/tmp"],
        capture_output=True, text=True,
        # 30s, not the 120s this started at: an inner bound that can
        # outlive the 180s harness kills the SESSION instead of failing the
        # test. Measured cost of these four rejections is 0.03-0.04s, so
        # 30s is still three orders of magnitude of headroom.
        timeout=30)
    assert proc.returncode == 2 and "usage:" in (proc.stderr or ""), (
        f"{gate} no longer rejects the umbrella's argv "
        f"(rc={proc.returncode}); if it gained a default for its "
        f"design-specific argument it must leave this register, or it will be "
        f"licensed as undrivable while silently running on that default")


@pytest.mark.parametrize("gate", sorted(REGISTER))
def test_recorded_required_flags_match_what_argparse_asks_for(gate):
    """`requires` is checked against the program, not trusted as prose."""
    proc = subprocess.run(
        [sys.executable, str(_PROGRAMS / f"{gate}.py"), "--rtl-dir", "/tmp"],
        capture_output=True, text=True,
        # 30s, not the 120s this started at: an inner bound that can
        # outlive the 180s harness kills the SESSION instead of failing the
        # test. Measured cost of these four rejections is 0.03-0.04s, so
        # 30s is still three orders of magnitude of headroom.
        timeout=30)
    stderr = proc.stderr or ""
    for flag in REGISTER[gate]["requires"].split():
        assert flag in stderr, (
            f"{gate}: register says it requires {flag}, but its own argparse "
            f"error does not mention it — the record has drifted from the CLI")


@pytest.mark.parametrize("gate", sorted(REGISTER))
def test_design_value_is_a_subset_of_requires(gate):
    """The design-specific flags must be among the required ones.

    Without this, `design_value` could name a flag the gate does not take and
    the justification would describe a different program.
    """
    entry = REGISTER[gate]
    required = set(entry["requires"].split())
    for flag in (f.strip() for f in entry["design_value"].split(",")):
        assert flag in required, (
            f"{gate}: design_value names {flag}, which is not in requires "
            f"({sorted(required)})")


@pytest.mark.parametrize("gate", sorted(REGISTER))
def test_entry_states_a_reason_and_a_disposition(gate):
    entry = REGISTER[gate]
    for field in ("why_no_umbrella", "disposition"):
        assert entry.get(field, "").strip(), f"{gate}: {field} is empty"
    assert len(entry["why_no_umbrella"]) > 80, (
        f"{gate}: why_no_umbrella is too short to be a reason; a register whose "
        f"justifications are one-liners is a list of names")


def test_register_gates_are_counted_as_licensed():
    """The whole point: these four must move out of the undecided pile.

    Verified through the drift check's own union rather than by re-implementing
    it, so a change to how licensing is computed is caught here.
    """
    spec = importlib.util.spec_from_file_location(
        "p0_gate_invocability_drift_check",
        _PROGRAMS / "p0_gate_invocability_drift_check.py")
    drift = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drift)
    licensed = drift._licensed_gates()
    missing = sorted(set(REGISTER) - licensed)
    assert not missing, (
        f"recorded as undrivable but still counted undecided: {missing}")
