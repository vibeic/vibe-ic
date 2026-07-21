#!/usr/bin/env python3
"""pdk_local hard-macro <-> target-PDK LAYER compatibility guard.

Found by the PDK-portability convergence cell (2026-07-22): a design that
carries its own hard macro under ``input/pdk_local/<vendor>/`` carries ONE
abstract, cut for ONE PDK's layer stack. LEF layer names are PDK-PRIVATE, so
pointing that design at a different PDK makes every pin shape land on a layer
the target technology never declares.

OpenROAD's LEF reader does NOT fail on that. It prints

    [WARNING ODB-0176] error: undefined layer (<name>) referenced

once per shape, DROPS the shape, and still reports
``LEF file: ..., created N library cells``. The macro loads with the correct
OUTLINE and ZERO pin geometry: placement, CTS, PDN and GDS all succeed while
every macro pin is physically unroutable. The run looks closed and is void —
the same "tool reports success while silently not doing the thing" class as
the silent wrong-PDK fallback guard next to it.

Guard: refuse, naming the macro and the exact undeclared layers. It never
renames or remaps a layer — remapping would silently re-cut another PDK's
abstract onto this stack at a pitch it was never drawn for.

chip-AGNOSTIC: the declared-layer set comes from whatever tech LEF the target
PDK resolved to; the guard holds no chip, vendor or PDK literal. Both a
positive (compatible macro must still pass) and a negative (incompatible
macro must be caught) proof are present, per the §4.05 no-leak requirement.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as p3  # noqa: E402


TECH_LEF = """\
VERSION 5.7 ;
LAYER LayerA1
    TYPE ROUTING ;
END LayerA1
LAYER ViaA1
    TYPE CUT ;
END ViaA1
LAYER LayerA2
    TYPE ROUTING ;
END LayerA2
"""


def _macro_lef(layer: str) -> str:
    return f"""\
VERSION 5.7 ;
MACRO some_hard_macro
  CLASS BLOCK ;
  SIZE 100.000 BY 200.000 ;
  PIN d0
    DIRECTION INPUT ;
    PORT
      LAYER {layer} ;
      RECT 0.000 1.000 0.070 1.070 ;
    END
  END d0
  OBS
    LAYER {layer} ;
    RECT 0.000 0.000 100.000 200.000 ;
  END
END some_hard_macro
"""


@pytest.fixture()
def tech(tmp_path: Path) -> Path:
    p = tmp_path / "target.tlef"
    p.write_text(TECH_LEF)
    return p


def test_layer_parsers_separate_declaration_from_reference(tech: Path):
    """`LAYER x` (no semicolon) declares; `LAYER x ;` references."""
    declared = p3._lef_declared_layers(tech.read_text())
    assert declared == {"LayerA1", "ViaA1", "LayerA2"}
    referenced = p3._lef_referenced_layers(_macro_lef("LayerA1"))
    assert referenced == {"LayerA1"}


def test_negative_incompatible_macro_is_refused(tmp_path: Path, tech: Path):
    """A macro cut for another stack must be REFUSED, naming the layer."""
    mlef = tmp_path / "foreign_macro.lef"
    mlef.write_text(_macro_lef("someOtherStackM3"))
    msg = p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, [str(mlef)])
    assert msg is not None
    assert "REFUSED" in msg
    assert "someOtherStackM3" in msg          # names the offending layer
    assert str(mlef) in msg                   # names the offending macro
    assert "target_pdk" in msg
    # It must explain the silent-void mechanism, not just fail.
    assert "ODB-0176" in msg


def test_positive_compatible_macro_still_passes(tmp_path: Path, tech: Path):
    """The overwhelmingly common case — macro matches the target stack."""
    mlef = tmp_path / "native_macro.lef"
    mlef.write_text(_macro_lef("LayerA1"))
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, [str(mlef)]) is None


def test_positive_no_macros_is_a_noop(tech: Path):
    """A design with no pdk_local macros is untouched."""
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, []) is None
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, None) is None


def test_cell_lef_may_also_declare_layers(tmp_path: Path, tech: Path):
    """Libraries that declare a layer in the CELL LEF must not be refused."""
    cell = tmp_path / "cells.lef"
    cell.write_text("VERSION 5.7 ;\nLAYER LayerA9\n    TYPE ROUTING ;\n"
                    "END LayerA9\n")
    mlef = tmp_path / "m.lef"
    mlef.write_text(_macro_lef("LayerA9"))
    # Without the cell LEF the layer is unknown -> refused ...
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, [str(mlef)]) is not None
    # ... with it, the layer is declared -> compatible.
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), str(cell), [str(mlef)]) is None


def test_unreadable_tech_lef_never_fabricates_a_refusal(tmp_path: Path):
    """Fail-safe toward NOT-refusing: no declared-layer evidence, no verdict.

    A refusal asserted from an unreadable tech LEF would block every run on
    any host where the PDK lives somewhere this process cannot read.
    """
    mlef = tmp_path / "m.lef"
    mlef.write_text(_macro_lef("anything"))
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tmp_path / "missing.tlef"), None,
        [str(mlef)]) is None


def test_macro_with_no_geometry_is_not_refused(tmp_path: Path, tech: Path):
    """A pure-outline abstract (no PORT/OBS layers) references nothing."""
    mlef = tmp_path / "outline_only.lef"
    mlef.write_text("VERSION 5.7 ;\nMACRO m\n  CLASS BLOCK ;\n"
                    "  SIZE 10.000 BY 10.000 ;\nEND m\n")
    assert p3.macro_lef_layer_compat_guard(
        "target_pdk", str(tech), None, [str(mlef)]) is None
