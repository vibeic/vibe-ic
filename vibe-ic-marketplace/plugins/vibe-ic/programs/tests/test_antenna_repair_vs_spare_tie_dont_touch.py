"""Antenna repair aborts at iteration 0 because the design-for-ECO spare tie net
is `dont_touch`, and the run ships unrepaired antennas plus floating diodes.

現象 (caravel_user_project x sky130A, clean-room v1.8.90):

    openroad.log  Completing 100% with 0 violations.        <- detailed route CLEAN
                  [INFO ANT-0002] Found 15 net violations.
                  [INFO ANT-0001] Found 18 pin violations.
                  [ERROR ODB-0373] Attempt to connect iterm to dont_touch net spare_tielo
                  ANTENNA_NATIVE_REROUTE_NONFATAL: ODB-0373
                  [ERROR ODB-0373] Attempt to connect iterm to dont_touch net spare_tielo
                  REPAIR_ANTENNA_NONFATAL: ODB-0373
                  ANTENNA_POSTROUTE_DONE

`_build_spare_postfix_tcl` marks the spare tie nets `setDoNotTouch true` so the
RESIZER SKIPS them instead of erroring on a dont_touch load pin. `repair_antennas`
is not the resizer — it only ADDS a diode instance and re-routes — but odb refuses
that connection too, which trips the catch on the `-reroute` call AND on its
fallback, so the repair loop `break`s at iteration 0.

Measured consequences in the shipped artefacts: 40 diode COMPONENTS placed but only
38 `( ANTENNA_n DIODE )` net connections (two `sky130_fd_sc_hd__diode_2 ANTENNA_n ()`
instances with a FLOATING gate input), 15 net + 18 pin antenna violations left, Step
26 FAIL and — through `perc_equivalent` — Step 28 FAIL.

Fix: lift the protection from the spare TIE NETS for the antenna window only and
restore it immediately after. Exactly the ORGANIC #563 precedent one layer down
(there: an INSTANCE, for the flow's own deliberate tie-off; here: a NET, for the
flow's own deliberate diode attach).

This is a guard RELAXATION, so the load-bearing half is the NO-LEAK proof (§4.05):

  * the relaxation is SCOPED — only the two spare tie NETS, named literally, are
    ever unprotected; no other net and no INSTANCE is;
  * it is BOUNDED — protection is restored UNCONDITIONALLY after the repair block,
    outside the if/else, so no `break` path can leave a net unprotected for the
    resizer passes that follow;
  * it only restores what it itself lifted (`$_ant_unprot`), so a net the flow
    never protected is not silently protected on the way out.

The end-to-end negative control is the flow's own `spare_preservation` /
`spare_cell_coverage` gates, which measure the invariant independently on the real
run — a source test cannot stand in for those, and this file does not pretend to.

chip-AGNOSTIC: the tie-net names are the flow's own, no chip/PDK literal.
"""
import re
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as P3  # noqa: E402


class _Pdk:
    """Minimal stand-in: the emitter reads only the diode-cell name."""
    antenna_diode_cell = "sky130_fd_sc_hd__diode_2"


def _tcl() -> str:
    return P3._antenna_repair_tcl(_Pdk())


def test_repair_can_attach_a_diode_to_a_spare_tie_net():
    """The window exists at all: the tie nets are unprotected before the repair."""
    t = _tcl()
    assert "setDoNotTouch false" in t, t[:400]
    i_unprot = t.index("setDoNotTouch false")
    i_repair = t.index("repair_antennas")
    assert i_unprot < i_repair, "unprotect must precede the repair loop"


def test_protection_is_restored_after_the_repair():
    t = _tcl()
    i_repair = t.rindex("repair_antennas")
    i_restore = t.index("setDoNotTouch true")
    assert i_restore > i_repair, "restore must follow the repair loop"
    assert t.index("ANTENNA_SPARE_TIE_REPROTECTED") < t.index(
        "ANTENNA_POSTROUTE_DONE")


# ── NO-LEAK: the relaxation must stay scoped, bounded and self-limited ───────

