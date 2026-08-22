#!/usr/bin/env python3
"""#329 delta 3 (salvage #315): re-examine the tie-aware BLOCK condition.

#329 delta 2 (landed) fixed a FALSE BLOCK: DRT-0307 needs a signal net to
actually land on a POWER/GROUND terminal, so only a netlist-PROVEN tie may
fire the blocking pre-route gate; a gap pin nothing drives survives routing
and must merely be reported. Delta 3 asks whether the landed condition is
now too strict or too loose.

MEASURED TOO STRICT, on one input: a macro supply pin the instance names with
an EMPTY connection.

Verilog spells "this port is unconnected" two ways, and they are the same
statement:

    OTP_128X8 u (.VDD(VDD), .VSS(VSS));            # VPP omitted
    OTP_128X8 u (.VDD(VDD), .VSS(VSS), .VPP());    # VPP named, empty

Both load into the OpenROAD DB as an ITerm with NO NET, so neither can ever
produce the signal-net-on-a-power-pin abort. The landed delta 2 gets the
omitted spelling right (reported, not blocked) and got the empty spelling
WRONG: the tie detector compared the connection string against the rail set,
and `""` is not in the rail set, so an absent driver was classified as a
netlist-proven tie and fired the BLOCKING gate. One electrical fact, two
verdicts, decided by punctuation — and the wrong one is the expensive
direction (a gate that stops a run that would have routed).

Measured on origin/main @ a88bedb75 (v1.6.94) before this fix:

    (a) .VPP()     EXPLICITLY UNCONNECTED -> blocking=True   <-- FALSE BLOCK
    (b) .VPP(1'b1) CONSTANT-TIED          -> blocking=True   (correct)
    (c) VPP        OMITTED                -> blocking=False  (correct)

The fix is in the DETECTOR, not the gate, so the informational tie count at
the global-connect emitter stops over-reporting for the same reason.

NOT relaxed, and pinned below: a real constant tie still blocks; a real signal
net still blocks; the gap is still surfaced as a named finding; and the
no-netlist conservative fallback still blocks every gap.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402

_LEF = """
MACRO OTP_128X8
  PIN VDD
    DIRECTION INOUT ; USE POWER ;
  END VDD
  PIN VSS
    DIRECTION INOUT ; USE GROUND ;
  END VSS
  PIN VPP
    DIRECTION INOUT ; USE POWER ;
  END VPP
  PIN D0
    DIRECTION INPUT ; USE SIGNAL ;
  END D0
