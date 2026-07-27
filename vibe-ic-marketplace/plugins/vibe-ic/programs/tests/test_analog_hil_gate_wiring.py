#!/usr/bin/env python3
"""The four HIL-discipline programs must stay WIRED into A9's flow gate.

`skills/analog-hw-tuning-loop/SKILL.md` names four programs as the enforcers of
its hardware-in-the-loop rules:

    step 5 of the loop  -> programs/analog_hil_three_way_verdict.py
    "Output format"     -> programs/analog_hil_report_schema_check.py
    "Do not exceed 3 hardware iterations" -> analog_hil_iteration_cap_check.py
    "Do not adjust more than 1 component" -> analog_hil_single_knob_check.py

All four existed, all four worked, and for their whole life that SKILL.md was
the ONLY file in the repo that mentioned any of them: they were absent from the
flow YAML, from `flow_compliance_check`'s gate lists, from every runner and from
CI. Every rule the loop documents was therefore enforced by prose alone — the
loop could iterate five times on the bench, turn three knobs at once, and emit a
report claiming `convergence_status: IDEAL` while `converged: false`, and no
program in the flow would say a word.

This file pins the wiring itself, so it cannot silently fall back out, and pins
that each wired program still FAILs the step through the new channel on a bad
input — a clause that cannot fail is decoration, not a gate.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as FCC  # noqa: E402

_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

# stem -> the artefact file whose contents it judges
HIL_PROGRAMS = {
    "analog_hil_report_schema_check": "hw_tuning_report.json",
    "analog_hil_iteration_cap_check": "hw_tuning_report.json",
    "analog_hil_single_knob_check": "hw_sizing_history.json",
    "analog_hil_three_way_verdict": "hw_tuning_report.json",
}


def _a9() -> dict:
    doc = yaml.safe_load(_FLOW.read_text())
    return next(s for s in doc["steps"] if str(s.get("id")) == "A9")


def _blocking_commands(gate) -> list[str]:
    """Every `program_exit_zero` command string in a gate, in gate order.

    Deliberately does NOT collect `optional_program_exit_zero` or
    `advisory_program_exit_zero`: neither can be relied on to fail the step
    (`optional` may never run, `advisory` never blocks), so counting them would
    let a downgrade pass this test.
    """
    found: list[str] = []

    def rec(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "program_exit_zero":
                    found.append(v["command"] if isinstance(v, dict) else str(v))
                elif k in ("optional_program_exit_zero",
                           "advisory_program_exit_zero"):
                    continue
                else:
                    rec(v)
        elif isinstance(node, list):
            for item in node:
                rec(item)

    rec(gate)
    return found


# ── the wiring itself ────────────────────────────────────────────────────────

@pytest.mark.parametrize("stem", sorted(HIL_PROGRAMS))
def test_hil_program_is_wired_into_a9_as_blocking(stem):
    """THE regression this file exists for. Each of the four must appear as a
    BLOCKING `program_exit_zero` clause of A9's gate."""
    cmds = _blocking_commands(_a9()["gate"])
    assert any(c.split()[0] == stem for c in cmds), (
        f"{stem} is no longer wired into A9's gate as program_exit_zero; "
        f"wired blocking commands are {[c.split()[0] for c in cmds]}")


@pytest.mark.parametrize("stem", sorted(HIL_PROGRAMS))
def test_wired_hil_program_exists_and_is_executable(stem):
    """A wired name that resolves to nothing is a gate that never runs."""
    assert (_PROGRAMS / f"{stem}.py").is_file()


def test_schema_check_is_ordered_before_the_iteration_cap():
    """Order is load-bearing, not cosmetic. `all_of` short-circuits on the first
    failing sub-gate, and on a MALFORMED hw_tuning_report.json the two programs
    disagree about severity: the schema check exits 1 (FAIL) while the cap check
    exits 2, which this harness reads as the disclosed-skip/VACUOUS tier. Running
    the schema check first is what makes a malformed report read as a failure."""
    cmds = [c.split()[0] for c in _blocking_commands(_a9()["gate"])]
    assert (cmds.index("analog_hil_report_schema_check")
            < cmds.index("analog_hil_iteration_cap_check")), cmds


