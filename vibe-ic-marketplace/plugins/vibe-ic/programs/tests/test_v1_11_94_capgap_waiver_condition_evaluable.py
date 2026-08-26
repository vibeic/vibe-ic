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
import waiver_staleness as ws             # noqa: E402


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
def test_id_only_capgap_waiver_is_refused_when_its_step_actually_ran(tmp_path):
    """THE DEFECT, stated as the failure it allowed: the board step EXECUTED
    and FAILED, and the carried-over cap-gap waiver excused it."""
    project = _project(tmp_path, [{"name": "fpga_compile", "status": "FAIL"}])
    ok, why = ws.condition_holds(_capgap_entry(6), project)
    assert ok is False, why
    assert "STALE WAIVER REFUSED" in why
    assert "fpga_compile" in why


def test_id_only_capgap_waiver_is_still_honoured_when_the_step_did_not_run(
        tmp_path):
    """The other direction. A genuine ENV_UNAVAILABLE deferral must be
    untouched — being able to refuse is worthless if it refuses everything."""
    project = _project(tmp_path, [{"name": "fpga_compile", "status": "SKIP"}])
    ok, why = ws.condition_holds(_capgap_entry(6), project)
    assert ok is True
    assert "condition holds" in why
    assert "unevaluable" not in why


def test_id_only_capgap_waiver_is_honoured_with_no_evidence(tmp_path):
    """Absence of evidence never manufactures a rejection."""
    project = _project(tmp_path, [{"name": "synth", "status": "PASS"}])
    ok, why = ws.condition_holds(_capgap_entry(39), project)
    assert ok is True
    assert "unevaluable" not in why


def test_the_withdrawn_run_shape_is_no_longer_unevaluable(tmp_path):
    """The exact three-entry shape measured on the spm publish run: two id-only
    cap-gap entries stamped with an EMPTY `_waiver_condition.step`, one
    name-carrying entry. None may report `unevaluable`."""
    project = _project(tmp_path, [
        {"name": "fpga_compile", "status": "SKIP"},
        {"name": "digital_hardmacro_gen", "status": "ENV_UNAVAILABLE"},
    ])
    entries = [_capgap_entry(39), _capgap_entry(6),
               {"step": "digital_hardmacro_gen", "verdict_tier":
                "ENV_UNAVAILABLE", "review_required": True}]
    for e in entries:
        ok, why = ws.condition_holds(e, project)
        assert ok is True, why
        assert "unevaluable" not in why, why


def test_many_to_one_id_refuses_when_any_of_its_role_steps_ran(tmp_path):
    """A waiver for step 31 excuses physical verification. If LVS ran, the
    condition it was issued under is broken even though DRC did not."""
    project = _project(tmp_path, [{"name": "drc", "status": "SKIP"},
                                  {"name": "lvs", "status": "FAIL"}])
    ok, why = ws.condition_holds(_capgap_entry(31, stamped_empty=False),
                                 project)
    assert ok is False, why
    assert "lvs" in why


def test_explicit_step_name_path_is_unchanged(tmp_path):
    """The name-carrying dialect must behave exactly as before, in BOTH
    directions."""
    project = _project(tmp_path, [{"name": "digital_hardmacro_gen",
                                   "status": "PASS"}])
    ok, why = ws.condition_holds(
        {"step": "digital_hardmacro_gen", "_env_unavailable": True}, project)
    assert ok is False and "STALE WAIVER REFUSED" in why
    project2 = _project(tmp_path / "b", [{"name": "digital_hardmacro_gen",
                                          "status": "ENV_UNAVAILABLE"}])
    ok2, _ = ws.condition_holds(
        {"step": "digital_hardmacro_gen", "_env_unavailable": True}, project2)
    assert ok2 is True


def test_a_waiver_naming_no_step_and_no_known_id_is_still_unevaluable(
        tmp_path):
    """The honest silence is preserved for an entry that really does identify
    nothing — the fix resolves ids, it does not invent them."""
    project = _project(tmp_path, [{"name": "synth", "status": "PASS"}])
    ok, why = ws.condition_holds({"_env_unavailable": True}, project)
    assert ok is True
    assert "unevaluable" in why


# ---------------------------------------------------------------------------
# The producer side: the stamp stops writing an empty step
# ---------------------------------------------------------------------------
def test_stamp_records_the_resolved_step_for_an_id_only_entry(tmp_path):
    project = _project(tmp_path, [{"name": "fpga_compile", "status": "SKIP"}])
    stamped = ws.stamp({"id": 6, "_env_unavailable": True}, project)
    cond = stamped["_waiver_condition"]
    assert cond["kind"] == ws.CONDITION_STEP_DID_NOT_EXECUTE
    assert cond["step"] == "fpga_compile"
    assert cond["step"] != ""


def test_stamp_leaves_a_non_env_unavailable_entry_untouched(tmp_path):
    project = _project(tmp_path, [])
    entry = {"id": 6, "verdict_tier": "REVIEWED"}
    assert ws.stamp(dict(entry), project) == entry


# ---------------------------------------------------------------------------
# End to end through the mapping the audit actually consumes
# ---------------------------------------------------------------------------
def test_prune_stale_mapping_drops_the_id_only_waiver_that_ran(tmp_path):
    project = _project(tmp_path, [{"name": "fpga_compile", "status": "PASS"}])
    mapping = {6: _capgap_entry(6), 39: _capgap_entry(39)}
    refused = ws.prune_stale_mapping(mapping, project)
    assert 6 in refused, "the executed step's waiver must be evicted"
    assert 6 not in mapping
    assert 39 in mapping, "the board step with no evidence stays honoured"


def test_filter_honorable_splits_the_capgap_pair(tmp_path):
    project = _project(tmp_path, [{"name": "fpga_compile", "status": "FAIL"}])
    keep, drop = ws.filter_honorable(
        [_capgap_entry(6), _capgap_entry(39)], project)
    assert [e["id"] for e in drop] == [6]
    assert [e["id"] for e in keep] == [39]
    assert "_refused_reason" in drop[0]


@pytest.mark.parametrize("status", ["PASS", "FAIL", "OK", "ERROR", "BLOCK"])
def test_every_executed_status_breaks_the_id_only_condition(tmp_path, status):
    project = _project(tmp_path / status,
                       [{"name": "fpga_compile", "status": status}])
    ok, _ = ws.condition_holds(_capgap_entry(6), project)
    assert ok is False
