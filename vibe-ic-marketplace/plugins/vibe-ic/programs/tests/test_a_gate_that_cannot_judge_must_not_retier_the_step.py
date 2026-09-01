"""A NOT-CHECKED classifier must not enter the gate denominator.

The defect
----------
`hold_area_budget_check` can never reach a verdict today: nothing in the plugin
writes `hold_buffer_area` / `total_cell_area` / a before-after total pair, so
project-directory mode always returns rc=2 NOT CHECKED. Wired at Step 20 in a
BLOCKING `program_exit_zero` slot, that rc=2 emits a `__VACUOUS_HINT__`, and
`check_step` promotes the whole STEP to `VACUOUS_PASS`.

`PASS_VOIDED_BY_DEPENDENCY` is only ever applied to a step whose status is
exactly `PASS`:

    if str(_r.id) != _tid or _r.status != "PASS":
        continue

so promoting the step to VACUOUS_PASS silently DELETES the stronger line

    PASS voided: dependency [19] CTS = FAIL, so this step's PASS certifies
    nothing about the design

`flow_compliance_check`'s own comment forbids the swap: "a vacuous step is one
nobody has to come back to, and a voided one is a step somebody does."
Published radius is 0 — Step 20 is MISSING on all 34 published run roots — so
it bites only on LIVE runs, which is worse, not better.

The repair
----------
Issue #1980 moves the classifier to the step's `program_outputs`. Its typed
NOT-CHECKED output remains reportable, but a program with no refusal predicate
cannot count as gate coverage or retier the step.

These tests drive the REAL entry point over a real fixture, and the second one
is the positive control: it re-runs the identical fixture against a yaml whose
only difference is the slot keyword, and asserts the defect comes back.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
FCC = PROGRAMS / "flow_compliance_check.py"

_VOIDED_RE = re.compile(
    r"PASS voided: dependency \[19\] CTS.*= FAIL, so this step's PASS "
    r"certifies nothing about the design")


def _def(ncomp: int, tag: str) -> str:
    comps = "\n".join(
        f"  - u{i} sky130_fd_sc_hd__buf_1 + PLACED ( {1000 + i * 10} 2000 ) N ;"
        for i in range(ncomp))
    return (f"VERSION 5.8 ;\nDIVIDERCHAR \"/\" ;\nBUSBITCHARS \"[]\" ;\n"
            f"DESIGN top_{tag} ;\nUNITS DISTANCE MICRONS 1000 ;\n"
            f"DIEAREA ( 0 0 ) ( 100000 100000 ) ;\n"
            f"COMPONENTS {ncomp} ;\n{comps}\nEND COMPONENTS\nEND DESIGN\n")


@pytest.fixture
def broken_chain(tmp_path):
    """Step 19 (CTS) FAILs on a vacuous clock-tree report; Step 20 (hold fix)
    genuinely PASSes — 4 hold buffers over the pre-hold input. Step 20's PASS
    therefore rests on a chain that broke."""
    pnr = tmp_path / "phase3/stage3/pnr"
    cts = tmp_path / "phase3/stage3/cts"
    pnr.mkdir(parents=True)
    cts.mkdir(parents=True)
    (pnr / "post_cts.def").write_text(_def(40, "cts"))
    (cts / "clock_tree.rpt").write_text(
        "CTS not invoked\nno clock tree was built\n")
    (pnr / "post_hold.def").write_text(_def(44, "hold"))
    return tmp_path


def _audit(project: Path, flow_def: Path) -> str:
    # <=60s: `ci_harness_timeout_ceiling_check` derives a 60s per-call ceiling
    # from the 180s harness bound, so an inner timeout above it can only fire
    # after the session has already been killed. Measured worst case for this
    # audit over the 4-file fixture is ~0.5s.
    r = _pr.run(
        [sys.executable, str(FCC), str(project), "--phase", "3", "--lenient",
         "--flow-def", str(flow_def)],
        capture_output=True, text=True)
    return r.stdout + r.stderr


def _step20(out: str) -> str:
    keep, on = [], False
    for ln in out.splitlines():
        if re.search(r"] Step 20:", ln):
            on = True
        elif on and re.search(r"] Step \d+:", ln):
            break
        if on:
            keep.append(ln)
    return "\n".join(keep)


def test_the_shipped_wiring_keeps_the_voided_disclosure(broken_chain):
    out = _audit(broken_chain, FLOW)
    block = _step20(out)
    assert "[PASS-VOIDED" in block, block
    assert _VOIDED_RE.search(block), block
    assert "VACUOUS-PASS" not in block, block


def test_the_classifier_is_a_program_output_not_a_gate():
    step20 = next(step for step in yaml.safe_load(FLOW.read_text())["steps"]
                  if step["id"] == 20)
    assert "hold_area_budget_check" in step20["programs"]
    assert "hold_area_budget_check" not in str(step20["gate"])
    assert step20["program_outputs"] == [{
        "program": "hold_area_budget_check",
        "path": "reports/phase3/pnr/hold_area_budget.json",
        "verdict_field": "verdict",
    }]


def test_POSITIVE_CONTROL_the_blocking_slot_deletes_the_voided_line(
        broken_chain, tmp_path):
    """Adding the classifier back as a gate recreates the tier defect."""
    flow = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    step20 = next(step for step in flow["steps"] if step["id"] == 20)
    step20["gate"]["all_of"].insert(0, {
        "program_exit_zero": (
            "hold_area_budget_check . --json "
            "reports/phase3/pnr/hold_area_budget.json")})
    variant = tmp_path / "blocking_flow.yaml"
    variant.write_text(yaml.safe_dump(flow, sort_keys=False))

    out = _audit(broken_chain, variant)
    block = _step20(out)
    # #1978 makes this unclassified rc=2 an unsafe non-verdict rather than a
    # benign vacuous skip.  The control's subject is unchanged: putting the
    # classifier back in the gate denominator re-tiers Step 20 away from PASS
    # and deletes the dependency-voided disclosure.
    assert "[INCOMPLETE" in block, block
    assert re.search(
        r"GATE_RAN hold_area_budget_check\s+rc=2\s+INCOMPLETE "
        r"reason_class=EXECUTION_ERROR", out), out
    assert not _VOIDED_RE.search(block), (
        "the blocking slot was supposed to delete the voided disclosure; if "
        "it no longer does, the tier interaction was fixed elsewhere and this "
        "wiring choice should be revisited\n" + block)