def test_hil_clauses_are_unconditional():
    """They must NOT be gated on the presence of the artefact they judge.

    Each program already SKIPs at rc=0 when its input is absent, so a
    `condition_files_exist` would buy nothing and would re-introduce exactly the
    self-disabling shape `flow_condition_reachability_check` exists to make
    extinct (the condition is false in precisely the scenario the check is for).
    """
    gate = _a9()["gate"]
    conditioned = []

    def rec(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("optional_program_exit_zero",
                         "advisory_program_exit_zero"):
                    cmd = v.get("command", "") if isinstance(v, dict) else str(v)
                    if cmd.split() and cmd.split()[0] in HIL_PROGRAMS:
                        conditioned.append(cmd.split()[0])
                else:
                    rec(v)
        elif isinstance(node, list):
            for item in node:
                rec(item)

    rec(gate)
    assert conditioned == [], conditioned


# ── the wiring has teeth: FAIL propagates through the new channel ────────────

def _project(tmp_path: Path, *, hil: dict | None = None) -> Path:
    """A cosim-complete analog project that every PRE-EXISTING A9 sub-gate
    accepts, so any FAIL the tests below observe is attributable to the clause
    under test and nothing else.

    It deliberately ships NO hw_measurements.json: that file is the input of the
    two older sub-gates (`analog_hw_spice_correlation_check`,
    `analog_a9_hw_verify_check`), and a synthetic one makes the correlation gate
    fail first — `all_of` short-circuits, and the test would then be measuring
    the wrong clause. Without it those two are respectively skipped and rc=2
    (VACUOUS, a pass tier), which is the documented simulation-only close.

    `hil` maps a filename under phase3/analog/blk1/ to its JSON content.
    """
    (tmp_path / "phase1" / "analog").mkdir(parents=True)
    bdir = tmp_path / "phase3" / "analog" / "blk1"
    bdir.mkdir(parents=True)
    cosim = tmp_path / "phase3" / "mixed_signal" / "cosim"
    cosim.mkdir(parents=True)
    blocks = json.dumps({"blocks": [{"name": "blk1"}]})
    (tmp_path / "phase1" / "analog" / "analog_block_list.json").write_text(blocks)
    (tmp_path / "phase3" / "analog" / "analog_block_list.json").write_text(blocks)
    (cosim / "mixed_signal_results.json").write_text(json.dumps(
        {"scenarios": [{"name": "s1", "status": "PASS"},
                       {"name": "s2", "status": "PASS"}]}))
    (cosim / "blk1_cosim_results.json").write_text(
        json.dumps({"simulation_passed": True}))
    for name, payload in (hil or {}).items():
        (bdir / name).write_text(json.dumps(payload))
    return tmp_path


GOOD_REPORT = {
    "block_name": "blk1",
    "converged": True,
    "total_iterations": {"spice": 3, "hardware": 1},
    "final_comparison": {
        "vout_dc": {"spec": 1.80, "spice": 1.8002, "hw": 1.803,
                    "discrepancy_pct": 0.16},
    },
    "convergence_status": "IDEAL",
}
GOOD_HISTORY = {
    "block_name": "blk1",
    "iterations": [
        {"iter": 1, "sizing": {"M1": {"W": 4.0, "L": 0.5}, "Rfb": 50000}},
        {"iter": 2, "sizing": {"M1": {"W": 4.0, "L": 0.5}, "Rfb": 52000}},
    ],
}

# Each bad artefact violates exactly ONE of the four rules.
_SCHEMA_BAD = dict(GOOD_REPORT, converged=False)                 # IDEAL & !converged
_CAP_BAD = dict(GOOD_REPORT, total_iterations={"spice": 4, "hardware": 5})
_VERDICT_BAD = dict(GOOD_REPORT, final_comparison={
    "vout_dc": {"spec": 1.80, "spice": 1.8002, "hw": 2.2,
                "discrepancy_pct": 22.21}})                       # HW off spec
_KNOB_BAD = {
    "block_name": "blk1",
    "iterations": [
        {"iter": 1, "sizing": {"M1": {"W": 4.0, "L": 0.5}, "Rfb": 50000}},
        {"iter": 2, "sizing": {"M1": {"W": 6.0, "L": 0.6}, "Rfb": 52000}},
    ],
}


def test_a9_passes_on_a_clean_hil_close(tmp_path):
    """DIRECTION 1 — the gates must not fire on a well-formed converged loop."""
    p = _project(tmp_path, hil={"hw_tuning_report.json": GOOD_REPORT,
                                "hw_sizing_history.json": GOOD_HISTORY})
    r = FCC.check_step(p, _a9(), {}, None)
    assert r.status not in ("FAIL", "MISSING"), (r.status, r.reasons)


def test_a9_unaffected_when_there_is_no_bench_data(tmp_path):
    """DIRECTION 2 — the cost of the wiring on a bench-less run is zero.

    All four programs SKIP at rc=0 with no HIL artefacts, so a simulation-only
    analog close keeps whatever verdict it had before this wiring landed."""
    r = FCC.check_step(_project(tmp_path), _a9(), {}, None)
    assert r.status not in ("FAIL", "MISSING"), (r.status, r.reasons)


@pytest.mark.parametrize("stem,files", [
    ("analog_hil_report_schema_check",
     {"hw_tuning_report.json": _SCHEMA_BAD}),
    ("analog_hil_iteration_cap_check",
     {"hw_tuning_report.json": _CAP_BAD}),
    ("analog_hil_single_knob_check",
     {"hw_tuning_report.json": GOOD_REPORT,
      "hw_sizing_history.json": _KNOB_BAD}),
    ("analog_hil_three_way_verdict",
     {"hw_tuning_report.json": _VERDICT_BAD}),
])
def test_bad_hil_artefact_fails_a9_through_the_new_wiring(tmp_path, stem, files):
    """The point of wiring: a violation must now turn the STEP red, not merely
    be discoverable by running a program nobody runs."""
    p = _project(tmp_path, hil=files)
    r = FCC.check_step(p, _a9(), {}, None)
    assert r.status == "FAIL", (r.status, r.reasons)
    assert any(stem in reason for reason in r.reasons), (stem, r.reasons)


@pytest.mark.parametrize("stem,files", [
    ("analog_hil_report_schema_check",
     {"hw_tuning_report.json": _SCHEMA_BAD}),
    ("analog_hil_iteration_cap_check",
     {"hw_tuning_report.json": _CAP_BAD}),
    ("analog_hil_single_knob_check",
     {"hw_sizing_history.json": _KNOB_BAD}),
    ("analog_hil_three_way_verdict",
     {"hw_tuning_report.json": _VERDICT_BAD}),
])
def test_each_program_still_has_a_reachable_rc1(tmp_path, stem, files):
    """A gate wired as BLOCKING must have a FAIL path that actually executes."""
    p = _project(tmp_path, hil=files)
    r = subprocess.run([sys.executable, str(_PROGRAMS / f"{stem}.py"), str(p)],
                       capture_output=True, text=True)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "FAIL" in r.stdout, r.stdout
