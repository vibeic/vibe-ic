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

#901 — WHAT THIS FILE PINS, AND WHAT IT DELIBERATELY DOES NOT
-------------------------------------------------------------
The first version of these tests pinned the TIER NAME `VACUOUS_PASS`, because
under the pre-#901 rule one clause that disclosed inapplicability re-tiered the
whole step. #901 replaced that with a CENSUS: A9 runs two census-bearing gate
clauses and `mixed_signal_cosim_check` really does read the cosim results, so a
tier asserting the whole step measured nothing was false about the half that
did. A simulation-only close is now PASS carrying a `partially vacuous (1 of 2
…)` disclosure that names `analog_a9_hw_verify_check`.

Nothing this file protects moved. What it protects is that a simulation-only
close cannot be told from a bench-verified one — a claim about TWO verdicts,
now pinned as one (`test_the_disclosure_is_what_separates_it_from_a_bench_
verified_close`) instead of being approximated by a label. The assertions read
the emitted verdict and the dict the `--json` report is built from, so they hold
under either vacuity doctrine and go red the moment the disclosure itself does.
"""
from __future__ import annotations

import dataclasses
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


def _project(tmp_path: Path, hw: dict | None, corner: dict | None = None) -> Path:
    """A cosim-complete analog project; `hw` None == no bench measurement.

    `corner` writes the SPICE side that `analog_hw_spice_correlation_check`
    correlates a bench number against. It is what makes a bench-carrying
    project close CLEANLY rather than FAIL on "0 measurements compared", so a
    genuinely bench-verified close is available as a control.
    """
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
    if corner is not None:
        (tmp_path / "phase3" / "analog" / "blk1"
         / "corner_results.json").write_text(json.dumps(corner))
    return tmp_path


def _bench_verified(tmp_path: Path) -> Path:
    """The control: a close that really did read a bench number."""
    return _project(tmp_path, hw={"measurements": {"gain_db": 42.1}},
                    corner={"pvt_results": {"tt": {"gain_db": 42.0}}})


def _vacuity_disclosures(result) -> list:
    """The disclosures in an EMITTED verdict, read off the verdict itself.

    Deliberately keyed on the words a reviewer reads and on the clause NAME,
    not on the tier label: #901 moved which pass-tier this lands in, and a test
    that pins the label re-pins the defect that #901 removed instead of the
    disclosure this file exists to protect.
    """
    return [x for x in result.reasons
            if "vacuous" in x.lower() and "ADVISORY" not in x]


# ── the defect ───────────────────────────────────────────────────────────────

def test_simulation_only_close_is_not_a_bare_pass(tmp_path):
    """THE defect. Cosim green, no bench measurement anywhere -> the step must
    disclose. Before the fix this was status PASS with reasons == [].

    BARE is the word that carries the meaning, and it was never the tier: what
    made the old verdict indefensible was that it said NOTHING, so the report
    could not be told apart from a bench-verified close. This asserts on the
    emitted verdict — a disclosure exists, and it NAMES the clause that
    examined nothing — which is the property the fix owes, in whichever
    pass-tier the flow's vacuity arithmetic puts it.

    Under #901 that tier is PASS, not VACUOUS_PASS, and the reason is measured
    rather than stipulated: A9's gate runs TWO census-bearing clauses, and
    `mixed_signal_cosim_check` really does read the cosim results. A tier that
    says the whole step measured nothing would be false about the half that
    did; the tier says PASS and the disclosure says which half did not.
    """
    p = _project(tmp_path, hw=None)
    assert not list(p.rglob("hw_measurements.json"))
    r = FCC.check_step(p, _a9(), {}, None)
    assert r.reasons, (r.status, r.reasons)
    disclosed = _vacuity_disclosures(r)
    assert disclosed, (r.status, r.reasons)
    assert any("analog_a9_hw_verify_check" in x for x in disclosed), disclosed

    # …and it must survive into the machine-readable channel, which is what the
    # `--json` report is built from (`asdict(step_result)`). A disclosure that
    # only ever reached a terminal would be the same defect one layer down.
    emitted = dataclasses.asdict(r)
    assert any("analog_a9_hw_verify_check" in x and "vacuous" in x.lower()
               for x in emitted["reasons"]), emitted["reasons"]


def test_the_disclosure_is_what_separates_it_from_a_bench_verified_close(tmp_path):
    """The defect stated as the COMPARISON it was always about.

    The module header charges the old behaviour with being "byte-identical in
    the report to a bench-verified close". That is a claim about two verdicts,
    so pin it as one: run both closes through the same gate and require the
    emitted verdicts to differ, with the difference living in the disclosure
    and NOT in a mandate — the bench-verified close must not be the only one
    that can pass.
    """
    sim = FCC.check_step(_project(tmp_path / "sim", hw=None), _a9(), {}, None)
    bench = FCC.check_step(_bench_verified(tmp_path / "bench"), _a9(), {}, None)

    assert bench.status not in ("FAIL", "MISSING"), (bench.status, bench.reasons)
    assert sim.status not in ("FAIL", "MISSING"), (sim.status, sim.reasons)

    assert (sim.status, list(sim.reasons)) != (bench.status, list(bench.reasons))
    assert _vacuity_disclosures(sim), sim.reasons
    assert not _vacuity_disclosures(bench), bench.reasons


def test_simulation_only_close_is_still_legal(tmp_path):
    """DIRECTION 1, and the whole point of choosing disclosure over a mandate: a
    headless/CI analog run must still be able to close. The disclosure rides on
    a PASS-FAMILY verdict — this must NOT become FAIL or MISSING."""
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
