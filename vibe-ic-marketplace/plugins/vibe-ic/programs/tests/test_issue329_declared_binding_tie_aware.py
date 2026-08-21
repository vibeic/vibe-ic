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

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import hardmacro_supply_intent as H  # noqa: E402
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

_L21_MAPPED = {"fields": {
    "power_rails": [{"rail": "VDD / core supply (1.8 V)"}, {"rail": "VSS"},
                    {"rail": "VPP_PROG"}],
    "hard_macro_supplies": [{"master": "OTP_128X8", "pin": "VPP",
                             "rail": "VPP_PROG"}]}}


class _Pdk:
    def __init__(self, lef_path):
        self.macro_lefs = [str(lef_path)]


def _project(tmp_path, l21):
    lef = tmp_path / "otp.lef"
    lef.write_text(_LEF)
    gd = tmp_path / "generated_docs"
    gd.mkdir(exist_ok=True)
    (gd / "L21_POWER_INTENT.json").write_text(json.dumps(l21))
    return lef


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


def test_329_the_split_reproduced_gate_accepts_but_old_plan_never_binds(
        tmp_path):
    """THE defect: the gate accepts the mapped pin (non-blocking), yet the
    physical plan WITHOUT the map leaves that same pin unbound — the accepted
    pin ships constant-tied. Both halves of the split, measured."""
    lef = _project(tmp_path, _L21_MAPPED)
    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef))
    assert d is not None and d["blocking"] is False      # gate: accounted
    connect, unconn = p3._macro_supply_gc_plan(
        [_LEF], ["VDD"], ["VSS"])                        # pre-fix plan shape
    assert "VPP" not in {c["pin"] for c in connect}      # ...but never bound
    assert "VPP" in {u["pin"] for u in unconn}


def test_329_declared_map_closes_the_split(tmp_path):
    connect, unconn = p3._macro_supply_gc_plan(
        [_LEF], ["VDD"], ["VSS"],
        declared_map={("OTP_128X8", "VPP"): "VPP_PROG"})
    vpp = next(c for c in connect if c["pin"] == "VPP")
    assert vpp["rail"] == "VPP_PROG"                     # the DECLARED rail
    assert "VPP" not in {u["pin"] for u in unconn}


def test_329_name_equality_keeps_precedence_over_the_map():
    """A pin whose name IS a rail must keep its rail==pin binding even if a
    (redundant) mapping exists — prior plans byte-stable."""
    connect, _ = p3._macro_supply_gc_plan(
        [_LEF], ["VDD"], ["VSS"],
        declared_map={("OTP_128X8", "VDD"): "SOMETHING_ELSE"})
    vdd = next(c for c in connect if c["pin"] == "VDD")
    assert vdd["rail"] == "VDD"


def test_329_no_map_is_byte_identical_to_before():
    a = p3._macro_supply_gc_plan([_LEF], ["VDD"], ["VSS"])
    b = p3._macro_supply_gc_plan([_LEF], ["VDD"], ["VSS"], declared_map={})
    assert a == b


def test_329_emitter_emits_the_declared_rail():
    connect, unconn = p3._macro_supply_gc_plan(
        [_LEF], ["VDD"], ["VSS"],
        declared_map={("OTP_128X8", "VPP"): "VPP_PROG"})
    tcl = p3._build_hardmacro_supply_gc_tcl(connect, unconn)
    assert "add_global_connection -net VPP_PROG" in tcl
    assert '-pin_pattern "^VPP\\$"' in tcl


# ── delta 2: tie-aware block condition ───────────────────────────────────────

_L21_NO_VPP = {"fields": {
    "power_rails": [{"rail": "VDD / core supply (1.8 V)"}, {"rail": "VSS"}]}}

_NL_TIED = ("module top;\n"
            "OTP_128X8 u_otp ( .VPP(1'b1), .VDD(VDD), .VSS(VSS), .D0(d) );\n"
            "endmodule\n")
_NL_UNDRIVEN = ("module top;\n"
                "OTP_128X8 u_otp ( .VDD(VDD), .VSS(VSS), .D0(d) );\n"
                "endmodule\n")


def test_329_netlist_proven_tie_blocks(tmp_path):
    lef = _project(tmp_path, _L21_NO_VPP)
    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef),
                                           netlist_text=_NL_TIED)
    assert d["blocking"] is True
    assert {g["pin"] for g in d["gaps"]} == {"VPP"}
    assert "netlist-proven" in d["message"]


def test_329_undriven_gap_is_reported_not_blocked(tmp_path):
    """Routing survives an undriven supply pin — blocking it is a false
    block. It must still be surfaced as a NAMED finding (never silent)."""
    lef = _project(tmp_path, _L21_NO_VPP)
    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef),
                                           netlist_text=_NL_UNDRIVEN)
    assert d["blocking"] is False
    assert {g["pin"] for g in d["gaps_reported"]} == {"VPP"}
    assert d["gaps"] == []


def test_329_without_a_netlist_the_strict_pre329_block_is_kept(tmp_path):
    """No netlist -> the tie is unprovable either way -> conservative
    fallback, NOT a silent relaxation."""
    lef = _project(tmp_path, _L21_NO_VPP)
    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef))
    assert d["blocking"] is True
    assert {g["pin"] for g in d["gaps"]} == {"VPP"}


