"""Phase-3 pre-route hard-macro supply decision: DESIGN-DECLARED binding + the
BLOCKING finding that must fire BEFORE detailed routing.

DEFECT (chip-AGNOSTIC, restated): a hard macro types a supply pin USE POWER /
USE GROUND in its own LEF; the RTL constant-ties it, so synthesis lands a SIGNAL
net (TIEHI/TIELO) on a POWER/GROUND terminal. If that pin matches NO supply rail
the design declares, OpenROAD's detailed router refuses the whole design and
aborts mid-route (DRT-0307) — every signal net ends up unrouted. The honest
behavior is to STOP before routing with a NAMED finding (macro/pin/net), not to
let TritonRoute crash five steps deep.

Two things this suite pins:
  1. DESIGN-DECLARED MAPPING — when L21 hard_macro_supplies binds a macro pin to
     a declared rail (even with a different name), the flow BINDS it (the design
     says so); the pin is then NOT blocking.
  2. BLOCKING — a signal-tied POWER/GROUND pin that no rail (name-match OR
     declared mapping) can bind is returned as a BLOCKING finding before route.

NEGATIVE CONTROL (bidirectional): the unbindable signal-tied pin BLOCKS; once the
design declares a real rail for it (or a rail name-matches), it BINDS and does
NOT block. All fixtures synthetic + neutral.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")


# Neutral macro: P_CORE/G_CORE match the design rails by name; P_PROG is a
# dedicated supply the design carries no rail for.
NEUTRAL_LEF = """VERSION 5.8 ;
MACRO NEUTRAL_MACRO
  CLASS BLOCK ;
  SIZE 20 BY 20 ;
  PIN P_CORE
    DIRECTION INOUT ;
    USE POWER ;
  END P_CORE
  PIN G_CORE
    DIRECTION INOUT ;
    USE GROUND ;
  END G_CORE
  PIN P_PROG
    DIRECTION INPUT ;
    USE POWER ;
    SHAPE FEEDTHRU ;
  END P_PROG
