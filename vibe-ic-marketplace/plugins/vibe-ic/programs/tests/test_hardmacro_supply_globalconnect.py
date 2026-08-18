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
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")


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
class TestMacroSupplyGcPlan:
    def test_matching_pins_connect_norail_pin_reported(self):
        connect, unconnected = R._macro_supply_gc_plan(
            [GENERIC_HARDMACRO_LEF], POWER_NETS, GROUND_NETS)
        by_pin = {c["pin"]: c for c in connect}
        assert set(by_pin) == {"VPWR", "VGND"}
        assert by_pin["VPWR"] == {"master": "GENERIC_HARDMACRO",
                                  "pin": "VPWR", "use": "POWER",
                                  "rail": "VPWR"}
        assert by_pin["VGND"]["rail"] == "VGND"
        assert by_pin["VGND"]["use"] == "GROUND"
        # VPROG has no matching rail → reported, NEVER connected/fabricated.
        assert [u["pin"] for u in unconnected] == ["VPROG"]
        assert unconnected[0]["use"] == "POWER"
        assert "VPROG" not in by_pin

    def test_no_rail_at_all_reports_everything_unfabricated(self):
        # A design that declares NO supply nets must connect NOTHING (never
        # invent a rail) and report every PG pin honestly.
        connect, unconnected = R._macro_supply_gc_plan(
            [GENERIC_HARDMACRO_LEF], set(), set())
        assert connect == []
        assert {u["pin"] for u in unconnected} == {"VPWR", "VGND", "VPROG"}

    def test_dedup_across_multiple_lefs(self):
        connect, unconnected = R._macro_supply_gc_plan(
            [GENERIC_HARDMACRO_LEF, GENERIC_HARDMACRO_LEF],
            POWER_NETS, GROUND_NETS)
        assert len(connect) == 2
        assert len(unconnected) == 1


# ── BEFORE-state guard: the signal-on-power detector ─────────────────────────
class TestSignalOnPowerGuard:
    def test_constant_ties_on_supply_pins_are_flagged(self):
        findings = R._detect_macro_supply_signal_ties(
            GENERIC_NETLIST, [GENERIC_HARDMACRO_LEF], POWER_NETS, GROUND_NETS)
        flagged = {(f["pin"], f["conn"]) for f in findings}
        # VPWR tied to a constant (1'b1) and VGND to 1'b0 — the exact defect:
        # a signal net on a POWER/GROUND terminal that DRT would refuse.
        assert ("VPWR", "1'b1") in flagged
        assert ("VGND", "1'b0") in flagged

    def test_clean_binding_is_not_flagged(self):
        # If the netlist already bound the pins to the rails, no defect.
        clean = GENERIC_NETLIST.replace(".VPWR(1'b1)", ".VPWR(VPWR)").replace(
            ".VGND(1'b0)", ".VGND(VGND)")
        findings = R._detect_macro_supply_signal_ties(
            clean, [GENERIC_HARDMACRO_LEF], POWER_NETS, GROUND_NETS)
        pins = {f["pin"] for f in findings}
        assert "VPWR" not in pins and "VGND" not in pins


# ── The emitted Tcl (structure + honesty) ────────────────────────────────────
class TestBuildTcl:
    def _tcl(self):
        connect, unconnected = R._macro_supply_gc_plan(
            [GENERIC_HARDMACRO_LEF], POWER_NETS, GROUND_NETS)
        return R._build_hardmacro_supply_gc_tcl(connect, unconnected)

    def test_binds_matching_pins_with_inst_and_pin_pattern(self):
        tcl = self._tcl()
        assert ('add_global_connection -net VPWR -inst_pattern $_hm_re '
                '-pin_pattern "^VPWR\\$" -power') in tcl
        assert ('add_global_connection -net VGND -inst_pattern $_hm_re '
                '-pin_pattern "^VGND\\$" -ground') in tcl
        assert "global_connect" in tcl

    def test_norail_pin_never_gets_add_global_connection(self):
        tcl = self._tcl()
        # The honesty invariant: VPROG must NEVER be handed a rail.
        for line in tcl.splitlines():
            if "add_global_connection" in line:
                assert "VPROG" not in line

    def test_norail_pin_is_reported(self):
        tcl = self._tcl()
        assert ("HARDMACRO_SUPPLY_UNCONNECTED: $_hm_in/VPROG (USE POWER, "
                "no matching supply rail in design)") in tcl

    def test_empty_plan_emits_nothing(self):
        # A design with no hard-macro PG pins produces a BYTE-IDENTICAL flow.
        assert R._build_hardmacro_supply_gc_tcl([], []) == ""


