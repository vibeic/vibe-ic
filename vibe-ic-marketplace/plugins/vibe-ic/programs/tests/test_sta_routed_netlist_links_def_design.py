#!/usr/bin/env python3
"""Post-route STA must link the module named by the routed DEF."""
from __future__ import annotations

import inspect
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


def _project(tmp_path: Path) -> tuple[Path, Path]:
    pnr = R._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True)
    routed = pnr / "logical_core_pnr.v"
    routed.write_text("module package_top; endmodule\n")
    (pnr / "logical_core.def").write_text(
        "VERSION 5.8 ;\nDESIGN package_top ;\nEND DESIGN\n")
    return tmp_path, routed


def _resolver():
    # Keep the negative arm executable: before the helper exists it behaves as
    # the current emitters do (link the logical artefact name).
    return getattr(
        R,
        "_sta_link_top",
        lambda project, logical_top, netlist, routed: logical_top,
    )


def test_routed_sta_links_the_def_owned_physical_top(tmp_path):
    project, routed_netlist = _project(tmp_path)
    assert _resolver()(project, "logical_core", routed_netlist, True) == "package_top"


def test_pre_layout_sta_keeps_the_logical_rtl_top(tmp_path):
    project, _ = _project(tmp_path)
    synth = R._pl.synth_dir(project) / "logical_core_synth.v"
    synth.parent.mkdir(parents=True)
    synth.write_text("module logical_core; endmodule\n")
    assert _resolver()(project, "logical_core", synth, False) == "logical_core"


def test_every_post_route_sta_emitter_consumes_the_shared_resolution():
    for emitter in (
        R._emit_spef_sta,
        R._emit_multi_corner_sta,
        R._emit_corner_spef_sta,
        R._emit_mcorner_ocv_sta,
    ):
        assert "_sta_link_top" in inspect.getsource(emitter), emitter.__name__


def test_sta_adds_only_the_io_liberty_matching_the_active_pvt(tmp_path):
    rec = tmp_path / "reports/phase3/io_pad_chip_top.json"
    rec.parent.mkdir(parents=True)
    rec.write_text(
        '{"io_library_liberty": ['
        '"/pdk/io/lib/io__tt_025C_5v00.lib", '
        '"/pdk/io/lib/io__ss_125C_4v50.lib"]}\n')

    class Pdk:
        macro_libs = ["/project/hardmacro.lib"]

    helper = getattr(R, "_sta_extra_liberties", lambda project, pdk, ref: list(pdk.macro_libs))
    got = helper(tmp_path, Pdk(), "/pdk/sc/lib/sc__ss_125C_4v50.lib")
    assert got == ["/project/hardmacro.lib", "/pdk/io/lib/io__ss_125C_4v50.lib"]


def test_every_post_route_sta_emitter_loads_pvt_matched_io_timing():
    for emitter in (
        R._emit_spef_sta,
        R._emit_multi_corner_sta,
        R._emit_corner_spef_sta,
        R._emit_mcorner_ocv_sta,
    ):
        assert "_sta_extra_liberties" in inspect.getsource(emitter), emitter.__name__


def test_post_route_power_uses_physical_top_and_pvt_matched_io_timing():
    source = inspect.getsource(R._emit_power_report)
    assert "_sta_link_top" in source
    assert "_sta_extra_liberties" in source
    assert "link_design {link_top}" in source


def test_pnr_loads_each_io_view_only_in_its_exact_process_scene(
        tmp_path, monkeypatch):
    rec = tmp_path / "reports/phase3/io_pad_chip_top.json"
    rec.parent.mkdir(parents=True)
    rec.write_text(
        '{"io_library_liberty": ['
        '"/pdk/io/io__ff_n40C_5v50.lib", '
        '"/pdk/io/io__ss_125C_4v50.lib", '
        '"/pdk/io/io__tt_025C_5v00.lib"]}\n')

    class Pdk:
        liberty = "/pdk/sc/sc__tt_025C_5v00.lib"
        macro_libs = ["/project/hardmacro.lib"]

    corners = {
        "SS": "/pdk/sc/sc__ss_125C_4v50.lib",
        "TT": "/pdk/sc/sc__tt_025C_5v00.lib",
        "FF": "/pdk/sc/sc__ff_n40C_5v50.lib",
    }
    monkeypatch.setattr(R, "_resolve_signoff_corner_libs",
                        lambda project, pdk, container: corners)
    got = R._pnr_io_liberties_tcl(
        tmp_path, Pdk(), "container",
        "define_corners ss tt ff\nread_liberty -corner ss slow.lib")
    assert got.splitlines() == [
        "read_liberty -corner ss /pdk/io/io__ss_125C_4v50.lib",
        "read_liberty -corner tt /pdk/io/io__tt_025C_5v00.lib",
        "read_liberty -corner ff /pdk/io/io__ff_n40C_5v50.lib",
    ]


