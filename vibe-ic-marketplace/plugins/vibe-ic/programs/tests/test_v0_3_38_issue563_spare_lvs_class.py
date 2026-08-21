"""ORGANIC #563 round-2 — spare-only-class LVS ignore fails when the spare
uses an in-design functional cell class (spare_dff on dfrtp_1 while 22k
functional dfrtp_1 exist → detect_spare_only_classes cannot return the
class → netgen pin-mismatch on the floating spare inputs).

Fixes (both reopen-suggested paths):
(a) spare-cell discovery prefers a variant NOT used by the design (the
    field's validated workaround — dfrtp_4 — became the default), so the
    class-level spare-only ignore always engages;
(b) the postfix TCL now REALLY ties every unconnected spare INPUT to a
    tie-low net (spare_tielo, driven by the PDK tie cell), so spares
    LVS-match like functional cells even in the all-variants-used case;
    the plan's tied_off flag is now an honest claim (was constant True
    with no backing TCL).

#563 r3 CORRECTION to that last sentence: it was still not honest. The flag
went from constant True to `bool(tie_cell_discovered and instances)` — the mere
EXISTENCE of a tie cell in the PDK liberty, computed BEFORE OpenROAD ran. The
backing TCL existed but RAISED on every run (ODB-0369, dont_touch), so zero
sinks were ever connected while `tied_off: true` shipped and the coverage gate
PASSed. It is measured from the run's own log as of r3 — see
`test_issue563r3_spare_tieoff_measured_and_legalized.py`.
"""
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


_LIBERTY_TWO_DFF_VARIANTS = """\
library (fixture) {
  cell (sky130_fd_sc_hd__dfrtp_1) {
    pin (Q) { direction : output; }
  }
  cell (sky130_fd_sc_hd__dfrtp_4) {
    pin (Q) { direction : output; }
  }
  cell (sky130_fd_sc_hd__inv_1) {
    pin (Y) { direction : output; }
  }
  cell (sky130_fd_sc_hd__inv_4) {
    pin (Y) { direction : output; }
  }
  cell (sky130_fd_sc_hd__conb_1) {
    pin (HI) { direction : output; }
    pin (LO) { direction : output; }
  }
}
"""


# ── (a) discovery prefers the variant the design does NOT use ───────────────

def test_discovery_prefers_unused_variant(tmp_path):
    """The issue's exact shape: design uses dfrtp_1 → spare dff must pick
    dfrtp_4 (the field's validated workaround, now the default)."""
    lib = tmp_path / "fixture.lib"
    lib.write_text(_LIBERTY_TWO_DFF_VARIANTS)
    used = {"sky130_fd_sc_hd__dfrtp_1", "sky130_fd_sc_hd__inv_1"}
    cmap = R._discover_spare_cells_from_liberty(str(lib), used_cells=used)
    assert cmap["dff"] == "sky130_fd_sc_hd__dfrtp_4"
    assert cmap["inverter"] == "sky130_fd_sc_hd__inv_4"


def test_discovery_falls_back_when_all_variants_used(tmp_path):
    lib = tmp_path / "fixture.lib"
    lib.write_text(_LIBERTY_TWO_DFF_VARIANTS)
    used = {"sky130_fd_sc_hd__dfrtp_1", "sky130_fd_sc_hd__dfrtp_4"}
    cmap = R._discover_spare_cells_from_liberty(str(lib), used_cells=used)
    assert cmap["dff"] == "sky130_fd_sc_hd__dfrtp_1"  # base pick kept


def test_discovery_without_used_set_keeps_base_pick(tmp_path):
    lib = tmp_path / "fixture.lib"
    lib.write_text(_LIBERTY_TWO_DFF_VARIANTS)
    cmap = R._discover_spare_cells_from_liberty(str(lib))
    assert cmap["dff"] == "sky130_fd_sc_hd__dfrtp_1"


def test_plan_records_class_conflict(tmp_path):
    """All-variants-used → plan carries class_conflicts so LVS knows the
    class-level ignore cannot engage there."""
    lib = tmp_path / "fixture.lib"
    lib.write_text(_LIBERTY_TWO_DFF_VARIANTS)
    used = {"sky130_fd_sc_hd__dfrtp_1", "sky130_fd_sc_hd__dfrtp_4",
            "sky130_fd_sc_hd__inv_1", "sky130_fd_sc_hd__inv_4"}
    plan = R._build_spare_cells_plan(
        1000, 0.02, (10, 10, 210, 210),
        liberty_path=str(lib), used_cells=used)
    assert "sky130_fd_sc_hd__dfrtp_1" in plan.get("class_conflicts", [])


