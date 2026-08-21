#!/usr/bin/env python3
"""The loop, driven end to end by REAL shipped programs over a REAL deck.

NOTHING IS SIMULATED IN THIS FILE
=================================
The actuator is `programs/openroad_hold_repair_tcl_gen.py` — a shipped program
with hard guardrails (`-allow_setup_violations false` always,
`-max_buffer_percent` capped at 5%). The measurement is
`programs/pnr_timing_repair_completeness_check.py` — a shipped program that
audits an OpenROAD P&R deck for the mandatory repair sequence and exits 0/1/2.
The registry is the SHIPPED `config/ppa_actuator_registry.yaml`. The deck is a
real Tcl file on disk. Every invocation is a real `subprocess.run` over a real
argv with no shell.

AND THE LOOP DOES NOT REPAIR ANYTHING, WHICH IS THE POINT
=========================================================
`openroad_hold_repair_tcl_gen --out` REPLACES its target. The hold-repair block
is an AMENDMENT to an existing deck, so replacing the deck destroys the
`set_wire_rc` / `repair_design` / `repair_timing -setup` chain that must sit
above it — the exact silicon-DOA shape the measurement exists to catch. Writing
to a separate include file does not help either: the checker audits each script
SEPARATELY and takes the worst verdict, so the include, judged alone, IS the
hold-only anti-pattern.

So the honest terminal state on today's tree is HANDOFF_REQUIRED or PLATEAU with
the residual violation VISIBLE, and this file asserts exactly that. It is the
anti-pretend proof: it goes RED the day the controller reports a repair it did
not achieve, and it goes red in a different way the day someone gives
`openroad_hold_repair_tcl_gen` an append mode without re-examining this loop.

An earlier revision of `_ppa/closure.py` PROMOTED on the first iteration here —
the objective (`missing_expected_commands`) really did fall 2 -> 1 while
`missing_required_commands` went 0 -> 3, because only the objective domain was
measured at baseline and a domain with no baseline has nothing to regress from.
`test_the_collateral_guard_fires_on_the_first_iteration` is that regression,
pinned.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import closure  # noqa: E402

PLUGIN = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = PLUGIN / "config" / "ppa_actuator_registry.yaml"
CONTROLLER = "pnr.deck.hold_block_emission"

#: A real P&R deck carrying the three MANDATORY repair commands and missing both
#: EXPECTED ones. That is the baseline violation: `missing_expected` = 2.
DECK_WITH_SETUP_CHAIN = """\
# P&R deck
read_def in.def
place_design
set_wire_rc -layer met3
repair_design
repair_timing -setup
detailed_route
report_design_area
"""


@pytest.fixture()
def impl(tmp_path):
    root = tmp_path / "impl"
    root.mkdir()
    (root / "pnr.tcl").write_text(DECK_WITH_SETUP_CHAIN, encoding="utf-8")
    return root


@pytest.fixture()
def controller(impl, tmp_path):
    reg = closure.load_registry(REGISTRY)
    return reg, closure.ClosureController(reg, impl, tmp_path / "work")


def test_the_two_bound_programs_really_are_in_the_tree():
    """Without this, everything below could be passing because nothing ran."""
    reg = closure.load_registry(REGISTRY)
    act = reg.actuators[reg.controllers[CONTROLLER].actuator_id]
    assert act.binding is closure.Binding.EXECUTABLE
    assert act.program_path().is_file(), act.program_path()
    for name in ("pnr.repair_deck.expected_completeness",
                 "pnr.repair_deck.required_completeness"):
        dom = reg.domains[name]
        assert dom.binding is closure.Binding.EXECUTABLE
        assert dom.program_path().is_file(), dom.program_path()


def test_the_baseline_violation_is_really_measured(controller):
    reg, ctl = controller
    m = ctl.measure(reg.domains["pnr.repair_deck.expected_completeness"], "t")
    assert m.usable() and m.value == 2, m.reason
    assert m.status == "DERIVED" and m.formula, (
        "a computed number is DERIVED and carries its formula")
    assert m.rc == 0, "WARN is rc=0 from this checker and it is still a measurement"
    n = ctl.measure(reg.domains["pnr.repair_deck.required_completeness"], "t")
    assert n.usable() and n.value == 0


def test_the_actuator_really_changes_the_deck(controller, impl):
    """Proved by the tree digest, not by the actuator's own exit code."""
    reg, ctl = controller
    act = reg.actuators["pnr.deck.emit_hold_repair_block"]
    before = closure.tree_digest(impl)
    params = act.bind_params({"margin_ps": 0, "max_buffer_percent": 5,
                              "out_path": "pnr.tcl"})
    import subprocess
    rc = subprocess.run(act.build_argv(impl, params), capture_output=True).returncode
    assert rc == 0
    assert closure.tree_digest(impl) != before
    assert "repair_timing -hold" in (impl / "pnr.tcl").read_text(encoding="utf-8")


def test_the_collateral_guard_fires_on_the_first_iteration(controller, impl):
    """The pinned regression. The action improves the objective 2 -> 1 AND takes
    `missing_required` 0 -> 3. It must roll back, not promote."""
    reg, ctl = controller
    before_bytes = (impl / "pnr.tcl").read_text(encoding="utf-8")
    run = ctl.run_controller(CONTROLLER)

    assert run.iterations, "the loop must actually have run an iteration"
    first = run.iterations[0]
    assert first.actuator_rc == 0, "the actuator itself succeeded"
    assert first.changed_implementation, "and it really changed the deck"
    assert first.decision == "ROLLED_BACK", first.decision_reason
    assert "collateral regression" in first.decision_reason
    assert "missing_required_commands: 0.0 -> 3.0" in first.decision_reason
    assert first.digest_restored == first.digest_before
    assert (impl / "pnr.tcl").read_text(encoding="utf-8") == before_bytes, (
        "the deck is restored BYTE FOR BYTE; the setup-repair chain survives")


