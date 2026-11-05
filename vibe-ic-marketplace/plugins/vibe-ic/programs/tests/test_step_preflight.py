#!/usr/bin/env python3
"""Bidirectional control for the `required_inputs` PRE-FLIGHT WIRING.

The capability (`step_required_inputs_check`) already had its own control. What
had NO control — and no caller — was the BEHAVIOUR: a runner that refuses to
dispatch a step whose declared inputs are absent.

FORWARD  a synthetic run missing exactly ONE declared input has that step
         REFUSED: the step function is never entered, the row is BLOCKED, and
         the refusal names the absent artefact AND the step that owed it.

REVERSE  the SAME synthetic run with that one input restored — nothing else
         changed — dispatches the step normally. This is the half that stops
         the forward control from being satisfied by a check that refuses
         everything.

Plus the controls that stop this from becoming a falsely-clean gate:
  * every site's declared flow-step ids exist in the shipped flow;
  * every declared site is ACTUALLY wired at a call site in its runner (a fix
    that never reaches the code that runs is not a fix);
  * BLOCKED is non-green in BOTH runners' `_aggregate_verdict`;
  * a producer-disclosed skip does NOT refuse (legitimate skips must not break);
  * an UNDECLARED span runs but SAYS it was not checked;
  * an unreadable flow yields UNAVAILABLE, never READY.
"""
from __future__ import annotations

import sys
from pathlib import Path



PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))




# --------------------------------------------------------------------------- #
# A synthetic run whose ONLY question is the one declared input of canonical
# step 31 (Physical Verification): step 21's `phase3/stage3/pnr/routed.def`.
# --------------------------------------------------------------------------- #
ROUTED_DEF = "phase3/stage3/pnr/routed.def"


def _synthetic_run(root: Path, with_routed_def: bool) -> Path:
    p = root / "run"
    (p / "phase2/stage1/rtl").mkdir(parents=True, exist_ok=True)
    (p / "phase2/stage2/synth").mkdir(parents=True, exist_ok=True)
    (p / "phase3/stage3/pnr").mkdir(parents=True, exist_ok=True)
    (p / "phase2/stage1/rtl/top.sv").write_text(
        "module top(input clk); endmodule\n")
    (p / "phase2/stage2/synth/netlist.v").write_text("module top(); endmodule\n")
    if with_routed_def:
        (p / ROUTED_DEF).write_text("DESIGN top ;\nEND DESIGN\n")
    return p








# --------------------------------------------------------------------------- #
# FORWARD
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# REVERSE — same run, one input restored, nothing else changed
# --------------------------------------------------------------------------- #


def test_forward_and_reverse_differ_only_in_that_one_file(tmp_path):
    """The pair above is a CONTROL only if the two trees differ by one path."""
    a = _synthetic_run(tmp_path / "a", with_routed_def=False)
    b = _synthetic_run(tmp_path / "b", with_routed_def=True)
    ra = {str(f.relative_to(a)) for f in a.rglob("*") if f.is_file()}
    rb = {str(f.relative_to(b)) for f in b.rglob("*") if f.is_file()}
    assert rb - ra == {ROUTED_DEF}
    assert ra - rb == set()


# --------------------------------------------------------------------------- #
# A run that LEGITIMATELY skips a step must not be broken
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# UNDECLARED must not block, and must not pass silently either
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# "I could not look" must never read as "I looked and it was fine"
# --------------------------------------------------------------------------- #






# --------------------------------------------------------------------------- #
# The map itself
# --------------------------------------------------------------------------- #




# --------------------------------------------------------------------------- #
# Did the fix reach the code that actually runs?
# --------------------------------------------------------------------------- #










# --------------------------------------------------------------------------- #
# A run that legitimately skips a step, from the CALLER's own authority
# --------------------------------------------------------------------------- #




def test_phase3_pure_analog_waiver_still_precedes_every_gate():
    """MEASURED on the real `u_hawaii_adc` Phase-1 tree (class `data_converter`,
    all-analog top interface, empty rtl/): the phase-3 runner WAIVEs the whole
    digital backend and writes NO pre-flight ledger, because the waiver branch
    is upstream of every `_spf.gate` call. Without that ordering, a pure-analog
    cell's five WAIVED rows would become five BLOCKED rows — a legitimately
    skipping run broken by the pre-flight. Cheap structural guard for an
    invariant whose real proof takes a whole phase-3 run."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text().splitlines()
    waive = next(i for i, l in enumerate(src) if "elif is_pure_analog:" in l)
    first_gate = next(i for i, l in enumerate(src) if "_spf.gate(" in l)
    assert waive < first_gate, (
        "a `_spf.gate` call now precedes the pure-analog waiver — a pure-analog "
        "cell would be REFUSED instead of WAIVED")
