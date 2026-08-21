#!/usr/bin/env python3
"""A step named for hardware verification must not report a bare PASS with none.

Step A9 was named "Co-Simulation / HW Verification" and, on a run carrying cosim
results and ZERO hw_measurements.json, `check_step` returned status PASS with an
empty reasons list — byte-identical in the report to a bench-verified close.

Not MANDATING bench hardware is a deliberate documented decision: the A9 entry in
`flow_condition_reachability_check`'s allowlist calls the exemption "the analog
analogue of --skip-hardware", and requiring a lab measurement would make headless
and CI analog runs permanently unpassable. So the fix is disclosure, not a
mandate — simulation-only closure stays legal, it just stops being silent.

Three things were wrong, and each is pinned below:

 1. The --skip-hardware analogy was never implemented. That routing is guarded by
    `isinstance(sid, int)` and A9's id is the string "A9", so the flag silently
    did nothing for it: step 6 disclosed as WAIVED with review_required while A9
    — the step that actually needs a bench — disclosed nothing.

 2. `analog_a9_hw_verify_check` already judged hw_measurements.json correctly and
    already had exactly the three tiers this needs, but was wired only into
    analog_one_shot_runner, never into A9's flow gate, so the flow verdict could
    not see it.

 3. The REQUIRED `program_exit_zero` branch did not read the stdout `VACUOUS_PASS:`
    disclosure that the OPTIONAL branch has always read. The shared analog helper
    `_analog_a_check_common.vacuous_pass()` discloses that way while exiting 0, so
    the same program disclosed a skip through an optional slot and was read as a
    bare PASS through a required one. That is general, not A9-specific.
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
_CHECKER = _PROGRAMS / "analog_a9_hw_verify_check.py"


def _a9() -> dict:
    doc = yaml.safe_load(_FLOW.read_text())
    return next(s for s in doc["steps"] if str(s.get("id")) == "A9")


def _project(tmp_path: Path, hw: dict | None) -> Path:
    """A cosim-complete analog project; `hw` None == no bench measurement."""
    (tmp_path / "phase1" / "analog").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "blk1").mkdir(parents=True)
    (tmp_path / "phase3" / "mixed_signal" / "cosim").mkdir(parents=True)
    blocks = json.dumps({"blocks": [{"name": "blk1"}]})
    (tmp_path / "phase1" / "analog" / "analog_block_list.json").write_text(blocks)
    (tmp_path / "phase3" / "analog" / "analog_block_list.json").write_text(blocks)
    cosim = tmp_path / "phase3" / "mixed_signal" / "cosim"
    (cosim / "mixed_signal_results.json").write_text(json.dumps(
        {"scenarios": [{"name": "s1", "status": "PASS"},
                       {"name": "s2", "status": "PASS"}]}))
    (cosim / "blk1_cosim_results.json").write_text(
        json.dumps({"simulation_passed": True}))
    if hw is not None:
        (tmp_path / "phase3" / "analog" / "blk1"
         / "hw_measurements.json").write_text(json.dumps(hw))
    return tmp_path


# ── the defect ───────────────────────────────────────────────────────────────

def test_simulation_only_close_is_not_a_bare_pass(tmp_path):
    """THE defect. Cosim green, no bench measurement anywhere -> the step must
    disclose. Before the fix this was status PASS with reasons == []."""
    p = _project(tmp_path, hw=None)
    assert not list(p.rglob("hw_measurements.json"))
    r = FCC.check_step(p, _a9(), {}, None)
    assert r.status != "PASS", (r.status, r.reasons)
    assert r.status == "VACUOUS_PASS", (r.status, r.reasons)
    assert any("VACUOUS" in x or "vacuous" in x for x in r.reasons), r.reasons


def test_simulation_only_close_is_still_legal(tmp_path):
    """DIRECTION 1, and the whole point of choosing disclosure over a mandate: a
    headless/CI analog run must still be able to close. VACUOUS_PASS is a
    pass-tier verdict — this must NOT become FAIL or MISSING."""
    r = FCC.check_step(_project(tmp_path, hw=None), _a9(), {}, None)
    assert r.status not in ("FAIL", "MISSING"), (r.status, r.reasons)


# ── the checker's own three tiers ────────────────────────────────────────────

def _run_checker(project: Path) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(_CHECKER), str(project)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


@pytest.mark.parametrize("hw,rc,token", [
    (None, 0, "VACUOUS_PASS"),                        # never measured
    ({"measurements": {}}, 1, "FAIL"),                # measured, no numbers
    ({"measurements": {"gain_db": 42.1}}, 0, "PASS"),  # really measured
])
def test_checker_tiers(tmp_path, hw, rc, token):
    """The tiers the gate depends on. A checker that could not FAIL would make
    the wiring decorative."""
    got_rc, out = _run_checker(_project(tmp_path, hw=hw))
    assert got_rc == rc, (got_rc, out[:300])
    assert token in out, out[:300]


# ── the general defect: a required gate must read the same disclosure ────────

def test_required_slot_reads_the_stdout_vacuous_disclosure(tmp_path):
    """The optional slot has always honoured a printed `VACUOUS_PASS:` at rc=0;
    the required slot ignored it. Same program, same disclosure, two answers."""
    gate = {"program_exit_zero":
            f"{_CHECKER.name[:-3]} . --json reports/gates/a9.json"}
    passed, reasons = FCC._evaluate_gate(_project(tmp_path, hw=None), gate)
    assert passed is True, reasons
    assert any(x.startswith(FCC._VACUOUS_HINT_PREFIX) for x in reasons), reasons


def test_required_slot_does_not_invent_a_vacuous_signal(tmp_path):
    """DIRECTION 1: a genuinely clean PASS must stay a clean PASS — the stdout
    fallback must key on the disclosure token, not on rc=0."""
    gate = {"program_exit_zero":
            f"{_CHECKER.name[:-3]} . --json reports/gates/a9.json"}
    p = _project(tmp_path, hw={"measurements": {"gain_db": 42.1}})
    passed, reasons = FCC._evaluate_gate(p, gate)
    assert passed is True, reasons
    assert not any(x.startswith(FCC._VACUOUS_HINT_PREFIX) for x in reasons), reasons


# ── the wiring and the naming, pinned ────────────────────────────────────────

def test_a9_gate_actually_runs_the_hw_verify_checker():
    txt = yaml.safe_dump(_a9())
    assert "analog_a9_hw_verify_check" in txt, (
        "A9's gate no longer runs the checker that judges hw_measurements.json "
        "— the flow verdict cannot see bench evidence without it")


def test_a9_name_does_not_claim_verification_it_never_enforces():
    name = _a9()["name"]
    assert "HW Verification" not in name, (
        f"A9 is named {name!r} but its gate never mandates a hardware "
        "measurement; a simulation-only close is legal by design")


def test_skip_hardware_reaches_the_lettered_analog_step():
    """The routing was int-id-only, so a lettered id could never match it however
    the run was launched."""
    assert "A9" in FCC._ANALOG_BENCH_STEP_IDS
    assert all(isinstance(x, str) for x in FCC._ANALOG_BENCH_STEP_IDS)


def test_skip_hardware_waives_a9_like_step_6(tmp_path):
    r = FCC.check_step(_project(tmp_path, hw=None), _a9(), {}, None,
                       skip_hardware=True)
    assert r.status == "WAIVED", (r.status, r.reasons)
    assert any("skip-hardware" in x for x in r.reasons), r.reasons


def test_without_the_flag_a9_is_not_waived(tmp_path):
    """DIRECTION 1: the waiver is the run MODE's, not a standing exemption."""
    r = FCC.check_step(_project(tmp_path, hw=None), _a9(), {}, None)
    assert r.status != "WAIVED", (r.status, r.reasons)
