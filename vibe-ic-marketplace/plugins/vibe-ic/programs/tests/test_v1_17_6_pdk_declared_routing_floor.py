#!/usr/bin/env python3
"""The PDK states where signals may route and the flow never read it.

`gf180mcuD/libs.tech/librelane/config.tcl`, verbatim:

    set ::env(RT_MIN_LAYER) "Metal2" ;# stdcells heavily use Metal1 - setting
                                      # it to Metal1 will cause congestions
    set ::env(RT_MAX_LAYER) "Metal5"
    set ::env(DRT_MIN_LAYER) "Metal1"

Two floors: GLOBAL routing starts at Metal2 (which is what `set_routing_layers`
sets), DETAILED routing may still descend to Metal1 for pin access.

`_v1_8_100_routing_layer_range` derives its own floor from the cell LEF's
pin-layer shares and then steps back one layer, so a library with exactly ONE
pin-dominated layer yields the BOTTOM routing layer. gf180mcu_fd_sc_mcu7t5v0
is such a library, and the flow emitted `-signal Metal1-Metal5`.

MEASURED, subservient x gf180mcuD, 2026-09-04, plugin v1.17.5 / image 0.3.41:
`ROUTE_NOT_CONVERGED` at die 1512x1512um after a 4-rung ladder, residual series
[3, 2, 1, 1], and every rung's residual is the same shape -- one `Metal
Spacing` on Metal1 between a signal net and `net:VDD`, marker exactly
0.150 x 0.000 um against Metal1's own `SPACING 0.230`, on four DIFFERENT nets.
The signal side is the router's own Metal1 patch; the VDD side is a standard
cell's fixed rail. Signal metal on the rail layer is what makes it.

PRECEDENCE PINNED HERE: design declaration > PDK declaration > derivation.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

_PDK_CFG = (
    '# a PDK flow config, in the shipped grammar\n'
    'set ::env(STD_CELL_LIBRARY) "lib_a"\n'
    'set ::env(RT_MIN_LAYER) "Metal2" ;# stdcells heavily use Metal1\n'
    'set ::env(RT_MAX_LAYER) "Metal5"\n'
    'set ::env(DRT_MIN_LAYER) "Metal1"\n'
    'set ::env(RT_CLOCK_MIN_LAYER) "Metal3"\n'
)
# Three routing layers is the minimum the range derivation accepts.
_TLEF = "".join(
    f"LAYER Metal{i}\n    TYPE ROUTING ;\n    MINWIDTH 0.230 ;\n"
    f"END Metal{i}\n" for i in (1, 2, 3, 4, 5))
# One pin-dominated layer only -- the shape that makes the derivation return
# the bottom routing layer.
_CLEF = "".join(
    f"MACRO c{i}\n  PIN A\n    PORT\n      LAYER Metal1 ;\n"
    f"    END\n  END A\nEND c{i}\n" for i in range(20))


class _Pdk:
    name = "somepdk"
    tech_lef = "/c/tech.tlef"
    cell_lef = "/c/cells.lef"
    metal_prefix = "Metal"


def _install(monkeypatch, cfg_text, tlef=_TLEF, clef=_CLEF):
    monkeypatch.setattr(R, "_pdk_dir_of", lambda pdk: "/c/pdk")

    def _read(path, container=""):
        p = str(path)
        if p.endswith("tech.tlef"):
            return tlef
        if p.endswith("cells.lef"):
            return clef
        if p.endswith("librelane/config.tcl"):
            return cfg_text
        return None

    monkeypatch.setattr(R, "_v1_6_604_read_text_or_container_cat", _read)


def test_the_pdks_own_config_is_read(monkeypatch):
    _install(monkeypatch, _PDK_CFG)
    got = R._pdk_declared_routing_layers(_Pdk(), "ctr")
    assert got["route_min_layer"] == "Metal2"
    assert got["route_max_layer"] == "Metal5"
    assert got["route_clock_min_layer"] == "Metal3"
    assert got["source"].endswith("libs.tech/librelane/config.tcl")


def test_a_trailing_tcl_comment_is_not_part_of_the_value(monkeypatch):
    """`set ::env(K) Metal2 ;# why` -- an unquoted value with a comment after
    it must not become `Metal2 ;# why`, which matches no layer name."""
    _install(monkeypatch, "set ::env(RT_MIN_LAYER) Metal2 ;# a reason\n")
    assert R._pdk_declared_routing_layers(_Pdk(), "ctr")["route_min_layer"] \
        == "Metal2"


def test_a_pdk_that_declares_nothing_yields_nothing(monkeypatch):
    _install(monkeypatch, 'set ::env(STD_CELL_LIBRARY) "lib_a"\n')
    assert R._pdk_declared_routing_layers(_Pdk(), "ctr") == {}


def test_no_config_file_at_all_yields_nothing(monkeypatch):
    _install(monkeypatch, None)
    assert R._pdk_declared_routing_layers(_Pdk(), "ctr") == {}


def test_the_derivation_alone_returns_the_rail_layer(monkeypatch, tmp_path):
    """NEGATIVE CONTROL / the defect itself. With ONE pin-dominated layer the
    cell-LEF derivation steps back onto the bottom routing layer, which is the
    layer the standard cells' power rails occupy."""
    _install(monkeypatch, None)
    monkeypatch.setattr(R, "_active_std_cell_library", lambda *a, **k: "lib_a")
    rng = R._v1_8_100_routing_layer_range(_Pdk(), tmp_path, "ctr")
    assert rng is not None
    assert rng[0] == "Metal1"


def test_the_pdk_declaration_lifts_the_signal_floor(monkeypatch, tmp_path):
    _install(monkeypatch, _PDK_CFG)
    monkeypatch.setattr(R, "_active_std_cell_library", lambda *a, **k: "lib_a")
    sig, clk, ceil, why = R._v1_8_100_routing_layer_range(
        _Pdk(), tmp_path, "ctr")
    assert sig == "Metal2"
    assert clk == "Metal3"
    assert ceil == "Metal5"
    assert "PDK-declared" in why and "librelane/config.tcl" in why


def test_the_design_declaration_still_outranks_the_pdk(monkeypatch, tmp_path):
    """A design that states its own floor is design INPUT and keeps winning."""
    _install(monkeypatch, _PDK_CFG)
    monkeypatch.setattr(R, "_active_std_cell_library", lambda *a, **k: "lib_a")
    import floorplan_contract as fpc
    monkeypatch.setattr(
        fpc, "declared_drv_limits",
        lambda *a, **k: {"route_min_layer": "Metal3",
                         "route_min_layer_source": "design/config.json"})
    sig, _clk, _ceil, why = R._v1_8_100_routing_layer_range(
        _Pdk(), tmp_path, "ctr")
    assert sig == "Metal3"
    assert "design-declared" in why
