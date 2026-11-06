"""TF24 — a post-route session that INSERTS cells must connect their supply,
and a candidate whose supply pins are not all on a declared supply net is
never promoted.

MEASURED (spm x gf180mcuD, vibeic-eda 0.3.79, pure direct flow; lane mig98
arm D, reproduced by lane migf24 on the same pre-repair DEF): the post-route
`signoff_spef_repair` session re-opens `routed.def` (VDD `( * VNW ) ( * VDD )`),
removes the fillers, inserts 15 + 1 `hold*` buffers, re-routes, re-fills and
writes `routed_repaired.def` — with VDD reduced to `( * DVDD )` plus an
explicit list that names neither the 16 buffers nor any refilled filler:
57,320 of 86,016 supply pins on no net. The step promoted it over
`routed.def`. The session registered no `add_global_connection` rule (they are
session state, not DEF) and never ran `global_connect`.

With the deck's own rules registered after `read_def` and applied before the
write, the same session on the same DEF writes `( * VNW ) ( * VDD )` again,
0 of 86,016 unowned, and the NETS section (every signal wire) is
byte-identical to the unfixed run: setup +1.486 ns / hold +0.091 ns both ways.

chip-AGNOSTIC: fixture nets are PWRNET / GNDNET; the calibration pair is the
registry's own real OpenROAD output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pg_supply_pin_ownership_check as G  # noqa: E402

CAL = PROGRAMS / "calibration"
CAL_LEF = CAL / "pg_supply_buf_1.lef"
CAL_POS = CAL / "pg_supply_unowned_positive.def"
CAL_NEG = CAL / "pg_supply_owned_negative.def"

DECK = """\
puts "PNR_BEGIN"
if {[catch {
  add_global_connection -net PWRNET -pin_pattern "^PWR$" -power
  add_global_connection -net GNDNET -pin_pattern "^GND$" -ground
  global_connect
  pdngen
} err]} { puts "PDN_FAILED: $err" }
detailed_route
"""

LEF = """\
MACRO BUFX
  CLASS CORE ;
  PIN A
    DIRECTION INPUT ;
  END A
  PIN PWR
    DIRECTION INOUT ;
    USE POWER ;
  END PWR
  PIN GND
    DIRECTION INOUT ;
    USE GROUND ;
  END GND
END BUFX
MACRO SPACER
  CLASS CORE SPACER ;