def test_the_real_loop_never_claims_a_repair_it_did_not_achieve(controller, impl):
    reg, ctl = controller
    run = ctl.run_controller(CONTROLLER)

    assert run.outcome in (closure.Outcome.PLATEAU,
                           closure.Outcome.HANDOFF_REQUIRED,
                           closure.Outcome.BUDGET_EXHAUSTED), run.outcome
    assert run.is_closed_loop_success() is False
    assert run.exit_code() == 1, (
        "the loop really ran and really left a violation: that is a finding "
        "about the design, so it is 1")
    assert run.promoted == 0
    assert run.rolled_back >= 1
    assert run.residual is not None
    assert run.residual["visible"] is True
    assert run.residual["satisfied"] is False
    assert run.residual["value"] == 2, (
        "the residual is reported with its NUMBER — the deck is still missing "
        "both expected commands, exactly as it was at baseline")
    assert "set_wire_rc" in (impl / "pnr.tcl").read_text(encoding="utf-8"), (
        "and the mandatory chain the loop failed to preserve was preserved")


def test_the_record_carries_the_real_argv_and_the_registry_it_acted_under(controller):
    reg, ctl = controller
    rec = ctl.run_controller(CONTROLLER).to_record()
    assert rec["registry_digest"] == reg.digest()
    argv = rec["iterations"][0]["argv"]
    assert argv[0] == sys.executable
    assert argv[1].endswith("openroad_hold_repair_tcl_gen.py")
    assert "--max-buffer-percent" in argv
    assert all(isinstance(a, str) for a in argv), "an argv list, never a string"


def test_both_domains_are_baselined_and_both_are_reported(controller):
    """The fix for the promote-over-a-destroyed-chain defect, asserted on the
    record: a domain with no baseline cannot be shown to have regressed."""
    reg, ctl = controller
    rec = ctl.run_controller(CONTROLLER).to_record()
    assert set(rec["baseline_all"]) == {
        "pnr.repair_deck.expected_completeness",
        "pnr.repair_deck.required_completeness"}
    assert set(rec["final_all"]) == set(rec["baseline_all"])
    assert rec["baseline_all"]["pnr.repair_deck.required_completeness"]["value"] == 0
    assert rec["final_all"]["pnr.repair_deck.required_completeness"]["value"] == 0


def test_an_actuator_whose_precondition_fails_hands_off_and_writes_nothing(tmp_path):
    """The deck is ABSENT. The action amends a deck, so this is not the action
    to take — and the controller must not quietly create a file nobody asked
    for. Note the deck is absent, not empty: those are different, and the
    controller reports them differently."""
    root = tmp_path / "impl"
    root.mkdir()
    (root / "placeholder.tcl").write_text("place_design\nrepair_timing -setup\n"
                                          "set_wire_rc\nrepair_design\n",
                                          encoding="utf-8")
    reg = closure.load_registry(REGISTRY)
    run = closure.ClosureController(reg, root, tmp_path / "w").run_controller(CONTROLLER)
    assert run.outcome is closure.Outcome.HANDOFF_REQUIRED
    assert "file_exists(pnr.tcl)" in run.reason
    assert not (root / "pnr.tcl").exists(), (
        "a controller that cannot act must not act anyway")
    assert run.iterations[0].actuator_rc is None
    assert run.exit_code() == 1


def test_an_implementation_root_with_no_deck_at_all_is_not_measured(tmp_path):
    """VACUOUS. The measurement is invoked over nothing, refuses, and the
    controller repeats the refusal instead of laundering it into a number."""
    root = tmp_path / "impl"
    root.mkdir()
    reg = closure.load_registry(REGISTRY)
    run = closure.ClosureController(reg, root, tmp_path / "w").run_controller(CONTROLLER)
    assert run.outcome is closure.Outcome.NOT_MEASURED
    assert run.exit_code() == 2, "not 0 and not 1"
    assert run.outcome.marker() == "[CANNOT CHECK]"
    assert run.iterations == []
    assert "value" not in run.baseline
    assert run.baseline["status"] == "NOT_MEASURED"


def test_a_deck_that_is_already_complete_does_not_trigger(tmp_path):
    """POSITIVE control for the trigger: green because there was nothing wrong,
    and the record says so rather than claiming a repair."""
    root = tmp_path / "impl"
    root.mkdir()
    (root / "pnr.tcl").write_text(
        "set_wire_rc -layer met3\nestimate_parasitics -placement\n"
        "repair_design\nrepair_timing -setup\nrepair_timing -hold\n",
        encoding="utf-8")
    reg = closure.load_registry(REGISTRY)
    run = closure.ClosureController(reg, root, tmp_path / "w").run_controller(CONTROLLER)
    assert run.outcome is closure.Outcome.NOT_TRIGGERED, run.reason
    assert run.exit_code() == 0
    assert run.is_closed_loop_success()
    assert run.iterations == []
    assert run.promoted == 0, "nothing was repaired, and nothing claims to be"


def test_this_controller_is_bound_to_no_flow_edge_on_purpose():
    """It repairs a DECK, not hold TIMING. Binding it to edge 20 would be the
    overclaim this whole lane exists to prevent, so the binding is asserted
    ABSENT and a future author has to change this test to add it."""
    reg = closure.load_registry(REGISTRY)
    assert CONTROLLER in reg.controllers
    assert CONTROLLER not in set(reg.edges.values())
    assert reg.edges["20"] is None
