"""The non-promoted repair note stated a reason, and it was the wrong one.

`_ship_repair_nonpromotion_note` used to close every non-promoted exit with a
FIXED string:

    ... not promoted (needs setup>=0 and DRC-clean).

That is a stated CAUSE. The promotion gate has EIGHT refusal clauses, and the
note named two of them unconditionally.

MEASURED on caravel_user_project x sky130A. The route is deterministic to the
byte -- `routed.def` md5 8dd2a0b7ab326390192d14c38ab8322a on two independent
hosts -- so the shape below is reproducible, not a one-off sample:

    SHIP_WNS_POSTROUTE          +8.814 ns   <- setup >= 0  SATISFIED
    reroute DRC violations       0          <- DRC-clean   SATISFIED
    repair_design slew  transcript 31 -> 36 <- THE CLAUSE THAT ACTUALLY FIRED
    repair_design cap   transcript 26 -> 30 <- and this one

Both conditions the note advertised were met, so the note sent every reader
looking at setup and DRC -- neither of which was the problem -- while the DRV
per-category guard silently discarded a repaired route that is measurably
better at sign-off (525 -> 479 violated pins; max_fanout 4 -> 0). The cell's
failure was recorded for a long time as suspected PnR run-to-run randomness,
which the byte-identical routes disprove.

These tests pin two things:
  1. the note names the clause that actually refused, and does NOT name
     setup/DRC when those are satisfied;
  2. the derived reason list and the gate can never disagree -- the list is
     empty exactly when the gate promotes. That equivalence is the real guard:
     without it the note drifts away from the decision again the next time a
     clause is added.

chip/PDK/vendor-AGNOSTIC: pure text/arithmetic on a parsed dict.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

spec = importlib.util.spec_from_file_location(
    "p3_refusal_probe", _PROGRAMS / "phase3_one_shot_runner.py")
p3 = importlib.util.module_from_spec(spec)
sys.modules["p3_refusal_probe"] = p3
spec.loader.exec_module(p3)


def _measured() -> dict:
    """The real caravel_user_project x sky130A parsed log, verbatim values."""
    return {
        "done": True,
        "repair_noop": False,
        "reroute_incomplete": 0,
        "unrouted_nets": 0,
        "route_violations": 0,
        "wns_before": 8.705495237753713,
        "wns_after_repair": 8.705495237753713,
        "wns_postroute": 8.814346835237014,
        "drv_slew_before": 31, "drv_slew_after": 36,
        "drv_cap_before": 26, "drv_cap_after": 30,
    }


def test_the_measured_refusal_is_the_drv_transcript_not_setup_or_drc():
    p = _measured()
    assert p3._ship_repair_should_promote(p, True, True) is False
    why = p3._ship_repair_refusals(p)
    joined = " | ".join(why)
    assert any("slew" in w for w in why), joined
    assert any("capacitance" in w for w in why), joined
    # 31 -> 36 and 26 -> 30 must be quoted, not summarised away.
    assert "31 -> 36" in joined and "26 -> 30" in joined, joined
    # and the two satisfied conditions must NOT be blamed.
    assert not any("DRC-clean" in w for w in why), joined
    assert not any("non-negative setup" in w for w in why), joined


def test_the_published_note_no_longer_blames_setup_and_drc():
    note = p3._ship_repair_nonpromotion_note(_measured())
    assert "needs setup>=0 and DRC-clean" not in note
    assert "31 -> 36" in note, note


def test_refusal_list_is_empty_exactly_when_the_gate_promotes():
    """Anti-drift: the reason list and the decision are one fact."""
    base = _measured()
    cases = [
        base,
        {**base, "drv_slew_after": 31, "drv_cap_after": 26},   # promotes
        {**base, "drv_slew_after": 31, "drv_cap_after": 26,
         "reroute_incomplete": 2},
        {**base, "drv_slew_after": 31, "drv_cap_after": 26, "repair_noop": True},
        {**base, "drv_slew_after": 31, "drv_cap_after": 26, "unrouted_nets": 3},
        {**base, "drv_slew_after": 31, "drv_cap_after": 26,
         "route_violations": 7},
        {**base, "drv_slew_after": 31, "drv_cap_after": 26,
         "wns_postroute": 8.70},                                # no improvement
        {**base, "drv_slew_after": 31, "drv_cap_after": 26,
         "wns_after_repair": -5.0},
        {**base, "drv_slew_after": 31, "drv_cap_after": 26,
         "wns_after_repair": None},
    ]
    for i, p in enumerate(cases):
        promoted = p3._ship_repair_should_promote(p, True, True)
        why = p3._ship_repair_refusals(p)
        assert promoted is (not why), (
            f"case {i}: gate promoted={promoted} but reasons={why}")


def test_a_promoting_shape_yields_no_reason_and_the_note_says_so():
    p = {**_measured(), "drv_slew_after": 31, "drv_cap_after": 26}
    assert p3._ship_repair_should_promote(p, True, True) is True
    assert p3._ship_repair_refusals(p) == []
    # The note is only reached when artefacts were missing; it must then say
    # that, rather than inventing a clause.
    assert "no complete repaired route was written" in \
        p3._ship_repair_nonpromotion_note(p)