# ── Read-back parser ─────────────────────────────────────────────────────────
class TestReadBack:
    def test_parses_counts(self):
        log = ("...\nHARDMACRO_SUPPLY_GC: bound=2\n"
               "HARDMACRO_SUPPLY_UNCONNECTED: u_macro/VPROG (USE POWER, ...)\n"
               "HARDMACRO_SUPPLY_UNCONNECTED_TOTAL: 1\n...")
        assert R._parse_hardmacro_supply_gc(log) == (2, 1)

    def test_absent_is_none_not_zero(self):
        assert R._parse_hardmacro_supply_gc("no such line here") is None


# ── _design_supply_nets mirrors the PDN rail derivation ──────────────────────
class _DuckPdk:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class TestDesignSupplyNets:
    def test_sky130_style_is_vpwr_vgnd(self):
        pdk = _DuckPdk(tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
                       metal_prefix="met", cell_lef=None)
        assert R._design_supply_nets(pdk) == ({"VPWR"}, {"VGND"})

    def test_no_cell_lef_no_rails(self):
        pdk = _DuckPdk(tapcell_master=None, metal_prefix="met", cell_lef=None)
        assert R._design_supply_nets(pdk) == (set(), set())


# ── tclsh: the emitted block PARSES + EVALUATES inside a full pnr.tcl ─────────
_STUB = 'proc unknown {args} { return "" }\n'


def _run_tclsh(script_path: Path):
    return subprocess.run([tclsh, str(script_path)],
                          capture_output=True, text=True, timeout=60)


def _pdk() -> "R.PdkConfig":
    return R.PdkConfig(
        name="fixture_pdk",
        liberty="/pdk/lib.lib", tech_lef="/pdk/tech.lef",
        cell_lef="/pdk/cells.lef", cell_gds=None,
        site="unithd", drc_deck=None, metal_prefix="met",
        tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
        antenna_diode_cell="sky130_fd_sc_hd__diode_2",
        pnr_exclude_cell_file="/pdk/drc_exclude.cells",
    )


def _full_pnr_tcl(tmp_path: Path, hm_block: str) -> str:
    pdk = _pdk()
    out_dir_c = str(tmp_path / "out")
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / "pdk" / "libs.ref" / "fix").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pdk" / "libs.tech" / "openlane").mkdir(
        parents=True, exist_ok=True)
    (tmp_path / "pdk" / "libs.tech" / "openlane" /
     "rules.openrcx.fix.nom.magic").write_text("# captable fixture\n")
    tech_lef_c = str(tmp_path / "pdk" / "libs.ref" / "fix" / "tech.lef")
    plan = R._build_spare_cells_plan(
        2000, 0.02, (10, 10, 290, 290), liberty_path="", container="")
    return R._build_pnr_tcl_text(
        tech_lef_c=tech_lef_c, cell_lef_c="/pdk/cells.lef",
        macro_lefs_tcl="", liberty_c="/pdk/lib.lib",
        macro_libs_tcl="", netlist_c="/work/netlist.v", top="chip_top",
        sdc_c="/work/chip_top.sdc",
        dont_use_block=R._dont_use_tcl(pdk),
        metal_prefix=pdk.metal_prefix, die_w=300, die_h=300,
        core_pad=10, core_w=280, core_h=280, site=pdk.site,
        out_dir_c=out_dir_c,
        tapcell_block=R._build_tapcell_tcl(pdk),
        pdn_block=R._build_pdn_tcl(pdk),
        util=0.45,
        spare_protection_tcl=R._build_spare_protection_tcl(plan, out_dir_c),
        spare_postfix_tcl=R._build_spare_postfix_tcl(
            plan, tie_lo_cell="sky130_fd_sc_hd__conb_1", tie_lo_pin="LO"),
        clk_buf="sky130_fd_sc_hd__clkbuf_4",
        clk_buf_root="sky130_fd_sc_hd__clkbuf_16",
        routing_constraint_tcl="",
        pg_cleanup_block=R._pg_net_cleanup_tcl(),
        spef_repair_block=R._post_route_spef_repair_tcl(out_dir_c, tech_lef_c),
        antenna_repair_block=R._antenna_repair_tcl(pdk),
        filler_block="",
        hardmacro_supply_gc_block=hm_block,
    )


