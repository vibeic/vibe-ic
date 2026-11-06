#!/usr/bin/env python3
"""#329 deltas (harvested via #349) on the #309/#348 hard-macro supply gate.

Three deltas, each a measured hole in the landed #309 implementation:

1. DECLARED-MAP PHYSICAL BINDING — the pre-route GATE accepted an explicit
   L21 mapping ((master,pin)->rail with differing names) as accounted-for,
   but the PHYSICAL emitter (`_macro_supply_gc_plan`) bound only
   name-equality pins. The accepted pin then arrived at routing still
   constant-tied: the exact DRT-0307 the gate exists to prevent — a
   producer/consumer split INSIDE one feature (gate says bound, emitter
   never binds).

2. TIE-AWARE BLOCK CONDITION — DRT-0307 needs a SIGNAL NET actually landing
   on the POWER/GROUND terminal. A gap pin nothing drives survives routing;
   blocking it is a false block. Block only netlist-proven ties; report the
   rest loudly. Without a netlist the strict pre-#329 behaviour is kept.

3. ENV-SAFETY (`env_blind`) — when NO rail is established at all (nothing
   declared, nothing measured) "no rail for this pin" is indistinguishable
   from "rails unreadable in this environment"; an environment blindness
   must not fire a BLOCKING gate (classifier three-tier doctrine). Loud,
   never silently green.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import hardmacro_supply_intent as H  # noqa: E402

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

_L21_MAPPED = {"fields": {
    "power_rails": [{"rail": "VDD / core supply (1.8 V)"}, {"rail": "VSS"},
                    {"rail": "VPP_PROG"}],
    "hard_macro_supplies": [{"master": "OTP_128X8", "pin": "VPP",
                             "rail": "VPP_PROG"}]}}






# ── delta 1: declared-map physical binding ───────────────────────────────────

def test_329_declared_binding_map_honors_established_rails_only():
    m = H.declared_binding_map(_L21_MAPPED, ["VPP_PROG", "VDD", "VSS"])
    assert m == {("OTP_128X8", "VPP"): "VPP_PROG"}


def test_329_declared_binding_map_anticheat_ghost_rail_excluded():
    """A mapping to a rail NOBODY establishes must not reach the emitter —
    honoring it would let a document fabricate a rail (same anti-cheat
    boundary as classify_pin's rail_undeclared)."""
    l21 = {"fields": {"hard_macro_supplies": [
        {"master": "OTP_128X8", "pin": "VPP", "rail": "VPP_GHOST"}]}}
    assert H.declared_binding_map(l21, ["VDD", "VSS"]) == {}


def test_329_declared_binding_map_skips_acknowledged_gaps():
    l21 = {"fields": {"hard_macro_supplies": [
        {"master": "OTP_128X8", "pin": "VPP", "integration_gap": True}]}}
    assert H.declared_binding_map(l21, ["VDD", "VSS", "VPP"]) == {}












# ── delta 2: tie-aware block condition ───────────────────────────────────────

_L21_NO_VPP = {"fields": {
    "power_rails": [{"rail": "VDD / core supply (1.8 V)"}, {"rail": "VSS"}]}}

_NL_TIED = ("module top;\n"
            "OTP_128X8 u_otp ( .VPP(1'b1), .VDD(VDD), .VSS(VSS), .D0(d) );\n"
            "endmodule\n")
_NL_UNDRIVEN = ("module top;\n"
                "OTP_128X8 u_otp ( .VDD(VDD), .VSS(VSS), .D0(d) );\n"
                "endmodule\n")












# ── delta 3: env-blind safety ────────────────────────────────────────────────
