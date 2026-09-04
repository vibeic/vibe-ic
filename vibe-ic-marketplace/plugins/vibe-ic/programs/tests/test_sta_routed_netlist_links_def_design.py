#!/usr/bin/env python3
"""Post-route STA must link the module named by the routed DEF."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path


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