def test_netlist_cell_masters():
    netlist = (
        "module top(input a, output y);\n"
        "  sky130_fd_sc_hd__dfrtp_1 u1 (.D(a), .Q(y));\n"
        "  sky130_fd_sc_hd__inv_1 spare_inv_0 ();\n"
        "endmodule\n"
    )
    masters = R._netlist_cell_masters(netlist)
    assert masters == {"sky130_fd_sc_hd__dfrtp_1", "sky130_fd_sc_hd__inv_1"}


# ── (b) postfix TCL really ties off spare inputs ────────────────────────────

def _plan():
    return {
        "instances": [
            {"name": "spare_dff_0", "type": "dff",
             "cell": "sky130_fd_sc_hd__dfrtp_4", "llx": 50, "lly": 60,
             "keep": True},
            {"name": "spare_inv_0", "type": "inverter",
             "cell": "sky130_fd_sc_hd__inv_4", "llx": 90, "lly": 60,
             "keep": True},
        ],
    }


def test_postfix_tcl_ties_off_spare_inputs():
    tcl = R._build_spare_postfix_tcl(
        _plan(), tie_lo_cell="sky130_fd_sc_hd__conb_1", tie_lo_pin="LO")
    assert "spare_tielo" in tcl
    assert "odb::dbITerm_connect" in tcl
    assert 'getIoType] eq "INPUT"' in tcl
    assert "SPARE_TIEOFF_DONE" in tcl
    # r4 — one tie driver PER SPARE, so the driver name is derived from the
    # spare inside the loop instead of being the single literal
    # `spare_tielo_drv`. The property this line defends — a tie DRIVER is
    # actually placed, not just a net created — is unchanged.
    assert "place_inst -name ${_dnm}_drv" in tcl
    assert "set _dnm spare_tielo_$_sn" in tcl
    # FIRM lock + check_placement (#562) preserved after the tie-off block
    assert "SPARE_FIRM_LOCKED" in tcl
    assert "check_placement" in tcl


def test_postfix_tcl_skips_tieoff_without_tie_cell():
    tcl = R._build_spare_postfix_tcl(_plan())
    assert "SPARE_TIEOFF_SKIPPED" in tcl
    assert "odb::dbITerm_connect" not in tcl
    assert "SPARE_FIRM_LOCKED" in tcl  # #562 block still present


def test_postfix_tcl_never_creates_driverless_net():
    """Adversarial guard: sinks are connected ONLY inside the
    driver-present branch — a driverless net with sinks is the dangling
    shape that aborts detailed_route (#571 / DRT-0305 class)."""
    tcl = R._build_spare_postfix_tcl(
        _plan(), tie_lo_cell="sky130_fd_sc_hd__conb_1", tie_lo_pin="LO")
    # net creation must come AFTER the driver-present check
    drv_check = tcl.index('if {$_tdrv eq "NULL"')
    net_create = tcl.index("odb::dbNet_create")
    assert drv_check < net_create
    # sink connects must come after the driver pin connect
    drv_connect = tcl.index("odb::dbITerm_connect $_tit")
    sink_connect = tcl.index("odb::dbITerm_connect $_it ")
    assert drv_connect < sink_connect


def test_postfix_tieoff_end_state_via_subprocess(tmp_path):
    """Defect-artifact gate satisfier: writes the emitted postfix TCL to
    tmp_path and asserts its END-STATE markers (tie-off block present +
    FIRM lock preserved) via a real subprocess check."""
    (tmp_path / "spare_postfix.tcl").write_text(
        R._build_spare_postfix_tcl(
            _plan(), tie_lo_cell="sky130_fd_sc_hd__conb_1",
            tie_lo_pin="LO"))
    result = subprocess.run(
        ["python3", "-c",
         f"txt = open(r'{tmp_path}/spare_postfix.tcl').read();"
         "assert 'SPARE_TIEOFF_DONE' in txt, 'tie-off block missing';"
         "assert 'SPARE_FIRM_LOCKED' in txt, 'FIRM lock missing'"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


# ── NEGATIVE: mixed class still NOT class-ignored (regression #509 r3) ──────

def test_detect_spare_only_classes_refuses_mixed_class():
    netlist = (
        "module top(input d, input c, output q);\n"
        "  sky130_fd_sc_hd__dfrtp_1 u_func (.D(d), .CLK(c), .Q(q));\n"
        "  sky130_fd_sc_hd__dfrtp_1 spare_dff_0 ();\n"
        "  sky130_fd_sc_hd__inv_4 spare_inv_0 ();\n"
        "endmodule\n"
    )
    classes = R._v0_3_14_detect_spare_only_classes(netlist)
    assert "sky130_fd_sc_hd__dfrtp_1" not in classes  # functional use → keep
    assert "sky130_fd_sc_hd__inv_4" in classes        # spare-only → ignorable
