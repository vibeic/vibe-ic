"""#654 — the router aborted and only one step noticed.

MEASURED on a real sky130A run:

    x  Step 26  Antenna check                     FAIL
    v  Step 31  Physical Verification (DRC+LVS)   PASS
    v  Step 37  GDSII output                      PASS
    v  Step 38  Foundry Handoff                   PASS

A 24 MB GDS was streamed and declared handoff-ready for a layout the router
never finished. Step 37's own NAME states the contract — "only if Step 31 PV
fully clean" — and Step 31 passed vacuously, so the guard let it through.

DRC and LVS on an unrouted layout are not WRONG, they are VACUOUS: there is
little routing to violate a spacing rule, and a netlist with no realized
interconnect can still match uniquely. True statements about a question nobody
asked, published under the names of the questions that were.

Nothing had to be inferred. The antenna step already writes

    { "clean": false, "routing_incomplete": true,
      "verdict": "FAIL", "net_violations": 0 }

and that pair on one line IS the trap: a clean antenna count on a design with no
realized signal routing. `grep -c routing_incomplete` over
`foundry_handoff_pack_gen.py` returned 0. `flow_compliance_check` catches it at
the audit layer, so the FLOW knows; the steps each certify independently and
never ask.

THE NEGATIVE CONTROL THE ISSUE ASKED FOR, run end to end:

    antenna.json                  reader   step_drc       handoff rc
    routing_incomplete: true      True     VACUOUS_PASS   2
    routing_incomplete: false     False    not blocked    0
    key ABSENT                    None     not blocked    0

"A gate that only fires in one direction is the defect this issue is about."
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner", _PROGRAMS / "phase3_one_shot_runner.py")
# REUSE THE OBJECT EVERY OTHER MODULE ALREADY HOLDS. Registering a fresh
# copy under the real name replaced `sys.modules["phase3_one_shot_runner"]`
# for everything collected AFTER this file: a test that bound the runner
# earlier and monkeypatches it was then patching an object nobody else
# resolved any more. MEASURED: collecting this file after
# test_d3_new_output_live_measurement turned six of its probes red ("never
# measured by a valid producer execution") while both were green alone. The
# load-by-path, SystemExit-tolerant fallback stays for a session in which
# nothing has imported the runner yet.
P = sys.modules.get("phase3_one_shot_runner")
if P is None:
    P = importlib.util.module_from_spec(_spec)
    sys.modules["phase3_one_shot_runner"] = P
    try:
        _spec.loader.exec_module(P)
    except SystemExit:
        pass


def _project(tmp_path, routing_incomplete):
    """A run whose antenna step recorded (or did not record) the fact."""
    r = P._pl.reports_phase3_dir(tmp_path)
    r.mkdir(parents=True, exist_ok=True)
    payload = {
        "tool": "openroad",
        "mode": "antenna_check_in_session_post_repair",
        # 0 violations beside an unrouted design — the trap, verbatim
        "net_violations": 0,
        "pin_violations": 0,
        "clean": True,
        "verdict": "FAIL" if routing_incomplete is True else "PASS",
    }
    if routing_incomplete is not None:
        payload["routing_incomplete"] = routing_incomplete
    (r / "antenna.json").write_text(json.dumps(payload, indent=2))
    return tmp_path


# ── the recorded fact, read rather than re-derived ────────────────────────


# ── what the sign-off steps do with it ────────────────────────────────────


# ── the three steps are actually wired, not merely wire-able ──────────────


# ── step 38, the most expensive form ──────────────────────────────────────
def _handoff(project):
    return _pr.run(
        [sys.executable, str(_PROGRAMS / "foundry_handoff_pack_gen.py"),
         str(project)],
        # 30s: `ci_harness_timeout_ceiling_check` caps an inner bound at 60,
        # because the harness dies at 180 and a longer bound kills the SESSION
        # rather than the call. MEASURED at 0.04s per invocation. This test
        # tripped that ceiling on its first landing — the third time in this one
        # batch, which is why the ceiling is a gate and not a convention.
        capture_output=True, text=True)


def test_the_handoff_pack_refuses_on_an_unrouted_layout(tmp_path):
    r = _handoff(_project(tmp_path, True))
    assert r.returncode == 2, r.stdout[-400:] + r.stderr[-400:]
    assert "INCOMPLETE" in r.stderr


def test_the_handoff_pack_does_not_refuse_a_routed_one(tmp_path):
    """The other direction, run for real. If this refused too, the fix would be
    "never hand off", which is not a fix."""
    r = _handoff(_project(tmp_path, False))
    assert r.returncode != 2 or "NOT_MEASURED" not in r.stderr


def test_the_handoff_pack_does_not_refuse_an_unrecorded_run(tmp_path):
    r = _handoff(_project(tmp_path, None))
    assert r.returncode != 2 or "NOT_MEASURED" not in r.stderr


def test_the_generator_names_the_fact_at_all():
    """`grep -c 'antenna.json\\|routing_incomplete'` over this file returned 0
    when the issue was filed. That count is the finding."""
    src = (_PROGRAMS / "foundry_handoff_pack_gen.py").read_text(encoding="utf-8")
    assert "routing_incomplete" in src and "antenna.json" in src