def test_329_a_gap_pin_wired_to_an_established_rail_is_not_a_tie(tmp_path):
    """Netlist already wires the undeclared pin to a real rail (VDD): not a
    signal-on-power tie, so no block — but the L21 gap is still reported."""
    lef = _project(tmp_path, _L21_NO_VPP)
    nl = ("module top;\n"
          "OTP_128X8 u_otp ( .VPP(VDD), .VDD(VDD), .VSS(VSS) );\n"
          "endmodule\n")
    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef),
                                           netlist_text=nl)
    assert d["blocking"] is False
    assert {g["pin"] for g in d["gaps_reported"]} == {"VPP"}


def test_329_tie_findings_carry_the_master_for_joining():
    ties = p3._detect_macro_supply_signal_ties(
        _NL_TIED, [_LEF], {"VDD"}, {"VSS"})
    assert ties and all(t["master"] == "OTP_128X8" for t in ties)


# ── delta 3: env-blind safety ────────────────────────────────────────────────

def test_329_env_blind_never_fires_the_blocking_gate(tmp_path):
    """Nothing declared AND nothing measured: 'no rail' is indistinguishable
    from 'rails unreadable here'. The uncertain bucket must not auto-trigger
    the blocking arm — but it must be LOUD."""
    lef = _project(tmp_path, {"fields": {}})
    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef),
                                           netlist_text=_NL_TIED)
    assert d["blocking"] is False
    assert d["env_blind"] is True
    assert "ENV-BLIND" in d["message"]
    assert {g["pin"] for g in d["gaps_reported"]} == {"VDD", "VSS", "VPP"}


def test_329_first_run_with_visible_pdk_rails_is_NOT_env_blind(tmp_path):
    """THE #309 regression guard for env-blindness. #348 measured 27/30 real
    designs with empty structured L21, and a FIRST run has no DEF yet — so
    'L21+DEF empty' is the NORMAL state of the very design #309 blocks. If
    that state counted as env-blind, the gate would silently disarm on
    first runs. The witness must be the PDK supply nets: visible PDK rails
    + a proven tie => still BLOCKS."""
    lef = _project(tmp_path, {"fields": {}})   # empty L21, no DEF anywhere

    class _PdkSky(_Pdk):
        tapcell_master = "sky130_fd_sc_hd__tapvpwrvgnd_1"

    d = p3._macro_supply_preroute_decision(tmp_path, _PdkSky(lef),
                                           netlist_text=_NL_TIED)
    assert not d.get("env_blind")
    assert d["blocking"] is True
    # VPP is netlist-tied to 1'b1 -> fatal; VDD/VSS are wired to nets named
    # like rails but NOT the PDK's VPWR/VGND -> also gaps here, also tied.
    assert "VPP" in {g["pin"] for g in d["gaps"]}


def test_329_a_pin_wired_to_the_pdk_rail_is_not_a_tie(tmp_path):
    """A pin the netlist already wires to the PDK supply net (VPWR) is not a
    signal-on-power tie — the PDK nets belong in the whitelist."""
    lef = _project(tmp_path, {"fields": {}})

    class _PdkSky(_Pdk):
        tapcell_master = "sky130_fd_sc_hd__tapvpwrvgnd_1"

    nl = ("module top;\n"
          "OTP_128X8 u_otp ( .VPP(VPWR), .VDD(VPWR), .VSS(VGND) );\n"
          "endmodule\n")
    d = p3._macro_supply_preroute_decision(tmp_path, _PdkSky(lef),
                                           netlist_text=nl)
    assert d["blocking"] is False
    assert {g["pin"] for g in d["gaps_reported"]} == {"VDD", "VSS", "VPP"}


def test_329_one_measured_rail_lifts_the_blindness(tmp_path):
    """A DEF SPECIALNETS rail proves the environment CAN see rails — the
    normal tie-aware path applies again and the proven tie blocks."""
    lef = _project(tmp_path, {"fields": {}})
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    # A ROUTED shape, not a bare connect-all-by-name. #668 made
    # `measured_rails()` count only rails the PDN actually BUILT — a
    # `- VDD ( * VDD ) + USE POWER ;` with no stripe, via or followpin is a name
    # and nothing else, and this fixture predates that distinction. What it
    # means to say is "a rail was MEASURED", so it now carries the conductor
    # that makes that true.
    (pnr / "routed.def").write_text(
        "SPECIALNETS 2 ;\n"
        "- VDD ( * VDD ) + USE POWER\n"
        "  + ROUTED met4 1600 + SHAPE STRIPE ( 1000 0 ) ( 1000 20000 ) ;\n"
        "- VSS ( * VSS ) + USE GROUND\n"
        "  + ROUTED met4 1600 + SHAPE STRIPE ( 2000 0 ) ( 2000 20000 ) ;\n"
        "END SPECIALNETS\n")
    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk(lef),
                                           netlist_text=_NL_TIED)
    if d.get("env_blind"):
        raise AssertionError("measured rail did not lift env-blindness — "
                             "check measured_rails() DEF discovery path")
    assert d["blocking"] is True
    assert {g["pin"] for g in d["gaps"]} == {"VPP"}