END NEUTRAL_MACRO
END LIBRARY
"""

# Netlist that constant-ties ALL three supply pins (the exact synthesis outcome
# that lands a signal net on a power pin). P_CORE/G_CORE will re-bind by name;
# P_PROG has no rail -> the routing-crash defect.
NETLIST = """module top (input a, output y);
  wire w;
  NEUTRAL_MACRO u0 (
    .P_CORE(1'b1),
    .G_CORE(1'b0),
    .P_PROG(1'b1),
    .A(a)
  );
  assign y = w;
endmodule
"""

POWER = {"P_CORE"}
GROUND = {"G_CORE"}


class TestSignalTieCarriesMaster:
    def test_detector_reports_master(self):
        ties = R._detect_macro_supply_signal_ties(
            NETLIST, [NEUTRAL_LEF], POWER, GROUND)
        for t in ties:
            assert t.get("master") == "NEUTRAL_MACRO"
        assert {t["pin"] for t in ties} >= {"P_CORE", "G_CORE", "P_PROG"}


class TestDeclaredMappingBinds:
    def test_declared_rail_binds_even_when_name_differs(self):
        # The design declares P_PROG -> P_IO (a real rail). The flow must bind
        # it, NOT invent and NOT leave it unconnected.
        connect, unconn = R._macro_supply_gc_plan(
            [NEUTRAL_LEF], POWER | {"P_IO"}, GROUND,
            declared_map={("NEUTRAL_MACRO", "P_PROG"): {"rail": "P_IO"}})
        by_pin = {c["pin"]: c["rail"] for c in connect}
        assert by_pin.get("P_PROG") == "P_IO"
        assert "P_PROG" not in {u["pin"] for u in unconn}

    def test_declared_rail_not_a_real_rail_is_not_bound(self):
        # A declared rail that is NOT among the design's actual rails cannot be
        # physically bound -> not connected (honest), never fabricated.
        connect, unconn = R._macro_supply_gc_plan(
            [NEUTRAL_LEF], POWER, GROUND,
            declared_map={("NEUTRAL_MACRO", "P_PROG"): {"rail": "PHANTOM"}})
        assert "P_PROG" not in {c["pin"] for c in connect}
        assert "P_PROG" in {u["pin"] for u in unconn}

    def test_backward_compatible_without_map(self):
        connect, _ = R._macro_supply_gc_plan([NEUTRAL_LEF], POWER, GROUND)
        assert {c["pin"] for c in connect} == {"P_CORE", "G_CORE"}


class TestPreRouteDecisionBlocking:
    def test_unbindable_signal_tie_blocks(self):
        # NEGATIVE CONTROL (defect present): P_PROG is signal-tied and no rail
        # binds it -> it MUST be a blocking finding before route.
        dec = R._macro_supply_preroute_decision(
            NETLIST, [NEUTRAL_LEF], POWER, GROUND, declared_map={})
        blk = {(b["master"], b["pin"]) for b in dec["blocking"]}
        assert blk == {("NEUTRAL_MACRO", "P_PROG")}
        # the blocking finding names the net it is tied to (for the report).
        pb = next(b for b in dec["blocking"] if b["pin"] == "P_PROG")
        assert pb["conn"] == "1'b1"
        # the bindable pins are in connect, NOT blocking.
        assert {c["pin"] for c in dec["connect"]} == {"P_CORE", "G_CORE"}

    def test_declaring_a_real_rail_clears_the_block(self):
        # NEGATIVE CONTROL (defect resolved): declare P_PROG -> P_IO -> binds,
        # no longer blocks.
        dec = R._macro_supply_preroute_decision(
            NETLIST, [NEUTRAL_LEF], POWER | {"P_IO"}, GROUND,
            declared_map={("NEUTRAL_MACRO", "P_PROG"): {"rail": "P_IO"}})
        assert dec["blocking"] == []
        assert "P_PROG" in {c["pin"] for c in dec["connect"]}

    def test_name_match_never_blocks(self):
        # If every supply pin name-matches a rail, nothing blocks even when all
        # are constant-tied (they all re-bind).
        nl = NETLIST.replace(".P_PROG(1'b1)", ".P_PROG(P_CORE)")
        dec = R._macro_supply_preroute_decision(
            nl, [NEUTRAL_LEF], POWER, GROUND, declared_map={})
        assert dec["blocking"] == []

    def test_floating_norail_pin_is_reported_not_blocked(self):
        # A no-rail pin that is NOT signal-tied (left unconnected in the
        # netlist) does not crash routing -> honest report, not a block.
        nl = NETLIST.replace(".P_PROG(1'b1),\n", "")
        dec = R._macro_supply_preroute_decision(
            nl, [NEUTRAL_LEF], POWER, GROUND, declared_map={})
        assert dec["blocking"] == []
        assert "P_PROG" in {u["pin"] for u in dec["unconnected"]}

    def test_no_macro_pins_is_empty(self):
        dec = R._macro_supply_preroute_decision(
            "module m(); endmodule\n", ["VERSION 5.8 ;\n"],
            set(), set(), declared_map={})
        assert dec["blocking"] == [] and dec["connect"] == []

    def test_empty_rail_set_never_blocks_env_safety(self):
        # If the design's rails could not be discovered (empty rail set — e.g.
        # the PDK cell LEF was unreadable in this environment), we are BLIND and
        # must NOT block: a normally-connected supply pin would otherwise be
        # mis-flagged. Falls back to the passive unconnected report.
        dec = R._macro_supply_preroute_decision(
            NETLIST, [NEUTRAL_LEF], set(), set(), declared_map={})
        assert dec["blocking"] == []
        # all three supply pins land in the honest unconnected report instead.
        assert {u["pin"] for u in dec["unconnected"]} == {
            "P_CORE", "G_CORE", "P_PROG"}

    def test_ground_blindness_does_not_block_ground_but_power_still_can(self):
        # power rails known, ground rails empty: a tied unbindable POWER pin
        # blocks, a tied GROUND pin does not (blind on ground).
        dec = R._macro_supply_preroute_decision(
            NETLIST, [NEUTRAL_LEF], {"P_CORE"}, set(), declared_map={})
        blk = {b["pin"] for b in dec["blocking"]}
        assert "G_CORE" not in blk
        assert "P_PROG" in blk