END SPACER
"""


def _def(components: str, specialnets: str, nets: str = "") -> str:
    ncomp = components.count(";")
    nsn = specialnets.count(";")
    nn = nets.count(";")
    return (f"VERSION 5.8 ;\nDESIGN t ;\nUNITS DISTANCE MICRONS 1000 ;\n"
            f"COMPONENTS {ncomp} ;\n{components}END COMPONENTS\n"
            f"SPECIALNETS {nsn} ;\n{specialnets}END SPECIALNETS\n"
            f"NETS {nn} ;\n{nets}END NETS\nEND DESIGN\n")


# ── the gate ────────────────────────────────────────────────────────────────



def test_the_real_pair_names_the_inserted_instance():
    rec = G.judge(CAL_POS.read_text(), [CAL_LEF.read_text()])
    assert rec["verdict"] == "FAIL" and rec["code"] == G.REFUSE_CODE
    assert {o["instance"] for o in rec["off_supply_examples"]} == {"hold1"}
    assert rec["off_supply_pins"] == 4
    neg = G.judge(CAL_NEG.read_text(), [CAL_LEF.read_text()])
    assert neg["verdict"] == "PASS", neg


def test_wildcard_ownership_passes_and_explicit_omission_fails():
    comps = "- u0 BUFX + PLACED ( 0 0 ) N ;\n- ins1 BUFX + PLACED ( 9 0 ) N ;\n"
    wild = ("- PWRNET ( * PWR ) + USE POWER ;\n"
            "- GNDNET ( * GND ) + USE GROUND ;\n")
    assert G.judge(_def(comps, wild), [LEF])["verdict"] == "PASS"
    explicit = ("- PWRNET ( u0 PWR ) + USE POWER ;\n"
                "- GNDNET ( u0 GND ) + USE GROUND ;\n")
    rec = G.judge(_def(comps, explicit), [LEF])
    assert rec["verdict"] == "FAIL"
    assert rec["off_supply_breakdown"]["no_net"] == 2
    assert {o["instance"] for o in rec["off_supply_examples"]} == {"ins1"}


def test_routing_points_after_the_first_plus_are_not_connections():
    comps = "- u0 BUFX + PLACED ( 0 0 ) N ;\n"
    # `( u0 PWR )` appears only as a routing coordinate pair after `+ ROUTED`.
    sn = ("- PWRNET + USE POWER + ROUTED Metal1 100 ( u0 PWR ) ( 5 0 ) ;\n"
          "- GNDNET ( * GND ) + USE GROUND ;\n")
    rec = G.judge(_def(comps, sn), [LEF])
    assert rec["verdict"] == "FAIL"
    assert rec["off_supply_examples"][0]["pin"] == "PWR"


def test_a_power_pin_on_the_ground_net_is_refused():
    comps = "- u0 BUFX + PLACED ( 0 0 ) N ;\n"
    sn = ("- PWRNET ( * GND ) + USE POWER ;\n"
          "- GNDNET ( * PWR ) + USE GROUND ;\n")
    rec = G.judge(_def(comps, sn), [LEF])
    assert rec["verdict"] == "FAIL"
    assert rec["off_supply_breakdown"]["wrong_kind"] == 2


def test_a_supply_pin_on_a_signal_net_is_refused():
    comps = "- u0 BUFX + PLACED ( 0 0 ) N ;\n"
    sn = "- GNDNET ( * GND ) + USE GROUND ;\n"
    nets = "- tie ( u0 PWR ) ( u0 A ) + USE SIGNAL ;\n"
    rec = G.judge(_def(comps, sn, nets), [LEF])
    assert rec["verdict"] == "FAIL"
    assert rec["off_supply_breakdown"]["not_a_supply_net"] == 1


def test_an_unread_master_is_unmeasured_never_clean():
    comps = "- u0 BUFX + PLACED ( 0 0 ) N ;\n- m0 MYSTERY + PLACED ( 9 0 ) N ;\n"
    sn = ("- PWRNET ( * PWR ) + USE POWER ;\n"
          "- GNDNET ( * GND ) + USE GROUND ;\n")
    rec = G.judge(_def(comps, sn), [LEF])
    assert rec["verdict"] == "NOT_MEASURED"
    assert rec["code"] == G.UNMEASURED_CODE
    assert rec["unknown_masters"] == {"MYSTERY": 1}


def test_a_proven_failure_outranks_an_unmeasured_remainder():
    comps = "- u0 BUFX + PLACED ( 0 0 ) N ;\n- m0 MYSTERY + PLACED ( 9 0 ) N ;\n"
    sn = "- GNDNET ( * GND ) + USE GROUND ;\n- PWRNET + USE POWER ;\n"
    assert G.judge(_def(comps, sn), [LEF])["verdict"] == "FAIL"


def test_no_declared_supply_net_is_unmeasured():
    comps = "- u0 SPACER + PLACED ( 0 0 ) N ;\n"
    rec = G.judge(_def(comps, ""), [LEF])
    assert rec["verdict"] == "NOT_MEASURED"


def test_cli_exit_codes_and_record(tmp_path):
    out = tmp_path / "r.json"
    assert G.main([str(CAL_POS), "--lef", str(CAL_LEF), "--json", str(out)]) == 1
    assert json.loads(out.read_text())["code"] == G.REFUSE_CODE
    assert G.main([str(CAL_NEG), "--lef", str(CAL_LEF)]) == 0
    assert G.main([str(tmp_path / "absent.def"), "--lef", str(CAL_LEF)]) == 2


# ── the producers ───────────────────────────────────────────────────────────











# ── the promotion refusal, driven through the real step ─────────────────────
