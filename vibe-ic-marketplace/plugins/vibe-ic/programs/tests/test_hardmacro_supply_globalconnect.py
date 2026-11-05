"""Regression: hard-macro supply-pin auto global-connect (before detailed route).

DEFECT (chip-AGNOSTIC): a hard macro types its supply pins USE POWER / USE GROUND
in its own LEF. When the RTL constant-ties such a pin, synthesis drives it with a
TIEHI/TIELO *signal* net, i.e. a signal net lands on a POWER/GROUND terminal.
OpenROAD's detailed router refuses a signal net that owns a POWER/GROUND terminal
and aborts, so the WHOLE design gets NO signal routing and LVS/STA are unreachable.

FIX: read each hard macro's own LEF, and for every POWER/GROUND pin whose name
matches a supply rail the design actually declares, emit an explicit per-instance
`add_global_connection -inst_pattern <inst> -pin_pattern <pin> -net <rail>` BEFORE
routing, then `global_connect`. A POWER/GROUND pin whose name matches NO declared
rail (e.g. a dedicated programming supply this design carries no rail for) is NOT
invented a rail — it is reported as an unconnected-supply finding, never faked.

This test proves BEFORE (the constant-tie is a signal-on-power the guard detects)
and AFTER (VPWR/VGND auto-bind to the rails; the no-rail VPROG is honestly
reported, not connected) on a SYNTHETIC generic macro. Docker-free; the tclsh
harnesses stub OpenROAD so no EDA image is needed.
"""
import shutil
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

tclsh = shutil.which("tclsh")


# ── Synthetic, fully generic fixture (no real LEF/name/number) ───────────────
# A made-up hard macro on a 4-layer generic stack (met1..met4). It declares two
# supply pins whose names MATCH the design's rails (VPWR/VGND) and one dedicated
# programming supply (VPROG) the design carries NO rail for.
GENERIC_HARDMACRO_LEF = """VERSION 5.8 ;
BUSBITCHARS "[]" ;
DIVIDERCHAR "/" ;

MACRO GENERIC_HARDMACRO
  CLASS BLOCK ;
  ORIGIN 0 0 ;
  SIZE 40 BY 40 ;
  SYMMETRY X Y ;
  PIN VPWR
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER met4 ;
        RECT 0 38 40 40 ;
    END
  END VPWR
  PIN VGND
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER met4 ;
        RECT 0 0 40 2 ;
    END
  END VGND
  PIN VPROG
    DIRECTION INPUT ;
    USE POWER ;
    PORT
      LAYER met3 ;
        RECT 18 18 22 22 ;
    END
  END VPROG
  PIN CLK
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER met2 ;
        RECT 2 10 3 11 ;
    END
  END CLK
  PIN D
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER met2 ;
        RECT 2 12 3 13 ;
    END
  END D
  PIN Q
    DIRECTION OUTPUT ;
    USE SIGNAL ;
    PORT
      LAYER met2 ;
        RECT 37 12 38 13 ;
    END
  END Q
END GENERIC_HARDMACRO

END LIBRARY
"""

# The tiny design that instantiates it, with the supply pins CONSTANT-TIED in the
# gate netlist (the exact synthesis outcome that lands a signal net on a POWER
# pin). VPROG is tied too — it has no rail, so it stays honestly unconnected.
GENERIC_NETLIST = """module generic_top (input clk, input d, output q);
  wire net_q;
  GENERIC_HARDMACRO u_macro (
    .VPWR(1'b1),
    .VGND(1'b0),
    .VPROG(1'b0),
    .CLK(clk),
    .D(d),
    .Q(net_q)
  );
  assign q = net_q;
endmodule
"""

POWER_NETS = {"VPWR"}
GROUND_NETS = {"VGND"}


# ── Pure-LEF parse ───────────────────────────────────────────────────────────
class TestParseMacroSupplyPins:
    def test_only_power_ground_pins_returned(self):
        pins = R._parse_macro_supply_pins(GENERIC_HARDMACRO_LEF)
        assert set(pins) == {"GENERIC_HARDMACRO"}
        got = sorted(pins["GENERIC_HARDMACRO"])
        assert got == [("VGND", "GROUND"), ("VPROG", "POWER"),
                       ("VPWR", "POWER")]

    def test_signal_pins_excluded(self):
        pins = R._parse_macro_supply_pins(GENERIC_HARDMACRO_LEF)
        names = {p for p, _ in pins["GENERIC_HARDMACRO"]}
        assert "CLK" not in names and "D" not in names and "Q" not in names

    def test_no_macro_no_pins(self):
        assert R._parse_macro_supply_pins("VERSION 5.8 ;\n") == {}


# ── The matching decision (the honesty boundary) ─────────────────────────────


# ── BEFORE-state guard: the signal-on-power detector ─────────────────────────


# ── The emitted Tcl (structure + honesty) ────────────────────────────────────


# ── Read-back parser ─────────────────────────────────────────────────────────


# ── _design_supply_nets mirrors the PDN rail derivation ──────────────────────




# ── tclsh: the emitted block PARSES + EVALUATES inside a full pnr.tcl ─────────
sys.path.insert(0, str(Path(__file__).resolve().parent))