def test_pnr_io_view_selector_does_not_cross_pvt_or_duplicate_macro_lib(
        tmp_path):
    rec = tmp_path / "reports/phase3/io_pad_chip_top.json"
    rec.parent.mkdir(parents=True)
    rec.write_text(
        '{"io_library_liberty": ['
        '"/project/hardmacro.lib", '
        '"/pdk/io/io__ss_125C_4v50.lib"]}\n')

    class Pdk:
        liberty = "/pdk/sc/sc__tt_025C_5v00.lib"
        macro_libs = ["/project/hardmacro.lib"]

    assert R._pnr_io_liberties_tcl(tmp_path, Pdk(), "container", None) == ""


def test_signoff_repair_loads_only_the_selected_pvt_io_view_before_def(
        tmp_path):
    rec = tmp_path / "reports/phase3/io_pad_chip_top.json"
    rec.parent.mkdir(parents=True)
    rec.write_text(
        '{"io_library_liberty": ['
        '"/pdk/io/io__tt_025C_5v00.lib", '
        '"/pdk/io/io__ss_125C_4v50.lib"]}\n')

    class Pdk:
        macro_libs = []

    selected = R._sta_extra_liberties(
        tmp_path, Pdk(), "/pdk/sc/sc__ss_125C_4v50.lib")
    tcl = R._ship_signoff_spef_repair_tcl(
        top="chip_top", tech_lef_c="/pdk/tech.lef",
        cell_lef_c="/pdk/cells.lef",
        ss_liberty_c="/pdk/sc/sc__ss_125C_4v50.lib",
        pnr_dir_c="/project/pnr", max_captable_c="/pdk/max.rules",
        metal_prefix="Metal", thread_count=1,
        extra_liberties_c=selected)
    assert "read_liberty /pdk/io/io__ss_125C_4v50.lib" in tcl
    assert "read_liberty /pdk/io/io__tt_025C_5v00.lib" not in tcl
    assert tcl.index("read_liberty /pdk/io/io__ss_125C_4v50.lib") < tcl.index(
        "read_def /project/pnr/routed.def")


def test_signoff_repair_step_consumes_the_shared_exact_pvt_selector():
    source = inspect.getsource(R.step_signoff_spef_repair)
    assert "_sta_extra_liberties(project, pdk, ss_lib)" in source
    assert "extra_liberties_c=extra_liberties_c" in source
    assert "fanout_root_buffer_cell=pdk.clk_buf or pdk.clk_buf_root" in source


def test_base_pnr_signoff_domain_owns_residual_fanout_repair_before_reroute():
    step_source = inspect.getsource(R.step_pnr)
    assert "fanout_root_buffer_cell=_fanout_root_buffer_cell" in step_source
    sdr_source = inspect.getsource(R._v1_8_100_signoff_drv_repair_tcl)
    assert "sdr_fanout_root_candidates.rpt" in sdr_source
    assert "repair_after_insert=False" in sdr_source
    tcl = R._v1_8_100_signoff_drv_repair_tcl("/pnr", "pdk_buf")
    root = tcl.index("sdr_fanout_root_candidates.rpt")
    assert root < tcl.index(
        "if {[catch {repair_timing -setup} _sdr_rt]}", root)


def test_signoff_repair_extra_liberty_empty_and_duplicate_are_noops():
    base = R._ship_signoff_spef_repair_tcl(
        "top", "/tech.lef", "/cells.lef", "/ss.lib", "/pnr",
        "/max.rules", "Metal", 1)
    empty = R._ship_signoff_spef_repair_tcl(
        "top", "/tech.lef", "/cells.lef", "/ss.lib", "/pnr",
        "/max.rules", "Metal", 1, extra_liberties_c=[])
    duplicate = R._ship_signoff_spef_repair_tcl(
        "top", "/tech.lef", "/cells.lef", "/ss.lib", "/pnr",
        "/max.rules", "Metal", 1, extra_liberties_c=["/ss.lib"])
    assert base == empty == duplicate


def test_signoff_repair_targets_only_tool_reported_fanout_violators():
    tcl = R._ship_max_fanout_root_repair_tcl("pdk_derived_clkbuf")
    assert "report_check_types -max_fanout -violators" in tcl
    assert "insert_buffer -net" in tcl
    assert "-buffer_cell pdk_derived_clkbuf" in tcl
    assert "SHIP_FANOUT_ROOT_LOAD_CENTROID" in tcl
    assert "{*}$_ship_fo_loc_args" in tcl
    assert "set_max_fanout" not in tcl  # the actuator must not change the gate


