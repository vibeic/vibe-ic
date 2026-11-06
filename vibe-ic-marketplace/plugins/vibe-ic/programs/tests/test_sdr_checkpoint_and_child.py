"""#2253 — the CHILD deck, and the Python half that adopts an accepted candidate.

The Tcl decision is pinned by `test_postroute_sdr_transaction.py`.  What is
pinned here is the OTHER two halves of the same transaction:

  * the CHILD deck is derived from pnr.tcl ITSELF (never re-emitted from a
    second builder), reads the checkpoint the shipping session wrote, elides
    the work that checkpoint already contains, and STOPS at the end of its own
    SDR stage — so it can publish a candidate and never a shipped artifact;
  * the PYTHON side finishes the post-route tail from an ACCEPTED candidate the
    shipping session was not allowed to read back, and refuses — loudly, with
    `routed.def` still absent — when it cannot.
"""
import shutil
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")

SITE1 = "postroute_drv_repair"
SITE2 = "postroute_drv_reconverge"


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


def _stage_captable(tmp_path: Path) -> str:
    (tmp_path / "pdk" / "libs.ref" / "fix").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pdk" / "libs.tech" / "openlane").mkdir(parents=True,
                                                        exist_ok=True)
    (tmp_path / "pdk" / "libs.tech" / "openlane" /
     "rules.openrcx.fix.nom.magic").write_text("# captable fixture\n")
    return str(tmp_path / "pdk" / "libs.ref" / "fix" / "tech.lef")


def _declared_nom(tech_lef_c: str) -> dict:
    """F13b: the post-route deck takes the ruleset the PDK DECLARES
    (`_openrcx_ruleset_declaration`'s record), never a glob. The declaration
    here names the very file `_stage_captable` wrote."""
    root = tech_lef_c.split("/libs.ref/")[0]
    path = next(str(p) for p in sorted(Path(root, "libs.tech").rglob(
        "rules.openrcx.*.nom.magic")))
    return {"status": "DECLARED", "declaration": ["fixture config.tcl"],
            "corners": {"nom": {"path": path, "pattern": "nom_*",
                                "declared_by": "config.tcl:RCX_RULES"}},
            "detail": ""}


def _full_pnr_tcl(tmp_path: Path) -> str:
    """The COMPLETE pnr.tcl, from its REAL builder, with the fork post-route
    repair probe POSITIVE so both SDR sites are emitted."""
    pdk = _pdk()
    out_dir_c = str(tmp_path / "out")
    (tmp_path / "out").mkdir(exist_ok=True)
    tech_lef_c = _stage_captable(tmp_path)
    plan = R._build_spare_cells_plan(2000, 0.02, (10, 10, 290, 290),
                                     liberty_path="", container="")
    antenna = R._antenna_repair_tcl(pdk)
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
        spef_repair_block=R._post_route_spef_repair_tcl(
            out_dir_c, tech_lef_c, fork_repair_capable=True,
            rcx_declaration=_declared_nom(tech_lef_c)),
        antenna_repair_block=antenna,
        drv_reconverge_block=(
            R._pnr_stage_begin(SITE2) + "\n"
            + 'puts "SDR2_BEGIN"\n'
            + R._v1_8_100_signoff_drv_repair_tcl(
                out_dir_c, "sky130_fd_sc_hd__clkbuf_16", stage=SITE2)
            + 'puts "SDR2_END"\n'
            + R._pnr_stage_end(SITE2) + "\n"),
        post_reconverge_antenna_block=antenna,
        filler_block="",
    )


# ------------------------------------------------------------- the child deck




















# ------------------------------------------------------ the python adopt half












# ---------------------------------------------------------- the disclosure








# -------------------------------- session state the DEF does not carry


_SPARE_PLAN = {"instances": [
    {"name": "spare_inv_0", "cell": "sky130_fd_sc_hd__inv_2", "llx": 0, "lly": 0},
    {"name": "spare_nand_1", "cell": "sky130_fd_sc_hd__nand2_1", "llx": 8, "lly": 0},
    {"name": "spare_noclass_2", "cell": None, "llx": 16, "lly": 0},
]}














# ---------------- R-0915-13: what a DEF restore gets WRONG, both halves








@needs_tclsh
def test_the_relay_never_reaches_supply_wiring(tmp_path):
    """The PG skip is NOT the exception `_drop_protected` lifts.

    DRIVEN, not read: the proc is executed with the dont_touch skip dropped,
    once on a SIGNAL net and once on a POWER net. The signal wire goes; the
    supply wire must not, because a caller that could destroy PG wiring would
    take the straps out of the die it is about to ship. That is the one refusal
    in this filter with no opt-out, and the only honest way to show it is to
    ask for the exception and be refused.
    """
    import subprocess
    stub = (
        'namespace eval odb { proc dbWire_destroy {w} { lappend ::D $w } }\n'
        'set ::D {}\n'
        'proc SIG {m args} {\n'
        '  switch -- $m { getSigType {return SIGNAL} getITerms {return {IT}}\n'
        '                 getWire {return WSIG} }\n'
        '}\n'
        'proc PWR {m args} {\n'
        '  switch -- $m { getSigType {return POWER} getITerms {return {IT}}\n'
        '                 getWire {return WPWR} }\n'
        '}\n'
        'proc IT {m args} { if {$m eq "getInst"} { return INST } }\n'
        'proc INST {m args} { if {$m eq "isDoNotTouch"} { return 1 } }\n')
    drive = ('puts "SIG_FORCED=[_vibeic_spare_safe_clear_net SIG 1]"\n'
             'puts "PWR_FORCED=[_vibeic_spare_safe_clear_net PWR 1]"\n'
             'puts "SIG_DEFAULT=[_vibeic_spare_safe_clear_net SIG]"\n'
             'puts "DESTROYED=$::D"\n')
    s = tmp_path / "pg.tcl"
    s.write_text(stub + R._spare_safe_clear_net_proc_tcl() + drive)
    r = subprocess.run([tclsh, str(s)], text=True, capture_output=True)
    assert r.returncode == 0, r.stderr
    # the exception reaches a protected SIGNAL net ...
    assert "SIG_FORCED=CLEARED" in r.stdout, r.stdout
    # ... and never a supply net, however it is asked
    assert "PWR_FORCED=PG" in r.stdout, r.stdout
    # ... and the default caller is unchanged: still PROTECTED
    assert "SIG_DEFAULT=PROTECTED" in r.stdout, r.stdout
    assert "DESTROYED=WSIG" in r.stdout, r.stdout






# ------- the child clears its own residual before the transaction judges it














# ------------- guides: detailed_route eats them, so each one gets its own
















# ------------------------- R-0915-16: the restore point is the ODB










# --------------------------------------- LEFs after the timing libraries (ORD-2056)
