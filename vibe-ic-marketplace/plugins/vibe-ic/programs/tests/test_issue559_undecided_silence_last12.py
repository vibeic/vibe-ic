"""#559 (round 6) — the last 12 undecided silences, measured and recorded.

`_UNDRIVABLE_BY_STRUCTURAL_UMBRELLA` records a DECISION for each of the 12 gates
that, at v1.9.8, rejected the P0 umbrella's argv with NO recorded disposition
anywhere (`p0_gate_invocability_drift_check` reported them as `undecided_silence`).
A decision that nothing re-derives decays into an assertion nobody can check, so
these tests re-derive it:

  * each named gate is still REGISTERED in the P0 umbrella (de-registering it
    would shrink the denominator and delete the evidence the check exists);
  * each named gate actually REJECTS the umbrella's own argv (measured live from
    its argparse output — the record cannot outlive the condition it describes);
  * each record is SUBSTANTIVE (a real measurement, not a rubber stamp);
  * the table drives `undecided_silence` to EMPTY, which is what lets the drift
    check turn undecided silence into a HARD ERROR instead of a report.

BIDIRECTIONAL NEGATIVE CONTROL (flow-change-acceptance): a gate that gains a
default for its missing argument stops rejecting the umbrella argv — it would
then be silently LICENSED by a table that still says it cannot be driven. The
`test_recorded_gate_still_rejects_the_umbrella_argv` case fails in exactly that
situation, so the register cannot outlive its truth.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load("flow_compliance_check", "flow_compliance_check.py")
D = _load("p0_gate_invocability_drift_check", "p0_gate_invocability_drift_check.py")
REGISTER = F._UNDRIVABLE_BY_STRUCTURAL_UMBRELLA

_VALID_CATEGORIES = {
    "reddens-corpus", "zero-decidable-denom", "cross-layer-contract",
    "semantic-design-value", "later-flow-artifact", "post-gate-policy",
    "utility-caller-supplied", "plugin-governance",
}


def test_register_is_not_empty():
    """An empty register would pass every other test in this file."""
    assert REGISTER, "_UNDRIVABLE_BY_STRUCTURAL_UMBRELLA is empty"


@pytest.mark.parametrize("gate", sorted(REGISTER))
def test_gate_is_registered_as_structural(gate):
    """Recorded, not de-registered — keep the gate counted in the denominator."""
    assert gate in F._STRUCTURAL_RTL_GATES, (
        f"{gate} is recorded as undrivable but no longer registered in "
        f"_STRUCTURAL_RTL_GATES; the record now describes a gate the umbrella "
        f"never counts")


@pytest.mark.parametrize("gate", sorted(REGISTER))
def test_recorded_gate_still_rejects_the_umbrella_argv(gate):
    """The measurement, re-derived live. The argv comes from the umbrella's own
    builder, so a gate that rejects it here rejects it in production too. If a
    gate stops rejecting (gains a default), this fails rather than silently
    licensing a now-drivable gate under a 'cannot be driven' record."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        probe = pathlib.Path(tmp)
        argv = F._structural_gate_argv(gate, probe, rtl_dir=probe)
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    # A gate that rejects the umbrella argv exits 2 with argparse's usage block,
    # OR hand-rolls the same complaint (Rule B in _gate_invocation). Either way
    # it did NOT run and did NOT return a 0/1 verdict about the probe.
    assert proc.returncode == 2, (
        f"{gate} exited {proc.returncode} on the umbrella argv — it no longer "
        f"rejects it, so this 'undrivable' record is stale. Re-measure and move "
        f"it to a wiring adapter or the right licensed table.\n"
        f"stderr:\n{proc.stderr[-600:]}")


@pytest.mark.parametrize("gate", sorted(REGISTER))
def test_record_is_substantive(gate):
    """A verdict with no measurement behind it is the rubber stamp #559 exists
    to prevent."""
    entry = REGISTER[gate]
    assert set(entry) >= {"category", "requires", "measured", "disposition"}, (
        f"{gate}: record is missing a field: {sorted(entry)}")
    assert entry["category"] in _VALID_CATEGORIES, (
        f"{gate}: category {entry['category']!r} not one of {_VALID_CATEGORIES}")
    assert len(entry["measured"]) > 120, (
        f"{gate}: `measured` must state the corpus measurement, not gesture at "
        f"it: {entry['measured']!r}")
    assert len(entry["disposition"]) > 40, (
        f"{gate}: `disposition` too thin: {entry['disposition']!r}")


def test_every_recorded_gate_is_now_licensed():
    """The whole point: the drift check's licensed set includes every gate here,
    so none of them reads as an undecided silence any longer."""
    licensed = D._licensed_gates()
    missing = sorted(set(REGISTER) - licensed)
    assert not missing, (
        f"recorded as undrivable but not in drift._licensed_gates(): {missing} "
        f"— the drift check would still count these as undecided silence")


def test_table_covers_exactly_the_v198_undecided_twelve():
    """Anchors the round-6 scope. These are the 12 gates that had NO recorded
    decision at v1.9.8. A change to this set is a real change to the triage
    frontier and must be deliberate."""
    assert set(REGISTER) == {
        "backlog_sanitize_check", "cross_constant_invariant_check",
        "fpga_qsf_lint", "fresh_agent_provenance_check",
        "interface_encoding_audit", "json_schema_check",
        "l9_completeness_check", "module_port_audit", "oe_pattern_check",
        "output_artifact_check", "tester_oracle_health_check",
        "warn_acceptance_policy_check",
    }
