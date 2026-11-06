#!/usr/bin/env python3
"""The ENV_UNAVAILABLE cap-gap waiver was UNEVALUABLE by the false-clean guard.

THE DEFECT
==========
`waiver_staleness` exists for exactly one job: refuse an ENV_UNAVAILABLE waiver
whose excused step actually EXECUTED in this run, so a carried-over waiver can
never excuse a failure that really happened.

It identifies the excused step by NAME only — `step`, `step_name`, or the
stamped `_waiver_condition.step`. But the flow's ONLY auto-produced
ENV_UNAVAILABLE waivers, the ones `flow_compliance_check._synthesise_fpga_skip_
waivers` and `_synthesise_pdk_substitution_waivers` build, identify their step
by canonical flow step ID and carry NO name at all::

    {"id": 6, "verdict_tier": "ENV_UNAVAILABLE", "_env_unavailable": true, ...}

`waivers_materialize._to_entry` then stamps them through `waiver_staleness.
stamp`, which asks the same name-only question and writes the condition with an
EMPTY step::

    "_waiver_condition": {"kind": "step_did_not_execute", "step": "", ...}

so the consumer reports `ENV_UNAVAILABLE waiver names no step — condition
unevaluable` and HONOURS the waiver unconditionally, forever, on every run.

MEASURED on the withdrawn spm publish run (waivers.json, 3 entries)::

    id=39 step=None  -> (True, 'ENV_UNAVAILABLE waiver names no step — condition unevaluable')
    id=6  step=None  -> (True, 'ENV_UNAVAILABLE waiver names no step — condition unevaluable')
    id=None step='digital_hardmacro_gen' -> (True, "step 'digital_hardmacro_gen' still reports a did-not-run status — condition holds")

Two of the three — and both of the two the guard was written for — were never
evaluated. The guard was disarmed for precisely the waiver class the flow
generates automatically, which is the class most likely to be carried forward.

THE FIX
=======
`_waiver_entries` already owns the ONE vocabulary for "which flow step a waiver
names", including the role-name -> id map. It gains the inverse,
`step_names_for_id`, and the guard resolves an id-only entry through it. The
mapping is MANY-TO-ONE (31 is drc/lvs/erc/physical_verification), so the
inverse returns EVERY role name and the guard applies its existing rule —
POSITIVE execution evidence anywhere is decisive — across all of them.

DIRECTION OF THE FIX. It can only ever make the guard able to REFUSE; a waiver
it could not evaluate was already being honoured. `test_still_honoured_*`
pins that a genuine did-not-run deferral is untouched, so "able to say no" was
not bought by saying no to everything.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _waiver_entries as _we             # noqa: E402


# The shape `_synthesise_fpga_skip_waivers` emits, verbatim in its identifying
# fields: an id, an ENV_UNAVAILABLE tier, and NO step name anywhere.
def _capgap_entry(step_id, stamped_empty: bool = True) -> dict:
    entry = {
        "id": step_id,
        "reason": "ENV_UNAVAILABLE (fpga-board-prototype cap-gap): ...",
        "approver": "field-agent-attest (fpga-board cap-gap tier)",
        "ticket": "fpga-board-prototype-capgap-v1.0.18",
        "verdict_tier": "ENV_UNAVAILABLE",
        "review_required": True,
        "_env_unavailable": True,
        "_fpga_skip": True,
        "auto_synthesized": True,
    }
    if stamped_empty:
        entry["_waiver_condition"] = {
            "kind": "step_did_not_execute",
            "step": "",
            "run_id": "reports/orchestrator/phase2_one_shot.json:mtime=1",
            "note": "...",
        }
    return entry


def _project(tmp_path: Path, steps) -> Path:
    p = tmp_path / "run"
    (p / "reports" / "orchestrator").mkdir(parents=True, exist_ok=True)
    (p / "reports" / "orchestrator" / "phase2_one_shot.json").write_text(
        json.dumps({"steps": list(steps)}))
    return p


# ---------------------------------------------------------------------------
# The inverse vocabulary
# ---------------------------------------------------------------------------
def test_step_names_for_id_returns_every_role_name_many_to_one():
    """31 is drc AND lvs AND erc AND physical_verification. The inverse of a
    many-to-one map is a SET, and dropping members would silently narrow which
    report steps the guard consults."""
    names = _we.step_names_for_id(31)
    assert set(names) >= {"drc", "lvs", "erc", "physical_verification"}
    for n in names:
        assert _we.resolve_step_name(n) == 31


def test_step_names_for_id_covers_the_two_fpga_board_steps():
    assert "fpga_compile" in _we.step_names_for_id(6)
    assert "fpga_onboard_test" in _we.step_names_for_id(39)


def test_step_names_for_id_handles_string_and_analog_ids():
    assert "analog_layout" in _we.step_names_for_id("A5")
    # A digit-string id is the same step as the int id, not a different one.
    assert set(_we.step_names_for_id("6")) == set(_we.step_names_for_id(6))


def test_step_names_for_id_never_answers_for_a_bool_or_unknown_id():
    """`True == 1` in Python. A bool id must not silently claim step 1's
    names, and an id no role maps to must answer nothing rather than guess."""
    assert _we.step_names_for_id(True) == ()
    assert _we.step_names_for_id(None) == ()
    assert _we.step_names_for_id(9999) == ()


# ---------------------------------------------------------------------------
# The guard: an id-only waiver is EVALUABLE
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The producer side: the stamp stops writing an empty step
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# End to end through the mapping the audit actually consumes
# ---------------------------------------------------------------------------