def test_only_the_spare_tie_nets_are_ever_unprotected():
    """No other net may be unprotected — the relaxation is a CLOSED-set window.

    r4 — the tie nets are one per spare, so the set is no longer spellable as a
    literal. It is still CLOSED: `_spare_tie_nets` is the list the spare tie-off
    block itself appended to, one entry per spare it actually created a net for,
    plus the literal `spare_tiehi` that nothing creates today. The property this
    test defends is unchanged — the window may never widen to "every net" — and
    it is checked two ways: the iterated expression names only those two sources,
    and nothing in the fragment enumerates the block's nets.
    """
    t = _tcl()
    lifted = re.findall(r"foreach\s+_astn\s+(\S+|\[[^\n]*?\])\s*\{", t)
    assert lifted, "the unprotect loop must iterate an explicit net list"
    src = lifted[0]
    assert src == "[concat $_spare_tie_nets [list spare_tiehi]]", src
    # NO-LEAK: the window must never be derived by walking the whole block.
    assert "getNets" not in t, (
        "the unprotect window must not enumerate every net in the block")


def test_no_instance_protection_is_lifted():
    """Spare INSTANCES stay dont_touch — only nets are in the window."""
    t = _tcl()
    assert "unset_dont_touch" not in t, (
        "the antenna window must not lift INSTANCE protection")


def test_restore_is_outside_the_repair_branch():
    """A `break` inside the loop must not skip the restore."""
    t = _tcl()
    # the restore loop must come after the closing of the else-branch that
    # holds the repair loop, i.e. after the last `check_antennas`
    i_last_check = t.rindex("check_antennas")
    assert t.index("foreach _astn $_ant_unprot") > i_last_check


def test_restore_only_touches_what_was_lifted():
    """Iterating `$_ant_unprot` — never the literal list — on the way out."""
    t = _tcl()
    tail = t[t.index("ANTENNA_POSTROUTE_CHECK_NONFATAL"):]
    assert "foreach _astn $_ant_unprot" in tail
    assert "[list spare_tielo spare_tiehi]" not in tail


def test_unprotect_is_conditional_on_being_protected():
    """A net that was never dont_touch is not recorded as lifted."""
    t = _tcl()
    assert "isDoNotTouch" in t


# ── the FIRM-lock leak the flow's own post-fill gate caught (iter4) ──────────
#
# The relaxation above let the repair RUN, and OpenROAD's antenna repair
# legalizes its diodes by putting the whole block back to PLACED and re-firming
# only the cells it owns. MEASURED: 7 of 8 FIRM-locked spares came back
# `+ PLACED` in routed.def, and `spare_cell_preservation_check` FAILed post-fill
# with `all_keep_attr_intact: false` / 6 `untagged` — while `survived: 7,
# removed: []`. Nothing was lost; only the LOCK, which is what the DEF `+ FIXED`
# keep-tag is read from. So the window must also snapshot + restore it.

def test_protected_instance_placement_status_is_snapshotted_and_restored():
    t = _tcl()
    assert "ANTENNA_FIRM_SNAPSHOT" in t
    assert "ANTENNA_FIRM_RESTORED" in t
    assert t.index("ANTENNA_FIRM_SNAPSHOT") < t.index("repair_antennas")
    assert t.rindex("repair_antennas") < t.index("ANTENNA_FIRM_RESTORED")


def test_firm_snapshot_is_property_keyed_not_name_keyed():
    """Covers whatever the flow protected, without knowing the names."""
    t = _tcl()
    snap = t[t.index("set _ant_firm {}"):t.index("ANTENNA_FIRM_SNAPSHOT")]
    assert "isDoNotTouch" in snap
    assert "spare_" not in snap, "the snapshot must not key on a name prefix"


def test_firm_restore_only_restores_the_status_it_recorded():
    """NO-LEAK: never promotes an instance to a status it did not hold."""
    t = _tcl()
    tail = t[t.index("ANTENNA_SPARE_TIE_REPROTECTED"):]
    assert "setPlacementStatus [lindex $_ap 1]" in tail, tail[:400]
    assert "setPlacementStatus FIRM" not in tail, (
        "must not hardcode a status — restore what was recorded")
