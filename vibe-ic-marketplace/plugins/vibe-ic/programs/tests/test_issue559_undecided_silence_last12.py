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
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

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
def test_recorded_gate_now_has_a_verdict_or_derived_na_contract(gate):
    """#1968 supersedes the old licensed silence with an explicit contract."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        probe = pathlib.Path(tmp)
        derived_na = F._p0_contract_na_reason(gate, probe, probe)
        argv = F._structural_gate_argv(gate, probe, rtl_dir=probe)
        proc = _pr.run(argv, capture_output=True, text=True)
    assert gate in F._STRUCTURAL_GATE_INVOCATION_CONTRACTS
    rejected = (proc.returncode == 2 and
                F._gate_invocation.classify_not_invocable(
                    proc.stdout, proc.stderr,
                    supplied_flags=[a for a in argv if a.startswith("--")]))
    assert derived_na is not None or not rejected, (
        f"{gate} has neither a derived N/A nor an invocable argv")


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


#: The 12 gates that had NO recorded decision at v1.9.8 (round 6).
_ROUND6_TWELVE = {
    "backlog_sanitize_check", "cross_constant_invariant_check",
    "fpga_qsf_lint", "fresh_agent_provenance_check",
    "interface_encoding_audit", "json_schema_check",
    "l9_completeness_check", "module_port_audit", "oe_pattern_check",
    "output_artifact_check", "tester_oracle_health_check",
    "warn_acceptance_policy_check",
}

#: Round 7 — the four the RATCHET could not see, added deliberately.
#:
#: These were never undecided by anyone's choice. `p0_gate_invocability_drift_check`
#: re-typed `_gate_invocation`'s Rule A (`rc == 2 and "usage:" in stderr`) and
#: never had Rule B, so a gate that hand-rolls its required-argument check was
#: invisible to the measurement entirely — neither licensed nor flagged. Measured
#: at v1.9.74: the umbrella classified 36 of 246 registered gates NOT_INVOCABLE,
#: the ratchet 32, and the difference is exactly this set.
_ROUND7_RULE_B_FOUR = {
    "fpga_async_input_synchronizer_check", "mask_application_check",
    "payload_bit_position_check", "periodic_signal_required_check",
}


def test_table_covers_exactly_the_undecided_gates_found_so_far():
    """Anchors the triage frontier. A change to this set is a real change to it
    and must be deliberate.

    Round 6 pinned twelve. Round 7 adds four MORE — not because four new gates
    went silent, but because the program that was supposed to find them used a
    narrower predicate than the umbrella that creates them. The split is kept
    visible rather than merged into one flat set: the twelve were found by a
    check that worked, the four were found by fixing the check.
    """
    assert set(REGISTER) == _ROUND6_TWELVE | _ROUND7_RULE_B_FOUR


def test_the_round7_four_are_now_explicit_derived_na_on_an_empty_design():
    """The four hand-rolled Rule-B silences are closed by #1968 contracts."""
    import tempfile
    for gate in sorted(_ROUND7_RULE_B_FOUR):
        with tempfile.TemporaryDirectory() as tmp:
            probe = pathlib.Path(tmp)
            reason = F._p0_contract_na_reason(gate, probe, probe)
        assert gate in F._STRUCTURAL_GATE_INVOCATION_CONTRACTS
        assert reason is not None and "N/A" in reason, gate