@needs_tclsh
def test_block_appears_before_routing_and_full_tcl_parses(tmp_path):
    connect, unconnected = R._macro_supply_gc_plan(
        [GENERIC_HARDMACRO_LEF], POWER_NETS, GROUND_NETS)
    hm_block = R._build_hardmacro_supply_gc_tcl(connect, unconnected)
    full = _full_pnr_tcl(tmp_path, hm_block)
    # Positioned BEFORE detailed routing (that is what makes the constant-tie
    # never reach the router).
    assert "hard-macro supply-pin auto global-connect" in full
    assert full.index("hard-macro supply-pin auto global-connect") < \
        full.index("detailed_route")
    script = tmp_path / "pnr.tcl"
    full = full.replace("\nexit\n", "\nputs PNR_TCL_END\n")
    script.write_text(_STUB + full)
    result = _run_tclsh(script)
    assert result.returncode == 0, result.stderr
    assert "PNR_TCL_END" in result.stdout


@needs_tclsh
def test_block_logic_connects_matching_and_reports_norail(tmp_path):
    """Execute the emitted block against a STUBBED OpenROAD DB (one instance of
    the generic macro) and prove: VPWR→power + VGND→ground are bound with an
    exact per-instance -inst_pattern, VPROG is reported as unconnected, and
    VPROG is NEVER handed to add_global_connection (honesty)."""
    connect, unconnected = R._macro_supply_gc_plan(
        [GENERIC_HARDMACRO_LEF], POWER_NETS, GROUND_NETS)
    block = R._build_hardmacro_supply_gc_tcl(connect, unconnected)
    harness = r"""
namespace eval ord {}
proc ord::get_db_block {} { return BLK }
proc BLK {m args} { switch $m { getInsts { return INST } getName {return top} } }
proc INST {m args} { switch $m { getMaster { return MST } getName { return u_macro } } }
proc MST {m args} { switch $m { getName { return GENERIC_HARDMACRO } } }
set ::AGC {}
proc add_global_connection {args} { lappend ::AGC $args }
proc global_connect {} {}
""" + block
    script = tmp_path / "logic.tcl"
    # Emit the captured add_global_connection calls last so we can assert them.
    script.write_text(harness + '\nputs "AGC_DUMP: $::AGC"\n')
    result = _run_tclsh(script)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "HARDMACRO_SUPPLY_GC: bound=2" in out
    assert ("HARDMACRO_SUPPLY_UNCONNECTED: u_macro/VPROG (USE POWER, "
            "no matching supply rail in design)") in out
    assert "HARDMACRO_SUPPLY_UNCONNECTED_TOTAL: 1" in out
    # The two matching pins were bound to their rails with the EXACT instance.
    assert "-net VPWR" in out and "-net VGND" in out
    assert "-inst_pattern {^u_macro$}" in out or "^u_macro$" in out
    assert "-power" in out and "-ground" in out
    # HONESTY: VPROG never reached add_global_connection.
    dump = out.split("AGC_DUMP:", 1)[1]
    assert "VPROG" not in dump