def test_signoff_domain_fanout_root_uses_enclosing_repair_and_unique_names():
    tcl = R._v1_8_100_signoff_drv_repair_tcl("/pnr", "pdk_buf")
    root = tcl.index("sdr_fanout_root_candidates.rpt")
    reroute = tcl.index('if {[catch {global_route} _sdr_gr]}', root)
    assert "repair_after_insert" not in tcl
    assert "_ship_fanout_root_serial" in tcl[root:reroute]
    assert "SHIP_FANOUT_ROOT_RD_NONFATAL" not in tcl[root:reroute]
    assert "insert_buffer -net" in tcl[root:reroute]


@pytest.mark.skipif(shutil.which("tclsh") is None, reason="tclsh unavailable")
def test_fanout_root_helper_executes_only_red_rows_and_noops_without_authority(
        tmp_path):
    report = tmp_path / "fanout.rpt"
    helper = R._ship_max_fanout_root_repair_tcl("pdk_buf", str(report))
    no_authority = R._ship_max_fanout_root_repair_tcl(None)
    script = tmp_path / "fanout_root.tcl"
    script.write_text(
        "set ::fixture {max fanout\nPin Limit Fanout Slack\n"
        "pad_a/Y 1 2 (VIOLATED)\npad_green/Y 4 2 2\n"
        "pad_b/Y 1 3 -2 (VIOLATED)}\n"
        "set ::calls {}\n"
        "proc report_check_types {args} { set idx [lsearch -exact $args >]; "
        "set fp [open [lindex $args [expr {$idx + 1}]] w]; "
        "puts -nonewline $fp $::fixture; close $fp; return {}}\n"
        "namespace eval ord {}\n"
        "proc ord::get_db_block {} { return db_block }\n"
        "proc db_block {method args} { if {$method eq \"getDefUnits\"} "
        "{ return 1000 }; error \"bad block method $method\" }\n"
        "proc get_pins {args} { return [lindex $args end] }\n"
        "proc get_nets {args} { return net_fixture }\n"
        "proc net_fixture {method args} { if {$method eq \"getITerms\"} "
        "{ return {driver load_a load_b} }; error \"bad net method $method\" }\n"
        "proc driver {method args} { if {$method eq \"getMTerm\"} "
        "{ return driver_mterm }; error \"bad driver method $method\" }\n"
        "proc driver_mterm {method args} { if {$method eq \"getIoType\"} "
        "{ return OUTPUT }; error \"bad driver mterm method $method\" }\n"
        "proc load_a {method args} { if {$method eq \"getMTerm\"} "
        "{ return load_mterm }; if {$method eq \"getBBox\"} { return box_a }; "
        "error \"bad load_a method $method\" }\n"
        "proc load_b {method args} { if {$method eq \"getMTerm\"} "
        "{ return load_mterm }; if {$method eq \"getBBox\"} { return box_b }; "
        "error \"bad load_b method $method\" }\n"
        "proc load_mterm {method args} { if {$method eq \"getIoType\"} "
        "{ return INPUT }; error \"bad load mterm method $method\" }\n"
        "proc box_a {method args} { set v [dict create xMin 1000 xMax 3000 "
        "yMin 2000 yMax 4000]; return [dict get $v $method] }\n"
        "proc box_b {method args} { set v [dict create xMin 3000 xMax 5000 "
        "yMin 4000 yMax 6000]; return [dict get $v $method] }\n"
        "proc insert_buffer {args} { lappend ::calls $args; return buf }\n"
        "proc repair_design {args} { return {}}\n"
        "proc repair_timing {args} { return {}}\n"
        "proc detailed_placement {args} { return {}}\n"
        "set _ship_rt_failed 0\n"
        + helper
        + "puts ROOT_CALLS=[llength $::calls]\n"
        + "puts ROOT_ARGS=$::calls\n"
        + "puts ROOT_INSERTED=$_ship_fanout_root_inserted\n"
        + no_authority
        + "puts NOAUTH_INSERTED=$_ship_fanout_root_inserted\n")
    result = subprocess.run(
        [shutil.which("tclsh"), str(script)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert "ROOT_CALLS=2" in result.stdout
    assert "ROOT_INSERTED=2" in result.stdout
    assert "NOAUTH_INSERTED=0" in result.stdout
    assert result.stdout.count(
        "SHIP_FANOUT_ROOT_LOAD_CENTROID: pin=") == 2
    assert result.stdout.count("-location {3.0 4.0}") == 2