END OTP_128X8
"""

# The programming rail is NOT declared -> VPP is a gap the gate must judge.
_L21_NO_VPP = {"fields": {
    "power_rails": [{"rail": "VDD / core supply (1.8 V)"}, {"rail": "VSS"}]}}

_NL_EMPTY_CONN = ("module top;\n"
                  "OTP_128X8 u_otp ( .VDD(VDD), .VSS(VSS), .VPP(), .D0(d) );\n"
                  "endmodule\n")
_NL_OMITTED = ("module top;\n"
               "OTP_128X8 u_otp ( .VDD(VDD), .VSS(VSS), .D0(d) );\n"
               "endmodule\n")
_NL_TIED = ("module top;\n"
            "OTP_128X8 u_otp ( .VDD(VDD), .VSS(VSS), .VPP(1'b1), .D0(d) );\n"
            "endmodule\n")
_NL_SIGNAL = ("module top;\n"
              "OTP_128X8 u_otp ( .VDD(VDD), .VSS(VSS), .VPP(n42), .D0(d) );\n"
              "endmodule\n")


class _Pdk:
    def __init__(self, lef_path):
        self.macro_lefs = [str(lef_path)]


def _project(tmp_path, l21=None):
    lef = tmp_path / "otp.lef"
    lef.write_text(_LEF)
    gd = tmp_path / "generated_docs"
    gd.mkdir(exist_ok=True)
    (gd / "L21_POWER_INTENT.json").write_text(
        json.dumps(_L21_NO_VPP if l21 is None else l21))
    return lef


# ── THE DEFECT ───────────────────────────────────────────────────────────────

def test_329d3_empty_connection_is_not_a_tie():
    """Detector level: `.VPP()` binds NO net, so it is not a signal net on a
    POWER terminal. This is the reproduction — RED on origin/main."""
    ties = p3._detect_macro_supply_signal_ties(
        _NL_EMPTY_CONN, [_LEF], {"VDD"}, {"VSS"})
    assert [t["pin"] for t in ties] == []


def test_329d3_empty_connection_does_not_fire_the_blocking_gate(tmp_path):
    """Gate level: the false block itself. Routing survives a supply pin no
    net reaches, so the pre-route gate must not stop the run."""
    lef = _project(tmp_path)
    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef),
                                           netlist_text=_NL_EMPTY_CONN)
    assert d["blocking"] is False
    assert d["gaps"] == []


def test_329d3_the_two_unconnected_spellings_reach_the_same_verdict(tmp_path):
    """The invariant the defect broke: an omitted port and an empty-connection
    port are the SAME statement, so the gate must not decide them differently.
    Compared on the whole decision, not just the boolean."""
    lef = _project(tmp_path)
    empty = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef),
                                               netlist_text=_NL_EMPTY_CONN)
    omitted = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef),
                                                 netlist_text=_NL_OMITTED)
    assert empty == omitted


def test_329d3_unconnected_pin_is_still_reported_never_silent(tmp_path):
    """Not blocking is not the same as not saying anything — the undeclared
    programming rail is still a real integration gap and must stay named."""
    lef = _project(tmp_path)
    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef),
                                           netlist_text=_NL_EMPTY_CONN)
    assert {g["pin"] for g in d["gaps_reported"]} == {"VPP"}


# ── NEGATIVE CONTROLS: the gate is narrowed, not disarmed ────────────────────

def test_329d3_constant_tie_still_blocks(tmp_path):
    lef = _project(tmp_path)
    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef),
                                           netlist_text=_NL_TIED)
    assert d["blocking"] is True
    assert {g["pin"] for g in d["gaps"]} == {"VPP"}


def test_329d3_a_real_signal_net_still_blocks(tmp_path):
    """The general case behind DRT-0307: an ordinary signal net landing on a
    POWER terminal. Nothing about the empty-connection fix may reach it."""
    lef = _project(tmp_path)
    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef),
                                           netlist_text=_NL_SIGNAL)
    assert d["blocking"] is True
    assert {g["pin"] for g in d["gaps"]} == {"VPP"}


def test_329d3_detector_still_flags_the_tie_and_the_signal():
    tied = p3._detect_macro_supply_signal_ties(
        _NL_TIED, [_LEF], {"VDD"}, {"VSS"})
    assert {(t["pin"], t["conn"]) for t in tied} == {("VPP", "1'b1")}
    sig = p3._detect_macro_supply_signal_ties(
        _NL_SIGNAL, [_LEF], {"VDD"}, {"VSS"})
    assert {(t["pin"], t["conn"]) for t in sig} == {("VPP", "n42")}


def test_329d3_no_netlist_keeps_the_conservative_block(tmp_path):
    """Without a netlist the tie is unprovable either way; the strict
    pre-#329 fallback must survive this narrowing untouched."""
    lef = _project(tmp_path)
    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef))
    assert d["blocking"] is True
    assert {g["pin"] for g in d["gaps"]} == {"VPP"}


def test_329d3_a_pin_wired_to_a_declared_rail_is_still_clean(tmp_path):
    """An empty connection must not become a way to mask a MIS-wire: a pin
    genuinely wired to a rail stays non-blocking for the RIGHT reason."""
    lef = _project(tmp_path)
    nl = ("module top;\n"
          "OTP_128X8 u_otp ( .VDD(VDD), .VSS(VSS), .VPP(VDD) );\n"
          "endmodule\n")
    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef),
                                           netlist_text=nl)
    assert d["blocking"] is False
    assert {g["pin"] for g in d["gaps_reported"]} == {"VPP"}


def test_329d3_whitespace_only_connection_counts_as_unconnected():
    """`.VPP( )` is the same statement with a space in it."""
    nl = ("module top;\n"
          "OTP_128X8 u_otp ( .VDD(VDD), .VSS(VSS), .VPP( ) );\n"
          "endmodule\n")
    assert p3._detect_macro_supply_signal_ties(
        nl, [_LEF], {"VDD"}, {"VSS"}) == []
