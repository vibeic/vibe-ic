"""Wiring a NOT-CHECKED gate must not downgrade a step's disclosure tier.

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
The gate moves to the `advisory_program_exit_zero` slot. `_evaluate_gate`
refuses to record rc=2 as `ok` and writes `n/a (input not present)` instead, and
`check_step` holds ADVISORY hints OUT of the tier decision (#306) — so the
disclosure is recorded AND the step stays PASS, so the voided line survives.

These tests drive the REAL entry point over a real fixture, and the last one
is the positive control: it re-runs the identical fixture against a yaml with
one gate name changed, and asserts the defect comes back.

SUPERSEDED IN PART BY vibe-ic#901 — recorded here, not silently absorbed
=======================================================================
The repair above is a PER-GATE one: move this gate out of the blocking slot.
#901 fixed the CLASS in `check_step` — the tier now COUNTS the clauses that
could have disclosed vacuity and requires ALL of them before calling a step
vacuous, so one unjudgeable gate can no longer re-tier a step whose siblings
reached verdicts. Measured on this file's own fixture: with the gate forced
back into the blocking slot the step now stays PASS and the voided line
survives, which is what the old positive control asserted would NOT happen.

That control's own failure message named this exact condition — "if it no
longer does, the tier interaction was fixed elsewhere and this wiring choice
should be revisited". It is kept, inverted, and a NEW positive control (every
countable clause vacuous) restores the falsification the file needs.

The advisory slot stays right: #306 is what keeps a gate that can never judge
out of the blocking denominator in the first place, and what puts its
NOT-CHECKED verdict on the step line.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
FCC = PROGRAMS / "flow_compliance_check.py"

_ADVISORY_CLAUSE = (
    '- advisory_program_exit_zero: "hold_area_budget_check . '
    '--json reports/phase3/pnr/hold_area_budget.json"')
_BLOCKING_CLAUSE = (
    '- program_exit_zero: "hold_area_budget_check . '
    '--json reports/phase3/pnr/hold_area_budget.json"')

#: #901 — step 20's ONE clause that can reach a verdict on this fixture, and
#: the substitution that makes every countable clause of the step vacuous.
#: That, not the slot keyword, is what decides the tier now.
_VERDICT_CAPABLE_CLAUSE = (
    '- program_exit_zero: "hold_closure_check . '
    '--json reports/phase3/pnr/hold_closure.json"')
_UNJUDGEABLE_SUBSTITUTE = (
    '- program_exit_zero: "hold_area_budget_check . '
    '--json reports/phase3/pnr/hold_closure.json"')

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
    r = subprocess.run(
        [sys.executable, str(FCC), str(project), "--phase", "3", "--lenient",
         "--flow-def", str(flow_def)],
        capture_output=True, text=True, timeout=55)
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


def test_the_advisory_slot_still_RECORDS_the_not_checked_disclosure(
        broken_chain):
    """Not blocking is not the same as not recorded. The gate must still RUN
    in-flow and its NOT-CHECKED verdict must reach the step line — an advisory
    gate that ran and said nothing would make the run look audited."""
    out = _audit(broken_chain, FLOW)
    assert "GATE_RAN hold_area_budget_check" in out, out
    assert re.search(r"GATE_RAN hold_area_budget_check\s+rc=2", out), out
    block = _step20(out)
    assert "ADVISORY (non-blocking, #306)" in block, block
    assert "hold_area_budget_check" in block, block


def test_the_blocking_slot_NO_LONGER_deletes_the_voided_line(
        broken_chain, tmp_path):
    """SUPERSEDED CONTROL — kept, inverted, and MEASURED (vibe-ic#901).

    This was the positive control: the same fixture against a yaml differing
    ONLY in the slot keyword, asserting that the blocking slot brought the
    defect back. Its own failure message named the condition under which it
    would stop holding — "if it no longer does, the tier interaction was fixed
    elsewhere and this wiring choice should be revisited". #901 is that fix.

    The tier no longer turns on ONE clause's disclosure: `check_step` counts
    the clauses that could have disclosed vacuity and requires ALL of them
    before it will call a step vacuous. Step 20 declares `hold_closure_check`
    alongside `hold_area_budget_check`, and on this fixture that gate reaches
    a real verdict — so with the gate in EITHER slot the step stays a PASS and
    the voided line survives. Asserting the old outcome here would be pinning
    a defect.

    The slot choice is still right and still load-bearing: `#306` is what
    keeps a gate that can never judge out of the blocking denominator at all,
    and the ADVISORY line is what makes its NOT-CHECKED verdict visible. What
    changed is that it is no longer the ONLY thing standing between an
    unjudgeable gate and a deleted disclosure.
    """
    text = FLOW.read_text(encoding="utf-8")
    assert text.count(_ADVISORY_CLAUSE) == 1, "the shipped clause moved"
    variant = tmp_path / "blocking_flow.yaml"
    variant.write_text(text.replace(_ADVISORY_CLAUSE, _BLOCKING_CLAUSE))

    block = _step20(_audit(broken_chain, variant))
    assert "[VACUOUS-PASS" not in block, block
    assert _VOIDED_RE.search(block), (
        "with #901's clause census in place the blocking slot must no longer "
        "be able to delete the voided disclosure\n" + block)
    assert "partially vacuous" in block, (
        "the unjudgeable gate's disclosure must survive the PASS — trading "
        "the wrong tier for a silent one is the same defect\n" + block)


def test_POSITIVE_CONTROL_an_ALL_vacuous_step_still_deletes_the_voided_line(
        broken_chain, tmp_path):
    """THE CONTROL, re-authored around what now decides the tier.

    The forward tests assert that Step 20 keeps its voided line. That claim is
    only worth something if a yaml exists on which it FAILS. It does: leave
    the unjudgeable gate exactly where it is and replace the ONE clause that
    can reach a verdict (`hold_closure_check`) with the same gate that cannot,
    so EVERY countable clause of the step discloses vacuity. The step is then
    genuinely vacuous, and the voided line is genuinely deleted.

    Same fixture, same entry point, one gate name different — and it separates
    "the census works" from "the VACUOUS_PASS tier was deleted".
    """
    text = FLOW.read_text(encoding="utf-8")
    assert text.count(_VERDICT_CAPABLE_CLAUSE) == 1, (
        "step 20's verdict-capable clause moved")
    variant = tmp_path / "all_vacuous_flow.yaml"
    variant.write_text(text.replace(_VERDICT_CAPABLE_CLAUSE,
                                    _UNJUDGEABLE_SUBSTITUTE))

    block = _step20(_audit(broken_chain, variant))
    assert "[VACUOUS-PASS" in block, block
    assert not _VOIDED_RE.search(block), (
        "every countable clause disclosed that it examined nothing, so the "
        "step IS vacuous and the voided line must go\n" + block)
